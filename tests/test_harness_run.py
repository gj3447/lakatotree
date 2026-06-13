"""Cluster ② — 하네스 실행기(harness_run, 프로덕션 진입점) 스모크 (나생천 GAP-T2-01/ROB-8).

harness_run.py 는 0% 커버리지였다(실 HTTP/bash/git 포트 한 번도 미실행). 포트 주입으로
한 사이클(상계→하계 build/judge→test_result→standing)과 build-fail 게이트를 검증.
"""
import json

import pytest

from lakatos import harness_run
from lakatos.harness import BuildFailed


def _spec(tmp_path, **over):
    spec = dict(tree='T', tag='exp1', parent='root', metric='p95', baseline=0.5,
                judge_cmd='echo metric=0.3')
    spec.update(over)
    p = tmp_path / 'spec.json'
    p.write_text(json.dumps(spec))
    return str(p)


def _wire(monkeypatch, bash=('metric=0.3', 0)):
    calls = []

    def fake_http(method, path, body=None):
        calls.append((method, path))
        return {'verdict': 'progressive', 'novel': None, 'delta': -0.2, 'grounded_extension': []}

    monkeypatch.setattr(harness_run, '_http', fake_http)
    monkeypatch.setattr(harness_run, '_bash', lambda cmd: bash)
    monkeypatch.setattr(harness_run, '_git_sha', lambda: 'abc1234')
    return calls


def test_harness_run_full_cycle(tmp_path, monkeypatch, capsys):
    calls = _wire(monkeypatch)
    harness_run.main(_spec(tmp_path))
    out = json.loads(capsys.readouterr().out)
    assert out['verdict'] == 'progressive'
    assert out['metric'] == 0.3
    posts = [p for mth, p in calls if mth == 'POST']
    assert any(p.endswith('/node') for p in posts)          # 하계 write: 노드 생성
    assert any('test_result' in p for p in posts)           # 하계 write: 판결 제출
    assert out['git_sha'] == 'abc1234'                       # 이력관리: git sha 관통


def test_harness_run_build_fail_gate(tmp_path, monkeypatch):
    _wire(monkeypatch, bash=('boom', 1))                     # 하계 ground-truth 게이트 실패
    spec = _spec(tmp_path, build_cmd='make')
    with pytest.raises(BuildFailed):
        harness_run.main(spec)                               # 빌드 실패면 채점·판결 중단
