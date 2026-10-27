"use client";

import { motion } from "framer-motion";
import { useId } from "react";
import { ambientLoop } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type ProgressBarProps = {
  label: string;
  // A number 0-100 is determinate. Omit it (or pass null) for indeterminate.
  value?: number | null;
};

const SWEEP_SECONDS = 1.2;

export function ProgressBar({ label, value = null }: ProgressBarProps) {
  const reduced = useReducedMotionSafe();
  const labelId = useId();
  const determinate = typeof value === "number" && Number.isFinite(value);
  const percent = determinate ? Math.min(100, Math.max(0, Math.round(value))) : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span id={labelId} className="text-foreground">
          {label}
        </span>
        {determinate && (
          <span className="tabular-nums text-muted" aria-hidden="true">
            {percent}%
          </span>
        )}
      </div>

      <div
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={determinate ? percent : undefined}
        className="relative h-3 w-full overflow-hidden rounded-full bg-surface-raised"
      >
        {determinate ? (
          <span
            className="absolute inset-y-0 left-0 rounded-full bg-(image:--gradient-accent) transition-[width] duration-300 ease-smooth-out"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <motion.span
            key={reduced ? "reduced" : "full"}
            initial={reduced ? undefined : { x: "0%" }}
            animate={reduced ? undefined : { x: "150%" }}
            transition={reduced ? undefined : ambientLoop(SWEEP_SECONDS)}
            className={cn(
              "absolute inset-y-0 left-0 rounded-full",
              reduced
                ? "w-full bg-deco-violet/40"
                : "w-2/5 bg-(image:--gradient-accent)",
            )}
          />
        )}
      </div>
    </div>
  );
}