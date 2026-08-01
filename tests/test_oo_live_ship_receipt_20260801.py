"""OO live ship receipt judge — sealed path only (no network)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

j = _load("selfdev_oo_live_ship", "judges/selfdev_oo_live_ship.py")
n = _load("selfdev_oo_live_ship_novel", "judges/selfdev_oo_live_ship_novel.py")

def test_live_receipt_metric_zero():
    assert j.measure() == 0

def test_live_receipt_novel_one():
    assert n.measure() == 1

def test_receipt_shape():
    p = ROOT / "raw" / "selfdev_oo_live_ship_20260801.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["verify_ok"] is True
    assert d["metric"] == 0
    assert d["mode"] == "LIVE_READBACK_WARN_NONPROD"
    assert d["outcomes"] >= 3
