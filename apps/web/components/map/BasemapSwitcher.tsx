"use client";

/**
 * BasemapSwitcher — controle flottant pour basculer entre fonds de carte.
 *
 * Place a l'interieur du wrapper relatif d'une <map>, en absolute top-right
 * (en dessous des contrles MapLibre NavigationControl).
 *
 * Approche technique :
 *   - Pas de map.setStyle(): on appelle setTiles() + setAttribution() sur la
 *     source raster existante (id = "carto"). Les overlays metiers (segments,
 *     capteurs, markers) restent intacts.
 *   - L'attribution est mise a jour via map.style.sourceCaches.carto si
 *     accessible, sinon on patch directement la balise DOM de l'attribution.
 *
 * UX :
 *   - Bouton 40x40 (>= 44x44 cible touch via padding interne du bouton flottant)
 *   - Animation d'ouverture/fermeture GSAP snappy (~0.25s, back.out)
 *   - Persistance dans localStorage via lib/map/basemaps.ts
 *   - Accessibilite : aria-expanded, aria-haspopup, role=menu, keyboard nav (Esc)
 *   - Respect prefers-reduced-motion via gsap.matchMedia()
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import { Layers, Check } from "lucide-react";
import maplibregl from "maplibre-gl";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";

import {
  BASEMAPS,
  BASEMAP_ORDER,
  DEFAULT_BASEMAP,
  readStoredBasemap,
  writeStoredBasemap,
  type BasemapId,
} from "@/lib/map/basemaps";
import { cn } from "@/lib/utils";

interface BasemapSwitcherProps {
  /** Reference vers l'instance MapLibre (partagee par la page). */
  mapRef: MutableRefObject<maplibregl.Map | null>;
  /** Id de la source raster (par defaut "carto", convention du projet). */
  sourceId?: string;
  /** Basemap initial si pas de preference stockee. */
  defaultBasemap?: BasemapId;
  /** Callback notifie a chaque changement (utile pour ajuster overlays). */
  onChange?: (id: BasemapId) => void;
  className?: string;
}

