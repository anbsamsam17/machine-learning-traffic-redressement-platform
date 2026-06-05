import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Carte d'evolution des debits",
};

export default function EvolutionLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
