/**
 * Motion system: pure data, no React.
 *
 * Every easing curve, duration, stagger value and variant lives here.
 * Components import from this file and never hard-code a curve.
 *
 * Reduced motion: each variant has an explicit `...Reduced` twin that animates
 * opacity only. Components pick between the two with the reduced-motion hook
 * (separate file). Nothing here reads the user's preference.
 */

import type { Transition, Variants } from "framer-motion";

/* ── Easing ───────────────────────────────────────────────────────────────── */

type Bezier = [number, number, number, number];

// These three curves are mirrored in src/app/globals.css (--ease-smooth-out,
// --ease-soft-in-out, --ease-overshoot). Change them together with globals.css.
//
// `overshoot` is for transforms only (scale, translate, rotate), never for
// opacity or color: a curve that overshoots 1 makes opacity and color flicker
// past their target.
export const smoothOut: Bezier = [0.22, 1, 0.36, 1];
export const softInOut: Bezier = [0.45, 0, 0.2, 1];
export const overshoot: Bezier = [0.34, 1.56, 0.64, 1];

/* ── Durations (seconds) ──────────────────────────────────────────────────── */

export const durations = {
  fast: 0.25,
  base: 0.5,
  slow: 0.8,
  slower: 1.2,
} as const;

/* ── Stagger (seconds between siblings) ───────────────────────────────────── */

export const stagger = {
  base: 0.08,
  grid: 0.06,
} as const;

/* ── Shared internals ─────────────────────────────────────────────────────── */

// Small head start for children of a stagger container.
const containerDelay = 0.1;

// Used by every reduced twin: opacity-only, fast, soft in-out.
const opacityOnly: Transition = {
  duration: durations.fast,
  ease: softInOut,
};

/* ── Variants ─────────────────────────────────────────────────────────────── */

// Parent that staggers its children. Has no visual state of its own.
export const staggerContainer: Variants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: stagger.base,
      delayChildren: containerDelay,
    },
  },
};

export const staggerContainerReduced: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: opacityOnly },
};

export const fadeRise: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: durations.slow, ease: smoothOut },
  },
};

export const fadeRiseReduced: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: opacityOnly },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.94 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: durations.slow, ease: smoothOut },
  },
};

export const scaleInReduced: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: opacityOnly },
};

// Enter-only page transition: there is deliberately no exit state.
export const pageTransition: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: durations.base, ease: smoothOut },
  },
};

export const pageTransitionReduced: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: opacityOnly },
};

/* ── Micro-interactions (hover / press) ───────────────────────────────────── */

// Components should also pass this as their `transition` prop so un-hover uses the same curve.
export const microTransition: Transition = {
  duration: durations.fast,
  ease: overshoot,
};

// Each target carries its own transition, so components never set one.
// Use as: whileHover={microInteractions.hover} whileTap={microInteractions.tap}
export const microInteractions = {
  hover: { y: -6, scale: 1.015, transition: microTransition },
  tap: { scale: 0.97, transition: microTransition },
};

// No transforms under reduced motion.
export const microInteractionsReduced = {
  hover: {},
  tap: {},
};

/* ── Ambient loop (drifting orbs and similar) ─────────────────────────────── */

export const defaultAmbientDuration = 24;

// Repeating, mirrored, infinite. Callers must not render ambient loops at all
// under reduced motion; this helper has no reduced twin on purpose.
export function ambientLoop(duration: number): Transition {
  return {
    duration,
    ease: softInOut,
    repeat: Infinity,
    repeatType: "mirror",
  };
}

/* ── Scroll reveal viewport ───────────────────────────────────────────────── */

export const defaultViewport = { once: true, amount: 0.2 };