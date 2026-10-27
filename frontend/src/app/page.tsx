import { Hero } from "@/components/home/hero";
import { ToolGrid } from "@/components/home/tool-grid";

export default function HomePage() {
  return (
    <div className="pt-20">
      <Hero />
      <section
        id="tools"
        tabIndex={-1}
        aria-labelledby="tools-heading"
        className="mx-auto max-w-6xl scroll-mt-24 px-gutter focus-visible:outline-none"
      >
        <h2
          id="tools-heading"
          className="mb-8 text-center font-display text-3xl tracking-tight sm:text-4xl"
        >
          All tools
        </h2>
        <ToolGrid />
      </section>
    </div>
  );
}