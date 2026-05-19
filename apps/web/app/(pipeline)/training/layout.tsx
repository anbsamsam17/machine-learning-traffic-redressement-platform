import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Entrainement",
};

export default function TrainingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
