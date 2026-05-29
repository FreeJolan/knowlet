/**
 * Phase 1 D slice 1 — Settings dialog (Appearance only for v1).
 *
 * Per the `new-3-dark.jsx` design, the theme toggle lives in
 * Settings → Appearance, not the top bar (rationale: theme isn't
 * a high-frequency switch, doesn't deserve top-bar real estate).
 *
 * v1 ships with only the Appearance section. Future settings
 * (sync / hotkeys / vault) slot into the same dialog.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  Cloud,
  CloudOff,
  Download,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Monitor,
  Moon,
  RefreshCw,
  ShieldAlert,
  Sun,
  Upload,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  cancelConnect,
  commitImport,
  disconnect as apiDisconnect,
  exportVaultUrl,
  getAuthStatus,
  getLLMConfig,
  getProviderModels,
  getSyncMode,
  listAICallEvents,
  listMiningTasks,
  previewImport,
  setSyncMode as apiSetSyncMode,
  startConnect,
  testLLM,
  type AICallEvent,
  type ImportReportPayload,
  type MiningTaskSummary,
  type SyncAuthStatus,
  type SyncModeResponse,
  updateLLMConfig,
} from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";
import {
  getThemePreference,
  resolveTheme,
  setThemePreference,
  type ThemeChangeDetail,
  type ThemePreference,
} from "@/lib/theme";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsDialog({ open, onClose }: Props) {
  const { t } = useTranslation();
  const [pref, setPref] = useState<ThemePreference>(() => getThemePreference());

  // Stay in sync with other tabs / Cmd+K toggle.
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<ThemeChangeDetail>).detail;
      if (detail) setPref(detail.preference);
    };
    window.addEventListener("knowlet:theme-changed", onChange);
    return () => window.removeEventListener("knowlet:theme-changed", onChange);
  }, []);

  const set = (next: ThemePreference) => {
    setPref(next);
    setThemePreference(next);
  };

  // Left-sidebar tabs (per Cursor / VS Code / Linear Settings UX).
  // Adding new categories = add a row here; the content area picks
  // the right panel via the discriminated union below.
  type SettingsTab =
    | "appearance"
    | "ai"
    | "sync"
    | "vault"
    | "advanced";
  const [activeTab, setActiveTab] = useState<SettingsTab>("appearance");
  const tabs: { key: SettingsTab; label: string; icon: typeof Sun }[] = [
    { key: "appearance", label: t("settings.tabs.appearance"), icon: Sun },
    { key: "ai", label: t("settings.tabs.ai"), icon: Zap },
    { key: "sync", label: t("settings.tabs.sync"), icon: Cloud },
    { key: "vault", label: t("settings.tabs.vault"), icon: Download },
    // Power-user trace / diagnostics; intentionally last per VS Code-style
    // "Application" section placement.
    { key: "advanced", label: t("settings.tabs.advanced"), icon: Activity },
  ];

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className="flex h-[85vh] max-h-[700px] overflow-hidden p-0 sm:max-w-3xl"
        data-testid="settings-dialog"
      >
        {/* a11y: keep DialogTitle/Description in the tree but visually
            hidden — title appears integrated in the left rail below. */}
        <DialogHeader className="sr-only">
          <DialogTitle>{t("settings.title")}</DialogTitle>
          <DialogDescription>{t("settings.subtitle")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 w-full flex-1">
          {/* Left sidebar — title + tab list */}
          <nav
            className="flex w-44 shrink-0 flex-col border-r"
            style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
            data-testid="settings-tabs"
          >
            <div className="px-3 py-3 font-semibold text-sm" aria-hidden="true">
              {t("settings.title")}
            </div>
            <div className="flex flex-col gap-0.5 px-2 pb-2">
            {tabs.map(({ key, label, icon: Icon }) => {
              const isActive = activeTab === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveTab(key)}
                  data-testid={`settings-tab-${key}`}
                  className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors"
                  style={{
                    background: isActive ? "var(--accent-tint-2)" : "transparent",
                    color: isActive ? "var(--ink)" : "var(--ink-mute)",
                    fontWeight: isActive ? 500 : 400,
                  }}
                >
                  <Icon className="size-3.5 shrink-0" />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
            </div>
          </nav>

          {/* Right — active panel content (scrollable) */}
          <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-5">
            {activeTab === "appearance" && (
              <>
                <Section title={t("settings.appearance.title")}>
                  <ThemePill
                    icon={<Sun size={14} />}
                    label={t("settings.appearance.light")}
                    active={pref === "light"}
                    onClick={() => set("light")}
                    testid="theme-pill-light"
                  />
                  <ThemePill
                    icon={<Moon size={14} />}
                    label={t("settings.appearance.dark")}
                    active={pref === "dark"}
                    onClick={() => set("dark")}
                    testid="theme-pill-dark"
                  />
                  <ThemePill
                    icon={<Monitor size={14} />}
                    label={t("settings.appearance.system")}
                    active={pref === "system"}
                    onClick={() => set("system")}
                    testid="theme-pill-system"
                  />
                </Section>
                {pref === "system" && (
                  <div
                    className="mt-3 font-mono text-[10.5px]"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    {t("settings.appearance.systemHint", {
                      resolved: resolveTheme("system"),
                    })}
                  </div>
                )}
              </>
            )}

            {activeTab === "ai" && <LLMConfigPanel />}

            {activeTab === "sync" && (
              <>
                <DriveAuthPanel />
                <div className="mt-6">
                  <SyncModePicker />
                </div>
              </>
            )}

            {activeTab === "vault" && <VaultPortabilityPanel />}

            {activeTab === "advanced" && (
              <>
                <AICallTracePanel />
                <div className="mt-6">
                  <MiningTaskStatusPanel />
                </div>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function DriveAuthPanel(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery<SyncAuthStatus>({
    queryKey: QK.syncAuth,
    queryFn: getAuthStatus,
    // While connecting we want a fast poll so the spinner gives way
    // to the connected state within ~2s of the user finishing OAuth.
    refetchInterval: (query) =>
      query.state.data?.connecting ? 2000 : false,
    staleTime: 30_000,
  });
  // When OAuth finishes successfully, the SyncChip's caches are
  // still stale (it polls every 60s) and would show "offline" until
  // the next tick. Invalidate the relevant queries on the
  // connecting → connected transition so the chip flips to "synced"
  // within ~2s of the browser callback returning.
  const wasConnecting = useRef(false);
  useEffect(() => {
    const connecting = q.data?.connecting ?? false;
    const connected = q.data?.connected ?? false;
    if (wasConnecting.current && connected && !connecting) {
      void qc.invalidateQueries({ queryKey: QK.syncConflicts });
      void qc.invalidateQueries({ queryKey: QK.syncUnpushed });
      void qc.invalidateQueries({ queryKey: QK.syncMode });
      void qc.invalidateQueries({ queryKey: QK.syncPushErrors });
      // Per-note badges (each note has its own status query) —
      // wildcard-invalidate so any open notes flip out of the
      // "offline / unauthenticated" pill immediately too.
      void qc.invalidateQueries({ queryKey: ["note-sync-status"] });
    }
    wasConnecting.current = connecting;
  }, [q.data?.connecting, q.data?.connected, qc]);
  const connect = useMutation({
    mutationFn: startConnect,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.syncAuth });
    },
  });
  const disconnectMut = useMutation({
    mutationFn: apiDisconnect,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.syncAuth });
      // Disconnect wipes sync_state — chip / conflicts caches need
      // to forget what they thought they knew.
      void qc.invalidateQueries({ queryKey: QK.syncConflicts });
      void qc.invalidateQueries({ queryKey: QK.syncUnpushed });
      void qc.invalidateQueries({ queryKey: QK.syncMode });
    },
  });
  const cancelMut = useMutation({
    mutationFn: cancelConnect,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.syncAuth });
    },
  });
  const data = q.data;
  return (
    <Section title={t("driveAuth.label")}>
      <div className="text-muted-foreground w-full text-xs">
        {t("driveAuth.blurb")}
      </div>
      {data?.connected ? (
        <div className="mt-2 flex w-full items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs">
            <Cloud className="size-4 text-emerald-600 dark:text-emerald-400" />
            <span>
              {data.user_display_name
                ? t("driveAuth.connectedAsNamed", {
                    email: data.user_email,
                    name: data.user_display_name,
                  })
                : t("driveAuth.connectedAs", { email: data.user_email })}
            </span>
          </div>
          <button
            type="button"
            onClick={() => disconnectMut.mutate()}
            data-testid="drive-disconnect"
            disabled={disconnectMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-accent/30"
            style={{ borderColor: "var(--line)" }}
            title={t("driveAuth.disconnectConfirm")}
          >
            {t("driveAuth.disconnect")}
          </button>
        </div>
      ) : data?.connecting ? (
        <div className="mt-2 flex w-full items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs">
            <Loader2 className="size-4 animate-spin" />
            <div>
              <div>{t("driveAuth.connecting")}</div>
              <div className="text-muted-foreground">
                {t("driveAuth.connectingHint")}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => cancelMut.mutate()}
            data-testid="drive-cancel-connect"
            disabled={cancelMut.isPending}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-accent/30"
            style={{ borderColor: "var(--line)" }}
          >
            {t("driveAuth.cancel")}
          </button>
        </div>
      ) : (
        <div className="mt-2 flex w-full flex-col gap-2">
          <div className="flex items-center gap-2 text-xs">
            <CloudOff className="size-4 text-muted-foreground" />
            <span>{t("driveAuth.notConnected")}</span>
          </div>
          <button
            type="button"
            onClick={() => connect.mutate()}
            data-testid="drive-connect"
            disabled={connect.isPending}
            className="inline-flex w-fit items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors"
            style={{
              background: "var(--accent-soft, rgba(91, 122, 156, 0.18))",
              color: "var(--accent-2, #34495e)",
              borderColor: "var(--accent, #5b7a9c)",
              fontWeight: 500,
            }}
          >
            <Cloud className="size-3" />
            {t("driveAuth.connect")}
          </button>
        </div>
      )}
      {data?.last_error && !data.connected && !data.connecting && (
        <div className="text-destructive mt-2 w-full text-xs">
          {t("driveAuth.lastError", { detail: data.last_error })}
        </div>
      )}
    </Section>
  );
}

