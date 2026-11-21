"use client";

import { motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ConversionResult,
  type ResultRow,
} from "@/components/tools/conversion-result";
import { ErrorBanner } from "@/components/tools/error-banner";
import { FileChip } from "@/components/tools/file-chip";
import {
  FileDropzone,
  type FileDropzoneHandle,
} from "@/components/tools/file-dropzone";
import { ProgressBar } from "@/components/tools/progress-bar";
import { deleteJob } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import {
  fadeRise,
  fadeRiseReduced,
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import {
  MAX_UPLOAD_BYTES,
  RETRYABLE_CODES,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/lib/tool-limits";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";
import {
  useToolJob,
  type JobRunner,
  type JobStatus,
} from "@/lib/use-tool-job";

const ACCEPT = { "application/pdf": [".pdf"] };

// What every PDF conversion result must carry for the workspace to clean up.
export type PdfConvertResult = {
  job_id: string;
  download_url: string;
};

// How one finished job is shown. Built by the tool, shown by the workspace.
export type PdfConvertSummary = {
  title: string;
  description: string;
  downloadLabel: string;
  rows: ResultRow[];
  // Read out once when the result appears.
  announcement: string;
};

type PdfConvertWorkspaceProps<R extends PdfConvertResult> = {
  accept?: Record<string, string[]>;
  fileLabel?: string;
  fileDescription?: string;
  canRun?: boolean;
  maxBytes?: number;
  resultDetails?: (result: R) => ReactNode;
  // Primary button text, for example "Convert to Word".
  actionLabel: string;
  actionIcon: ReactNode;
  // Progress label while the server works, for example "Converting to Word".
  busyLabel: string;
  // Live-region text while the server works.
  busyAnnouncement: string;
  // An honest note about fidelity, shown above the button.
  fidelityNote?: string;
  // Tool-specific controls (for example a mode picker), shown after a file is
  // chosen and before the result. It is a function because only the workspace
  // knows `busy`, and the controls must be disabled while a job is running.
  options?: (busy: boolean) => ReactNode;
  run: JobRunner<R>;
  describe: (result: R) => PdfConvertSummary;
  resetLabel: string;
};

type AnnouncementInput = {
  status: JobStatus;
  file: File | null;
  progress: number;
  actionLabel: string;
  busyAnnouncement: string;
  resultAnnouncement: string;
  downloaded: boolean;
  cancelled: boolean;
};

// Derived during render, so there is no effect and no extra state. The text
// only changes at meaningful moments (upload progress moves in 25% steps),
// which keeps the polite live region from chattering.
function buildAnnouncement({
  status,
  file,
  progress,
  actionLabel,
  busyAnnouncement,
  resultAnnouncement,
  downloaded,
  cancelled,
}: AnnouncementInput): string {
  switch (status) {
    case "idle":
      return "";
    case "ready":
      if (!file) return "";
      return cancelled
        ? `Upload cancelled. Press ${actionLabel} to try again.`
        : `Selected ${file.name}, ${formatBytes(file.size)}. Press ${actionLabel}.`;
    case "uploading": {
      const step = Math.floor(progress / 25) * 25;
      return step === 0 ? "Uploading your file." : `Uploading, ${step} percent.`;
    }
    case "processing":
      return busyAnnouncement;
    case "done":
      return downloaded
        ? "Download started. The file is deleted from this machine once it has been sent."
        : resultAnnouncement;
    case "error":
      // The error banner has role alert and announces itself.
      return "";
  }
}

export function PdfConvertWorkspace<R extends PdfConvertResult>({
  accept = ACCEPT,
  fileLabel,
  fileDescription,
  canRun = true,
  maxBytes = MAX_UPLOAD_BYTES,
  resultDetails,
  actionLabel,
  actionIcon,
  busyLabel,
  busyAnnouncement,
  fidelityNote,
  options,
  run,
  describe,
  resetLabel,
}: PdfConvertWorkspaceProps<R>) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const enter = reduced ? fadeRiseReduced : fadeRise;

  const job = useToolJob<R>();
  const { status, file, progress, result, error } = job;

  const [rejection, setRejection] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const dropzoneRef = useRef<FileDropzoneHandle>(null);
  const actionButtonRef = useRef<HTMLButtonElement>(null);
  const optionsRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousStatusRef = useRef<JobStatus>("idle");
  // The job on the server that nobody has downloaded yet, if any.
  const pendingJobRef = useRef<string | null>(null);

  // Focus follows the state: file chosen or upload cancelled -> primary
  // button, result -> its heading, error -> the banner, back to idle -> the
  // dropzone. Runs after the new state's elements are mounted.
  useEffect(() => {
    const previous = previousStatusRef.current;
    previousStatusRef.current = status;
    if (previous === status) return;

    if (status === "ready") {
      if (canRun) {
        actionButtonRef.current?.focus();
      } else {
        optionsRef.current?.querySelector<HTMLElement>("input, textarea, button")?.focus();
      }
    } else if (status === "done") {
      resultHeadingRef.current?.focus();
    } else if (status === "error") {
      errorRef.current?.focus();
    } else if (status === "idle") {
      dropzoneRef.current?.focus();
    }
  }, [status, canRun]);

  useEffect(() => {
    pendingJobRef.current = result && !downloaded ? result.job_id : null;
  }, [result, downloaded]);

  // Leaving the page with an undownloaded result: best-effort delete.
  useEffect(() => {
    return () => {
      const jobId = pendingJobRef.current;
      pendingJobRef.current = null;
      if (jobId) void deleteJob(jobId);
    };
  }, []);

  function handleSelect(selected: File) {
    setRejection(null);
    setCancelled(false);
    setDownloaded(false);
    job.select(selected);
  }

  function handleRemove() {
    setRejection(null);
    setCancelled(false);
    job.clear();
  }

  function handleConvert() {
    setCancelled(false);
    job.start(run);
  }

  function handleCancel() {
    setCancelled(true);
    job.cancel();
  }

  function handleDownload() {
    setDownloaded(true);
  }

  function handleAnother() {
    if (result && !downloaded) void deleteJob(result.job_id);
    setDownloaded(false);
    setRejection(null);
    setCancelled(false);
    job.reset();
  }

  const busy = status === "uploading" || status === "processing";
  const showPick = status === "idle";
  const showResult = status === "done" && result !== null;
  const showConfigure = !showPick && !showResult;
  const retryable = error !== null && RETRYABLE_CODES.has(error.code);

  const summary = showResult && result ? describe(result) : null;

  const announcement = buildAnnouncement({
    status,
    file,
    progress,
    actionLabel,
    busyAnnouncement,
    resultAnnouncement: summary?.announcement ?? "",
    downloaded,
    cancelled,
  });

  return (
    <div className="flex flex-col gap-6">
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      {showPick && (
        <div className="flex flex-col gap-4">
          {rejection && <ErrorBanner message={rejection} />}
          <FileDropzone
            ref={dropzoneRef}
            accept={accept}
            label={fileLabel}
            fileDescription={fileDescription}
            maxSizeBytes={maxBytes}
            onSelect={handleSelect}
            onReject={setRejection}
          />
          {fidelityNote && (
            <p className="text-sm leading-relaxed text-muted">{fidelityNote}</p>
          )}
        </div>
      )}

      {showConfigure && (
        <motion.div
          key={reduced ? "reduced" : "full"}
          variants={enter}
          initial="hidden"
          animate="visible"
          className="flex flex-col gap-6"
        >
          {file && (
            <FileChip
              name={file.name}
              size={file.size}
              disabled={busy}
              onRemove={handleRemove}
            />
          )}

          {status === "error" && error && (
            <ErrorBanner
              ref={errorRef}
              message={error.message}
              onRetry={retryable && canRun ? handleConvert : undefined}
            />
          )}

          {options && <div ref={optionsRef}>{options(busy)}</div>}

          {fidelityNote && (
            <p className="text-sm leading-relaxed text-muted">{fidelityNote}</p>
          )}

          <div className="flex flex-col items-start gap-4">
            <motion.button
              ref={actionButtonRef}
              type="button"
              disabled={busy || !canRun}
              aria-disabled={busy || !canRun}
              onClick={() => {
                if (!busy && canRun) handleConvert();
              }}
              whileHover={busy || !canRun ? undefined : interactions.hover}
              whileTap={busy || !canRun ? undefined : interactions.tap}
              transition={microTransition}
              className={cn(
                primaryButtonClass,
                (busy || !canRun) && "cursor-not-allowed opacity-60",
              )}
            >
              {actionIcon}
              {actionLabel}
            </motion.button>

            {busy && (
              <div className="flex w-full flex-col gap-3">
                {status === "uploading" ? (
                  <ProgressBar label="Uploading" value={progress} />
                ) : (
                  <ProgressBar label={busyLabel} />
                )}
                {status === "uploading" && (
                  <div>
                    <motion.button
                      type="button"
                      onClick={handleCancel}
                      whileHover={interactions.hover}
                      whileTap={interactions.tap}
                      transition={microTransition}
                      className={secondaryButtonClass}
                    >
                      <X aria-hidden="true" className="size-4" />
                      Cancel upload
                    </motion.button>
                  </div>
                )}
              </div>
            )}
          </div>
        </motion.div>
      )}

      {showResult && result && summary && (
        <motion.div
          key={reduced ? "reduced" : "full"}
          variants={enter}
          initial="hidden"
          animate="visible"
        >
          <ConversionResult
            title={summary.title}
            description={summary.description}
            rows={summary.rows}
            downloadUrl={result.download_url}
            downloadLabel={summary.downloadLabel}
            downloaded={downloaded}
            onDownload={handleDownload}
            onReset={handleAnother}
            resetLabel={resetLabel}
            headingRef={resultHeadingRef}
          >
            {resultDetails?.(result)}
          </ConversionResult>
        </motion.div>
      )}
    </div>
  );
}
