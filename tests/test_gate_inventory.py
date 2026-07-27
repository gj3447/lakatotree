"""Gate inventory drift guard — LAKATOS_* env 플래그 전수가 docs/GATE_DEFAULT_INVENTORY 문서에
등재됐는지 매 커밋 검사. "built-then-disarmed" 재발은 대부분 *새 플래그가 조용히 추가*될 때
일어나므로, 인벤토리가 코드를 따라오지 못하면 RED.

env 플래그 판정: .py 안의 모든 `LAKATOS_[A-Z_]+` 토큰 − 모듈 상수 allowlist.
(상수 경유 간접 read — 예: _FLOOR_ENV = 'LAKATOS_ENGINE_RULE_FLOOR' — 도 토큰 자체는 잡힌다.)
# KG: span_lakatotree_engine
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "GATE_DEFAULT_INVENTORY_2026-07-24.md"
SCAN_DIRS = ("server", "lakatos", "judges", "c1verify", "scripts", "tests", "examples")

# env 가 아니라 모듈 상수인 토큰 (문서 §D 참고 기록과 동기화)
NON_ENV_CONSTANTS = {"LAKATOS_PRODUCER", "LAKATOS_LOCATIONS"}


def _env_flags() -> set[str]:
    flags: set[str] = set()
    for d in SCAN_DIRS:
        for f in (ROOT / d).rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            flags.update(re.findall(r"LAKATOS_[A-Z_]+", f.read_text(encoding="utf-8")))
    for f in (ROOT / "scripts").rglob("*.sh"):
        flags.update(re.findall(r"LAKATOS_[A-Z_]+", f.read_text(encoding="utf-8")))
    return flags - NON_ENV_CONSTANTS


def test_gate_inventory_covers_all_env_flags():
    doc = DOC.read_text(encoding="utf-8")
    assert DOC.exists(), "게이트 인벤토리 문서 소실"
    missing = {fl for fl in _env_flags() if fl not in doc}
    assert not missing, (
        f"인벤토리 미등재 env 플래그: {sorted(missing)} — "
        f"docs/GATE_DEFAULT_INVENTORY_2026-07-24.md 에 기본값/판정을 등재하거나 "
        f"NON_ENV_CONSTANTS 로 분류할 것.")


def test_gate_inventory_doc_exists_and_has_verdicts():
    """인벤토리는 목록이 아니라 *판정* 문서 — B 절(env 게이트)에 판정 마커가 있어야."""
    doc = DOC.read_text(encoding="utf-8")
    assert "## B." in doc and "## E." in doc, "인벤토리 구조(게이트/구조 절) 훼손"
