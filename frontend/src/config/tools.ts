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
} from "lucide-react";

export type ToolCategory = "optimize" | "edit" | "from-pdf" | "to-pdf";

export type ToolIcon =
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
  { id: "optimize", label: "Optimize" },
  { id: "edit", label: "Edit" },
  { id: "from-pdf", label: "Convert from PDF" },
  { id: "to-pdf", label: "Convert to PDF" },
];

export const tools: readonly Tool[] = [
  {
    slug: "redact-pdf",
    title: "Redact PDF",
    description: "Permanently remove matching page text and scrub metadata.",
    category: "edit",
    icon: "redact",
  },
  {
    slug: "pdf-to-markdown",
    title: "PDF to AI Markdown",
    description: "Extract structured Markdown for notes and language models.",
    category: "from-pdf",
    icon: "markdown",
  },
  {
    slug: "compress-pdf",
    title: "Compress PDF",
    description: "Reduce the file size of a PDF.",
    category: "optimize",
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
    category: "from-pdf",
    icon: "word",
  },
  {
    slug: "pdf-to-powerpoint",
    title: "PDF to PowerPoint",
    description: "Convert a PDF into a PowerPoint presentation.",
    category: "from-pdf",
    icon: "powerpoint",
  },
  {
    slug: "pdf-to-excel",
    title: "PDF to Excel",
    description: "Convert PDF content into an Excel spreadsheet.",
    category: "from-pdf",
    icon: "excel",
  },
  {
    slug: "pdf-to-jpg",
    title: "PDF to JPG",
    description: "Convert PDF pages into JPG images.",
    category: "from-pdf",
    icon: "image",
  },
  {
    slug: "word-to-pdf",
    title: "Word to PDF",
    description: "Convert a Word document into a PDF.",
    category: "to-pdf",
    icon: "word",
  },
  {
    slug: "powerpoint-to-pdf",
    title: "PowerPoint to PDF",
    description: "Convert a PowerPoint presentation into a PDF.",
    category: "to-pdf",
    icon: "powerpoint",
  },
  {
    slug: "excel-to-pdf",
    title: "Excel to PDF",
    description: "Convert an Excel spreadsheet into a PDF.",
    category: "to-pdf",
    icon: "excel",
  },
  {
    slug: "jpg-to-pdf",
    title: "JPG to PDF",
    description: "Convert JPG images into a PDF.",
    category: "to-pdf",
    icon: "image",
  },
];

// Icon components live here, keyed by ToolIcon. Tool entries carry only the
// string key, because component functions can't cross from server components
// to client components. Client components look the icon up: toolIcons[tool.icon].
export const toolIcons = {
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
