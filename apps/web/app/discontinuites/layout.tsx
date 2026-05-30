import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Analyse discontinuites TVr",
};

export default function DiscontinuitesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
