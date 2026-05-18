// FALLBACK Sam notify/mood — to remove after agent N merges @/lib/sam/notify
// and @/lib/sam/store. The contract here MUST match those modules exactly so
// pipeline pages can switch the import path without other changes.
//
// Once agent N has merged, swap each page's import:
//   from "@/lib/sam-fallback"  →  "@/lib/sam/notify" / "@/lib/sam/store"
// (or just re-export from those modules here for a single-flip swap.)

import { toast } from "sonner";

export type SamMood =
  | "welcome"
  | "based"
  | "thinking"
  | "analysing"
  | "info"
  | "goodjob"
  | "error";

interface NotifyOptions {
  title?: string;
  autoCloseMs?: number;
  id?: string | number;
}

interface PromiseMessages {
  loading: string;
  success: string;
  error: string;
}

export const samNotify = {
  success: (m: string, opts?: NotifyOptions) =>
    toast.success(opts?.title ? `${opts.title}: ${m}` : m, { id: opts?.id, duration: opts?.autoCloseMs }),
  error: (m: string, opts?: NotifyOptions) =>
    toast.error(opts?.title ? `${opts.title}: ${m}` : m, { id: opts?.id, duration: opts?.autoCloseMs }),
  analysing: (m: string, opts?: NotifyOptions) =>
    toast.loading(m, { id: opts?.id, duration: opts?.autoCloseMs }),
  thinking: (m: string, opts?: NotifyOptions) =>
    toast.loading(m, { id: opts?.id, duration: opts?.autoCloseMs }),
  info: (m: string, opts?: NotifyOptions) =>
    toast(m, { id: opts?.id, duration: opts?.autoCloseMs }),
  welcome: (m: string, opts?: NotifyOptions) =>
    toast.success(m, { id: opts?.id, duration: opts?.autoCloseMs }),
  dismiss: (id?: string | number) => toast.dismiss(id),
  promise: <T>(p: Promise<T>, msgs: PromiseMessages) =>
    toast.promise(p, msgs),
};

export const samMood = {
  set: (_mood: SamMood, _label?: string, _autoResetMs?: number): void => {
    /* no-op in fallback; widget mounted in app/layout.tsx will pick up real impl */
  },
  reset: (): void => {
    /* no-op */
  },
};
