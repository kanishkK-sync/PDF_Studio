import { PrivacyBadge } from "@/components/layout/privacy-badge";

export function Footer() {
  return (
    <footer className="mt-section border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-gutter py-10 sm:flex-row">
        <p className="text-sm text-muted">
          &copy; {new Date().getFullYear()} pdf-studio. A local-first PDF toolkit.
        </p>
        <PrivacyBadge />
      </div>
    </footer>
  );
}