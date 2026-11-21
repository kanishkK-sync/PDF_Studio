"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft, X } from "lucide-react";
import { categories, tools, toolIcons } from "@/config/tools";

export function openCommandPalette() { window.dispatchEvent(new Event("studio:search")); }

const keywords: Record<string, string> = {
  "redact-pdf": "scrub sanitize metadata privacy mask", "compare-pdf": "diff revisions changes",
  "pdf-to-markdown": "md tokens llm ai extraction", "compress-pdf": "shrink optimize size",
  "merge-pdf": "join combine", "split-pdf": "separate extract ranges", "edit-pdf": "replace text",
  "pdf-to-excel": "xlsx spreadsheet tables", "pdf-to-powerpoint": "pptx slides",
  "pdf-to-word": "docx", "powerpoint-to-pdf": "pptx slides", "word-to-pdf": "docx",
  "excel-to-pdf": "xlsx spreadsheet", "pdf-to-jpg": "jpeg render", "jpg-to-pdf": "jpeg png images",
};
const entries = tools.map(tool => {
  const category = categories.find(c => c.id === tool.category)!.label;
  return { tool, category, fields: [tool.title, tool.slug, keywords[tool.slug] ?? "", category].map(s => s.toLowerCase()) };
});

function score(term: string, field: string) {
  if (field.includes(term)) return 100 + term.length - field.indexOf(term) / 10;
  let start = -1, previous = -1;
  for (const letter of term) {
    previous = field.indexOf(letter, previous + 1);
    if (previous < 0) return 0;
    if (start === -1) start = previous;
  }
  return term.length / (previous - start + 1);
}

export function CommandPalette() {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const router = useRouter();
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const results = entries.map(entry => {
    const scores = terms.map(term => Math.max(...entry.fields.map(field => score(term, field))));
    return { ...entry, rank: scores.includes(0) ? -1 : scores.reduce((a,b) => a+b, 0) };
  }).filter(e => e.rank >= 0).sort((a,b) => b.rank-a.rank);

  useEffect(() => {
    const open = () => {
      if (!dialog.current?.open) dialog.current?.showModal();
      input.current?.focus();
    };
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (dialog.current?.open) dialog.current.close(); else open();
      }
    }
    window.addEventListener("studio:search", open);
    window.addEventListener("keydown", shortcut);
    return () => { window.removeEventListener("studio:search", open); window.removeEventListener("keydown", shortcut); };
  }, []);
  function go(slug: string) {
    dialog.current?.close();
    router.push(`/tools/${slug}`);
  }
  return <dialog ref={dialog} className="command-dialog" aria-label="Find a tool"
    onClose={() => { setQuery(""); setIndex(0); }}
    onClick={e => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
    <div className="command-inner">
      <div className="command-input"><Search aria-hidden="true" size={20}/>
        <input ref={input} role="combobox" aria-label="Search tools" aria-expanded="true" aria-autocomplete="list"
          aria-controls="command-results" aria-activedescendant={results[index] ? `command-${results[index].tool.slug}` : undefined}
          value={query} placeholder="Find a tool…" onChange={e => { setQuery(e.target.value); setIndex(0); }}
          onKeyDown={e => {
            if (e.nativeEvent.isComposing || !results.length) return;
            if (e.key === "Enter") { e.preventDefault(); go(results[index].tool.slug); }
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              const next = (index + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
              setIndex(next);
              document.getElementById(`command-${results[next].tool.slug}`)?.scrollIntoView({ block: "nearest", behavior: "instant" });
            }
          }}/>
        <button type="button" aria-label="Close search" onClick={() => dialog.current?.close()}><X size={18}/></button>
      </div>
      <ul id="command-results" role="listbox" aria-label="Matching tools">{results.map(({ tool, category }, i) => {
        const Icon = toolIcons[tool.icon];
        return <li role="option" aria-selected={i === index} id={`command-${tool.slug}`} key={tool.slug}
          onMouseDown={e => e.preventDefault()} onPointerMove={() => setIndex(i)} onClick={() => go(tool.slug)}>
          <Icon size={17}/><span>{tool.title}</span><small>{category}</small>
        </li>;
      })}</ul>
      {!results.length && <p role="status" className="p-5 text-sm text-muted">No tools match “{query}”.</p>}
      <div className="command-hints"><span>↑ ↓ Navigate</span><span><CornerDownLeft size={12}/> Open tool</span><span>Esc Close</span></div>
    </div>
  </dialog>;
}
