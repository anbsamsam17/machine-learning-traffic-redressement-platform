"use client";

/** Tabs animees : underline GSAP qui glisse fluidement entre les onglets actifs. */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { gsap } from "gsap";
import { cn } from "@/lib/utils";

export interface TabItem {
  /** Identifiant stable de l'onglet (utilise comme key). */
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  /** Optionnel : contenu rendu sous les tabs si `panels` n'est pas pris en main par le parent. */
  content?: ReactNode;
  disabled?: boolean;
}

export interface TabGroupProps {
  items: TabItem[];
  /** Mode controle (valeur active depuis le parent). */
  value?: string;
  /** Valeur active par defaut en mode non-controle. Defaut = premier item actif. */
  defaultValue?: string;
  onChange?: (id: string) => void;
  /** Couleur de l'underline. Defaut "accent". */
  tone?: "accent" | "amber" | "cyan" | "violet";
  /** Affiche les contenus `item.content` sous la barre. Defaut true. */
  renderPanels?: boolean;
  className?: string;
  tabsClassName?: string;
  panelClassName?: string;
}

const TONE_BAR: Record<NonNullable<TabGroupProps["tone"]>, string> = {
  accent: "bg-accent",
  amber: "bg-[#f59e0b]",
  cyan: "bg-[#22d3ee]",
  violet: "bg-[#a78bfa]",
};

export function TabGroup({
  items,
  value,
  defaultValue,
  onChange,
  tone = "accent",
  renderPanels = true,
  className,
  tabsClassName,
  panelClassName,
}: TabGroupProps) {
  const isControlled = value !== undefined;
  const firstEnabled = items.find((i) => !i.disabled)?.id ?? items[0]?.id ?? "";
  const [internal, setInternal] = useState<string>(defaultValue ?? firstEnabled);
  const active = isControlled ? (value as string) : internal;
  const groupId = useId();

  const listRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLSpanElement>(null);
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const moveBar = useCallback(
    (id: string, animate: boolean) => {
      const list = listRef.current;
      const bar = barRef.current;
      const target = tabRefs.current.get(id);
      if (!list || !bar || !target) return;
      const listRect = list.getBoundingClientRect();
      const tRect = target.getBoundingClientRect();
      const left = tRect.left - listRect.left;
      const width = tRect.width;
      const mm = window.matchMedia("(prefers-reduced-motion: reduce)");
      if (!animate || mm.matches) {
        gsap.set(bar, { x: left, width });
        return;
      }
      gsap.to(bar, {
        x: left,
        width,
        duration: 0.35,
        ease: "power3.out",
      });
    },
    []
  );

  // Position initiale + re-layout au resize
  useEffect(() => {
    moveBar(active, false);
    const onResize = () => moveBar(active, false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [active, moveBar]);

  const select = useCallback(
    (id: string) => {
      const item = items.find((i) => i.id === id);
      if (!item || item.disabled) return;
      if (!isControlled) setInternal(id);
      onChange?.(id);
      moveBar(id, true);
    },
    [items, isControlled, onChange, moveBar]
  );

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((i) => !i.disabled);
    if (enabled.length === 0) return;
    const idx = enabled.findIndex((i) => i.id === active);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      select(enabled[(idx + 1) % enabled.length].id);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      select(enabled[(idx - 1 + enabled.length) % enabled.length].id);
    } else if (e.key === "Home") {
      e.preventDefault();
      select(enabled[0].id);
    } else if (e.key === "End") {
      e.preventDefault();
      select(enabled[enabled.length - 1].id);
    }
  };

  return (
    <div className={cn("w-full", className)}>
      <div
        ref={listRef}
        role="tablist"
        onKeyDown={onKey}
        className={cn(
          "relative inline-flex items-center gap-1 border-b border-border",
          tabsClassName
        )}
      >
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              ref={(node) => {
                if (node) tabRefs.current.set(item.id, node);
                else tabRefs.current.delete(item.id);
              }}
              role="tab"
              type="button"
              id={`${groupId}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${groupId}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              disabled={item.disabled}
              onClick={() => select(item.id)}
              className={cn(
                "inline-flex items-center gap-2 px-3 py-2 text-sm font-medium",
                "transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-t",
                selected ? "text-text" : "text-text-muted hover:text-text",
                item.disabled && "opacity-40 cursor-not-allowed"
              )}
            >
              {item.icon && <span className="[&_svg]:size-4">{item.icon}</span>}
              {item.label}
            </button>
          );
        })}
        <span
          ref={barRef}
          aria-hidden
          className={cn(
            "pointer-events-none absolute bottom-0 left-0 h-[2px] rounded-full",
            TONE_BAR[tone]
          )}
          style={{ transform: "translateX(0)", width: 0 }}
        />
      </div>

      {renderPanels && (
        <div className={cn("mt-4", panelClassName)}>
          {items.map((item) => (
            <div
              key={item.id}
              role="tabpanel"
              id={`${groupId}-panel-${item.id}`}
              aria-labelledby={`${groupId}-tab-${item.id}`}
              hidden={item.id !== active}
            >
              {item.id === active && item.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
