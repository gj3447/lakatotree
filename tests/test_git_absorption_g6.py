"""git-흡수 G6 landed guards — assurance tier verb×gate 디스패치 테이블 (P1 근본봉합).

git 은 verb 별 전제조건을 한 commands[] 테이블(git.c:529-685)에 선언하고 단일 run_builtin 이 핸들러 전
일괄검사한다(핸들러가 잊을 수 없음). fsck 는 per-OID skiplist(fsck.h:23-104). 이식하되 git 의
default-OFF(transfer.fsckObjects 기본 off)는 *반전*: 신규 트리는 최고 tier(anchored)가 기본, 구조 코어
(G1 receipt CAS·prereg 409·first-write-wins)는 tier 어휘 밖이라 어떤 tier 도 끌 수 없다(by construction).

  guard_defect     = test_no_mutating_verb_writes_verdict_below_tier_floor (개선축 음성 오라클)
  guard_mechanism  = test_structural_core_unconditional_and_hardcore_demote_rejected (novel축 양성 오라클)

상세 스펙트럼(업그레이드/기본값/422·409 경계/replay floor dead-σ/fsck skiplist)은
tests/fix_harness/test_git_absorption_g6_assurance_tier.py — 이 파일은 프로그램 하네스가 scan 하는
이중가드 정본(examples/git_absorption_20260702_programme.py::receipt).

# KG: LakatosTree_GitAbsorption_20260702 / G6_assurance_tier_dispatch_table
"""
from __future__ import annotations

import pytest

from lakatos import assurance
from server.contexts.audit import fsck as F
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result
from server.contexts.tree.writer import TierDowngrade, TreeKgWriter


def _submit_svc(captured: list, *, tier: str | None, flag: bool = False) -> JudgementService:
    """cross-metric novel(nmet≠m) 사전등록 노드 + 트리 tier 를 단 fake KG (FF1 하네스 동형)."""
    def kg(query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': None,
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0,
                     'psha': None, 'closes': None, 'n_opened': 0,
                     'require_novel_anchor': flag, 'assurance_tier': tier}]
        return []
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


class _TreeMetaKg:
    """upsert_tree_meta 의 MERGE ON CREATE + 단조 ratchet CASE 의미론을 충실 재현(revert-민감:
    writer 가 SSOT rank-CASE 를 방출하지 않으면 하향이 그대로 먹혀 demote 가드가 RED)."""

    def __init__(self, seed: dict[str, dict] | None = None):
        self.trees = {k: dict(v) for k, v in (seed or {}).items()}
        self.last_query = ''

    def __call__(self, ops):
        results = []
        for query, params in ops:
            if 'MERGE (t:LakatosTree' not in query:
                results.append([])
                continue
            self.last_query = query
            name = params.get('tree')
            created = name not in self.trees
            t = self.trees.setdefault(name, {})
            declared = params.get('declared_tier')
            if created and 'ON CREATE SET t.assurance_tier' in query:
                t['assurance_tier'] = declared if declared is not None else params.get('default_tier')
            if declared is not None:
                if assurance.cypher_tier_rank_case('t.assurance_tier') in query:   # ratchet 방출됨
                    if params.get('declared_rank', -1) >= assurance.tier_rank(t.get('assurance_tier')):
                        t['assurance_tier'] = declared
                else:                                    # 무가드(revert) = 블랭킷 덮어쓰기 재현
                    t['assurance_tier'] = declared
            results.append([{'assurance_tier': t.get('assurance_tier')}])
        return results


