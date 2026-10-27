import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ComingSoonPanel } from "@/app/tools/coming-soon-panel";
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

  return (
    <div className="mx-auto max-w-3xl px-gutter pb-section pt-28">
      <ComingSoonPanel tool={tool} />
    </div>
  );
}