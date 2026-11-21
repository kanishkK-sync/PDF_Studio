"use client";

import { motion } from "framer-motion";
import { Plus, Upload } from "lucide-react";
import { useId, useImperativeHandle, type Ref } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import type { FileDropzoneHandle } from "@/components/tools/file-dropzone";
import { formatBytes } from "@/lib/format";
import { validateUploadFile } from "@/lib/file-guardrails";
import { scaleIn, scaleInReduced } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

type ImagesDropzoneProps = {
  accept: Record<string, string[]>;
  // Largest single file. The workspace checks the total separately.
  maxBytes: number;
  label: string;
  hint: string;
  fileDescription?: string;
  // A small "add more" row instead of the large first-pick card.
  compact?: boolean;
  disabled?: boolean;
  onSelect: (files: File[]) => void;
  onReject: (message: string) => void;
  ref?: Ref<FileDropzoneHandle>;
};

function rejectionMessage(
  rejections: FileRejection[],
  maxBytes: number,
  fileDescription: string,
): string {
  const codes = new Set(
    rejections.flatMap((rejection) =>
      rejection.errors.map((error) => error.code),
    ),
  );

  const parts: string[] = [];
  for (const rejection of rejections.slice(0, 3)) {
    const custom = rejection.errors.find((error) =>
      ["file-empty", "file-invalid-extension", "file-too-large"].includes(error.code),
    );
    if (custom) parts.push(custom.message);
  }
  if (rejections.length > 3) parts.push(`${rejections.length - 3} more files were skipped.`);
  if (parts.length > 0) return parts.join(" ");
  if (codes.has("file-invalid-type")) {
    parts.push(`Only ${fileDescription} can be used, so other files were skipped.`);
  }
  if (codes.has("file-too-large")) {
    parts.push(
      `A file was larger than ${formatBytes(maxBytes)} and was skipped.`,
    );
  }
  return parts.length > 0
    ? parts.join(" ")
    : "Some files can't be used and were skipped.";
}

export function ImagesDropzone({
  accept,
  maxBytes,
  label,
  hint,
  fileDescription = "JPG and PNG pictures",
  compact = false,
  disabled = false,
  onSelect,
  onReject,
  ref,
}: ImagesDropzoneProps) {
  const reduced = useReducedMotionSafe();
  const hintId = useId();

  const { getRootProps, getInputProps, isDragActive, isDragReject, rootRef } =
    useDropzone({
      accept,
      multiple: true,
      disabled,
      validator: (file) => validateUploadFile(file, accept, maxBytes),
      onDropAccepted: (files) => {
        onSelect(files);
      },
      onDropRejected: (rejections) => {
        onReject(rejectionMessage(rejections, maxBytes, fileDescription));
      },
    });

  useImperativeHandle(
    ref,
    () => ({
      focus: () => {
        rootRef.current?.focus();
      },
    }),
    [rootRef],
  );

  const title = isDragActive
    ? isDragReject
      ? `Only ${fileDescription} will work`
      : `Drop to add these ${fileDescription}`
    : label;

  const zone = (
    <div
      {...getRootProps({
        role: "button",
        "aria-label": label,
        "aria-describedby": hintId,
        "aria-disabled": disabled,
      })}
      data-drag={isDragActive ? "true" : "false"}
      className={cn(
        "group flex cursor-pointer border-2 border-dashed bg-surface text-center transition-[border-color,box-shadow,background-color] duration-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-violet",
        compact
          ? "flex-row items-center justify-center gap-3 rounded-xl px-4 py-4"
          : "flex-col items-center justify-center gap-4 rounded-2xl px-6 py-14",
        isDragActive && isDragReject
          ? "border-accent-amber bg-surface-raised"
          : isDragActive
            ? "border-accent-violet bg-surface-raised shadow-glow"
            : "border-border hover:border-accent-violet",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <input {...getInputProps()} />

      {compact ? (
        <>
          <Plus aria-hidden="true" className="size-5 shrink-0 text-accent-violet" />
          <span className="flex min-w-0 flex-col items-start text-left">
            <span className="text-sm font-medium text-foreground">{title}</span>
            <span id={hintId} className="text-xs text-muted">
              {hint}
            </span>
          </span>
        </>
      ) : (
        <>
          <span className="inline-flex size-14 items-center justify-center rounded-xl border border-border bg-surface-raised text-accent-violet transition-transform duration-300 ease-overshoot motion-safe:group-data-[drag=true]:-translate-y-1 motion-safe:group-data-[drag=true]:scale-110">
            <Upload aria-hidden="true" className="size-7" />
          </span>
          <div className="flex flex-col gap-1">
            <p className="font-display text-xl tracking-tight text-foreground sm:text-2xl">
              {title}
            </p>
            <p id={hintId} className="text-sm text-muted">
              {hint}
            </p>
          </div>
        </>
      )}
    </div>
  );

  if (compact) return zone;

  return (
    <motion.div
      key={reduced ? "reduced" : "full"}
      variants={reduced ? scaleInReduced : scaleIn}
      initial="hidden"
      animate="visible"
    >
      {zone}
    </motion.div>
  );
}
