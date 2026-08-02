"""run_cycle 일관성 계약 characterization — Phase 3(UoW) 결정의 박제 + G3 문제이동 반영.

판단(2026-06-16): run_cycle 을 단일 분산 트랜잭션으로 만드는 정식 UoW 는 *하지 않는다*.
근거 — ① submit_test_result 가 register_prediction 의 KG write 를 read-back 한 뒤 Python
judge() 로 판정한다(write→read→compute→write 사슬) → 단순 ops batch 불가. ② 정식 UoW(공유
tx 관통)는 Tree/Judgement/EvidenceClaim 3개 서비스를 가로지르는 고위험 변경. ③ 실제 노출은
좁고 *자기치유적*: 노드 write 는 MERGE, 예측은 SET(멱등) → 부분 실패 후 재실행이 안전.

★G3(git-흡수 2026-07-02) 문제이동 — 계약이 *두 구간*으로 갈라졌다(UoW 없이 보상 롤백으로):
  - pre-receipt(node/predict/submit 실패): 이 사이클이 만든 신규 노드는 보상 롤백 → 신규노드 0
    (가드: tests/test_git_absorption_g3.py — 고아 예측노드 debris 금지).
  - post-receipt(critique 이후 실패): 판결 영수증이 *내구점* — 롤백하지 않는다(G1 불변영수증·
    G9 증거불멸). 이 파일이 박제하는 것이 바로 이 구간이다.
이 파일의 테스트는 여전히 유효하다: critique-실패 시 앞 단계 write 잔존 + 재실행 완주(멱등).
# KG: span_lakatotree_engine
"""
import importlib
import json
import os
from pathlib import Path

import pytest

from lakatos.verdicts import receipt_content_sha, verdict_history_payload_sha

