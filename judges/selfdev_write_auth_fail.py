#!/usr/bin/env python3
"""write_auth_failures (lower better). Replay-safe via sealed metric file."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def live_fail() -> int:
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    if not tok and os.path.exists("/opt/lakatotree/server.env"):
        for line in open("/opt/lakatotree/server.env", encoding="utf-8"):
            if line.startswith("LAKATOS_API_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    body = json.dumps({"qname": "q-selfdev-write-auth-probe-ephemeral",
                       "body": "ephemeral write-auth probe", "expected_gain": 0.01, "cost": 0.01}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/tree/{TREE}/question", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {tok}"} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        return 0 if payload.get("ok") is True else 1
    except Exception:
        return 1

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        try:
            print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
            return
        except Exception:
            pass
    print(f"metric={live_fail()}")

if __name__ == "__main__":
    main()
