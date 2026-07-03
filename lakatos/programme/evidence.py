"""evidence-record 로더/검증 — 측정 하네스가 뱉은 grounded 레코드를 엔진이 source_record 로 먹는다.

계약 정본: docs/EVIDENCE_RECORD.md. longinus-data-binding(데이터 provenance)을 *측정*으로 확장.

★정직성 불변식(validate_record 가 강제):
  - 레코드는 **verdict 를 담지 않는다**(measurement 안에도). 판결은 엔진이 생성 — 자기채점 차단.
  - measurement 는 grounded(provenance.inputs 출처 명시)여야 한다.
  - preregistration.registered_before_measurement 가 True 여야 한다(HARKing 차단).
"""
from __future__ import annotations

import json
import pathlib

RECORD_SCHEMA = 'lakato-evidence-record/v1'
REQUIRED = ('schema', 'programme', 'conjecture', 'preregistration', 'measurement', 'provenance', 'harness')


def load_record(path) -> dict:
    """evidence json 로드. 파일 없으면 FileNotFoundError(호출측이 OPEN 으로 처리)."""
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def validate_record(rec: dict) -> list[str]:
    """정직성·구조 검증. 빈 리스트=합격. 위반 문자열 리스트=불합격(엔진이 grounding 거부)."""
    errs: list[str] = []
    if rec.get('schema') != RECORD_SCHEMA:
        errs.append(f"schema 불일치: {rec.get('schema')!r} != {RECORD_SCHEMA!r}")
    for k in REQUIRED:
        if k not in rec:
            errs.append(f"필수키 누락: {k}")
    # ★자기채점 차단 — 레코드에 verdict 금지
    if 'verdict' in rec:
        errs.append("정직성 위반: 레코드 최상위에 verdict 존재(판결은 엔진이 생성)")
    meas = rec.get('measurement') or {}
    if isinstance(meas, dict) and 'verdict' in meas:
        errs.append("정직성 위반: measurement 안에 verdict 존재")
    # grounding — provenance.inputs 출처 명시 필수
    prov = rec.get('provenance') or {}
    if not prov.get('inputs') and not prov.get('data_manifest'):
        errs.append("grounding 부재: provenance.inputs/data_manifest 둘 다 없음")
    # 사전등록 — HARKing 차단
    prereg = rec.get('preregistration') or {}
    if prereg.get('registered_before_measurement') is not True:
        errs.append("사전등록 미표명: preregistration.registered_before_measurement != True")
    return errs


def is_grounded(rec: dict) -> bool:
    """검증 합격 ∧ provenance.grounded=True 일 때만 grounding 자격."""
    return not validate_record(rec) and bool((rec.get('provenance') or {}).get('grounded'))


def source_id(rec: dict) -> str:
    """노드 source_record 추적용 id (conjecture@harness-script)."""
    h = (rec.get('harness') or {}).get('script', '?')
    return f"{rec.get('conjecture', '?')}@{h}"


def summarize(rec: dict) -> dict:
    """판결 programme 이 쓰기 좋은 요약 — measured/predicted/grounded/findings."""
    meas = rec.get('measurement') or {}
    pre = rec.get('preregistration') or {}
    return {
        'source_record': source_id(rec),
        'grounded': is_grounded(rec),
        'metric': meas.get('metric'),
        'measured': meas.get('value'),
        'unit': meas.get('unit'),
        'predicted': pre.get('predicted'),
        'kill_condition': pre.get('kill_condition'),
        'findings': rec.get('findings') or [],
        'errors': validate_record(rec),
    }
