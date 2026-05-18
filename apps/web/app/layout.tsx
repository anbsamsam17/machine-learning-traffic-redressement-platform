import type { Metadata } from "next";
import { Inter, Geist } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import "./globals.css";
import { cn } from "@/lib/utils";
import { AppHeader } from "@/components/layout/app-header";
import { SamWidget } from "@/components/avatar/SamWidget";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "MDL Redressement Tool",
  description:
    "Pipeline de modelisation de redressement FCD : donnees, entrainement, evaluation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className={cn("dark", inter.variable, "font-sans", geist.variable)} suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground font-sans antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          <AppHeader />
          <main className="flex-1">{children}</main>
          <Toaster
            theme="dark"
            position="bottom-right"
            duration={4000}
            gap={12}
            // Sam persistent widget lives at bottom-6 right-6 (≈96px wide +
            // 24px margin). We push the sonner stack above the widget so
            // toasts and Sam don't overlap.
            offset={{ bottom: 144, right: 24 }}
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
        </ThemeProvider>
      </body>
    </html>
  );
}
