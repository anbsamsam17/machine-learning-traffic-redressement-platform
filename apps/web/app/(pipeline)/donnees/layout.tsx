import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Donnees",
};

export default function DonneesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
