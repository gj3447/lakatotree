"""FF5b guard (frontier-fix 2026-06-26): trust fail-open 기본값 봉합 — 검증 안 된 *출처주장*(source 키 보유)
verdict 가 source_trust 미지정 시 최대신뢰(1.0)가 아니라 fail-safe(무정보)를 받는다. 내부(출처주장 없음)
verdict 는 1.0 유지(비파괴 — conformance/bayes 단위테스트는 source 키 없는 verdict 라 영향 없음).

deep-dive FF5b: branch_credence 의 v.get('source_trust', 1.0) 가 신뢰 데이터 없는 출처에 *최대* 증거력.
D1 이 wired 경로(scripted 노드 e.source_trust 영속, forged→0.0)는 이미 닫았고, 이 가드는 *bare default*
방향(출처주장 미검증=무정보)을 못박는다. branch_credence 는 metrics/leaderboard 가 쓰는 실 집계함수.

두 가드 green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF5b 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF5b_trust_failopen_default
"""
from __future__ import annotations

from lakatos.quant.bayes import DEFAULT_PRIOR, SOURCE_TRUST_FAILSAFE, branch_credence

_STRONG = dict(verdict='progressive', delta=5.0, noise_band=1.0)   # 강한 progressive(효과크기 큼)


def test_absent_source_trust_is_not_max_credulous():
    """음성 오라클: 출처주장(source) O + source_trust 미지정 → fail-open(최대신뢰) 아님 → credence 무정보(prior 불변).
    같은 verdict 가 명시 high-trust 면 boost 되는 것과 대비(=trust 가 실제로 게이트)."""
    claim_no_trust = branch_credence([{**_STRONG, 'source': 'http://unverified.example'}])
    claim_trusted = branch_credence([{**_STRONG, 'source': 'http://x', 'source_trust': 1.0}])
    assert claim_no_trust < claim_trusted, (claim_no_trust, claim_trusted)
    # fail-safe = 무정보(BF 중립) → prior 불변(최대신뢰였다면 prior 위로 boost 됐을 것)
    assert abs(claim_no_trust - DEFAULT_PRIOR) < 1e-9, claim_no_trust


def test_trust_default_floors_to_failsafe_not_one():
    """양성: 미검증 출처주장의 trust 기본 = SOURCE_TRUST_FAILSAFE(≠1.0, ≤하한). 내부(출처주장 없음)는 1.0 유지(비파괴)."""
    assert SOURCE_TRUST_FAILSAFE != 1.0 and SOURCE_TRUST_FAILSAFE <= 0.5
    # 내부 verdict(source 키 없음)는 여전히 1.0 가중 → credence boost(비파괴 회귀가드: 기존 동작 보존)
    internal = branch_credence([dict(**_STRONG)])   # source 키 없음
    assert internal > DEFAULT_PRIOR, internal
    # 출처주장-without-trust 는 boost 안 됨(내부와 대비 = 구분이 실재)
    claim_no_trust = branch_credence([{**_STRONG, 'source': 'http://unverified.example'}])
    assert claim_no_trust < internal, (claim_no_trust, internal)
