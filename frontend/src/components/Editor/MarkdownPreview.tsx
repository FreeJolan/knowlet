/**
 * Phase 1 B markdown preview pane — read-only render of the same body
 * the CodeMirror editor holds. We use react-markdown + remark-gfm because
 * remark/rehype is the standard pipeline for plug-in extensions
 * (KaTeX in slice 5, Mermaid in slice 6, wiki-link transformer in slice 7).
 *
 * Styling matches the kn-paper aesthetic: serif body, muted hr, monospace
 * code, var(--ink) text, var(--accent-soft) blockquote stripe. We don't
 * use Tailwind's `prose` class because we already control the design
 * tokens; importing typography would fight our scale.
 */

import "katex/dist/katex.min.css";

import type { ComponentProps } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { MermaidBlock } from "./MermaidBlock";
import { rehypeSourceLine } from "./rehypeSourceLine";
import { remarkWikilink } from "./remarkWikilink";

/**
 * Marker scheme for wiki-link href values produced by `remarkWikilink`.
 * Anything starting with this prefix is an Obsidian-style internal
 * `[[Title]]` or `[[Title#Heading]]` link — handled by PreviewAnchor
 * via a custom event so AppShell can resolve title→noteId and switch.
 */
const WIKILINK_SCHEME = "wikilink:";

type Props = { value: string };

/**
 * Code block renderer: detect ```mermaid fences and route them to the
 * MermaidBlock; everything else falls through to react-markdown's
 * default <code> output (CSS in globals.css / .kn-md gives it a styled
 * <pre> wrapper). The `inline` flag distinguishes ` `inline code` ` from
 * fenced blocks — only fenced blocks have a language class.
 */
function PreviewCode({
  className,
  children,
  ...rest
}: ComponentProps<"code"> & { inline?: boolean }) {
  // react-markdown gives the language as `language-<name>` in className.
  const langMatch = /language-(\w+)/.exec(className ?? "");
  const lang = langMatch?.[1];
  if (lang === "mermaid") {
    const source = String(children ?? "").replace(/\n$/, "");
    return <MermaidBlock source={source} />;
  }
  return (
    <code className={className} {...rest}>
      {children}
    </code>
  );
}

/**
 * Rewrite vault-relative attachment paths to the URL the FastAPI backend
 * serves them at. The note file on disk stays portable (`![](_attachments/x.png)`
 * works in Obsidian / Finder); only the live preview swaps in `/files/`.
 *
 * Accepts both plain `_attachments/x.png` and Obsidian-style
 * `./_attachments/x.png` shapes. External http(s) and data: URLs pass
 * through untouched.
 */
function resolveImgSrc(src: string | undefined): string | undefined {
  if (!src) return src;
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  if (src.startsWith("/")) return src;
  const normalized = src.replace(/^\.\//, "");
  if (normalized.startsWith("_attachments/")) return `/files/${normalized}`;
  return src;
}

function PreviewImg({ src, alt, ...rest }: ComponentProps<"img">) {
  return <img {...rest} src={resolveImgSrc(src)} alt={alt ?? ""} loading="lazy" />;
}

/**
 * Anchor renderer:
 *
 *  - http(s) links open in a new tab. Without this, a click navigates the
 *    SPA away from the current note (the user reported this — the entire
 *    /<note-id> route is replaced).
 *  - Empty / placeholder hrefs (e.g. the cursor sitting in `[txt]()`)
 *    become preventDefault no-ops so they don't reload the page.
 *  - Internal `[[Title]]` wikilinks land here in slice 7 too — for now
 *    everything that doesn't look like a URL is treated as a no-op so
 *    the page never navigates away from the editor unexpectedly.
 */
/**
 * Parse a `wikilink:Target#heading` href produced by remarkWikiLink.
 * The package URL-encodes the target, so decode before splitting.
 */
function parseWikilinkHref(href: string): { title: string; hash: string } | null {
  if (!href.startsWith(WIKILINK_SCHEME)) return null;
  let payload = href.slice(WIKILINK_SCHEME.length);
  try {
    payload = decodeURIComponent(payload);
  } catch {
    // leave raw if not decodable
  }
  const hashIdx = payload.indexOf("#");
  if (hashIdx === -1) return { title: payload, hash: "" };
  return {
    title: payload.slice(0, hashIdx),
    hash: payload.slice(hashIdx + 1),
  };
}

function PreviewAnchor({ href, children, ...rest }: ComponentProps<"a">) {
  // Internal Obsidian-style [[Title]] / [[Title#Heading]] — dispatch to
  // AppShell which handles resolution + cross-note navigation.
  if (typeof href === "string" && href.startsWith(WIKILINK_SCHEME)) {
    const parsed = parseWikilinkHref(href);
    return (
      <a
        {...rest}
        href={href}
        data-wikilink="true"
        onClick={(e) => {
          e.preventDefault();
          if (!parsed) return;
          window.dispatchEvent(
            new CustomEvent("knowlet:open-wikilink", { detail: parsed }),
          );
        }}
      >
        {children}
      </a>
    );
  }
  const isExternal =
    typeof href === "string" && /^(https?:\/\/|mailto:)/i.test(href);
  if (isExternal) {
    return (
      <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }
  return (
    <a
      {...rest}
      href={href ?? "#"}
      onClick={(e) => {
        e.preventDefault();
      }}
    >
      {children}
    </a>
  );
}

export function MarkdownPreview({ value }: Props) {
  return (
    <div
      // overflow + height live on the wrapper in NoteView (so the
      // scroll-sync listener sees scroll events at a stable element);
      // this inner div is just the styled body.
      className="kn-md prose-paper px-2 py-2"
      style={{ color: "var(--ink)" }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkWikilink]}
        rehypePlugins={[
          // rehype-slug: auto-id every heading so [[Title#Heading]] can
          // scroll to that heading after the note switches.
          rehypeSlug,
          // rehypeSourceLine: stamp `data-source-line="N"` on every
          // rendered element so the split-mode scroll sync can map
          // CodeMirror line numbers ↔ preview DOM nodes.
          rehypeSourceLine,
          rehypeKatex,
        ]}
        components={{
          a: PreviewAnchor,
          img: PreviewImg,
          code: PreviewCode,
        }}
        // react-markdown's default URL sanitizer rewrites any non-
        // http(s)/mailto scheme to "" — including our custom
        // `wikilink:`. Pass through wikilink + attachment URLs;
        // delegate everything else to the default sanitizer.
        urlTransform={(url, key) => {
          if (url.startsWith("wikilink:")) return url;
          if (key === "src" && url.startsWith("_attachments/")) return url;
          return defaultUrlTransform(url);
        }}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}
