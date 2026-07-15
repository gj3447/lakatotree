"""PROM16 루프-경계 가드 — bash 벽시계 timeout · CLI 타입경계 · 트리별 사이클 예산.

라카토스 사이클은 run_cycle 한 번이 결정론적 1-pass 이고, 다회 루프는 *외부*(agent/스크립트)가 돈다.
그 경계에 PROM16 하네스/루프 표준(THEORY/harness_loop_engineering)의 3 결손이 있었다:

  GAP-3 (S3)  bash 벽시계 timeout 이 하드코딩 600 이고 TimeoutExpired 가 *생 예외*로 샜다
              → 이제 LAKATOTREE_BASH_TIMEOUT(기본 600) + 타입 실패(BashTimeout).
  FIX-A       CLI 'cycle' verb 가 harness_run.main 을 *직접* 불러 BuildFailed/ScoringRefused/
              BashTimeout 이 생 스택트레이스로 터졌다(문서가 bash 사용자를 보내는 바로 그 표면)
              → run_typed 타입경계 경유. 성공경로는 거동 동일(prov JSON + exit 0).
  FIX-C       LAKATOTREE_BASH_TIMEOUT 자체가 오염되면(빈값/문자/0/음수) int() 가 _bash 안에서
              생 ValueError 로 터졌다 = 가드가 스스로 무타입 크래시 → 타입 config_error 로 거부.
  GAP-1 (S1/S5) 트리별 사이클 예산 — 내구(저장된 채점노드 count 로 파생, 인메모리 카운터 아님).

각 가드는 양방향(발화 + 정상경로 무영향)으로 못 박는다. revert-민감: 가드를 떼면 RED.
# KG: span_lakatotree_harness / span_lakatotree_engine
"""
from __future__ import annotations

import json
import subprocess

import pytest

from lakatos import harness_run
from lakatos.harness import BashConfigError, BashTimeout, BuildFailed


# ── GAP-3 / FIX-C: bash 벽시계 timeout 과 그 설정값 파싱 ────────────────────────────────

def test_bash_timeout_default_is_600_and_env_overrides(monkeypatch):
    """정상경로: env 미설정=600(기존 하드코딩과 동일 = 비파괴), 설정 시 그 값이 subprocess 로 관통."""
    monkeypatch.delenv('LAKATOTREE_BASH_TIMEOUT', raising=False)
    assert harness_run._bash_timeout() == 600      # 기본값 = 종전 하드코딩과 동일

    monkeypatch.setenv('LAKATOTREE_BASH_TIMEOUT', '')
    assert harness_run._bash_timeout() == 600, "빈 env(`FOO=`)는 쉘 관용상 *미설정* — 기본값"

    monkeypatch.setenv('LAKATOTREE_BASH_TIMEOUT', '12')
    assert harness_run._bash_timeout() == 12

    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='metric=1', stderr='')

    monkeypatch.setattr(harness_run.subprocess, 'run', fake_run)
    harness_run._bash('echo hi')
    assert seen['timeout'] == 12, '설정된 벽시계 예산이 subprocess 까지 관통하지 않음'


def test_bash_timeout_expiry_is_typed_not_bare(monkeypatch):
    """발화: 벽시계 초과는 *타입* 실패(BashTimeout) — 생 TimeoutExpired 가 루프 종단이 되면 안 된다."""
    monkeypatch.setenv('LAKATOTREE_BASH_TIMEOUT', '5')

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])

    monkeypatch.setattr(harness_run.subprocess, 'run', fake_run)
    with pytest.raises(BashTimeout) as e:
        harness_run._bash('sleep 999')
    assert '5' in str(e.value)   # 초과한 예산을 증거로 남긴다