export function BasemapSwitcher({
  mapRef,
  sourceId = "carto",
  defaultBasemap = DEFAULT_BASEMAP,
  onChange,
  className,
}: BasemapSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [currentBasemap, setCurrentBasemap] = useState<BasemapId>(defaultBasemap);
  const [hydrated, setHydrated] = useState(false);

  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // Hydratation : lit la preference localStorage cote client (SSR-safe).
  useEffect(() => {
    const stored = readStoredBasemap();
    setCurrentBasemap(stored);
    setHydrated(true);
  }, []);

  // Applique le basemap en cours sur la map (au montage + a chaque change).
  // On verifie que la source existe deja (sinon retry au prochain rerender).
  useEffect(() => {
    if (!hydrated) return;
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      const src = map.getSource(sourceId);
      if (!src) return false;
      try {
        const def = BASEMAPS[currentBasemap];
        // setTiles change uniquement les URLs sans recreer la source ; les
        // overlays (segments, capteurs, markers) restent intacts.
        (src as maplibregl.RasterTileSource).setTiles(def.tiles);
        // Met a jour l'attribution lue par AttributionControl. setTiles ne le
        // fait pas, donc on patch le champ et on declenche un repaint via la
        // remise des bounds (no-op visuel mais force le refresh de l'UI).
        const srcAny = src as unknown as { attribution?: string };
        srcAny.attribution = def.attribution;
        map.triggerRepaint();
        return true;
      } catch {
        return false;
      }
    };

    if (apply()) return;
    // Si la source n'est pas encore prete (race au montage), on attend
    // l'evenement style.load / sourcedata.
    const onReady = () => {
      if (apply()) {
        map.off("sourcedata", onReady);
        map.off("load", onReady);
      }
    };
    map.on("sourcedata", onReady);
    map.on("load", onReady);
    return () => {
      map.off("sourcedata", onReady);
      map.off("load", onReady);
    };
  }, [currentBasemap, hydrated, mapRef, sourceId]);

  const handleSelect = useCallback(
    (id: BasemapId) => {
      if (id === currentBasemap) {
        setOpen(false);
        return;
      }
      setCurrentBasemap(id);
      writeStoredBasemap(id);
      onChange?.(id);
      setOpen(false);
      buttonRef.current?.focus();
    },
    [currentBasemap, onChange],
  );

  // Animation GSAP : panneau qui apparait depuis le coin top-right (origine
  // alignee sur le bouton). Snappy ~0.22s avec back.out(1.6) pour un leger
  // overshoot. Respect prefers-reduced-motion via matchMedia.
  useGSAP(
    () => {
      const panel = panelRef.current;
      if (!panel) return;

      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: reduce)", () => {
        gsap.set(panel, { autoAlpha: open ? 1 : 0, scale: 1, y: 0 });
      });
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        if (open) {
          gsap.fromTo(
            panel,
            { autoAlpha: 0, scale: 0.88, y: -6 },
            {
              autoAlpha: 1,
              scale: 1,
              y: 0,
              duration: 0.22,
              ease: "back.out(1.6)",
              transformOrigin: "top right",
            },
          );
        } else {
          gsap.to(panel, {
            autoAlpha: 0,
            scale: 0.92,
            y: -4,
            duration: 0.14,
            ease: "power2.in",
            transformOrigin: "top right",
          });
        }
      });

      return () => {
        mm.revert();
      };
    },
    { dependencies: [open], scope: wrapperRef },
  );

  // Fermeture au click outside + Esc
  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const currentDef = BASEMAPS[currentBasemap];

  return (
    <div
      ref={wrapperRef}
      className={cn(
        // Position : top-right, en dessous des controles MapLibre (zoom +
        // boussole occupent ~80px). On laisse 96px pour rester safe.
        "absolute right-3 top-[96px] z-10",
        className,
      )}
    >
      {/* Bouton declencheur */}
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Fond de carte : ${currentDef.label}. Cliquez pour changer.`}
        aria-expanded={open}
        aria-haspopup="menu"
        title={`Fond de carte : ${currentDef.label}`}
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg",
          "bg-[rgba(15,20,36,.92)] border border-[#1f2740] shadow-lg backdrop-blur",
          "text-[#a0b0d8] hover:text-[#22d3ee] hover:border-[#22d3ee]/60",
          "transition-colors duration-200 cursor-pointer",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0d1117]",
          open && "text-[#22d3ee] border-[#22d3ee]/60",
        )}
      >
        <Layers size={18} aria-hidden />
      </button>

      {/* Panneau : 4 vignettes */}
      <div
        ref={panelRef}
        role="menu"
        aria-label="Selection du fond de carte"
        style={{ visibility: "hidden", opacity: 0 }}
        className={cn(
          "absolute right-0 top-12 w-[208px] p-2 rounded-xl",
          "bg-[rgba(15,20,36,.96)] border border-[#1f2740] shadow-2xl backdrop-blur",
        )}
      >
        <div className="px-2 pt-1 pb-2 text-[10px] uppercase tracking-wider text-[#7a8aab] font-semibold">
          Fond de carte
        </div>
        <ul className="space-y-1">
          {BASEMAP_ORDER.map((id) => {
            const def = BASEMAPS[id];
            const isActive = id === currentBasemap;
            return (
              <li key={id}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={isActive}
                  onClick={() => handleSelect(id)}
                  className={cn(
                    "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md",
                    "text-left transition-colors duration-150 cursor-pointer",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]",
                    isActive
                      ? "bg-[rgba(34,211,238,.10)] ring-1 ring-[#22d3ee]"
                      : "hover:bg-[rgba(255,255,255,.04)]",
                  )}
                >
                  {/* Vignette d'apercu */}
                  <span
                    aria-hidden
                    className="shrink-0 h-9 w-9 rounded-md border"
                    style={{
                      background: def.thumb.background,
                      borderColor: def.thumb.border,
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block text-[12px] font-semibold leading-tight",
                        isActive ? "text-[#22d3ee]" : "text-[#e6edf3]",
                      )}
                    >
                      {def.label}
                    </span>
                    <span className="block text-[10px] text-[#7a8aab] leading-tight mt-0.5">
                      {def.description}
                    </span>
                  </span>
                  {isActive && (
                    <Check
                      size={14}
                      className="text-[#22d3ee] shrink-0"
                      aria-hidden
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

export default BasemapSwitcher;
