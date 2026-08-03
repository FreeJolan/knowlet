/**
 * Rich clipboard paste for the Markdown editor.
 *
 * Browsers expose formatted clipboard content as `text/html`, while
 * CodeMirror deliberately inserts `text/plain`. Convert the HTML to
 * Markdown before it reaches CodeMirror so formatting survives without
 * changing the note's portable Markdown storage format.
 */

import {
  EditorSelection,
  EditorState,
  type Extension,
} from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  emDelimiter: "*",
  strongDelimiter: "**",
});

// Adds GitHub-flavoured tables, task lists and strikethrough support.
turndown.use(gfm);
// The plug-in emits single-tildes, which some Markdown renderers treat as
// literal punctuation. Keep stored notes portable with the common `~~` form.
turndown.addRule("doubleTildeStrikethrough", {
  filter(node) {
    return ["DEL", "S", "STRIKE"].includes(node.nodeName);
  },
  replacement(content) {
    return content.trim() ? `~~${content}~~` : content;
  },
});

const FORMATTED_ELEMENT_SELECTOR = [
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "p",
  "br",
  "strong",
  "b",
  "em",
  "i",
  "s",
  "strike",
  "del",
  "a[href]",
  "blockquote",
  "pre",
  "code",
  "ul",
  "ol",
  "table",
  "img",
].join(",");

function hasBoldStyle(element: HTMLElement): boolean {
  const weight = element.style.fontWeight.trim().toLowerCase();
  if (weight === "bold" || weight === "bolder") return true;
  const numeric = Number.parseInt(weight, 10);
  return !Number.isNaN(numeric) && numeric >= 600;
}

function hasItalicStyle(element: HTMLElement): boolean {
  const style = element.style.fontStyle.trim().toLowerCase();
  return style === "italic" || style.startsWith("oblique");
}

function hasStrikeStyle(element: HTMLElement): boolean {
  const decoration = `${element.style.textDecorationLine} ${element.style.textDecoration}`;
  return decoration.toLowerCase().includes("line-through");
}

function hasMeaningfulFormatting(root: HTMLElement): boolean {
  if (root.querySelector(FORMATTED_ELEMENT_SELECTOR)) return true;
  return Array.from(root.querySelectorAll<HTMLElement>("[style]")).some(
    (element) =>
      hasBoldStyle(element) ||
      hasItalicStyle(element) ||
      hasStrikeStyle(element),
  );
}

/**
 * Clipboard producers such as Google Docs and Microsoft Office often
 * express emphasis with inline CSS on a span instead of semantic tags.
 * Turn those styles into tags that Turndown understands. CSS with no
 * Markdown equivalent (font family, colour, size) is intentionally ignored.
 */
function normalizeInlineStyles(root: HTMLElement): void {
  const styled = Array.from(root.querySelectorAll<HTMLElement>("[style]"));
  for (const element of styled) {
    const tags: string[] = [];
    if (hasBoldStyle(element) && !element.matches("strong, b")) {
      tags.push("strong");
    }
    if (hasItalicStyle(element) && !element.matches("em, i")) {
      tags.push("em");
    }
    if (hasStrikeStyle(element) && !element.matches("s, strike, del")) {
      tags.push("del");
    }
    for (const tag of tags) {
      const wrapper = element.ownerDocument.createElement(tag);
      while (element.firstChild) wrapper.append(element.firstChild);
      element.append(wrapper);
    }
  }
}

function convertHtml(html: string): string | null {
  const document = new DOMParser().parseFromString(html, "text/html");
  const { body } = document;
  if (!hasMeaningfulFormatting(body)) return null;

  body
    .querySelectorAll("script, style, noscript, template, meta, link, title")
    .forEach((element) => element.remove());
  normalizeInlineStyles(body);

  const markdown = turndown.turndown(body).replaceAll("\u00a0", " ").trim();
  return markdown || null;
}

function clipboardMarkdown(data: DataTransfer): string | null {
  // Apps that already provide Markdown should win over their HTML fallback.
  const markdown = data.getData("text/markdown");
  if (markdown) return markdown;

  const html = data.getData("text/html");
  if (!html) return null;
  return convertHtml(html);
}

function insertPaste(view: EditorView, text: string): void {
  const transaction = view.state.changeByRange((range) => ({
    changes: { from: range.from, to: range.to, insert: text },
    range: EditorSelection.cursor(range.from + text.length),
  }));
  view.dispatch(transaction, {
    scrollIntoView: true,
    userEvent: "input.paste",
  });
}

export function richTextPasteExtension(): Extension {
  return EditorView.domEventHandlers({
    paste(event, view) {
      const data = event.clipboardData;
      if (
        !data ||
        event.defaultPrevented ||
        view.state.facet(EditorState.readOnly)
      ) {
        return false;
      }

      // The earlier image-upload extension owns file-backed image pastes.
      // Returning here also prevents an HTML fallback from being inserted
      // alongside an uploaded image if a clipboard exposes both payloads.
      if (
        Array.from(data.items).some(
          (item) => item.kind === "file" && item.type.startsWith("image/"),
        )
      ) {
        return false;
      }

      const markdown = clipboardMarkdown(data);
      if (markdown === null) return false;

      event.preventDefault();
      insertPaste(view, markdown);
      return true;
    },
  });
}
