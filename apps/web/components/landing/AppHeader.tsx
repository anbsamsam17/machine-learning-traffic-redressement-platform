"use client";

/**
 * Landing-specific header wrapper.
 *
 * The global `<AppHeader />` (from `components/layout/app-header.tsx`) is already
 * rendered in `app/layout.tsx`, so this file exists primarily as a placeholder
 * for the future `<Logo />` component the login agent ships and any landing-only
 * header treatments (eyebrow, breadcrumb, etc.). For now it re-exports the
 * global header so the import path requested by the spec resolves.
 */
export { AppHeader } from "@/components/layout/app-header";
