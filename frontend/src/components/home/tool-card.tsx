"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import type { PointerEvent } from "react";
import { categories, toolIcons, type Tool } from "@/config/tools";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export function ToolCard({ tool }: { tool: Tool }) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const Icon = toolIcons[tool.icon];
  const categoryLabel = categories.find((c) => c.id === tool.category)?.label;
  const titleId = `tool-${tool.slug}-title`;
  const categoryId = `tool-${tool.slug}-category`;
  const descriptionId = `tool-${tool.slug}-description`;
  const describedBy = categoryLabel
    ? `${categoryId} ${descriptionId}`
    : descriptionId;

  // Feeds the cursor-following glow. Sets CSS variables directly, so moving
  // the pointer never re-renders. Skipped under reduced motion.
  function handlePointerMove(event: PointerEvent<HTMLAnchorElement>) {
    if (reduced) return;
    const card = event.currentTarget;
    const rect = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${event.clientX - rect.left}px`);
    card.style.setProperty("--my", `${event.clientY - rect.top}px`);
  }

  return (
    <motion.div
      className="h-full"
      whileHover={interactions.hover}
      whileTap={interactions.tap}
      transition={microTransition}
    >
      <Link
        href={`/tools/${tool.slug}`}
        aria-labelledby={titleId}
        aria-describedby={describedBy}
        onPointerMove={handlePointerMove}
        className="group relative flex h-full flex-col gap-5 overflow-hidden rounded-xl border border-border bg-surface p-6 shadow-soft transition-shadow duration-300 hover:shadow-glow-strong"
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(280px_circle_at_var(--mx,50%)_var(--my,50%),var(--accent-violet-deco),transparent_70%)] opacity-0 transition-opacity duration-300 group-hover:opacity-15 dark:group-hover:opacity-30"
        />

        <span className="relative inline-flex size-12 items-center justify-center rounded-lg border border-border bg-surface-raised text-accent-violet transition-transform duration-300 ease-overshoot motion-safe:group-hover:-rotate-6 motion-safe:group-hover:scale-110">
          <Icon aria-hidden="true" className="size-6" />
        </span>

        <div className="relative flex flex-col gap-2">
          {categoryLabel && (
            <span
              id={categoryId}
              className="self-start rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-muted"
            >
              {categoryLabel}
            </span>
          )}
          <h3
            id={titleId}
            className="font-display text-xl tracking-tight text-foreground"
          >
            {tool.title}
          </h3>
          <p id={descriptionId} className="text-sm leading-relaxed text-muted">
            {tool.description}
          </p>
        </div>
      </Link>
    </motion.div>
  );
}