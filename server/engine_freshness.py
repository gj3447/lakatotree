"""jp4 판관 자기고유수용감각 provider — 자기신원(stale)·자기능력(capability) 판정 (JP 캠페인 2026-07-10).

라이브 위험의 실체(deep-think 확정): stale CA(1845b4e, 30커밋 뒤)가 stale:true 를 자백하면서도
FORCEFUL 서명 중이었다 — 어떤 write 경로도 staleness 를 안 읽었고, 그 프로세스가 *적재한* certify
에는 G6 자체가 없었다(무능력). 이 모듈이 그 두 축을 판정 dict 로 조립해 judgement_service 가
소비한다(발화 술어는 judgement_policy.engine_freshness_fires — 순수층 분리).

3중 fail-open(dead-σ: 부재≠반증): ① env LAKATOS_JUDGE_FRESHNESS_GATE 미설정 → provider None =
게이트 완전 사체(기존 스위트/KG-less 경로 무변경) ② 무장돼도 sha 미상/git 부재 → stale_code None
= 무발화(단 'indeterminate' 로 관측화 — 침묵 아님) ③ 테스트는 명시 DI 주입으로만 무장.
"""
from __future__ import annotations

import importlib
import os
import sys


def engine_capability(certify_mod=None, policy_mod=None) -> dict:
    """러닝 프로세스 live-object 자기점검 — sys.modules 우선(부팅 코드가 이미 적재한 모듈을 본다;
    디스크 신코드를 새로 import 해 '유능' 오판하는 것을 방지). 문자열 grep 아님(proxy 게임 금지).
    모듈 파라미터는 테스트 주입용(결손 fake 로 무능력 재현)."""
    missing: list[str] = []
    certify = certify_mod or sys.modules.get('lakatos.verdict.certify') \
        or importlib.import_module('lakatos.verdict.certify')
    if not callable(getattr(certify, 'is_measurement_owned', None)):
        missing.append('certify.is_measurement_owned')
    if 'measurement_owned' not in getattr(certify, 'GATES', ()):
        missing.append('certify.GATES:measurement_owned')
    policy = policy_mod or sys.modules.get('server.contexts.tree.judgement_policy') \
        or importlib.import_module('server.contexts.tree.judgement_policy')
    if not callable(getattr(policy, 'resolve_measurement', None)):
        missing.append('judgement_policy.resolve_measurement')
    return {'capable': not missing, 'missing': missing}


def engine_freshness() -> dict:
    """판관 자기진단 dict — {'stale_code': bool|None, 'capable', 'missing', 'boot_git_sha',
    'disk_head_sha'}. stale_code 는 코드경로(lakatos/·server/) 한정 diff(결과-아티팩트/docs 커밋은
    발화 안 함 — 채점 루프 자기차단 회피)."""
    from server.version import BOOT_GIT_SHA, code_paths_changed, disk_head_sha
    disk = disk_head_sha()
    return {'stale_code': code_paths_changed(BOOT_GIT_SHA, disk),
            'boot_git_sha': BOOT_GIT_SHA, 'disk_head_sha': disk,
            **engine_capability()}


def freshness_provider_from_env():
    """env opt-in(LAKATOS_JUDGE_FRESHNESS_GATE — 명시적 boolean, LAKATOS_REPLAY_EXEC 답습).
    미설정/거짓 = None = 게이트 사체. staleness/capability 는 트리 속성이 아니라 *서버 프로세스*
    속성이라 tier 디스패치가 아닌 env 가 정확한 스위치다."""
    on = os.environ.get('LAKATOS_JUDGE_FRESHNESS_GATE', '').strip().lower() in ('1', 'true', 'yes', 'on')
    return engine_freshness if on else None
