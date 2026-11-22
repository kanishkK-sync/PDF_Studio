import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist } from "next/font/google";
import { Footer } from "@/components/layout/footer";
import { Navbar } from "@/components/layout/navbar";
import { SkipLink } from "@/components/layout/skip-link";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { CommandPalette } from "@/components/layout/command-palette";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-sans",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://pdf-studio-bice.vercel.app"),
  title: {
    default: "pdf-studio — Privacy-First PDF Workstation",
    template: "%s | pdf-studio",
  },
  description: "Convert, edit, compare, and protect documents with 15 free PDF tools. Local processing and temporary job storage provide zero long-term file retention.",
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "pdf-studio",
    title: "pdf-studio — Privacy-First PDF Workstation",
    description: "15 free PDF tools for local conversion, editing, comparison, and redaction with zero long-term file retention.",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "pdf-studio — Privacy-First PDF Workstation" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "pdf-studio — Privacy-First PDF Workstation",
    description: "15 free PDF tools for local conversion, editing, comparison, and redaction with zero long-term file retention.",
    images: ["/opengraph-image"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <body
        className={`${geist.variable} flex min-h-dvh flex-col bg-background text-foreground antialiased`}
      >
        <SkipLink />
        <ThemeProvider>
          <CommandPalette />
          <Navbar />
          <main
            id="main-content"
            tabIndex={-1}
            className="flex-1 focus-visible:outline-none"
          >
            {children}
          </main>
          <Footer />
        </ThemeProvider>
      </body>
    </html>
  );
}