function SyncModePicker(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery<SyncModeResponse>({
    queryKey: QK.syncMode,
    queryFn: getSyncMode,
    staleTime: 5 * 60_000,
  });
  const mut = useMutation({
    mutationFn: apiSetSyncMode,
    onSuccess: (resp) => {
      qc.setQueryData(QK.syncMode, resp);
      // Strict mode might want to escalate the inbox immediately —
      // refetching conflicts so the chip / blocking modal reacts.
      void qc.invalidateQueries({ queryKey: QK.syncConflicts });
    },
  });

  const current = q.data?.mode ?? "auto";
  const effective = q.data?.effective_mode ?? current;
  const deviceCount = q.data?.device_count ?? 0;
  // #111 — only the Auto pill needs the auto-upgrade hint; Strict /
  // Quiet are explicit user choices and don't have a hidden mode
  // promotion to explain.
  const autoUpgraded = current === "auto" && effective === "strict";

  return (
    <Section title={t("syncMode.label")}>
      <div className="text-muted-foreground mb-2 w-full text-xs">
        {t("syncMode.description")}
      </div>
      <ModePill
        icon={<Zap size={14} />}
        label={t("syncMode.auto")}
        hint={t("syncMode.autoHint")}
        active={current === "auto"}
        onClick={() => mut.mutate("auto")}
        testid="sync-mode-pill-auto"
      />
      <ModePill
        icon={<ShieldAlert size={14} />}
        label={t("syncMode.strict")}
        hint={t("syncMode.strictHint")}
        active={current === "strict"}
        onClick={() => mut.mutate("strict")}
        testid="sync-mode-pill-strict"
      />
      <ModePill
        icon={<CloudOff size={14} />}
        label={t("syncMode.lax")}
        hint={t("syncMode.laxHint")}
        active={current === "lax"}
        onClick={() => mut.mutate("lax")}
        testid="sync-mode-pill-lax"
      />
      {autoUpgraded && (
        <div
          data-testid="sync-mode-auto-upgraded-hint"
          className="text-warn-fg dark:text-warn-fg-dark mt-2 w-full text-xs"
        >
          {t("syncMode.autoUpgradedHint", { count: deviceCount })}
        </div>
      )}
    </Section>
  );
}

