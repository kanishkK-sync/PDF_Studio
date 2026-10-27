"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore, type MouseEvent } from "react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { useSmoothScroll } from "@/components/providers/smooth-scroll-provider";
import { scrollToTarget } from "@/lib/scroll-to";
import { cn } from "@/lib/utils";

const SCROLL_THRESHOLD = 16;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("scroll", onChange, { passive: true });
  return () => window.removeEventListener("scroll", onChange);
}

function getSnapshot(): boolean {
  return window.scrollY > SCROLL_THRESHOLD;
}

function getServerSnapshot(): boolean {
  return false;
}

export function Navbar() {
  const scrolled = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const pathname = usePathname();
  const lenisRef = useSmoothScroll();

  // In-page scroll to the tool grid. On other routes the link navigates home.
  function handleToolsClick(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    if (pathname !== "/") return;

    if (scrollToTarget("tools", lenisRef.current)) {
      event.preventDefault();
    }
  }

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-40 border-b transition-[background-color,border-color,backdrop-filter] duration-300 ease-soft-in-out",
        scrolled
          ? "border-border bg-background/70 backdrop-blur-md"
          : "border-transparent bg-transparent",
      )}
    >
      <nav
        aria-label="Primary"
        className={cn(
          "mx-auto flex max-w-6xl items-center justify-between px-gutter transition-[height] duration-300 ease-soft-in-out",
          scrolled ? "h-14" : "h-20",
        )}
      >
        <Link
          href="/"
          className="inline-flex items-center gap-2 rounded-md font-display text-xl tracking-tight text-foreground"
        >
          <span
            aria-hidden="true"
            className="size-2.5 rounded-full bg-[image:var(--gradient-accent)]"
          />
          pdf-studio
        </Link>

        <div className="flex items-center gap-2 sm:gap-4">
          <Link
            href="/#tools"
            onClick={handleToolsClick}
            className="rounded-md px-3 py-2 text-sm font-medium text-muted hover:text-foreground"
          >
            Tools
          </Link>
          <ThemeToggle />
        </div>
      </nav>
    </header>
  );
}