"""Smoke test for the A5 orchestrator: validates login/upload/mapping/validate
and a single quick training (5 epochs) before kicking off the full 12-config grid.
"""

from __future__ import annotations

import json
import sys
import time

import requests

API = "http://127.0.0.1:7005"

# Re-use the orchestrator helpers
sys.path.insert(0, r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/.playwright-mcp/Batch_MDL_Phase05")
from run_a5 import (  # noqa: E402
    login, upload, auto_map, validate_mapping, BASELINE, FULL_11, YEAR_MAPPING
)


def main() -> int:
    print("[smoke] login")
    token = login()
    print("[smoke] upload")
    sid = upload(token)
    print(f"[smoke] sid={sid}")
    print("[smoke] auto_map")
    proposed = auto_map(token, sid)
    print(f"[smoke] mapped {len(proposed)} cols, sample: {list(proposed.items())[:5]}")
    print("[smoke] validate")
    vm = validate_mapping(token, sid, proposed)
    print(f"[smoke] rows={vm['rows']} cols_count={len(vm['columns'])}")
    cols = vm["columns"]
    missing = [c for c in FULL_11 if c not in cols]
    print(f"[smoke] FULL_11 missing in learning_df: {missing}")
    if "annee" not in cols:
        print("[smoke] WARN: 'annee' not in learning_df, year_mapped derivation will fail")

    # Try a 5-epoch training to validate the pipeline
    payload = {**BASELINE, "session_id": sid, "min_nb_epochs_list": [3], "max_epochs": 5,
               "output_dir": "SMOKE"}
    print("[smoke] start training (5 epochs)")
    r = requests.post(
        f"{API}/api/training/start", json=payload,
        headers={"Authorization": f"Bearer {token}"}, timeout=60,
    )
    if r.status_code != 200:
        print(f"[smoke] start_training FAILED: {r.status_code} {r.text[:800]}")
        return 1
    print(f"[smoke] start={r.json()}")
    task_id = r.json()["task_id"]
    # Poll
    while True:
        time.sleep(2)
        s = requests.get(
            f"{API}/api/training/status/{task_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        ).json()
        print(f"[smoke] status={s['status']} pct={s.get('progress_pct')} "
              f"model={s.get('current_model_name')} epoch={s.get('current_epoch')}/{s.get('total_epochs')}")
        if s["status"] in ("completed", "failed", "cancelled"):
            if s["status"] != "completed":
                print(f"[smoke] FAILED: {s}")
                return 1
            break
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
