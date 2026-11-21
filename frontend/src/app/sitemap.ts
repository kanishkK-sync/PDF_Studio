import type { MetadataRoute } from "next";

const TOOL_SLUGS = [
  "compress-pdf",
  "pdf-to-jpg",
  "jpg-to-pdf",
  "pdf-to-word",
  "pdf-to-excel",
  "pdf-to-pptx",
  "merge-pdf",
  "split-pdf",
  "word-to-pdf",
  "excel-to-pdf",
  "ppt-to-pdf",
  "edit-pdf",
  "redact-pdf",
  "pdf-to-markdown",
  "compare-pdf",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");
  const lastModified = "2026-11-21";

  return [
    { url: `${siteUrl}/`, lastModified, changeFrequency: "weekly", priority: 1 },
    ...TOOL_SLUGS.map((slug) => ({
      url: `${siteUrl}/tools/${slug}`,
      lastModified,
      changeFrequency: "weekly" as const,
      priority: 0.85,
    })),
  ];
}