"use client";

import { motion } from "framer-motion";
import { RotateCcw, TriangleAlert } from "lucide-react";
import type { Ref } from "react";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type ErrorBannerProps = {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  // Lets the workspace move focus here when an error appears.
  ref?: Ref<HTMLDivElement>;
};

export function ErrorBanner({
  message,
  onRetry,
  retryLabel = "Try again",
  ref,
}: ErrorBannerProps) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="flex flex-col gap-4 rounded-xl border border-accent-magenta bg-surface p-4 shadow-soft outline-none sm:flex-row sm:items-center sm:p-5"
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <TriangleAlert
          aria-hidden="true"
          className="mt-0.5 size-5 shrink-0 text-accent-magenta"
        />
        <p className="min-w-0 break-words text-sm leading-relaxed text-foreground">
          {message}
        </p>
      </div>

      {onRetry && (
        <motion.button
          type="button"
          onClick={onRetry}
          whileHover={interactions.hover}
          whileTap={interactions.tap}
          transition={microTransition}
          className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-full border border-border bg-surface-raised px-5 text-sm font-medium text-foreground"
        >
          <RotateCcw aria-hidden="true" className="size-4" />
          {retryLabel}
        </motion.button>
      )}
    </div>
  );
}