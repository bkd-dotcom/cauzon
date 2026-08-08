import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Source_Serif_4 } from "next/font/google";

import "./globals.css";

/**
 * Two voices, deliberately.
 *
 * Mono is the display face, not just the code face — URNs, table names and SQL
 * genuinely are monospace in this domain, so the machine's own idiom becomes the
 * page's typography. Serif carries prose evidence, because Cauzon's output is a
 * filed dossier. The split mirrors the agent's architecture: grounding speaks in
 * mono, reasoning speaks in serif.
 */
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-mono",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  variable: "--font-source-serif",
  display: "swap",
});

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const metadata: Metadata = {
  title: "Cauzon — every root cause, proven from the source",
  description:
    "A path-grounded root-cause analysis agent for DataHub. Walks lineage upstream and only names a cause it can prove with a verifiable path.",
  // Every one of these is prefixed. Next rewrites `src`/`href` in JSX under a
  // basePath, but not string paths in the metadata object — so an absolute path
  // here 404s on a basePath deployment, which is how GitHub Pages is configured.
  manifest: `${BASE}/manifest.webmanifest`,
  icons: { icon: `${BASE}/favicon-32.png`, apple: `${BASE}/apple-touch-icon.png` },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Cauzon",
  },
  openGraph: {
    title: "Cauzon — every root cause, proven from the source",
    description:
      "Path-grounded RCA for data incidents. It refuses to blame an asset it cannot connect to the symptom.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#0b1110",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${plexMono.variable} ${sourceSerif.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only px-3 py-2 focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:border focus:border-jade focus:bg-ink focus:text-jade"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