ROOT = Path(__file__).resolve().parents[1]


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _patch_steps(app, monkeypatch, calls, *, critique_raises=False, durable=None):
    """run_cycle 이 오케스트레이션하는 단계 facade 들을 기록용 fake 로 교체.
    (per-call _programme_service() 팩토리가 이 패치를 캡처한다 — test_p5 와 동일 seam.)"""
    # These are application-service orchestration tests, not startup/storage
    # election tests.  Live readiness/fencing has dedicated coverage.
    monkeypatch.setattr(app, '_require_critique_history_ready', lambda: None)
    monkeypatch.setattr(app, 'add_cycle_node', lambda n, x, claim: (calls.append('node'), {'ok': True})[1])
    monkeypatch.setattr(app, 'register_prediction', lambda n, t, x: (calls.append('predict'), {'ok': True})[1])
    durable = {} if durable is None else durable

    def _kg(query, **params):
        if "OutboxEntry {id:$event_id}" in query:
            row = durable.get(params["event_id"])
            if row is None:
                return []
            snapshot = dict(row)
            group = snapshot.get('cycle_causal_group')
            group_rows = []
            for entry in durable.values():
                causal_group = entry.get(
                    'causal_group', entry.get('cycle_causal_group')
                )
                if causal_group != group:
                    continue
                member = dict(entry)
                if 'outbox_receipt_sha' in member:
                    member.update(
                        receipt_sha=member.get('outbox_receipt_sha'),
                        causal_group=member.get('cycle_causal_group'),
                        causal_index=member.get('cycle_causal_index'),
                    )
                group_rows.append(member)
            snapshot['group_outboxes'] = sorted(
                group_rows,
                key=lambda member: (
                    member.get('causal_index'), member.get('id')
                ),
            )
            return [snapshot]
        if "OutboxEntry {causal_group:$group}" in query:
            group = params["group"]
            found = []
            for entry in durable.values():
                causal_group = entry.get(
                    'causal_group', entry.get('cycle_causal_group')
                )
                if causal_group != group:
                    continue
                row = dict(entry)
                if 'outbox_receipt_sha' in row:
                    row.update(
                        receipt_sha=row.get('outbox_receipt_sha'),
                        causal_group=row.get('cycle_causal_group'),
                        causal_index=row.get('cycle_causal_index'),
                    )
                found.append(row)
            return sorted(
                found,
                key=lambda row: (row.get('causal_index'), row.get('id')),
            )
        return []

    def _submit(n, t, x, *, cycle_claim, cycle_request):
        calls.append('result')
        suffix = cycle_claim.removeprefix('cycle-')
        event_id = f'ob-cycle-result-{suffix}'
        request_sha256 = 'c' * 64
        test_summary = {
            'value': 0.4,
            'baseline': 0.5,
            'delta': -0.2,
            'verdict': 'progressive',
            'script': 'inline',
            'result_path': '',
            'source_script_path': 'inline',
            'source_result_path': '',
            'result_sha256': None,
            'measurement_lock_sha': None,
            'novel': None,
            'script_sha': '',
            'freshen': False,
            'replay_status': 'not_attempted',
            'replay_reason': 'unsealed_script',
            'regenerated_metric': None,
            'lakatos': 'progressive',
            'metric_verdict': 'progressive',
            'novel_server_anchored': True,
            'requires_human': False,
            'script_sha_server_verified': False,
            'rule': 'improved',
            'attested_by': None,
            'cycle_claim': cycle_claim,
            'cycle_request_sha256': suffix,
            'request_sha256': request_sha256,
            'verdict_display': (
                'progressive@L0(client_asserted,client_asserted_unverified)'
            ),
            'assurance': {'val': 0, 'basis': ['client_asserted_unverified']},
            'qualitative_self_report': False,
            'replay_authoritative': False,
            'eureka_open': {
                'felt': False, 'true': False, 'hallucinated': False,
                'reasons': [], 'bf': 0.0,
            },
            'eureka_closed': {
                'felt': False, 'true': False, 'hallucinated': False,
                'reasons': [], 'bf': 0.0,
            },
        }
        receipt_fields = {
            'tree': n,
            'tag': t,
            'target_id': None,
            'verdict': 'progressive',
            'verdict_source': 'scripted',
            'metric_name': 'p95',
            'metric_value': 0.4,
            'novel_confirmed': None,
            'lakatos_status': 'progressive',
            'judged_at': '2026-08-02T00:00:00+00:00',
            'judge_script_sha': '',
            'prev_receipt_sha': None,
            'measurement_grade': 'client_asserted',
            'engine_rule_sha': None,
            'comment_sha': None,
            'replay_status': 'not_attempted',
            'replay_reason': 'unsealed_script',
            'regenerated_metric': None,
            'judge_script_path': 'inline',
            'result_path': '',
            'result_sha256': None,
            'measurement_lock_sha': None,
            'source_script_path': 'inline',
            'source_result_path': '',
            'history_payload_sha256': verdict_history_payload_sha(test_summary),
        }
        receipt_sha = receipt_content_sha(receipt_fields)
        test_event_id = f'ob-test-result-{receipt_sha}'
        payload = {
            'cycle_claim': cycle_claim,
            'cycle_request': cycle_request,
            'verdict_receipt_sha': receipt_sha,
            'dependent_history_event_ids': [test_event_id],
            'result': {
                'delta': -0.2,
                'lakatos': 'progressive',
                'novel': None,
                'novel_server_anchored': True,
                'verdict': 'progressive',
            },
        }
        durable[event_id] = {
            'id': event_id,
            'tree': n,
            'op': 'cycle_result',
            'node_tag': t,
            'payload': json.dumps(payload, sort_keys=True, separators=(',', ':')),
            'status': 'pending',
            'created_at': '2026-08-02T00:00:00+00:00',
            'reason': 'cycle_result_commit_intent',
            'applied_at': None,
            'outbox_receipt_sha': receipt_sha,
            'current_receipt_sha': receipt_sha,
            'bound_receipt_sha': receipt_sha,
            'receipt_tree': n,
            'receipt_tag': t,
            'cycle_causal_group': receipt_sha,
            'cycle_causal_index': 2,
            'current_verdict': 'progressive',
            'current_verdict_source': 'scripted',
            'current_lakatos_status': 'progressive',
            'current_metric_value': 0.4,
            **{f'receipt_{key}': value for key, value in receipt_fields.items()
               if key not in {'tree', 'tag'}},
        }
        durable[test_event_id] = {
            'id': test_event_id,
            'tree': n,
            'op': 'test_result',
            'node_tag': t,
            'payload': json.dumps({**test_summary, 'receipt_sha': receipt_sha},
                                  sort_keys=True, separators=(',', ':')),
            'status': 'pending',
            'created_at': '2026-08-02T00:00:00+00:00',
            'reason': 'test_result_commit_intent',
            'applied_at': None,
            'receipt_sha': receipt_sha,
            'causal_group': receipt_sha,
            'causal_index': 0,
            'request_sha256': request_sha256,
        }
        return {
            'verdict': 'progressive',
            'novel': None,
            'lakatos': 'progressive',
            'delta': -0.2,
            'novel_server_anchored': True,
            '_cycle_event_id': event_id,
            '_cycle_payload': payload,
        }

    monkeypatch.setattr(app, 'kg', _kg)
    monkeypatch.setattr(app, 'hist', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'submit_test_result', _submit)

    def _critique(n, t, x):
        calls.append('critique')
        if critique_raises:
            raise RuntimeError('critique write 실패 (부분 실패 시뮬레이션)')
        return {'ok': True}

    monkeypatch.setattr(app, 'add_critique', _critique)
    monkeypatch.setattr(app, 'standing', lambda n, t: {'stands': True})


