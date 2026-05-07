/**
 * Phase 1 D slice 1 — shadcn-style HoverCard primitive wrapper.
 *
 * Mirror of the standard shadcn/ui hover-card pattern: re-exports
 * Radix's HoverCard primitives with our project's class conventions.
 */

import * as HoverCardPrimitive from "@radix-ui/react-hover-card";
import * as React from "react";

const HoverCard = HoverCardPrimitive.Root;
const HoverCardTrigger = HoverCardPrimitive.Trigger;

const HoverCardContent = React.forwardRef<
  React.ElementRef<typeof HoverCardPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof HoverCardPrimitive.Content>
>(({ className, align = "center", sideOffset = 6, ...props }, ref) => (
  <HoverCardPrimitive.Portal>
    <HoverCardPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={
        // Local-token-driven styling so the hover card inherits paper /
        // dark theme correctly. shadcn's stock classes use
        // tw-{primary|popover} which we do have via globals.css token
        // bridge, but for a content card that should look distinctly
        // like an inline preview (not a popover dropdown) we skip the
        // `bg-popover` opacity dance and use card tokens directly.
        "z-50 rounded-md border outline-none " +
        "shadow-md " +
        (className ?? "")
      }
      style={{
        background: "var(--card, #fbf8f1)",
        borderColor: "var(--line)",
        color: "var(--ink)",
      }}
      {...props}
    />
  </HoverCardPrimitive.Portal>
));
HoverCardContent.displayName = HoverCardPrimitive.Content.displayName;

export { HoverCard, HoverCardContent, HoverCardTrigger };
