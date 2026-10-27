import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { toolIcons, type Tool } from "@/config/tools";

export function ToolHeader({ tool }: { tool: Tool }) {
  const Icon = toolIcons[tool.icon];

  return (
    <header>
      <Link
        href="/#tools"
        className="inline-flex items-center gap-2 rounded-md text-sm font-medium text-muted hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        All tools
      </Link>

      <div className="mt-8 flex flex-col gap-5 sm:flex-row sm:items-center">
        <span className="inline-flex size-14 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-raised text-accent-violet">
          <Icon aria-hidden="true" className="size-7" />
        </span>

        <div className="min-w-0">
          <h1 className="break-words font-display text-4xl tracking-tight sm:text-5xl">
            {tool.title}
          </h1>
          <p className="mt-3 text-lg text-muted">{tool.description}</p>
        </div>
      </div>
    </header>
  );
}