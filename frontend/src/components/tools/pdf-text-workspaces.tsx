"use client";

import { FileText, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { PdfConvertWorkspace } from "@/components/tools/pdf-convert-workspace";
import { pdfToMarkdown, redactPdf, type MarkdownFile, type Redaction } from "@/lib/api";
import { pdfTextTools, secondaryButtonClass } from "@/lib/tool-limits";

const presets = [
  ["emails", "Emails"], ["phones", "Phone numbers"], ["ssn", "Social Security numbers"],
  ["cards", "Card numbers"], ["urls", "URLs"],
];
const limits = pdfTextTools["redact-pdf"];

export function RedactWorkspace() {
  const [terms, setTerms] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [scrub, setScrub] = useState(true);
  const count = terms.split(/[,\n]/).filter(value => value.trim()).length;

  return <PdfConvertWorkspace<Redaction>
    actionLabel="Redact and verify"
    actionIcon={<ShieldCheck aria-hidden="true" className="size-4" />}
    maxBytes={limits.maxBytes}
    busyLabel="Redacting PDF"
    busyAnnouncement="Removing matches and checking the saved PDF."
    fidelityNote="Matches are found in searchable page text. Review scans, pictures and outlined lettering visually. Scrubbing also removes forms, annotations, links and attachments."
    canRun={(count > 0 || selected.length > 0) && count <= limits.maxTerms}
    options={busy => <fieldset disabled={busy} className="grid gap-4">
      <legend className="mb-3 font-medium">Sensitive information</legend>
      <div className="flex flex-wrap gap-2">
        {presets.map(([key, label]) => <label key={key} className="flex min-h-11 items-center gap-2 rounded-full border border-border bg-surface px-4 text-sm has-checked:border-accent-violet has-checked:bg-surface-raised">
          <input type="checkbox" checked={selected.includes(key)} onChange={event => {
            const checked = event.target.checked;
            setSelected(current => checked ? [...current, key] : current.filter(v => v !== key));
          }} />{label}
        </label>)}
      </div>
      <label className="grid gap-2">Custom sensitive phrases (separate with commas or new lines)
        <textarea rows={4} spellCheck={false} autoComplete="off" maxLength={limits.maxCharacters} value={terms} onChange={e => setTerms(e.target.value)}
          className="rounded-xl border border-border bg-surface p-3 text-foreground" />
      </label>
      {count > limits.maxTerms && <p role="alert">Use at most {limits.maxTerms} phrases.</p>}
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={scrub} onChange={e => setScrub(e.target.checked)} />
        Scrub hidden author &amp; XMP metadata
      </label>
    </fieldset>}
    run={(file, callbacks) => redactPdf(file, terms, selected, scrub, callbacks)}
    describe={r => ({
      title: "Your redacted PDF is ready", downloadLabel: "Download redacted PDF",
      description: "Verification searched the saved PDF’s extractable page text for your phrases and presets.",
      announcement: `Verified. ${r.redacted_count} matches removed.`,
      rows: [],
    })}
    resultDetails={r => <div className="flex items-start gap-3 rounded-xl border border-border bg-surface-raised p-4">
      <ShieldCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent-violet" />
      <p className="text-sm font-medium">
        {r.redacted_count === 0
          ? "No matching page text found"
          : `${r.redacted_count} ${r.redacted_count === 1 ? "match" : "matches"} permanently destroyed · 0 recoverable characters in matched page text`}
        {" · "}{r.metadata_scrubbed ? "Metadata scrubbed" : "Metadata retained"}
      </p>
    </div>}
    resetLabel="Redact another PDF"
  />;
}

function MarkdownPreview({ file }: { file: MarkdownFile }) {
  const [message, setMessage] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(file.markdown);
      setMessage("Markdown copied.");
    } catch {
      setMessage("Clipboard access is unavailable. Select the preview text to copy it.");
    }
  }
  return <section aria-label="Markdown preview" className="grid min-w-0 gap-3 rounded-xl border border-border bg-surface p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-display text-xl">Markdown preview</h3>
      <span className="rounded-full bg-surface-raised px-3 py-1 text-sm">~{file.estimated_tokens.toLocaleString()} tokens</span>
    </div>
    <pre tabIndex={0} aria-label="Extracted Markdown" className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-raised p-4 text-sm">{file.markdown}</pre>
    <button type="button" onClick={copy} className={secondaryButtonClass}>Copy Markdown</button>
    <span role="status" className="text-sm text-muted">{message}</span>
  </section>;
}

export function MarkdownWorkspace() {
  const [markers, setMarkers] = useState(true);
  return <PdfConvertWorkspace<MarkdownFile>
    actionLabel="Extract Markdown"
    actionIcon={<FileText aria-hidden="true" className="size-4" />}
    maxBytes={pdfTextTools["pdf-to-markdown"].maxBytes}
    busyLabel="Extracting Markdown"
    busyAnnouncement="Reading page text and tables."
    fidelityNote="Choose a PDF with selectable text. Review reading order and inferred headings in the preview."
    options={busy => <label className="flex items-center gap-2">
      <input type="checkbox" disabled={busy} checked={markers} onChange={e => setMarkers(e.target.checked)} />
      Include page markers
    </label>}
    run={(file, callbacks) => pdfToMarkdown(file, markers, callbacks)}
    describe={r => ({
      title: "Your Markdown is ready", downloadLabel: "Download Markdown",
      description: r.download_name, announcement: `Extracted ${r.word_count} words.`,
      rows: [{ label: "Pages", value: String(r.page_count) }, { label: "Words", value: String(r.word_count) }],
    })}
    resultDetails={file => <MarkdownPreview file={file} />}
    resetLabel="Extract another PDF"
  />;
}
