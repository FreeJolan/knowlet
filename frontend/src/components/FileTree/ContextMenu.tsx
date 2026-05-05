/**
 * Lightweight right-click context menu — built on top of shadcn's Popover
 * primitives but anchored to a synthetic point (not a trigger element)
 * because the user clicks a tree row, not a button. We therefore manage
 * open / close state imperatively from the FileTree.
 */

import { useEffect, useRef } from "react";

export interface ContextMenuItem {
  label: string;
  destructive?: boolean;
  onSelect: () => void;
}

export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  // Close on outside click / Escape — the standard popover etiquette.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      role="menu"
      style={{ top: y, left: x }}
      className="fixed z-50 min-w-[180px] rounded-md border bg-popover py-1 text-sm text-popover-foreground shadow-md"
    >
      {items.map((it, i) => (
        <button
          key={i}
          role="menuitem"
          className={`flex w-full items-center px-3 py-1.5 text-left hover:bg-accent hover:text-accent-foreground ${
            it.destructive ? "text-destructive" : ""
          }`}
          onClick={() => {
            it.onSelect();
            onClose();
          }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
