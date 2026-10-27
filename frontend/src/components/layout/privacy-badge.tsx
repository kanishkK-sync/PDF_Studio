import { ShieldCheck } from "lucide-react";

export function PrivacyBadge() {
  return (
    <p className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted">
      <ShieldCheck aria-hidden="true" className="size-4 shrink-0 text-accent-violet" />
      <span>100% local processing. Files never leave your device.</span>
    </p>
  );
}