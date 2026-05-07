/**
 * Phase 1 D slice 1 — theme state manager.
 *
 * Three-way preference (Light / Dark / System) per the
 * `new-3-dark.jsx` design. Persisted to localStorage; "System" listens
 * to `prefers-color-scheme` and re-applies on change.
 *
 * Apply by setting `document.documentElement.dataset.theme`; CSS
 * tokens under `[data-theme="dark"]` (defined in globals.css per
 * ADR-0019) take effect on the same frame.
 */

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "knowlet.theme.v1";

/** Read the user's saved preference; defaults to `system`. */
export function getThemePreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const v = window.localStorage.getItem(STORAGE_KEY);
  if (v === "light" || v === "dark" || v === "system") return v;
  return "system";
}

/** What's actually being rendered right now (resolved against system). */
export function resolveTheme(pref: ThemePreference): "light" | "dark" {
  if (pref !== "system") return pref;
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/** Apply a resolved theme to `<html>`. CSS does the rest. */
export function applyTheme(resolved: "light" | "dark"): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = resolved;
}

/** Persist the user preference + apply it. */
export function setThemePreference(pref: ThemePreference): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, pref);
  applyTheme(resolveTheme(pref));
  // Notify any subscribers in this tab — `storage` events fire only
  // for OTHER tabs, so we dispatch a CustomEvent for in-tab listeners
  // (Settings dialog radios, header icon swap, etc.).
  window.dispatchEvent(
    new CustomEvent<ThemeChangeDetail>("knowlet:theme-changed", {
      detail: { preference: pref, resolved: resolveTheme(pref) },
    }),
  );
}

export interface ThemeChangeDetail {
  preference: ThemePreference;
  resolved: "light" | "dark";
}

/**
 * Subscribe to system-pref changes (only relevant when preference =
 * "system"). Caller decides whether to re-apply.
 */
export function watchSystemTheme(
  cb: (resolved: "light" | "dark") => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = (e: MediaQueryListEvent) => {
    cb(e.matches ? "dark" : "light");
  };
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** Bootstrap on app load: apply persisted preference + start watching
 *  system changes if pref is "system". Caller invokes once at the
 *  React root. */
export function bootThemeManager(): () => void {
  const pref = getThemePreference();
  applyTheme(resolveTheme(pref));
  // Always watch — when user switches to "system" we'll need it; if
  // they're on light/dark explicitly, watcher fires but apply does
  // nothing because we re-resolve.
  return watchSystemTheme(() => {
    const cur = getThemePreference();
    applyTheme(resolveTheme(cur));
    // Notify in-tab listeners so they can refresh their displayed
    // resolved state (system change should update icon if the user is
    // on "system" preference).
    if (cur === "system") {
      window.dispatchEvent(
        new CustomEvent<ThemeChangeDetail>("knowlet:theme-changed", {
          detail: { preference: cur, resolved: resolveTheme(cur) },
        }),
      );
    }
  });
}
