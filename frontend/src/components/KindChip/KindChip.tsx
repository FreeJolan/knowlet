/**
 * KindChip — knowledge / reference visual indicator (ADR-0029 §4.5).
 *
 * Three modes:
 *   "tag"         — minimal icon, used in dense surfaces (file tree row).
 *                   No label, no border. Hover still shows the tooltip.
 *   "chip"        — icon + label pill, used in the note header where
 *                   the user makes save decisions. ADR-0029 §4.5 meta
 *                   principle: type must be visible on the SAME screen
 *                   the user makes save decisions — never hidden in
 *                   frontmatter / settings.
 *   "chip-quiet"  — icon + label, no border. Drafts / switcher rows.
 *
 * Tooltips are permanent (per ADR-0029 §4.5 "Permanent learnability"
 * amendment 2026-05-16 — dismiss-once onboarding is too brittle; every
 * chip explains itself on hover at any point).
 *
 * Interactive prop: when `onToggle` is supplied, clicking the chip
 * triggers the toggle flow. Demotes (knowledge → reference) get a
 * popover confirmation; promotes are instant. Both are surfaced via
 * the popover so the user gets visual feedback either way.
 */

import { BookOpen, Lightbulb } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { NoteKind } from "@/api/types";

export type KindChipVariant = "tag" | "chip" | "chip-quiet";

interface KindChipProps {
  kind: NoteKind;
  variant?: KindChipVariant;
  /** When provided, the chip is clickable and triggers a kind toggle.
   *  Promotes (reference → knowledge) call `onConfirmedToggle` directly;
   *  demotes (knowledge → reference) open a popover for confirmation. */
  onConfirmedToggle?: (next: NoteKind) => void;
  /** Optional override for the test id (e.g. when multiple chips are
   *  rendered on the same screen and tests need to disambiguate). */
  testId?: string;
}

const ICON_FOR: Record<NoteKind, typeof Lightbulb> = {
  knowledge: Lightbulb,
  reference: BookOpen,
};

export function KindChip({
  kind,
  variant = "chip",
  onConfirmedToggle,
  testId,
}: KindChipProps): React.ReactElement {
  const { t } = useTranslation();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const Icon = ICON_FOR[kind];
  const label = t(`noteKind.${kind}.label`);
  const tooltip = t(`noteKind.${kind}.tooltip`);

  const interactive = !!onConfirmedToggle;
  const next: NoteKind = kind === "knowledge" ? "reference" : "knowledge";

  // Compose styles per variant. Token-driven so light / dark themes
  // both look right. The "tag" variant is intentionally minimal — a
  // file tree row can't afford much pixels.
  const baseStyle: React.CSSProperties = {
    color:
      kind === "knowledge"
        ? "var(--accent-2, #5b7a9c)"
        : "var(--ink-mute, #6b7280)",
  };
  const containerClass = (() => {
    switch (variant) {
      case "tag":
        return "inline-flex items-center";
      case "chip":
        return "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]";
      case "chip-quiet":
        return "inline-flex items-center gap-1 text-[11px]";
    }
  })();
  const chipBorderStyle: React.CSSProperties =
    variant === "chip"
      ? {
          ...baseStyle,
          borderColor: "var(--line)",
          background: "var(--bg-1)",
        }
      : baseStyle;

  const iconSize = variant === "tag" ? "size-3" : "size-3.5";

  const handleClick = (e: React.MouseEvent) => {
    if (!interactive) return;
    e.stopPropagation();
    // ADR-0029 §4.5: knowledge → reference is a downgrade → ALWAYS
    // confirm. reference → knowledge is an upgrade → instant.
    if (kind === "knowledge") {
      setPopoverOpen(true);
    } else {
      onConfirmedToggle?.(next);
    }
  };

  const content = (
    <span
      className={containerClass}
      style={chipBorderStyle}
      data-testid={testId ?? `kind-chip-${kind}`}
      data-kind={kind}
    >
      <Icon className={iconSize} />
      {variant !== "tag" && <span>{label}</span>}
    </span>
  );

  // Wrap with Popover (interactive demote) or just tooltip (anything else).
  if (interactive) {
    return (
      <TooltipProvider delayDuration={350}>
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <Tooltip>
            <TooltipTrigger asChild>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  onClick={handleClick}
                  className="cursor-pointer p-0"
                  data-testid={
                    testId ? `${testId}-button` : `kind-chip-${kind}-button`
                  }
                  aria-label={t("noteKind.toggleAriaLabel", { from: label })}
                >
                  {content}
                </button>
              </PopoverTrigger>
            </TooltipTrigger>
            <TooltipContent side="top">{tooltip}</TooltipContent>
          </Tooltip>
          <PopoverContent
            className="w-72 text-xs"
            data-testid="kind-chip-demote-popover"
          >
            <div className="font-medium mb-1.5">
              {t("noteKind.demote.title")}
            </div>
            <div className="text-muted-foreground mb-2.5">
              {t("noteKind.demote.body")}
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPopoverOpen(false)}
                className="rounded border px-2.5 py-1 text-xs"
                style={{ borderColor: "var(--line)" }}
                data-testid="kind-chip-demote-cancel"
              >
                {t("noteKind.demote.cancel")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setPopoverOpen(false);
                  onConfirmedToggle?.(next);
                }}
                className="rounded border px-2.5 py-1 text-xs"
                style={{
                  borderColor: "var(--destructive, #c0392b)",
                  color: "var(--destructive, #c0392b)",
                }}
                data-testid="kind-chip-demote-confirm"
              >
                {t("noteKind.demote.confirm")}
              </button>
            </div>
          </PopoverContent>
        </Popover>
      </TooltipProvider>
    );
  }

  // Static (non-interactive) chip — tooltip only.
  return (
    <TooltipProvider delayDuration={350}>
      <Tooltip>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent side="top">{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
