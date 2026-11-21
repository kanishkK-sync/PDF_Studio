"use client";

import type { KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import type { CategoryFilter } from "@/store/ui-store";

type Tab = { id: CategoryFilter; label: string };

type CategoryTabsProps = {
  categories: readonly Tab[];
  activeId: CategoryFilter;
  onChange: (id: CategoryFilter) => void;
};

// tool-grid.tsx builds the same ids for the tabpanel's aria-labelledby.
function tabId(id: CategoryFilter): string {
  return `tab-${id}`;
}

export function CategoryTabs({ categories, activeId, onChange }: CategoryTabsProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = categories.findIndex((tab) => tab.id === activeId);
    let next: number;

    switch (event.key) {
      case "ArrowRight":
        next = (current + 1) % categories.length;
        break;
      case "ArrowLeft":
        next = (current - 1 + categories.length) % categories.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = categories.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    const tab = categories[next];
    onChange(tab.id);
    document.getElementById(tabId(tab.id))?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="Filter tools by category"
      onKeyDown={handleKeyDown}
      className="studio-tabs"
    >
      {categories.map((tab) => {
        const isActive = tab.id === activeId;

        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId(tab.id)}
            aria-selected={isActive}
            aria-controls="tool-panel"
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cn(
              "rounded-md px-3 py-2 text-sm font-medium",
              isActive ? "bg-surface-raised text-foreground shadow-soft" : "text-muted hover:text-foreground",
            )}
          >
            <span className="relative">{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}