def _cycle(app):
    return app.CycleIn(tag='e1', metric_name='p95', baseline=0.5, measured=0.4,
                       critiques=[app.CritiqueIn(arg_id='d1', attacks='e1')])


@pytest.mark.parametrize("location", ["tree", "tag", "comment", "critique"])
@pytest.mark.parametrize("poison", ["bad\x00text", "bad\ud800text"])
def test_cycle_rejects_postgres_hostile_text_before_any_step(
    monkeypatch,
    location,
    poison,
):
    app = load_app()
    calls = []
    _patch_steps(app, monkeypatch, calls)
    tree = "T"
    payload = _cycle(app).model_dump()
    if location == "tree":
        tree = poison
    elif location == "tag":
        payload["tag"] = poison
    elif location == "comment":
        payload["comment"] = poison
    else:
        payload["critiques"][0]["body"] = poison

    # Pydantic itself rejects a lone surrogate in ``tag``.  Bypass only that
    # outer schema boundary so this test still exercises run_cycle's complete
    # record preflight (defence in depth for internal callers).
    if location == "tag" and "\ud800" in poison:
        cycle = app.CycleIn.model_construct(
            **{
                **payload,
                "critiques": [
                    app.CritiqueIn(**critique)
                    for critique in payload["critiques"]
                ],
            }
        )
    else:
        cycle = app.CycleIn(**payload)

    with pytest.raises(app.HTTPException) as exc:
        app.run_cycle(tree, cycle)

    assert exc.value.status_code == 422
    assert calls == []


def test_valid_unicode_cycle_uses_the_same_preflighted_request_for_claim(
    monkeypatch,
):
    app = load_app()
    calls = []
    durable = {}
    _patch_steps(app, monkeypatch, calls, durable=durable)
    cycle = app.CycleIn(
        tag="실험-하나",
        metric_name="정확도",
        baseline=0.5,
        measured=0.4,
        comment="정상 유니코드",
        critiques=[
            app.CritiqueIn(arg_id="반박-하나", attacks="실험-하나", body="검토"),
        ],
    )
    request = ["나무", cycle.model_dump()]
    expected_claim = app._programme_service()._cycle_claim(
        "나무", cycle, request
    )

    app.run_cycle("나무", cycle)

    event_id = f"ob-cycle-result-{expected_claim.removeprefix('cycle-')}"
    assert durable[event_id]["id"] == event_id
    assert json.loads(durable[event_id]["payload"])["cycle_request"] == request


def test_run_cycle_is_not_atomic_partial_writes_persist_on_midstep_failure(monkeypatch):
    """계약: run_cycle 은 원자적이지 *않다*. 마지막 단계(critique)가 실패하면 앞 단계
    (node/predict/result) write 는 이미 적용된 채 남고, 예외는 호출자로 전파된다(롤백 없음).
    이것은 *알려진/의도된* 경계 — 숨은 버그가 아니라 문서화된 일관성 모델(KG=truth, ROB-1)."""
    app = load_app()
    calls = []
    _patch_steps(app, monkeypatch, calls, critique_raises=True)
    with pytest.raises(RuntimeError):
        app.run_cycle('T', _cycle(app))
    # 판정까지는 실행됨(부분 write 잔존), critique 에서 폭발
    assert calls == ['node', 'predict', 'result', 'critique']


