"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function ScrollReveal({ children, delay = 0, className = "" }: {
  children: ReactNode; delay?: number; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    if (!node || motion.matches || !("IntersectionObserver" in window)) return;
    // Already-visible and server-rendered content stays visible during hydration.
    if (node.getBoundingClientRect().top < window.innerHeight) return;
    node.dataset.pending = "true";
    const reveal = () => { delete node.dataset.pending; observer.disconnect(); };
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) reveal();
    });
    observer.observe(node);
    node.addEventListener("focusin", reveal);
    motion.addEventListener("change", reveal);
    return () => {
      reveal();
      node.removeEventListener("focusin", reveal);
      motion.removeEventListener("change", reveal);
    };
  }, []);
  return <div ref={ref} className={`scroll-reveal ${className}`} style={{ transitionDelay: `${delay}ms` }}>{children}</div>;
}
