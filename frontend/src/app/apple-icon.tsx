import { ImageResponse } from "next/og";

export const alt = "pdf-studio document icon";
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "100%",
          height: "100%",
          background: "#09090B",
        }}
      >
        <svg width="148" height="148" viewBox="0 0 64 64">
          <path d="M20 13h16l10 10v25a3 3 0 0 1-3 3H21a3 3 0 0 1-3-3V16a3 3 0 0 1 2-3Z" fill="#18181B" stroke="#FAFAFA" strokeWidth="2.5" strokeLinejoin="round" />
          <path d="M36 13v10h10" fill="none" stroke="#FAFAFA" strokeWidth="2.5" strokeLinejoin="round" />
          <path d="M25 33h14" stroke="#38BDF8" strokeWidth="3" strokeLinecap="round" />
          <path d="M25 41h9" stroke="#71717A" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
      </div>
    ),
    size,
  );
}
