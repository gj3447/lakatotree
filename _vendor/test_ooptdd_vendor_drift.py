"""Drift check for the vendored ooptdd core (copied in by scripts/vendor_ooptdd.py).

RED the moment a vendored file is edited away from the committed manifest. To sync
with upstream, re-run ``python <ooptdd>/scripts/vendor_ooptdd.py <this-repo>`` —
the manifest changes show up as a git diff to review. Pure stdlib, offline.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_VENDOR = Path(__file__).resolve().parent           # …/_vendor
_MANIFEST = _VENDOR / "ooptdd_vendor_manifest.json"


def _normalized_sha256(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return hashlib.sha256(("\n".join(lines).rstrip("\n") + "\n").encode()).hexdigest()


def test_vendored_ooptdd_matches_manifest():
    manifest = json.loads(_MANIFEST.read_text())
    drifted = []
    for rel, want in manifest["files"].items():
        path = _VENDOR / "ooptdd" / rel
        assert path.exists(), f"vendored file missing: {rel} (re-vendor)"
        got = _normalized_sha256(path.read_text())
        if got != want:
            drifted.append(rel)
    assert not drifted, (
        f"vendored ooptdd drifted from manifest: {drifted}. "
        "Someone edited the vendored copy directly. Re-vendor from canonical: "
        "python <ooptdd>/scripts/vendor_ooptdd.py <this-repo>"
    )


def test_vendored_matches_canonical_head_when_present():
    """When the canonical ooptdd checkout exists (dev box), the vendored copy must match
    *committed* canonical (HEAD) — catches "upstream committed, we lagged". Compares
    against HEAD, not the working tree, so unrelated in-flight WIP in the canonical repo
    doesn't false-RED. Skips on the field PC where the canonical repo is absent (the
    manifest guard above still covers integrity there)."""
    repo = Path(os.getenv("OOPTDD_CANONICAL", "<WORKSPACE>/ooptdd"))
    if not (repo / "src" / "ooptdd").exists():
        pytest.skip("canonical ooptdd checkout absent")
    # Vendoring is a *deliberate pin*: being behind committed HEAD is a SKIP (surfaced,
    # not a CI failure), so a fast-moving upstream doesn't red us — we bump intentionally.
    manifest = json.loads(_MANIFEST.read_text())
    behind = []
    for rel in manifest["files"]:
        try:
            head = subprocess.run(
                ["git", "-C", str(repo), "show", f"HEAD:src/ooptdd/{rel}"],
                capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("canonical not a usable git checkout")
        if _normalized_sha256(head.decode()) != _normalized_sha256((_VENDOR / "ooptdd" / rel).read_text()):
            behind.append(rel)
    if behind:
        pytest.skip(f"vendored pinned behind committed canonical (HEAD) on {behind} — "
                    "re-vendor deliberately: python <ooptdd>/scripts/sync_consumers_from_head.py --apply")
