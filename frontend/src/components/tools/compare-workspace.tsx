"use client";

import { ArrowLeft, ArrowRight, Download, GitCompareArrows } from "lucide-react";
import { useCallback, useState } from "react";
import { ErrorBanner } from "@/components/tools/error-banner";
import { FileChip } from "@/components/tools/file-chip";
import { FileDropzone } from "@/components/tools/file-dropzone";
import { ProgressBar } from "@/components/tools/progress-bar";
import { ApiError, buildDownloadUrl, comparePdfs, deleteJob } from "@/lib/api";
import { readComparison, type Comparison } from "@/lib/comparison-archive";
import { formatBytes } from "@/lib/format";
import { comparisonLimits, primaryButtonClass, secondaryButtonClass } from "@/lib/tool-limits";
import { useToolJob, type JobCallbacks } from "@/lib/use-tool-job";

const limits = comparisonLimits["compare-pdf"];
const pdf = { "application/pdf": [".pdf"] };

function runComparison(original: File, revised: File, callbacks: JobCallbacks) {
  if (original.size + revised.size > limits.maxTotalBytes) {
    throw new ApiError("too_large", `Choose two PDFs totaling at most ${formatBytes(limits.maxTotalBytes)}.`, 413);
  }
  const upload = comparePdfs(original, revised, callbacks);
  const controller = new AbortController();
  const promise = upload.promise.then(async job => {
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(180_000)]);
      const response = await fetch(buildDownloadUrl(job.download_url), { signal, cache: "no-store" });
      if (!response.ok) throw new ApiError("network_error", "The report download failed. Compare the files again.", response.status);
      const archive = await response.blob();
      try {
        return await readComparison(archive, job.download_name);
      } catch {
        throw new ApiError("unexpected_response", "The comparison archive could not be read. Compare the files again.", 0);
      }
    } catch (error) {
      void deleteJob(job.job_id);
      if (error instanceof DOMException && error.name === "TimeoutError") {
        throw new ApiError("network_error", "The report download timed out. Try comparing the files again.", 0);
      }
      throw error;
    }
  });
  return { promise, abort: () => { controller.abort(); upload.abort(); } };
}

function FileSlot({ label, file, busy, onSelect, onRemove }: {
  label: string; file: File | null; busy: boolean;
  onSelect: (file: File) => string | undefined; onRemove: () => void;
}) {
  const [error, setError] = useState<string>();
  return (
    <fieldset disabled={busy} className="grid min-w-0 content-start gap-3">
      <legend className="mb-3 font-display text-xl">{label}</legend>
      {file ? <FileChip name={file.name} size={file.size} disabled={busy} onRemove={onRemove} /> :
        <FileDropzone label={`Choose ${label.toLowerCase()}`} accept={pdf}
          maxSizeBytes={limits.maxTotalBytes} disabled={busy}
          onSelect={value => setError(onSelect(value))} onReject={setError} />}
      {error && <ErrorBanner message={error} />}
    </fieldset>
  );
}

function TextChanges({ label, lines }: { label: string; lines: string[] }) {
  return <section className="min-w-0 rounded-xl border border-border bg-surface p-4">
    <h3 className="font-medium">{label} ({lines.length})</h3>
    {lines.length > 0
      ? <pre tabIndex={0} aria-label={label} className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap break-words text-sm">{lines.join("\n")}</pre>
      : <p className="mt-2 text-sm text-muted">None</p>}
  </section>;
}

