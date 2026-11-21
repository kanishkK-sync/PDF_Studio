// Keep crawl endpoints and structured data on the same origin as metadataBase.
export function siteUrl(path: string): string {
  return new URL(
    path,
    process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000",
  ).toString();
}