# ── guard_defect (개선축, 음성 오라클): below-floor full standing 이 죽었다 ──────────────────
def test_no_mutating_verb_writes_verdict_below_tier_floor():
    # (1) anchored tier(opt-in 플래그 OFF): 서버앵커 없는 cross-metric novel → partial 강등.
    #     tier 디스패치가 정책 SSOT — 핸들러 하드코딩/per-flag 아님(P1: 기본 설정에서 게이트 ON).
    cap: list = []
    _submit_svc(cap, tier='anchored', flag=False).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))   # novel_script 없음 = 서버앵커 0
    p = cap[0][0][1]
    assert p['v'] == 'partial' and p['novel'] is False, p
    assert p['lstat'] == 'novel_not_server_anchored', p
    # 판결 write 가 resolve 한 tier 를 스탬프(fsck VERDICT_WRITE_WITHOUT_TIER_RESOLVE 의 영수증).
    assert p.get('atier') == 'anchored', p
    # (2) legacy(무tier) 트리 거동불변: 같은 제출이 여전히 progressive(비파괴 — 소급 강등 없음).
    cap2: list = []
    _submit_svc(cap2, tier=None, flag=False).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    assert cap2[0][0][1]['v'] == 'progressive_unverified'
    assert cap2[0][0][1].get('atier') == assurance.LEGACY
    # (3) legacy 의 opt-in 플래그(FF1)는 그대로 존중 — 플래그로 올릴 순 있어도 tier 를 내릴 순 없다.
    cap3: list = []
    _submit_svc(cap3, tier=None, flag=True).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    assert cap3[0][0][1]['v'] == 'partial'
    # (4) 신규 트리 쓰기 기본 = anchored(ON CREATE) — '기본 설정에서 게이트 ON' 의 뿌리.
    tkg = _TreeMetaKg()
    TreeKgWriter(kg_tx=tkg).upsert_tree_meta(name='NEW')
    assert tkg.trees['NEW'].get('assurance_tier') == assurance.DEFAULT_NEW_TREE_TIER == 'anchored'


# ── guard_mechanism (novel축, 양성 오라클): commands[]-테이블 메커니즘 실재 ──────────────────
def test_structural_core_unconditional_and_hardcore_demote_rejected():
    # (1) 구조 코어 무조건: tier/verb 게이트 비트 어휘와 교집합 ∅ — 끌 수 있는 문장이 표현 불가.
    all_bits = frozenset().union(*assurance.TIER_GATES.values(), *assurance.VERB_GATES.values())
    assert assurance.STRUCTURAL_CORE & all_bits == frozenset()
    cores = {assurance.structural_core_gates(t) for t in (*assurance.TIERS, assurance.LEGACY, None)}
    assert cores == {assurance.STRUCTURAL_CORE}
    # (2) 게이트는 tier 상승에 단조증가(느슨해지는 tier 없음).
    ranked = sorted(assurance.TIERS, key=assurance.tier_rank)
    for lo, hi in zip(ranked, ranked[1:]):
        assert assurance.TIER_GATES[lo] <= assurance.TIER_GATES[hi]
    # (3) 하드코어 demote 거부: anchored → notebook 선언은 ratchet CAS 가 거부 + writer 가
    #     SSOT rank-CASE 를 실제 방출(revert-proof).
    tkg = _TreeMetaKg({'PREC': {'assurance_tier': 'anchored'}})
    w = TreeKgWriter(kg_tx=tkg)
    with pytest.raises(TierDowngrade):
        w.upsert_tree_meta(name='PREC', assurance_tier='notebook')
    assert tkg.trees['PREC']['assurance_tier'] == 'anchored'
    assert assurance.cypher_tier_rank_case('t.assurance_tier') in tkg.last_query
    # 동률 멱등 OK · legacy→상승 OK · tier 생략 재-upsert 는 기존 tier 불변(T2 clobber 봉합).
    w.upsert_tree_meta(name='PREC', assurance_tier='anchored')
    tkg2 = _TreeMetaKg({'L': {}})
    w2 = TreeKgWriter(kg_tx=tkg2)
    w2.upsert_tree_meta(name='L', assurance_tier='receipted')
    assert tkg2.trees['L']['assurance_tier'] == 'receipted'
    w2.upsert_tree_meta(name='L', title='re-run without tier')
    assert tkg2.trees['L']['assurance_tier'] == 'receipted'
    # (4) legacy 면제는 record content-sha skiplist 로만(git per-OID) — 규칙 클래스 면제 불가.
    legacy = {'verdict': 'progressive', 'verdict_source': 'scripted',
              'pred_registered_at': '2026-07-01', 'judged_at': '2026-07-01T00:00:00Z'}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' in {f.check_id for f in F.fsck_node(legacy)}
    skip = frozenset({F.record_content_sha(legacy)})
    assert F.fsck_node(legacy, skiplist=skip) == []
    peer = {**legacy, 'judged_at': '2026-07-01T00:00:01Z'}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' in {f.check_id for f in F.fsck_node(peer, skiplist=skip)}
    # (5) 새 쓰기(tier 스탬프 보유)는 finding 0 — 경계가 미래 쓰기를 막지 않는다.
    stamped = {**legacy, 'assurance_tier_resolved': 'anchored'}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' not in {f.check_id for f in F.fsck_node(stamped)}
