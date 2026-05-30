import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Visualisation Carte + Capteurs",
};

export default function VisualisationLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
