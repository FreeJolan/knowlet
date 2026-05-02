/**
 * knowlet web UI — Alpine-based, three-column notes-first layout.
 *
 * Discipline (ADR-0008): no business logic here. Every action is a fetch()
 * to a backend endpoint that has a CLI mirror. Rendering, event handling,
 * modal state — those are this file's only job. Hand-rolled stream/parser
 * logic lives in `lib/*.js` (per ADR-0008 §"Update 2026-05-02") so it can
 * be tested in isolation; imported below.
 */

import { parseSSE } from "./lib/sse.js";
import { classifyQuery, filterCommands, filterNotes } from "./lib/palette.js";

// ---------- shared helpers ----------

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

function debounce(fn, wait) {
  let t = null;
  return function (...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), wait);
  };
}

// ---------- top-level toast ----------

function toast(msg, kind) {
  const el = document.createElement("div");
  el.className = `toast ${kind || ""}`;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 200);
  }, 3000);
}

// ---------- i18n ----------

let I18N = {};
async function loadI18n(lang) {
  try {
    const r = await fetch(`/api/i18n/${encodeURIComponent(lang || "en")}`);
    if (r.ok) I18N = await r.json();
  } catch (_) {
    I18N = {};
  }
}
function tt(key) {
  return I18N[key] || key;
}
function ttf(key, vars) {
  let s = tt(key);
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.split(`{${k}}`).join(v == null ? "" : String(v));
    }
  }
  return s;
}
function applyI18n(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    const v = I18N[key];
    if (v) el.textContent = v;
  });
  scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.dataset.i18nPlaceholder;
    const v = I18N[key];
    if (v) el.placeholder = v;
  });
  scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.dataset.i18nTitle;
    const v = I18N[key];
    if (v) el.title = v;
  });
}

// ---------- markdown render with link-target=_blank ----------

function renderMarkdown(text) {
  if (typeof marked !== "undefined") {
    const html = marked.parse(text || "");
    return html.replace(
      /<a (?![^>]*\btarget=)/gi,
      '<a target="_blank" rel="noopener noreferrer" '
    );
  }
  const pre = document.createElement("pre");
  pre.textContent = text || "";
  return pre.outerHTML;
}

// ---------- main UI factory ----------

