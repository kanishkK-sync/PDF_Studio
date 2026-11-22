import { ImageResponse } from "next/og";

export const alt = "pdf-studio — 15 privacy-first PDF tools with zero cloud retention";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          width: "100%",
          height: "100%",
          padding: "56px 64px",
          background: "#09090B",
          color: "#FAFAFA",
          fontFamily: "sans-serif",
          border: "1px solid #27272A",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <svg width="72" height="72" viewBox="0 0 64 64">
            <rect width="64" height="64" rx="14" fill="#18181B" />
            <path d="M20 13h16l10 10v25a3 3 0 0 1-3 3H21a3 3 0 0 1-3-3V16a3 3 0 0 1 2-3Z" fill="#18181B" stroke="#FAFAFA" strokeWidth="2.5" strokeLinejoin="round" />
            <path d="M36 13v10h10" fill="none" stroke="#FAFAFA" strokeWidth="2.5" strokeLinejoin="round" />
            <path d="M25 33h14" stroke="#38BDF8" strokeWidth="3" strokeLinecap="round" />
            <path d="M25 41h9" stroke="#71717A" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
          <div style={{ display: "flex", alignItems: "center", gap: 12, color: "#A1A1AA", fontSize: 18, letterSpacing: 2 }}>
            <div style={{ width: 8, height: 8, borderRadius: 4, background: "#38BDF8" }} />
            PRIVACY-FIRST PDF WORKSTATION
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 108, fontWeight: 700, letterSpacing: -6, lineHeight: 1.1 }}>pdf-studio</div>
          <div style={{ marginTop: 24, width: 80, height: 4, background: "#38BDF8" }} />
          <div style={{ marginTop: 24, maxWidth: 980, fontSize: 30, lineHeight: 1.45, color: "#A1A1AA" }}>
            Compare revisions, redact sensitive text, export AI Markdown, and convert documents locally.
          </div>
        </div>
        <div style={{ paddingTop: 24, borderTop: "1px solid #27272A", fontSize: 20, letterSpacing: 2, color: "#38BDF8" }}>
          ZERO CLOUD RETENTION · PYMUPDF CORE · 15 TOOLS
        </div>
      </div>
    ),
    size,
  );
}
