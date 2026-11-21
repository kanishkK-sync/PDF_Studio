import { comparisonLimits } from "@/lib/tool-limits";

type PageStatus = "added" | "removed" | "modified" | "unchanged";

export type PageDiff = {
  page: number;
  status: PageStatus;
  similarity_percent: number;
  has_visual_changes: boolean;
  added_lines: string[];
  removed_lines: string[];
  image: string;
};

type DiffReport = {
  original_pages: number;
  revised_pages: number;
  total_pages: number;
  compared_pages: number;
  pages_changed: number;
  truncated: boolean;
  overall_similarity: number;
  pages: PageDiff[];
};

export type Comparison = {
  archive: Blob;
  name: string;
  report: DiffReport;
  images: Map<string, Blob>;
};

const limit = comparisonLimits["compare-pdf"].maxPages;

function valid(condition: unknown): asserts condition {
  if (!condition) throw new Error("Invalid comparison archive");
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(line => typeof line === "string");
}

function percent(value: unknown): value is number {
  return typeof value === "number" && value >= 0 && value <= 100;
}

function positiveCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function checkReport(value: unknown): asserts value is DiffReport {
  valid(record(value) && Array.isArray(value.pages) && positiveCount(value.original_pages)
    && positiveCount(value.revised_pages) && positiveCount(value.compared_pages)
    && value.total_pages === Math.max(value.original_pages, value.revised_pages)
    && value.compared_pages <= Math.min(limit, value.total_pages)
    && value.truncated === (value.compared_pages < value.total_pages)
    && value.pages.length === value.compared_pages && percent(value.overall_similarity));
  for (const [index, page] of value.pages.entries()) {
    valid(record(page) && page.page === index + 1 && percent(page.similarity_percent)
      && typeof page.has_visual_changes === "boolean"
      && ["added", "removed", "unchanged", "modified"].includes(String(page.status))
      && strings(page.added_lines) && strings(page.removed_lines)
      && page.image === `page-${String(index + 1).padStart(3, "0")}-diff.png`);
  }
  valid(value.pages_changed === value.pages.filter(p => p.status !== "unchanged").length);
}

// The local API writes a seekable, single-disk ZIP_STORED archive with no
// ZIP comment or data descriptors. Slice the original blob so PNG payloads
// stay out of the JS heap and only the active page needs an object URL.
export async function readComparison(archive: Blob, name: string): Promise<Comparison> {
  valid(archive.size >= 22);
  const end = new DataView(await archive.slice(-22).arrayBuffer());
  valid(end.getUint32(0, true) === 0x06054b50 && end.getUint16(20, true) === 0);
  const count = end.getUint16(10, true);
  const directory = end.getUint32(16, true);
  valid(count >= 3 && count <= limit + 2
    && directory + end.getUint32(12, true) === archive.size - 22);

  let offset = 0;
  const entries = new Map<string, Blob>();
  for (let i = 0; i < count; i++) {
    valid(offset + 30 <= directory);
    const header = new DataView(await archive.slice(offset, offset + 30).arrayBuffer());
    valid(header.getUint32(0, true) === 0x04034b50 && header.getUint16(6, true) === 0
      && header.getUint16(8, true) === 0);
    const size = header.getUint32(18, true);
    const nameLength = header.getUint16(26, true);
    const start = offset + 30 + nameLength + header.getUint16(28, true);
    valid(size === header.getUint32(22, true) && start + size <= directory);
    const filename = await archive.slice(offset + 30, offset + 30 + nameLength).text();
    valid(!entries.has(filename));
    entries.set(filename, archive.slice(start, start + size, filename.endsWith(".png") ? "image/png" : ""));
    offset = start + size;
  }
  valid(offset === directory && entries.has("diff-summary.txt"));
  const json = entries.get("diff-report.json");
  valid(json);
  const report: unknown = JSON.parse(await json.text());
  checkReport(report);
  valid(count === report.pages.length + 2);
  for (const page of report.pages) {
    const image = entries.get(page.image);
    valid(image && image.size >= 8);
    const png = new DataView(await image.slice(0, 8).arrayBuffer());
    valid(png.getUint32(0) === 0x89504e47 && png.getUint32(4) === 0x0d0a1a0a);
  }
  return { archive, name, report, images: entries };
}
