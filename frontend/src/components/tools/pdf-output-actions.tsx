"use client";

import { ArrowRight, Download, RotateCcw } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { buildDownloadUrl } from "@/lib/api";
import { stageWorkflowFile } from "@/lib/workflow-handoff";
import { MAX_UPLOAD_BYTES } from "@/lib/tool-limits";
import { formatBytes } from "@/lib/format";

const targets = [
  ["compress-pdf", "Compress"], ["redact-pdf", "Redact & Scrub"],
  ["pdf-to-markdown", "AI Markdown"], ["compare-pdf", "Compare PDF"],
] as const;

type Props = {
  url: string; name: string; downloadLabel: string; resetLabel: string;
  onDownload: () => void; onReset: () => void;
};

export function PdfOutputActions({ url, name, downloadLabel, resetLabel, onDownload, onReset }: Props) {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const cache = useRef<File | null>(null);
  const request = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => {
    request.current?.abort();
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    cache.current = null;
  }, []);

  async function handleOutput(target?: string) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      let file = cache.current;
      if (!file) {
        const response = await fetch(buildDownloadUrl(url), {
          cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(180_000)]),
        });
        if (response.status === 404) throw new Error("This result has expired. Process the file again.");
        if (!response.ok) throw new Error("The PDF could not be retrieved. Try again.");
        const blob = await response.blob();
        if (!blob.size || !blob.type.startsWith("application/pdf")) throw new Error("The engine returned an unreadable PDF result.");
        file = new File([blob], name, { type: "application/pdf" });
        if (controller.signal.aborted) return;
        cache.current = file;
      }
      if (target) {
        if (file.size > MAX_UPLOAD_BYTES) throw new Error(`This output exceeds the next tool’s ${formatBytes(MAX_UPLOAD_BYTES)} limit. You can still download it.`);
        stageWorkflowFile(target, file);
        router.push(`/tools/${target}`);
      } else {
        objectUrl.current ??= URL.createObjectURL(file);
        const link = document.createElement("a");
        link.href = objectUrl.current;
        link.download = file.name;
        document.body.append(link);
        link.click();
        link.remove();
        onDownload();
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof TypeError || cause instanceof DOMException
        ? "The engine is unavailable or timed out. Check the connection and try again."
        : cause instanceof Error ? cause.message : "Could not retrieve the PDF.");
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return <div className="grid gap-4">
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={busy} className="studio-primary" onClick={() => void handleOutput()}><Download size={15}/>{downloadLabel}</button>
      <button type="button" disabled={busy} className="studio-secondary" onClick={onReset}><RotateCcw size={15}/>{resetLabel}</button>
    </div>
    <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4" aria-label="Continue in Studio">
      <span className="mr-1 inline-flex items-center gap-1 text-sm font-medium">Continue in Studio <ArrowRight size={14}/></span>
      {targets.filter(([target]) => target !== slug).map(([target, label]) => <button key={target} type="button"
        disabled={busy} className="rounded-full border border-border bg-surface-raised px-3 py-2 text-xs hover:border-accent-violet"
        onClick={() => void handleOutput(target)}>{label}</button>)}
    </div>
    {busy && <p role="status" className="text-sm text-muted">Preparing your PDF…</p>}
    {error && <p role="alert" className="text-sm text-accent-amber">{error}</p>}
  </div>;
}
