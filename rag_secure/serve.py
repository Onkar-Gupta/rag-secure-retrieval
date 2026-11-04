import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rag_secure import db, demo, generator, ingest, security, source


class AskRequest(BaseModel):
    question: str
    explain: bool = False


def create_app(cfg, users, col, llm, embedding_function=None):
    """The HTTP service. `llm` is a function (system, user) -> text, so tests can pass a fake.

    A fresh SQLite connection is opened per request, which keeps the threaded server safe."""
    demo_on = bool(cfg.get("demo_mode", False))
    sessions = demo.Sessions(cfg.get("demo_ttl_seconds", 3600), cfg.get("demo_max_sessions", 20))
    lock = threading.Lock()  # one ingest at a time

    def reindex(embedding=embedding_function):
        return ingest.ingest(cfg["docs_dir"], cfg["chroma_dir"], cfg["db_path"], cfg["chunk_size"],
                             cfg["chunk_overlap"], embedding, uploader="demo", min_page_chars=cfg.get("min_page_chars", 20))

    def end_sessions(groups):
        """Delete these sessions' folders and drop their chunks from the index."""
        if groups:
            with lock:
                demo.remove_folders(cfg["docs_dir"], groups)
                reindex()

    @asynccontextmanager
    async def lifespan(_app):
        if demo_on:
            end_sessions(demo.leftover_groups(cfg["docs_dir"]))  # left by a crash
        yield
        if demo_on:
            end_sessions(sessions.pop_all())

    app = FastAPI(title="rag-secure-retrieval", version="0.1.0", lifespan=lifespan)
    app.state.sessions = sessions
    header = cfg.get("api_key_header", "X-API-Key")

    def current_user(x_api_key: str | None = Header(default=None, alias=header)):
        found = security.user_for_key(users, x_api_key)
        if found is None and demo_on:
            end_sessions(sessions.pop_expired())
            live = sessions.lookup(x_api_key)
            found = (live[0], ["public", live[0]]) if live else None
        if found is None:  # same reply for a missing key and a wrong key
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        return found

    ui_dir = Path(__file__).parent / "ui"
    app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")

    @app.get("/", include_in_schema=False)
    def page():
        return FileResponse(ui_dir / "index.html")

    @app.get("/mode")
    def mode():
        """What the page needs to know before anyone signs in. Nothing about documents or users."""
        return {"demo": demo_on, "demo_users": bool(cfg.get("ui_demo_users", False)),
                "max_files": cfg.get("demo_max_files", 3), "max_file_mb": cfg.get("demo_max_file_mb", 5),
                "ttl": cfg.get("demo_ttl_seconds", 3600)}

    @app.get("/me")
    def me(user: Annotated[tuple, Depends(current_user)]):
        return {"name": user[0], "groups": user[1]}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    def readable(conn, doc_id, groups):
        """True only for an indexed, non-quarantined document in one of the caller's groups."""
        row = conn.execute("SELECT grp, quarantined FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return bool(row) and row[0] in groups and not row[1]

    @app.get("/source")
    def cited_source(chunk: str, user: Annotated[tuple, Depends(current_user)]):
        """The passage a citation points at, in its page. Same 404 for a missing and a forbidden chunk."""
        conn = db.connect(cfg["db_path"])
        try:
            found = source.context(conn, chunk, cfg["chunk_size"], cfg["chunk_overlap"])
            if found is None or not readable(conn, found["doc_id"], user[1]):
                raise HTTPException(status_code=404, detail="not found")
            return {**found, "kind": "pdf" if found["doc_id"].lower().endswith(".pdf") else "text"}
        finally:
            conn.close()

    @app.get("/file")
    def original_file(doc: str, user: Annotated[tuple, Depends(current_user)]):
        """The original file of a document the caller may read. Only indexed documents are served."""
        conn = db.connect(cfg["db_path"])
        try:
            ok = readable(conn, doc, user[1])
        finally:
            conn.close()
        root = Path(cfg["docs_dir"]).resolve()
        path = (root / doc).resolve()
        if not ok or not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        media = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain; charset=utf-8"
        return Response(path.read_bytes(), media_type=media,
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(path.name)}",
                                 "X-Content-Type-Options": "nosniff"})

    @app.post("/ask")
    def ask(req: AskRequest, user: Annotated[tuple, Depends(current_user)]):
        name, groups = user
        try:
            question = security.check_question(req.question, cfg["max_question_chars"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        conn = db.connect(cfg["db_path"])
        try:
            start = time.perf_counter()
            try:
                result, trace = generator.ask_with_trace(question, groups, col, conn, cfg, llm)
            except RuntimeError:
                raise HTTPException(status_code=503, detail="the language model is not available") from None
            db.log_query(conn, name, question, [h["chunk_id"] for h in trace if h["used"]], result["found"],
                         (time.perf_counter() - start) * 1000, keep_text=cfg.get("log_question_text", False))
            provenance = db.provenance(conn, result["sources"])  # built after the model call; model never sees it
        finally:
            conn.close()
        body = {"answer": result["answer"], "sources": result["sources"], "found": result["found"],
                "provenance": provenance}
        if req.explain:
            body["explanation"] = generator.explanation(result, trace, cfg["relevance_threshold"])
        return body

    @app.post("/ingest")
    def run_ingest(user: Annotated[tuple, Depends(current_user)]):
        name, _ = user
        if name not in cfg.get("admin_users", []):
            raise HTTPException(status_code=403, detail="admin only")
        return ingest.ingest(cfg["docs_dir"], cfg["chroma_dir"], cfg["db_path"], cfg["chunk_size"],
                             cfg["chunk_overlap"], embedding_function, uploader=name)

    @app.post("/session")
    def new_session():
        if not demo_on:
            raise HTTPException(status_code=404, detail="demo mode is off")
        end_sessions(sessions.pop_expired())
        try:
            key, group = sessions.create()
        except demo.DemoFull:
            raise HTTPException(status_code=503, detail="the demo is full, try again later") from None
        return {"key": key, "group": group, "groups": ["public", group], "expires_in_seconds": sessions.ttl,
                "max_files": cfg.get("demo_max_files", 3), "max_file_mb": cfg.get("demo_max_file_mb", 5)}

    @app.post("/upload")
    async def upload(request: Request, user: Annotated[tuple, Depends(current_user)],
                     x_filename: str | None = Header(default=None)):
        """Add one file to the caller's own session group. The group is never taken from the request."""
        group = user[0]
        if not demo_on or not sessions.is_session_group(group):
            raise HTTPException(status_code=403, detail="uploads are only for demo sessions")
        name = demo.clean_name(x_filename)
        if isinstance(name, tuple):
            raise HTTPException(status_code=name[0], detail=name[1])
        limit = int(cfg.get("demo_max_file_mb", 5) * 1024 * 1024)
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(status_code=413, detail="file too large")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > limit:
                raise HTTPException(status_code=413, detail="file too large")
        if not body:
            raise HTTPException(status_code=400, detail="empty file")
        _, session = sessions.lookup(request.headers.get(header))
        folder = Path(cfg["docs_dir"]) / group
        with lock:
            if name in session["files"] or len(session["files"]) >= cfg.get("demo_max_files", 3):
                raise HTTPException(status_code=409, detail="file limit reached or name already used")
            folder.mkdir(exist_ok=True)
            (folder / name).write_bytes(body)
            try:
                counts = reindex()
            except Exception:  # noqa: BLE001  any unreadable file is rolled back and refused
                (folder / name).unlink(missing_ok=True)
                reindex()
                raise HTTPException(status_code=422, detail="could not read that file") from None
            session["files"].append(name)
        return {"file": name, "chunks": counts["chunks"], "pages_without_text": counts["pages_without_text"],
                "files_used": len(session["files"]), "max_files": cfg.get("demo_max_files", 3)}

    return app


def build_app(cfg):
    """The app wired to the real index and the real Ollama model, from a loaded config."""
    llm = generator.ollama_llm(cfg["model"], cfg["ollama_url"], cfg["temperature"], cfg["seed"], cfg["max_tokens"])
    return create_app(cfg, security.load_users(cfg["users_file"]), ingest.open_collection(cfg["chroma_dir"]), llm)