function ComparisonViewer({ result, originalName, revisedName, onReset }: {
  result: Comparison; originalName: string; revisedName: string; onReset: () => void;
}) {
  const { report } = result;
  const [changedOnly, setChangedOnly] = useState(report.pages_changed > 0);
  const [number, setNumber] = useState(1);
  const [actualSize, setActualSize] = useState(false);
  const pages = changedOnly ? report.pages.filter(page => page.status !== "unchanged") : report.pages;
  const index = Math.max(0, pages.findIndex(page => page.page === number));
  const current = pages[index];
  const image = current && result.images.get(current.image);
  const previewRef = useCallback((node: HTMLImageElement | null) => {
    if (!node || !image) return;
    const url = URL.createObjectURL(image);
    node.src = url;
    return () => URL.revokeObjectURL(url);
  }, [image]);
  const downloadRef = useCallback((node: HTMLAnchorElement | null) => {
    if (!node) return;
    const url = URL.createObjectURL(result.archive);
    node.href = url;
    return () => URL.revokeObjectURL(url);
  }, [result.archive]);
  const focusHeading = useCallback((node: HTMLHeadingElement | null) => node?.focus(), []);

  return <section className="grid gap-5 rounded-2xl border border-border bg-surface p-5 sm:p-8">
    <div>
      <h2 ref={focusHeading} tabIndex={-1} className="font-display text-3xl">Comparison report</h2>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted">Original PDF</dt><dd className="break-all">{originalName} · {report.original_pages} pages</dd></div>
        <div><dt className="text-muted">Revised PDF</dt><dd className="break-all">{revisedName} · {report.revised_pages} pages</dd></div>
      </dl>
    </div>
    <dl className="grid grid-cols-2 gap-4 rounded-xl bg-surface-raised p-4">
      <div><dt className="text-sm text-muted">Overall similarity</dt><dd className="font-display text-3xl">{report.overall_similarity}%</dd></div>
      <div><dt className="text-sm text-muted">Changed pages</dt><dd className="font-display text-3xl">{report.pages_changed} / {report.compared_pages}</dd></div>
    </dl>
    {report.truncated && <p role="note" className="text-sm">Results cover the first {report.compared_pages} of {report.total_pages} page positions.</p>}
    <label className="flex min-h-11 items-center gap-2">
      <input type="checkbox" checked={changedOnly} onChange={e => {
        setNumber(current?.page ?? 1);
        setChangedOnly(e.target.checked);
      }} /> Changed pages only
    </label>
    {current ? <>
      <nav aria-label="Comparison pages" className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" aria-label="Previous page" disabled={index === 0} className={secondaryButtonClass}
          onClick={() => setNumber(pages[index - 1].page)}><ArrowLeft aria-hidden="true" className="size-4" />Previous</button>
        <label className="flex items-center gap-2">Page
          <select value={current.page} onChange={e => setNumber(Number(e.target.value))}
            className="rounded-lg border border-border bg-surface p-2">
            {pages.map(page => <option key={page.page} value={page.page}>{page.page} · {page.status}</option>)}
          </select>
        </label>
        <button type="button" aria-label="Next page" disabled={index + 1 === pages.length} className={secondaryButtonClass}
          onClick={() => setNumber(pages[index + 1].page)}>Next<ArrowRight aria-hidden="true" className="size-4" /></button>
      </nav>
      <figure className="grid min-w-0 gap-3">
        <figcaption className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span aria-live="polite">Page {current.page} · {current.status} · {current.similarity_percent}% similarity
            {current.status === "modified" && !current.has_visual_changes && " · Text changes only"}
          </span>
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={actualSize} onChange={e => setActualSize(e.target.checked)} />
            Actual size
          </label>
        </figcaption>
        <div tabIndex={actualSize ? 0 : undefined} role="region" aria-label="Visual difference preview"
          className="max-h-[70vh] min-w-0 overflow-auto rounded-lg border border-border bg-surface-raised">
          {/* eslint-disable-next-line @next/next/no-img-element -- this is a local raster from the ZIP */}
          <img ref={previewRef} alt={`Visual comparison for page ${current.page}, ${current.status}`}
            className={actualSize ? "mx-auto block max-w-none" : "mx-auto block max-h-[70vh] max-w-full object-contain"} />
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
          <span><i aria-hidden="true" className="mr-2 inline-block size-3 rounded-sm bg-diff-added" />Added or darker</span>
          <span><i aria-hidden="true" className="mr-2 inline-block size-3 rounded-sm bg-diff-removed" />Removed or lighter</span>
          <span>Gray · Unchanged</span>
        </div>
      </figure>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextChanges label="Removed lines" lines={current.removed_lines} />
        <TextChanges label="Added lines" lines={current.added_lines} />
      </div>
    </> : <p role="status">No changed pages in this comparison.</p>}
    <div className="flex flex-wrap gap-3">
      <a ref={downloadRef} download={result.name} className={primaryButtonClass}><Download aria-hidden="true" className="size-4" />Download ZIP report</a>
      <button type="button" onClick={onReset} className={secondaryButtonClass}>Compare another pair</button>
    </div>
  </section>;
}

export function CompareWorkspace() {
  const job = useToolJob<Comparison>();
  const [revised, setRevised] = useState<File | null>(null);
  const busy = job.status === "uploading" || job.status === "processing";
  function select(file: File, original: boolean) {
    const other = original ? revised : job.file;
    if (file.size + (other?.size ?? 0) > limits.maxTotalBytes) {
      return `Choose two PDFs totaling at most ${formatBytes(limits.maxTotalBytes)}.`;
    }
    if (original) job.select(file);
    else {
      setRevised(file);
      if (job.file) job.select(job.file);
    }
  }
  if (job.result && job.file && revised) return <ComparisonViewer result={job.result}
    originalName={job.file.name} revisedName={revised.name} onReset={() => { setRevised(null); job.reset(); }} />;
  return <div className="grid gap-5">
    <p className="text-sm text-muted">Compare corresponding page numbers, up to the first {limits.maxPages} pages. The two PDFs can total up to {formatBytes(limits.maxTotalBytes)}.</p>
    <div className="grid gap-4 md:grid-cols-2">
      <FileSlot label="Original PDF" file={job.file} busy={busy} onSelect={f => select(f, true)} onRemove={job.clear} />
      <FileSlot label="Revised PDF" file={revised} busy={busy} onSelect={f => select(f, false)} onRemove={() => {
        setRevised(null);
        if (job.file) job.select(job.file);
      }} />
    </div>
    {job.error && <ErrorBanner message={job.error.message} />}
    {busy && <ProgressBar label={job.status === "uploading" ? "Uploading PDFs" : "Comparing pages and preparing the viewer"}
      value={job.status === "uploading" ? job.progress : null} />}
    <div><button type="button" disabled={!job.file || !revised || busy}
      className={primaryButtonClass + " disabled:cursor-not-allowed disabled:opacity-60"}
      onClick={() => { if (revised) job.start((file, callbacks) => runComparison(file, revised, callbacks)); }}>
      <GitCompareArrows aria-hidden="true" className="size-4" />Compare PDFs
    </button></div>
  </div>;
}
