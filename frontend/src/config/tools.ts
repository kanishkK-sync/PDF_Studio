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
import { MAX_IMAGES, MAX_UPLOAD_MB } from "@/lib/tool-limits";

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
  seoTitle: string;
  seoDescription: string;
  keywords: string[];
  howItWorks: [string, string, string];
  faqs: [ToolFaq, ToolFaq, ToolFaq];
};

export type ToolFaq = { question: string; answer: string };

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
    seoTitle: "Compare PDF Files Free — Visual & Text Diff",
    seoDescription: "Compare two PDFs locally to highlight page images and text changes. Download a difference report with temporary processing and zero long-term retention.",
    keywords: ["compare PDF files", "PDF visual diff", "PDF text comparison", "local PDF comparison", "PDF change report"],
    howItWorks: ["Choose the original and revised PDFs.", "Run the visual and structural comparison.", "Download the report and review highlighted changes."],
    faqs: [
      { question: "Are both compared PDFs retained?", answer: "The local backend uses isolated temporary folders. Both uploads are removed after processing; the report is removed after download or expiry for zero long-term retention." },
      { question: "What are the PDF comparison limits?", answer: `Choose two PDFs totaling at most ${MAX_UPLOAD_MB} MB. The comparison covers up to the first 25 pages; backend settings may impose lower limits.` },
      { question: "How accurate is the PDF difference report?", answer: "The report combines rendered page differences with text changes. Rendering resolution can decrease for large pages, so inspect subtle changes alongside the originals." },
    ],
  },
  {
    slug: "redact-pdf",
    title: "Redact PDF",
    description: "Permanently remove matching page text and scrub metadata.",
    category: "privacy",
    icon: "redact",
    seoTitle: "Redact PDF Free — Remove Text & Scrub Metadata",
    seoDescription: "Remove matching PDF text and scrub metadata with a local redaction engine. Download a sanitized PDF with zero long-term file retention.",
    keywords: ["redact PDF", "remove sensitive PDF text", "scrub PDF metadata", "local PDF redaction", "permanent PDF redaction"],
    howItWorks: ["Choose a PDF with selectable text.", "Enter sensitive phrases or select presets and metadata scrubbing.", "Run redaction, download the PDF, and review it."],
    faqs: [
      { question: "Are sensitive PDFs kept after redaction?", answer: "Redaction runs in the local backend's temporary job folder. Uploads are deleted after processing and sanitized outputs after download or expiry, providing zero long-term retention." },
      { question: "What limits apply to PDF redaction?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB and enter at most 100 phrases within 8,000 characters. The backend defaults to 300 pages and can be configured differently.` },
      { question: "Does redaction remove sensitive text from scans?", answer: "Matching selectable text is permanently removed rather than covered with a visual overlay. Scanned text requires OCR elsewhere; review the output for images and unmatched sensitive content." },
    ],
  },
  {
    slug: "pdf-to-markdown",
    title: "PDF to AI Markdown",
    description: "Extract structured Markdown for notes and language models.",
    category: "extract",
    icon: "markdown",
    seoTitle: "PDF to Markdown Free — Structured Text for AI",
    seoDescription: "Extract PDF headings, text, and tables into Markdown for notes or AI workflows. Process locally and download without long-term file retention.",
    keywords: ["PDF to Markdown", "PDF to AI Markdown", "extract PDF text", "PDF Markdown converter", "local PDF extraction"],
    howItWorks: ["Choose a PDF containing selectable text.", "Extract its content into structured Markdown.", "Preview, copy, or download the Markdown."],
    faqs: [
      { question: "Is my PDF sent to an AI service for Markdown extraction?", answer: "Extraction uses the local backend, without an external AI service. Uploads are deleted after processing and downloadable Markdown after download or expiry for zero long-term retention." },
      { question: "How large can a PDF for Markdown extraction be?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB. The backend defaults to a 300-page limit; deployment settings may change that limit.` },
      { question: "Will Markdown preserve every PDF layout detail?", answer: "Markdown preserves extracted structure rather than exact page appearance. Complex columns and tables may need cleanup, and scanned text is not recognized without OCR." },
    ],
  },
  {
    slug: "compress-pdf",
    title: "Compress PDF",
    description: "Reduce the file size of a PDF.",
    category: "edit",
    icon: "compress",
    seoTitle: "Compress PDF Free — Reduce PDF File Size Locally",
    seoDescription: "Reduce PDF file size with light, balanced, or strong compression. Process in your local engine and download with zero long-term retention.",
    keywords: ["compress PDF", "reduce PDF file size", "local PDF compressor", "free PDF compression", "smaller PDF files"],
    howItWorks: ["Choose the PDF to compress.", "Select light, balanced, or strong compression.", "Review the size savings and download the PDF."],
    faqs: [
      { question: "Does the compressor retain my PDF?", answer: "The local backend deletes the uploaded PDF after processing and the compressed result after download or expiry. Zero retention means no long-term file archive; temporary job files are used." },
      { question: "What is the compression upload limit?", answer: `Choose one nonempty PDF up to ${MAX_UPLOAD_MB} MB. Backend page and resource limits also apply; the default page limit is 300.` },
      { question: "Will PDF compression reduce image quality?", answer: "Stronger compression can reduce image detail. Savings depend on the source; when no smaller valid candidate is available, the original is kept. Review the result before sharing." },
    ],
  },
  {
    slug: "edit-pdf",
    title: "Edit PDF Text",
    description: "Edit and replace text in a PDF.",
    category: "edit",
    icon: "edit",
    seoTitle: "Edit PDF Text Free — Find & Replace Locally",
    seoDescription: "Find and replace selectable PDF text in a local workspace. Download your edited document with temporary processing and zero long-term retention.",
    keywords: ["edit PDF text", "PDF find and replace", "replace text in PDF", "local PDF editor", "free PDF text editor"],
    howItWorks: ["Choose a PDF with selectable text.", "Enter the exact text to find and its replacement.", "Replace the text, download, and inspect the edited areas."],
    faqs: [
      { question: "Are edited PDFs stored permanently?", answer: "The local engine removes uploads after processing and edited files after download or expiry. This zero long-term retention model still uses temporary files during the job." },
      { question: "What are the PDF text editing limits?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB. Find and replacement fields each allow 500 characters; the backend defaults to 300 pages.` },
      { question: "Will replacement text keep the original layout?", answer: "Matching selectable text is replaced within its page area. Long replacements can clip or change spacing. Scanned text cannot be edited, so review each replacement." },
    ],
  },
  {
    slug: "merge-pdf",
    title: "Merge PDF",
    description: "Combine PDFs in the order you choose.",
    category: "edit",
    icon: "merge",
    seoTitle: "Merge PDF Files Free — Combine PDFs in Order",
    seoDescription: "Combine multiple PDFs in your chosen order using a local engine. Download one merged PDF with zero long-term retention of source documents.",
    keywords: ["merge PDF files", "combine PDFs", "local PDF merger", "join PDF documents", "free PDF merge"],
    howItWorks: ["Choose two or more PDFs.", "Arrange the files in the desired order.", "Merge the documents and download one PDF."],
    faqs: [
      { question: "Does merging retain copies of the source PDFs?", answer: "Source PDFs are processed in an isolated local job folder and deleted after processing. The merged PDF is removed after download or expiry for zero long-term retention." },
      { question: "How many PDFs can I merge?", answer: `Choose 2 to 20 PDFs totaling at most ${MAX_UPLOAD_MB} MB. The backend defaults to a 300-page combined limit, which deployment settings can change.` },
      { question: "Does merging lower PDF page quality?", answer: "Pages are combined without rendering them as images, preserving page content. Check document features such as forms, bookmarks, and signatures in the merged output." },
    ],
  },
  {
    slug: "split-pdf",
    title: "Split PDF",
    description: "Extract pages or create separate PDFs.",
    category: "edit",
    icon: "split",
    seoTitle: "Split PDF Free — Extract Pages or Page Ranges",
    seoDescription: "Extract selected PDF pages or split ranges into separate files locally. Download a PDF or ZIP with zero long-term document retention.",
    keywords: ["split PDF", "extract PDF pages", "PDF page ranges", "local PDF splitter", "separate PDF files"],
    howItWorks: ["Choose a PDF and enter pages or ranges.", "Select one extracted PDF or separate PDFs per range.", "Split the document and download the PDF or ZIP."],
    faqs: [
      { question: "Are split PDF pages retained?", answer: "The local backend deletes the source after processing and the output PDF or ZIP after download or expiry. Temporary job storage supports zero long-term retention." },
      { question: "What limits apply when splitting a PDF?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB and select at most 100 ranges. The backend defaults to 300 source and selected output pages, including repeated pages.` },
      { question: "Will extracted PDF pages lose quality?", answer: "Splitting copies selected pages without rasterizing them. Page content keeps its quality, though document-level features such as bookmarks and signatures may change." },
    ],
  },
  {
    slug: "pdf-to-word",
    title: "PDF to Word",
    description: "Convert a PDF into a Word document.",
    category: "convert",
    icon: "word",
    seoTitle: "PDF to Word Free — Convert PDF to DOCX Locally",
    seoDescription: "Convert PDFs into Word DOCX documents with a local engine. Extract editable text where available and download with zero long-term retention.",
    keywords: ["PDF to Word", "PDF to DOCX", "editable PDF conversion", "local PDF Word converter", "free PDF to Word"],
    howItWorks: ["Choose the PDF to convert.", "Run the local Word conversion.", "Download the DOCX and check its layout in Word."],
    faqs: [
      { question: "Are PDF and Word files retained after conversion?", answer: "The local backend deletes the PDF upload after processing and the Word output after download or expiry. Zero long-term retention uses temporary job folders during conversion." },
      { question: "What are the PDF to Word file limits?", answer: `Choose one PDF up to ${MAX_UPLOAD_MB} MB. The backend defaults to 300 pages, subject to deployment configuration and resource limits.` },
      { question: "Will the Word document match the PDF exactly?", answer: "Text-based PDFs work best. Unusual fonts, tables, and complex layouts can shift. Scanned pages remain pictures because this converter does not perform OCR." },
    ],
  },
  {
    slug: "pdf-to-powerpoint",
    title: "PDF to PowerPoint",
    description: "Convert a PDF into a PowerPoint presentation.",
    category: "convert",
    icon: "powerpoint",
    seoTitle: "PDF to PowerPoint Free — Convert PDF to PPTX",
    seoDescription: "Turn PDF pages into PowerPoint slides locally. Choose picture slides or editable objects, then download PPTX with zero long-term retention.",
    keywords: ["PDF to PowerPoint", "PDF to PPTX", "PDF to slides", "editable PowerPoint conversion", "local PDF presentation converter"],
    howItWorks: ["Choose the PDF for your presentation.", "Select picture slides or editable objects.", "Convert, download the PPTX, and review the slides."],
    faqs: [
      { question: "Are presentation conversions kept on a cloud service?", answer: "Conversion runs in the local backend's temporary folder. The PDF is deleted after processing and the PPTX after download or expiry for zero long-term retention." },
      { question: "How large can a PDF to PowerPoint job be?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB. The backend defaults to 300 pages; rendering resource limits may also affect the job.` },
      { question: "Should I use picture or editable slides for best quality?", answer: "Picture mode preserves page appearance at the rendered resolution. Editable mode rebuilds text and images, substitutes fonts, and may omit drawings or shift spacing. Scans remain pictures." },
    ],
  },
  {
    slug: "pdf-to-excel",
    title: "PDF to Excel",
    description: "Convert PDF content into an Excel spreadsheet.",
    category: "extract",
    icon: "excel",
    seoTitle: "PDF to Excel Free — Extract Tables to XLSX",
    seoDescription: "Extract PDF tables into Excel sheets with a local converter. Download XLSX or a text fallback with zero long-term document retention.",
    keywords: ["PDF to Excel", "PDF tables to XLSX", "extract PDF tables", "local PDF spreadsheet converter", "free PDF to Excel"],
    howItWorks: ["Choose a PDF containing text or tables.", "Extract detected tables into spreadsheet sheets.", "Download the XLSX and verify its rows and columns."],
    faqs: [
      { question: "Are extracted spreadsheet data retained?", answer: "The local backend deletes the source PDF after processing and the Excel output after download or expiry. Temporary job folders provide zero long-term retention." },
      { question: "What limits apply to PDF to Excel conversion?", answer: `Choose one PDF up to ${MAX_UPLOAD_MB} MB. The backend defaults to a 300-page limit, configurable by the deployment.` },
      { question: "How accurately are PDF tables converted to Excel?", answer: "Detected tables become separate sheets. If none are found, extracted text goes into one sheet. Check cell alignment and values; scanned PDFs need OCR elsewhere." },
    ],
  },
  {
    slug: "pdf-to-jpg",
    title: "PDF to JPG",
    description: "Convert PDF pages into JPG images.",
    category: "convert",
    icon: "image",
    seoTitle: "PDF to JPG Free — Convert PDF Pages to Images",
    seoDescription: "Render PDF pages as JPG images locally with selectable quality. Download a JPG or ZIP with zero long-term retention of your documents.",
    keywords: ["PDF to JPG", "PDF pages to images", "local PDF image converter", "PDF to JPEG", "high quality PDF JPG"],
    howItWorks: ["Choose a PDF to render as images.", "Select low, medium, or high image quality.", "Convert and download the JPG or multi-page ZIP."],
    faqs: [
      { question: "Are generated JPG images retained?", answer: "The local engine removes the PDF upload after processing and the JPG or ZIP output after download or expiry. Zero long-term retention still involves temporary job files." },
      { question: "What are the PDF to JPG limits?", answer: `Upload one PDF up to ${MAX_UPLOAD_MB} MB. The backend defaults to 300 pages and applies pixel limits when rendering large pages.` },
      { question: "What image quality do the JPG presets produce?", answer: "Low targets 100 DPI, medium 150 DPI, and high 220 DPI with increasing JPEG quality. Large pages may render at lower resolution to stay within the pixel budget; JPEG is lossy." },
    ],
  },
  {
    slug: "word-to-pdf",
    title: "Word to PDF",
    description: "Convert a Word document into a PDF.",
    category: "convert",
    icon: "word",
    seoTitle: "Word to PDF Free — Convert DOCX Locally",
    seoDescription: "Convert Word DOCX documents into PDFs with a local engine. Render basic text, tables, and pictures with zero long-term file retention.",
    keywords: ["Word to PDF", "DOCX to PDF", "local Word PDF converter", "free Word conversion", "document to PDF"],
    howItWorks: ["Choose a Word DOCX document.", "Run the local PDF conversion.", "Download the PDF and review its pages."],
    faqs: [
      { question: "Is my Word document retained after creating a PDF?", answer: "The local backend deletes the DOCX after processing and the PDF after download or expiry. Temporary job storage enables zero long-term retention." },
      { question: "Which Word files and sizes are supported?", answer: `Upload one .docx file up to ${MAX_UPLOAD_MB} MB. Legacy .doc files are not accepted. The backend defaults to a 300-page output limit.` },
      { question: "Will the PDF preserve all Word formatting?", answer: "Basic text, tables, and pictures are rendered, with searchable text where possible. Advanced layouts and unsupported features may change or be omitted; inspect the PDF before sharing." },
    ],
  },
  {
    slug: "powerpoint-to-pdf",
    title: "PowerPoint to PDF",
    description: "Convert a PowerPoint presentation into a PDF.",
    category: "convert",
    icon: "powerpoint",
    seoTitle: "PowerPoint to PDF Free — Convert PPTX Locally",
    seoDescription: "Convert PowerPoint PPTX presentations into PDF documents locally. Render basic slide content and download with zero long-term retention.",
    keywords: ["PowerPoint to PDF", "PPTX to PDF", "slides to PDF", "local presentation converter", "free PowerPoint PDF converter"],
    howItWorks: ["Choose a PowerPoint PPTX presentation.", "Convert the presentation with the local engine.", "Download the PDF and check slide content and layout."],
    faqs: [
      { question: "Is my PowerPoint presentation stored after conversion?", answer: "The PPTX is processed locally and deleted after processing. The PDF is deleted after download or expiry, supporting zero long-term retention with temporary job storage." },
      { question: "Which PowerPoint files can I convert?", answer: `Choose one .pptx file up to ${MAX_UPLOAD_MB} MB. Legacy .ppt files are not accepted. The backend defaults to a 300-page limit.` },
      { question: "Does the PDF preserve animations and every slide feature?", answer: "PDF output is static. Basic text, tables, and pictures are rendered; animations, charts, and advanced layouts may change or be omitted. Review the output slide by slide." },
    ],
  },
  {
    slug: "excel-to-pdf",
    title: "Excel to PDF",
    description: "Convert an Excel spreadsheet into a PDF.",
    category: "convert",
    icon: "excel",
    seoTitle: "Excel to PDF Free — Convert XLSX Locally",
    seoDescription: "Convert Excel XLSX spreadsheets into PDF documents with a local engine. Review rendered sheets and download with zero long-term retention.",
    keywords: ["Excel to PDF", "XLSX to PDF", "spreadsheet to PDF", "local Excel PDF converter", "free spreadsheet conversion"],
    howItWorks: ["Choose an Excel XLSX workbook.", "Convert the workbook into PDF pages locally.", "Download and check sheet pagination and cell content."],
    faqs: [
      { question: "Are workbook contents retained after conversion?", answer: "The local backend deletes the XLSX upload after processing and the PDF after download or expiry. Temporary job folders support zero long-term retention." },
      { question: "Which Excel files and sizes are supported?", answer: `Upload one .xlsx workbook up to ${MAX_UPLOAD_MB} MB. Legacy .xls files are not accepted. The backend defaults to a 300-page output limit.` },
      { question: "Will formulas and charts look exactly like Excel?", answer: "Basic spreadsheet content is rendered into static PDF pages. Formulas, charts, and advanced formatting may change or be omitted; verify values, column widths, and pagination." },
    ],
  },
  {
    slug: "jpg-to-pdf",
    title: "JPG to PDF",
    description: "Convert JPG images into a PDF.",
    category: "convert",
    icon: "image",
    seoTitle: "JPG to PDF Free — Combine Images into a PDF",
    seoDescription: "Arrange JPG images and create a PDF with a local engine. Choose page settings and download with zero long-term retention of your images.",
    keywords: ["JPG to PDF", "JPEG to PDF", "combine images into PDF", "local image PDF converter", "free JPG PDF converter"],
    howItWorks: ["Choose images and arrange them in order.", "Choose pages fitted to each image or A4 pages.", "Create and download the combined PDF."],
    faqs: [
      { question: "Are my images kept after creating a PDF?", answer: "Images are processed in a local temporary job folder and deleted after processing. The PDF is removed after download or expiry for zero long-term retention." },
      { question: "How many images can I convert to PDF?", answer: `Choose up to ${MAX_IMAGES} images totaling at most ${MAX_UPLOAD_MB} MB. Backend image-count and pixel limits remain authoritative and may differ by deployment.` },
      { question: "Will converting JPG images to PDF improve their quality?", answer: "The PDF uses the source images; it cannot restore missing detail. Page size, margins, and orientation affect placement. Use clear originals and inspect the PDF at the intended viewing size." },
    ],
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
