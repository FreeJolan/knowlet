/**
 * knowlet web UI — minimal vanilla JS over the FastAPI backend.
 *
 * Discipline: no business logic here. Every action is a fetch() to a backend
 * endpoint that has a CLI mirror. Rendering, event handling, modal state —
 * those are this file's only job.
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const messagesEl = $("#messages");
const inputEl = $("#input");
const composerEl = $("#composer");
const notesListEl = $("#notes-list");
const notesEmptyEl = $("#notes-empty");
const metaEl = $("#meta");

const draftModal = $("#draft-modal");
const profileModal = $("#profile-modal");
const noteModal = $("#note-modal");

// --------------------------------------------------------- helpers

function renderMarkdown(text) {
  // marked is loaded from CDN. If it failed to load, fall back to <pre>.
  if (typeof marked !== "undefined") {
    return marked.parse(text || "");
  }
  const pre = document.createElement("pre");
  pre.textContent = text || "";
  return pre.outerHTML;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 200);
  }, 3000);
}

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const data = await r.json();
      if (data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  if (r.status === 204) return null;
  return await r.json();
}

function appendBubble(role, text, toolCalls = []) {
  const wrap = document.createElement("div");
  wrap.className = `bubble ${role}`;

  const roleEl = document.createElement("div");
  roleEl.className = "role";
  roleEl.textContent = role;
  wrap.appendChild(roleEl);

  if (role === "assistant") {
    const content = document.createElement("div");
    content.className = "content";
    content.innerHTML = renderMarkdown(text);
    wrap.appendChild(content);
  } else {
    const content = document.createElement("div");
    content.className = "content";
    content.textContent = text;
    wrap.appendChild(content);
  }

  for (const tc of toolCalls) {
    const trace = document.createElement("div");
    const isErr = tc.result && tc.result.error;
    trace.className = `tool-trace ${isErr ? "error" : ""}`;
    const args = JSON.stringify(tc.arguments).slice(0, 120);
    const summary = isErr
      ? `error: ${tc.result.error}`
      : tc.result && tc.result.count != null
      ? `${tc.result.count} hit(s)`
      : "ok";
    trace.textContent = `· ${tc.name}(${args}) → ${summary}`;
    wrap.appendChild(trace);
  }

  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrap;
}

// --------------------------------------------------------- chat

async function sendMessage(text) {
  if (!text.trim()) return;
  inputEl.value = "";
  inputEl.disabled = true;
  appendBubble("user", text);

  const placeholder = appendBubble("assistant", "…thinking");

  try {
    const data = await api("POST", "/api/chat/turn", { text });
    placeholder.remove();
    appendBubble("assistant", data.reply, data.tool_calls || []);
  } catch (exc) {
    placeholder.remove();
    appendBubble("assistant", `**Error:** ${exc.message}`);
    toast(exc.message, "error");
  } finally {
    inputEl.disabled = false;
    inputEl.focus();
  }
}

composerEl.addEventListener("submit", (ev) => {
  ev.preventDefault();
  sendMessage(inputEl.value);
});

inputEl.addEventListener("keydown", (ev) => {
  // Cmd/Ctrl+Enter sends.
  if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
    ev.preventDefault();
    sendMessage(inputEl.value);
  }
});

// --------------------------------------------------------- header buttons

$("#clear-btn").addEventListener("click", async () => {
  try {
    await api("POST", "/api/chat/clear");
    messagesEl.innerHTML = "";
    toast("history cleared", "ok");
  } catch (exc) {
    toast(exc.message, "error");
  }
});

$("#save-btn").addEventListener("click", async () => {
  try {
    const draft = await api("POST", "/api/chat/draft");
    $("#draft-title").value = draft.title;
    $("#draft-tags").value = (draft.tags || []).join(", ");
    $("#draft-body").value = draft.body;
    draftModal.hidden = false;
  } catch (exc) {
    toast(exc.message, "error");
  }
});

$("#draft-cancel").addEventListener("click", () => (draftModal.hidden = true));
$("#draft-commit").addEventListener("click", async () => {
  const title = $("#draft-title").value.trim();
  const tags = $("#draft-tags").value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const body = $("#draft-body").value.trim();
  if (!title || !body) {
    toast("title and body are required", "error");
    return;
  }
  try {
    await api("POST", "/api/notes", { title, tags, body });
    draftModal.hidden = true;
    toast("note saved", "ok");
    await refreshNotes();
  } catch (exc) {
    toast(exc.message, "error");
  }
});

// --------------------------------------------------------- profile

$("#profile-btn").addEventListener("click", async () => {
  try {
    const p = await api("GET", "/api/profile");
    $("#profile-name").value = p.exists ? p.name || "" : "";
    $("#profile-body").value = p.exists ? p.body : "";
    profileModal.hidden = false;
  } catch (exc) {
    toast(exc.message, "error");
  }
});

$("#profile-cancel").addEventListener("click", () => (profileModal.hidden = true));
$("#profile-save").addEventListener("click", async () => {
  const name = $("#profile-name").value.trim() || null;
  const body = $("#profile-body").value;
  try {
    await api("PUT", "/api/profile", { name, body });
    profileModal.hidden = true;
    toast("profile saved", "ok");
  } catch (exc) {
    toast(exc.message, "error");
  }
});

// --------------------------------------------------------- notes sidebar

async function refreshNotes() {
  try {
    const rows = await api("GET", "/api/notes?limit=20&recent=true");
    notesListEl.innerHTML = "";
    if (!rows.length) {
      notesEmptyEl.hidden = false;
      return;
    }
    notesEmptyEl.hidden = true;
    for (const r of rows) {
      const li = document.createElement("li");
      li.dataset.id = r.id;
      li.innerHTML = `<span class="note-title"></span><span class="note-meta"></span>`;
      li.querySelector(".note-title").textContent = r.title;
      const tagBlurb = r.tags.length ? ` · ${r.tags.join(", ")}` : "";
      li.querySelector(".note-meta").textContent = `${r.updated_at}${tagBlurb}`;
      li.addEventListener("click", () => openNote(r.id));
      notesListEl.appendChild(li);
    }
  } catch (exc) {
    toast(exc.message, "error");
  }
}

async function openNote(noteId) {
  try {
    const n = await api("GET", `/api/notes/${encodeURIComponent(noteId)}`);
    $("#note-title").textContent = n.title;
    const tagBlurb = n.tags.length ? ` · ${n.tags.join(", ")}` : "";
    $("#note-meta").textContent = `${n.updated_at}${tagBlurb}`;
    $("#note-body").innerHTML = renderMarkdown(n.body);
    noteModal.hidden = false;
  } catch (exc) {
    toast(exc.message, "error");
  }
}

$("#note-close").addEventListener("click", () => (noteModal.hidden = true));

// --------------------------------------------------------- bootstrap

async function bootstrap() {
  try {
    const h = await api("GET", "/api/health");
    metaEl.textContent = `vault: ${h.vault.split("/").pop()}  ·  model: ${h.model}`;
  } catch (exc) {
    metaEl.textContent = `(health check failed: ${exc.message})`;
  }
  await refreshNotes();
  // Restore any prior conversation in the running session.
  try {
    const data = await api("GET", "/api/chat/history");
    for (const m of data.history || []) {
      appendBubble(m.role, m.content || "");
    }
  } catch (_) {
    // Non-fatal — likely no runtime yet.
  }
}

bootstrap();
