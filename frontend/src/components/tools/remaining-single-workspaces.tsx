"use client";

import { FileText, FileSpreadsheet, Presentation, PenLine, Scissors } from "lucide-react";
import { useId, useState } from "react";
import { OptionGroup, type ChoiceOption } from "@/components/tools/option-group";
import { PdfConvertWorkspace, type PdfConvertSummary } from "@/components/tools/pdf-convert-workspace";
import { editPdf, officeToPdf, splitPdf, type DocumentResult } from "@/lib/api";
import { formatBytes } from "@/lib/format";

type OfficeKind = "word" | "powerpoint" | "excel";
const OFFICE = {
  word: { title: "Word", ext: ".docx", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", icon: FileText },
  powerpoint: { title: "PowerPoint", ext: ".pptx", mime: "application/vnd.openxmlformats-officedocument.presentationml.presentation", icon: Presentation },
  excel: { title: "Excel", ext: ".xlsx", mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon: FileSpreadsheet },
} as const;

function officeSummary(kind: OfficeKind, result: DocumentResult): PdfConvertSummary {
  const name = OFFICE[kind].title;
  return {
    title: "Your PDF is ready",
    description: `It will download as ${result.download_name}. Check the layout before sharing it; complex formatting may move.`,
    downloadLabel: "Download PDF",
    announcement: `Done. Your ${name} file became a PDF with ${result.page_count} pages.`,
    rows: [
      { label: "Pages", value: String(result.page_count) },
      { label: name, value: formatBytes(result.original_size ?? 0) },
      { label: "PDF", value: formatBytes(result.result_size) },
    ],
  };
}

function OfficeWorkspace({ kind }: { kind: OfficeKind }) {
  const config = OFFICE[kind];
  const Icon = config.icon;
  return <PdfConvertWorkspace<DocumentResult>
    accept={{ [config.mime]: [config.ext] }}
    fileLabel={`Drop a ${config.title} file here, or choose a file`}
    fileDescription={`${config.title} file`}
    actionLabel="Create PDF"
    actionIcon={<Icon aria-hidden="true" className="size-4" />}
    busyLabel="Creating PDF"
    busyAnnouncement={`Converting your ${config.title} file to PDF.`}
    fidelityNote="Text remains searchable where possible. Basic text, tables and pictures are rendered; advanced layouts, charts, formulas and animations may change or be omitted."
    run={(file, callbacks) => officeToPdf(file, kind, callbacks)}
    describe={(result) => officeSummary(kind, result)}
    resetLabel="Convert another"
  />;
}

export function WordToPdfWorkspace() { return <OfficeWorkspace kind="word" />; }
export function PowerpointToPdfWorkspace() { return <OfficeWorkspace kind="powerpoint" />; }
export function ExcelToPdfWorkspace() { return <OfficeWorkspace kind="excel" />; }

const fieldClass = "min-h-11 w-full rounded-xl border border-border bg-surface px-4 py-2 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent-violet disabled:opacity-60";

export function EditPdfWorkspace() {
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const findId = useId();
  const replaceId = useId();
  return <PdfConvertWorkspace<DocumentResult>
    actionLabel="Replace text"
    actionIcon={<PenLine aria-hidden="true" className="size-4" />}
    busyLabel="Editing PDF"
    busyAnnouncement="Replacing text in your PDF."
    fidelityNote="Works on selectable text. Matching text is removed and replaced in its page area; long replacements may be clipped. Scanned text cannot be edited."
    canRun={find.trim().length > 0 && replace.trim().length > 0}
    options={(busy) => <div className="grid gap-4 sm:grid-cols-2">
      <div className="flex flex-col gap-2"><label htmlFor={findId} className="text-sm font-medium text-foreground">Find exact text</label><input id={findId} className={fieldClass} value={find} maxLength={500} disabled={busy} onChange={(e) => setFind(e.target.value)} /></div>
      <div className="flex flex-col gap-2"><label htmlFor={replaceId} className="text-sm font-medium text-foreground">Replace with</label><input id={replaceId} className={fieldClass} value={replace} maxLength={500} disabled={busy} onChange={(e) => setReplace(e.target.value)} /></div>
    </div>}
    run={(file, callbacks) => editPdf(file, find, replace, callbacks)}
    describe={(result) => ({
      title: "Your edited PDF is ready",
      description: `It will download as ${result.download_name}. Review the replaced text before sharing.`,
      downloadLabel: "Download PDF",
      announcement: `Done. Replaced ${result.replacement_count ?? 0} matches.`,
      rows: [{ label: "Replacements", value: String(result.replacement_count ?? 0) }, { label: "Pages", value: String(result.page_count) }, { label: "PDF", value: formatBytes(result.result_size) }],
    })}
    resetLabel="Edit another"
  />;
}

type SplitMode = "extract" | "separate";
const SPLIT_OPTIONS: readonly ChoiceOption<SplitMode>[] = [
  { id: "extract", title: "Extract", description: "Put all selected pages into one PDF." },
  { id: "separate", title: "Separate", description: "Create one PDF per range and download a ZIP." },
];
const RANGE_PATTERN = /^\s*\d{1,6}\s*(?:-\s*\d{0,6})?\s*(?:,\s*\d{1,6}\s*(?:-\s*\d{0,6})?\s*)*$/;

export function SplitPdfWorkspace() {
  const [ranges, setRanges] = useState("");
  const [mode, setMode] = useState<SplitMode>("extract");
  const rangeId = useId();
  return <PdfConvertWorkspace<DocumentResult>
    actionLabel="Split PDF"
    actionIcon={<Scissors aria-hidden="true" className="size-4" />}
    busyLabel="Splitting PDF"
    busyAnnouncement="Splitting your PDF."
    canRun={RANGE_PATTERN.test(ranges)}
    options={(busy) => <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2"><label htmlFor={rangeId} className="text-sm font-medium text-foreground">Pages or ranges</label><input id={rangeId} className={fieldClass} placeholder="1-3, 5, 8-" value={ranges} disabled={busy} onChange={(e) => setRanges(e.target.value)} aria-describedby={`${rangeId}-hint`} /><p id={`${rangeId}-hint`} className="text-sm text-muted">Use page numbers starting at 1. An open range such as 8- runs to the final page.</p></div>
      <OptionGroup label="Split method" options={SPLIT_OPTIONS} value={mode} onChange={setMode} disabled={busy} columns={2} />
    </div>}
    run={(file, callbacks) => splitPdf(file, ranges, mode, callbacks)}
    describe={(result) => ({
      title: "Your pages are ready",
      description: `It will download as ${result.download_name}.`,
      downloadLabel: result.kind === "zip" ? "Download ZIP" : "Download PDF",
      announcement: `Done. Selected ${result.selected_pages} pages.`,
      rows: [{ label: "Selected pages", value: String(result.selected_pages ?? 0) }, { label: "Files", value: String(result.file_count ?? 1) }, { label: "Download", value: formatBytes(result.result_size) }],
    })}
    resetLabel="Split another"
  />;
}
