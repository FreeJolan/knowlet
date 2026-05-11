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
  Cloud,
  CloudOff,
  Download,
  Loader2,
  Monitor,
  Moon,
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
  getSyncMode,
  previewImport,
  setSyncMode as apiSetSyncMode,
  startConnect,
  type ImportReportPayload,
  type SyncAuthStatus,
  type SyncModeResponse,
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

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="settings-dialog">
        <DialogHeader>
          <DialogTitle>{t("settings.title")}</DialogTitle>
          <DialogDescription>{t("settings.subtitle")}</DialogDescription>
        </DialogHeader>
        <div className="mt-2">
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

          <div className="mt-6">
            <DriveAuthPanel />
          </div>

          <div className="mt-6">
            <SyncModePicker />
          </div>

          <div className="mt-6">
            <VaultPortabilityPanel />
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
      const label = r.mode === "restore"
        ? t("vaultPortability.restoreDoneShort", {
            count: r.notes_created,
            target: r.target_path,
          })
        : t("vaultPortability.mergeDoneShort", {
            count: r.notes_created,
            renamed: r.notes_renamed,
          });
      setResultText(label);
      setPreview(null);
      setPendingFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
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
            {preview.mode === "restore"
              ? t("vaultPortability.previewRestoreTitle")
              : t("vaultPortability.previewMergeTitle")}
          </div>
          {preview.mode === "restore" ? (
            <ul className="mt-1 list-disc pl-5 text-muted-foreground">
              <li>{t("vaultPortability.previewRestoreNotes", { count: preview.notes_created })}</li>
              <li>{t("vaultPortability.previewRestoreAtt", { count: preview.attachments_copied })}</li>
              {preview.manifest && (
                <li>
                  {t("vaultPortability.previewRestoreFrom", {
                    version: preview.manifest.knowlet_version,
                    at: preview.manifest.exported_at,
                  })}
                </li>
              )}
            </ul>
          ) : (
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
          )}
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
