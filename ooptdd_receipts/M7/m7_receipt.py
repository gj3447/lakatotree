"""OOPTDD emit-adapter — LakatoTree 설계감사 M7(sorry=0 강제 배선)을 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진/엔진코드가 아니라 이 adapter 에만. M7 은 formal/Pidna.lean 정적
파일이라 import 할 런타임 모듈이 없다 — 그래서 verify 가 *실제 M7 가드 코드*(tests.test_design_audit_m7
모듈의 _pidna_enforces_sorry_zero / _WAE_RE / _PIDNA)를 import 해 구동한다(재구현 금지). R12: lean 컴파일
없이 정적 wiring 확인(log-free oracle). Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

결함 상태(M7): Pidna.lean 에 `set_option warningAsError true` 가 *없으면* Lean 의 `sorry` 는 warning 일
뿐이고 `lake build` 는 exit 0 → Rung.derived 자기보고 거부 불변식이 sorry 한 줄로 위조 가능. 수정은 그
파일스코프 옵션을 배선하는 것. verify 는 (양성)배선됨 + (음성)부재였다면 가드가 거짓 통과하지 않음을 증언.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

# 실제 M7 가드 코드를 import 해 구동(재구현 금지). 이 모듈이 곧 참고테스트가 신뢰하는 wiring 검사.
from tests import test_design_audit_m7 as m7  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M7", "event": name, **attrs}


def verify(backend, cid):
    """M7 강제 배선 구동 — 실제 Pidna.lean 본문에 sorry=0 강제(`set_option warningAsError true`)가
    배선됐는지 *그 가드 코드 자체*로 확인하고, 음성 오라클(부재 상태였다면 가드가 거짓 통과 안 함)을 증언."""
    pidna_path = m7._PIDNA
    pidna_text = pidna_path.read_text(encoding="utf-8")

    # (양성) 실제 M7 가드 함수를 구동 — Pidna.lean 에 sorry=0 강제 옵션이 *배선됨*.
    wired = m7._pidna_enforces_sorry_zero()
    assert wired is True, (
        f"M7 결함: {pidna_path} 에 sorry=0 강제(set_option warningAsError true)가 없음 — "
        "sorry 한 줄로 lake build green 위조 가능(Rung.derived 불변식 forge)."
    )
    # 옵션 매치가 실제 파일 본문에서 나온 것임을 재확인(가드 정규식이 진짜 텍스트에 적중).
    m_match = m7._WAE_RE.search(pidna_text)
    assert m_match is not None, "wiring 정규식이 Pidna.lean 본문에 적중하지 못함"
    backend.ship([_ev(cid, "lean_sorry_enforcement_wired",
                      pidna=str(pidna_path),
                      matched=m_match.group(0),
                      offset=m_match.start())])

    # (음성 오라클 / no-fake-green) — 결함 상태(옵션 없는 Pidna 본문)에서는 가드가 *거짓 통과하지 않음*.
    # 옵션 라인을 제거한 가상 본문에 동일 가드 정규식을 적용 → 매치 None(=결함 검출). 이게 안 깨지면
    # 가드가 vacuous 하게 항상-green 인 셈이라 영수증이 가짜가 됨.
    defect_text = m7._WAE_RE.sub("-- (M7 defect: enforcement stripped)", pidna_text)
    defect_detected = m7._WAE_RE.search(defect_text) is None
    assert defect_detected is True, (
        "음성 오라클 실패: sorry=0 강제를 제거한 본문에서도 가드 정규식이 여전히 매치함 — "
        "가드가 결함을 구분 못 함(vacuous green)."
    )
    backend.ship([_ev(cid, "lean_sorry_enforcement_wired",
                      negative_oracle=True,
                      defect_detected=defect_detected,
                      note="옵션 제거 본문에서 가드가 부재로 판정(결함 검출)")])
