import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import { Providers } from "./providers";
import { AppHeader } from "@/components/layout/app-header";
import { SamWidget } from "@/components/avatar/SamWidget";
import { SamPageBinder } from "@/components/avatar/SamPageBinder";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: {
    default: "MDL Redressement Tool",
    template: "%s",
  },
  description:
    "Pipeline de modelisation de redressement FCD : donnees, entrainement, evaluation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="fr"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-bg text-text font-sans antialiased">
        <Providers>
          <AppHeader />
          <SamPageBinder />
          <main id="main-content" className="flex-1">{children}</main>
          {/* Toasts are status messages — make sure SR users hear them */}
          <Toaster
            position="bottom-right"
            duration={4000}
            gap={12}
            // SamWidget lives at fixed bottom-6 right-6 (128px + 24 margin).
            // Push toast stack above the widget so they don't overlap.
            offset={{ bottom: 176, right: 24 }}
            theme="dark"
            closeButton
            richColors={false}
            aria-live="polite"
            toastOptions={{
              style: {
                background: "rgba(15, 20, 40, 0.95)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                color: "#f8fafc",
                backdropFilter: "blur(16px)",
              },
            }}
          />
          <SamWidget />
        </Providers>
      </body>
    </html>
  );
}
