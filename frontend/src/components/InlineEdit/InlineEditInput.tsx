/**
 * InlineEditInput — single source of truth for "tree row enters edit
 * mode" inputs (rename existing entity, name a new one).
 *
 * Why a shared component:
 *
 * - **IME safety**: Chinese / Japanese / Korean input methods deliver
 *   keystrokes via composition events. A naïve `if (e.key === "Enter")
 *   onSubmit()` handler fires when the user only meant to confirm a
 *   pinyin candidate — committing a half-typed name and dropping focus
 *   onto another row that interprets the next keypress as a tree
 *   shortcut. We guard with `e.nativeEvent.isComposing` so Enter / Esc
 *   inside an active composition is treated as IME confirmation only.
 * - **Focus race vs. arborist remounts**: react-arborist clones row
 *   nodes on every store update. Each clone causes our enclosing
 *   <Row> to remount the input. A useEffect-scheduled focus loses to
 *   the second remount; useLayoutEffect runs synchronously after
 *   commit (before paint), keeping the cursor visible across remounts.
 * - **Event isolation**: Enter / Escape inside the input must not
 *   bubble to the tree container — arborist's keyboard handler treats
 *   Enter as "activate selected node", which would re-open / re-edit
 *   the wrong row. `stopPropagation` on every keydown.
 *
 * Used by file-tree row rename (existing entity) and new-note /
 * new-folder placeholder (pending entity). Any future inline-edit site
 * (note title in editor header, tag rename, etc.) should reuse this.
 */

import { useEffect, useLayoutEffect, useRef } from "react";

export interface InlineEditInputProps {
  /** Initial value the input opens with. */
  initial: string;
  /** Placeholder shown when value is empty. */
  placeholder?: string;
  /** User pressed Enter outside an IME composition. */
  onSubmit: (value: string) => void;
  /** User pressed Esc outside an IME composition, or clicked outside. */
  onCancel: () => void;
  /** Optional test/data hook. */
  dataTestId?: string;
}

export function InlineEditInput({
  initial,
  placeholder,
  onSubmit,
  onCancel,
  dataTestId,
}: InlineEditInputProps) {
  const ref = useRef<HTMLInputElement | null>(null);

  // useLayoutEffect: synchronous focus right after the commit phase, so
  // the input is focused before the browser paints. This wins the race
  // against arborist's row reclone (which would otherwise remount us
  // and discard the first focus call).
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.select();
  });

  // Outside-click cancels. Listen on capture-phase pointerdown to beat
  // Radix's own portal-close chain that fires after pointerup.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onOutside = (e: PointerEvent) => {
      if (e.target instanceof Node && !el.contains(e.target)) onCancel();
    };
    document.addEventListener("pointerdown", onOutside, true);
    return () => document.removeEventListener("pointerdown", onOutside, true);
  }, [onCancel]);

  return (
    <input
      ref={ref}
      type="text"
      defaultValue={initial}
      placeholder={placeholder}
      data-rename-input="true"
      data-testid={dataTestId}
      className="flex-1 rounded-sm border bg-background px-1 text-foreground outline-none ring-2"
      style={{
        // The dogfood report showed caret invisible on the warm paper
        // canvas. Force a high-contrast caret (the dusk-blue ring color)
        // and a clearly visible 2px ring so the user always sees the
        // input is focused even if the cursor itself blinks.
        borderColor: "var(--ring)",
        // @ts-expect-error css custom prop
        "--tw-ring-color": "var(--ring)",
        caretColor: "var(--ring)",
      }}
      onKeyDown={(e) => {
        // IME composition: Enter / Escape are candidate-confirm /
        // candidate-dismiss for the input method, NOT submit / cancel
        // for our component. Don't act on them.
        if (e.nativeEvent.isComposing) {
          // Even during composition we must stop the event from
          // bubbling — arborist's tree-container Enter handler does
          // `setTimeout(() => tree.edit(focusedNode))` which would put
          // a sibling row into edit mode while the user is still
          // composing pinyin.
          e.stopPropagation();
          e.nativeEvent.stopImmediatePropagation();
          return;
        }
        // For non-IME keys: stop the event from reaching arborist's
        // tree-container handlers under all circumstances. React's
        // stopPropagation alone has missed at least one path
        // (arborist's `setTimeout(tree.edit)` fired anyway during the
        // 2026-05-05 dogfood IME test), so use the native form too.
        const stop = () => {
          e.stopPropagation();
          e.nativeEvent.stopImmediatePropagation();
        };
        if (e.key === "Enter") {
          e.preventDefault();
          stop();
          onSubmit(e.currentTarget.value);
        } else if (e.key === "Escape") {
          e.preventDefault();
          stop();
          onCancel();
        } else {
          // Other keys (ArrowUp/Down/Backspace/letter etc.) — keep
          // them inside the input only.
          stop();
        }
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
