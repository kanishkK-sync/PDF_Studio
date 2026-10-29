"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { useId, useRef, type KeyboardEvent } from "react";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export type ChoiceOption<T extends string> = {
  id: T;
  title: string;
  description: string;
  // Small pill next to the title, for example "Recommended".
  badge?: string;
};

type OptionGroupProps<T extends string> = {
  label: string;
  options: readonly ChoiceOption<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  // Columns from the sm breakpoint up; always one column on narrow screens.
  columns?: 2 | 3;
};

export function OptionGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled = false,
  columns = 3,
}: OptionGroupProps<T>) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const baseId = useId();
  const labelId = `${baseId}-label`;
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Arrow keys move focus and selection together, like native radio buttons.
  function choose(index: number) {
    const option = options[index];
    if (!option) return;
    onChange(option.id);
    buttonRefs.current[index]?.focus();
  }

  function handleKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    const count = options.length;
    let next: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (index + 1) % count;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (index - 1 + count) % count;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = count - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    choose(next);
  }

  return (
    <div className="flex flex-col gap-3">
      <p id={labelId} className="text-sm font-medium text-foreground">
        {label}
      </p>

      <div
        role="radiogroup"
        aria-labelledby={labelId}
        aria-disabled={disabled}
        className={cn(
          "grid gap-3",
          columns === 2 ? "sm:grid-cols-2" : "sm:grid-cols-3",
        )}
      >
        {options.map((option, index) => {
          const selected = option.id === value;
          const titleId = `${baseId}-${option.id}-title`;
          const descriptionId = `${baseId}-${option.id}-description`;

          return (
            <motion.button
              key={option.id}
              ref={(node) => {
                buttonRefs.current[index] = node;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-labelledby={titleId}
              aria-describedby={descriptionId}
              tabIndex={selected ? 0 : -1}
              disabled={disabled}
              onClick={() => {
                onChange(option.id);
              }}
              onKeyDown={(event) => {
                handleKeyDown(event, index);
              }}
              whileHover={disabled ? undefined : interactions.hover}
              whileTap={disabled ? undefined : interactions.tap}
              transition={microTransition}
              className={cn(
                "flex h-full flex-col gap-3 rounded-xl border-2 p-4 text-left disabled:cursor-not-allowed disabled:opacity-60",
                selected
                  ? "border-accent-violet bg-surface-raised shadow-glow"
                  : "border-border bg-surface shadow-soft",
              )}
            >
              <span className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full border-2",
                    selected
                      ? "border-accent-violet bg-accent-violet text-background"
                      : "border-border",
                  )}
                >
                  {selected && <Check className="size-3" />}
                </span>
                <span
                  id={titleId}
                  className="flex min-w-0 flex-wrap items-center gap-2 font-display text-lg text-foreground"
                >
                  <span>{option.title}</span>
                  {option.badge && (
                    <span className="rounded-full border border-accent-violet px-2 py-0.5 font-sans text-xs font-medium text-accent-violet">
                      {option.badge}
                    </span>
                  )}
                </span>
              </span>
              <span
                id={descriptionId}
                className="text-sm leading-relaxed text-muted"
              >
                {option.description}
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}