"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { validateUploadFile } from "@/lib/file-guardrails";
import { MAX_UPLOAD_BYTES } from "@/lib/tool-limits";

const pdf = { "application/pdf": [".pdf"] };
const imported = new WeakSet<File>();
let pending: { target: string; file: File } | null = null;

export function stageWorkflowFile(target: string, file: File) {
  pending = { target, file };
}

export function consumeWorkflowFile(target: string) {
  if (pending?.target !== target) return null;
  const { file } = pending;
  pending = null;
  return file;
}

export function isWorkflowFile(file: File) { return imported.has(file); }

export function useWorkflowInput(select: (file: File) => void, reject: (message: string) => void) {
  const { slug } = useParams<{ slug: string }>();
  useEffect(() => {
    let active = true;
    // Consume after mount, including React's development setup/cleanup replay.
    queueMicrotask(() => {
      if (!active) return;
      const file = consumeWorkflowFile(slug);
      if (!file) return;
      const error = validateUploadFile(file, pdf, MAX_UPLOAD_BYTES);
      if (error) reject(error.message);
      else {
        imported.add(file);
        select(file);
      }
    });
    return () => { active = false; };
  }, [slug, select, reject]);
}
