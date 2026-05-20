"""Re-parse report.html for every A3_* run and patch metrics.json with the
correct tol_inclus / tol_total / err_p80_pct. The original worker regex did
not match the new CI95 <small> annotations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BATCH = Path(__file__).parent

TOL_RE = re.compile(
    r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)'
)
P80_RE = re.compile(
    r'Err\. rel\. p80</div>\s*<div class="v">\s*([\d.]+)\s*%'
)


def main() -> int:
    updated = 0
    for d in sorted(BATCH.iterdir()):
        if not d.is_dir() or not d.name.startswith("A3_"):
            continue
        report = d / "report.html"
        metrics = d / "metrics.json"
        if not (report.exists() and metrics.exists()):
            continue
        html = report.read_text(encoding="utf-8", errors="ignore")
        m_tol = TOL_RE.search(html)
        m_p80 = P80_RE.search(html)
        if not m_tol:
            continue
        try:
            doc = json.loads(metrics.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        new_tol_in = int(m_tol.group(1))
        new_tol_tot = int(m_tol.group(2))
        new_p80 = float(m_p80.group(1)) if m_p80 else float("nan")
        old_tol_in = doc.get("tol_inclus", 0)
        old_tol_tot = doc.get("tol_total", 0)
        if (
            old_tol_in != new_tol_in
            or old_tol_tot != new_tol_tot
            or doc.get("err_p80_pct") != new_p80
        ):
            doc["tol_inclus"] = new_tol_in
            doc["tol_total"] = new_tol_tot
            doc["err_p80_pct"] = new_p80
            doc["barplot_broken"] = "Aucune donnee disponible" in html
            metrics.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            updated += 1
            print(
                f"{d.name}: tol={new_tol_in}/{new_tol_tot} ({100 * new_tol_in / max(new_tol_tot, 1):.1f}%), p80={new_p80}%"
            )
            # Patch README metrics section in-place.
            readme = d / "README.md"
            if readme.exists():
                text = readme.read_text(encoding="utf-8")
                text = re.sub(
                    r"Capteurs tolérance inclus:.*",
                    f"Capteurs tolérance inclus: **{new_tol_in}/{new_tol_tot}** ({100 * new_tol_in / max(new_tol_tot, 1):.1f}%)",
                    text,
                )
                text = re.sub(
                    r"Erreur relative p80:.*",
                    f"Erreur relative p80: **{new_p80}%**",
                    text,
                )
                readme.write_text(text, encoding="utf-8")
    print(f"updated {updated} metrics.json files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