@pytest.mark.parametrize('bad', ['abc', '0', '-1', '1.5', ' '])
def test_bash_timeout_malformed_env_is_typed_config_error(monkeypatch, bad):
    """FIX-C 발화: 오염된 env 가 _bash 안에서 무타입 ValueError 로 터지면 안 된다(가드의 자멸).

    fail-closed 선택: *선언됐지만 뜻이 부정한* 값을 조용히 600 으로 되돌리면 운영자가 선언한
    경계를 무음 무시하는 우회가 된다(빈 문자열=미설정과 구분 — 위 기본값 테스트 참조).
    """
    monkeypatch.setenv('LAKATOTREE_BASH_TIMEOUT', bad)
    with pytest.raises(BashConfigError):
        harness_run._bash_timeout()


# ── FIX-A: CLI 'cycle' 표면의 타입 종단 ──────────────────────────────────────────────

def _spec(tmp_path, **over) -> str:
    spec = dict(tree='T', tag='exp1', parent='root', metric='p95', baseline=0.5,
                judge_cmd='echo metric=0.3')
    spec.update(over)
    p = tmp_path / 'spec.json'
    p.write_text(json.dumps(spec))
    return str(p)


def _wire(monkeypatch, bash=('metric=0.3', 0)):
    monkeypatch.setattr(harness_run, '_http', lambda m, p, b=None: {
        'verdict': 'progressive', 'novel': None, 'delta': -0.2})
    monkeypatch.setattr(harness_run, '_bash', lambda cmd: bash)
    monkeypatch.setattr(harness_run, '_git_sha', lambda: 'abc1234')


def test_cli_cycle_build_failure_is_typed_terminal_not_traceback(tmp_path, monkeypatch, capsys):
    """FIX-A 발화: 실패 spec 으로 CLI 'cycle' 을 몰면 *타입 종단*(SystemExit + status 코드)이지
    생 BuildFailed 스택트레이스가 아니다 — mcp_server 가 bash 사용자를 보내는 문서화된 표면."""
    from lakatos import cli

    _wire(monkeypatch, bash=('boom', 1))
    with pytest.raises(SystemExit) as e:
        cli.main(['cycle', _spec(tmp_path, build_cmd='make')])
    assert e.value.code != 0, '실패 사이클이 exit 0(가짜 green)으로 끝남'
    err = capsys.readouterr().err
    assert json.loads(err.strip().splitlines()[-1])['status'] == 'build_failed'
    assert 'Traceback' not in err


def test_cli_cycle_timeout_is_typed_terminal(tmp_path, monkeypatch, capsys):
    """벽시계 초과도 CLI 표면에서 타입 종단으로 — 루프 드라이버가 이유코드로 분기할 수 있어야."""
    from lakatos import cli

    _wire(monkeypatch)

    def boom(cmd):
        raise BashTimeout('벽시계 예산 5s 초과')

    monkeypatch.setattr(harness_run, '_bash', boom)
    with pytest.raises(SystemExit) as e:
        cli.main(['cycle', _spec(tmp_path, build_cmd='make')])
    assert e.value.code != 0
    assert json.loads(capsys.readouterr().err.strip().splitlines()[-1])['status'] == 'timeout'


def test_cli_cycle_success_path_unchanged(tmp_path, monkeypatch, capsys):
    """정상경로 무영향(비파괴 회귀): 성공 사이클은 여전히 prov JSON 을 stdout 에 찍고 exit 0."""
    from lakatos import cli

    _wire(monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.main(['cycle', _spec(tmp_path)])
    assert e.value.code == 0, '성공 사이클이 0 으로 안 끝남(거동 변경)'
    out = json.loads(capsys.readouterr().out)
    assert out['verdict'] == 'progressive' and out['metric'] == 0.3


def test_engine_exceptions_stay_intact_for_library_callers(tmp_path, monkeypatch):
    """라이브러리 호출자 계약 보존: main() 은 여전히 *엔진 예외*를 raise 한다(타입화는 CLI 경계에서만).
    run_typed 가 main 을 삼키는 게 아니라 *감싸는* 것임을 못 박음."""
    _wire(monkeypatch, bash=('boom', 1))
    with pytest.raises(BuildFailed):
        harness_run.main(_spec(tmp_path, build_cmd='make'))
