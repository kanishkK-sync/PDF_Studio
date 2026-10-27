"use client";

import { motion } from "framer-motion";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;

  return (
    <motion.button
      type="button"
      aria-label="Toggle light and dark theme"
      onClick={() => setTheme(theme === "light" ? "dark" : "light")}
      whileHover={interactions.hover}
      whileTap={interactions.tap}
      transition={microTransition}
      className="inline-flex size-10 items-center justify-center rounded-full border border-border bg-surface text-foreground"
    >
      <Sun aria-hidden="true" className="hidden size-5 dark:block" />
      <Moon aria-hidden="true" className="block size-5 dark:hidden" />
    </motion.button>
  );
}