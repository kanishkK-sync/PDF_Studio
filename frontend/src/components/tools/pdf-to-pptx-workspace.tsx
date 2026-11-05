"use client";

import { Presentation } from "lucide-react";
import { useState } from "react";
import {
  OptionGroup,
  type ChoiceOption,
} from "@/components/tools/option-group";
import {
  PdfConvertWorkspace,
  type PdfConvertSummary,
} from "@/components/tools/pdf-convert-workspace";
import {
  convertPdfToPptx,
  type PdfToPptxResult,
  type PptxMode,
} from "@/lib/api";
import { formatBytes } from "@/lib/format";

const FIDELITY_NOTE =
  "Pictures mode looks exactly like the PDF but nothing on it can be edited. Editable mode rebuilds text and images as PowerPoint objects, but fonts, drawings and spacing can change. Scanned pages stay pictures in both modes.";

const MODE_OPTIONS: readonly ChoiceOption<PptxMode>[] = [
  {
    id: "pictures",
    title: "Pictures",
    description:
      "Looks exactly like the PDF. Each page is one image on its slide, so the text cannot be edited.",
    badge: "Recommended",
  },
  {
    id: "editable",
    title: "Editable",
    description:
      "Text and images become real PowerPoint objects you can edit. Fonts become Arial, drawings are dropped and the layout can shift.",
  },
];

const MODE_LABELS: Record<PptxMode, string> = {
  pictures: "Pictures",
  editable: "Editable",
};

function describe(result: PdfToPptxResult): PdfConvertSummary {
  const pictures = result.mode === "pictures";

  return {
    title: "Your PowerPoint presentation is ready",
    description: pictures
      ? `It will download as ${result.download_name}. Each page is one image on its slide, so it looks like the PDF but the text cannot be edited.`
      : `It will download as ${result.download_name}. Text and images are real PowerPoint objects you can edit. Fonts are replaced with Arial, drawings are dropped and the layout can shift, so check each slide.`,
    downloadLabel: "Download PowerPoint file",
    announcement: `Done. Your PDF with ${result.slide_count} ${result.slide_count === 1 ? "page" : "pages"} became a ${MODE_LABELS[result.mode].toLowerCase()} PowerPoint file of ${formatBytes(result.result_size)}.`,
    rows: [
      { label: "Slides", value: String(result.slide_count) },
      { label: "Style", value: MODE_LABELS[result.mode] },
      { label: "PDF", value: formatBytes(result.original_size) },
      { label: "PowerPoint file", value: formatBytes(result.result_size) },
    ],
  };
}

export function PdfToPptxWorkspace() {
  const [mode, setMode] = useState<PptxMode>("pictures");

  return (
    <PdfConvertWorkspace<PdfToPptxResult>
      actionLabel="Convert to PowerPoint"
      actionIcon={<Presentation aria-hidden="true" className="size-4" />}
      busyLabel="Converting to PowerPoint"
      busyAnnouncement="Converting your PDF to PowerPoint."
      fidelityNote={FIDELITY_NOTE}
      options={(busy) => (
        <OptionGroup
          label="Slide style"
          options={MODE_OPTIONS}
          value={mode}
          onChange={setMode}
          disabled={busy}
          columns={2}
        />
      )}
      run={(file, callbacks) => convertPdfToPptx(file, mode, callbacks)}
      describe={describe}
      resetLabel="Convert another"
    />
  );
}