/**
 * IME composition guard for keyboard handlers on `<input>` /
 * `<textarea>` elements.
 *
 * Why this exists (per project memory `feedback_verify_ui_before_handoff`
 * + Phase 1 A `InlineEditInput` lessons):
 *
 *   Chinese / Japanese / Korean input methods deliver keystrokes via
 *   `compositionstart` / `compositionupdate` / `compositionend` events.
 *   While the user is mid-composition, pressing Enter or Esc means
 *   "confirm pinyin candidate" or "cancel candidate" — NOT "submit
 *   form" or "close panel". A naïve `if (e.key === "Enter") submit()`
 *   handler kills the half-typed input.
 *
 * Browsers expose two equally reliable signals:
 *   - `e.nativeEvent.isComposing` (synthetic React event)
 *   - `e.keyCode === 229` (legacy IME marker on Enter during composition)
 *
 * Either one is sufficient; we check both so the guard works across
 * browser quirks (Safari's webkit layer occasionally emits one but
 * not the other).
 *
 * USAGE:
 *
 *   <input
 *     onKeyDown={imeSafeKeyHandler((e) => {
 *       if (e.key === "Enter") onSubmit();
 *       if (e.key === "Escape") onCancel();
 *     })}
 *   />
 *
 * The wrapped handler is called ONLY when no composition is active.
 * If the user IS composing, the event is allowed to propagate (so the
 * IME's own confirmation handling proceeds normally).
 *
 * RULE: every `<input>` and `<textarea>` with an `onKeyDown` that
 * keys on Enter / Esc / `,` / arrows MUST go through this wrapper.
 * The matching ESLint rule (TODO) bans raw `onKeyDown` on those
 * elements; until it lands this file is the social contract.
 */

import type { KeyboardEvent } from "react";

export function imeSafeKeyHandler<T extends HTMLElement>(
  handler: (e: KeyboardEvent<T>) => void,
): (e: KeyboardEvent<T>) => void {
  return (e: KeyboardEvent<T>) => {
    // Both signals catch IME composition. `nativeEvent.isComposing` is
    // the modern path; `keyCode === 229` is the legacy fallback that
    // some Safari + Chinese-IME combinations still emit.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    handler(e);
  };
}
