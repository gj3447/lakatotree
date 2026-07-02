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
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _patch_steps(app, monkeypatch, calls, *, critique_raises=False):
    """run_cycle 이 오케스트레이션하는 단계 facade 들을 기록용 fake 로 교체.
    (per-call _programme_service() 팩토리가 이 패치를 캡처한다 — test_p5 와 동일 seam.)"""
    monkeypatch.setattr(app, 'add_node', lambda n, x: (calls.append('node'), {'ok': True})[1])
    monkeypatch.setattr(app, 'register_prediction', lambda n, t, x: (calls.append('predict'), {'ok': True})[1])
    monkeypatch.setattr(app, 'submit_test_result',
                        lambda n, t, x: (calls.append('result'),
                                         {'verdict': 'progressive', 'novel': None, 'delta': -0.2})[1])

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
    """복구 경로 = 재실행. 부분 실패 후 다시 호출하면 모든 단계를 재호출해 완주한다 —
    하부 write 가 멱등(MERGE/SET)이라 재실행이 안전하다는 모델의 행동적 증거."""
    app = load_app()

    # 1차: critique 에서 실패
    calls1 = []
    _patch_steps(app, monkeypatch, calls1, critique_raises=True)
    with pytest.raises(RuntimeError):
        app.run_cycle('T', _cycle(app))
    assert 'critique' in calls1

    # 2차(재실행): critique 정상 → 완주
    calls2 = []
    _patch_steps(app, monkeypatch, calls2, critique_raises=False)
    out = app.run_cycle('T', _cycle(app))
    assert calls2 == ['node', 'predict', 'result', 'critique']   # 멱등 단계 재호출로 복구
    assert out['verdict'] == 'progressive' and out['critiques'] == 1


def test_node_write_is_merge_based_the_idempotency_foundation():
    """재실행 안전의 구조적 근거: 노드 write 가 MERGE(upsert) 라 같은 tag 재호출이 덮어쓰기로
    수렴한다. CREATE 로 바뀌면 재실행이 깨지므로(=복구 경로 상실) 이 가드가 잡는다."""
    writer_src = (ROOT / 'server/contexts/tree/writer.py').read_text(encoding='utf-8')
    judgement_src = (ROOT / 'server/contexts/tree/judgement_service.py').read_text(encoding='utf-8')
    assert 'MERGE (e:LakatosNode' in writer_src, '노드 write 는 MERGE 여야 재실행 안전(복구 경로)'
    assert 'CREATE (e:LakatosNode' not in writer_src, 'CREATE 는 재실행 시 중복/실패 → 복구 경로 상실'
    # 예측 등록은 SET(멱등 속성 갱신)
    assert 'SET e.pred_metric' in judgement_src, '예측 등록은 SET(멱등) 이어야 재등록 안전'
