/**
 * React JSX attribute augmentation for browser-native but non-standard
 * file-system input attributes used by our folder upload UI.
 */
import "react";

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface InputHTMLAttributes<T> {
    webkitdirectory?: string;
    directory?: string;
  }
}

export {};
