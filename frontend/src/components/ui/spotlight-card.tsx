"use client";

import { useEffect, useRef, type PointerEvent, type ReactNode } from "react";

export function SpotlightCard({ children }: { children: ReactNode }) {
  const frame = useRef(0);
  const point = useRef([0, 0]);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  function move(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "touch" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const node = event.currentTarget;
    point.current = [event.clientX, event.clientY];
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const rect = node.getBoundingClientRect();
      node.style.setProperty("--mouse-x", `${point.current[0] - rect.left}px`);
      node.style.setProperty("--mouse-y", `${point.current[1] - rect.top}px`);
    });
  }
  return <div className="spotlight-card" onPointerMove={move}>{children}</div>;
}
