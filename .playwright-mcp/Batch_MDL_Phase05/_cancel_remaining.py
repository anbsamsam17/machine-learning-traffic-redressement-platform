"""Cancel every new training task the running run_a5.py orchestrator starts,
so it exits its main loop quickly without burning CPU on configs whose
artifacts will be discarded anyway.

Runs until the orchestrator process exits (detected via log file going
stale + no python run_a5 process).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import requests

API = "http://127.0.0.1:7005"
EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"
LOG = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05/run_a5.log"
)
TASK_RE = re.compile(r"task_id=([a-f0-9]+)")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def login() -> str:
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def orchestrator_alive() -> bool:
    # Check via tasklist for python.exe running run_a5.py
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where",
             "name='python.exe' and CommandLine like '%run_a5.py%'",
             "get", "ProcessId"],
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="ignore")
        return any(line.strip().isdigit() for line in out.splitlines())
    except Exception:
        return False


def main() -> int:
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    _log("logged in, watching log for new task_ids")
    seen: set[str] = set()
    stale_count = 0
    last_size = 0
    while True:
        if not LOG.exists():
            time.sleep(2)
            continue
        text = LOG.read_text(encoding="utf-8", errors="ignore")
        size = len(text)
        if size == last_size:
            stale_count += 1
        else:
            stale_count = 0
            last_size = size
        for m in TASK_RE.finditer(text):
            tid = m.group(1)
            if tid in seen:
                continue
            seen.add(tid)
            try:
                r = requests.post(
                    f"{API}/api/training/cancel/{tid}",
                    headers=headers,
                    timeout=10,
                )
                _log(f"cancel {tid} -> HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                _log(f"cancel {tid} failed: {exc}")
        # Exit when log has been stable for ~30s AND orchestrator is gone
        if stale_count >= 15 and not orchestrator_alive():
            _log(f"orchestrator gone (stale={stale_count}). Exit.")
            break
        # Also exit if log shows All configs done
        if "All configs done" in text:
            _log("orchestrator finished naturally")
            break
        time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
