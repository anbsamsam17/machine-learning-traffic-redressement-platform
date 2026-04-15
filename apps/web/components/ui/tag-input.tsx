"use client";

import { useState, type KeyboardEvent } from "react";
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

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      if (!values.includes(input.trim())) {
        onChange([...values, input.trim()]);
      }
      setInput("");
    }
    if (e.key === "Backspace" && !input && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function remove(idx: number) {
    onChange(values.filter((_, i) => i !== idx));
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 p-2 glass-light rounded-lg min-h-[42px]",
        className
      )}
    >
      {values.map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-accent/15 text-accent text-xs font-medium border border-accent/20"
        >
          {v}
          <button
            type="button"
            onClick={() => remove(i)}
            className="hover:text-red-400 transition-colors"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        type={type}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={values.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[80px] bg-transparent text-sm text-foreground placeholder:text-muted outline-none"
      />
    </div>
  );
}
