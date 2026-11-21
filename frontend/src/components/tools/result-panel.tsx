"use client";

import {
  animate,
  motion,
  useMotionValue,
  useTransform,
} from "framer-motion";
import { PdfOutputActions } from "@/components/tools/pdf-output-actions";
import { useEffect, useId, type Ref } from "react";
import type { CompressResult } from "@/lib/api";
import { formatBytes, formatPercent } from "@/lib/format";
import {
  durations,
  smoothOut,
} from "@/lib/motion";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type ResultPanelProps = {
  result: CompressResult;
  onDownload: () => void;
  onReset: () => void;
  resetLabel?: string;
  // Focus target for the workspace when the result appears.
  headingRef?: Ref<HTMLHeadingElement>;
};

export function ResultPanel({
  result,
  onDownload,
  onReset,
  resetLabel = "Compress another",
  headingRef,
}: ResultPanelProps) {
  const reduced = useReducedMotionSafe();
  const headingId = useId();

  const optimized = result.already_optimized;
  const target = Number.isFinite(result.saved_percent)
    ? Math.min(100, Math.max(0, result.saved_percent))
    : 0;

  // Counts up once. Shown immediately under reduced motion.
  const count = useMotionValue(reduced ? target : 0);
  const countText = useTransform(count, formatPercent);

  useEffect(() => {
    if (reduced) {
      count.set(target);
      return undefined;
    }
    const controls = animate(count, target, {
      duration: durations.slow,
      ease: smoothOut,
    });
    return () => {
      controls.stop();
    };
  }, [count, reduced, target]);

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
          {optimized ? "Already optimized" : "Your PDF is ready"}
        </h2>
        <p className="min-w-0 break-words text-sm leading-relaxed text-muted">
          {optimized
            ? "This PDF is already as small as we can make it without hurting quality, so we kept the original. There was nothing to save."
            : `It will download as ${result.original_name}-compressed.pdf.`}
        </p>
      </div>

      {optimized ? (
        <dl>
          <div className="flex flex-col gap-1">
            <dt className="text-xs text-muted">File size</dt>
            <dd className="font-display text-2xl text-foreground">
              {formatBytes(result.original_size)}
            </dd>
          </div>
        </dl>
      ) : (
        <>
          <div className="flex flex-col gap-3">
            <p className="font-display text-5xl tracking-tight text-accent-violet sm:text-6xl">
              <span aria-hidden="true">
                <motion.span>{countText}</motion.span>
              </span>
              <span className="sr-only">
                Saved {formatPercent(result.saved_percent)}
              </span>
              <span
                aria-hidden="true"
                className="ml-3 text-base text-muted sm:text-lg"
              >
                smaller
              </span>
            </p>

            <div
              aria-hidden="true"
              className="h-3 w-full overflow-hidden rounded-full bg-surface-raised"
            >
              <motion.div
                key={reduced ? "reduced" : "full"}
                className="h-full rounded-full bg-(image:--gradient-accent)"
                initial={reduced ? false : { width: "0%" }}
                animate={{ width: `${target}%` }}
                transition={{ duration: durations.slow, ease: smoothOut }}
              />
            </div>
            <p className="text-sm text-muted">
              {formatBytes(result.saved_bytes)} saved
            </p>
          </div>

          <dl className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <dt className="text-xs text-muted">Original</dt>
              <dd className="font-display text-xl text-foreground">
                {formatBytes(result.original_size)}
              </dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-xs text-muted">Compressed</dt>
              <dd className="font-display text-xl text-foreground">
                {formatBytes(result.compressed_size)}
              </dd>
            </div>
          </dl>
        </>
      )}

      <PdfOutputActions key={result.job_id} url={result.download_url} name={`${result.original_name}-compressed.pdf`}
        downloadLabel="Download PDF" resetLabel={resetLabel} onDownload={onDownload} onReset={onReset} />
    </section>
  );
}
