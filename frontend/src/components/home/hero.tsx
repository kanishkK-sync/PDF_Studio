"use client";

import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";
import type { MouseEvent } from "react";
import { useSmoothScroll } from "@/components/providers/smooth-scroll-provider";
import {
  ambientLoop,
  durations,
  fadeRise,
  fadeRiseReduced,
  microInteractions,
  microInteractionsReduced,
  microTransition,
  staggerContainer,
  staggerContainerReduced,
} from "@/lib/motion";
import { scrollToTarget } from "@/lib/scroll-to";
import { useBackendStatus, type BackendStatus } from "@/lib/use-backend-status";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

const pulseTransition = ambientLoop(durations.slower);

const statusStyles: Record<BackendStatus, { dot: string; label: string }> = {
  checking: { dot: "bg-accent-amber", label: "Checking backend…" },
  connected: { dot: "bg-emerald-600", label: "Backend connected" },
  offline: { dot: "bg-red-600", label: "Backend offline" },
};

export function Hero() {
  const reduced = useReducedMotionSafe();
  const status = useBackendStatus();
  const lenisRef = useSmoothScroll();

  const variants = reduced ? fadeRiseReduced : fadeRise;
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const { dot, label } = statusStyles[status];

  function handleExploreClick(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    if (scrollToTarget("tools", lenisRef.current)) {
      event.preventDefault();
    }
  }

  return (
    <section
      aria-labelledby="hero-heading"
      className="mx-auto max-w-6xl px-gutter pb-section pt-16 text-center sm:pt-24"
    >
      <motion.div
        key={reduced ? "reduced" : "full"}
        variants={reduced ? staggerContainerReduced : staggerContainer}
        initial="hidden"
        animate="visible"
        className="flex flex-col items-center"
      >
        <motion.h1
          id="hero-heading"
          variants={variants}
          className="max-w-4xl text-balance font-display text-5xl tracking-tight sm:text-6xl lg:text-7xl"
        >
          Your PDFs, handled{" "}
          <span className="bg-[image:var(--gradient-accent-text)] bg-clip-text text-transparent">
            beautifully
          </span>
          .
        </motion.h1>

        <motion.p
          variants={variants}
          className="mt-6 max-w-2xl text-pretty text-lg text-muted sm:text-xl"
        >
          Free, private, and runs entirely on your machine.
        </motion.p>

        <motion.div variants={variants} className="mt-10">
          <motion.a
            href="#tools"
            onClick={handleExploreClick}
            whileHover={interactions.hover}
            whileTap={interactions.tap}
            transition={microTransition}
            className="inline-flex items-center gap-2 rounded-full bg-foreground px-7 py-3.5 text-base font-semibold text-background shadow-glow transition-shadow duration-300 hover:shadow-glow-strong"
          >
            Explore Tools
            <ArrowDown aria-hidden="true" className="size-4" />
          </motion.a>
        </motion.div>

        <motion.div variants={variants} className="mt-8">
          <div
            role="status"
            className="inline-flex items-center gap-2.5 rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-muted"
          >
            <span className="relative inline-flex size-2.5">
              <motion.span
                key={reduced ? "reduced" : "full"}
                aria-hidden="true"
                className={`absolute inset-0 rounded-full ${dot}`}
                animate={reduced ? undefined : { scale: [1, 2.4], opacity: [0.5, 0] }}
                transition={reduced ? undefined : pulseTransition}
              />
              <span
                aria-hidden="true"
                className={`relative size-2.5 rounded-full ${dot}`}
              />
            </span>
            <span>{label}</span>
          </div>
        </motion.div>
      </motion.div>
    </section>
  );
}