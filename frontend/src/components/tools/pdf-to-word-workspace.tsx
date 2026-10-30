"use client";

import { FileText } from "lucide-react";
import {
  PdfConvertWorkspace,
  type PdfConvertSummary,
} from "@/components/tools/pdf-convert-workspace";
import { convertPdfToWord, type PdfToWordResult } from "@/lib/api";
import { formatBytes } from "@/lib/format";

const FIDELITY_NOTE =
  "Works best on PDFs made from text documents. Complex layouts, unusual fonts and tables can shift, and scanned pages stay as pictures because there is no text recognition. Check the result in Word.";

function describe(result: PdfToWordResult): PdfConvertSummary {
  const pages = `${result.page_count} ${result.page_count === 1 ? "page" : "pages"}`;

  return {
    title: "Your Word document is ready",
    description: `It will download as ${result.download_name}.`,
    downloadLabel: "Download Word file",
    announcement: `Done. Your PDF with ${pages} was converted to a Word document of ${formatBytes(result.result_size)}.`,
    rows: [
      { label: "Pages", value: String(result.page_count) },
      { label: "PDF", value: formatBytes(result.original_size) },
      { label: "Word file", value: formatBytes(result.result_size) },
    ],
  };
}

export function PdfToWordWorkspace() {
  return (
    <PdfConvertWorkspace
      actionLabel="Convert to Word"
      actionIcon={<FileText aria-hidden="true" className="size-4" />}
      busyLabel="Converting to Word"
      busyAnnouncement="Converting your PDF to Word."
      fidelityNote={FIDELITY_NOTE}
      run={convertPdfToWord}
      describe={describe}
      resetLabel="Convert another"
    />
  );
}