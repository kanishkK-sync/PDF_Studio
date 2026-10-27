import { ArrowLeft } from "lucide-react";
import Link from "next/link";

export function ToolNotFound() {
  return (
    <div className="rounded-xl border border-border bg-surface p-10 text-center shadow-soft">
      <p
        aria-hidden="true"
        className="bg-[image:var(--gradient-accent-text)] bg-clip-text font-display text-7xl tracking-tight text-transparent"
      >
        404
      </p>

      <h1 className="mt-4 font-display text-4xl tracking-tight sm:text-5xl">
        Tool not found
      </h1>
      <p className="mx-auto mt-3 max-w-md text-muted">
        No tool lives at this address. The link may be mistyped, or the tool
        may have moved.
      </p>

      <Link
        href="/#tools"
        className="mt-8 inline-flex items-center gap-2 rounded-full bg-foreground px-6 py-3 text-sm font-semibold text-background shadow-glow transition-shadow duration-300 hover:shadow-glow-strong"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Browse all tools
      </Link>
    </div>
  );
}