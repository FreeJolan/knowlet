import {
  CheckCircle2,
  Download,
  Loader2,
  RefreshCw,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

import type { DesktopUpdater } from "./useDesktopUpdater";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  updater: DesktopUpdater;
}

interface SettingsPanelProps {
  updater: DesktopUpdater;
  onOpenUpdateDialog: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function progressPercent(updater: DesktopUpdater): number | null {
  const progress = updater.progress;
  const total = progress?.totalBytes;
  if (!total) return null;
  return Math.max(
    0,
    Math.min(100, ((progress?.downloadedBytes ?? 0) / total) * 100),
  );
}

function phaseLabel(updater: DesktopUpdater, t: (key: string) => string): string {
  return t(`desktopUpdate.phase.${updater.phase}`);
}

function statusIcon(updater: DesktopUpdater) {
  if (updater.phase === "checking" || updater.phase === "downloading") {
    return <Loader2 className="size-4 animate-spin" />;
  }
  if (updater.phase === "installing" || updater.phase === "restarting") {
    return <RotateCw className="size-4 animate-spin" />;
  }
  if (updater.phase === "available") return <Download className="size-4" />;
  if (updater.phase === "up-to-date") return <CheckCircle2 className="size-4" />;
  return <ShieldCheck className="size-4" />;
}

function UpdateProgress({ updater }: { updater: DesktopUpdater }) {
  const { t } = useTranslation();
  if (updater.phase !== "downloading") return null;
  const percent = progressPercent(updater);
  return (
    <div className="mt-4" data-testid="desktop-update-progress">
      <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{t("desktopUpdate.downloading")}</span>
        <span>
          {percent === null
            ? formatBytes(updater.progress?.downloadedBytes ?? 0)
            : `${Math.round(percent)}%`}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${percent ?? 22}%` }}
        />
      </div>
    </div>
  );
}

export function DesktopUpdateDialog({
  open,
  onOpenChange,
  updater,
}: DialogProps) {
  const { t } = useTranslation();
  const canInstall = updater.phase === "available";
  const canCheck = updater.supported && !updater.isBusy;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="desktop-update-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {statusIcon(updater)}
            {t("desktopUpdate.title")}
          </DialogTitle>
          <DialogDescription>
            {t("desktopUpdate.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div
            className="rounded-lg border p-3"
            style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">
                  {phaseLabel(updater, t)}
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {updater.update
                    ? t("desktopUpdate.versionLine", {
                        current: updater.update.currentVersion,
                        next: updater.update.version,
                      })
                    : updater.lastCheckedAt
                      ? t("desktopUpdate.checkedAt", {
                          time: updater.lastCheckedAt.toLocaleTimeString(),
                        })
                      : t("desktopUpdate.notChecked")}
                </div>
              </div>
              {updater.hasUpdate && (
                <span className="rounded-full bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary">
                  {t("desktopUpdate.availableBadge")}
                </span>
              )}
            </div>
            <UpdateProgress updater={updater} />
          </div>

          {updater.update?.body && (
            <div
              className="max-h-32 overflow-y-auto rounded-lg border p-3 text-xs whitespace-pre-wrap"
              style={{ borderColor: "var(--line)" }}
              data-testid="desktop-update-notes"
            >
              {updater.update.body}
            </div>
          )}

          {updater.error && (
            <div
              className="rounded-lg border px-3 py-2 text-xs"
              style={{
                borderColor: "rgba(192,57,43,0.35)",
                background: "rgba(192,57,43,0.08)",
                color: "var(--destructive,#c0392b)",
              }}
              data-testid="desktop-update-error"
            >
              {updater.error}
            </div>
          )}

          {!updater.supported && (
            <div className="text-xs text-muted-foreground">
              {t("desktopUpdate.unsupportedHint")}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void updater.checkForUpdate()}
              disabled={!canCheck}
              data-testid="desktop-update-check"
            >
              <RefreshCw
                className={updater.phase === "checking" ? "animate-spin" : ""}
              />
              {t("desktopUpdate.check")}
            </Button>
            <Button
              type="button"
              onClick={() => void updater.installUpdate()}
              disabled={!canInstall}
              data-testid="desktop-update-install"
            >
              {updater.phase === "downloading" ||
              updater.phase === "installing" ||
              updater.phase === "restarting" ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Download />
              )}
              {t("desktopUpdate.install")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function DesktopUpdateSettingsPanel({
  updater,
  onOpenUpdateDialog,
}: SettingsPanelProps) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3" data-testid="settings-desktop-update-panel">
      <div
        className="rounded-lg border p-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium">{t("desktopUpdate.title")}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {updater.supported
                ? t("desktopUpdate.settingsHint")
                : t("desktopUpdate.unsupportedHint")}
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              {phaseLabel(updater, t)}
            </div>
          </div>
          <Button
            type="button"
            variant={updater.hasUpdate ? "default" : "outline"}
            onClick={onOpenUpdateDialog}
            data-testid="settings-open-update-dialog"
          >
            {updater.hasUpdate ? <Download /> : <RefreshCw />}
            {updater.hasUpdate
              ? t("desktopUpdate.openInstall")
              : t("desktopUpdate.openCheck")}
          </Button>
        </div>
      </div>
    </div>
  );
}
