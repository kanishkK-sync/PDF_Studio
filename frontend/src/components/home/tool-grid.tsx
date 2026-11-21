"use client";

import { CategoryTabs } from "@/components/home/category-tabs";
import { ToolCard } from "@/components/home/tool-card";
import { ScrollReveal } from "@/components/ui/scroll-reveal";
import { categories, tools } from "@/config/tools";
import { useUiStore } from "@/store/ui-store";

const tabs = [
  { id: "all" as const, label: `All Tools (${tools.length})` },
  ...categories.map(c => ({ id: c.id, label: `${c.label} (${tools.filter(t => t.category === c.id).length})` })),
];

export function ToolGrid() {
  const active = useUiStore(s => s.activeCategory);
  const setActive = useUiStore(s => s.setActiveCategory);
  const visible = tools.filter(t => active === "all" || active === t.category);
  return <>
    <CategoryTabs categories={tabs} activeId={active} onChange={setActive} />
    <div role="tabpanel" id="tool-panel" aria-labelledby={`tab-${active}`}>
      <ul className="tool-directory">
        {visible.map((tool, i) => <li key={tool.slug} className={i === 0 && visible.length > 2 ? "directory-feature" : ""}>
          <ScrollReveal className="h-full" delay={(i % 3) * 35}><ToolCard tool={tool} index={tools.indexOf(tool)} /></ScrollReveal>
        </li>)}
      </ul>
    </div>
  </>;
}
