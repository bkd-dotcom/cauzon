import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cauzon — DataHub RCA",
  description: "Path-grounded root-cause analysis for data incidents on DataHub.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/favicon-32.png",
    apple: "/apple-touch-icon.png",
  },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Cauzon" },
};

export const viewport: Viewport = {
  themeColor: "#0b1020",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1, // app-like on mobile
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <script
          dangerouslySetInnerHTML={{
            __html: `if ('serviceWorker' in navigator) {
              window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(()=>{}));
            }`,
          }}
        />
      </body>
    </html>
  );
}
