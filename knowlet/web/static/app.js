/**
 * knowlet web UI — Alpine-based, three-column notes-first layout (M6.1).
 *
 * Discipline (ADR-0008): no business logic here. Every action is a fetch()
 * to a backend endpoint that has a CLI mirror. Rendering, event handling,
 * modal state — those are this file's only job.
 */

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

    // ---- footer counters ----
    draftsCount: 0,
    cardsCount: 0,
    miningTaskName: "",
    miningRunning: false,

    // ---- modals ----
    modal: null,          // null | 'sediment' | 'profile' | 'drafts' | 'cards'

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
        document.documentElement.lang = h.language || "en";
        await loadI18n(h.language || "en");
        applyI18n();
      } catch (exc) {
        toast(`health: ${exc.message}`, "error");
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
      ]);

      // bind debounced save
      this.debouncedSave = debounce(() => this.saveCurrent(), 800);

      // restore last open notes from localStorage
      try {
        const ids = JSON.parse(localStorage.getItem("knowlet:openTabs") || "[]");
        for (const id of ids) await this.openNote(id, false);
        const cur = localStorage.getItem("knowlet:currentNoteId");
        if (cur && this.openTabs.find((t) => t.id === cur)) this.currentNoteId = cur;
      } catch (_) {}
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

    async newNote() {
      const title = prompt(tt("prompt.new.title")) || "";
      if (!title.trim()) return;
      try {
        const r = await api("POST", "/api/notes", {
          title: title.trim(),
          tags: [],
          body: `# ${title.trim()}\n\n`,
        });
        await this.refreshNotes();
        await this.openNote(r.note_id);
        this.editorMode = "edit";
      } catch (exc) {
        toast(exc.message, "error");
      }
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
        this.scrollChatToBottom();
      } catch (_) {}
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
      } catch (exc) {
        asst.content += `\n\n**Error:** ${exc.message}`;
        toast(exc.message, "error");
      } finally {
        this.chatStreaming = false;
      }
    },

    async clearChat() {
      try {
        await api("POST", "/api/chat/clear");
        this.chatHistory = [];
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
        this.modal = "drafts";
        await this.loadCurrentDraft();
      } catch (exc) {
        toast(exc.message, "error");
      }
    },

    async loadCurrentDraft() {
      const d = this.draftsState.queue[this.draftsState.current];
      if (!d) {
        this.modal = null;
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
        this.modal = "cards";
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
          this.modal = null;
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

    // ============================================================ overlays

    closeAllOverlays() {
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
