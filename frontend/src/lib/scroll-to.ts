import type Lenis from "lenis";

// Scrolls to the element with the given id, then focuses it.
// Returns false (and does nothing) when the element doesn't exist.
// Pass `lenisRef.current` from useSmoothScroll(): Lenis when it exists,
// native scrolling otherwise.
export function scrollToTarget(targetId: string, lenis: Lenis | null): boolean {
  const target = document.getElementById(targetId);
  if (!target) return false;

  if (lenis) {
    // Honour the target's own scroll-margin-top, as native scrolling would.
    const offset = -(parseFloat(getComputedStyle(target).scrollMarginTop) || 0);
    lenis.scrollTo(target, { offset });
  } else {
    target.scrollIntoView({ behavior: "auto" });
  }

  // The target has tabIndex={-1}, so it can take focus without a tab stop.
  target.focus({ preventScroll: true });
  return true;
}