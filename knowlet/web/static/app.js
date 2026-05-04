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

// M7.0.5: register highlight.js with marked once at module load. We guard
// against any of the three globals being missing (offline mode, ad-blockers
// nuking jsdelivr) so the editor still renders plain (un-highlighted) code.
(function _wireHighlightOnce() {
  if (typeof marked === "undefined") return;
  if (typeof hljs === "undefined" || typeof markedHighlight === "undefined") {
    console.warn("highlight.js or marked-highlight not loaded; code blocks will be plain.");
    return;
  }
  marked.use(
    markedHighlight.markedHighlight({
      langPrefix: "hljs language-",
      highlight(code, lang) {
        const language = lang && hljs.getLanguage(lang) ? lang : "plaintext";
        try {
          return hljs.highlight(code, { language }).value;
        } catch (_e) {
          return hljs.highlight(code, { language: "plaintext" }).value;
        }
      },
    })
  );
})();

function renderMarkdown(text) {
  if (typeof marked !== "undefined") {
    // M7.0.4: pre-rewrite `[[Title]]` (or `[[Title|alias]]`) into a sentinel
    // span so marked doesn't mangle the brackets, then upgrade to a clickable
    // link in post. Doing it pre-marked guarantees the link survives any
    // surrounding markdown (lists, blockquotes, etc).
    const wikiSrc = (text || "").replace(
      /\[\[([^\[\]\n|]+?)(?:\|([^\[\]\n]+?))?\]\]/g,
      (_m, target, alias) => {
        const t = target.trim();
        const a = (alias || target).trim();
        if (!t) return _m;
        const safeT = t.replace(/"/g, "&quot;");
        return `<span class="wikilink" data-wiki-target="${safeT}">${a}</span>`;
      }
    );
    let html = marked.parse(wikiSrc);
    // External-by-default for real links (not in-app fragment links).
    html = html.replace(
      /<a (?![^>]*\btarget=)/gi,
      '<a target="_blank" rel="noopener noreferrer" '
    );
    // M7.0.3: rewrite portable relative `_attachments/foo.png` paths in the
    // markdown into web-served URLs so the preview pane can render them.
    // The on-disk markdown stays portable (Obsidian / Finder open it as-is);
    // only the rendered HTML knows about /files/.
    html = html.replace(
      /<img([^>]*)\bsrc="(_attachments\/[^"]+)"/gi,
      '<img$1 src="/files/$2"'
    );
    return html;
  }
  const pre = document.createElement("pre");
  pre.textContent = text || "";
  return pre.outerHTML;
}

// ---------- image paste → upload → insert markdown ----------

