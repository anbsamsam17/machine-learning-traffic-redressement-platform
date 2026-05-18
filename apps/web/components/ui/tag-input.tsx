"use client";

import { useState, type KeyboardEvent, type ClipboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface TagInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  className?: string;
  type?: "text" | "number";
}

export function TagInput({
  values,
  onChange,
  placeholder = "Ajouter...",
  className,
  type = "text",
}: TagInputProps) {
  const [input, setInput] = useState("");

  /** Parse a raw string into trimmed, non-empty, deduplicated tokens. */
  function parseTokens(raw: string): string[] {
    return raw
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
  }

  /** Add new values, deduplicating against existing ones. */
  function addValues(newTokens: string[]) {
    const unique = newTokens.filter((t) => !values.includes(t));
    // Also deduplicate within the batch itself
    const deduped = [...new Set(unique)];
    if (deduped.length > 0) {
      onChange([...values, ...deduped]);
    }
  }

  /** Commit whatever is currently in the input field. */
  function commitInput() {
    const tokens = parseTokens(input);
    if (tokens.length > 0) {
      addValues(tokens);
    }
    setInput("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // Enter, Tab, or comma triggers commit
    if ((e.key === "Enter" || e.key === "Tab" || e.key === ",") && input.trim()) {
      e.preventDefault();
      commitInput();
      return;
    }
    if (e.key === "Backspace" && !input && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function handleBlur() {
    if (input.trim()) {
      commitInput();
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text");
    // Only intercept if the pasted text contains commas (multi-value paste)
    if (pasted.includes(",")) {
      e.preventDefault();
      const tokens = parseTokens(pasted);
      if (tokens.length > 0) {
        addValues(tokens);
      }
      setInput("");
    }
  }

  function remove(idx: number) {
    onChange(values.filter((_, i) => i !== idx));
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 p-2 rounded-md bg-bg-elevated border border-border min-h-[40px] focus-within:border-border-strong focus-within:ring-2 focus-within:ring-accent",
        className
      )}
    >
      {values.map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 px-2 h-6 rounded bg-accent-subtle text-accent text-xs font-mono font-medium border border-accent/20"
        >
          {v}
          <button
            type="button"
            onClick={() => remove(i)}
            className="hover:text-danger transition-colors"
            aria-label={`Retirer ${v}`}
          >
            <X size={10} aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        type={type}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onPaste={handlePaste}
        placeholder={values.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[80px] bg-transparent text-sm text-text placeholder:text-text-subtle outline-none border-0 focus-visible:ring-0 px-1"
      />
    </div>
  );
}
