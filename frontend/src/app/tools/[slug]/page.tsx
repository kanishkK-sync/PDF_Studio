import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ComingSoonPanel } from "@/app/tools/coming-soon-panel";
import { ToolHeader } from "@/components/tools/tool-header";
import { renderWorkspace } from "@/components/tools/workspaces";
import { getToolBySlug, tools } from "@/config/tools";

type ToolPageProps = {
  params: Promise<{ slug: string }>;
};

export function generateStaticParams() {
  return tools.map((tool) => ({ slug: tool.slug }));
}

export async function generateMetadata({
  params,
}: ToolPageProps): Promise<Metadata> {
  const { slug } = await params;
  const tool = getToolBySlug(slug);

  if (!tool) {
    return { title: "Tool not found" };
  }

  return { title: tool.title, description: tool.description };
}

export default async function ToolPage({ params }: ToolPageProps) {
  const { slug } = await params;
  const tool = getToolBySlug(slug);

  if (!tool) {
    notFound();
  }

  const workspace = renderWorkspace(slug);

  return (
    <div className="mx-auto max-w-3xl px-gutter pb-section pt-28">
      {workspace ? (
        <>
          <ToolHeader tool={tool} />
          <div className="mt-10">{workspace}</div>
        </>
      ) : (
        <ComingSoonPanel tool={tool} />
      )}
    </div>
  );
}