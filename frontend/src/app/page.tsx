import { FileCheck2, Layers3, Shredder, ShieldCheck, HardDrive, Cpu } from "lucide-react";
import { Hero } from "@/components/home/hero";
import { ToolGrid } from "@/components/home/tool-grid";
import { ScrollReveal } from "@/components/ui/scroll-reveal";

const pipeline = [
  { icon: FileCheck2, title: "Client Guardrails", text: "File type, size, and empty-file checks run before upload." },
  { icon: Layers3, title: "Isolated Ephemeral Worker", text: "The local engine processes each job in its own temporary folder." },
  { icon: Shredder, title: "Auto-Purged Output", text: "The engine clears results after download or expiry." },
];

export default function HomePage() {
  return <div className="studio-shell">
    <Hero />
    <section id="tools" tabIndex={-1} aria-labelledby="tools-heading" className="scroll-mt-24">
      <h2 id="tools-heading" className="studio-heading">Tool directory</h2>
      <ToolGrid />
    </section>
    <ScrollReveal><section aria-labelledby="pipeline-heading" className="pipeline">
      <h2 id="pipeline-heading" className="studio-heading">3-stage zero-trace execution pipeline</h2>
      <ol className="pipeline-grid">{pipeline.map(({ icon: Icon, title, text }, i) => <li key={title}>
        <Icon size={20} aria-hidden="true"/><h3><span>0{i + 1}.</span> {title}</h3><p>{text}</p>
      </li>)}</ol>
      <div className="trust-strip"><span><HardDrive/> Local processing</span><span><ShieldCheck/> No cloud retention</span><span><Cpu/> In-memory tool handoffs</span></div>
    </section></ScrollReveal>
  </div>;
}
