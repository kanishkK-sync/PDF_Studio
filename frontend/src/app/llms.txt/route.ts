export function GET(): Response {
  const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");
  const body = `# pdf-studio
> Privacy-first, zero-retention PDF workstation powered by PyMuPDF. Files are processed in isolated ephemeral jobs and purged automatically.

## Tools
- Compress PDF: ${siteUrl}/tools/compress-pdf
- PDF to JPG: ${siteUrl}/tools/pdf-to-jpg
- JPG to PDF: ${siteUrl}/tools/jpg-to-pdf
- PDF to Word: ${siteUrl}/tools/pdf-to-word
- PDF to Excel: ${siteUrl}/tools/pdf-to-excel
- PDF to PowerPoint: ${siteUrl}/tools/pdf-to-pptx
- Merge PDF: ${siteUrl}/tools/merge-pdf
- Split PDF: ${siteUrl}/tools/split-pdf
- Word to PDF: ${siteUrl}/tools/word-to-pdf
- Excel to PDF: ${siteUrl}/tools/excel-to-pdf
- PowerPoint to PDF: ${siteUrl}/tools/ppt-to-pdf
- Edit PDF Text: ${siteUrl}/tools/edit-pdf
- Redact & Scrub PDF: ${siteUrl}/tools/redact-pdf
- PDF to AI Markdown: ${siteUrl}/tools/pdf-to-markdown
- Visual & Structural PDF Diff: ${siteUrl}/tools/compare-pdf
`;

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}