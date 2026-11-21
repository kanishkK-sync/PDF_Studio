"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <button
      type="button"
      aria-label="Toggle light and dark theme"
      onClick={() => setTheme(theme === "light" ? "dark" : "light")}
      className="inline-flex size-10 items-center justify-center rounded-full border border-border bg-surface text-foreground"
    >
      <Sun aria-hidden="true" className="hidden size-5 dark:block" />
      <Moon aria-hidden="true" className="block size-5 dark:hidden" />
    </button>
  );
}
