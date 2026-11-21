"use client";

import { motion } from "framer-motion";
import { Download, RotateCcw } from "lucide-react";
import { useId, useRef, type MouseEvent, type Ref } from "react";
import { buildDownloadUrl } from "@/lib/api";
import {
  microInteractions,
  microInteractionsReduced,
  microTransition,
} from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export type ResultRow = {
  label: string;
  value: string;
};

type ConversionResultProps = {
  title: string;
  description: string;
  rows: readonly ResultRow[];
  // The contract's relative download_url; resolved against the API host here.
  downloadUrl: string;
  downloadLabel: string;
  // True once the download link was clicked. The server deletes the file
  // after sending it, so a second download cannot work.
  downloaded: boolean;
  onDownload: () => void;
  onReset: () => void;
  resetLabel: string;
  // Focus target for the workspace when the result appears.
  headingRef?: Ref<HTMLHeadingElement>;
};

const primaryClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-accent-violet px-6 text-sm font-medium text-background shadow-glow";
const secondaryClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-border bg-surface-raised px-6 text-sm font-medium text-foreground";

export function ConversionResult({
  title,
  description,
  rows,
  downloadUrl,
  downloadLabel,
  downloaded,
  onDownload,
  onReset,
  resetLabel,
  headingRef,
}: ConversionResultProps) {
  const reduced = useReducedMotionSafe();
  const interactions = reduced ? microInteractionsReduced : microInteractions;
  const headingId = useId();
  const downloadStarted = useRef(false);

  function handleDownloadClick(event: MouseEvent<HTMLAnchorElement>) {
    if (downloaded || downloadStarted.current) {
      event.preventDefault();
      return;
    }
    downloadStarted.current = true;
    onDownload();
  }

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-6 rounded-2xl border border-border bg-surface p-6 shadow-soft sm:p-8"
    >
      <div className="flex flex-col gap-2">
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="font-display text-2xl tracking-tight text-foreground outline-none sm:text-3xl"
        >
          {title}
        </h2>
        <p className="min-w-0 break-words text-sm leading-relaxed text-muted">
          {description}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {rows.map((row) => (
          <div key={row.label} className="flex min-w-0 flex-col gap-1">
            <dt className="text-xs text-muted">{row.label}</dt>
            <dd className="break-words font-display text-xl text-foreground">
              {row.value}
            </dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-3 sm:flex-row">
        <motion.a
          href={buildDownloadUrl(downloadUrl)}
          aria-disabled={downloaded}
          aria-label={downloadLabel}
          tabIndex={downloaded ? -1 : 0}
          onClick={handleDownloadClick}
          whileHover={downloaded ? undefined : interactions.hover}
          whileTap={downloaded ? undefined : interactions.tap}
          transition={microTransition}
          className={cn(
            primaryClass,
            "focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-violet",
            downloaded && "pointer-events-none opacity-60",
          )}
        >
          <Download aria-hidden="true" className="size-4" />
          {downloaded ? "Downloaded" : downloadLabel}
        </motion.a>

        <motion.button
          type="button"
          onClick={onReset}
          whileHover={interactions.hover}
          whileTap={interactions.tap}
          transition={microTransition}
          className={`${secondaryClass} focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-violet`}
        >
          <RotateCcw aria-hidden="true" className="size-4" />
          {resetLabel}
        </motion.button>
      </div>

      <p className="text-xs leading-relaxed text-muted">
        {downloaded
          ? "Downloaded. The file has been deleted from this machine."
          : "Once you download it, the file is deleted from this machine."}
      </p>
    </section>
  );
}
