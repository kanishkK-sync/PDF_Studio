"use client";

import { motion } from "framer-motion";
import { FileText, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import {
  ConversionResult,
  type ResultRow,
} from "@/components/tools/conversion-result";
import { ErrorBanner } from "@/components/tools/error-banner";
import type { FileDropzoneHandle } from "@/components/tools/file-dropzone";
import { ImageList } from "@/components/tools/image-list";
import { ImagesDropzone } from "@/components/tools/images-dropzone";
import {
  OptionGroup,
  type ChoiceOption,
} from "@/components/tools/option-group";
import { ProgressBar } from "@/components/tools/progress-bar";
import {
  deleteJob,
  jpgToPdf,
  type JpgToPdfResult,
  type PageSize,
} from "@/lib/api";
import { formatBytes } from "@/lib/format";
import {
  fadeRise,
  fadeRiseReduced,
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import {
  MAX_IMAGES,
  MAX_UPLOAD_BYTES,
  RETRYABLE_CODES,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/lib/tool-limits";
import { cn } from "@/lib/utils";
import { useMultiFileJob } from "@/lib/use-multi-file-job";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";
import type { JobStatus } from "@/lib/use-tool-job";

const ACCEPT = {
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
};

const PAGE_SIZE_OPTIONS: readonly ChoiceOption<PageSize>[] = [
  {
    id: "fit",
    title: "Fit to image",
    description:
      "Each page is exactly as big as its picture. Nothing is cropped or padded.",
  },
  {
    id: "a4",
    title: "A4",
    description:
      "Each picture is centred on an A4 page with a margin, upright or sideways to match.",
  },
];

const PAGE_SIZE_LABELS: Record<PageSize, string> = {
  fit: "Same as each image",
  a4: "A4",
};

function imageCount(count: number): string {
  return `${count} ${count === 1 ? "image" : "images"}`;
}

type AnnouncementInput = {
  status: JobStatus;
  count: number;
  totalBytes: number;
  progress: number;
  result: JpgToPdfResult | null;
  downloaded: boolean;
  cancelled: boolean;
};

// Derived during render, so there is no effect and no extra state. The text
// only changes at meaningful moments (upload progress moves in 25% steps),
// which keeps the polite live region from chattering.
function buildAnnouncement({
  status,
  count,
  totalBytes,
  progress,
  result,
  downloaded,
  cancelled,
}: AnnouncementInput): string {
  switch (status) {
    case "idle":
      return "";
    case "ready":
      return cancelled
        ? "Upload cancelled. Press Create PDF to try again."
        : `${imageCount(count)} selected, ${formatBytes(totalBytes)}. Reorder them if needed, choose a page size, then press Create PDF.`;
    case "uploading": {
      const step = Math.floor(progress / 25) * 25;
      return step === 0
        ? "Uploading your images."
        : `Uploading, ${step} percent.`;
    }
    case "processing":
      return "Building your PDF.";
    case "done":
      if (!result) return "";
      if (downloaded) {
        return "Download started. The file is deleted from this machine once it has been sent.";
      }
      return `Done. Your PDF has ${result.page_count} ${result.page_count === 1 ? "page" : "pages"} and is ${formatBytes(result.result_size)}.`;
    case "error":
      // The error banner has role alert and announces itself.
      return "";
  }
}

export function JpgToPdfWorkspace() {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const enter = reduced ? fadeRiseReduced : fadeRise;
  const limitId = useId();

  const job = useMultiFileJob<JpgToPdfResult>(MAX_IMAGES, MAX_UPLOAD_BYTES);
  const { status, entries, progress, result, error } = job;

  const [pageSize, setPageSize] = useState<PageSize>("fit");
  // A problem with the picked files (wrong type, too many), shown as a banner.
  const [notice, setNotice] = useState<string | null>(null);
  // The latest list change, for the live region ("Moved a.jpg to position 2").
  const [note, setNote] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const dropzoneRef = useRef<FileDropzoneHandle>(null);
  const convertButtonRef = useRef<HTMLButtonElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousStatusRef = useRef<JobStatus>("idle");
  // The job on the server that nobody has downloaded yet, if any.
  const pendingJobRef = useRef<string | null>(null);

  // Focus follows the state: first files chosen or upload cancelled -> primary
  // button, result -> its heading, error -> the banner, back to idle -> the
  // dropzone. Going from error to ready (the user changed the list) must not
  // steal focus from the list, so that case is left alone.
  useEffect(() => {
    const previous = previousStatusRef.current;
    previousStatusRef.current = status;
    if (previous === status) return;

    if (status === "ready") {
      if (previous === "idle" || previous === "uploading") {
        convertButtonRef.current?.focus();
      }
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

  function handleSelect(files: File[]) {
    setCancelled(false);
    setDownloaded(false);
    const { added, skipped, overTotal, overCount } = job.add(files);
    if (skipped > 0) {
      setNotice([
        overTotal > 0 ? `${overTotal} ${overTotal === 1 ? "image was" : "images were"} skipped because the total would exceed ${formatBytes(MAX_UPLOAD_BYTES)}.` : "",
        overCount > 0 ? `${overCount} ${overCount === 1 ? "image was" : "images were"} skipped because the limit is ${MAX_IMAGES} images.` : "",
      ].filter(Boolean).join(" "));
    } else {
      setNotice(null);
    }
    if (added > 0) {
      setNote(
        entries.length > 0
          ? `Added ${imageCount(added)}. ${imageCount(entries.length + added)} selected.`
          : null,
      );
    }
  }

  function handleMove(id: string, delta: -1 | 1) {
    const index = entries.findIndex((entry) => entry.id === id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= entries.length) return;
    const name = entries[index]?.file.name ?? "Image";
    job.move(id, delta);
    setNote(`Moved ${name} to position ${target + 1} of ${entries.length}.`);
  }

  function handleRemove(id: string) {
    const entry = entries.find((item) => item.id === id);
    if (!entry) return;
    job.remove(id);
    setCancelled(false);
    setNotice(null);
    setNote(
      `Removed ${entry.file.name}. ${imageCount(entries.length - 1)} left.`,
    );
  }

  function handleConvert() {
    if (entries.length === 0) return;
    setNotice(null);
    setNote(null);
    setCancelled(false);
    job.start((files, callbacks) => jpgToPdf(files, pageSize, callbacks));
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
    setNotice(null);
    setNote(null);
    setCancelled(false);
    job.clear();
  }

  const busy = status === "uploading" || status === "processing";
  const showPick = status === "idle";
  const showResult = status === "done" && result !== null;
  const showConfigure = !showPick && !showResult;
  const retryable = error !== null && RETRYABLE_CODES.has(error.code);

  const totalBytes = entries.reduce((sum, entry) => sum + entry.file.size, 0);
  const overLimit = totalBytes > MAX_UPLOAD_BYTES;
  const remaining = Math.max(0, MAX_IMAGES - entries.length);
  const canConvert = !busy && entries.length > 0 && !overLimit;

  const announcement =
    note ??
    buildAnnouncement({
      status,
      count: entries.length,
      totalBytes,
      progress,
      result,
      downloaded,
      cancelled,
    });

  const rows: ResultRow[] = result
    ? [
        { label: "Pages", value: String(result.page_count) },
        { label: "Page size", value: PAGE_SIZE_LABELS[result.page_size] },
        { label: "Images", value: formatBytes(result.total_input_size) },
        { label: "PDF", value: formatBytes(result.result_size) },
      ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      {showPick && (
        <div className="flex flex-col gap-4">
          {notice && <ErrorBanner message={notice} />}
          <ImagesDropzone
            ref={dropzoneRef}
            accept={ACCEPT}
            maxBytes={MAX_UPLOAD_BYTES}
            label="Drop JPG or PNG images here, or choose files"
            hint={`Up to ${MAX_IMAGES} images, ${formatBytes(MAX_UPLOAD_BYTES)} in total`}
            onSelect={handleSelect}
            onReject={setNotice}
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
          {notice && <ErrorBanner message={notice} />}

          {status === "error" && error && (
            <ErrorBanner
              ref={errorRef}
              message={error.message}
              onRetry={retryable ? handleConvert : undefined}
            />
          )}

          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-foreground">
                {imageCount(entries.length)}, {formatBytes(totalBytes)}
              </p>
              <p className="text-sm text-muted">
                Pages follow this order. Use the arrow buttons to change it.
              </p>
              {overLimit && (
                <p id={limitId} className="text-sm text-accent-amber">
                  Together these are larger than the {formatBytes(MAX_UPLOAD_BYTES)}{" "}
                  limit. Remove some images to continue.
                </p>
              )}
            </div>

            <ImageList
              entries={entries}
              disabled={busy}
              onMove={handleMove}
              onRemove={handleRemove}
            />

            <ImagesDropzone
              compact
              accept={ACCEPT}
              maxBytes={MAX_UPLOAD_BYTES}
              label="Add more images"
              hint={
                remaining > 0
                  ? `You can add ${imageCount(remaining)} more`
                  : `The limit of ${MAX_IMAGES} images is reached`
              }
              disabled={busy || remaining === 0}
              onSelect={handleSelect}
              onReject={setNotice}
            />
          </div>

          <OptionGroup
            label="Page size"
            options={PAGE_SIZE_OPTIONS}
            value={pageSize}
            onChange={(value) => {
              setPageSize(value);
            }}
            disabled={busy}
            columns={2}
          />

          <div className="flex flex-col items-start gap-4">
            <motion.button
              ref={convertButtonRef}
              type="button"
              disabled={!canConvert}
              aria-disabled={!canConvert}
              aria-describedby={overLimit ? limitId : undefined}
              onClick={() => {
                if (canConvert) handleConvert();
              }}
              whileHover={canConvert ? interactions.hover : undefined}
              whileTap={canConvert ? interactions.tap : undefined}
              transition={microTransition}
              className={cn(
                primaryButtonClass,
                !canConvert && "cursor-not-allowed opacity-60",
              )}
            >
              <FileText aria-hidden="true" className="size-4" />
              Create PDF
            </motion.button>

            {busy && (
              <div className="flex w-full flex-col gap-3">
                {status === "uploading" ? (
                  <ProgressBar label="Uploading" value={progress} />
                ) : (
                  <ProgressBar label="Building your PDF" />
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

      {showResult && result && (
        <motion.div
          key={reduced ? "reduced" : "full"}
          variants={enter}
          initial="hidden"
          animate="visible"
        >
          <ConversionResult
            title="Your PDF is ready"
            description={`It will download as ${result.download_name}.`}
            rows={rows}
            downloadUrl={result.download_url}
            downloadLabel="Download PDF"
            downloaded={downloaded}
            onDownload={handleDownload}
            onReset={handleAnother}
            resetLabel="Convert more images"
            headingRef={resultHeadingRef}
          />
        </motion.div>
      )}
    </div>
  );
}
