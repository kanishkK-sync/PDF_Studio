"use client";

import Lenis from "lenis";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { durations } from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

// Context value is a ref to the Lenis instance (null when there is none:
// before mount, under reduced motion, or outside the provider). Read
// `.current` inside event handlers or effects, never during render.
const noLenis: RefObject<Lenis | null> = { current: null };

export const SmoothScrollContext = createContext<RefObject<Lenis | null>>(noLenis);

export function useSmoothScroll(): RefObject<Lenis | null> {
  return useContext(SmoothScrollContext);
}

export function SmoothScrollProvider({ children }: { children: ReactNode }) {
  const reduced = useReducedMotionSafe();
  const lenisRef = useRef<Lenis | null>(null);

  useEffect(() => {
    // Reduced motion: no Lenis, no RAF loop. Native scrolling handles the page.
    // If an instance existed, the previous effect's cleanup already destroyed it.
    if (reduced) return;

    // No `easing` option on purpose: no curve is hard-coded outside motion.ts.
    // No `anchors` option either, so native anchor jumps and focus handling are
    // left alone. Keyboard scrolling is never intercepted by Lenis.
    const lenis = new Lenis({ duration: durations.slower });
    lenisRef.current = lenis;

    let frameId = 0;
    function raf(time: number) {
      lenis.raf(time);
      frameId = requestAnimationFrame(raf);
    }
    frameId = requestAnimationFrame(raf);

    return () => {
      cancelAnimationFrame(frameId);
      lenis.destroy();
      lenisRef.current = null;
    };
  }, [reduced]);

  return (
    <SmoothScrollContext.Provider value={lenisRef}>
      {children}
    </SmoothScrollContext.Provider>
  );
}