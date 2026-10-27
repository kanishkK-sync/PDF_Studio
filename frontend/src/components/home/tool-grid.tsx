"use client";

import {
  AnimatePresence,
  motion,
  useInView,
  type Transition,
} from "framer-motion";
import { useRef } from "react";
import { CategoryTabs } from "@/components/home/category-tabs";
import { ToolCard } from "@/components/home/tool-card";
import { categories, tools } from "@/config/tools";
import {
  defaultViewport,
  durations,
  fadeRise,
  fadeRiseReduced,
  softInOut,
  staggerContainer,
  staggerContainerReduced,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";
import { useUiStore, type CategoryFilter } from "@/store/ui-store";

// "All" is injected here; the registry only holds the four real categories.
const tabs: readonly { id: CategoryFilter; label: string }[] = [
  { id: "all", label: "All" },
  ...categories,
];

// Layout (reflow) and exit animations. Under reduced motion both are instant.
const layoutTransition: Transition = {
  duration: durations.base,
  ease: softInOut,
};
const instant: Transition = { duration: 0 };
const exitFull = {
  opacity: 0,
  transition: { duration: durations.fast, ease: softInOut },
};
const exitReduced = { opacity: 0, transition: instant };

export function ToolGrid() {
  const reduced = useReducedMotionSafe();
  const activeCategory = useUiStore((s) => s.activeCategory);
  const setActiveCategory = useUiStore((s) => s.setActiveCategory);

  // The observed element is the tabpanel, which is never re-keyed. The motion
  // list below is keyed on `reduced`, and a re-keyed element would be left
  // unobserved by useInView.
  const panelRef = useRef<HTMLDivElement>(null);
  const inView = useInView(panelRef, defaultViewport);

  const visibleTools =
    activeCategory === "all"
      ? tools
      : tools.filter((tool) => tool.category === activeCategory);

  return (
    <div>
      <CategoryTabs
        categories={tabs}
        activeId={activeCategory}
        onChange={setActiveCategory}
      />

      <div
        ref={panelRef}
        role="tabpanel"
        id="tool-panel"
        aria-labelledby={`tab-${activeCategory}`}
        className="mt-8"
      >
        <motion.ul
          key={reduced ? "reduced" : "full"}
          variants={reduced ? staggerContainerReduced : staggerContainer}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="relative grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        >
          <AnimatePresence mode="popLayout">
            {visibleTools.map((tool) => (
              <motion.li
                key={tool.slug}
                layout
                variants={reduced ? fadeRiseReduced : fadeRise}
                exit={reduced ? exitReduced : exitFull}
                transition={reduced ? instant : layoutTransition}
                className="list-none"
              >
                <ToolCard tool={tool} />
              </motion.li>
            ))}
          </AnimatePresence>
        </motion.ul>
      </div>
    </div>
  );
}