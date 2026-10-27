import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Fraunces, Geist } from "next/font/google";
import { AmbientBackground } from "@/components/layout/ambient-background";
import { FilmGrain } from "@/components/layout/film-grain";
import { Footer } from "@/components/layout/footer";
import { Navbar } from "@/components/layout/navbar";
import { SkipLink } from "@/components/layout/skip-link";
import { SmoothScrollProvider } from "@/components/providers/smooth-scroll-provider";
import { ThemeProvider } from "@/components/providers/theme-provider";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-fraunces",
});

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
  description: "Beautiful local PDF tools",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${fraunces.variable} ${geist.variable} flex min-h-dvh flex-col bg-background text-foreground antialiased`}
      >
        <SkipLink />
        <FilmGrain />
        <ThemeProvider>
          <SmoothScrollProvider>
            <AmbientBackground />
            <Navbar />
            <main
              id="main-content"
              tabIndex={-1}
              className="flex-1 focus-visible:outline-none"
            >
              {children}
            </main>
            <Footer />
          </SmoothScrollProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}