async function uploadImageBlob(blob) {
  const fd = new FormData();
  fd.append("file", blob, blob.name || "pasted");
  const res = await fetch("/api/attachments", { method: "POST", body: fd });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`upload failed (${res.status}): ${detail}`);
  }
  const { path } = await res.json();
  return path;
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
    treeFolderState: {},  // {<folder-path>: true=collapsed, false=open}; default open
    openTabs: [],         // [{id, title, path, tags, body, updated_at, dirty, saving}]
    currentNoteId: null,
    editorMode: "preview",

    // ---- right rail ----
    rightOpen: true,
    rightTab: "outline",  // 'outline' | 'backlinks' | 'ai'

    // ---- backlinks (M7.0.4) ----
    backlinks: { loading: false, noteId: null, rows: [] },

    // ---- AI dock chat ----
    chatHistory: [],      // [{role: 'user'|'assistant', content, tool_calls?}]
    chatScope: "note",    // 'note' | 'vault' | 'none'
    chatStreaming: false,
    chatDraft: "",
    imeComposing: false,
    // M7.1: selection → chat capsule
    chatRefs: [],         // [{note_id, note_title, quote_text, paragraph_anchor, source, source_url}]
    chatRefsSent: [],     // grayed; one click to "use again"
    selectionPopover: { visible: false, x: 0, y: 0 },

    // M7.2: URL capture
    urlCapturePending: null,  // null | {url, status: 'ready'|'fetching'|'error', error?}
    // M7.2: Layer A ambient (sediment)
    similarNotes: { loading: false, query: "", rows: [] },
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
    modal: null,          // null | 'sediment' | 'profile' | 'new-card'

    // ADR-0004 amendment (2026-05-04): UI peer of the create_card LLM tool.
    newCard: { front: "", back: "", tagsStr: "" },

    // ---- focus modes (fullscreen overlays per ADR-0011 §5) ----
    // The three focus modes preserve outer layout / open notes / scroll
    // position on Esc — they're overlays, not navigation.
    focus: null,          // null | 'chat' | 'drafts' | 'cards' | 'quiz'

    // ---- M7.4 quiz focus mode state ----
    quiz: {
      stage: "scope",     // 'scope' | 'loading' | 'loop' | 'summary' | 'error' | 'history'
      session: null,      // QuizSessionPayload from /api/quiz/start
      currentIndex: 0,
      answerDraft: "",
      submitting: false,
      n: 5,               // user-tweakable (advanced settings)
      scopeKind: "notes", // 'notes' | 'tag' (M7.4.3)
      scopeNoteIds: [],   // when scopeKind === 'notes'
      scopeTag: "",       // when scopeKind === 'tag'
      error: "",
      // disagreement loop state
      disagreeOpen: -1,   // question index whose disagree textarea is open
      disagreeDraft: "",
      // Cards reflux state — selected indices for batch convert
      refluxSelected: {}, // {questionIdx: true}
      // M7.4.3 history tab
      history: [],        // [QuizSummaryRow] from GET /api/quiz
      historyLoading: false,
    },

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

      // M7.0.2: restore folder collapse state
      try {
        const saved = JSON.parse(
          localStorage.getItem("knowlet:treeFolderState") || "{}",
        );
        if (saved && typeof saved === "object") this.treeFolderState = saved;
      } catch (_) {}

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

    /** Build a folder tree from the flat notes list (M7.0.2). Each node:
     *   { name, path, folders: [...], notes: [...] }
     * `path` is the full slash-joined folder path; root has path "".
     * When a search filter is active, the tree is built from the filtered
     * subset — folders with no surviving notes collapse out. */
    noteTree() {
      const list = this.filteredNotes();
      const root = { name: "", path: "", folders: [], notes: [] };
      // Stable folder lookup so we don't rebuild a map every visit.
      const byPath = new Map();
      byPath.set("", root);

      for (const n of list) {
        const folder = (n.folder || "").trim();
        if (!folder) {
          root.notes.push(n);
          continue;
        }
        const segs = folder.split("/").filter(Boolean);
        let cursor = root;
        let acc = "";
        for (const seg of segs) {
          acc = acc ? `${acc}/${seg}` : seg;
          let child = byPath.get(acc);
          if (!child) {
            child = { name: seg, path: acc, folders: [], notes: [] };
            byPath.set(acc, child);
            cursor.folders.push(child);
          }
          cursor = child;
        }
        cursor.notes.push(n);
      }

      // Sort each level: folders first (alphabetical), then notes
      // (preserve incoming order — already sorted by recent on the server).
      const sortNode = (node) => {
        node.folders.sort((a, b) => a.name.localeCompare(b.name));
        for (const f of node.folders) sortNode(f);
      };
      sortNode(root);
      return root;
    },

    /** True if this folder is currently collapsed. Defaults to OPEN —
     * the user has to actively close folders, matching VS Code / Finder
     * convention for fresh trees. When the user filter-searches, treat
     * everything as open so matches aren't hidden. */
    isFolderCollapsed(folderPath) {
      if (this.treeFilter.trim()) return false;
      return !!this.treeFolderState[folderPath];
    },

    /** Flatten the tree into a render-friendly depth-annotated list:
     *   [{kind: 'folder'|'note', depth, ...}, ...]
     * Alpine's nested x-for is awkward; flat indexing is straightforward. */
    flatTree() {
      const root = this.noteTree();
      const out = [];
      const walk = (node, depth) => {
        // Don't render the root folder; its children are top-level.
        for (const f of node.folders) {
          const collapsed = this.isFolderCollapsed(f.path);
          out.push({
            kind: "folder",
            depth,
            path: f.path,
            name: f.name,
            collapsed,
            note_count: this._countNotes(f),
          });
          if (!collapsed) walk(f, depth + 1);
        }
        for (const n of node.notes) {
          out.push({ kind: "note", depth, note: n });
        }
      };
      walk(root, 0);
      return out;
    },

    _countNotes(node) {
      let total = node.notes.length;
      for (const f of node.folders) total += this._countNotes(f);
      return total;
    },

    toggleFolder(folderPath) {
      const next = { ...this.treeFolderState };
      next[folderPath] = !next[folderPath];
      if (!next[folderPath]) delete next[folderPath];
      this.treeFolderState = next;
      try {
        localStorage.setItem(
          "knowlet:treeFolderState",
          JSON.stringify(this.treeFolderState),
        );
      } catch (_) {}
    },

    /** Alias used by the backlinks panel — same as openNote, plus closes
     * any modal/overlay layer that might be on top. */
    async openNoteById(id) {
      await this.openNote(id);
    },

    /** Click delegate for the preview pane. Wikilinks are rendered as
     * <span class="wikilink" data-wiki-target="…">; on click we look up
     * the matching note by title (case-insensitive, whitespace-collapsed)
     * and open it. No match → toast so the user knows the link is broken. */
    handlePreviewClick(event) {
      const el = event.target.closest(".wikilink");
      if (!el) return;
      event.preventDefault();
      const target = el.dataset.wikiTarget || "";
      const norm = (s) => s.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
      const wanted = norm(target);
      const hit = this.notes.find((n) => norm(n.title) === wanted);
      if (hit) {
        this.openNote(hit.id);
      } else {
        toast(`没有找到笔记: ${target}`, "warn");
      }
    },

    /** M7.0.4: load inbound `[[Title]]` references for the current note.
     * Caches per-noteId so flipping tabs doesn't refetch needlessly; the
     * cache invalidates whenever currentNoteId changes (via $watch in HTML)
     * — saving the current note triggers no refresh, which is fine since
     * the user can manually click the Backlinks tab again to refresh, or
     * we'll add a save-time refetch in M7.1 if dogfooding shows it bites. */
    async loadBacklinks() {
      const id = this.currentNoteId;
      if (!id) {
        this.backlinks = { loading: false, noteId: null, rows: [] };
        return;
      }
      if (this.backlinks.noteId === id && !this.backlinks.loading) return;
      this.backlinks = { loading: true, noteId: id, rows: [] };
      try {
        const rows = await api("GET", `/api/notes/${encodeURIComponent(id)}/backlinks`);
        if (this.currentNoteId !== id) return; // user navigated away mid-flight
        this.backlinks = { loading: false, noteId: id, rows };
      } catch (exc) {
        if (this.currentNoteId !== id) return;
        this.backlinks = { loading: false, noteId: id, rows: [] };
        toast(`backlinks: ${exc.message}`, "error");
      }
    },

    /** Render the sentence preview with the matched `[[target]]` highlighted.
     * We do the highlight in JS rather than backend HTML so the API stays
     * neutral (no embedded markup) and the UI controls the visual treatment. */
    formatBacklinkSentence(row) {
      const text = row.sentence || "";
      const target = row.target || "";
      const escapeHTML = (s) =>
        s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const escaped = escapeHTML(text);
      // Match `[[target]]` or `[[ target ]]` or alias `[[target|alias]]`.
      const re = new RegExp(
        "\\[\\[\\s*" +
          target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
          "(\\s*\\|[^\\]]+)?\\s*\\]\\]",
        "i"
      );
      return escaped.replace(
        re,
        (m) => `<mark class="bl-mark">${escapeHTML(m)}</mark>`
      );
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

    /** M7.0.3: intercept image paste in the editor textarea. Uploads each
     * image clipboard item to `/api/attachments`, then inserts a markdown
     * link at the caret. Non-image clipboard items (text, etc) fall through
     * to the browser's default paste so users can still paste regular text.
     */
    async onEditorPaste(event) {
      const items = event.clipboardData?.items;
      if (!items) return;
      const images = Array.from(items).filter(
        (it) => it.kind === "file" && it.type.startsWith("image/")
      );
      if (images.length === 0) return;
      event.preventDefault();
      const ta = event.target;
      for (const it of images) {
        const blob = it.getAsFile();
        if (!blob) continue;
        // Show a placeholder so the user has visual confirmation while
        // the upload is in flight (large pasted screenshots can take a moment).
        const placeholder = `![uploading…](_attachments/pending-${Date.now()})`;
        this._insertAtCaret(ta, placeholder + "\n");
        try {
          const path = await uploadImageBlob(blob);
          // Filename without ext makes a friendlier alt text than ULID.
          const altBase = path.split("/").pop().split(".")[0];
          const final = `![${altBase}](${path})`;
          if (ta.value.includes(placeholder)) {
            ta.value = ta.value.replace(placeholder, final);
            this.editorBody = ta.value;
          } else {
            this._insertAtCaret(ta, final + "\n");
          }
        } catch (err) {
          console.error("paste upload failed:", err);
          if (ta.value.includes(placeholder)) {
            ta.value = ta.value.replace(placeholder, "");
            this.editorBody = ta.value;
          }
          toast(`图片上传失败: ${err.message}`, "error");
        }
      }
    },

    _insertAtCaret(ta, text) {
      const start = ta.selectionStart ?? ta.value.length;
      const end = ta.selectionEnd ?? start;
      const before = ta.value.slice(0, start);
      const after = ta.value.slice(end);
      const next = before + text + after;
      ta.value = next;
      // Move caret to end of inserted text.
      const pos = start + text.length;
      ta.selectionStart = ta.selectionEnd = pos;
      // Push back through Alpine binding so currentTab().body stays in sync.
      this.editorBody = next;
    },

    // ============================================================ M7.1 quote refs

    /** Capture the current editor selection (textarea or preview), build
     * a capsule, and push it onto chatRefs. The capsule structure matches
     * the QuoteRefPayload Pydantic on the backend; the LLM-facing prompt
     * is composed at send time, not here. */
    captureSelectionAsCapsule() {
      const cur = this.currentTab();
      if (!cur) {
        toast("先打开一条笔记", "warn");
        return false;
      }
      const text = this._currentSelectionText();
      if (!text || text.length < 2) {
        toast("先在笔记里选一段文字", "warn");
        return false;
      }
      if (this.chatRefs.length >= 5) {
        toast("最多挂 5 颗引用,请先取掉一颗", "warn");
        return false;
      }
      // Anchor = first 64 chars of the selected paragraph (the line(s)
      // the selection sits inside, not just the selection itself), so
      // a later edit that doesn't kill the paragraph still finds it.
      const anchor = text
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 64)
        .toLowerCase();
      this.chatRefs.push({
        note_id: cur.id,
        note_title: cur.title,
        quote_text: text,
        paragraph_anchor: anchor,
      });
      this.selectionPopover.visible = false;
      // Switch right rail to AI tab so the user sees the capsule landing.
      this.rightOpen = true;
      this.rightTab = "ai";
      return true;
    },

    /** Reads the current selection from either the preview pane (window
     * selection) or the editor textarea (selectionStart/End). Returns
     * the trimmed string, or "" if nothing is selected. */
    _currentSelectionText() {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0 && sel.toString().trim().length > 0) {
        return sel.toString().trim();
      }
      const ta = document.querySelector('textarea[x-model="editorBody"]');
      if (ta && typeof ta.selectionStart === "number") {
        const s = ta.value.slice(ta.selectionStart, ta.selectionEnd).trim();
        if (s) return s;
      }
      return "";
    },

    /** Selection-change watcher. When the user finishes selecting non-empty
     * text inside the editor, position the popover anchor to the top-right
     * of the selection rect so they can one-click attach. */
    onEditorSelectionChange() {
      const text = this._currentSelectionText();
      if (!text || text.length < 2) {
        this.selectionPopover.visible = false;
        return;
      }
      // Get a bounding box for placement. Prefer the live DOM range
      // when the selection is in the preview; fall back to a textarea-
      // relative box when it's in the textarea (no API for caret rect,
      // anchor near the textarea corner is good enough).
      const sel = window.getSelection();
      let rect = null;
      if (sel && sel.rangeCount > 0 && sel.toString().trim().length > 0) {
        rect = sel.getRangeAt(0).getBoundingClientRect();
      } else {
        const ta = document.querySelector('textarea[x-model="editorBody"]');
        if (ta) rect = ta.getBoundingClientRect();
      }
      if (!rect || (rect.width === 0 && rect.height === 0)) {
        this.selectionPopover.visible = false;
        return;
      }
      // Anchor: just above the right edge of the selection. If too close
      // to the top of the viewport, flip to just below.
      const flipBelow = rect.top < 50;
      this.selectionPopover.x = Math.min(
        window.innerWidth - 180,
        Math.max(8, rect.right - 32)
      );
      this.selectionPopover.y = flipBelow ? rect.bottom + 6 : rect.top - 32;
      this.selectionPopover.visible = true;
    },

    removeChatRef(idx) {
      this.chatRefs.splice(idx, 1);
    },

    /** Reactivate a previously-sent (grayed) capsule. */
    reuseChatRef(idx) {
      if (this.chatRefs.length >= 5) {
        toast("最多挂 5 颗引用,请先取掉一颗", "warn");
        return;
      }
      const r = this.chatRefsSent[idx];
      if (!r) return;
      this.chatRefsSent.splice(idx, 1);
      this.chatRefs.push(r);
    },

    clearSentChatRefs() {
      this.chatRefsSent = [];
    },

    // ============================================================ M7.2 URL capture

    /** Loose mirror of `is_likely_url` in core/url_capture.py — keeps the
     * paste detector permissive enough for the common case (single URL on
     * its own line) but strict enough to not eat regular text pastes. */
    _isLikelyUrl(text) {
      const s = (text || "").trim();
      if (!s || /\s/.test(s)) return false;
      return /^https?:\/\/\S+$/.test(s);
    },

    /** Paste handler bound to both chat textareas. If the clipboard text
     * is a single URL, prevent default + show a small "fetch & discuss"
     * hint. Anything else paths through normally. */
    onChatInputPaste(event) {
      const data = event.clipboardData?.getData?.("text") || "";
      if (!this._isLikelyUrl(data)) return;
      event.preventDefault();
      this.urlCapturePending = { url: data.trim(), status: "ready" };
    },

    /** Run the capture: fetch + summarize on the backend, push a
     * `source="url"` capsule. Status updates feed the toast/hint banner. */
    async runUrlCapture() {
      const ctx = this.urlCapturePending;
      if (!ctx || !ctx.url) return;
      if (this.chatRefs.length >= 5) {
        toast("最多挂 5 颗引用,请先取掉一颗", "warn");
        return;
      }
      this.urlCapturePending = { ...ctx, status: "fetching" };
      try {
        const r = await api("POST", "/api/url/capture", { url: ctx.url });
        this.chatRefs.push({
          note_id: `url://${r.url}`,
          note_title: r.title || r.hostname || r.url,
          quote_text: r.summary || "",
          paragraph_anchor: "",
          source: "url",
          source_url: r.url,
        });
        if (r.summary_failed) {
          toast(`摘要失败,胶囊已挂上,可手动追问`, "warn");
        }
        // Switch right rail to AI tab so user sees the capsule landing.
        this.rightOpen = true;
        this.rightTab = "ai";
        this.urlCapturePending = null;
      } catch (exc) {
        const detail = exc.message || "抓取失败";
        toast(`URL 抓取失败: ${detail}`, "error");
        this.urlCapturePending = { ...ctx, status: "error", error: detail };
      }
    },

    cancelUrlCapture() {
      this.urlCapturePending = null;
    },

    // ============================================================ M7.2 Layer A ambient

    /** Sediment modal opens → fetch top-3 similar Notes by the draft body.
     * Called from the modal's open hook; idempotent for a given body. */
    async loadSimilarForSediment() {
      const body = (this.sediment?.body || "").trim();
      if (!body) {
        this.similarNotes = { loading: false, query: "", rows: [] };
        return;
      }
      // Cache: same query → no refetch.
      if (this.similarNotes.query === body && !this.similarNotes.loading) return;
      this.similarNotes = { loading: true, query: body, rows: [] };
      try {
        const url =
          "/api/notes/similar?top_k=3&q=" +
          encodeURIComponent(body.slice(0, 4000));
        const rows = await api("GET", url);
        this.similarNotes = { loading: false, query: body, rows };
      } catch (exc) {
        // Layer A is purely informational — failure is a quiet no-op.
        this.similarNotes = { loading: false, query: body, rows: [] };
      }
    },

    /** Click a similar-Note row in the sediment ambient panel — opens it
     * in a new editor tab + closes the modal so the user can read first
     * before deciding whether to merge by hand. ADR-0013 §1 stays intact:
     * we never auto-merge, only navigate. */
    openSimilarNote(noteId) {
      this.modal = null;
      this.openNote(noteId);
    },

    // ============================================================ M7.4 quiz focus mode

    /** Enter the quiz focus mode at the scope picker. Pre-seeds with the
     * current Note (if any) so the most common path — "quiz me on this" —
     * is one click. */
    openQuizFocus() {
      const cur = this.currentTab();
      this.quiz = {
        stage: "scope",
        session: null,
        currentIndex: 0,
        answerDraft: "",
        submitting: false,
        n: 5,
        scopeKind: "notes",
        scopeNoteIds: cur ? [cur.id] : [],
        scopeTag: "",
        error: "",
        disagreeOpen: -1,
        disagreeDraft: "",
        refluxSelected: {},
        history: [],
        historyLoading: false,
      };
      this.focus = "quiz";
    },

    exitQuizFocus() {
      this.focus = null;
    },

    /** Toggle a Note's inclusion in the quiz scope. Lets the user pick
     * 1..N notes from a list (the ADR's "manual multi-select" scope). */
    toggleQuizScopeNote(noteId) {
      const arr = this.quiz.scopeNoteIds;
      const i = arr.indexOf(noteId);
      if (i >= 0) arr.splice(i, 1);
      else arr.push(noteId);
    },

    /** Kick off generation. The backend handles the LLM call; we just
     * show a loading state with retry on failure. */
    async startQuiz() {
      const kind = this.quiz.scopeKind;
      if (kind === "notes" && this.quiz.scopeNoteIds.length === 0) {
        toast(tt("quiz.scope.empty") || "请至少选一条笔记", "warn");
        return;
      }
      if (kind === "tag" && !this.quiz.scopeTag.trim()) {
        toast(tt("quiz.scope.tag_empty") || "请选一个 tag", "warn");
        return;
      }
      this.quiz.stage = "loading";
      this.quiz.error = "";
      try {
        const payload = {
          n: Math.max(1, Math.min(20, this.quiz.n | 0)),
          scope_type: kind,
        };
        if (kind === "notes") payload.note_ids = this.quiz.scopeNoteIds;
        if (kind === "tag") payload.tag = this.quiz.scopeTag.trim();
        const session = await api("POST", "/api/quiz/start", payload);
        this.quiz.session = session;
        this.quiz.currentIndex = 0;
        this.quiz.answerDraft = "";
        this.quiz.stage = "loop";
      } catch (exc) {
        this.quiz.stage = "error";
        this.quiz.error = exc.message || "generation failed";
      }
    },

    /** M7.4.3: load past quiz sessions for the history tab. Light list
     * (no question text), opens the full session via openQuizHistory. */
    async loadQuizHistory() {
      this.quiz.historyLoading = true;
      try {
        const rows = await api("GET", "/api/quiz?limit=50");
        this.quiz.history = rows;
      } catch (exc) {
        toast(`history failed: ${exc.message}`, "error");
        this.quiz.history = [];
      } finally {
        this.quiz.historyLoading = false;
      }
    },

    async openQuizHistory(quizId) {
      try {
        const session = await api("GET", `/api/quiz/${encodeURIComponent(quizId)}`);
        this.quiz.session = session;
        this.quiz.stage = "summary";
        // No reflux defaults for historical sessions — user already
        // saw the summary at completion time; this is read-only review.
        this.quiz.refluxSelected = {};
      } catch (exc) {
        toast(`open failed: ${exc.message}`, "error");
      }
    },

    /** Tag list derived from the loaded notes — used by the scope-picker
     * tag dropdown. Sorted by frequency desc, then alphabetical so the
     * user's most-used tags surface first. */
    quizScopeTagOptions() {
      const counts = new Map();
      for (const n of this.notes) {
        for (const t of (n.tags || [])) {
          counts.set(t, (counts.get(t) || 0) + 1);
        }
      }
      return Array.from(counts.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([tag, count]) => ({ tag, count }));
    },

    /** "再来一组" — regenerate without billing the user mentally. New
     * session id, same scope. */
    async regenerateQuiz() {
      this.quiz.session = null;
      this.quiz.currentIndex = 0;
      this.quiz.answerDraft = "";
      await this.startQuiz();
    },

    quizCurrentQuestion() {
      const s = this.quiz.session;
      if (!s) return null;
      return s.questions[this.quiz.currentIndex] || null;
    },

    /** Submit the current answer for grading; advance to next question
     * or to the summary if this was the last. */
    async submitQuizAnswer() {
      const s = this.quiz.session;
      if (!s || this.quiz.submitting) return;
      this.quiz.submitting = true;
      try {
        const updated = await api(
          "POST",
          `/api/quiz/${encodeURIComponent(s.id)}/answer`,
          {
            question_index: this.quiz.currentIndex,
            user_answer: this.quiz.answerDraft || "",
          },
        );
        this.quiz.session = updated;
      } catch (exc) {
        toast(`grading failed: ${exc.message}`, "error");
      } finally {
        this.quiz.submitting = false;
      }
    },

    /** Move to the next question, or finalize if at the last one. */
    async advanceQuiz() {
      const s = this.quiz.session;
      if (!s) return;
      const last = this.quiz.currentIndex >= s.questions.length - 1;
      if (last) {
        await this.completeQuiz();
        return;
      }
      this.quiz.currentIndex += 1;
      this.quiz.answerDraft = "";
    },

    async completeQuiz() {
      const s = this.quiz.session;
      if (!s) return;
      try {
        const final = await api("POST", `/api/quiz/${encodeURIComponent(s.id)}/complete`);
        this.quiz.session = final;
        this.quiz.stage = "summary";
        // Pre-select error questions for Cards reflux per ADR-0014 §6.
        this.quiz.refluxSelected = {};
        for (let i = 0; i < final.questions.length; i++) {
          if ((final.questions[i].ai_score || 0) < 3) {
            this.quiz.refluxSelected[i] = true;
          }
        }
      } catch (exc) {
        toast(`finalize failed: ${exc.message}`, "error");
      }
    },

    /** ADR-0014 §4.3 disagreement loop: user clicks ✗,we open a textarea
     * for an optional reason, then POST it. */
    openDisagree(qIdx) {
      const q = this.quiz.session?.questions?.[qIdx];
      this.quiz.disagreeOpen = qIdx;
      this.quiz.disagreeDraft = q?.user_disagree_reason || "";
    },

    closeDisagree() {
      this.quiz.disagreeOpen = -1;
      this.quiz.disagreeDraft = "";
    },

    async submitDisagree(qIdx, disagree) {
      const s = this.quiz.session;
      if (!s) return;
      try {
        const updated = await api(
          "POST",
          `/api/quiz/${encodeURIComponent(s.id)}/disagree`,
          {
            question_index: qIdx,
            disagree,
            reason: disagree ? this.quiz.disagreeDraft : "",
          },
        );
        this.quiz.session = updated;
        this.quiz.disagreeOpen = -1;
        this.quiz.disagreeDraft = "";
      } catch (exc) {
        toast(`disagree failed: ${exc.message}`, "error");
      }
    },

    /** ADR-0014 §6 Cards reflux: convert each selected error question
     * into a Card. Defaults front=question, back=reference_answer, tags
     * derived server-side. */
    async refluxSelectedCards() {
      const s = this.quiz.session;
      if (!s) return;
      const indices = Object.keys(this.quiz.refluxSelected)
        .filter((k) => this.quiz.refluxSelected[k])
        .map((k) => parseInt(k, 10));
      if (indices.length === 0) {
        toast("没有选中任何题", "warn");
        return;
      }
      let updated = s;
      for (const idx of indices) {
        try {
          updated = await api(
            "POST",
            `/api/quiz/${encodeURIComponent(s.id)}/reflux`,
            { question_index: idx },
          );
        } catch (exc) {
          toast(`Card 创建失败: ${exc.message}`, "error");
        }
      }
      this.quiz.session = updated;
      this.refreshCardsCount();
      toast(`${indices.length} 题已转为 Card`, "ok");
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
        // M7.1: capsules don't carry across sessions.
        this.chatRefs = [];
        this.chatRefsSent = [];
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
        // M7.1: capsules belong to a session — clear on switch.
        this.chatRefs = [];
        this.chatRefsSent = [];
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

      // M7.1: snapshot capsules at send time, then move them to "sent"
      // (grayed) so the user can one-click "use again" without re-selecting.
      const refsToSend = this.chatRefs.slice();
      if (refsToSend.length > 0) {
        this.chatRefsSent = this.chatRefsSent.concat(refsToSend);
        this.chatRefs = [];
      }

      try {
        const r = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: payloadText, references: refsToSend }),
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
        this.chatRefs = [];
        this.chatRefsSent = [];
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

    // ============================================================ create_card UI peer (ADR-0004 amendment)

    openCreateCardModal() {
      this.newCard = { front: "", back: "", tagsStr: "" };
      this.modal = "new-card";
    },

    async commitNewCard() {
      const front = (this.newCard.front || "").trim();
      const back = (this.newCard.back || "").trim();
      if (!front || !back) {
        toast(tt("card.new.empty") || "正面 + 背面都不能为空", "warn");
        return;
      }
      const tags = (this.newCard.tagsStr || "")
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t);
      try {
        await api("POST", "/api/cards", {
          type: "qa",
          front,
          back,
          tags,
          source_note_id: null,
        });
        this.modal = null;
        toast(tt("card.new.created") || "Card 已创建", "ok");
        this.refreshCardsCount();
        // If the user is in cards focus, refresh the queue so the new
        // card surfaces immediately (it's due now per FSRS initial state).
        if (this.focus === "cards") await this.openCardsReview();
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
        { id: "url-capture",    label: tt("palette.cmd.urlcapture"), sub: tt("palette.cmd.urlcapture.sub") },
        { id: "web-search",     label: tt("palette.cmd.websearch"),  sub: tt("palette.cmd.websearch.sub") },
        { id: "new-card",       label: tt("palette.cmd.newcard"),    sub: tt("palette.cmd.newcard.sub") },
        { id: "quiz-me",        label: tt("palette.cmd.quiz"),       sub: tt("palette.cmd.quiz.sub"), disabled: !this.currentTab() && this.notes.length === 0 },
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
        case "url-capture":    this.runPaletteUrlCapture(); break;
        case "web-search":     this.runPaletteWebSearch(); break;
        case "new-card":       this.closePalette(); this.openCreateCardModal(); break;
        case "quiz-me":        this.closePalette(); this.openQuizFocus(); break;
      }
    },

    /** ADR-0004 amendment (2026-05-04): every AI capability needs a
     * UI alternative. web_search is registered as an LLM tool; this
     * palette command is the UI peer — user types a query, we hit the
     * same provider, drop the snippet block into the chat input as
     * pre-filled context the user can edit before sending. */
    async runPaletteWebSearch() {
      this.closePalette();
      const q = window.prompt(tt("palette.cmd.websearch.prompt") || "搜索什么?");
      if (!q || !q.trim()) return;
      try {
        // Hit /api/chat/turn with a minimal user text that asks the LLM
        // to search; we lean on the existing tool path so results show
        // up via the standard tool_call trace UI. The user can refine
        // from there. Future polish: a dedicated /api/web_search route
        // for "search-only without LLM commentary."
        const cur = this.chatDraft || "";
        this.chatDraft = (cur + (cur ? "\n\n" : "") + `请用 web_search 查一下:${q.trim()}`).trim();
        this.rightOpen = true;
        this.rightTab = "ai";
        this.$nextTick(() => {
          const el = this.$refs.chatInput;
          if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
        });
      } catch (exc) {
        toast(`web search 失败: ${exc.message}`, "error");
      }
    },

    /** M7.2: palette `抓取网页` — prompt for URL, then run the capture
     * flow that powers paste detection. Browser prompt() is enough for a
     * keyboard-fallback path; users who paste into chat get the better
     * inline UX. */
    async runPaletteUrlCapture() {
      this.closePalette();
      const url = window.prompt(tt("palette.cmd.urlcapture.prompt") || "请输入要抓取的 URL");
      if (!url) return;
      this.urlCapturePending = { url: url.trim(), status: "ready" };
      await this.runUrlCapture();
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
      } else if (mode === "quiz") {
        this.openQuizFocus();
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
