import Link from "next/link";
import { ArrowDown, ArrowUpRight } from "lucide-react";
import { tools } from "@/config/tools";

export function Hero() {
  return <section className="studio-hero" aria-labelledby="hero-heading">
    <div className="relative z-10">
      <div className="telemetry-tags"><span><i />Zero cloud retention</span><span>PyMuPDF core</span><span>{tools.length} pro tools</span></div>
      <h1 id="hero-heading">Your document<br /><em>workstation.</em></h1>
      <p className="max-w-md text-base leading-relaxed text-muted sm:text-lg">Compare revisions, redact sensitive text, and convert documents in one local workspace.</p>
      <div className="mt-7 flex flex-wrap gap-3">
        <a className="studio-primary" href="#tools">Explore tools <ArrowDown size={16} /></a>
        <Link className="studio-secondary" href="/tools/compare-pdf">Compare PDFs <ArrowUpRight size={16} /></Link>
      </div>
    </div>
    <div aria-hidden="true" className="document-drawing"><div className="paper-stack">
      <div className="paper-layer paper-back" /><div className="paper-layer paper-mid" />
      <div className="paper-layer paper-front"><div className="paper-spine" /><div className="paper-title" /><div className="paper-lines" /><div className="paper-chart"><i/><i/><i/><i/><i/><i/><i/></div></div>
    </div></div>
  </section>;
}
