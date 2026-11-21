"use client";

import Link from "next/link";
import { Layers3, Search } from "lucide-react";
import { useEffect, useRef } from "react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { openCommandPalette } from "@/components/layout/command-palette";
import { useBackendStatus } from "@/lib/use-backend-status";

export function Navbar() {
  const header = useRef<HTMLElement>(null);
  const progress = useRef<HTMLDivElement>(null);
  const { status, latency } = useBackendStatus();
  const label = status === "connected" ? "Engine Ready" : status === "offline" ? "Engine offline" : "Checking engine";
  useEffect(() => {
    let frame = 0;
    function paint() {
      frame = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const fraction = max > 0 ? Math.max(0, Math.min(1, scrollY / max)) : 0;
      if (progress.current) progress.current.style.transform = `scaleX(${fraction})`;
      header.current?.toggleAttribute("data-compact", scrollY > 24);
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
    const observer = new ResizeObserver(schedule);
    observer.observe(document.body);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    paint();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule); };
  }, []);
  return <header ref={header} className="studio-nav">
    <div className="scroll-progress" ref={progress} aria-hidden="true"/>
    <nav aria-label="Primary">
      <Link href="/" className="brand"><span><Layers3 size={18}/></span>pdf-studio</Link>
      <div className="flex items-center gap-2 sm:gap-3">
        <span className="engine-pill" role="status" aria-label={label} data-status={status} title={label}><i/><span>{label}</span>{latency !== null && <b>· {latency}ms</b>}</span>
        <button type="button" aria-label="Search tools (Control or Command K)" aria-haspopup="dialog" className="search-trigger" onClick={openCommandPalette}>
          <Search size={15}/><span>Search tools</span><kbd>Ctrl K</kbd>
        </button><ThemeToggle />
      </div>
    </nav>
  </header>;
}
