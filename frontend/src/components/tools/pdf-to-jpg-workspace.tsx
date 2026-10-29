"use client";

import { motion } from "framer-motion";
import { FileImage, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
import {
  OptionGroup,
  type ChoiceOption,
} from "@/components/tools/option-group";
import { ProgressBar } from "@/components/tools/progress-bar";
import {
  convertPdfToJpg,
  deleteJob,
  type PdfToJpgResult,
  type Quality,
} from "@/lib/api";
import { formatBytes } from "@/lib/format";
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

// Errors worth a retry button. The others (not a PDF, encrypted, corrupt, too
// large, too many pages) fail the same way every time, so the user picks
// another file.
const RETRYABLE_CODES = new Set([
  "network_error",
  "processing_failed",
  "internal_error",
  "unexpected_response",
]);

const QUALITY_OPTIONS: readonly ChoiceOption<Quality>[] = [
  {
    id: "low",
    title: "Low",
    description:
      "Smallest files. About 100 DPI, fine for screens and quick sharing.",
  },
  {
    id: "medium",
    title: "Medium",
    description: "Best mix of size and sharpness. About 150 DPI.",
    badge: "Recommended",
  },
  {
    id: "high",
    title: "High",
    description: "Sharpest images. About 220 DPI, so the files are larger.",
  },
];

const QUALITY_LABELS: Record<Quality, string> = {
  low: "Low, about 100 DPI",
  medium: "Medium, about 150 DPI",
  high: "High, about 220 DPI",
};

const primaryClass =
  "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent-violet px-6 text-sm font-medium text-background shadow-glow sm:w-auto";
const secondaryClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-border bg-surface-raised px-6 text-sm font-medium text-foreground";

type AnnouncementInput = {
  status: JobStatus;
  file: File | null;
  progress: number;
  result: PdfToJpgResult | null;
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
        ? "Upload cancelled. Press Convert to JPG to try again."
        : `Selected ${file.name}, ${formatBytes(file.size)}. Choose an image quality, then press Convert to JPG.`;
    case "uploading": {
      const step = Math.floor(progress / 25) * 25;
      return step === 0 ? "Uploading your PDF." : `Uploading, ${step} percent.`;
    }
    case "processing":
      return "Converting your PDF to JPG images.";
    case "done":
      if (!result) return "";
      if (downloaded) {
        return "Download started. The file is deleted from this machine once it has been sent.";
      }
      return result.kind === "zip"
        ? `Done. ${result.page_count} pages were converted to JPG images and packed in a ZIP file of ${formatBytes(result.result_size)}.`
        : `Done. Your page was converted to a JPG image of ${formatBytes(result.result_size)}.`;
    case "error":
      // The error banner has role alert and announces itself.
      return "";
  }
}

type ResultSummary = {
  title: string;
  description: string;
  downloadLabel: string;
  rows: ResultRow[];
};

// The file name matches what the backend puts in Content-Disposition:
// "<name>.jpg" for one page, "<name>-jpg.zip" for several.
function describeResult(result: PdfToJpgResult): ResultSummary {
  const zip = result.kind === "zip";
  const downloadName = zip
    ? `${result.original_name}-jpg.zip`
    : `${result.original_name}.jpg`;

  return {
    title: zip ? "Your JPG images are ready" : "Your JPG image is ready",
    description: zip
      ? `It will download as ${downloadName}, with one JPG image for each page.`
      : `It will download as ${downloadName}.`,
    downloadLabel: zip ? "Download ZIP" : "Download JPG",
    rows: [
      { label: "Pages", value: String(result.page_count) },
      {
        label: "Result",
        value: zip ? `ZIP of ${result.file_count} JPGs` : "1 JPG image",
      },
      { label: "Quality", value: QUALITY_LABELS[result.quality] },
      { label: "Size", value: formatBytes(result.result_size) },
    ],
  };
}

export function PdfToJpgWorkspace() {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const enter = reduced ? fadeRiseReduced : fadeRise;

  const job = useToolJob<PdfToJpgResult>();
  const { status, file, progress, result, error } = job;

  const [quality, setQuality] = useState<Quality>("medium");
  const [rejection, setRejection] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const dropzoneRef = useRef<FileDropzoneHandle>(null);
  const convertButtonRef = useRef<HTMLButtonElement>(null);
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
      convertButtonRef.current?.focus();
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

  function handleConvert() {
    setCancelled(false);
    job.start((selected, callbacks) =>
      convertPdfToJpg(selected, quality, callbacks),
    );
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

  const summary = showResult && result ? describeResult(result) : null;

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
              onRetry={retryable ? handleConvert : undefined}
            />
          )}

          <OptionGroup
            label="Image quality"
            options={QUALITY_OPTIONS}
            value={quality}
            onChange={setQuality}
            disabled={busy}
          />

          {/* aria-disabled instead of disabled (or unmounting) so the button
              keeps keyboard focus while the job runs. */}
          <div className="flex flex-col items-start gap-4">
            <motion.button
              ref={convertButtonRef}
              type="button"
              aria-disabled={busy}
              onClick={() => {
                if (!busy) handleConvert();
              }}
              whileHover={busy ? undefined : interactions.hover}
              whileTap={busy ? undefined : interactions.tap}
              transition={microTransition}
              className={`${primaryClass}${busy ? " cursor-not-allowed opacity-60" : ""}`}
            >
              <FileImage aria-hidden="true" className="size-4" />
              Convert to JPG
            </motion.button>

            {busy && (
              <div className="flex w-full flex-col gap-3">
                {status === "uploading" ? (
                  <ProgressBar label="Uploading" value={progress} />
                ) : (
                  <ProgressBar label="Converting" />
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
            resetLabel="Convert another"
            headingRef={resultHeadingRef}
          />
        </motion.div>
      )}
    </div>
  );
}