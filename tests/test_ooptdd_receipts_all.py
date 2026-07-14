"""ooptdd 영수증 전수 CI 이빨 — ooptdd_receipts/*/requirements.yaml 자동 발견·전수 실행.

채택 배선(2026-07-02): LTDD 영수증이 '만든 사람 세션에서만 도는 산출물'이면 채택이 아니다 —
여기서 *자동 발견*해 매 스위트마다 전수 실행한다. 새 영수증은 ooptdd_receipts/<ID>/ 에 spec+
emit-adapter 만 두면 등록 없이 CI 상주(추가만 하면 이빨). 엔진 코드가 영수증 계약을 깨면 스위트 RED.

러너는 self-contained: _vendor/ooptdd_loop + repo .venv(fastapi 有), 네트워크/시크릿 0 (memory backend).
코퍼스는 자동발견하므로 수동 개수표와 무관하게 모든 영수증을 실행한다.

규율 리마인드(각 영수증): emit-adapter 는 실코드 구동(재구현 금지) + 음성 오라클(vacuous green 차단) 필수.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

import lakatos.io  # noqa: F401 — _vendor bootstrap (import ooptdd / ooptdd_loop 해석)
from ooptdd_loop.runner import run_loop
from ooptdd_loop.spec import load_spec
from ooptdd_loop.tools import _run_payload

_REPO = Path(__file__).resolve().parents[1]
_SPECS = sorted(glob.glob(str(_REPO / "ooptdd_receipts" / "*" / "requirements.yaml")))


def test_receipt_corpus_is_nonempty_and_growing():
    """자동발견이 진공이 아님 — 현재 정본 28개 이상(삭제는 명시 결정이어야 한다)."""
    assert len(_SPECS) >= 28, f"영수증 코퍼스 축소: {len(_SPECS)}개 — 삭제는 명시 결정이어야 한다"


def test_dedicated_runner_discovers_exact_same_corpus():
    """전용 CI runner와 pytest가 같은 spec 집합을 실행한다 — 수동 allowlist drift 차단."""
    from ooptdd_receipts.run_all import discover_specs

    dedicated = {str(p) for p in discover_specs()}
    assert dedicated == set(_SPECS), (
        f"전용 runner와 pytest corpus 불일치: dedicated_only={sorted(dedicated - set(_SPECS))}, "
        f"pytest_only={sorted(set(_SPECS) - dedicated)}")


@pytest.mark.parametrize("spec_path", _SPECS, ids=lambda p: Path(p).parent.name)
def test_ooptdd_receipt_green(spec_path: str):
    """각 영수증: spec 로드 → in-process 구동 → 요구사항 전수 done + methodology_ok."""
    spec = load_spec(spec_path)
    spec.target.root = str(Path(spec_path).resolve().parent)   # cwd 무관(이식성) — run_all.py 규율
    payload = _run_payload(run_loop(spec))
    assert payload.get("total", 0) > 0, f"빈 spec(요구사항 0): {spec_path}"
    assert payload.get("done") == payload.get("total"), \
        f"영수증 RED {Path(spec_path).parent.name}: {payload.get('done')}/{payload.get('total')}"
    assert payload.get("complete") and payload.get("methodology_ok"), payload
