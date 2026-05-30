import { Download, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { DesktopUpdater } from "./useDesktopUpdater";

interface Props {
  updater: DesktopUpdater;
  onClick: () => void;
}

export function DesktopUpdateButton({ updater, onClick }: Props) {
  const { t } = useTranslation();
  if (!updater.supported) return null;

  const busy = updater.phase === "checking" || updater.phase === "downloading";
  const title = updater.hasUpdate
    ? t("desktopUpdate.headerAvailable")
    : t("desktopUpdate.headerCheck");

  return (
    <Button
      variant={updater.hasUpdate ? "secondary" : "ghost"}
      size="icon"
      aria-label={title}
      title={title}
      onClick={onClick}
      data-testid="header-desktop-update-button"
      data-update-state={updater.phase}
    >
      <span className="relative inline-flex">
        {busy ? (
          <Loader2 className="size-4 animate-spin" />
        ) : updater.hasUpdate ? (
          <Download className="size-4" />
        ) : (
          <RefreshCw className="size-4" />
        )}
        {updater.hasUpdate && (
          <span
            className="absolute -right-1 -top-1 size-2 rounded-full bg-primary"
            data-testid="header-desktop-update-dot"
          />
        )}
      </span>
    </Button>
  );
}
