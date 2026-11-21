import type { ReactElement } from "react";
import { CompressWorkspace } from "@/components/tools/compress-workspace";
import { JpgToPdfWorkspace } from "@/components/tools/jpg-to-pdf-workspace";
import { MergePdfWorkspace } from "@/components/tools/merge-pdf-workspace";
import { EditPdfWorkspace, ExcelToPdfWorkspace, PowerpointToPdfWorkspace, SplitPdfWorkspace, WordToPdfWorkspace } from "@/components/tools/remaining-single-workspaces";
import { PdfToExcelWorkspace } from "@/components/tools/pdf-to-excel-workspace";
import { PdfToJpgWorkspace } from "@/components/tools/pdf-to-jpg-workspace";
import { PdfToPptxWorkspace } from "@/components/tools/pdf-to-pptx-workspace";
import { PdfToWordWorkspace } from "@/components/tools/pdf-to-word-workspace";

// Tool slug -> function that renders its interactive workspace. A slug that is
// not listed keeps the Coming soon panel. Add one line here when a later phase
// builds a tool. Returning an element (not a component) keeps the page from
// creating components during render.
const workspaces: Readonly<Record<string, () => ReactElement>> = {
  "compress-pdf": () => <CompressWorkspace />,
  "pdf-to-jpg": () => <PdfToJpgWorkspace />,
  "jpg-to-pdf": () => <JpgToPdfWorkspace />,
  "pdf-to-word": () => <PdfToWordWorkspace />,
  "pdf-to-excel": () => <PdfToExcelWorkspace />,
  "pdf-to-powerpoint": () => <PdfToPptxWorkspace />,
  "edit-pdf": () => <EditPdfWorkspace />,
  "merge-pdf": () => <MergePdfWorkspace />,
  "split-pdf": () => <SplitPdfWorkspace />,
  "word-to-pdf": () => <WordToPdfWorkspace />,
  "powerpoint-to-pdf": () => <PowerpointToPdfWorkspace />,
  "excel-to-pdf": () => <ExcelToPdfWorkspace />,
};

export function renderWorkspace(slug: string): ReactElement | null {
  // hasOwn so a slug like "constructor" can never match the object prototype.
  if (!Object.hasOwn(workspaces, slug)) return null;
  const render = workspaces[slug];
  return render ? render() : null;
}
