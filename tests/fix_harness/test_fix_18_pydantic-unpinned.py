"""FIX-HARNESS #18 (P3 honesty/reproducibility): server imports pydantic as a
first-class API but requirements.txt does not pin it — the next 'requirements
incomplete' instance (mirrors #14's starlette case).

finding id: #18
locations:
  - requirements.txt            -> NO `pydantic==` line (only fastapi==0.137.2,
                                   which constrains pydantic>=2.9.0 with NO upper bound)
  - server/app.py:31                       from pydantic import TypeAdapter
  - server/api_schemas.py:10               from pydantic import BaseModel, Field
  - server/contexts/lineage/schemas.py:8   from pydantic import BaseModel, Field
  - server/contexts/tree/schemas.py:9      from pydantic import BaseModel, ConfigDict, Field

the bug:
  Four server modules import pydantic directly (BaseModel/ConfigDict/Field/
  TypeAdapter) as a first-class API. requirements.txt is documented (lines 1-4)
  as version-pinned "for reproducibility" — "receipts, not claims" applied to
  the build. Yet pydantic appears nowhere in requirements.txt. fastapi==0.137.2
  only pulls pydantic>=2.9.0 transitively with NO upper bound, so a clean CI
  resolve could install a future pydantic 3.x with breaking changes (ConfigDict /
  TypeAdapter / extra-handling semantics), silently breaking the verified-green
  build with no edit to this repo. starlette gets a pin (line 8, "server schemas
  import it directly") precisely for this reason; pydantic — imported the same
  first-class way — does not.

the exact fix (requirements.txt):
  add `pydantic==2.13.4` (the installed/verified version) with a note mirroring
  starlette's, e.g.:
    pydantic==2.13.4      # server schemas import it directly (BaseModel/ConfigDict/TypeAdapter)

post-fix contract: requirements.txt MUST pin pydantic with `==`. Today no such
line exists (bug). xfail(strict) until fixed.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_REQS = _ROOT / "requirements.txt"

# Server modules that import pydantic as a first-class API. The pin must exist
# *because* these direct imports do — assert they really do so the oracle is
# non-vacuous (a future refactor dropping pydantic would legitimately retire it).
_PYDANTIC_IMPORTERS = (
    "server/app.py",
    "server/api_schemas.py",
    "server/contexts/lineage/schemas.py",
    "server/contexts/tree/schemas.py",
)

_PIN_RE = re.compile(r"(?mi)^\s*pydantic\s*==", re.MULTILINE)
_IMPORT_RE = re.compile(r"(?m)^\s*(?:from\s+pydantic\b|import\s+pydantic\b)")


# mechanism / positive oracle: the four server modules DO import pydantic directly
# (proves the dependency is first-class → a pin is warranted). Expected GREEN today.
def test_server_modules_import_pydantic_directly():
    for rel in _PYDANTIC_IMPORTERS:
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert _IMPORT_RE.search(src), f"{rel} no longer imports pydantic directly"


# defect axis / negative oracle: pydantic is a direct dependency, so requirements.txt
# must pin it with `==` (post-fix contract). RED today — no such line exists.
# [FIXED 2026-06-27] #18 — green regression (requirements.txt pins pydantic==2.13.4)
def test_requirements_pins_pydantic_exactly():
    text = _REQS.read_text(encoding="utf-8")
    # Pre-condition: at least one server module imports pydantic directly (non-vacuous).
    assert any(
        _IMPORT_RE.search((_ROOT / rel).read_text(encoding="utf-8"))
        for rel in _PYDANTIC_IMPORTERS
    ), "no server module imports pydantic — pin would be vacuous"
    # Correct (post-fix) behavior: a `pydantic==<ver>` line must exist, exactly as
    # starlette is pinned because "server schemas import it directly".
    assert _PIN_RE.search(text), (
        "requirements.txt must pin pydantic with '==' (it is imported directly by "
        "server/app.py, api_schemas.py, contexts/{lineage,tree}/schemas.py); "
        "fastapi only constrains pydantic>=2.9.0 with no upper bound"
    )
