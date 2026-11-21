import {
  FileImage,
  FileSpreadsheet,
  FileText,
  Minimize2,
  PenLine,
  Combine,
  Scissors,
  Presentation,
  ShieldCheck,
  FileCode,
  GitCompareArrows,
} from "lucide-react";

export type ToolCategory = "privacy" | "extract" | "convert" | "edit";

export type ToolIcon =
  | "compare"
  | "redact"
  | "markdown"
  | "compress"
  | "edit"
  | "merge"
  | "split"
  | "word"
  | "powerpoint"
  | "excel"
  | "image";

export type Tool = {
  slug: string;
  title: string;
  description: string;
  category: ToolCategory;
  icon: ToolIcon;
};

// Display order. The "All" tab is added by the UI.
export const categories: readonly { id: ToolCategory; label: string }[] = [
  { id: "privacy", label: "Privacy & Diff" },
  { id: "extract", label: "AI & Extraction" },
  { id: "convert", label: "Convert" },
  { id: "edit", label: "Optimize & Edit" },
];

export const tools: readonly Tool[] = [
  {
    slug: "compare-pdf",
    title: "Visual & Structural PDF Diff",
    description: "Compare two PDFs page by page, highlighting visual and text changes.",
    category: "privacy",
    icon: "compare",
  },
  {
    slug: "redact-pdf",
    title: "Redact PDF",
    description: "Permanently remove matching page text and scrub metadata.",
    category: "privacy",
    icon: "redact",
  },
  {
    slug: "pdf-to-markdown",
    title: "PDF to AI Markdown",
    description: "Extract structured Markdown for notes and language models.",
    category: "extract",
    icon: "markdown",
  },
  {
    slug: "compress-pdf",
    title: "Compress PDF",
    description: "Reduce the file size of a PDF.",
    category: "edit",
    icon: "compress",
  },
  {
    slug: "edit-pdf",
    title: "Edit PDF Text",
    description: "Edit and replace text in a PDF.",
    category: "edit",
    icon: "edit",
  },
  {
    slug: "merge-pdf",
    title: "Merge PDF",
    description: "Combine PDFs in the order you choose.",
    category: "edit",
    icon: "merge",
  },
  {
    slug: "split-pdf",
    title: "Split PDF",
    description: "Extract pages or create separate PDFs.",
    category: "edit",
    icon: "split",
  },
  {
    slug: "pdf-to-word",
    title: "PDF to Word",
    description: "Convert a PDF into a Word document.",
    category: "convert",
    icon: "word",
  },
  {
    slug: "pdf-to-powerpoint",
    title: "PDF to PowerPoint",
    description: "Convert a PDF into a PowerPoint presentation.",
    category: "convert",
    icon: "powerpoint",
  },
  {
    slug: "pdf-to-excel",
    title: "PDF to Excel",
    description: "Convert PDF content into an Excel spreadsheet.",
    category: "extract",
    icon: "excel",
  },
  {
    slug: "pdf-to-jpg",
    title: "PDF to JPG",
    description: "Convert PDF pages into JPG images.",
    category: "convert",
    icon: "image",
  },
  {
    slug: "word-to-pdf",
    title: "Word to PDF",
    description: "Convert a Word document into a PDF.",
    category: "convert",
    icon: "word",
  },
  {
    slug: "powerpoint-to-pdf",
    title: "PowerPoint to PDF",
    description: "Convert a PowerPoint presentation into a PDF.",
    category: "convert",
    icon: "powerpoint",
  },
  {
    slug: "excel-to-pdf",
    title: "Excel to PDF",
    description: "Convert an Excel spreadsheet into a PDF.",
    category: "convert",
    icon: "excel",
  },
  {
    slug: "jpg-to-pdf",
    title: "JPG to PDF",
    description: "Convert JPG images into a PDF.",
    category: "convert",
    icon: "image",
  },
];

// Icon components live here, keyed by ToolIcon. Tool entries carry only the
// string key, because component functions can't cross from server components
// to client components. Client components look the icon up: toolIcons[tool.icon].
export const toolIcons = {
  compare: GitCompareArrows,
  redact: ShieldCheck,
  markdown: FileCode,
  compress: Minimize2,
  edit: PenLine,
  merge: Combine,
  split: Scissors,
  word: FileText,
  powerpoint: Presentation,
  excel: FileSpreadsheet,
  image: FileImage,
} satisfies Record<ToolIcon, unknown>;

export function getToolBySlug(slug: string): Tool | undefined {
  return tools.find((tool) => tool.slug === slug);
}
