import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { toolIcons, type Tool } from "@/config/tools";

export function ComingSoonPanel({ tool }: { tool: Tool }) {
  const Icon = toolIcons[tool.icon];

  return (
    <div>
      <Link
        href="/#tools"
        className="inline-flex items-center gap-2 rounded-md text-sm font-medium text-muted hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        All tools
      </Link>

      <div className="mt-8 rounded-xl border border-border bg-surface p-10 shadow-soft">
        <span className="inline-flex size-14 items-center justify-center rounded-lg border border-border bg-surface-raised text-accent-violet">
          <Icon aria-hidden="true" className="size-7" />
        </span>

        <h1 className="mt-6 font-display text-4xl tracking-tight sm:text-5xl">
          {tool.title}
        </h1>
        <p className="mt-3 text-lg text-muted">{tool.description}</p>

        <p className="mt-6">
          <span className="inline-flex rounded-full border border-border px-3 py-1 text-sm font-medium text-accent-violet">
            Coming soon
          </span>
        </p>
        <p className="mt-4 text-sm text-muted">
          The interface for this tool arrives in a later phase.
        </p>
      </div>
    </div>
  );
}