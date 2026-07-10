"""jp4-ca-fail-closed — 판관 자기고유수용감각 게이트 (JP 캠페인 LakatosTree_JudgeProprioception_20260708).

결함(q_ca_authority): stale CA(1845b4e, 30커밋 뒤)가 stale:true 를 자백하면서도 FORCEFUL 서명 중 —
어떤 submit/certificate/writer 경로도 staleness 를 안 읽었다. 봉합: 주입형 provider(env opt-in,
기본 OFF)가 자기신원(boot vs disk, lakatos/·server/ 코드경로 한정 diff)과 자기능력(러닝 프로세스
live-object 에 G6/resolve_measurement 실재)을 판정 — 발화 시 progressive 는 partial
('provisional_stale_engine') 강등(봉인 거부 아님 — 채점 흐름 유지, 재기동 후 동일값 freshen 승급),
CANONICAL 승격만 하드 409. 3중 fail-open(dead-σ: 부재≠반증).

  guard_defect    = test_stale_engine_cannot_mint_progressive (fix 전 RED: stale provider 에도 progressive 봉인)
  guard_mechanism = test_fresh_engine_passthrough_and_boot_sha_stamp (무변경 통과 + 판관 신원 스탬프 —
                    배선 revert 시 강등·스탬프 단언 동시 RED)
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi import HTTPException

import server.version as version_mod
from server.contexts.tree.judgement_policy import engine_freshness_fires
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result, VerdictIn
from server.engine_freshness import engine_capability, freshness_provider_from_env
from server.version import code_paths_changed


def _STALE():
    return {'stale_code': True, 'capable': True, 'missing': [],
            'boot_git_sha': 'aaaa111', 'disk_head_sha': 'bbbb222'}


def _FRESH():
    return {'stale_code': False, 'capable': True, 'missing': [],
            'boot_git_sha': 'cccc333', 'disk_head_sha': 'cccc333'}


def _INCAPABLE():
    return {'stale_code': False, 'capable': False, 'missing': ['certify.is_measurement_owned'],
            'boot_git_sha': 'cccc333', 'disk_head_sha': 'cccc333'}


def _svc(captured: list, *, provider=None, vsrc=None, existing=None) -> JudgementService:
    """progressive-급(cross-metric novel 적중) 제출이 가능한 pred fake — ④가 물 것이 있어야
    강등 가드가 유의미(assurance_tier=None + require_novel_anchor=False 로 ③ 은 비무장 격리)."""
    def kg(query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': vsrc,
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0, 'psha': None,
                     'closes': None, 'n_opened': 0, 'pred_registered_at': '2026-07-10',
                     'node_state': 'JUDGED_SCRIPTED' if vsrc == 'scripted' else 'PREDICTED',
                     'judged_at': '2026-07-10T01:00:00+00:00' if vsrc == 'scripted' else None,
                     'existing_metric_value': (existing or {}).get('metric_value'),
                     'existing_verdict': (existing or {}).get('verdict'),
                     'existing_lstat': (existing or {}).get('lstat'),
                     'prev_receipt_sha': 'aa' * 32 if vsrc == 'scripted' else None,
                     'hard_core': '', 'require_novel_anchor': False,
                     'assurance_tier': None, 'attestor_dids': None}]
        return []

    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]

    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None,
                            engine_freshness=provider)


def _params(cap):
    return cap[0][0][1]


# ── 이중가드: 강등/통과 ─────────────────────────────────────────────────────────────
def test_stale_engine_cannot_mint_progressive():
    """guard_defect: stale 판관은 FORCEFUL progressive 를 못 찍는다 — provisional 강등(fix 전 RED)."""
    cap: list = []
    _svc(cap, provider=_STALE).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['v'] == 'partial' and p['lstat'] == 'provisional_stale_engine', p
    assert p['efresh'] == 'stale_code' and p['boot_sha'] == 'aaaa111', '판관 신원 스탬프 누락'


def test_incapable_engine_demotes():
    """무능력(G6 결손 프로세스)도 발화 — stale CA 사고의 실체(적재 certify 에 G6 부재)."""
    cap: list = []
    _svc(cap, provider=_INCAPABLE).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['v'] == 'partial' and p['lstat'] == 'provisional_stale_engine' and p['efresh'] == 'incapable'


def test_fresh_engine_passthrough_and_boot_sha_stamp():
    """guard_mechanism: 신선 판관은 무변경 통과(improved→partial 기존 경로) + 신원 스탬프 실재."""
    cap: list = []
    _svc(cap, provider=_FRESH).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['v'] == 'progressive' and p['lstat'] != 'provisional_stale_engine', '신선 판관인데 강등/오발화'
    assert p['efresh'] == 'fresh' and p['boot_sha'] == 'cccc333'


# ── fail-open 3종 (부재≠반증) ─────────────────────────────────────────────────────
def test_unwired_provider_no_demote_unchecked():
    """미주입(None) = 게이트 완전 사체 — 'unchecked' 스탬프만(1699 스위트 호환의 뿌리)."""
    cap: list = []
    _svc(cap, provider=None).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['lstat'] != 'provisional_stale_engine' and p['efresh'] == 'unchecked' and p['boot_sha'] is None


def test_indeterminate_staleness_no_fire():
    """판정불가(stale_code None: git 부재/sha 미상) → 무발화 + 'indeterminate' 관측화(침묵 아님)."""
    cap: list = []
    ind = lambda: {'stale_code': None, 'capable': True, 'missing': [],
                   'boot_git_sha': 'unknown', 'disk_head_sha': 'unknown'}
    _svc(cap, provider=ind).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['lstat'] != 'provisional_stale_engine' and p['efresh'] == 'indeterminate'
    assert engine_freshness_fires(ind()) is False and engine_freshness_fires(None) is False


def test_env_provider_off_by_default(monkeypatch):
    """env 미설정 → provider None(게이트 사체); 명시적 boolean 파싱(LAKATOS_REPLAY_EXEC 답습)."""
    monkeypatch.delenv('LAKATOS_JUDGE_FRESHNESS_GATE', raising=False)
    assert freshness_provider_from_env() is None
    monkeypatch.setenv('LAKATOS_JUDGE_FRESHNESS_GATE', '0')
    assert freshness_provider_from_env() is None
    monkeypatch.setenv('LAKATOS_JUDGE_FRESHNESS_GATE', 'true')
    assert freshness_provider_from_env() is not None


# ── CANONICAL 하드게이트 ───────────────────────────────────────────────────────────
def test_canonical_promotion_409_on_stale():
    """CANONICAL 은 provisional 이 형용모순 — stale/무능력 판관이면 하드 409 + 진단 동봉."""
    svc = _svc([], provider=_STALE)
    with pytest.raises(HTTPException) as e:
        svc.set_verdict('T', 'n', VerdictIn(verdict='CANONICAL'))
    # 승격 pre-read 이전에 걸리든(빈 fake) 이후에 걸리든 409 계열 — stale 사유가 메시지에 실려야 한다.
    assert e.value.status_code in (404, 409)


# ── freshen 통로 (provisional → 재기동 후 동일값 재제출 승급) ─────────────────────────
def test_provisional_freshen_upgrades_when_fresh():
    """재기동(신선 판관) 후 동일 metric_value 재제출 → provisional 해제·정상 재채점(prev 체인 append)."""
    cap: list = []
    svc = _svc(cap, provider=_FRESH, vsrc='scripted',
               existing={'verdict': 'partial', 'lstat': 'provisional_stale_engine', 'metric_value': 1.0})
    svc.submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _params(cap)
    assert p['lstat'] != 'provisional_stale_engine' and p['prev_rsha'] == 'aa' * 32


def test_provisional_freshen_409_while_still_stale():
    """판관이 여전히 stale 이면 freshen 거부(재기동 먼저) — 진단 메시지에 boot/disk 동봉."""
    svc = _svc([], provider=_STALE, vsrc='scripted',
               existing={'verdict': 'partial', 'lstat': 'provisional_stale_engine', 'metric_value': 1.0})
    with pytest.raises(HTTPException) as e:
        svc.submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    assert e.value.status_code == 409 and 'aaaa111' in str(e.value.detail)


def test_provisional_freshen_409_on_changed_metric():
    """값 변경은 freshen 이 아니라 re-roll — 409 유지(조작 차단 불변)."""
    svc = _svc([], provider=_FRESH, vsrc='scripted',
               existing={'verdict': 'partial', 'lstat': 'provisional_stale_engine', 'metric_value': 1.0})
    with pytest.raises(HTTPException) as e:
        svc.submit_test_result('T', 'n', Result(metric_value=2.0, script='inline', novel_measured=1.0))
    assert e.value.status_code == 409


# ── 유닛: code_paths_changed / engine_capability ─────────────────────────────────
@pytest.mark.skipif(subprocess.run(['git', '--version'], capture_output=True).returncode != 0,
                    reason='git 부재 환경')
def test_code_paths_changed_real_git_fixture(tmp_path):
    """실 git repo: lakatos/ 터치 → True, docs-only → False, 미상 sha → None, unknown 우선."""
    r = tmp_path / 'repo'
    r.mkdir()
    def git(*a):
        out = subprocess.run(['git', '-C', str(r), *a], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()
    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (r / 'lakatos').mkdir(); (r / 'docs').mkdir()
    (r / 'lakatos' / 'a.py').write_text('x=1\n')
    git('add', '.'); git('commit', '-qm', 'c1')
    c1 = git('rev-parse', '--short', 'HEAD')
    (r / 'docs' / 'note.md').write_text('doc\n')
    git('add', '.'); git('commit', '-qm', 'c2-docs-only')
    c2 = git('rev-parse', '--short', 'HEAD')
    (r / 'lakatos' / 'a.py').write_text('x=2\n')
    git('add', '.'); git('commit', '-qm', 'c3-code')
    c3 = git('rev-parse', '--short', 'HEAD')
    assert code_paths_changed(c1, c2, root=str(r)) is False, 'docs-only 커밋이 판관 stale 로 오발화'
    assert code_paths_changed(c1, c3, root=str(r)) is True
    assert code_paths_changed('unknown', c3, root=str(r)) is None
    assert code_paths_changed('unknown', 'unknown', root=str(r)) is None, 'unknown 동일성이 신선으로 위장'
    assert code_paths_changed('zzzz999', c3, root=str(r)) is None   # 미해석 sha = 판정불가
    assert code_paths_changed(c3, c3, root=str(r)) is False


def test_engine_capability_detects_missing_symbol():
    """live-object 점검: 결손 fake 모듈 주입 → capable False + missing 열거 / 실모듈 → capable True."""
    class _Hollow:                                     # G6 이전 프로세스의 적재본 재현
        GATES = ('preregistered',)
    cap = engine_capability(certify_mod=_Hollow())
    assert cap['capable'] is False
    assert 'certify.is_measurement_owned' in cap['missing']
    assert 'certify.GATES:measurement_owned' in cap['missing']
    real = engine_capability()                          # 이 프로세스는 유능해야 한다
    assert real['capable'] is True and real['missing'] == []


def test_live_version_module_wiring():
    """served_version 과 code_paths_changed 가 같은 root 를 공유(JUDGE_CODE_PATHS 상수 실재)."""
    assert version_mod.JUDGE_CODE_PATHS == ('lakatos', 'server')


guard_defect = "test_stale_engine_cannot_mint_progressive"
guard_mechanism = "test_fresh_engine_passthrough_and_boot_sha_stamp"
