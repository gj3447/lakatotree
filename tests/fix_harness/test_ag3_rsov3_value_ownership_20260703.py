"""AG3/R-SOV V1 값소유(value-ownership) keystone — 측정주권 PROM 2026-07-03.

테제(선행 [[measurement-sovereignty-prom-20260703]]): 원장은 client float 를 '운반'만 한다 —
measurement_grade 부재 → 서버 진짜검증 노드와 client 위조 노드가 *같은 receipt_sha* 를 든다. AG3 는
  (a) measurement_grade 를 RECEIPT_FIELDS 로 봉인(진짜검증≠위조가 다른 sha)하고
  (b) 서버 replay 가 verified 일 때만 regenerated 값을 SSOT metric_value 로 *치환*(값소유, SCOPED).
persisted 노드가 아니라 *들어온*(incoming) 값을 replay 하므로 신규노드도 seal 전에 소유한다 —
AG6/V4 ordering 역전 교정(기존 P0a replay_status 는 submit 시 아직 persist 안 된 mv=None 을 읽어 라이브에서
항상 not_attempted 로 죽어 있었다). SCOPED 치환(항상치환 아님): verified 부분집합만 소유 → 외부/비재현값
(regenerated=None)·반증값 파괴 금지(확정결정).

  guard_defect    = test_verified_replay_owns_value_not_client   (음성: 치환 제거 시 sealed==client → RED)
  guard_mechanism = test_measurement_grade_sealed_in_receipt_fields (양성: grade 가 봉인 sha 를 실제로 가른다)

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag3_value_ownership
"""
from __future__ import annotations

from pathlib import Path

from lakatos.io.replay import ProducerReplayVerdict
from lakatos.verdicts import RECEIPT_FIELDS, receipt_content_sha
from server.contexts.tree.judgement_policy import build_receipt_fields, resolve_measurement
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result

ROOT = Path(__file__).resolve().parents[2]


# ── (A) 순수 결정 seam: resolve_measurement 진리표 ──────────────────────────────────
def test_resolve_measurement_truth_table():
    # None(exec off / 비재현 스크립트): client 값 유지, grade=client_asserted, status=not_attempted.
    assert resolve_measurement(None, 0.5) == (0.5, 'client_asserted', 'not_attempted')
    # verified: regenerated 를 SSOT 로 치환(값소유), grade=server_regenerated, status=verified.
    ok = ProducerReplayVerdict(verified=True, regenerated=0.777, recorded=0.5, reason='externally_verified')
    assert resolve_measurement(ok, 0.5) == (0.777, 'server_regenerated', 'verified')
    # mismatch(위조/크래시): SCOPED — client 값 유지(반증값 소유 안 함), grade=client_asserted, status=mismatch.
    bad = ProducerReplayVerdict(verified=False, regenerated=9.9, recorded=0.5, reason='mismatch')
    assert resolve_measurement(bad, 0.5) == (0.5, 'client_asserted', 'mismatch')
    # 방어: verified 인데 regenerated=None → 소유 불가, client 유지(외부값 null 파괴 금지).
    edge = ProducerReplayVerdict(verified=True, regenerated=None, recorded=0.5, reason='x')
    assert resolve_measurement(edge, 0.5) == (0.5, 'client_asserted', 'verified')


# ── (B) submit 배선: KG fake 로 봉인되는 SET 파라미터 관측 ────────────────────────────
class _SubmitKg:
    def __init__(self):
        self.captured = []

    def __call__(self, query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': '',
                     'vsrc': None, 'nmet': None, 'ndir': None, 'nthr': None, 'psha': None,
                     'closes': None, 'n_opened': 0, 'pred_registered_at': '2026-07-03',
                     'node_state': 'PREDICTED', 'judged_at': None, 'existing_metric_value': None,
                     'hard_core': '', 'require_novel_anchor': False, 'assurance_tier': None,
                     'attestor_dids': None, 'prev_receipt_sha': None}]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{'claimed': 'seam'}] for _ in ops]


def _svc(kg, replay_verdict):
    # producer_replay_submit 를 mock — submit 시 들어온 값의 서버 재유도 결과를 직접 주입.
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None,
                            producer_replay_submit=lambda *a, **k: replay_verdict)


