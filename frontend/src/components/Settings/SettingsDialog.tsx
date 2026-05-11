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
  Loader2,
  Monitor,
  Moon,
  ShieldAlert,
  Sun,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  disconnect as apiDisconnect,
  getAuthStatus,
  getSyncMode,
  setSyncMode as apiSetSyncMode,
  startConnect,
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
        <div className="mt-2 flex w-full items-center gap-2 text-xs">
          <Loader2 className="size-4 animate-spin" />
          <div>
            <div>{t("driveAuth.connecting")}</div>
            <div className="text-muted-foreground">
              {t("driveAuth.connectingHint")}
            </div>
          </div>
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
