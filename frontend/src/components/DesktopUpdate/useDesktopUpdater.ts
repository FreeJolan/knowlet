import { isTauri } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import {
  check,
  type DownloadEvent,
  type Update,
} from "@tauri-apps/plugin-updater";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type DesktopUpdatePhase =
  | "unsupported"
  | "idle"
  | "checking"
  | "up-to-date"
  | "available"
  | "downloading"
  | "installing"
  | "restarting"
  | "error";

export interface DesktopUpdateInfo {
  currentVersion: string;
  version: string;
  date?: string;
  body?: string;
}

export interface DesktopUpdateProgress {
  downloadedBytes: number;
  totalBytes?: number;
}

export interface DesktopUpdater {
  supported: boolean;
  phase: DesktopUpdatePhase;
  update: DesktopUpdateInfo | null;
  progress: DesktopUpdateProgress | null;
  error: string | null;
  lastCheckedAt: Date | null;
  hasUpdate: boolean;
  isBusy: boolean;
  checkForUpdate: (options?: { silent?: boolean }) => Promise<void>;
  installUpdate: () => Promise<void>;
  clearError: () => void;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Unknown update error";
}

function isDesktopRuntime(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

export function useDesktopUpdater(): DesktopUpdater {
  const [supported, setSupported] = useState(false);
  const [phase, setPhase] = useState<DesktopUpdatePhase>("unsupported");
  const [update, setUpdate] = useState<DesktopUpdateInfo | null>(null);
  const [progress, setProgress] = useState<DesktopUpdateProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const updateRef = useRef<Update | null>(null);
  const autoCheckedRef = useRef(false);

  const replaceUpdate = useCallback((next: Update | null) => {
    const previous = updateRef.current;
    if (previous && previous !== next) {
      void previous.close().catch(() => undefined);
    }
    updateRef.current = next;
    setUpdate(
      next
        ? {
            currentVersion: next.currentVersion,
            version: next.version,
            date: next.date,
            body: next.body,
          }
        : null,
    );
  }, []);

  useEffect(() => {
    const desktop = isDesktopRuntime();
    setSupported(desktop);
    setPhase(desktop ? "idle" : "unsupported");
    return () => {
      void updateRef.current?.close().catch(() => undefined);
      updateRef.current = null;
    };
  }, []);

  const checkForUpdate = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!isDesktopRuntime()) {
        setSupported(false);
        setPhase("unsupported");
        return;
      }

      setSupported(true);
      setPhase("checking");
      setProgress(null);
      if (!options?.silent) setError(null);

      try {
        const next = await check();
        setLastCheckedAt(new Date());
        replaceUpdate(next);
        setPhase(next ? "available" : "up-to-date");
      } catch (err) {
        replaceUpdate(null);
        setLastCheckedAt(new Date());
        if (options?.silent) {
          setPhase("idle");
          return;
        }
        setError(errorMessage(err));
        setPhase("error");
      }
    },
    [replaceUpdate],
  );

  useEffect(() => {
    if (!supported || autoCheckedRef.current) return;
    autoCheckedRef.current = true;
    const timer = window.setTimeout(() => {
      void checkForUpdate({ silent: true });
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [checkForUpdate, supported]);

  const installUpdate = useCallback(async () => {
    if (!isDesktopRuntime()) {
      setSupported(false);
      setPhase("unsupported");
      return;
    }

    let candidate = updateRef.current;
    if (!candidate) {
      await checkForUpdate();
      candidate = updateRef.current;
    }
    if (!candidate) return;

    setPhase("downloading");
    setError(null);
    setProgress({ downloadedBytes: 0 });

    let downloadedBytes = 0;
    try {
      await candidate.downloadAndInstall((event: DownloadEvent) => {
        if (event.event === "Started") {
          downloadedBytes = 0;
          setProgress({
            downloadedBytes: 0,
            totalBytes: event.data.contentLength,
          });
        }
        if (event.event === "Progress") {
          downloadedBytes += event.data.chunkLength;
          setProgress((prev) => ({
            downloadedBytes,
            totalBytes: prev?.totalBytes,
          }));
        }
        if (event.event === "Finished") {
          setPhase("installing");
        }
      });
      setPhase("restarting");
      await relaunch();
    } catch (err) {
      setError(errorMessage(err));
      setPhase("error");
    }
  }, [checkForUpdate]);

  const isBusy =
    phase === "checking" ||
    phase === "downloading" ||
    phase === "installing" ||
    phase === "restarting";
  const hasUpdate =
    phase === "available" ||
    phase === "downloading" ||
    phase === "installing" ||
    phase === "restarting";

  return useMemo(
    () => ({
      supported,
      phase,
      update,
      progress,
      error,
      lastCheckedAt,
      hasUpdate,
      isBusy,
      checkForUpdate,
      installUpdate,
      clearError: () => setError(null),
    }),
    [
      supported,
      phase,
      update,
      progress,
      error,
      lastCheckedAt,
      hasUpdate,
      isBusy,
      checkForUpdate,
      installUpdate,
    ],
  );
}
