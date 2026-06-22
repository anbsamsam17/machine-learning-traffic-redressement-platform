"""
build_index.py - Concatenate the HTML template + inline GeoJSON
into the final standalone index.html.

Reads:
  - _template.html
  - 2025_light.min.geojson  (output of prepare_data.py)

Writes:
  - index.html
"""

from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).parent
TPL = HERE / "_template.html"
DATA = HERE / "2025_light.min.geojson"
OUT = HERE / "index.html"
PLACEHOLDER = "__GEOJSON_PLACEHOLDER__"


def main() -> None:
    t0 = time.perf_counter()
    if not TPL.exists():
        raise SystemExit(f"Template not found: {TPL}")
    if not DATA.exists():
        raise SystemExit(
            f"GeoJSON not found: {DATA} - run prepare_data.py first."
        )

    print(f"[build] reading template ({TPL.stat().st_size / 1024:.1f} KB)")
    tpl = TPL.read_text(encoding="utf-8")
    if PLACEHOLDER not in tpl:
        raise SystemExit(f"Placeholder {PLACEHOLDER} missing from template.")

    print(f"[build] reading data ({DATA.stat().st_size / 1e6:.2f} MB)")
    data = DATA.read_text(encoding="utf-8")
    # Validate that the data is well-formed JSON before injecting.
    parsed = json.loads(data)
    n_feats = len(parsed["features"])
    print(f"[build] data has {n_feats:,} features")

    # Inject. The placeholder is a bare token after `const GEOJSON = ` and is
    # safe to replace by raw JSON (JSON is valid JS-object literal here).
    html = tpl.replace(PLACEHOLDER, data)

    print(f"[build] writing {OUT.name}")
    OUT.write_text(html, encoding="utf-8")

    size_mb = OUT.stat().st_size / 1e6
    print("-" * 60)
    print(f"[build] index.html : {size_mb:6.2f} MB")
    print(f"[build] features   : {n_feats:,}")
    print(f"[build] done in {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