function ModePill({
  icon,
  label,
  hint,
  active,
  onClick,
  testid,
}: {
  icon: React.ReactNode;
  label: string;
  hint: string;
  active: boolean;
  onClick: () => void;
  testid: string;
}): React.ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-pressed={active}
      title={hint}
      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors"
      style={{
        background: active
          ? "var(--accent-soft, rgba(91, 122, 156, 0.18))"
          : "transparent",
        color: active ? "var(--accent-2, #34495e)" : "var(--ink, #2a2823)",
        borderColor: active ? "var(--accent, #5b7a9c)" : "var(--line)",
        fontWeight: active ? 500 : 400,
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className="mb-2 font-mono text-[10.5px] uppercase tracking-wider"
        style={{ color: "var(--ink-mute)" }}
      >
        {title}
      </div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function VaultPortabilityPanel(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState<ImportReportPayload | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [resultText, setResultText] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setPreview(null);
    setPendingFile(null);
    setErrorText(null);
    setResultText(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handlePick = async (file: File | null) => {
    if (!file) return;
    setErrorText(null);
    setResultText(null);
    setImporting(true);
    try {
      const r = await previewImport(file);
      setPreview(r);
      setPendingFile(file);
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
    }
  };

  const handleConfirm = async () => {
    if (!pendingFile) return;
    setImporting(true);
    setErrorText(null);
    try {
      const r = await commitImport(pendingFile);
      const label = t("vaultPortability.mergeDoneShort", {
        count: r.notes_created,
        renamed: r.notes_renamed,
        skipped: r.notes_skipped,
      });
      setResultText(label);
      setPreview(null);
      setPendingFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      // Server reindexed on the import endpoint. Bust the caches
      // that surface notes so the new ``imported/YYYY-MM-DD/``
      // folder + its rows show up immediately instead of waiting
      // for the next 30s staleTime window.
      void qc.invalidateQueries({ queryKey: QK.tree });
      void qc.invalidateQueries({ queryKey: QK.tags });
      void qc.invalidateQueries({ queryKey: QK.tagsWithNotes });
      void qc.invalidateQueries({ queryKey: QK.graph });
      // Search results are query-scoped; nuke them all.
      void qc.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) && q.queryKey[0] === "search",
      });
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
    }
  };

  return (
    <Section title={t("vaultPortability.label")}>
      <div className="text-muted-foreground w-full text-xs">
        {t("vaultPortability.blurb")}
      </div>
      <div className="mt-2 flex w-full flex-wrap gap-2">
        <a
          href={exportVaultUrl()}
          download
          data-testid="vault-export-link"
          className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-accent/30"
          style={{ borderColor: "var(--line)" }}
        >
          <Download className="size-3" />
          {t("vaultPortability.exportButton")}
        </a>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={importing}
          data-testid="vault-import-trigger"
          className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-accent/30 disabled:opacity-50"
          style={{ borderColor: "var(--line)" }}
        >
          <Upload className="size-3" />
          {t("vaultPortability.importButton")}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          hidden
          onChange={(e) => void handlePick(e.target.files?.[0] ?? null)}
        />
      </div>
      {importing && !preview && (
        <div className="mt-2 flex w-full items-center gap-2 text-xs">
          <Loader2 className="size-3 animate-spin" />
          <span>{t("vaultPortability.previewing")}</span>
        </div>
      )}
      {preview && (
        <div className="mt-3 w-full rounded border p-3 text-xs" style={{ borderColor: "var(--line)" }}>
          <div className="font-medium">
            {t("vaultPortability.previewMergeTitle")}
          </div>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            <li>{t("vaultPortability.previewMergeCreate", { count: preview.notes_created })}</li>
            {preview.notes_renamed > 0 && (
              <li>{t("vaultPortability.previewMergeRename", { count: preview.notes_renamed })}</li>
            )}
            {preview.notes_skipped > 0 && (
              <li>{t("vaultPortability.previewMergeSkip", { count: preview.notes_skipped })}</li>
            )}
            {preview.attachments_copied > 0 && (
              <li>{t("vaultPortability.previewMergeAtt", { count: preview.attachments_copied })}</li>
            )}
          </ul>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={importing}
              data-testid="vault-import-confirm"
              className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-accent/30 disabled:opacity-50"
              style={{
                background: "var(--accent-soft, rgba(91,122,156,0.18))",
                color: "var(--accent-2, #34495e)",
                borderColor: "var(--accent, #5b7a9c)",
              }}
            >
              {importing ? <Loader2 className="size-3 animate-spin" /> : null}
              {t("vaultPortability.confirmButton")}
            </button>
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center rounded border px-2 py-1 text-xs hover:bg-accent/30"
              style={{ borderColor: "var(--line)" }}
            >
              {t("vaultPortability.cancelButton")}
            </button>
          </div>
        </div>
      )}
      {errorText && (
        <div className="text-destructive mt-2 w-full text-xs">
          {t("vaultPortability.errorPrefix", { detail: errorText })}
        </div>
      )}
      {resultText && (
        <div className="mt-2 w-full text-xs" style={{ color: "var(--ok, #198754)" }}>
          {resultText}
        </div>
      )}
    </Section>
  );
}

