import type { ReactElement } from "react";
import { CompressWorkspace } from "@/components/tools/compress-workspace";
import { PdfToJpgWorkspace } from "@/components/tools/pdf-to-jpg-workspace";

// Tool slug -> function that renders its interactive workspace. A slug that is
// not listed keeps the Coming soon panel. Add one line here when a later phase
// builds a tool. Returning an element (not a component) keeps the page from
// creating components during render.
const workspaces: Readonly<Record<string, () => ReactElement>> = {
  "compress-pdf": () => <CompressWorkspace />,
  "pdf-to-jpg": () => <PdfToJpgWorkspace />,
};

export function renderWorkspace(slug: string): ReactElement | null {
  // hasOwn so a slug like "constructor" can never match the object prototype.
  if (!Object.hasOwn(workspaces, slug)) return null;
  const render = workspaces[slug];
  return render ? render() : null;
}