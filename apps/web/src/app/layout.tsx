import type { Metadata } from "next";
import { Sora, Nunito } from "next/font/google";
import "./globals.css";

const display = Sora({ subsets: ["latin"], variable: "--font-display", weight: ["600", "700", "800"] });
const body = Nunito({ subsets: ["latin"], variable: "--font-body", weight: ["400", "600", "700", "800", "900"] });

export const metadata: Metadata = {
  title: "Prism — Agentic GTM Studio",
  description: "One topic in. A whole spectrum of publish-ready content out — researched, written, designed and fact-checked by a team of AI agents, live.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${body.variable}`}>{children}</body>
    </html>
  );
}
