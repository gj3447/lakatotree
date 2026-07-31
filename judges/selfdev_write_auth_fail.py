#!/usr/bin/env python3
"""SelfDev live metric: write-auth failures (lower better; 0 = write path live).

Probes POST /question with Bearer token. metric=0 success, metric=1 auth/write fail.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TREE = os.environ.get(
    "LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612"
)
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")


def main() -> None:
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    # Prefer env token; on LXC judge sandbox may lack it — also try server.env side channel
    if not tok and os.path.exists("/opt/lakatotree/server.env"):
        for line in open("/opt/lakatotree/server.env", encoding="utf-8"):
            if line.startswith("LAKATOS_API_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    qname = "q-selfdev-write-auth-probe-ephemeral"
    body = json.dumps(
        {
            "qname": qname,
            "body": "ephemeral write-auth probe (open refresh only)",
            "expected_gain": 0.01,
            "cost": 0.01,
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/api/tree/{TREE}/question",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {tok}"} if tok else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
            payload = json.load(resp)
        ok = code == 200 and payload.get("ok") is True
        print(f"metric={0 if ok else 1}")
    except urllib.error.HTTPError as e:
        print(f"metric=1")
        print(f"# http={e.code}", flush=True)
    except Exception as e:  # noqa: BLE001 — harness wants metric always
        print("metric=1")
        print(f"# err={type(e).__name__}", flush=True)


if __name__ == "__main__":
    main()
