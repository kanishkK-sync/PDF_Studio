import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      shadow: ["soft", "glow", "glow-strong"],
      ease: ["smooth-out", "soft-in-out", "overshoot"],
      spacing: ["gutter", "section"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}