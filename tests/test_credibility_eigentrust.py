"""prom-honesty/credibility (정본 prom 2026-06-21): set_verdict 의 credibility 입력이 client-self-reported
source_trust 가 아니라 노드의 인터넷 관측 *eigentrust* 로 산출되는지.

  - internal 노드(인터넷 관측 없음) → credibility 게이트 생략(constitution/reproducible 가 영수증).
  - 인터넷 노드 → 그 source 의 eigentrust(네트워크 신뢰, sybil 저항)로 게이트 — self-report 1.0 으론 통과 못 함.
# KG: span_lakatotree_trust
"""
import json

from lakatos.engine import CredibilityTier
from server.contexts.tree.judgement_service import JudgementService


def _svc(obs_rows):
    def kg(q, **kw):
        return obs_rows if "HAS_RESEARCH_EVENT" in q else []
    return JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _obs(source_type, url="x"):
    return {"payload": json.dumps({"url": url, "source_type": source_type, "corroboration_score": 0.5})}


def test_internal_node_skips_credibility_gate():
    """인터넷 관측 없음 → None(credibility 게이트 생략; fake source-trust 로 통과시키지 않는다)."""
    c = _svc([])._eigentrust_credibility("T", "n", novel_confirmed=True, has_human_verdict=False)
    assert c is None


def test_authoritative_internet_source_is_eigentrust_backed_extracted():
    """권위 출처(peer_reviewed=seed) → eigentrust seed_dominated → backed, 직접출처 EXTRACTED(고신뢰 통과)."""
    c = _svc([_obs("peer_reviewed")])._eigentrust_credibility("T", "n", novel_confirmed=False, has_human_verdict=False)
    assert c is not None
    assert c["current"] == CredibilityTier.EXTRACTED and c["has_direct_source"] is True


def test_nonauthoritative_internet_source_is_unbacked_inconclusive():
    """비권위 단일 출처 → uniform_unlearned(미뒷받침) → inconclusive AMBIGUOUS, 직접출처 없음 → CANONICAL 차단."""
    c = _svc([_obs("blog")])._eigentrust_credibility("T", "n", novel_confirmed=True, has_human_verdict=False)
    assert c is not None
    assert c["current"] == CredibilityTier.AMBIGUOUS and c["has_direct_source"] is False
