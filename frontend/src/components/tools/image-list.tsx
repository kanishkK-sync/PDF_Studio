"use client";

import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { formatBytes } from "@/lib/format";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { FileEntry } from "@/lib/use-multi-file-job";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type ImageListProps = {
  entries: readonly FileEntry[];
  label?: string;
  showPreviews?: boolean;
  disabled?: boolean;
  onMove: (id: string, delta: -1 | 1) => void;
  onRemove: (id: string) => void;
};

type FocusKind = "up" | "down" | "remove";
type FocusTarget = { id: string; kind: FocusKind };

type IconButtonProps = {
  id: string;
  label: string;
  onClick: () => void;
  // Looks and reports as unavailable (first row's "up", last row's "down")
  // but stays focusable, so keyboard focus is never lost on a boundary.
  unavailable?: boolean;
  disabled?: boolean;
  children: ReactNode;
};

function IconButton({
  id,
  label,
  onClick,
  unavailable = false,
  disabled = false,
  children,
}: IconButtonProps) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const inactive = disabled || unavailable;

  return (
    <motion.button
      id={id}
      type="button"
      aria-label={label}
      aria-disabled={unavailable ? true : undefined}
      disabled={disabled}
      onClick={onClick}
      whileHover={inactive ? undefined : interactions.hover}
      whileTap={inactive ? undefined : interactions.tap}
      transition={microTransition}
      className={cn(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-foreground disabled:cursor-not-allowed disabled:opacity-50",
        unavailable && "opacity-40",
      )}
    >
      {children}
    </motion.button>
  );
}

export function ImageList({
  entries,
  label = "Selected images, in page order",
  showPreviews = true,
  disabled = false,
  onMove,
  onRemove,
}: ImageListProps) {
  const baseId = useId();
  const focusTargetRef = useRef<FocusTarget | null>(null);

  // Moving or removing re-renders the rows, which can drop focus. After the
  // list has changed, put focus back where the user was working.
  useEffect(() => {
    const target = focusTargetRef.current;
    if (!target) return;
    focusTargetRef.current = null;
    document.getElementById(`${baseId}-${target.id}-${target.kind}`)?.focus();
  }, [entries, baseId]);

  function handleMove(id: string, index: number, delta: -1 | 1) {
    const target = index + delta;
    if (target < 0 || target >= entries.length) return;
    focusTargetRef.current = { id, kind: delta === -1 ? "up" : "down" };
    onMove(id, delta);
  }

  function handleRemove(id: string, index: number) {
    const next = index + 1 < entries.length ? entries[index + 1] : undefined;
    const previous = index > 0 ? entries[index - 1] : undefined;
    const neighbour = next ?? previous;
    focusTargetRef.current = neighbour
      ? { id: neighbour.id, kind: "remove" }
      : null;
    onRemove(id);
  }

  return (
    <ol aria-label={label} className="flex flex-col gap-3">
      {entries.map((entry, index) => {
        const name = entry.file.name;
        return (
          <li
            key={entry.id}
            className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-surface p-3 shadow-soft sm:flex-row sm:items-center"
          >
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <span
                aria-hidden="true"
                className="w-6 shrink-0 text-center text-sm tabular-nums text-muted"
              >
                {index + 1}
              </span>
              {showPreviews && <span
                aria-hidden="true"
                className="size-14 shrink-0 rounded-lg border border-border bg-surface-raised bg-cover bg-center"
                style={{ backgroundImage: `url("${entry.previewUrl}")` }}
              />}
              <div className="min-w-0 flex-1">
                <p
                  title={name}
                  className="truncate text-sm font-medium text-foreground"
                >
                  {name}
                </p>
                <p className="text-xs text-muted">
                  {formatBytes(entry.file.size)}
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-end gap-1">
              <IconButton
                id={`${baseId}-${entry.id}-up`}
                label={`Move ${name} up`}
                unavailable={index === 0}
                disabled={disabled}
                onClick={() => {
                  handleMove(entry.id, index, -1);
                }}
              >
                <ArrowUp aria-hidden="true" className="size-4" />
              </IconButton>
              <IconButton
                id={`${baseId}-${entry.id}-down`}
                label={`Move ${name} down`}
                unavailable={index === entries.length - 1}
                disabled={disabled}
                onClick={() => {
                  handleMove(entry.id, index, 1);
                }}
              >
                <ArrowDown aria-hidden="true" className="size-4" />
              </IconButton>
              <IconButton
                id={`${baseId}-${entry.id}-remove`}
                label={`Remove ${name}`}
                disabled={disabled}
                onClick={() => {
                  handleRemove(entry.id, index);
                }}
              >
                <X aria-hidden="true" className="size-4" />
              </IconButton>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
