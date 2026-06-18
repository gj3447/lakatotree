"""G-Web + G-WorldAction 강제 게이트 (prom32 finding_06/07/08 + AXIS_gates.md).

prom32 사이클이 PROGRESSIVE_CONDITIONAL 로 남은 이유 = "automated G-Web/G-WorldAction 게이트가
코드로 증명될 때까지". InternetObservation/BashAct 모델은 있었으나 *게이트로 강제*되지 않았다
(런타임은 generic ResearchEvent payload 로 우회). 본 모듈이 그 둘을 enforced gate 로 만든다.

  G-Web         : 인터넷 fetch 증거 = url/retrieved_at/content_hash|snapshot/source_type/trust/
                  injection-scan/lakatos-location 전수 (finding_01/07, AXIS_gates G-Web)
  G-WorldAction : bash 실행 증거 = command/cwd/exit_code/stdout|stderr (+git_diff) (finding_06)
  injection scan: 인터넷 content 의 프롬프트 인젝션/exfiltration 휴리스틱 (finding_07 F07)
# KG: span_lakatotree_world_gates / Doctrine_InternetFirst_RequestSecond_ReasonJoyThird_20260612
"""
import re

from lakatos.engine import GateResult, BashAct, LAKATOS_LOCATIONS

# ── F07: 프롬프트 인젝션/exfiltration 휴리스틱 시그널 ──────────────────────────
_INJECTION_PATTERNS = [
    (r'ignore\s+(all\s+|the\s+)?(previous|above|prior|earlier)\s+instructions', 'ignore_previous'),
    (r'disregard\s+(all\s+|the\s+)?.{0,20}(instruction|rule|system|prompt)', 'disregard'),
    (r'you\s+are\s+now\s+', 'role_override'),
    (r'(reveal|print|show|leak|exfiltrat|send|email|upload).{0,30}(secret|api[\s_-]?key|password|token|credential|\.env)', 'exfiltration'),
    (r'<\s*/?\s*(system|assistant|tool|im_start|im_end)\s*>', 'role_tag_injection'),
    (r'(^|\s)(sudo\s|rm\s+-rf\s|curl\s+.{0,80}\|\s*(sh|bash))', 'tool_misuse'),
    (r'do\s+not\s+(tell|inform|mention|reveal).{0,20}(user|human|operator)', 'concealment'),
    (r'new\s+(instruction|task|directive)s?\s*:', 'instruction_injection'),
]


_ZERO_WIDTH = re.compile('[​-‏‪-‮﻿]')   # zero-width/방향제어 문자


# KG: rs-wg-scan-injection (Longinus ReferenceSite) — prom32 F07
def scan_prompt_injection(text: str) -> dict:
    """인터넷 content 의 프롬프트 인젝션/exfiltration 위험 *휴리스틱* (F07).

    반환 {scanned: True, signals: [...], risk: [0,1]}. risk = min(1, 0.34×시그널 수).
    risk 는 add_observation 에서 그 증거의 confidence 를 derate(trust×(1−risk))해 claim-standing 에
    실제 반영된다(엔진 SourceCredibilityScore.injection_penalty 는 별도 참조모델).

    ★정직 한계(나생문): 정규식 휴리스틱은 *바닥선*이지 보증이 아니다 — word-splitting('ig nore'),
    심한 난독화는 놓칠 수 있다(false negative). 그래서 차단이 아닌 risk 부착 + confidence derate 로
    설계(상계는 untrusted, 숨기지 말고 표시). 고위험 content 의 최종 수용은 인간판정(G-Human) 몫.
    전처리로 zero-width/과다공백 정규화해 사소한 회피만 차단.
    """
    t = _ZERO_WIDTH.sub('', (text or '').lower())
    t = re.sub(r'[ \t]{2,}', ' ', t)
    signals = sorted({name for pat, name in _INJECTION_PATTERNS if re.search(pat, t)})
    return {'scanned': True, 'signals': signals, 'risk': round(min(1.0, 0.34 * len(signals)), 3)}


# ── G-Web: 인터넷 fetch 게이트 ───────────────────────────────────────────────
# G-Trust: 신뢰는 *분해된* 성분이어야("단일 최종 점수는 不可", AXIS_gates G-Trust).
# ★나생문: bare 'trust' 는 분해 성분이 아님(제외) — 분해 성분 중 1+ 가 *양수*여야(present+nonzero).
_CREDIBILITY_KEYS = ('link_authority', 'source_class_weight', 'primary_source_bonus',
                     'provenance_score', 'corroboration_score', 'recency_score', 'supply_chain_score')


# KG: rs-wg-web-gate (Longinus ReferenceSite) — prom32 G-Web
def web_gate(obs: dict, *, injection: dict | None = None) -> GateResult:
    """G-Web: 인터넷 fetch 증거가 승격 자격을 갖췄나 (AXIS_gates G-Web 전수).

    obs 필수: url, retrieved_at, (content_hash | raw_snapshot_path), source_type,
              trust 성분(trust 또는 link_authority), lakatos_location ∈ LAKATOS_LOCATIONS.
    injection: scan_prompt_injection 결과(scanned=True 필수) — 미스캔 = 미통과.
    """
    miss: list[str] = []
    if not obs.get('url'):
        miss.append('url')
    if not obs.get('retrieved_at'):
        miss.append('retrieved_at')
    if not (obs.get('content_hash') or obs.get('raw_snapshot_path')):
        miss.append('content_hash_or_snapshot')
    if not obs.get('source_type'):
        miss.append('source_type')
    if not any(obs.get(k) for k in _CREDIBILITY_KEYS):   # 양수 성분 1+ (all-None/all-zero 거부)
        miss.append('trust_components')
    if not (injection and injection.get('scanned')):
        miss.append('injection_scan')
    if obs.get('lakatos_location') not in LAKATOS_LOCATIONS:
        miss.append('lakatos_location')
    return GateResult.fail(miss) if miss else GateResult.pass_()


# ── G-WorldAction: bash 실행 게이트 ──────────────────────────────────────────
# KG: rs-wg-world-action-gate (Longinus ReferenceSite) — prom32 G-WorldAction
def world_action_gate(act: dict, *, require_git_diff: bool = False) -> GateResult:
    """G-WorldAction: bash 실행이 증거 자격을 갖췄나 (finding_06).

    BashAct.evidence_ready 를 dict 입력으로 강제 — command/cwd/exit_code/stdout|stderr 필수.
    require_git_diff=True 면 git_diff_hash(=git_sha) 도 요구(코드 영향 명령).
    """
    ba = BashAct(
        name=act.get('name', 'world_action'),
        command=act.get('command', '') or '',
        cwd=act.get('cwd', '') or '',
        exit_code=act.get('exit_code'),
        stdout_summary=act.get('stdout_summary', '') or '',
        stderr_summary=act.get('stderr_summary', '') or '',
        touched_files=tuple(act.get('touched_files') or ()),
        git_sha=act.get('git_diff_hash') or act.get('git_sha'),
    )
    return ba.evidence_ready(require_git_sha=require_git_diff)
