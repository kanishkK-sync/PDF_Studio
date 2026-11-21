"use client";

import { useEffect, useState } from "react";
import { isWorkflowFile } from "@/lib/workflow-handoff";

export function FileTelemetryBar({ file }: { file: File }) {
  const [header, setHeader] = useState<{ file: File; value: string } | null>(null);
  const ext = file.name.split(".").pop()?.toUpperCase() ?? "";
  useEffect(() => {
    if (ext !== "PDF") return;
    let active = true;
    file.slice(0, 1024).arrayBuffer().then(data => {
      const match = new TextDecoder("latin1").decode(data).match(/%PDF-(\d\.\d)/);
      if (active) setHeader({ file, value: match ? `PDF ${match[1]}` : "PDF header unrecognized" });
    }).catch(() => { if (active) setHeader({ file, value: "Header unavailable" }); });
    return () => { active = false; };
  }, [file, ext]);
  return <div className="file-telemetry" aria-label="Document details">
    {isWorkflowFile(file) && <span className="rounded bg-surface-raised px-2 text-accent-violet">Loaded from previous step</span>}
    {ext === "PDF" && <span>{header?.file === file ? header.value : "Reading PDF header…"}</span>}
    <span>{file.size.toLocaleString()} bytes</span><span>.{ext.toLowerCase()} extension verified</span>
  </div>;
}
