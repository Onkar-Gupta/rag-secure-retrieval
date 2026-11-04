"use strict";
// Ginger answers, Simba guards. Model text is only ever added with textContent, never as HTML.
const $ = (s) => document.querySelector(s);
const POSES = {
  idle: ["ginger", "waiting", "Ready when you are.", "Ask about anything on your shelf."],
  looking: ["ginger", "looking", "Looking through your files.", ""],
  answered: ["ginger", "answering", "Found it.", "The gold tags show where it says so."],
  locked: ["simba", "locked", "Nothing on your shelf says that.",
    "It is either not there or not yours to read, and Ginger will not say which."],
  error: ["ginger", "error", "Something went wrong.", ""],
  welcome: ["simba", "welcome", "Welcome.", "Add a file to your shelf, then ask about it."],
  sniff: ["simba", "looking", "Filing your document.", "Simba is reading it in. Large PDFs take a moment."],
};
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* storage is optional */ } },
  del(k) { try { sessionStorage.removeItem(k); } catch { /* storage is optional */ } },
};
let key = store.get("key");
let mode = { demo: false, demo_users: false, max_files: 3, max_file_mb: 5, ttl: 3600 };
let me = null;
const files = [];

function stage(name, sub, head) {
  const [dog, pose, say, subtitle] = POSES[name];
  const img = $("#mascot");
  const next = `/ui/img/${dog}_${pose}.png`;
  if (!img.src.endsWith(next)) {
    img.classList.add("swap");
    setTimeout(() => { img.src = next; img.classList.remove("swap"); }, 120);
  }
  img.alt = `${dog === "ginger" ? "Ginger" : "Simba"}, ${pose}`;
  $("#say").textContent = head || say;
  $("#sub").textContent = sub === undefined ? subtitle : sub;
  const card = $(".stage");
  card.classList.toggle("busy", name === "looking" || name === "sniff");
  for (const el of [$("#say"), $("#sub")]) { el.classList.remove("fade"); void el.offsetWidth; el.classList.add("fade"); }
}

async function call(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (key) headers["X-API-Key"] = key;
  const res = await fetch(path, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  return { status: res.status, body };
}

const WORDS = {
  401: "Your session has ended. Start a new one.",
  400: "Use a plain file name: letters, digits, spaces, dots, dashes or brackets.",
  409: () => `You can add ${mode.max_files} files per session, and each name once.`,
  413: () => `That file is over ${mode.max_file_mb} MB.`,
  415: "Use a PDF, Markdown or text file.",
  422: "That file or question could not be read.",
  503: "The model is not running. Start Ollama, then ask again.",
};
const say = (status) => (typeof WORDS[status] === "function" ? WORDS[status]() : WORDS[status]);

function showStart(message) {
  $("#boot").hidden = true;
  $("#app").hidden = true;
  $("#start").hidden = false;
  $("#start-title").textContent = mode.demo ? "Bring a file, then ask about it" : "Use your API key";
  $("#start-text").textContent = mode.demo
    ? `Add a PDF to a private shelf and ask Ginger about it. Only you can read what you add, and the shelf clears itself after ${Math.round(mode.ttl / 60)} minutes.`
    : "Ginger reads only the files your key allows.";
  $("#start-demo").hidden = !mode.demo;
  $("#start-key").hidden = mode.demo;
  $("#demo-users").hidden = !mode.demo_users;
  const err = $("#start-error");
  err.hidden = !message;
  err.textContent = message || "";
}

function groupName(g) { return g.startsWith("demo-session-") ? "your uploads" : g; }

async function enter() {
  const r = await call("/me");
  if (r.status !== 200) { key = null; store.del("key"); showStart(r.status === 401 ? say(401) : "Could not reach the service."); return; }
  me = r.body;
  $("#boot").hidden = true;
  $("#start").hidden = true;
  $("#app").hidden = false;
  $("#access").textContent = `On your shelf: ${me.groups.map(groupName).join(", ")}.`;
  const own = me.groups.some((g) => g.startsWith("demo-session-"));
  $("#upload").hidden = !(mode.demo && own);
  $("#over").hidden = !own;
  $("#limits").textContent = `PDF, Markdown or text, up to ${mode.max_file_mb} MB. ${mode.max_files} files per session.`;
  stage(own && !files.length ? "welcome" : "idle");
  tick();
}

function tick() {
  const end = Number(store.get("ends"));
  if (!end) { $("#expiry").textContent = ""; return; }
  const left = Math.round((end - Date.now()) / 60000);
  if (left <= 0) { key = null; store.del("key"); store.del("ends"); showStart(say(401)); return; }
  $("#expiry").textContent = `This shelf clears in ${left} min, and its files are deleted.`;
  setTimeout(tick, 30000);
}

async function begin() {
  const r = await call("/session", { method: "POST" });
  if (r.status !== 200) { showStart(r.status === 503 ? "The demo is full. Try again in a few minutes." : "Could not start a session."); return; }
  key = r.body.key;
  store.set("key", key);
  store.set("ends", String(Date.now() + r.body.expires_in_seconds * 1000));
  mode.max_files = r.body.max_files;
  mode.max_file_mb = r.body.max_file_mb;
  files.length = 0;
  $("#files").replaceChildren();
  $("#answer").replaceChildren();
  await enter();
}

function label(p) {
  const name = p.doc_id.split("/").pop();
  return p.page ? `${name}, page ${p.page}` : name;
}

function cited(text, prov) {
  const p = document.createElement("p");
  let last = 0;
  for (const m of text.matchAll(/\[([^\]]+)\]/g)) {
    p.append(text.slice(last, m.index));
    const tag = document.createElement("span");
    tag.className = "tag";
    const hit = prov.find((x) => x.chunk_id === m[1]);
    tag.textContent = hit ? label(hit) : m[1];
    p.append(tag);
    last = m.index + m[0].length;
  }
  p.append(text.slice(last));
  return p;
}

