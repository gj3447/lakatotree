"""인증층 — P2: '이 claim 은 어디까지 믿어도 되는가'를 게이트 전수 통과로만 답한다.

인증서(Certificate)는 칭찬이 아니라 **검증가능 계보의 묶음**이다. LLM 의견 0,
순수함수 체크 6개의 AND — 하나라도 빠지면 인증 거부 + 빠진 게이트와 다음 행동 명시:

  G1 preregistered    : 사전등록 예측 + scripted 판결 존재 (judge — 사후 합리화 차단)
  G2 reproducible     : DatasetManifest 가 G-RebuildFromRaw 통과 (lineage — raw root 서 재생성)
  G3 stands           : 판결이 Dung grounded extension 에 섬 (argue — 미해소 의문 없음)
  G4 calibrated       : 트리(발급자) 수준 보정 기록 존재 (calibrate — novel 등록 예측의 Brier/ECE, *노드별 아님*)
  G5 grounded         : 인용 상수의 tier 공개 (grounding — 문헌값/정책값 구분 동봉)
  G6 measurement_owned: 측정값이 client float 봉인이 아님 — 서버 재유도(server_regenerated, 값소유) 또는
                        attested(allow-list 신원 서명). AG3~5 measurement_grade 사다리에 *이빨*을 준다:
                        client_asserted(무replay·무서명) 값은 인증 불가. 측정값 없는 노드(질적/problem)는
                        측정소유가 무의미하므로 자동통과(SCOPED — 측정을 *근거로 든* claim 에만 적용).

인증은 시점 스냅샷이다 — evidence_window 에 박힌 sha/시각 밖에선 효력 주장 안 함
(CANONICAL 이 '임시 현재 최선'인 것과 동형). 철회는 새 반박 증거가 G3(stands)를 깨면 자동:
evidence_claim_service.add_critique → spine.reconcile_standing 가 grounded standing 이 깨진
CANONICAL 을 former_canonical 로 강등(verdict_source='engine', valid_until_rebutted 잠금 존중).
# KG: span_lakatotree_certify / P2
"""
from dataclasses import dataclass, field

GATES = ('preregistered', 'reproducible', 'stands', 'calibrated', 'grounded', 'measurement_owned')

# G6 값소유 등급(AG3~5 measurement_grade 사다리)이 인증을 *지탱*하는 등급.
OWNED_GRADES = ('server_regenerated', 'attested')


def is_measurement_owned(grade, has_metric: bool) -> bool:
    """G6 술어 (순수) — 측정을 *근거로 든* claim(has_metric)은 값이 소유돼야 인증가능:
    server_regenerated(서버 replay 재유도=값소유) 또는 attested(allow-list 신원 서명).
    측정값 없는 노드(질적/problem)는 측정소유가 무의미 → 자동 소유(SCOPED, 무회귀).
    client_asserted / None grade + 측정근거 → 미소유(무replay·무서명 float 는 인증 못 받음)."""
    return (not has_metric) or (grade in OWNED_GRADES)


@dataclass(frozen=True)
class GateCheck:
    gate: str
    passed: bool
    evidence_ref: str      # 통과 근거 포인터 (manifest path / verdict id / 보정표 등)
    note: str = ''


@dataclass(frozen=True)
class Certificate:
    claim_id: str
    certified: bool
    checks: tuple                 # (GateCheck, ...) — 전 게이트 공개 (부분 통과도 보임)
    missing: tuple                # 미통과 게이트 이름들
    evidence_window: dict         # {'as_of': ..., 'shas': {...}} — 시점 스냅샷 한계 명시
    limits: str = ('인증은 evidence_window 시점의 검증가능 계보 묶음 — 새 반박 증거가 '
                   'standing 을 깨면 효력 상실 (절대 보증 아님)')


def gate_check(gate: str, passed: bool, evidence_ref: str, note: str = '') -> GateCheck:
    if gate not in GATES:
        raise ValueError(f'미등록 게이트 {gate!r} — GATES {GATES} 만 (어휘 단일화)')
    if passed and not evidence_ref:
        raise ValueError(f'{gate}: 통과 주장에 evidence_ref 없음 — 근거 없는 PASS 금지 (고무도장 차단)')
    return GateCheck(gate=gate, passed=passed, evidence_ref=evidence_ref, note=note)


def certify_claim(claim_id: str, checks: list, evidence_window: dict) -> Certificate:
    """게이트 전수 AND — 5게이트 모두 제출·통과해야 인증. 누락 게이트 = 미통과로 집계.

    부분 통과를 숨기지 않는다: checks 에 제출된 전부 + missing 에 빠진 전부가 남는다.
    """
    by_gate = {}
    for c in checks:
        if c.gate in by_gate:
            raise ValueError(f'게이트 {c.gate} 중복 제출 — 체크 1게이트 1회 (유리한 쪽 고르기 차단)')
        by_gate[c.gate] = c
    missing = tuple(g for g in GATES if g not in by_gate or not by_gate[g].passed)
    if 'as_of' not in evidence_window:
        raise ValueError("evidence_window 에 'as_of' 필수 — 시점 없는 인증은 절대 보증으로 오독됨")
    return Certificate(
        claim_id=claim_id,
        certified=not missing,
        checks=tuple(by_gate.get(g) or GateCheck(g, False, '', '미제출') for g in GATES),
        missing=missing,
        evidence_window=dict(evidence_window),
    )


def next_actions(cert: Certificate) -> list:
    """미통과 게이트 → 기계 판독형 다음 행동 (claim-standing.next_actions 동형)."""
    todo = {
        'preregistered': '예측 사전등록 후 스크립트 채점 (judge.Prediction → judge)',
        'reproducible': 'DatasetManifest 작성 + manifest-verify (lakatos manifest-verify)',
        'stands': '미해소 의문 해소 — 반박 제출 또는 판결 재검토 (argue.verdict_stands)',
        'calibrated': '발급자 예측 이력으로 Brier/ECE 산출 (calibrate)',
        'grounded': '인용 상수 tier 공개 (grounding.provenance)',
        'measurement_owned': '측정값 소유 — replay 재유도 활성화(LAKATOS_REPLAY_EXEC → server_regenerated) '
                             '또는 write-cert 서명(allow-list 신원 → attested). client float 봉인은 인증 불가.',
    }
    return [{'gate': g, 'action': todo[g]} for g in cert.missing]