function LLMConfigPanel(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const cfg = useQuery({
    queryKey: QK.llmConfig,
    queryFn: getLLMConfig,
    staleTime: 30_000,
  });
  // Provider's /v1/models is a mutation, not a query, because it
  // takes **draft** credentials (so user can preview the model list
  // before clicking Save — fixes the chicken-and-egg where you
  // can't pick a model without saving creds first).
  const providerModelsMut = useMutation({
    mutationFn: getProviderModels,
  });
  const update = useMutation({
    mutationFn: updateLLMConfig,
    onSuccess: (next) => {
      qc.setQueryData(QK.llmConfig, next);
    },
  });
  const testMut = useMutation({
    mutationFn: testLLM,
  });

  // Local editing state — staged until user saves.
  const [draft, setDraft] = useState<{
    base_url: string;
    model: string;
    api_key: string;
  }>({
    base_url: "",
    model: "",
    api_key: "",
  });
  const [dirty, setDirty] = useState(false);
  const [revealKey, setRevealKey] = useState(false);

  // Sync draft when config query loads / refreshes.
  useEffect(() => {
    if (cfg.data && !dirty) {
      setDraft({
        base_url: cfg.data.base_url,
        model: cfg.data.model,
        api_key: "",
      });
    }
  }, [cfg.data, dirty]);

  // Auto-load model list once on mount, using saved config. Subsequent
  // refreshes pass current draft (handled by handleRefresh below).
  const autoLoaded = useRef(false);
  useEffect(() => {
    if (
      cfg.data?.base_url &&
      !autoLoaded.current &&
      !providerModelsMut.isPending
    ) {
      autoLoaded.current = true;
      providerModelsMut.mutate({});
    }
  }, [cfg.data?.base_url, providerModelsMut]);

  if (!cfg.data) {
    return (
      <Section title={t("llm.label")}>
        <div className="text-muted-foreground w-full text-xs">
          {t("llm.loading")}
        </div>
      </Section>
    );
  }

  const handleRefreshModels = () => {
    providerModelsMut.mutate({
      base_url: draft.base_url,
      api_key: draft.api_key,
    });
  };

  // Save requires a non-empty model — otherwise the saved config
  // would be silently broken (LLM calls fail with "no model" later).
  const modelEmpty = !draft.model.trim();
  const baseUrlEmpty = !draft.base_url.trim();
  const saveBlockReason = baseUrlEmpty
    ? t("llm.saveNeedsBaseUrl")
    : modelEmpty
      ? t("llm.saveNeedsModel")
      : "";

  const handleSave = () => {
    if (saveBlockReason) return;
    update.mutate(
      {
        base_url: draft.base_url,
        model: draft.model,
        // empty string = keep existing key per backend convention
        api_key: draft.api_key,
      },
      {
        onSuccess: () => {
          setDraft((d) => ({ ...d, api_key: "" }));
          setDirty(false);
        },
      },
    );
  };

  const inputStyle = {
    borderColor: "var(--line)",
    background: "var(--bg-1)",
  } as const;

  return (
    <Section title={t("llm.label")}>
      <div className="text-muted-foreground w-full text-xs">
        {t("llm.blurb")}
      </div>

      <div className="mt-3 flex w-full flex-col gap-2">
        <label className="flex w-full flex-col gap-1 text-[11px]">
          <span className="text-muted-foreground">{t("llm.baseUrlLabel")}</span>
          <input
            value={draft.base_url}
            onChange={(e) => {
              setDraft((d) => ({ ...d, base_url: e.target.value }));
              setDirty(true);
            }}
            placeholder={t("llm.baseUrlPlaceholder")}
            data-testid="llm-base-url-input"
            className="rounded border px-2 py-1 text-xs"
            style={inputStyle}
          />
          <span className="text-[10px] text-muted-foreground">
            {t("llm.baseUrlHelp")}
          </span>
        </label>

        <label className="flex w-full flex-col gap-1 text-[11px]">
          <span className="text-muted-foreground">{t("llm.apiKeyLabel")}</span>
          {cfg.data.has_api_key ? (
            // Configured state — show pill-style status instead of an
            // empty input. Click "替换" to enter edit mode.
            <ApiKeyStatusRow
              onReplace={() => {
                // Focusing the input is enough — placeholder explains
                // "leave blank to keep, type to replace".
                const el = document.querySelector<HTMLInputElement>(
                  "[data-testid=llm-api-key-input]",
                );
                el?.focus();
              }}
              t={t}
            />
          ) : (
            <div className="flex items-center gap-1 text-[10px] text-amber-700 dark:text-amber-400">
              <KeyRound className="size-3" />
              <span>{t("llm.apiKeyNotSet")}</span>
            </div>
          )}
          <div className="relative">
            <input
              type={revealKey ? "text" : "password"}
              value={draft.api_key}
              onChange={(e) => {
                setDraft((d) => ({ ...d, api_key: e.target.value }));
                setDirty(true);
              }}
              placeholder={
                cfg.data.has_api_key
                  ? t("llm.apiKeyPlaceholderKeepExisting")
                  : t("llm.apiKeyPlaceholderNew")
              }
              data-testid="llm-api-key-input"
              className="w-full rounded border px-2 py-1 pr-7 text-xs"
              style={inputStyle}
            />
            <button
              type="button"
              onClick={() => setRevealKey((v) => !v)}
              disabled={!draft.api_key}
              title={
                revealKey ? t("llm.apiKeyHide") : t("llm.apiKeyReveal")
              }
              aria-label={
                revealKey ? t("llm.apiKeyHide") : t("llm.apiKeyReveal")
              }
              data-testid="llm-api-key-reveal"
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30"
            >
              {revealKey ? (
                <EyeOff className="size-3" />
              ) : (
                <Eye className="size-3" />
              )}
            </button>
          </div>
        </label>

        <label className="flex w-full flex-col gap-1 text-[11px]">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">{t("llm.modelLabel")}</span>
            <button
              type="button"
              onClick={handleRefreshModels}
              title={t("llm.refreshModels")}
              disabled={baseUrlEmpty}
              className="text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              <RefreshCw
                className={`size-3 ${providerModelsMut.isPending ? "animate-spin" : ""}`}
              />
            </button>
          </div>
          {/* Combobox: typeable input + datalist dropdown of provider's
              actual models. We never list our own opinions here. */}
          <input
            list="llm-model-options"
            value={draft.model}
            onChange={(e) => {
              setDraft((d) => ({ ...d, model: e.target.value }));
              setDirty(true);
            }}
            placeholder={t("llm.modelPlaceholder")}
            data-testid="llm-model-input"
            className="rounded border px-2 py-1 text-xs"
            style={inputStyle}
          />
          <datalist id="llm-model-options">
            {(providerModelsMut.data?.models ?? []).map((m) => (
              <option key={m.id} value={m.id} />
            ))}
          </datalist>
          {providerModelsMut.data?.error ? (
            <span className="text-[10px] text-muted-foreground">
              {t("llm.modelsListFailed")}
            </span>
          ) : providerModelsMut.data?.models?.length ? (
            <span className="text-[10px] text-emerald-700 dark:text-emerald-400">
              {t("llm.modelsLoaded", { count: providerModelsMut.data.models.length })}
            </span>
          ) : (
            <span className="text-[10px] text-muted-foreground">
              {t("llm.modelsRefreshHint")}
            </span>
          )}
        </label>

        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || update.isPending || !!saveBlockReason}
            title={saveBlockReason || ""}
            data-testid="llm-save"
            className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-colors disabled:opacity-50"
            style={{
              background: "var(--accent-soft, rgba(91,122,156,0.18))",
              color: "var(--accent-2, #34495e)",
              borderColor: "var(--accent, #5b7a9c)",
            }}
          >
            {update.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
            {t("llm.save")}
          </button>
          <button
            type="button"
            onClick={() =>
              testMut.mutate({
                base_url: draft.base_url,
                api_key: draft.api_key,
                model: draft.model,
              })
            }
            disabled={
              testMut.isPending ||
              // Need *some* key — either typed or saved.
              (!draft.api_key && !cfg.data.has_api_key) ||
              baseUrlEmpty
            }
            data-testid="llm-test"
            className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-accent/30 disabled:opacity-50"
            style={{ borderColor: "var(--line)" }}
            title={
              !draft.api_key && !cfg.data.has_api_key
                ? t("llm.testNeedsKey")
                : ""
            }
          >
            {testMut.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
            {t("llm.test")}
          </button>
        </div>

        {testMut.data && (
          <div
            className="rounded border p-2 text-[11px]"
            style={{
              borderColor: testMut.data.ok
                ? "var(--ok, #198754)"
                : "var(--destructive, #c0392b)",
              background: "var(--bg-1)",
            }}
            data-testid="llm-test-result"
          >
            {testMut.data.ok ? (
              <>
                <div style={{ color: "var(--ok, #198754)" }}>
                  ✓ {t("llm.testOk", { latency: testMut.data.latency_ms })}
                </div>
                {testMut.data.preview && (
                  <div className="mt-1 text-muted-foreground">
                    {t("llm.testPreview")}: {testMut.data.preview}
                  </div>
                )}
                {testMut.data.capabilities && (
                  <div
                    className="mt-2 space-y-1"
                    data-testid="llm-capability-profile"
                  >
                    <div className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                      {t("llm.capabilities")}
                    </div>
                    {testMut.data.capabilities.checks.map((check) => (
                      <div
                        key={check.name}
                        className="flex items-start gap-1.5"
                        data-testid={`llm-capability-${check.name}`}
                      >
                        {check.ok ? (
                          <CheckCircle2 className="mt-0.5 size-3 shrink-0 text-emerald-600" />
                        ) : (
                          <ShieldAlert className="mt-0.5 size-3 shrink-0 text-amber-600" />
                        )}
                        <div className="min-w-0">
                          <div style={{ color: "var(--ink)" }}>
                            {capabilityLabel(check.name, t)}
                          </div>
                          <div className="break-words text-muted-foreground">
                            {check.detail}
                            {check.latency_ms ? ` · ${check.latency_ms}ms` : ""}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="text-destructive">
                ✗ {t("llm.testFailed")}: {testMut.data.error}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

function capabilityLabel(name: string, t: (k: string) => string): string {
  switch (name) {
    case "chat_completions":
      return t("llm.capabilityChat");
    case "streaming":
      return t("llm.capabilityStreaming");
    case "chat_tools":
      return t("llm.capabilityTools");
    case "responses":
      return t("llm.capabilityResponses");
    case "hosted_web_search":
      return t("llm.capabilityHostedSearch");
    default:
      return name;
  }
}

function ApiKeyStatusRow({
  onReplace,
  t,
}: {
  onReplace: () => void;
  t: (k: string) => string;
}) {
  return (
    <div className="flex items-center gap-1 text-[10px]">
      <CheckCircle2 className="size-3 text-emerald-600 dark:text-emerald-400" />
      <span className="text-emerald-700 dark:text-emerald-300">
        {t("llm.apiKeyConfigured")}
      </span>
      <button
        type="button"
        onClick={onReplace}
        className="ml-auto text-muted-foreground hover:text-foreground"
      >
        {t("llm.apiKeyReplace")}
      </button>
    </div>
  );
}

function ThemePill({
  icon,
  label,
  active,
  onClick,
  testid,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  testid: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-pressed={active}
      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors"
      style={{
        background: active
          ? "var(--accent-soft, rgba(91, 122, 156, 0.18))"
          : "transparent",
        color: active ? "var(--accent-2, #34495e)" : "var(--ink, #2a2823)",
        borderColor: active ? "var(--accent, #5b7a9c)" : "var(--line)",
        fontWeight: active ? 500 : 400,
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ---------------- AI call trace (Phase 3 Stage 1 Step 1.6) ----------------

function AICallTracePanel(): React.ReactNode {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<string | null>(null);
  const events = useQuery({
    queryKey: ["ai-call-events"],
    queryFn: () => listAICallEvents(50),
    staleTime: 10_000,
  });

  return (
    <Section title={t("settings.advanced.aiCallTitle")}>
      <div className="w-full text-xs text-muted-foreground">
        {t("settings.advanced.aiCallBlurb")}
      </div>

      <div className="mt-3 flex w-full items-center justify-between">
        <span className="text-[11px] text-muted-foreground">
          {events.data
            ? t("settings.advanced.eventCount", {
                count: events.data.events.length,
              })
            : ""}
        </span>
        <button
          type="button"
          onClick={() => events.refetch()}
          className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
          title={t("settings.advanced.refresh")}
        >
          <RefreshCw
            className={`size-3 ${events.isFetching ? "animate-spin" : ""}`}
          />
          {t("settings.advanced.refresh")}
        </button>
      </div>

      <div
        className="mt-2 w-full rounded border"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        {!events.data && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.advanced.loading")}
          </div>
        )}
        {events.data && events.data.events.length === 0 && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.advanced.empty")}
          </div>
        )}
        {events.data &&
          // Most recent first (store returns ASC; reverse for display).
          [...events.data.events].reverse().map((ev) => (
            <AICallRow
              key={ev.id}
              event={ev}
              isExpanded={expanded === ev.id}
              onToggle={() =>
                setExpanded(expanded === ev.id ? null : ev.id)
              }
              t={t}
            />
          ))}
      </div>
    </Section>
  );
}

function AICallRow({
  event,
  isExpanded,
  onToggle,
  t,
}: {
  event: AICallEvent;
  isExpanded: boolean;
  onToggle: () => void;
  t: (k: string, v?: Record<string, unknown>) => string;
}): React.ReactNode {
  const p = event.payload;
  const isError = !!p.error;
  return (
    <div
      className="border-b last:border-b-0 px-2 py-1.5 text-[11px] cursor-pointer hover:bg-accent/10"
      style={{ borderColor: "var(--line)" }}
      onClick={onToggle}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono" style={{ color: "var(--ink-mute)" }}>
          {event.ts.slice(11, 19)}
        </span>
        <span
          className="rounded px-1.5"
          style={{
            background: isError
              ? "rgba(192,57,43,0.15)"
              : "var(--accent-tint-2)",
            color: isError
              ? "var(--destructive,#c0392b)"
              : "var(--ink)",
          }}
        >
          {p.role || "unknown"}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {p.model}
        </span>
        <span className="text-muted-foreground">
          {p.latency_ms}ms · {p.prompt_chars}→{p.response_chars} chars
          {p.tool_calls ? ` · ${p.tool_calls} tools` : ""}
          {p.stream ? " · stream" : ""}
        </span>
      </div>
      {isExpanded && (
        <div className="mt-1.5 space-y-1.5 pl-2 text-[10.5px]">
          {p.error && (
            <div
              className="rounded px-1.5 py-1"
              style={{
                background: "rgba(192,57,43,0.1)",
                color: "var(--destructive,#c0392b)",
              }}
            >
              <strong>{t("settings.advanced.error")}:</strong> {p.error}
            </div>
          )}
          {p.input_preview && (
            <div>
              <strong>{t("settings.advanced.input")}:</strong>{" "}
              <span className="font-mono text-muted-foreground">
                {p.input_preview}
              </span>
            </div>
          )}
          {p.output_preview && (
            <div>
              <strong>{t("settings.advanced.output")}:</strong>{" "}
              <span className="font-mono text-muted-foreground">
                {p.output_preview}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ------------ Mining task status (Phase 3 Stage 3 §3.8) -----------

function MiningTaskStatusPanel(): React.ReactNode {
  const { t } = useTranslation();
  const tasks = useQuery({
    queryKey: ["mining-tasks"],
    queryFn: listMiningTasks,
    staleTime: 10_000,
  });

  return (
    <Section title={t("settings.advanced.miningTitle")}>
      <div className="w-full text-xs text-muted-foreground">
        {t("settings.advanced.miningBlurb")}
      </div>

      <div
        className="mt-2 w-full rounded border"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        {!tasks.data && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.advanced.loading")}
          </div>
        )}
        {tasks.data && tasks.data.length === 0 && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.advanced.miningEmpty")}
          </div>
        )}
        {tasks.data &&
          tasks.data.map((task) => (
            <MiningTaskRow key={task.id} task={task} t={t} />
          ))}
      </div>
    </Section>
  );
}

function MiningTaskRow({
  task,
  t,
}: {
  task: MiningTaskSummary;
  t: (k: string, v?: Record<string, unknown>) => string;
}): React.ReactNode {
  const statusColor = (() => {
    switch (task.status) {
      case "running":
        return { bg: "var(--accent-tint-2)", fg: "var(--ink)" };
      case "paused-by-backlog":
        return {
          bg: "rgba(217,151,77,0.15)",
          fg: "var(--ink)",
        };
      case "paused-by-user":
      default:
        return {
          bg: "rgba(100,100,100,0.1)",
          fg: "var(--ink-mute)",
        };
    }
  })();
  return (
    <div
      className="border-b last:border-b-0 px-2 py-1.5 text-[11px]"
      style={{ borderColor: "var(--line)" }}
      data-testid={`mining-task-row-${task.id}`}
    >
      <div className="flex items-center gap-2">
        <span
          className="rounded px-1.5"
          style={{ background: statusColor.bg, color: statusColor.fg }}
          data-testid={`mining-task-status-${task.id}`}
        >
          {t(`settings.advanced.miningStatus.${task.status}`)}
        </span>
        <span className="font-medium">{task.name}</span>
        <span className="text-muted-foreground">
          {t("settings.advanced.miningPendingCount", {
            n: task.pending_drafts,
            max: task.max_pending_drafts ?? "∞",
          })}
        </span>
      </div>
      {task.status === "paused-by-backlog" && (
        <div className="mt-1 pl-2 text-[10.5px] text-muted-foreground">
          {t("settings.advanced.miningPausedByBacklog")}
        </div>
      )}
    </div>
  );
}
