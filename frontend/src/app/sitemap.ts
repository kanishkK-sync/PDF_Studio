import type { MetadataRoute } from "next";
import { tools } from "@/config/tools";
import { siteUrl } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["/", ...tools.map((tool) => `/tools/${tool.slug}`)].map((path) => ({
    url: siteUrl(path),
    lastModified: "2026-11-21",
  }));
}
