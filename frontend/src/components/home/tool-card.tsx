import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { categories, toolIcons, type Tool } from "@/config/tools";
import { SpotlightCard } from "@/components/ui/spotlight-card";

export function ToolCard({ tool, index }: { tool: Tool; index: number }) {
  const Icon = toolIcons[tool.icon];
  return <SpotlightCard><Link href={`/tools/${tool.slug}`} className="tool-tile group" aria-labelledby={`title-${tool.slug}`}>
    <div className="flex items-center justify-between gap-2">
      <span className="tile-icon"><Icon size={21} strokeWidth={1.6} aria-hidden="true" /></span>
      <span className="tile-index">{String(index + 1).padStart(2, "0")}</span>
    </div>
    <span className="tile-category">{categories.find(c => c.id === tool.category)?.label}</span>
    <div className="flex items-start justify-between gap-2">
      <h3 id={`title-${tool.slug}`} className="text-lg font-semibold leading-tight tracking-tight">{tool.title}</h3>
      <ArrowUpRight aria-hidden="true" size={16} className="tile-arrow shrink-0"/>
    </div>
    <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted">{tool.description}</p>
  </Link></SpotlightCard>;
}
