"""판관 정체성(engine_rule_sha) SSOT — jp1 (JP 캠페인 LakatosTree_JudgeProprioception_20260708).

'재유도가 판관, 캐시 불신'을 엔진 *자신*에게 적용하는 첫 조각: 판결 규칙 표면의 내용주소를
계산해, 영수증(v2)·인증서가 "어느 판관이 이 verdict 를 찍었나"를 봉인할 수 있게 한다.
이게 없으면 '오늘 엔진이면 이걸 여전히 progressive 라 부를까?'가 원장 수준에서 답 불가
(통시적 자기정체성 부재 = unreadable green).

정의: engine_rule_sha = sha256('engine-rule\\x00v1\\n' + JCS({relpath: sha256(file bytes)}))
  - RULE_SURFACE = lakatos/verdicts.py + lakatos/verdict/*.py 전수(정렬, 디렉토리 규칙) —
    hand-list rot 방지: 신규 규칙 파일이 자동 포함된다(누락보다 과포함이 보수적).
  - server 층(judgement_policy 등) 의도적 제외: lakatos base 는 pip-설치 stdlib-only 로
    단독 계산 가능해야 한다(패키징 경계 2ee0433). server 층 stale 위험은 jp4 축이 담당.
    한계 명기: FF1 서버 정책 변경은 engine_rule_sha 를 안 바꾼다.
  - ENGINE_RULE_SHA = import 시점 1회 스냅샷(server/version.py BOOT_GIT_SHA 규율 동형 —
    재유도 금지: '이 프로세스의 판관이 누구인가'의 참값). current_engine_rule_sha() 는
    매호출 disk 재유도(스냅샷 대조로 규칙-코드 stale 검출).

정직 floor(스윕 소비): docs/engine_rule_floor.json 의 선언 sha 집합(git-tracked, 사람 검토
커밋으로만 등재 — KG 저장은 R6 확정결정대로 기각: writer 셀프등재 자기면제 구멍) ∪
{현 ENGINE_RULE_SHA}. sha ∉ floor(v1 legacy 의 필드 부재 포함) = floor 이하. 집행(강등)은
서버 opt-in verb 의 몫 — 이 모듈은 순수 계산만(IO=파일 읽기, KG/네트워크 0).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent          # lakatos/
_SURFACE_DIR = _PKG_ROOT / 'verdict'
_ENCODING_HEADER = b'engine-rule\x00v1\n'
_FLOOR_ENV = 'LAKATOS_ENGINE_RULE_FLOOR'
_FLOOR_DEFAULT = _PKG_ROOT.parent / 'docs' / 'engine_rule_floor.json'


def rule_surface_manifest() -> dict[str, str]:
    """판결 규칙 표면의 {relpath: sha256(bytes)} — 정렬·결정론. 디렉토리 규칙이라 신규 규칙 파일 자동 포함."""
    files = sorted([_PKG_ROOT / 'verdicts.py', *_SURFACE_DIR.glob('*.py')])
    return {p.relative_to(_PKG_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files if p.name != '__pycache__'}


def compute_engine_rule_sha(manifest: dict[str, str]) -> str:
    """manifest → 내용주소(full 64-hex). JCS(sorted·compact) — receipt blob 과 같은 json 규율."""
    body = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(_ENCODING_HEADER + body.encode('utf-8')).hexdigest()


# ── import 시점 1회 스냅샷 — 재유도 금지(BOOT_GIT_SHA 동형): 이 프로세스의 판관 정체성 참값 ──
ENGINE_RULE_SHA: str = compute_engine_rule_sha(rule_surface_manifest())


def current_engine_rule_sha() -> str:
    """매호출 disk 재유도 — ENGINE_RULE_SHA(스냅샷)와 다르면 규칙 코드가 부팅 후 변경됨(stale 판관)."""
    return compute_engine_rule_sha(rule_surface_manifest())


def load_rule_floor(path: str | None = None) -> set[str]:
    """docs/engine_rule_floor.json 의 선언 sha 집합. 부재/부패 = 선언분 0 (fsck load_skiplist 동형 —
    floor 는 항상 effective_floor() 에서 현 ENGINE_RULE_SHA 와 합쳐지므로 부트스트랩 가능)."""
    p = Path(path or os.environ.get(_FLOOR_ENV) or _FLOOR_DEFAULT)
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return {str(e['sha']) for e in data.get('entries', [])
                if isinstance(e, dict) and e.get('sha')}
    except (OSError, ValueError, TypeError, KeyError):
        return set()


def effective_floor(path: str | None = None) -> set[str]:
    """유효 floor = 선언 집합 ∪ {현 ENGINE_RULE_SHA} — 현 규칙이 floor 메커니즘 자체를 포함하므로 자명."""
    return load_rule_floor(path) | {ENGINE_RULE_SHA}