def test_verified_replay_owns_value_not_client():
    """guard_defect: 서버 replay verified → sealed metric_value 는 server regenerated(값소유), client float 아님.

    mock 은 regenerated 를 client 값과 *멀리* 벌려(0.777 vs 0.123) 치환을 관측가능하게 한다 — 실 io.replay
    는 verified⟹within-tol 이나(그 불변식은 test_fix_producer_replay 가 커버), 여기 검증대상은 배선(치환이
    실제로 일어나나)이다. 치환을 r.metric_value 로 되돌리면 mv==0.123 → 이 가드 RED(revert-민감)."""
    kg = _SubmitKg()
    vv = ProducerReplayVerdict(verified=True, regenerated=0.777, recorded=0.123, reason='externally_verified')
    _svc(kg, vv).submit_test_result('T', 'seam', Result(metric_value=0.123, script='/x/score.py',
                                                        result_path='/x/r.json'))
    _q, params = kg.captured[0][0]
    assert params['mv'] == 0.777, f'값소유 실패 — client 0.123 이 봉인됨: {params["mv"]}'
    assert params['mg'] == 'server_regenerated', f'grade={params.get("mg")}'
    assert params['replay_status'] == 'verified'
    assert 'e.measurement_grade=$mg' in _q, 'SET 절에 measurement_grade 없음(persist 누락)'
    assert 'rec.measurement_grade=$mg' in _q, ':VerdictReceipt 봉인에 measurement_grade 없음'


def test_client_asserted_when_no_replay():
    """replay None(exec off): client 값 유지 + grade=client_asserted + not_attempted (dead-σ: 부재≠반증)."""
    kg = _SubmitKg()
    _svc(kg, None).submit_test_result('T', 'seam', Result(metric_value=0.123, script='inline'))
    _q, params = kg.captured[0][0]
    assert params['mv'] == 0.123
    assert params['mg'] == 'client_asserted'
    assert params['replay_status'] == 'not_attempted'


def test_mismatch_does_not_own_value():
    """replay verified=False(위조): SCOPED — client 값 유지(반증값 소유 안 함) + status=mismatch."""
    kg = _SubmitKg()
    bad = ProducerReplayVerdict(verified=False, regenerated=9.9, recorded=0.123, reason='mismatch')
    _svc(kg, bad).submit_test_result('T', 'seam', Result(metric_value=0.123, script='/x/s.py'))
    _q, params = kg.captured[0][0]
    assert params['mv'] == 0.123
    assert params['mg'] == 'client_asserted'
    assert params['replay_status'] == 'mismatch'


def test_measurement_grade_sealed_in_receipt_fields():
    """guard_mechanism: measurement_grade 가 (RECEIPT_FIELDS 봉인 sha)+(build_receipt_fields)+(repository RETURN)에
    실재하고, grade 가 *실제로 receipt_sha 를 가른다*(진짜검증≠위조가 다른 sha — '운반만' 봉합)."""
    assert 'measurement_grade' in RECEIPT_FIELDS
    fields = build_receipt_fields(
        tree='T', tag='n', target_id=None, verdict='progressive', metric_name='m',
        metric_value=0.5, novel_confirmed=True, lakatos_status='ok', judged_at='2026-07-03T00:00:00Z',
        judge_script_sha='x', prev_receipt_sha=None, measurement_grade='server_regenerated')
    assert fields['measurement_grade'] == 'server_regenerated'
    assert set(fields.keys()) == set(RECEIPT_FIELDS)
    # 봉인: grade 만 다르면 receipt_sha 도 달라야 — 없으면 위조·진짜검증이 동일 sha(테제의 구멍).
    a = receipt_content_sha(dict(fields, measurement_grade='server_regenerated'))
    b = receipt_content_sha(dict(fields, measurement_grade='client_asserted'))
    assert a != b, 'measurement_grade 가 receipt_sha 에 안 들어감 — 봉인 실패(client float 운반만)'
    # 읽기표면 공시(SET⊆RETURN parity).
    repo = (ROOT / 'server/contexts/tree/repository.py').read_text(encoding='utf-8')
    assert 'e.measurement_grade AS measurement_grade' in repo


guard_defect = "test_verified_replay_owns_value_not_client"
guard_mechanism = "test_measurement_grade_sealed_in_receipt_fields"
