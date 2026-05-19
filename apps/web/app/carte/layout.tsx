import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Carte de debits",
};

export default function CarteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
