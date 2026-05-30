import { invoke, isTauri } from "@tauri-apps/api/core";
import { CheckCircle2, FolderOpen, HardDrive, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type RecentVaultSummary = {
  name: string;
  parent: string;
  path: string;
};

type NewVaultPreviewStatus =
  | "ready"
  | "existing_empty"
  | "existing_non_empty"
  | "existing_vault"
  | "invalid";

type NewVaultPreview = {
  status: NewVaultPreviewStatus;
  name: string;
  parent: string;
  target: string;
  can_create: boolean;
  requires_empty_dir_confirmation: boolean;
  message: string;
  suggested_name: string | null;
};

type BusyAction = "create" | "open" | `recent:${string}` | null;

export function isDesktopVaultLauncherPage(): boolean {
  return new URLSearchParams(window.location.search).has("desktop-launcher");
}

export function DesktopVaultLauncher(): React.ReactNode {
  const [recent, setRecent] = useState<RecentVaultSummary[]>([]);
  const [name, setName] = useState("My Knowlet");
  const [parent, setParent] = useState("");
  const [preview, setPreview] = useState<NewVaultPreview | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState("");
  const tauriAvailable = isTauri();

  const canAskPreview = parent.trim().length > 0 && name.trim().length > 0;
  const createLabel = useMemo(() => {
    if (preview?.status === "existing_empty") return "Use Empty Folder";
    return "Create Vault";
  }, [preview]);

  const refreshRecent = useCallback(async () => {
    setError("");
    if (!tauriAvailable) return;
    try {
      setRecent(await invoke<RecentVaultSummary[]>("desktop_recent_vaults"));
    } catch (err) {
      setError(String(err));
    }
  }, [tauriAvailable]);

  useEffect(() => {
    if (!tauriAvailable) return;
    void refreshRecent();
  }, [refreshRecent, tauriAvailable]);

  useEffect(() => {
    if (!tauriAvailable) {
      setPreview(null);
      return;
    }
    if (!canAskPreview) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void invoke<NewVaultPreview>("desktop_preview_new_vault", { parent, name })
        .then((next) => {
          if (!cancelled) setPreview(next);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(String(err));
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [canAskPreview, name, parent, tauriAvailable]);

  async function chooseParent() {
    setError("");
    if (!tauriAvailable) {
      setError("Vault creation is available in the Knowlet desktop app.");
      return;
    }
    try {
      const selected = await invoke<string | null>("desktop_choose_vault_parent");
      if (selected) setParent(selected);
    } catch (err) {
      setError(String(err));
    }
  }

  async function openExisting() {
    setBusy("open");
    setError("");
    if (!tauriAvailable) {
      setError("Vault opening is available in the Knowlet desktop app.");
      setBusy(null);
      return;
    }
    try {
      await invoke("desktop_pick_existing_vault");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  async function openRecent(path: string) {
    setBusy(`recent:${path}`);
    setError("");
    if (!tauriAvailable) {
      setError("Vault opening is available in the Knowlet desktop app.");
      setBusy(null);
      return;
    }
    try {
      await invoke("desktop_open_vault", { path });
    } catch (err) {
      setError(String(err));
      await refreshRecent();
    } finally {
      setBusy(null);
    }
  }

  async function createVault() {
    if (!preview?.can_create) return;
    setBusy("create");
    setError("");
    if (!tauriAvailable) {
      setError("Vault creation is available in the Knowlet desktop app.");
      setBusy(null);
      return;
    }
    try {
      await invoke("desktop_create_vault", {
        parent,
        name,
        allowExistingEmpty: preview.requires_empty_dir_confirmation,
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  const createDisabled = !preview?.can_create || busy !== null;

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl grid-cols-[minmax(0,0.86fr)_minmax(340px,0.64fr)] gap-8 px-10 py-9">
        <section className="flex min-h-0 flex-col">
          <div className="mb-7 flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-xl border border-[var(--line)] bg-[var(--panel)]">
              <HardDrive className="size-5 text-[var(--accent-2)]" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-normal">Choose a Vault</h1>
              <p className="mt-1 text-sm text-[var(--ink-soft)]">
                Open an existing knowledge base, or create a new folder for one.
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
            <div className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3">
              <div className="text-sm font-medium">Recent Vaults</div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={refreshRecent}
                title="Refresh recent vaults"
              >
                <RefreshCw className="size-4" />
              </Button>
            </div>
            <div className="max-h-[440px] overflow-auto p-2">
              {recent.length === 0 ? (
                <div className="px-3 py-12 text-center text-sm text-[var(--ink-soft)]">
                  No recent vaults yet.
                </div>
              ) : (
                recent.map((vault) => (
                  <button
                    key={vault.path}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition hover:bg-[var(--accent-tint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    onClick={() => void openRecent(vault.path)}
                    disabled={busy !== null}
                  >
                    <FolderOpen className="size-4 shrink-0 text-[var(--accent-2)]" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{vault.name}</span>
                      <span className="block truncate text-xs text-[var(--ink-soft)]">
                        {vault.parent}
                      </span>
                    </span>
                    {busy === `recent:${vault.path}` && (
                      <span className="text-xs text-[var(--ink-soft)]">Opening...</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-4">
          <div className="rounded-lg border border-[var(--line)] bg-[var(--card-paper)] p-4">
            <div className="mb-4 flex items-center gap-2">
              <Plus className="size-4 text-[var(--accent-2)]" />
              <h2 className="text-base font-semibold">Create New Vault</h2>
            </div>

            <label className="mb-3 block">
              <span className="mb-1.5 block text-xs font-medium text-[var(--ink-soft)]">
                Vault name
              </span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Research Notes"
              />
            </label>

            <label className="mb-3 block">
              <span className="mb-1.5 block text-xs font-medium text-[var(--ink-soft)]">
                Location
              </span>
              <div className="flex gap-2">
                <Input
                  value={parent}
                  onChange={(event) => setParent(event.target.value)}
                  placeholder="/Users/you/Documents"
                />
                <Button type="button" variant="outline" onClick={chooseParent}>
                  Choose
                </Button>
              </div>
            </label>

            {preview && (
              <div
                className={[
                  "mb-4 rounded-md border px-3 py-2 text-xs leading-relaxed",
                  preview.can_create
                    ? "border-[var(--line)] bg-[var(--accent-tint)] text-[var(--ink)]"
                    : "border-[var(--warn)]/40 bg-[var(--panel)] text-[var(--ink)]",
                ].join(" ")}
              >
                <div>{preview.message}</div>
                {preview.suggested_name && (
                  <button
                    type="button"
                    className="mt-2 font-medium text-[var(--accent-2)] underline-offset-4 hover:underline"
                    onClick={() => setName(preview.suggested_name ?? name)}
                  >
                    Use "{preview.suggested_name}" instead
                  </button>
                )}
              </div>
            )}

            <Button
              type="button"
              className="w-full"
              disabled={createDisabled}
              onClick={() => void createVault()}
            >
              {busy === "create" ? "Creating..." : createLabel}
            </Button>
          </div>

          <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4">
            <div className="mb-3 flex items-center gap-2">
              <FolderOpen className="size-4 text-[var(--accent-2)]" />
              <h2 className="text-base font-semibold">Open Existing Vault</h2>
            </div>
            <p className="mb-4 text-sm text-[var(--ink-soft)]">
              Select a folder that already contains a Knowlet `.knowlet` directory.
            </p>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => void openExisting()}
              disabled={busy !== null}
            >
              {busy === "open" ? "Opening..." : "Choose Folder"}
            </Button>
          </div>

          {error && (
            <div className="rounded-lg border border-[var(--danger)]/40 bg-[var(--panel)] px-3 py-2 text-sm text-[var(--ink)]">
              {error}
            </div>
          )}

          {preview?.can_create && (
            <div className="mt-auto flex items-center gap-2 text-xs text-[var(--ink-soft)]">
              <CheckCircle2 className="size-3.5 text-[var(--good)]" />
              <span>Vault name and location are ready.</span>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
