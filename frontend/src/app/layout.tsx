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
  title: {
    default: "pdf-studio",
    template: "%s · pdf-studio",
  },
  description: "A local document workstation for PDF conversion, editing, and comparison.",
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