function ui() {
  return {
    // ---- meta / health ----
    meta: { vault: "", model: "", language: "en" },
    ready: true,                     // false during async bootstrap (B4)
    bootstrapStatus: "ready",        // 'idle' | 'running' | 'ready' | 'error'

    // ---- notes / tabs ----
    notes: [],
    notesLoading: true,
    treeFilter: "",
    openTabs: [],         // [{id, title, path, tags, body, updated_at, dirty, saving}]
    currentNoteId: null,
    editorMode: "preview",

    // ---- right rail ----
    rightOpen: true,
    rightTab: "outline",  // 'outline' | 'backlinks' | 'ai'

    // ---- AI dock chat ----
    chatHistory: [],      // [{role: 'user'|'assistant', content, tool_calls?}]
    chatScope: "note",    // 'note' | 'vault' | 'none'
    chatStreaming: false,
    chatDraft: "",
    imeComposing: false,
    // M6.4 multi-session
    sessions: [],         // ConversationSummary[] from /api/chat/sessions
    activeSessionId: "",
    activeSessionTitle: "",

    // ---- footer counters ----
    draftsCount: 0,
    cardsCount: 0,
    miningTaskName: "",
    miningRunning: false,

    // ---- modals (small dialogs) ----
    modal: null,          // null | 'sediment' | 'profile'

    // ---- focus modes (fullscreen overlays per ADR-0011 §5) ----
    // The three focus modes preserve outer layout / open notes / scroll
    // position on Esc — they're overlays, not navigation.
    focus: null,          // null | 'chat' | 'drafts' | 'cards'

    // ---- Cmd+K command palette ----
    palette: {
      open: false,
      query: "",
      selected: 0,
      mode: "all",        // 'all' | 'notes-only' (Cmd+P quick-switcher)
      asking: false,      // true while > ask AI is streaming
      askResult: "",      // streamed answer body
      askError: "",
    },

    // ---- sediment state ----
    sedimentDrafting: false,
    sediment: { title: "", tagsStr: "", body: "" },

    // ---- profile state ----
    profile: { name: "", body: "" },

    // ---- drafts state ----
    draftsState: { queue: [], current: 0, full: null },

    // ---- cards state ----
    cardsState: { queue: [], current: 0, revealed: false },

    // ============================================================ init

    async init() {
      // health → language → i18n catalog
      try {
        const h = await api("GET", "/api/health");
        this.meta = {
          vault: h.vault.split("/").pop(),
          model: h.model,
          language: h.language || "en",
        };
        this.ready = h.ready === true;
        this.bootstrapStatus = h.bootstrap_status || "idle";
        document.documentElement.lang = h.language || "en";
        await loadI18n(h.language || "en");
        applyI18n();
      } catch (exc) {
        toast(`health: ${exc.message}`, "error");
      }

      // If the server is still indexing (B4 async lifespan), poll until ready
      // so chat / search endpoints become usable transparently. Backoff
      // 1s → 5s caps the noise on a slow first run.
      if (!this.ready && this.bootstrapStatus !== "idle") {
        this._pollUntilReady();
      }

      // wire Split.js for left vs (center+right). Right rail is collapsed by Alpine,
      // so we don't include it in Split — center should reflow.
      this.$nextTick(() => {
        try {
          window._knowletSplit = Split(["#pane-left", "#pane-center"], {
            sizes: [20, 80],
            minSize: [200, 320],
            gutterSize: 4,
            onDragEnd: (sizes) => {
              try { localStorage.setItem("knowlet:sizes", JSON.stringify(sizes)); } catch (_) {}
            },
          });
          // restore preference
          const saved = localStorage.getItem("knowlet:sizes");
          if (saved) {
            try {
              const sizes = JSON.parse(saved);
              if (Array.isArray(sizes) && sizes.length === 2) {
                window._knowletSplit.setSizes(sizes);
              }
            } catch (_) {}
          }
        } catch (e) {
          console.warn("Split.js init failed", e);
        }
      });

      // initial data
      await Promise.all([
        this.refreshNotes(),
        this.refreshDraftsCount(),
        this.refreshCardsCount(),
        this.refreshMining(),
        this.fetchChatHistory(),
        this.refreshSessions(),
      ]);

      // bind debounced save
      this.debouncedSave = debounce(() => this.saveCurrent(), 800);

      // restore last open notes from localStorage
      try {
        // Dedup at read time: localStorage is user-editable, and earlier
        // versions of the app could persist duplicates (the now-fixed
        // double-init bug). Without this, x-for `:key="tab.id"` warns
        // "Duplicate key" and the editor pane renders twice.
        const raw = JSON.parse(localStorage.getItem("knowlet:openTabs") || "[]");
        const ids = [...new Set(Array.isArray(raw) ? raw : [])];
        for (const id of ids) await this.openNote(id, false);
        const cur = localStorage.getItem("knowlet:currentNoteId");
        if (cur && this.openTabs.find((t) => t.id === cur)) this.currentNoteId = cur;
      } catch (_) {}
    },

    /** Poll /api/health until bootstrap_status is 'ready' (or stays in
     * 'error' for a while). Called from init when the first health check
     * showed the server still indexing on startup. */
    async _pollUntilReady() {
      let delay = 1000;
      const maxDelay = 5000;
      while (!this.ready) {
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(maxDelay, delay + 500);
        try {
          const h = await api("GET", "/api/health");
          this.bootstrapStatus = h.bootstrap_status || "idle";
          if (h.ready === true) {
            this.ready = true;
            toast(tt("health.indexing.done"), "ok");
            return;
          }
          if (this.bootstrapStatus === "error") {
            toast(
              tt("health.bootstrap.error") + ": " + (h.bootstrap_error || "?"),
              "error",
            );
            return;
          }
        } catch (_) {
          // transient — keep polling
        }
      }
    },

    // ============================================================ notes / tree

    async refreshNotes() {
      this.notesLoading = true;
      try {
        const rows = await api("GET", "/api/notes?limit=200&recent=true");
        this.notes = rows;
      } catch (exc) {
        toast(exc.message, "error");
      } finally {
        this.notesLoading = false;
      }
    },

    filteredNotes() {
      const q = this.treeFilter.trim().toLowerCase();
      if (!q) return this.notes;
      return this.notes.filter((n) => n.title.toLowerCase().includes(q));
    },

    async openNote(id, focus) {
      // already open?
      const existing = this.openTabs.find((t) => t.id === id);
      if (existing) {
        this.currentNoteId = id;
        this.persistTabs();
        return;
      }
      try {
        const n = await api("GET", `/api/notes/${encodeURIComponent(id)}`);
        this.openTabs.push({
          id: n.id,
          title: n.title,
          path: n.path,
          tags: n.tags || [],
          body: n.body || "",
          updated_at: n.updated_at,
          dirty: false,
          saving: false,
        });
        if (focus !== false) this.currentNoteId = n.id;
        this.persistTabs();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    closeTab(id) {
      const i = this.openTabs.findIndex((t) => t.id === id);
      if (i < 0) return;
      this.openTabs.splice(i, 1);
      if (this.currentNoteId === id) {
        this.currentNoteId =
          this.openTabs[i]?.id || this.openTabs[i - 1]?.id || null;
      }
      this.persistTabs();
    },

    currentTab() {
      return this.openTabs.find((t) => t.id === this.currentNoteId) || null;
    },

    /** Two-way binding target for the center textarea. Alpine's `x-model`
     * requires a writable left-hand-side expression — a ternary like
     * `currentTab() ? currentTab().body : ''` raises
     * `Invalid left-hand side in assignment`. Routing through this
     * getter/setter keeps the binding clean and lets us mark the tab
     * dirty + debounce save in one place. */
    get editorBody() {
      return this.currentTab()?.body ?? "";
    },
    set editorBody(value) {
      const tab = this.currentTab();
      if (!tab) return;
      if (tab.body !== value) {
        tab.body = value;
        this.markDirty();
      }
    },

    persistTabs() {
      try {
        localStorage.setItem(
          "knowlet:openTabs",
          JSON.stringify(this.openTabs.map((t) => t.id))
        );
        if (this.currentNoteId) localStorage.setItem("knowlet:currentNoteId", this.currentNoteId);
      } catch (_) {}
    },

    markDirty() {
      const tab = this.currentTab();
      if (!tab) return;
      tab.dirty = true;
      this.debouncedSave();
    },

    async saveCurrent() {
      const tab = this.currentTab();
      if (!tab || !tab.dirty) return;
      tab.saving = true;
      try {
        const payload = {
          title: tab.title,
          tags: tab.tags || [],
          body: tab.body || "",
        };
        const updated = await api(
          "PUT",
          `/api/notes/${encodeURIComponent(tab.id)}`,
          payload
        );
        tab.updated_at = updated.updated_at;
        tab.path = updated.path;
        tab.dirty = false;
        // refresh sidebar list to reflect updated_at
        this.refreshNotes();
      } catch (exc) {
        toast(`保存失败: ${exc.message}`, "error");
      } finally {
        tab.saving = false;
      }
    },

    /** Soft-delete a Note (M7.0.1). Confirmation prompt + DELETE
     * /api/notes/{id}, which moves the file to notes/.trash/. The Note
     * gets removed from openTabs (if present) and the sidebar refreshes.
     * Per ADR-0013 §1, deletion is a structural change: only triggered
     * by an explicit user click, never by AI. */
    async deleteNote(id, title) {
      if (!id) return;
      const msg = ttf("sidebar.note.delete.confirm", {
        title: title || tt("rail.ai.empty.notitle"),
      });
      if (!window.confirm(msg)) return;
      try {
        await api("DELETE", `/api/notes/${encodeURIComponent(id)}`);
        // Close any tab pointing at the deleted note.
        const i = this.openTabs.findIndex((t) => t.id === id);
        if (i >= 0) {
          this.openTabs.splice(i, 1);
          if (this.currentNoteId === id) {
            this.currentNoteId =
              this.openTabs[i]?.id || this.openTabs[i - 1]?.id || null;
          }
          this.persistTabs();
        }
        await this.refreshNotes();
        toast(ttf("sidebar.note.delete.toast", { title: title || "" }), "ok");
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    /** Sidebar "+" / palette `New note` command both land here. We open
     * the Cmd+K palette pre-filled with `+ ` so the user types the title
     * inline — no browser-native `prompt()` (raw, unstyled, races with
     * i18n load) and no separate modal to maintain. Enter creates the
     * note via the existing `newnote` palette branch. */
    newNote() {
      this.openPalette("all");
      this.palette.query = "+ ";
      this.$nextTick(() => {
        const el = this.$refs.paletteInput;
        if (el) {
          el.focus();
          // Place caret after the leading "+ " so the user just types.
          try { el.setSelectionRange(2, 2); } catch (_) {}
        }
      });
    },

    outline() {
      const text = this.currentTab()?.body || "";
      const headings = [];
      for (const line of text.split("\n")) {
        const m = /^(#{1,4})\s+(.+?)\s*$/.exec(line);
        if (m) headings.push({ level: m[1].length, text: m[2] });
      }
      return headings;
    },

    // ============================================================ AI dock chat

    async fetchChatHistory() {
      try {
        const data = await api("GET", "/api/chat/history");
        // map to lightweight {role, content}
        this.chatHistory = (data.history || []).map((m) => ({
          role: m.role,
          content: m.content || "",
          tool_calls: (m.tool_calls || []).map((tc) => ({
            id: tc.id,
            name: tc.function?.name,
            args: tc.function?.arguments,
          })),
        }));
        this.activeSessionId = data.active_id || "";
        this.activeSessionTitle = data.active_title || "";
        this.scrollChatToBottom();
      } catch (_) {}
    },

    // ============================================================ multi-session (M6.4)

    async refreshSessions() {
      try {
        const data = await api("GET", "/api/chat/sessions?limit=50");
        this.sessions = data.sessions || [];
        this.activeSessionId = data.active_id || this.activeSessionId;
      } catch (_) {}
    },

    /** Switch to an existing session: persist outgoing on the server,
     * load the new history, scroll the chat focus pane to bottom. */
    async activateSession(id) {
      if (!id || id === this.activeSessionId) return;
      try {
        await api("POST", `/api/chat/sessions/${encodeURIComponent(id)}/activate`);
        await this.fetchChatHistory();
        await this.refreshSessions();
        this.scrollChatFocusToBottom();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    /** Start a fresh session and switch to it. */
    async createSession() {
      try {
        const r = await api("POST", "/api/chat/sessions");
        this.activeSessionId = r.id;
        this.activeSessionTitle = r.title || "";
        this.chatHistory = [];
        await this.refreshSessions();
        this.$nextTick(() => {
          const el = this.$refs.chatFocusInput;
          if (el) el.focus();
        });
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async renameSession(id, title) {
      const trimmed = (title || "").trim();
      if (!trimmed) return;
      try {
        await api("PUT", `/api/chat/sessions/${encodeURIComponent(id)}`, {
          title: trimmed,
        });
        if (id === this.activeSessionId) this.activeSessionTitle = trimmed;
        await this.refreshSessions();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async promptRenameSession(id) {
      const current = this.sessions.find((s) => s.id === id)?.title || "";
      const next = window.prompt(tt("chat.session.rename.prompt"), current);
      if (next === null) return;
      await this.renameSession(id, next);
    },

    async deleteSession(id) {
      if (id === this.activeSessionId) {
        // Backend would 409; UX is "switch first, then delete".
        toast(tt("chat.session.delete.refuse_active"), "error");
        return;
      }
      if (!window.confirm(tt("chat.session.delete.confirm"))) return;
      try {
        await api("DELETE", `/api/chat/sessions/${encodeURIComponent(id)}`);
        await this.refreshSessions();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    /** Fire-and-forget auto-title after the first turn of an untitled
     * session. Doesn't block the UI; refreshes the sidebar when done. */
    _maybeAutoTitle() {
      if (!this.activeSessionId) return;
      if (this.activeSessionTitle) return;
      // Need at least one full exchange (user + assistant).
      if (this.chatHistory.length < 2) return;
      const sid = this.activeSessionId;
      // Don't await — runs in the background. Errors are silent (best-effort).
      (async () => {
        try {
          const r = await api(
            "POST",
            `/api/chat/sessions/${encodeURIComponent(sid)}/auto-title`,
          );
          if (r && r.title && sid === this.activeSessionId) {
            this.activeSessionTitle = r.title;
          }
          await this.refreshSessions();
        } catch (_) {
          // best-effort: a flaky LLM call shouldn't bubble up to the user
        }
      })();
    },

    handleChatKey(ev) {
      if (ev.key !== "Enter") return;
      if (this.imeComposing || ev.isComposing || ev.keyCode === 229) return;
      if (ev.shiftKey) return;
      ev.preventDefault();
      this.sendChat();
    },

    async sendChat() {
      const text = (this.chatDraft || "").trim();
      if (!text || this.chatStreaming) return;
      this.chatStreaming = true;
      this.chatDraft = "";

      // user bubble
      this.chatHistory.push({ role: "user", content: text });
      // assistant placeholder
      const asst = { role: "assistant", content: "", tool_calls: [] };
      this.chatHistory.push(asst);
      this.scrollChatToBottom();

      // augment with scope context as a prelude when scope = note
      const cur = this.currentTab();
      let payloadText = text;
      if (this.chatScope === "note" && cur) {
        payloadText =
          `(scope: 这条 Note "${cur.title}")\n\n` +
          `--- Note 内容 ---\n${cur.body}\n--- end ---\n\n` +
          text;
      }
      // scope=vault and scope=none: send as-is; system prompt + tools handle rest.

      try {
        const r = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: payloadText }),
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
            asst.content += ev.text;
          } else if (ev.type === "tool_call") {
            asst.tool_calls.push({
              id: ev.id,
              name: ev.name,
              args: ev.arguments,
            });
          } else if (ev.type === "tool_result") {
            // could enrich the tool_call entry; skip for M6.1
          } else if (ev.type === "turn_done") {
            if (ev.final_text) asst.content = ev.final_text;
          } else if (ev.type === "error") {
            asst.content += `\n\n**Error:** ${ev.message}`;
          }
          this.scrollChatToBottom();
        }
        // refresh side counts in case tools touched drafts/cards/notes
        this.refreshDraftsCount();
        this.refreshCardsCount();
        this.refreshNotes();
        // M6.4: refresh sidebar (this exchange may have just made an
        // empty session "meaningful" + bumped its updated_at) and kick
        // off auto-titling if needed.
        this.refreshSessions();
        this._maybeAutoTitle();
      } catch (exc) {
        asst.content += `\n\n**Error:** ${exc.message}`;
        toast(exc.message, "error");
      } finally {
        this.chatStreaming = false;
      }
    },

    async clearChat() {
      try {
        const r = await api("POST", "/api/chat/clear");
        this.chatHistory = [];
        // Backend returns the new active session id (M6.4).
        if (r && r.active_id) {
          this.activeSessionId = r.active_id;
          this.activeSessionTitle = "";
        }
        await this.refreshSessions();
        toast(tt("chat.web.cleared"), "ok");
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    scrollChatToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.chatScroll;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    // ============================================================ sediment / save chat as note

    async openSediment() {
      this.modal = "sediment";
      this.sediment = { title: "", tagsStr: "", body: "" };
      this.sedimentDrafting = true;
      try {
        const draft = await api("POST", "/api/chat/draft");
        this.sediment.title = draft.title;
        this.sediment.tagsStr = (draft.tags || []).join(", ");
        this.sediment.body = draft.body;
      } catch (exc) {
        toast(exc.message, "error");
        this.modal = null;
      } finally {
        this.sedimentDrafting = false;
      }
    },

    async commitSediment() {
      const title = this.sediment.title.trim();
      const body = this.sediment.body.trim();
      if (!title || !body) {
        toast(tt("sediment.web.required"), "error");
        return;
      }
      const tags = this.sediment.tagsStr
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      try {
        await api("POST", "/api/notes", { title, tags, body });
        this.modal = null;
        toast(tt("sediment.web.saved"), "ok");
        await this.refreshNotes();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    // ============================================================ profile

    async openProfile() {
      try {
        const p = await api("GET", "/api/profile");
        this.profile = {
          name: p.exists ? p.name || "" : "",
          body: p.exists ? p.body : "",
        };
        this.modal = "profile";
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async saveProfile() {
      try {
        await api("PUT", "/api/profile", {
          name: this.profile.name.trim() || null,
          body: this.profile.body,
        });
        this.modal = null;
        toast(tt("profile.web.saved"), "ok");
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    // ============================================================ drafts review

    async refreshDraftsCount() {
      try {
        const drafts = await api("GET", "/api/drafts");
        this.draftsCount = drafts.length;
      } catch (_) {}
    },

    draftsLabel() {
      if (this.draftsCount === 0) return "0";
      if (this.draftsCount > 50) return "满";
      if (this.draftsCount > 9) return "9+";
      return String(this.draftsCount);
    },

    draftsCountClass() {
      if (this.draftsCount > 50) return "text-danger";
      if (this.draftsCount > 30) return "text-warn";
      return "text-ok";
    },

    async openDraftsReview() {
      try {
        const drafts = await api("GET", "/api/drafts");
        if (!drafts.length) {
          toast(tt("inbox.empty"), "ok");
          return;
        }
        this.draftsState = { queue: drafts, current: 0, full: null };
        this.focus = "drafts";
        await this.loadCurrentDraft();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async loadCurrentDraft() {
      const d = this.draftsState.queue[this.draftsState.current];
      if (!d) {
        this.focus = null;
        await this.refreshDraftsCount();
        await this.refreshNotes();
        toast(tt("inbox.done"), "ok");
        return;
      }
      try {
        this.draftsState.full = await api(
          "GET",
          `/api/drafts/${encodeURIComponent(d.id)}`
        );
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async actDraft(action) {
      const d = this.draftsState.queue[this.draftsState.current];
      if (!d) return;
      try {
        if (action === "approve") {
          await api("POST", `/api/drafts/${encodeURIComponent(d.id)}/approve`);
        } else if (action === "reject") {
          await api("POST", `/api/drafts/${encodeURIComponent(d.id)}/reject`);
        }
        // skip just advances
        this.draftsState.current += 1;
        await this.loadCurrentDraft();
        await this.refreshDraftsCount();
        if (action === "approve") await this.refreshNotes();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    /** J / K navigation within drafts focus. K = next (forward in queue),
     * J = prev. Treats prev as a no-op past index 0 (no rewind into
     * already-decided drafts; ADR-0011 §6 says drafts are a forward-only
     * stream). */
    async draftsNav(delta) {
      if (this.focus !== "drafts") return;
      const next = this.draftsState.current + delta;
      if (next < 0 || next >= this.draftsState.queue.length) return;
      this.draftsState.current = next;
      await this.loadCurrentDraft();
    },

    // ============================================================ cards review

    async refreshCardsCount() {
      try {
        const due = await api("GET", "/api/cards/due?limit=50");
        this.cardsCount = due.length;
      } catch (_) {}
    },

    async openCardsReview() {
      try {
        const due = await api("GET", "/api/cards/due?limit=50");
        if (!due.length) {
          toast(tt("review.empty"), "ok");
          return;
        }
        this.cardsState = { queue: due, current: 0, revealed: false };
        this.focus = "cards";
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async rateCard(rating) {
      const card = this.cardsState.queue[this.cardsState.current];
      if (!card) return;
      try {
        await api("POST", `/api/cards/${encodeURIComponent(card.id)}/review`, { rating });
        this.cardsState.current += 1;
        this.cardsState.revealed = false;
        if (this.cardsState.current >= this.cardsState.queue.length) {
          this.focus = null;
          await this.refreshCardsCount();
          toast(tt("review.done"), "ok");
        }
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    // ============================================================ mining

    async refreshMining() {
      try {
        const tasks = await api("GET", "/api/mining/tasks");
        this.miningTaskName = tasks.length
          ? tasks[0].name + (tasks.length > 1 ? ` (+${tasks.length - 1})` : "")
          : "";
      } catch (_) {}
    },

    async runMiningNow() {
      this.miningRunning = true;
      try {
        const reports = await api("POST", "/api/mining/run-all");
        const totals = reports.reduce(
          (a, r) => ({
            fetched: a.fetched + r.fetched,
            new_items: a.new_items + r.new_items,
            drafts: a.drafts + r.drafts_created,
          }),
          { fetched: 0, new_items: 0, drafts: 0 }
        );
        if (totals.drafts === 0) {
          if (totals.new_items === 0) {
            toast(ttf("mining.toast.empty", { n: totals.fetched }), "ok");
          } else {
            toast(
              ttf("mining.toast.no_drafts", { n: totals.fetched, m: totals.new_items }),
              "ok"
            );
          }
        } else {
          toast(
            ttf("mining.toast.success", { n: totals.fetched, m: totals.drafts }),
            "ok"
          );
        }
        await this.refreshDraftsCount();
      } catch (exc) {
        toast(exc.message, "error");
      } finally {
        this.miningRunning = false;
      }
    },

    // ============================================================ Cmd+K palette

    /** Stable list of command actions. Each entry matches a CLI mirror
     * (ADR-0008): `runMiningNow` ↔ `knowlet mining run-all`,
     * `clearChat` ↔ `knowlet chat clear`, etc. Adding a new palette command
     * means: (a) confirm the CLI mirror exists, (b) add the i18n keys, (c)
     * append here. */
    paletteCommands() {
      return [
        { id: "mining-run-all", label: tt("palette.cmd.mining"),    sub: tt("palette.cmd.mining.sub") },
        { id: "open-drafts",    label: tt("palette.cmd.drafts"),    sub: tt("palette.cmd.drafts.sub") },
        { id: "open-cards",     label: tt("palette.cmd.cards"),     sub: tt("palette.cmd.cards.sub") },
        { id: "save-chat",      label: tt("palette.cmd.sediment"),  sub: tt("palette.cmd.sediment.sub"),  disabled: !this.chatHistory.length },
        { id: "clear-chat",     label: tt("palette.cmd.clearchat"), sub: tt("palette.cmd.clearchat.sub"), disabled: !this.chatHistory.length },
        { id: "open-profile",   label: tt("palette.cmd.profile"),   sub: tt("palette.cmd.profile.sub") },
        { id: "new-note",       label: tt("palette.cmd.newnote"),   sub: tt("palette.cmd.newnote.sub") },
        { id: "reindex",        label: tt("palette.cmd.reindex"),   sub: tt("palette.cmd.reindex.sub") },
        { id: "doctor",         label: tt("palette.cmd.doctor"),    sub: tt("palette.cmd.doctor.sub") },
      ];
    },

    /** Dispatch a palette command by id. Pulled out of paletteCommands()
     * to keep that function returning *plain data* (no closures stored on
     * objects that Alpine's reactive proxy walks). */
    runPaletteCmd(id) {
      switch (id) {
        case "mining-run-all": this.runMiningNow(); break;
        case "open-drafts":    this.openDraftsReview(); break;
        case "open-cards":     this.openCardsReview(); break;
        case "save-chat":      this.openSediment(); break;
        case "clear-chat":     this.clearChat(); break;
        case "open-profile":   this.openProfile(); break;
        case "new-note":       this.newNote(); break;
        case "reindex":        this.runReindex(); break;
        case "doctor":         this.runDoctor(); break;
      }
    },

    /** M6.5: palette `重建索引` — fire the reindex on the server and toast
     * the row counts. Doesn't block the UI. */
    async runReindex() {
      try {
        toast(tt("palette.cmd.reindex.running"), "ok");
        const r = await api("POST", "/api/system/reindex");
        toast(
          ttf("palette.cmd.reindex.done", {
            changed: r.changed, deleted: r.deleted, unchanged: r.unchanged,
          }),
          "ok",
        );
      } catch (exc) {
        toast(`reindex: ${exc.message}`, "error");
      }
    },

    /** M6.5: palette `诊断` — run the full doctor check and toast the
     * pass/fail summary. The full result table is captured but rendered
     * compactly; M7+ will give it a dedicated focus mode if needed. */
    async runDoctor() {
      try {
        toast(tt("palette.cmd.doctor.running"), "ok");
        const r = await api("POST", "/api/system/doctor");
        const ok = (r.failures || 0) === 0;
        const msg = ttf("palette.cmd.doctor.done", {
          fail: r.failures || 0, warn: r.warnings || 0,
        });
        toast(msg, ok ? "ok" : "error");
      } catch (exc) {
        toast(`doctor: ${exc.message}`, "error");
      }
    },

    /** Compute filtered, sectioned palette results.
     *
     * Items are PURE DATA — no callback properties. Dispatch happens via
     * `kind` (+ `cmdId` for command items). Storing arrow functions on
     * Alpine-tracked objects led to spurious invocation on init in some
     * proxy paths; pure data dodges the entire class of bug.
     *
     * Query syntax:
     *  - `> ...`      → Ask AI (one-shot popup, no chat history)
     *  - `+ <title>`  → New note with that title
     *  - bare text    → Fuzzy match notes + commands
     */
    paletteItems() {
      const { mode, text } = classifyQuery(this.palette.query);
      const items = [];

      if (mode === "ask") {
        items.push({ section: "askai", header: tt("palette.section.askai") });
        items.push({
          kind: "ask",
          label: text || tt("palette.askai.empty"),
          sub: tt("palette.askai.sub"),
          query: text,
          disabled: !text,
        });
        return items;
      }

      if (mode === "newnote") {
        items.push({ section: "newnote", header: tt("palette.section.newnote") });
        items.push({
          kind: "newnote",
          label: text || tt("palette.newnote.empty"),
          sub: tt("palette.newnote.sub"),
          newTitle: text,
          disabled: !text,
        });
        return items;
      }

      // mode is 'fuzzy' (text is a lowercased query) or 'browse' (text is "")
      const noteMatches = filterNotes(this.notes || [], text, 8);
      if (noteMatches.length) {
        items.push({ section: "notes", header: tt("palette.section.notes") });
        for (const n of noteMatches) {
          items.push({
            kind: "note",
            label: n.title,
            sub: n.updated_at || "",
            noteId: n.id,
          });
        }
      }

      if (this.palette.mode !== "notes-only") {
        const cmds = filterCommands(this.paletteCommands(), text);
        if (cmds.length) {
          items.push({ section: "commands", header: tt("palette.section.commands") });
          for (const c of cmds) {
            items.push({ kind: "cmd", cmdId: c.id, label: c.label, sub: c.sub, disabled: !!c.disabled });
          }
        }
      }

      if (!items.length) {
        items.push({
          kind: "empty",
          label: tt("palette.empty"),
          disabled: true,
        });
      }

      return items;
    },

    /** Filtered to actionable rows only (for keyboard nav indexing). */
    paletteActionable() {
      return this.paletteItems().filter((i) =>
        i.kind && i.kind !== "empty" && !i.disabled
      );
    },

    openPalette(mode) {
      this.palette.open = true;
      this.palette.mode = mode || "all";
      this.palette.query = "";
      this.palette.selected = 0;
      this.palette.askResult = "";
      this.palette.askError = "";
      this.palette.asking = false;
      this.$nextTick(() => {
        const el = this.$refs.paletteInput;
        if (el) el.focus();
      });
    },

    closePalette() {
      this.palette.open = false;
      this.palette.query = "";
      this.palette.askResult = "";
      this.palette.askError = "";
      this.palette.asking = false;
    },

    paletteMove(delta) {
      const n = this.paletteActionable().length;
      if (!n) return;
      this.palette.selected = (this.palette.selected + delta + n) % n;
    },

    paletteEnter(opts) {
      const items = this.paletteActionable();
      const it = items[this.palette.selected];
      if (!it || it.disabled) return;
      // Cmd+Enter on a note opens but keeps palette open and creates a
      // fresh tab. For other kinds, Cmd+Enter is identical to Enter.
      if (opts && opts.newTab && it.kind === "note") {
        this.openNote(it.noteId);
        return;
      }
      switch (it.kind) {
        case "note":     this.openNoteFromPalette(it.noteId); break;
        case "ask":      this.askOnce(it.query); break;
        case "newnote":  this.newNoteFromPalette(it.newTitle); break;
        case "cmd":      this.runPaletteCmd(it.cmdId); break;
        default: return;
      }
      // Ask-AI keeps palette open to show the streaming answer; everything
      // else dismisses.
      if (it.kind !== "ask") this.closePalette();
    },

    handlePaletteKey(ev) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        this.closePalette();
      } else if (ev.key === "ArrowDown") {
        ev.preventDefault();
        this.paletteMove(1);
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        this.paletteMove(-1);
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        this.paletteEnter({ newTab: ev.metaKey || ev.ctrlKey });
      }
    },

    /** Opening a note from the palette — same as openNote, plus closes overlay. */
    async openNoteFromPalette(id) {
      await this.openNote(id);
    },

    async newNoteFromPalette(title) {
      try {
        const r = await api("POST", "/api/notes", {
          title,
          tags: [],
          body: `# ${title}\n\n`,
        });
        await this.refreshNotes();
        await this.openNote(r.note_id);
        this.editorMode = "edit";
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    /** Stream a one-shot answer into palette.askResult — does NOT touch
     * the persistent chat session (per ADR-0011 §4). */
    async askOnce(query) {
      if (!query || this.palette.asking) return;
      this.palette.asking = true;
      this.palette.askResult = "";
      this.palette.askError = "";
      try {
        const r = await fetch("/api/chat/ask-once", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: query }),
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
            this.palette.askResult += ev.text;
          } else if (ev.type === "turn_done" && ev.final_text) {
            this.palette.askResult = ev.final_text;
          } else if (ev.type === "error") {
            this.palette.askError = ev.message;
          }
        }
      } catch (exc) {
        this.palette.askError = exc.message;
      } finally {
        this.palette.asking = false;
      }
    },

    // ============================================================ chat focus

    openChatFocus() {
      this.focus = "chat";
      this.$nextTick(() => {
        const el = this.$refs.chatFocusInput;
        if (el) el.focus();
        this.scrollChatFocusToBottom();
      });
    },

    scrollChatFocusToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.chatFocusScroll;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    handleChatFocusKey(ev) {
      if (ev.key !== "Enter") return;
      if (this.imeComposing || ev.isComposing || ev.keyCode === 229) return;
      if (ev.shiftKey) return;
      ev.preventDefault();
      this.sendChat();
      this.scrollChatFocusToBottom();
    },

    // ============================================================ focus mode keyboard

    /** Global hotkeys for entering focus modes. Bound on body via Alpine.
     * Cmd+Shift+{C,D,R} match the ADR-0011 §5 spec. */
    handleFocusHotkey(ev, mode) {
      if (this.modal) return;       // modal takes precedence
      if (this.palette.open) return;
      if (this.focus === mode) return;
      if (mode === "chat") {
        this.openChatFocus();
      } else if (mode === "drafts") {
        this.openDraftsReview();
      } else if (mode === "cards") {
        this.openCardsReview();
      }
    },

    /** Within drafts focus: X reject, S skip, A approve, J prev, K next. */
    handleDraftsFocusKey(ev) {
      if (this.focus !== "drafts") return;
      // Ignore when typing in any input/textarea (none expected here, but
      // safe to guard).
      const tag = (ev.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      const k = ev.key.toLowerCase();
      if (k === "x") { ev.preventDefault(); this.actDraft("reject"); }
      else if (k === "s") { ev.preventDefault(); this.actDraft("skip"); }
      else if (k === "a" || ev.key === "Enter") { ev.preventDefault(); this.actDraft("approve"); }
      else if (k === "j") { ev.preventDefault(); this.draftsNav(-1); }
      else if (k === "k") { ev.preventDefault(); this.draftsNav(1); }
    },

    /** Within cards focus: ⏎ reveal, then 1/2/3/4 rate. */
    handleCardsFocusKey(ev) {
      if (this.focus !== "cards") return;
      const tag = (ev.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (!this.cardsState.revealed) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          this.cardsState.revealed = true;
        }
        return;
      }
      const n = parseInt(ev.key, 10);
      if (n >= 1 && n <= 4) {
        ev.preventDefault();
        this.rateCard(n);
      }
    },

    /** Progress hairline width for focus headers. 0 → 1 over the queue. */
    draftsProgress() {
      const total = this.draftsState.queue.length || 1;
      const done = Math.min(this.draftsState.current, total);
      return Math.round((done / total) * 100);
    },
    cardsProgress() {
      const total = this.cardsState.queue.length || 1;
      const done = Math.min(this.cardsState.current, total);
      return Math.round((done / total) * 100);
    },

    // ============================================================ overlays

    closeAllOverlays() {
      if (this.palette.open) {
        this.closePalette();
        return;
      }
      if (this.focus) {
        this.focus = null;
        return;
      }
      if (this.modal) this.modal = null;
    },

    // ============================================================ helpers exposed to template

    renderMarkdown(text) {
      return renderMarkdown(text);
    },

    tt(key) {
      return tt(key);
    },

    ttf(key, vars) {
      return ttf(key, vars);
    },
  };
}

// ES module ⇒ everything above is module-scoped. Alpine reads `ui()` and
// `toast()` from the global scope (via `x-data="ui()"` and inline @click
// handlers like `toast(...)`), so re-export them onto window. This is the
// minimum surface needed; the rest of the helpers stay encapsulated.
window.ui = ui;
window.toast = toast;
