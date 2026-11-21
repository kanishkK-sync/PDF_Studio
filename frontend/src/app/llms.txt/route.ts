import { tools } from "@/config/tools";
import { siteUrl } from "@/lib/site";

export function GET() {
  const content = [
    "# pdf-studio",
    "",
    "> A privacy-first PDF workstation with 15 free document tools.",
    "",
    "## Privacy & Local Architecture",
    "",
    "Files are sent to the configured pdf-studio backend, running locally by default. Each job uses an isolated temporary folder. Zero retention means zero long-term storage: uploads are removed after processing; outputs are removed after download or expiry. The default expiry period is 30 minutes and is configurable. A remote backend processes files on its server; use a backend you control to keep processing local.",
    "",
    "## Tools",
    "",
    ...tools.map((tool) => `- [${tool.title}](${siteUrl(`/tools/${tool.slug}`)}): ${tool.seoDescription}`),
    "",
  ].join("\n");

  return new Response(content, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
