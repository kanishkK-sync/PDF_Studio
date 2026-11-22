import type { MetadataRoute } from "next";
import { tools } from "@/config/tools";
import { siteUrl } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = "2026-11-21";

  return [
    { url: siteUrl("/"), lastModified, changeFrequency: "weekly", priority: 1 },
    ...tools.map(({ slug }) => ({
      url: siteUrl(`/tools/${slug}`),
      lastModified,
      changeFrequency: "weekly" as const,
      priority: 0.85,
    })),
  ];
}
