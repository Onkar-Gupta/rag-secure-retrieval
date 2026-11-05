"use strict";
// Static replay of saved answers. Text is only ever added with textContent, never as HTML.
const $ = (s) => document.querySelector(s);
const R = window.REPLAY;
let topic = null;

function stage(dog, pose, say, sub) {
  const img = $("#mascot");
  const next = `img/${dog}_${pose}.png`;
  if (!img.src.endsWith(next)) img.src = next;
  img.alt = `${dog === "ginger" ? "Ginger" : "Simba"}, ${pose}`;
  $("#say").textContent = say;
  $("#sub").textContent = sub;
}

function label(s) { return `${s.doc}, page ${s.page}`; }

function cited(text, sources) {
  const p = document.createElement("p");
  let last = 0;
  for (const m of text.matchAll(/\[([^\]]+)\]/g)) {
    p.append(text.slice(last, m.index));
    const hit = sources.find((x) => x.chunk_id === m[1]);
    if (hit) {
      const tag = document.createElement("button");
      tag.type = "button";
      tag.className = "tag";
      tag.textContent = label(hit);
      tag.title = "Show where this comes from";
      tag.addEventListener("click", () => openSource(hit, text));
      p.append(tag);
    }
    last = m.index + m[0].length;
  }
  p.append(text.slice(last));
  return p;
}

function showAnswer(q) {
  const card = document.createElement("div");
  card.className = q.found ? "card" : "card locked";
  card.append(cited(q.answer, q.sources));
  if (q.found) {
    const list = document.createElement("ul");
    list.className = "sources";
    for (const s of q.sources) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "link";
      b.textContent = label(s);
      b.addEventListener("click", () => openSource(s, q.answer));
      li.append(b);
      list.append(li);
    }
    card.append(list);
  }
  const check = document.createElement("p");
  check.className = "hint";
  check.textContent = `Test sheet: ${q.right}. Saved answer took ${(q.ms / 1000).toFixed(1)} s.`;
  card.append(check);
  const d = document.createElement("details");
  const s = document.createElement("summary");
  s.textContent = "Ginger's working";
  d.append(s);
  const ul = document.createElement("ul");
  ul.className = "found";
  for (const h of q.working) {
    const li = document.createElement("li");
    const b = document.createElement("strong");
    b.textContent = h.chunk.split("/").pop();
    li.append(b, ` ${h.used ? "close enough" : "too far"}${h.cited ? ", cited" : ""}: `, h.snippet);
    ul.append(li);
  }
  d.append(ul);
  card.append(d);
  const box = $("#answer");
  box.replaceChildren(card);
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  if (q.found) stage("ginger", "answering", "Found it.", "The gold tag shows where the PDF says so.");
  else stage("simba", "locked", "Not in this PDF.", "Ginger says so instead of guessing.");
}

function pickTopic(t) {
  topic = t;
  $("#app").hidden = false;
  $("#answer").replaceChildren();
  $("#pdf-blurb").textContent = `${t.title}. ${t.blurb}`;
  $("#pdf-link").href = t.pdf;
  const ul = $("#questions");
  ul.replaceChildren();
  t.questions.forEach((q, i) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn secondary";
    b.textContent = `${i + 1}. ${q.question}`;
    b.addEventListener("click", () => showAnswer(q));
    li.append(b);
    ul.append(li);
  });
  document.querySelectorAll("#topic-list .btn").forEach((b) => b.classList.toggle("primary", b.dataset.id === t.id));
  stage("ginger", "waiting", `${t.title}.`, "Read the PDF if you like, then pick a question.");
  $("#app").scrollIntoView({ behavior: "smooth", block: "start" });
}

function openSource(s, answer) {
  $("#v-title").textContent = label(s);
  $("#v-meta").textContent = `Page ${s.page}. The light highlight is the passage Ginger read. The strong highlight is the sentence closest to the answer.`;
  const chunk = document.createElement("span");
  chunk.className = "chunk";
  const parts = s.highlight.split(/(?<=[.!?])(\s+)/);
  const words = new Set(answer.replace(/\[[^\]]*\]/g, "").toLowerCase().match(/[a-z0-9]{3,}/g) || []);
  let best = 0, at = -1;
  parts.forEach((p, i) => {
    if (i % 2) return;
    const n = (p.toLowerCase().match(/[a-z0-9]{3,}/g) || []).filter((w) => words.has(w)).length;
    if (n > best) { best = n; at = i; }
  });
  parts.forEach((p, i) => {
    if (i === at) { const m = document.createElement("mark"); m.textContent = p; chunk.append(m); } else chunk.append(p);
  });
  $("#v-passage").replaceChildren(s.before, chunk, s.after);
  const link = $("#v-pdf");
  link.href = `${topic.pdf}#page=${s.page}`;
  link.textContent = `Open the PDF at page ${s.page}`;
  $("#viewer").showModal();
}

function init() {
  $("#notice").textContent = `This is a replay. The answers were saved from one real run of the system (${R.meta.model}, ${R.meta.date}). You cannot type new questions here.`;
  $("#foot").textContent = `Run on ${R.meta.date}, repository commit ${R.meta.commit}. The first answer of the run was slower while the model loaded.`;
  for (const t of R.topics) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn secondary";
    b.dataset.id = t.id;
    b.textContent = t.title;
    b.addEventListener("click", () => pickTopic(t));
    $("#topic-list").append(b);
  }
  $("#v-close").addEventListener("click", () => $("#viewer").close());
  stage("simba", "welcome", "Welcome.", "Pick a topic, then ask Ginger one of five questions.");
}
init();
