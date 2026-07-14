"""git-흡수 G6 — assurance tier verb×gate 디스패치 테이블 (이중 가드).

git 은 verb 별 전제조건을 한 commands[] 테이블(git.c:529-685)에 선언하고 단일 run_builtin 이 핸들러 전
일괄검사한다(핸들러가 잊을 수 없음). fsck 는 FATAL 비강등 + per-OID skiplist(fsck.h:23-104). 이식하되
git 의 default-OFF(transfer.fsckObjects 기본 off)는 *반전*: 신규 트리는 최고 tier(anchored)가 기본이고,
구조 코어(G1 receipt CAS·prereg 409·first-write-wins)는 tier 어휘 밖이라 어떤 tier 도 끌 수 없다.

이중 가드(RED-first — 작성 시점 grep: 'assurance_tier' 코드 0곳):
  guard_defect     = test_no_mutating_verb_writes_verdict_below_tier_floor
  guard_mechanism  = test_structural_core_unconditional_and_hardcore_demote_rejected

# KG: LakatosTree_GitAbsorption_20260702 / G6_assurance_tier_dispatch_table
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lakatos import assurance
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result
from server.contexts.tree.schemas import VerdictIn


# ───────────────────────── submit_test_result 경로 fake (FF1 하네스 동형) ─────────────────────────

def _submit_svc(captured: list, *, tier: str | None, flag: bool = False) -> JudgementService:
    """cross-metric novel(nmet='novelaxis' ≠ m='seam') 사전등록 노드 + 트리 tier 를 단 fake KG.

    핵심: require_novel_anchor *플래그는 off* — 데모트가 일어나면 그건 tier 디스패치가 발동한 것.
    """
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


def _params(cap: list) -> dict:
    return cap[0][0][1]


def test_no_mutating_verb_writes_verdict_below_tier_floor():
    """guard_defect: anchored tier 트리(opt-in 플래그 OFF)에서 cross-metric novel 을 서버앵커 영수증
    없이 제출하면 progressive 가 *아니라* partial — tier 자체가 정책 SSOT(핸들러 하드코딩·per-flag 아님).

    revert 민감도: judgement_service 가 tier 디스패치를 안 읽으면(플래그만 보면) progressive → RED."""
    cap: list = []
    _submit_svc(cap, tier='anchored', flag=False).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))   # novel_script 없음 = 서버앵커 부재
    p = _params(cap)
    assert p['v'] == 'partial', f"anchored tier floor 미발동 — client float 로 progressive 를 삼: {p['v']}"
    assert p['novel'] is False, p
    assert p['lstat'] == 'novel_not_server_anchored', p


def test_notebook_and_legacy_tier_behavior_invariant():
    """비파괴 회귀: notebook tier(명시 최저) 와 legacy(무tier, G6 이전 트리)는 플래그 off 면
    기존 동작 그대로 progressive — tier 도입이 구 트리를 소급 강등하지 않는다(거동 불변)."""
    for tier in ('notebook', None):
        cap: list = []
        _submit_svc(cap, tier=tier, flag=False).submit_test_result('T', 'n', Result(
            metric_value=1.0, script='inline', novel_measured=1.0))
        assert _params(cap)['v'] == 'progressive_unverified', f"tier={tier} 가 소급 강등됨(비파괴 위반)"


def test_legacy_tree_optin_flag_still_respected():
    """legacy 트리의 기존 opt-in 플래그(require_novel_anchor=True)는 tier 도입 후에도 그대로 발동(FF1 보존)."""
    cap: list = []
    _submit_svc(cap, tier=None, flag=True).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    assert _params(cap)['v'] == 'partial'


def test_scored_node_stamps_resolved_tier():
    """S5 전제: 판결 write 가 어느 tier 로 resolve 됐는지 노드에 스탬프(fsck 의 tier-resolve 흔적)."""
    cap: list = []
    _submit_svc(cap, tier='anchored', flag=False).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    query, params = cap[0][0]
    assert 'assurance_tier_resolved' in query, "판결 SET 에 tier-resolve 스탬프 없음(S5 fsck 흔적 부재)"
    assert params.get('atier') == 'anchored', params


# ───────────────────────── 디스패치 테이블 SSOT + tier ratchet (mechanism) ─────────────────────────

class _FakeTreeMetaKg:
    """upsert_tree_meta 가 방출한 Cypher 의 MERGE...ON CREATE SET + 단조 ratchet CASE 의미론을 최소 재현.

    G1 fake 규율: writer 가 ratchet CASE(assurance.cypher_tier_rank_case SSOT 생성물)를 *실제로 방출*할
    때만 단조 의미론을 적용 — 무가드로 되돌리면(블랭킷 SET) 다운그레이드가 그대로 먹혀 409 테스트가 RED.
    """

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
            ratcheted = assurance.cypher_tier_rank_case('t.assurance_tier') in query
            if declared is not None:
                if ratcheted:
                    cur_rank = assurance.tier_rank(t.get('assurance_tier'))
                    if params.get('declared_rank', -1) >= cur_rank:
                        t['assurance_tier'] = declared
                else:   # 무가드(revert) = 블랭킷 덮어쓰기 → 다운그레이드 관철 = 테스트 RED
                    t['assurance_tier'] = declared
            results.append([{'assurance_tier': t.get('assurance_tier')}])
        return results


def _writer(seed=None):
    from server.contexts.tree.writer import TreeKgWriter
    kg = _FakeTreeMetaKg(seed)
    return TreeKgWriter(kg_tx=kg), kg


def test_structural_core_unconditional_and_hardcore_demote_rejected():
    """guard_mechanism 이중 프롱.

    (a) 구조 코어 무조건: G1 receipt CAS·prereg 409·first-write-wins 는 tier 게이트 *어휘 밖* —
        어떤 tier/verb 조합도 이를 끄는 문장을 표현할 수 없다(by construction). 모든 tier 에서
        structural_core_gates 동일 + tier 게이트 비트와 교집합 ∅.
    (b) 하드코어 demote 거부: 기존 anchored 트리에 notebook 선언 → 단조 ratchet CAS 가 거부(409 어휘,
        writer 예외) + writer 가 SSOT 생성 rank-CASE 를 실제 방출(revert-proof)."""
    # (a) 구조 코어 — tier 로 표현 불가
    all_tier_bits = frozenset().union(*assurance.TIER_GATES.values())
    all_verb_bits = frozenset().union(*assurance.VERB_GATES.values())
    assert assurance.STRUCTURAL_CORE & (all_tier_bits | all_verb_bits) == frozenset(), \
        "구조 코어 게이트가 tier/verb 비트 어휘에 등장 — tier 로 끌 수 있는 표현이 생김(P1 역전 파손)"
    cores = {assurance.structural_core_gates(t) for t in (*assurance.TIERS, assurance.LEGACY, None)}
    assert cores == {assurance.STRUCTURAL_CORE}, "structural core 가 tier 에 따라 달라짐(무조건성 파손)"
    # 게이트는 tier 상승에 단조증가(상위 tier 가 하위의 superset — 느슨해지는 tier 없음)
    ranked = sorted(assurance.TIERS, key=assurance.tier_rank)
    for lo, hi in zip(ranked, ranked[1:]):
        assert assurance.TIER_GATES[lo] <= assurance.TIER_GATES[hi], f"{hi} ⊉ {lo}: tier 상승이 게이트를 풀음"

    # (b) demote 거부 + revert-proof
    from server.contexts.tree.writer import TierDowngrade
    writer, kg = _writer({'PREC': {'assurance_tier': 'anchored'}})
    with pytest.raises(TierDowngrade):
        writer.upsert_tree_meta(name='PREC', assurance_tier='notebook')
    assert kg.trees['PREC']['assurance_tier'] == 'anchored', "다운그레이드가 관철됨(ratchet 파손)"
    assert assurance.cypher_tier_rank_case('t.assurance_tier') in kg.last_query, \
        "writer 가 SSOT rank-CASE ratchet 를 방출하지 않음 — 블랭킷 SET 으로 되돌아감"


def test_upgrade_allowed_and_monotone():
    """ratchet 은 단조 *증가* 는 허용: notebook → anchored 업그레이드는 관철(과잉차단 아님)."""
    writer, kg = _writer({'T': {'assurance_tier': 'notebook'}})
    writer.upsert_tree_meta(name='T', assurance_tier='anchored')
    assert kg.trees['T']['assurance_tier'] == 'anchored'


def test_new_tree_defaults_to_anchored_legacy_untouched():
    """git default-OFF 의 반전(P1): 신규 트리는 ON CREATE SET 으로 anchored 가 기본.
    T2 clobber 교정: 기존 legacy(무tier) 트리는 tier 미선언 upsert 에 절대 안 덮인다(ON CREATE only)."""
    writer, kg = _writer({'OLD': {}})          # 기존 트리, tier 없음(legacy)
    writer.upsert_tree_meta(name='NEW')        # 신규, tier 미선언
    writer.upsert_tree_meta(name='OLD')        # 기존, tier 미선언 upsert
    assert kg.trees['NEW'].get('assurance_tier') == assurance.DEFAULT_NEW_TREE_TIER
    assert kg.trees['OLD'].get('assurance_tier') is None, \
        "tier 미선언 upsert 가 legacy 트리에 tier 를 스탬프(T2 write-clobber 재발)"


def test_unknown_tier_rejected_422():
    """선언 tier 어휘는 닫힌 집합(TIERS) — 오타/미정의 tier 는 422(무음 저장 금지)."""
    from server.contexts.tree.mutations import TreeMutationService, TreeSpec
    from server.contexts.tree.validation import LakatosSemanticValidator
    writer, _ = _writer()
    svc = TreeMutationService(writer=writer, validator=LakatosSemanticValidator(),
                              hist=lambda *a, **k: None)
    with pytest.raises(HTTPException) as ei:
        svc.upsert_tree(TreeSpec(name='T', hard_core='hc', frontier_rule='fr',
                                 assurance_tier='precious'))
    assert ei.value.status_code == 422
    assert 'assurance_tier' in str(ei.value.detail)   # meta 검증이 아니라 tier 어휘 거부여야


def test_demote_maps_to_409_at_service_boundary():
    """mutations 경계: writer TierDowngrade → HTTP 409 로 번역(클라이언트 계약)."""
    from server.contexts.tree.mutations import TreeMutationService, TreeSpec
    from server.contexts.tree.validation import LakatosSemanticValidator
    writer, _ = _writer({'PREC': {'assurance_tier': 'anchored'}})
    svc = TreeMutationService(writer=writer, validator=LakatosSemanticValidator(),
                              hist=lambda *a, **k: None)
    with pytest.raises(HTTPException) as ei:
        svc.upsert_tree(TreeSpec(name='PREC', hard_core='hc', frontier_rule='fr',
                                 assurance_tier='receipted'))
    assert ei.value.status_code == 409


# ───────────────────────── S4 replay 승격 FLOOR (dead-σ 교정) ─────────────────────────

def _canon_svc(*, tier: str | None, replay):
    """CANONICAL 승격 경로 fake — scripted progressive + novel_confirmed 후보 노드."""
    def kg(query, **p):
        if 'cur.verdict AS verdict' in query:
            return [{'verdict': 'progressive', 'verdict_source': 'scripted', 'node_state': None,
                     'source_trust': 1.0, 'novel_confirmed': True, 'qualitative_self_report': False,
                     'author': '', 'args': [], 'assurance_tier': tier}]
        if "cur.verdict='CANONICAL'" in query:
            return [{'tag': p.get('tag')}]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: [[] for _ in ops], hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None,
                            producer_replay_for_node=lambda n, t: replay)


def test_replay_floor_blocks_canonical_only_when_ran_and_failed():
    """anchored tier: producer replay 가 *실행되어 실패*(False)했으면 CANONICAL 승격 409 —
    측정 재실행이 반증한 노드를 최강 주장으로 못 올린다(승격 FLOOR)."""
    with pytest.raises(HTTPException) as ei:
        _canon_svc(tier='anchored', replay=False).set_verdict('T', 'n', VerdictIn(verdict='CANONICAL'))
    assert ei.value.status_code == 409
    assert 'replay' in str(ei.value.detail).lower()


def test_replay_floor_nonblocking_when_exec_off_dead_sigma():
    """dead-σ 교정(관통위험 ④): LAKATOS_REPLAY_EXEC off 배포에서 replay=None(검증 불가)은 *비차단* —
    anchored tier 라도 승격이 잠기지 않는다(검증 불가 = 부재지 반증이 아님). notebook/legacy 는
    False 여도 비차단(floor 는 anchored 전용)."""
    assert _canon_svc(tier='anchored', replay=None).set_verdict(
        'T', 'n', VerdictIn(verdict='CANONICAL'))['ok'] is True
    assert _canon_svc(tier='notebook', replay=False).set_verdict(
        'T', 'n', VerdictIn(verdict='CANONICAL'))['ok'] is True
    assert _canon_svc(tier=None, replay=False).set_verdict(
        'T', 'n', VerdictIn(verdict='CANONICAL'))['ok'] is True


# ───────────────────────── S5 fsck: tier-resolve 흔적 + legacy skiplist ─────────────────────────

def test_fsck_flags_verdict_write_without_tier_resolve_with_skiplist():
    """scripted 판결인데 tier-resolve 스탬프가 없으면 열거 check-id 로 표면화(ERROR).
    legacy 면제는 *레코드 content-sha skiplist 로만*(git per-OID skiplist) — 규칙 자체는 면제 불가."""
    from server.contexts.audit import fsck as F
    legacy = {'verdict': 'progressive', 'verdict_source': 'scripted',
              'pred_registered_at': '2026-06-01T00:00:00+00:00', 'judged_at': '2026-06-01T00:00:01+00:00',
              'source_trust': 1.0}
    ids = {f.check_id for f in F.fsck_node(legacy)}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' in ids

    stamped = {**legacy, 'assurance_tier_resolved': 'anchored'}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' not in {f.check_id for f in F.fsck_node(stamped)}

    # skiplist: 그 레코드만 면제(내용 바뀌면 sha 가 달라져 면제 소멸 — 규칙 면제 아님)
    skip = frozenset({F.record_content_sha(legacy)})
    assert F.fsck_node(legacy, skiplist=skip) == []
    other = {**legacy, 'judged_at': '2026-06-02T00:00:00+00:00'}
    assert 'VERDICT_WRITE_WITHOUT_TIER_RESOLVE' in {f.check_id for f in F.fsck_node(other, skiplist=skip)}
    # boundary(ingest) 도 같은 skiplist 의미론(audit==ingest 양방향)
    assert F.boundary_fsck(legacy, skiplist=skip) == []
    assert F.boundary_fsck(legacy) != []
