"use client";

import { motion } from "framer-motion";
import { Minimize2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ErrorBanner } from "@/components/tools/error-banner";
import { FileChip } from "@/components/tools/file-chip";
import {
  FileDropzone,
  type FileDropzoneHandle,
} from "@/components/tools/file-dropzone";
import { LevelSelector } from "@/components/tools/level-selector";
import { ProgressBar } from "@/components/tools/progress-bar";
import { ResultPanel } from "@/components/tools/result-panel";
import {
  compressPdf,
  deleteJob,
  type CompressResult,
  type Level,
} from "@/lib/api";
import { formatBytes, formatPercent } from "@/lib/format";
import {
  fadeRise,
  fadeRiseReduced,
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";
import { useToolJob, type JobStatus } from "@/lib/use-tool-job";

// Written out in full so Next can inline it at build time. The backend's own
// MAX_UPLOAD_MB stays the authority; this only saves a doomed upload.
const parsedMaxMb = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
const MAX_UPLOAD_MB =
  Number.isFinite(parsedMaxMb) && parsedMaxMb > 0 ? parsedMaxMb : 100;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

const ACCEPT = { "application/pdf": [".pdf"] };

// Errors worth a retry button. The others (not a PDF, encrypted, corrupt,
// too large) fail the same way every time, so the user picks another file.
const RETRYABLE_CODES = new Set([
  "network_error",
  "processing_failed",
  "internal_error",
  "unexpected_response",
]);

const primaryClass =
  "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent-violet px-6 text-sm font-medium text-background shadow-glow sm:w-auto";
const secondaryClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-border bg-surface-raised px-6 text-sm font-medium text-foreground";

type AnnouncementInput = {
  status: JobStatus;
  file: File | null;
  progress: number;
  result: CompressResult | null;
  downloaded: boolean;
  cancelled: boolean;
};

// Derived during render, so there is no effect and no extra state. The text
// only changes at meaningful moments (upload progress moves in 25% steps),
// which is what keeps the polite live region from chattering.
function buildAnnouncement({
  status,
  file,
  progress,
  result,
  downloaded,
  cancelled,
}: AnnouncementInput): string {
  switch (status) {
    case "idle":
      return "";
    case "ready":
      if (!file) return "";
      return cancelled
        ? "Upload cancelled. Press Compress PDF to try again."
        : `Selected ${file.name}, ${formatBytes(file.size)}. Choose a compression level, then press Compress PDF.`;
    case "uploading": {
      const step = Math.floor(progress / 25) * 25;
      return step === 0 ? "Uploading your PDF." : `Uploading, ${step} percent.`;
    }
    case "processing":
      return "Compressing your PDF.";
    case "done":
      if (!result) return "";
      if (downloaded) {
        return "Download started. The file is deleted from this machine once it has been sent.";
      }
      return result.already_optimized
        ? "This PDF is already optimized, so the original was kept."
        : `Done. Your PDF is ${formatPercent(result.saved_percent)} smaller, from ${formatBytes(result.original_size)} to ${formatBytes(result.compressed_size)}.`;
    case "error":
      // The error banner has role alert and announces itself.
      return "";
  }
}

export function CompressWorkspace() {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const enter = reduced ? fadeRiseReduced : fadeRise;

  const job = useToolJob<CompressResult>();
  const { status, file, progress, result, error } = job;

  const [level, setLevel] = useState<Level>("balanced");
  const [rejection, setRejection] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const dropzoneRef = useRef<FileDropzoneHandle>(null);
  const compressButtonRef = useRef<HTMLButtonElement>(null);
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
      compressButtonRef.current?.focus();
    } else if (status === "done") {
      resultHeadingRef.current?.focus();
    } else if (status === "error") {
      errorRef.current?.focus();
    } else if (status === "idle") {
      dropzoneRef.current?.focus();
    }
  }, [status]);

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

  function handleCompress() {
    setCancelled(false);
    job.start((selected, callbacks) => compressPdf(selected, level, callbacks));
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

  const announcement = buildAnnouncement({
    status,
    file,
    progress,
    result,
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
            accept={ACCEPT}
            maxSizeBytes={MAX_UPLOAD_BYTES}
            onSelect={handleSelect}
            onReject={setRejection}
          />
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
              onRetry={retryable ? handleCompress : undefined}
            />
          )}

          <LevelSelector value={level} onChange={setLevel} disabled={busy} />

          {/* aria-disabled instead of disabled (or unmounting) so the button
              keeps keyboard focus while the job runs. */}
          <div className="flex flex-col items-start gap-4">
            <motion.button
              ref={compressButtonRef}
              type="button"
              aria-disabled={busy}
              onClick={() => {
                if (!busy) handleCompress();
              }}
              whileHover={busy ? undefined : interactions.hover}
              whileTap={busy ? undefined : interactions.tap}
              transition={microTransition}
              className={`${primaryClass}${busy ? " cursor-not-allowed opacity-60" : ""}`}
            >
              <Minimize2 aria-hidden="true" className="size-4" />
              Compress PDF
            </motion.button>

            {busy && (
              <div className="flex w-full flex-col gap-3">
                {status === "uploading" ? (
                  <ProgressBar label="Uploading" value={progress} />
                ) : (
                  <ProgressBar label="Compressing" />
                )}
                {status === "uploading" && (
                  <div>
                    <motion.button
                      type="button"
                      onClick={handleCancel}
                      whileHover={interactions.hover}
                      whileTap={interactions.tap}
                      transition={microTransition}
                      className={secondaryClass}
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

      {showResult && result && (
        <motion.div
          key={reduced ? "reduced" : "full"}
          variants={enter}
          initial="hidden"
          animate="visible"
        >
          <ResultPanel
            result={result}
            downloaded={downloaded}
            onDownload={handleDownload}
            onReset={handleAnother}
            headingRef={resultHeadingRef}
          />
        </motion.div>
      )}
    </div>
  );
}