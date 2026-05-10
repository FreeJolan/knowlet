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
import { CloudOff, Monitor, Moon, ShieldAlert, Sun, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getSyncMode,
  getUnpushedStatus,
  pushAllUnpushed,
  setSyncMode as apiSetSyncMode,
  type SyncModeResponse,
  type UnpushedStatus,
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
            <SyncModePicker />
          </div>

          <div className="mt-6">
            <FirstPushPanel />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FirstPushPanel(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery<UnpushedStatus>({
    queryKey: QK.syncUnpushed,
    queryFn: getUnpushedStatus,
    staleTime: 30_000,
  });
  const mut = useMutation({
    mutationFn: pushAllUnpushed,
    onSuccess: () => {
      // Refetch the count immediately so the panel reflects the
      // queued state. The drainer pushes on its own cadence, so
      // the count will further decrease over the next minute or
      // two — also reflected via the standard polling cadence.
      void qc.invalidateQueries({ queryKey: QK.syncUnpushed });
    },
  });
  // Hide the whole panel on boxes without Drive auth — there's
  // nothing the user can do here yet, and an "all good" line on
  // a never-connected vault would mislead them into thinking sync
  // is set up.
  if (!q.data?.authenticated) return null;
  const count = q.data.count;
  const summary =
    count === 0
      ? t("firstPush.summary_zero")
      : t("firstPush.summary", { count });
  return (
    <Section title={t("firstPush.label")}>
      <div className="text-muted-foreground w-full text-xs">{summary}</div>
      {count > 0 && (
        <button
          type="button"
          data-testid="first-push-button"
          disabled={mut.isPending}
          onClick={() => mut.mutate()}
          className="mt-2 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors"
          style={{
            background: "var(--accent-soft, rgba(91, 122, 156, 0.18))",
            color: "var(--accent-2, #34495e)",
            borderColor: "var(--accent, #5b7a9c)",
            fontWeight: 500,
          }}
        >
          {mut.isPending ? t("firstPush.queuing") : t("firstPush.label")}
        </button>
      )}
      {mut.isError && (
        <div className="text-destructive mt-2 w-full text-xs">
          {t("firstPush.failed", {
            detail:
              (mut.error as { detail?: string } | undefined)?.detail ??
              String(mut.error),
          })}
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
