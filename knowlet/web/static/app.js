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

async function* parseSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const dataLines = block
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6));
      const json = dataLines.join("");
      if (!json) continue;
      try {
        yield JSON.parse(json);
      } catch (err) {
        console.error("SSE parse error", err, json);
      }
    }
  }
}

async function sendMessage(text) {
  if (!text.trim()) return;
  inputEl.value = "";
  inputEl.disabled = true;
  appendBubble("user", text);

  // Build an empty assistant bubble we'll fill as events arrive.
  const wrap = document.createElement("div");
  wrap.className = "bubble assistant";
  const roleEl = document.createElement("div");
  roleEl.className = "role";
  roleEl.textContent = "assistant";
  wrap.appendChild(roleEl);
  const contentEl = document.createElement("div");
  contentEl.className = "content";
  contentEl.dataset.raw = "";
  wrap.appendChild(contentEl);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  // Track tool calls so we can update their displayed result line in place.
  const toolEls = new Map(); // id → element

  function renderContent() {
    contentEl.innerHTML = renderMarkdown(contentEl.dataset.raw);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  try {
    const r = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`;
      try {
        const d = await r.json();
        if (d.detail) detail = d.detail;
      } catch (_) {}
      throw new Error(detail);
    }

    for await (const ev of parseSSE(r)) {
      if (ev.type === "reply_chunk") {
        contentEl.dataset.raw += ev.text;
        renderContent();
      } else if (ev.type === "tool_call") {
        const trace = document.createElement("div");
        trace.className = "tool-trace";
        const args = JSON.stringify(ev.arguments).slice(0, 120);
        trace.textContent = `· ${ev.name}(${args})`;
        wrap.appendChild(trace);
        toolEls.set(ev.id, trace);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (ev.type === "tool_result") {
        const trace = toolEls.get(ev.id);
        if (trace) {
          const isErr = ev.payload && ev.payload.error;
          const summary = isErr
            ? `error: ${ev.payload.error}`
            : ev.payload && ev.payload.count != null
            ? `${ev.payload.count} hit(s)`
            : "ok";
          trace.textContent = `· ${ev.name} → ${summary}`;
          if (isErr) trace.classList.add("error");
        }
      } else if (ev.type === "turn_done") {
        // Final assembly: ensure full markdown render.
        if (ev.final_text) {
          contentEl.dataset.raw = ev.final_text;
          renderContent();
        }
      } else if (ev.type === "error") {
        contentEl.dataset.raw += `\n\n**Error:** ${ev.message}`;
        renderContent();
        toast(ev.message, "error");
      }
    }
  } catch (exc) {
    contentEl.dataset.raw += `\n\n**Error:** ${exc.message}`;
    renderContent();
    toast(exc.message, "error");
  } finally {
    inputEl.disabled = false;
    inputEl.focus();
    // The LLM may have created a card or processed drafts; reflect that.
    refreshCards();
    refreshDrafts();
    refreshNotes();
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

// --------------------------------------------------------- cards review

const reviewModal = $("#review-modal");
const reviewState = {
  queue: [],
  current: 0,
};

async function refreshCards() {
  try {
    const due = await api("GET", "/api/cards/due?limit=50");
    const status = $("#cards-status");
    const btn = $("#review-btn");
    if (!due.length) {
      status.textContent = "nothing due — make some cards in chat";
      btn.hidden = true;
    } else {
      status.textContent = `${due.length} card${due.length === 1 ? "" : "s"} due`;
      btn.hidden = false;
    }
  } catch (exc) {
    $("#cards-status").textContent = `(error: ${exc.message})`;
  }
}

async function openReview() {
  try {
    const due = await api("GET", "/api/cards/due?limit=50");
    if (!due.length) {
      toast("nothing due", "ok");
      return;
    }
    reviewState.queue = due;
    reviewState.current = 0;
    reviewModal.hidden = false;
    showCurrentCard();
  } catch (exc) {
    toast(exc.message, "error");
  }
}

function showCurrentCard() {
  const card = reviewState.queue[reviewState.current];
  if (!card) return finishReview();
  $("#review-progress").textContent = `card ${reviewState.current + 1} / ${reviewState.queue.length}`;
  $("#review-front").innerHTML = renderMarkdown(card.front);
  $("#review-back").innerHTML = renderMarkdown(card.back);
  $("#review-back").hidden = true;
  $("#review-tags").textContent = card.tags.length ? `tags: ${card.tags.join(", ")}` : "";
  $("#review-actions").hidden = false;
  $("#review-rate-row").hidden = true;
}

function finishReview() {
  reviewModal.hidden = true;
  reviewState.queue = [];
  reviewState.current = 0;
  refreshCards();
  toast("review done", "ok");
}

$("#review-btn").addEventListener("click", openReview);
$("#review-reveal").addEventListener("click", () => {
  $("#review-back").hidden = false;
  $("#review-actions").hidden = true;
  $("#review-rate-row").hidden = false;
});
$("#review-quit").addEventListener("click", () => (reviewModal.hidden = true));
for (const btn of $$('#review-rate-row button[data-rating]')) {
  btn.addEventListener("click", async () => {
    const card = reviewState.queue[reviewState.current];
    if (!card) return;
    try {
      await api("POST", `/api/cards/${encodeURIComponent(card.id)}/review`, {
        rating: parseInt(btn.dataset.rating, 10),
      });
      reviewState.current += 1;
      showCurrentCard();
    } catch (exc) {
      toast(exc.message, "error");
    }
  });
}

// --------------------------------------------------------- drafts review

const draftsModal = $("#drafts-modal");
const draftsState = { queue: [], current: 0 };

async function refreshDrafts() {
  try {
    const drafts = await api("GET", "/api/drafts");
    const status = $("#drafts-status");
    const btn = $("#drafts-btn");
    if (!drafts.length) {
      status.textContent = "inbox empty — run mining or wait for the schedule";
      btn.hidden = true;
    } else {
      status.textContent = `${drafts.length} draft${drafts.length === 1 ? "" : "s"} pending`;
      btn.hidden = false;
    }
  } catch (exc) {
    $("#drafts-status").textContent = `(error: ${exc.message})`;
  }
}

async function showDraftAt(index) {
  const drafts = draftsState.queue;
  if (index >= drafts.length) {
    draftsModal.hidden = true;
    refreshDrafts();
    refreshNotes();
    toast("done", "ok");
    return;
  }
  draftsState.current = index;
  try {
    const full = await api(
      "GET",
      `/api/drafts/${encodeURIComponent(drafts[index].id)}`
    );
    $("#drafts-progress").textContent = `draft ${index + 1} / ${drafts.length}`;
    $("#drafts-title").textContent = full.title;
    $("#drafts-source").textContent =
      `source: ${full.source || "—"}  ·  task: ${full.task_id || "—"}` +
      (full.tags.length ? `  ·  tags: ${full.tags.join(", ")}` : "");
    $("#drafts-body").innerHTML = renderMarkdown(full.body);
  } catch (exc) {
    toast(exc.message, "error");
  }
}

async function openDraftsReview() {
  try {
    const drafts = await api("GET", "/api/drafts");
    if (!drafts.length) {
      toast("inbox empty", "ok");
      return;
    }
    draftsState.queue = drafts;
    draftsState.current = 0;
    draftsModal.hidden = false;
    showDraftAt(0);
  } catch (exc) {
    toast(exc.message, "error");
  }
}

$("#drafts-btn").addEventListener("click", openDraftsReview);
$("#drafts-quit").addEventListener("click", () => (draftsModal.hidden = true));
$("#drafts-skip").addEventListener("click", () =>
  showDraftAt(draftsState.current + 1)
);
$("#drafts-reject").addEventListener("click", async () => {
  const card = draftsState.queue[draftsState.current];
  try {
    await api("POST", `/api/drafts/${encodeURIComponent(card.id)}/reject`);
    showDraftAt(draftsState.current + 1);
  } catch (exc) {
    toast(exc.message, "error");
  }
});
$("#drafts-approve").addEventListener("click", async () => {
  const card = draftsState.queue[draftsState.current];
  try {
    await api("POST", `/api/drafts/${encodeURIComponent(card.id)}/approve`);
    showDraftAt(draftsState.current + 1);
  } catch (exc) {
    toast(exc.message, "error");
  }
});

$("#run-mining-btn").addEventListener("click", async () => {
  $("#run-mining-btn").disabled = true;
  $("#drafts-status").textContent = "running mining tasks…";
  try {
    const reports = await api("POST", "/api/mining/run-all");
    const totals = reports.reduce(
      (acc, r) => {
        acc.fetched += r.fetched;
        acc.drafts += r.drafts_created;
        return acc;
      },
      { fetched: 0, drafts: 0 }
    );
    toast(
      `mining: ${totals.fetched} fetched, ${totals.drafts} drafts`,
      "ok"
    );
  } catch (exc) {
    toast(exc.message, "error");
  } finally {
    $("#run-mining-btn").disabled = false;
    refreshDrafts();
  }
});

// --------------------------------------------------------- bootstrap

async function bootstrap() {
  try {
    const h = await api("GET", "/api/health");
    metaEl.textContent = `vault: ${h.vault.split("/").pop()}  ·  model: ${h.model}`;
  } catch (exc) {
    metaEl.textContent = `(health check failed: ${exc.message})`;
  }
  await refreshNotes();
  await refreshCards();
  await refreshDrafts();
  // Show the "run mining now" button only if at least one task exists.
  try {
    const tasks = await api("GET", "/api/mining/tasks");
    if (tasks.length) $("#run-mining-btn").hidden = false;
  } catch (_) {}
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