function render(body) {
  const box = $("#answer");
  box.replaceChildren();
  const card = document.createElement("div");
  card.className = body.found ? "card" : "card locked";
  card.append(cited(body.answer, body.provenance || []));
  if (body.found && body.provenance.length) {
    const list = document.createElement("ul");
    list.className = "sources";
    for (const p of body.provenance) {
      const li = document.createElement("li");
      li.textContent = `${label(p)} (${groupName(p.group)}${p.ingested_at ? `, added ${p.ingested_at}` : ""})`;
      list.append(li);
    }
    card.append(list);
  }
  if (body.explanation) {
    const d = document.createElement("details");
    const s = document.createElement("summary");
    s.textContent = "Ginger's working";
    d.append(s);
    const ul = document.createElement("ul");
    ul.className = "found";
    for (const h of body.explanation.retrieved) {
      const li = document.createElement("li");
      const b = document.createElement("strong");
      b.textContent = h.chunk_id.split("/").pop();
      li.append(b, ` ${h.used ? "close enough" : "too far"}${h.cited ? ", cited" : ""}: `, h.snippet);
      ul.append(li);
    }
    d.append(ul);
    card.append(d);
  }
  box.append(card);
}

function loading() {
  const card = document.createElement("div");
  card.className = "card loading";
  card.setAttribute("aria-busy", "true");
  for (let i = 0; i < 3; i++) { const b = document.createElement("div"); b.className = "bar"; card.append(b); }
  const w = document.createElement("p");
  w.className = "wait";
  card.append(w);
  $("#answer").replaceChildren(card);
  const t0 = Date.now();
  const timer = setInterval(() => {
    const secs = Math.round((Date.now() - t0) / 1000);
    $("#sub").textContent = `Ginger has been searching for ${secs} s.`;
    w.textContent = secs >= 8 ? "The first question can take longer while the model loads." : "";
  }, 500);
  return () => clearInterval(timer);
}

async function ask(e) {
  e.preventDefault();
  const q = $("#question").value.trim();
  if (!q) { $("#question").focus(); return; }
  $("#go").disabled = true;
  $("#go").textContent = "Looking…";
  stage("looking");
  const stopTimer = loading();
  let r;
  try {
    r = await call("/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, explain: true }) });
  } catch { r = { status: 0 }; }
  stopTimer();
  $("#go").disabled = false;
  $("#go").textContent = "Ask Ginger";
  if (r.status === 200) {
    render(r.body);
    stage(r.body.found ? "answered" : "locked");
  } else if (r.status === 401) {
    key = null; store.del("key"); store.del("ends"); showStart(say(401));
  } else {
    $("#answer").replaceChildren();
    stage("error", say(r.status) || "Could not reach the service.");
  }
}

function listFile(name, body) {
  const li = document.createElement("li");
  li.textContent = name;
  const small = document.createElement("small");
  small.textContent = `${body.chunks} pieces indexed`;
  li.append(small);
  for (const w of body.pages_without_text || []) {
    const warn = document.createElement("small");
    warn.textContent = `${w.split(" ").slice(-2).join(" ")} looks scanned. Run OCR on the PDF, then add it again.`;
    li.append(warn);
  }
  $("#files").append(li);
}

async function upload() {
  const file = $("#file").files[0];
  $("#file").value = "";
  if (!file) return;
  const note = $("#upload-note");
  note.hidden = true;
  $("#progress").hidden = false;
  stage("sniff");
  let r;
  try {
    r = await call("/upload", { method: "POST", headers: { "X-Filename": file.name }, body: file });
  } catch { r = { status: 400 }; }
  $("#progress").hidden = true;
  if (r.status === 200) {
    files.push(file.name);
    listFile(file.name, r.body);
    stage("welcome", `${file.name} is on your shelf. Ask about it.`, "Added.");
  } else {
    note.textContent = say(r.status) || "Could not add that file.";
    note.hidden = false;
    stage(r.status === 401 ? "error" : "idle");
    if (r.status === 401) { key = null; store.del("key"); showStart(say(401)); }
  }
}

function over() { key = null; store.del("key"); store.del("ends"); showStart(); }

async function init() {
  try { const r = await call("/mode"); if (r.status === 200) mode = { ...mode, ...r.body }; } catch { /* keep defaults */ }
  $("#begin").addEventListener("click", begin);
  $("#start-key").addEventListener("submit", (e) => { e.preventDefault(); key = $("#key").value.trim(); store.set("key", key); enter(); });
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { $("#key").value = c.dataset.key; }));
  $("#ask").addEventListener("submit", ask);
  $("#question").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#ask").requestSubmit(); });
  $("#pick").addEventListener("click", () => $("#file").click());
  $("#file").addEventListener("change", upload);
  $("#over").addEventListener("click", over);
  if (key) await enter(); else showStart();
}
init();
