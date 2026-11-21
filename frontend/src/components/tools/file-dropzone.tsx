"use client";

import { motion } from "framer-motion";
import { Upload } from "lucide-react";
import { useId, useImperativeHandle, type Ref } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { formatBytes } from "@/lib/format";
import { scaleIn, scaleInReduced } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useReducedMotionSafe } from "@/lib/use-reduced-motion-safe";

export type FileDropzoneHandle = {
  focus: () => void;
};

type FileDropzoneProps = {
  accept: Record<string, string[]>;
  maxSizeBytes: number;
  label?: string;
  fileDescription?: string;
  disabled?: boolean;
  onSelect: (file: File) => void;
  onReject: (message: string) => void;
  ref?: Ref<FileDropzoneHandle>;
};

const DEFAULT_LABEL = "Drop a PDF here, or choose a file";

function rejectionMessage(
  rejections: FileRejection[],
  maxSizeBytes: number,
  fileDescription: string,
): string {
  const codes = new Set(
    rejections.flatMap((rejection) =>
      rejection.errors.map((error) => error.code),
    ),
  );

  if (rejections.length > 1 || codes.has("too-many-files")) {
    return "Please choose one file at a time.";
  }
  if (codes.has("file-invalid-type")) {
    return `That file isn't a ${fileDescription}. Please choose the right file type.`;
  }
  if (codes.has("file-too-large")) {
    return `That file is larger than ${formatBytes(maxSizeBytes)}. Please choose a smaller file.`;
  }
  return "That file can't be used. Please choose a different file.";
}

export function FileDropzone({
  accept,
  maxSizeBytes,
  label = DEFAULT_LABEL,
  fileDescription = "PDF",
  disabled = false,
  onSelect,
  onReject,
  ref,
}: FileDropzoneProps) {
  const reduced = useReducedMotionSafe();
  const hintId = useId();

  const { getRootProps, getInputProps, isDragActive, isDragReject, rootRef } =
    useDropzone({
      accept,
      maxSize: maxSizeBytes,
      multiple: false,
      disabled,
      onDropAccepted: (files) => {
        const file = files[0];
        if (file) onSelect(file);
      },
      onDropRejected: (rejections) => {
        onReject(rejectionMessage(rejections, maxSizeBytes, fileDescription));
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
      ? `Only one ${fileDescription} will work`
      : `Drop to select this ${fileDescription}`
    : label;

  return (
    <motion.div
      key={reduced ? "reduced" : "full"}
      variants={reduced ? scaleInReduced : scaleIn}
      initial="hidden"
      animate="visible"
    >
      <div
        {...getRootProps({
          role: "button",
          "aria-label": label,
          "aria-describedby": hintId,
          "aria-disabled": disabled,
        })}
        data-drag={isDragActive ? "true" : "false"}
        className={cn(
          "group flex cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed bg-surface px-6 py-14 text-center transition-[border-color,box-shadow,background-color] duration-300",
          isDragActive && isDragReject
            ? "border-accent-amber bg-surface-raised"
            : isDragActive
              ? "border-accent-violet bg-surface-raised shadow-glow"
              : "border-border hover:border-accent-violet",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        <input {...getInputProps()} />

        <span className="inline-flex size-14 items-center justify-center rounded-xl border border-border bg-surface-raised text-accent-violet transition-transform duration-300 ease-overshoot motion-safe:group-data-[drag=true]:-translate-y-1 motion-safe:group-data-[drag=true]:scale-110">
          <Upload aria-hidden="true" className="size-7" />
        </span>

        <div className="flex flex-col gap-1">
          <p className="font-display text-xl tracking-tight text-foreground sm:text-2xl">
            {title}
          </p>
          <p id={hintId} className="text-sm text-muted">
            One {fileDescription}, up to {formatBytes(maxSizeBytes)}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
