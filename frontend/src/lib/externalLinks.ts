import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";

const RAPID_ACTIVATION_WINDOW_MS = 300;

export type ExternalLinkFailure = "invalid-url" | "open-failed";

type ExternalLinkHandlerOptions = {
  onFailure: (failure: ExternalLinkFailure | null) => void;
};

function isInternalLink(anchor: HTMLAnchorElement, href: string): boolean {
  return (
    href.startsWith("#") ||
    href.startsWith("wikilink:") ||
    href.startsWith("tag:") ||
    anchor.classList.contains("kn-wikilink") ||
    anchor.classList.contains("kn-inline-tag")
  );
}

function isHttpUrl(href: string): boolean {
  try {
    const parsed = new URL(href);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function hardenWebLink(anchor: HTMLAnchorElement): void {
  anchor.target = "_blank";
  const rel = new Set(anchor.rel.split(/\s+/).filter(Boolean));
  rel.add("noopener");
  rel.add("noreferrer");
  anchor.rel = [...rel].join(" ");
}

/**
 * Routes absolute HTTP(S) links to the system browser in the desktop app.
 * The browser build keeps native target=_blank behavior. Internal Knowlet
 * links and downloads stay with their existing handlers.
 */
export function installExternalLinkHandler({
  onFailure,
}: ExternalLinkHandlerOptions): () => void {
  const recentActivations = new Map<
    string,
    { activatedAt: number; token: symbol }
  >();
  const expiryTimers = new Set<number>();

  const forgetAfterCooldown = (
    href: string,
    activation: { activatedAt: number; token: symbol },
  ) => {
    const timer = window.setTimeout(() => {
      expiryTimers.delete(timer);
      if (recentActivations.get(href)?.token === activation.token) {
        recentActivations.delete(href);
      }
    }, RAPID_ACTIVATION_WINDOW_MS);
    expiryTimers.add(timer);
  };

  const onClick = (event: MouseEvent) => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;

    const anchor = event.target.closest<HTMLAnchorElement>("a[href]");
    if (!anchor || anchor.hasAttribute("download")) return;

    const href = anchor.getAttribute("href")?.trim() ?? "";
    if (!href) {
      event.preventDefault();
      return;
    }
    if (isInternalLink(anchor, href)) return;

    if (!isHttpUrl(href)) {
      event.preventDefault();
      onFailure("invalid-url");
      return;
    }

    hardenWebLink(anchor);
    onFailure(null);
    if (!isTauri()) return;

    event.preventDefault();

    const now = Date.now();
    const previousActivation = recentActivations.get(href);
    if (
      previousActivation !== undefined &&
      now - previousActivation.activatedAt < RAPID_ACTIVATION_WINDOW_MS
    ) {
      return;
    }
    const activation = { activatedAt: now, token: Symbol(href) };
    recentActivations.set(href, activation);

    const failCurrentActivation = () => {
      if (recentActivations.get(href)?.token !== activation.token) return;
      recentActivations.delete(href);
      onFailure("open-failed");
    };

    try {
      void openUrl(href).then(
        () => {
          if (recentActivations.get(href)?.token !== activation.token) return;
          forgetAfterCooldown(href, activation);
        },
        failCurrentActivation,
      );
    } catch {
      failCurrentActivation();
    }
  };

  document.addEventListener("click", onClick, true);
  return () => {
    document.removeEventListener("click", onClick, true);
    for (const timer of expiryTimers) window.clearTimeout(timer);
    recentActivations.clear();
  };
}
