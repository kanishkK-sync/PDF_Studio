"use client";

import { motion } from "framer-motion";
import { ambientLoop, defaultAmbientDuration } from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

const loopTransition = ambientLoop(defaultAmbientDuration);

const orbs = [
  {
    id: "violet",
    className:
      "-left-48 -top-48 bg-[radial-gradient(closest-side,var(--accent-violet-deco),transparent)]",
    animate: { x: ["-6%", "6%"], y: ["-4%", "8%"] },
  },
  {
    id: "magenta",
    className:
      "-right-56 top-1/3 bg-[radial-gradient(closest-side,var(--accent-magenta-deco),transparent)]",
    animate: { x: ["5%", "-7%"], y: ["6%", "-6%"] },
  },
  {
    id: "amber",
    className:
      "-bottom-64 left-1/4 bg-[radial-gradient(closest-side,var(--accent-amber-deco),transparent)]",
    animate: { x: ["-8%", "6%"], y: ["4%", "-8%"] },
  },
];

export function AmbientBackground() {
  const reduced = useReducedMotionSafe();

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      {orbs.map((orb) => (
        <motion.div
          key={`${orb.id}-${reduced ? "reduced" : "full"}`}
          className={`absolute size-144 rounded-full opacity-15 dark:opacity-30 ${orb.className}`}
          animate={reduced ? undefined : orb.animate}
          transition={reduced ? undefined : loopTransition}
        />
      ))}
    </div>
  );
}