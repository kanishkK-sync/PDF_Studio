"use client";

import { motion } from "framer-motion";
import { FileText, X } from "lucide-react";
import { formatBytes } from "@/lib/format";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type FileChipProps = {
  name: string;
  size: number;
  disabled?: boolean;
  onRemove: () => void;
};

export function FileChip({
  name,
  size,
  disabled = false,
  onRemove,
}: FileChipProps) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;

  return (
    <div className="flex min-w-0 items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-soft">
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-raised text-accent-violet">
        <FileText aria-hidden="true" className="size-5" />
      </span>

      <div className="min-w-0 flex-1">
        <p title={name} className="truncate text-sm font-medium text-foreground">
          {name}
        </p>
        <p className="text-xs text-muted">{formatBytes(size)}</p>
      </div>

      <motion.button
        type="button"
        disabled={disabled}
        aria-label={`Remove ${name}`}
        onClick={onRemove}
        whileHover={disabled ? undefined : interactions.hover}
        whileTap={disabled ? undefined : interactions.tap}
        transition={microTransition}
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-foreground disabled:cursor-not-allowed disabled:opacity-50"
      >
        <X aria-hidden="true" className="size-4" />
      </motion.button>
    </div>
  );
}