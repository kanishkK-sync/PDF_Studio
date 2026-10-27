"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { pageTransition, pageTransitionReduced } from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export function PageTransition({ children }: { children: ReactNode }) {
  const reduced = useReducedMotionSafe();

  return (
    <motion.div
      key={reduced ? "reduced" : "full"}
      variants={reduced ? pageTransitionReduced : pageTransition}
      initial="hidden"
      animate="visible"
    >
      {children}
    </motion.div>
  );
}