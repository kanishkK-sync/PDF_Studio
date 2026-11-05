"use client";

import { FileSpreadsheet } from "lucide-react";
import {
  PdfConvertWorkspace,
  type PdfConvertSummary,
} from "@/components/tools/pdf-convert-workspace";
import { convertPdfToExcel, type PdfToExcelResult } from "@/lib/api";
import { formatBytes } from "@/lib/format";

const FIDELITY_NOTE =
  "Works best on PDFs that contain real tables. Each table becomes its own sheet. If the PDF has no tables, its text goes into one sheet instead. Scanned PDFs have no text to read, because there is no text recognition.";

function describe(result: PdfToExcelResult): PdfConvertSummary {
  const count = result.table_count;
  const tables = result.mode === "tables";

  return {
    title: "Your Excel workbook is ready",
    description: tables
      ? `It will download as ${result.download_name}. Each table found is on its own sheet, named by page and table number, for example "P1 T1".`
      : `It will download as ${result.download_name}. No tables were found, so the text of the PDF is in one sheet named "Text", with one line per row and its page number.`,
    downloadLabel: "Download Excel file",
    announcement: tables
      ? `Done. Found ${count} ${count === 1 ? "table" : "tables"} in your PDF and put ${count === 1 ? "it" : "each"} on its own sheet. The Excel file is ${formatBytes(result.result_size)}.`
      : `Done. No tables were found, so the text of your PDF was put in one sheet. The Excel file is ${formatBytes(result.result_size)}.`,
    rows: [
      { label: "Pages", value: String(result.page_count) },
      {
        label: "Tables",
        value: result.table_count > 0 ? String(result.table_count) : "None found",
      },
      { label: "PDF", value: formatBytes(result.original_size) },
      { label: "Excel file", value: formatBytes(result.result_size) },
    ],
  };
}

export function PdfToExcelWorkspace() {
  return (
    <PdfConvertWorkspace<PdfToExcelResult>
      actionLabel="Convert to Excel"
      actionIcon={<FileSpreadsheet aria-hidden="true" className="size-4" />}
      busyLabel="Converting to Excel"
      busyAnnouncement="Converting your PDF to Excel."
      fidelityNote={FIDELITY_NOTE}
      run={convertPdfToExcel}
      describe={describe}
      resetLabel="Convert another"
    />
  );
}