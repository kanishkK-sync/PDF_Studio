"use client";

import { Combine, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ConversionResult } from "@/components/tools/conversion-result";
import { ErrorBanner } from "@/components/tools/error-banner";
import type { FileDropzoneHandle } from "@/components/tools/file-dropzone";
import { ImageList } from "@/components/tools/image-list";
import { ImagesDropzone } from "@/components/tools/images-dropzone";
import { ProgressBar } from "@/components/tools/progress-bar";
import { deleteJob, mergePdf, type DocumentResult } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { MAX_UPLOAD_BYTES, primaryButtonClass, secondaryButtonClass } from "@/lib/tool-limits";
import { cn } from "@/lib/utils";
import { useMultiFileJob } from "@/lib/use-multi-file-job";
import type { JobStatus } from "@/lib/use-tool-job";

const ACCEPT = { "application/pdf": [".pdf"] };
const MAX_MERGE_FILES = 20;

export function MergePdfWorkspace() {
  const job = useMultiFileJob<DocumentResult>(MAX_MERGE_FILES, MAX_UPLOAD_BYTES, false);
  const { entries, status, progress, result, error } = job;
  const [notice, setNotice] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const dropzoneRef = useRef<FileDropzoneHandle>(null);
  const actionRef = useRef<HTMLButtonElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const previousStatus = useRef<JobStatus>("idle");
  const pendingJob = useRef<string | null>(null);
  useEffect(() => {
    const previous = previousStatus.current;
    previousStatus.current = status;
    if (previous === status) return;
    if (status === "ready" && (previous === "idle" || previous === "uploading")) {
      if (entries.length >= 2) actionRef.current?.focus();
      else dropzoneRef.current?.focus();
    }
    if (status === "error") errorRef.current?.focus();
    if (status === "done") headingRef.current?.focus();
    if (status === "idle") dropzoneRef.current?.focus();
  }, [status, entries.length]);
  useEffect(() => { pendingJob.current = result && !downloaded ? result.job_id : null; }, [result, downloaded]);
  useEffect(() => () => { if (pendingJob.current) void deleteJob(pendingJob.current); }, []);

  function add(files: File[]) {
    const { overTotal, overCount } = job.add(files);
    setNotice([
      overTotal > 0 ? `${overTotal} ${overTotal === 1 ? "PDF was" : "PDFs were"} skipped because the total would exceed ${formatBytes(MAX_UPLOAD_BYTES)}.` : "",
      overCount > 0 ? `${overCount} ${overCount === 1 ? "PDF was" : "PDFs were"} skipped because the limit is ${MAX_MERGE_FILES} files.` : "",
    ].filter(Boolean).join(" ") || null);
  }
  function reset() {
    if (result && !downloaded) void deleteJob(result.job_id);
    job.clear();
    setDownloaded(false);
    setNotice(null);
  }

  const busy = status === "uploading" || status === "processing";
  const total = entries.reduce((sum, item) => sum + item.file.size, 0);
  const ready = entries.length >= 2 && total <= MAX_UPLOAD_BYTES && !busy;
  const message = status === "done" ? `Done. Merged ${result?.file_count} files into ${result?.page_count} pages.` : status === "processing" ? "Merging your PDFs." : status === "uploading" ? `Uploading, ${Math.floor(progress / 25) * 25} percent.` : status === "ready" ? `${entries.length} PDFs selected in merge order.` : "";

  return <div className="flex flex-col gap-6">
    <div role="status" aria-live="polite" className="sr-only">{message}</div>
    {status !== "done" && <>
      {notice && <ErrorBanner message={notice} />}
      {status === "error" && error && <ErrorBanner ref={errorRef} message={error.message} onRetry={ready ? () => job.start(mergePdf) : undefined} />}
      {entries.length > 0 && <>
        <p className="text-sm text-muted">{entries.length} PDFs, {formatBytes(total)}. Pages follow this order. Use the arrow buttons to reorder.</p>
        <ImageList entries={entries} label="Selected PDFs, in merge order" showPreviews={false} disabled={busy} onMove={job.move} onRemove={job.remove} />
      </>}
      <ImagesDropzone ref={dropzoneRef} accept={ACCEPT} maxBytes={MAX_UPLOAD_BYTES} fileDescription="PDF files" label={entries.length ? "Add more PDFs" : "Drop PDFs here, or choose files"} hint={`2 to ${MAX_MERGE_FILES} PDFs, ${formatBytes(MAX_UPLOAD_BYTES)} in total`} compact={entries.length > 0} disabled={busy || entries.length >= MAX_MERGE_FILES} onSelect={add} onReject={setNotice} />
      {total > MAX_UPLOAD_BYTES && <p className="text-sm text-accent-amber">Together these files exceed the {formatBytes(MAX_UPLOAD_BYTES)} limit. Remove files to continue.</p>}
      {entries.length > 0 && <div className="flex flex-col items-start gap-4">
        <button ref={actionRef} type="button" disabled={!ready} aria-disabled={!ready} className={cn(primaryButtonClass, !ready && "cursor-not-allowed opacity-60")} onClick={() => { if (ready) job.start(mergePdf); }}><Combine aria-hidden="true" className="size-4" /> Merge PDFs</button>
        {busy && <div className="flex w-full flex-col gap-3">{status === "uploading" ? <ProgressBar label="Uploading" value={progress} /> : <ProgressBar label="Merging PDFs" />}{status === "uploading" && <button type="button" className={secondaryButtonClass} onClick={job.cancel}><X aria-hidden="true" className="size-4" /> Cancel upload</button>}</div>}
      </div>}
    </>}
    {status === "done" && result && <ConversionResult title="Your merged PDF is ready" description={`It will download as ${result.download_name}.`} rows={[{ label: "Files", value: String(result.file_count ?? entries.length) }, { label: "Pages", value: String(result.page_count) }, { label: "PDF", value: formatBytes(result.result_size) }]} downloadUrl={result.download_url} downloadLabel="Download PDF" downloaded={downloaded} onDownload={() => setDownloaded(true)} onReset={reset} resetLabel="Merge more PDFs" headingRef={headingRef} />}
  </div>;
}
