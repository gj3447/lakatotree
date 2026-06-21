"""PROM-C (prom-honesty): write→독립 read→compare *positive* 왕복 receipt — CI=hermetic memory, 외부=gated.

감사 발견: oo/marquez 테스트가 전부 opener 주입(같은 프로세스가 만든 hand-crafted hits 대조 = 영수증
연극)이고 write→독립 read→compare 왕복이 *어디에도 없다*; 유일한 실네트워크 테스트는 기본 OFF + 부정경로만.

이 파일이 그 구멍을 닫는다 — ooptdd 0.3.0 backend conformance kit(실제 ship→query 왕복)으로:
  · CI(hermetic): memory backend 가 *실제* persist + 독립 read-back 하는 진짜 왕복(opener 주입 아님).
    whole-row·_timestamp·injection-safe cid·completeness·gate 까지 ship→query 로 검증.
  · 반-공허(teeth): drop=True(silent ingest loss — 2026-06-09 22h 미감지 그 실패모드)는 *반드시* 실패.
  · gated(real store): 외부 백엔드 1개로 positive 외부 왕복(CONSUMER_LOGS_E2E=1 + OOPTDD_E2E_BACKEND).
# KG: span_lakatotree_oo_sink / LakatosTree_PromHonesty_20260620
"""
from __future__ import annotations

import os

import pytest

import lakatos.io.oo_sink  # noqa: F401 — _vendor 를 sys.path 에 올리는 부트스트랩(import ooptdd 해석)
from ooptdd.backends import get_backend, memory_reset
from ooptdd.backends.conformance import assert_backend_conforms
from ooptdd.backends.memory import MemoryBackend


def test_oo_positive_roundtrip_memory_backend():
    """진짜 write→독립 read→compare 왕복: memory backend 가 실제 저장·재독한다(opener hand-crafted hits 아님).
    ship→query 로 whole-row passthrough·_timestamp·cid 바인딩·completeness·gate 평가까지 검증(어긋나면 raise)."""
    memory_reset()
    assert_backend_conforms(lambda: MemoryBackend())


def test_roundtrip_catches_silent_ingest_loss():
    """반-공허(RED-with-teeth): 적재했다 *조용히 잃는* 백엔드(drop=True, 2026-06-09 그 실패모드)는
    반드시 검출돼야 한다 — 통과하면 왕복이 무력. (왕복 receipt 가 진짜 이빨이 있음을 증명)."""
    memory_reset()
    with pytest.raises(AssertionError, match="round-trip lost"):
        assert_backend_conforms(lambda: MemoryBackend(drop=True))


@pytest.mark.skipif(os.getenv('CONSUMER_LOGS_E2E') != '1' or not os.getenv('OOPTDD_E2E_BACKEND'),
                    reason='oo e2e off — 실외부 store positive 왕복 (CONSUMER_LOGS_E2E=1 + OOPTDD_E2E_BACKEND 설정)')
def test_oo_positive_roundtrip_real_store():
    """gated: 실제 외부 백엔드(openobserve/clickhouse/victorialogs/…)에 ship→query positive 왕복.
    기존 lakatos 실네트워크 테스트가 *부정경로*(bogus cid)만 보던 것을 positive 외부 왕복으로 보완."""
    assert_backend_conforms(lambda: get_backend(os.environ['OOPTDD_E2E_BACKEND']))
