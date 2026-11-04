import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from rag_secure import db, generator, ingest, security


class AskRequest(BaseModel):
    question: str
    explain: bool = False


def create_app(cfg, users, col, llm, embedding_function=None):
    """The HTTP service. `llm` is a function (system, user) -> text, so tests can pass a fake.

    A fresh SQLite connection is opened per request, which keeps the threaded server safe."""
    app = FastAPI(title="rag-secure-retrieval", version="0.1.0")
    header = cfg.get("api_key_header", "X-API-Key")

    def current_user(x_api_key: str | None = Header(default=None, alias=header)):
        found = security.user_for_key(users, x_api_key)
        if found is None:  # same reply for a missing key and a wrong key
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        return found

    @app.get("/health")
    def health():
        return {"status": "ok"}

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
        finally:
            conn.close()
        body = {"answer": result["answer"], "sources": result["sources"], "found": result["found"]}
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

    return app


def build_app(cfg):
    """The app wired to the real index and the real Ollama model, from a loaded config."""
    llm = generator.ollama_llm(cfg["model"], cfg["ollama_url"], cfg["temperature"], cfg["seed"], cfg["max_tokens"])
    return create_app(cfg, security.load_users(cfg["users_file"]), ingest.open_collection(cfg["chroma_dir"]), llm)
