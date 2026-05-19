import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MDL Redressement — Configuration",
};

export default function ConfigLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
