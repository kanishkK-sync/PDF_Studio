import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ComingSoonPanel } from "@/app/tools/coming-soon-panel";
import { ToolHeader } from "@/components/tools/tool-header";
import { renderWorkspace } from "@/components/tools/workspaces";
import { getToolBySlug, tools } from "@/config/tools";
import { siteUrl } from "@/lib/site";

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
    notFound();
  }

  return {
    title: tool.seoTitle,
    description: tool.seoDescription,
    keywords: tool.keywords,
    alternates: { canonical: `/tools/${slug}` },
    openGraph: {
      type: "website",
      locale: "en_US",
      siteName: "pdf-studio",
      title: tool.seoTitle,
      description: tool.seoDescription,
      url: `/tools/${slug}`,
      images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "pdf-studio — Privacy-First PDF Workstation" }],
    },
    twitter: {
      card: "summary_large_image",
      title: tool.seoTitle,
      description: tool.seoDescription,
      images: ["/opengraph-image"],
    },
  };
}

export default async function ToolPage({ params }: ToolPageProps) {
  const { slug } = await params;
  const tool = getToolBySlug(slug);

  if (!tool) {
    notFound();
  }

  const workspace = renderWorkspace(slug);
  const url = siteUrl(`/tools/${slug}`);
  const application = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "@id": `${url}#application`,
    name: tool.title,
    description: tool.seoDescription,
    url,
    applicationCategory: "UtilitiesApplication",
    operatingSystem: "Any OS with a modern web browser",
    isAccessibleForFree: true,
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  };
  const faqPage = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "@id": `${url}#faq`,
    mainEntity: tool.faqs.map(({ question, answer }) => ({
      "@type": "Question",
      name: question,
      acceptedAnswer: { "@type": "Answer", text: answer },
    })),
  };

  return (
    <div className="mx-auto max-w-3xl px-gutter pb-section pt-28">
      {[application, faqPage].map((schema) => (
        <script
          key={schema["@type"]}
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            // Escape HTML delimiters so content cannot terminate the script.
            __html: JSON.stringify(schema).replace(/</g, "\\u003c"),
          }}
        />
      ))}
      {workspace ? (
        <>
          <ToolHeader tool={tool} />
          <div className="mt-10">{workspace}</div>
        </>
      ) : (
        <ComingSoonPanel tool={tool} />
      )}
      <div className="mt-16 space-y-12">
        <section aria-labelledby="how-it-works-heading" className="border-t border-border pt-8">
          <h2 id="how-it-works-heading" className="text-xl font-semibold tracking-tight">How It Works</h2>
          <ol className="mt-6 grid gap-6 sm:grid-cols-3">
            {tool.howItWorks.map((step, index) => (
              <li key={step} className="border-l border-border pl-4">
                <span aria-hidden="true" className="font-mono text-xs text-accent-violet">0{index + 1}</span>
                <p className="mt-2 text-sm leading-relaxed text-muted">{step}</p>
              </li>
            ))}
          </ol>
        </section>
        <section aria-labelledby="privacy-heading" className="border-t border-border pt-8">
          <h2 id="privacy-heading" className="text-xl font-semibold tracking-tight">Zero-Trace Processing</h2>
          <div className="mt-4 space-y-3 text-sm leading-relaxed text-muted">
            <p>pdf-studio sends files to your configured backend, which runs on your machine by default. Each job uses an isolated temporary folder in the local engine.</p>
            <p>Zero retention means zero long-term file storage: uploads are removed after processing, and results are removed after download or expiry. Temporary files exist while the job runs. The expiry period defaults to 30 minutes and is configurable by the backend operator.</p>
            <p>If you connect to a remote backend, files are processed on that server. Use a backend you control to keep document processing local.</p>
          </div>
        </section>
        <section aria-labelledby="faq-heading" className="border-t border-border pt-8">
          <h2 id="faq-heading" className="text-xl font-semibold tracking-tight">Frequently Asked Questions</h2>
          <dl className="mt-6 divide-y divide-border">
            {tool.faqs.map(({ question, answer }) => (
              <div key={question} className="py-5 first:pt-0 last:pb-0">
                <dt className="text-sm font-medium text-foreground">{question}</dt>
                <dd className="mt-2 text-sm leading-relaxed text-muted">{answer}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
