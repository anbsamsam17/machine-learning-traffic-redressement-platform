import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Boucles de comptage",
};

export default function CompteursLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