def test_run_cycle_rerun_after_partial_failure_completes(monkeypatch):
    """복구 경로 = 내구 cycle_result 재사용 후 미완료 critique만 재시도한다."""
    app = load_app()

    # 1차: critique 에서 실패
    calls1 = []
    durable = {}
    _patch_steps(app, monkeypatch, calls1, critique_raises=True, durable=durable)
    with pytest.raises(RuntimeError):
        app.run_cycle('T', _cycle(app))
    assert 'critique' in calls1

    # 2차(재실행): critique 정상 → 완주
    calls2 = []
    _patch_steps(app, monkeypatch, calls2, critique_raises=False, durable=durable)
    out = app.run_cycle('T', _cycle(app))
    assert calls2 == ['critique']
    assert out['verdict'] == 'progressive' and out['critiques'] == 1
    assert out['idempotent'] is True


def test_concurrent_loser_recovers_result_committed_after_initial_preflight(
    monkeypatch,
):
    """초기 miss 뒤 CAS loser가 된 동일 cycle은 false 409 대신 exact receipt를 재사용."""

    app = load_app()
    calls = []
    durable = {}
    _patch_steps(app, monkeypatch, calls, durable=durable)

    real_submit = app.submit_test_result

    def commit_elsewhere_then_conflict(
        n, t, x, *, cycle_claim, cycle_request
    ):
        real_submit(
            n, t, x, cycle_claim=cycle_claim, cycle_request=cycle_request
        )
        raise app.HTTPException(409, "concurrent winner committed")

    monkeypatch.setattr(app, 'submit_test_result', commit_elsewhere_then_conflict)

    out = app.run_cycle('T', _cycle(app))

    assert out['idempotent'] is True
    assert out['verdict'] == 'progressive'
    assert calls == ['node', 'predict', 'result', 'critique']


def test_exact_cycle_replay_preserves_conditional_response_fields(monkeypatch):
    app = load_app()
    durable = {}
    cycle = app.CycleIn(
        tag='e1',
        metric_name='p95',
        baseline=0.5,
        measured=0.4,
        multi_run=True,
        multi_run_values=[0.3, 0.5],
        critiques=[app.CritiqueIn(arg_id='d1', attacks='e1')],
    )

    fresh_calls = []
    _patch_steps(app, monkeypatch, fresh_calls, durable=durable)
    fresh = app.run_cycle('T', cycle)

    replay_calls = []
    _patch_steps(app, monkeypatch, replay_calls, durable=durable)
    replay = app.run_cycle('T', cycle)

    assert replay_calls == ['critique']
    assert replay['multi_run'] == fresh['multi_run']
    assert replay['novel_server_anchored'] is fresh['novel_server_anchored'] is True


def test_node_write_is_merge_based_the_idempotency_foundation():
    """재실행 안전의 구조적 근거: 노드 write 가 MERGE(upsert) 라 같은 tag 재호출이 덮어쓰기로
    수렴한다. CREATE 로 바뀌면 재실행이 깨지므로(=복구 경로 상실) 이 가드가 잡는다."""
    writer_src = (ROOT / 'server/contexts/tree/writer.py').read_text(encoding='utf-8')
    judgement_src = (ROOT / 'server/contexts/tree/judgement_service.py').read_text(encoding='utf-8')
    assert 'MERGE (e:LakatosNode' in writer_src, '노드 write 는 MERGE 여야 재실행 안전(복구 경로)'
    assert 'CREATE (e:LakatosNode' not in writer_src, 'CREATE 는 재실행 시 중복/실패 → 복구 경로 상실'
    # 예측 등록은 SET(멱등 속성 갱신)
    assert 'SET e.pred_metric' in judgement_src, '예측 등록은 SET(멱등) 이어야 재등록 안전'
