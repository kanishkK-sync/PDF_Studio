"use client";

import { create } from "zustand";
import type { ToolCategory } from "@/config/tools";

export type CategoryFilter = "all" | ToolCategory;

type State = {
  activeCategory: CategoryFilter;
  setActiveCategory: (category: CategoryFilter) => void;
};

// Usage rule: components must select a single primitive, for example
//   const activeCategory = useUiStore((s) => s.activeCategory);
//   const setActiveCategory = useUiStore((s) => s.setActiveCategory);
// Never select a new object or array from the store, such as
// useUiStore((s) => ({ a: s.activeCategory })) or useUiStore((s) => [s.activeCategory]).
// In zustand 5 a selector that returns a fresh reference on every call can
// cause an infinite render loop.
export const useUiStore = create<State>()((set) => ({
  activeCategory: "all",
  setActiveCategory: (category) => set({ activeCategory: category }),
}));