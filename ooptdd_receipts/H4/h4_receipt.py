"""OOPTDD emit-adapter — LakatoTree 설계감사 H4(hard_core demote 가드)을 *구조화 이벤트 trace*(R02)로 영수증화.

결함(감사 H4): demote_canonical 이 expansion/contraction 의 hard-core 가드를 우회해 hard_core belief 의
credence 를 조용히 제자리 강등하던 결함. 수정: old.kind=='hard_core' 면 allow_hard_core 없이는
HardCoreProtected 를 raise.

규율(ooptdd): 이벤트 리터럴은 엔진(lakatos/programme/agm.py 불변)이 아니라 이 adapter 의 verify 본문에만.
verify 가 *실제* lakatos.programme.agm.demote_canonical 를 구동(재구현 금지)하고, 관측한 사실을
구조화 이벤트로 ship. 음성 오라클: 결함이 살아있었다면(가드 부재) hard_core 강등이 *조용히 성공*해
HardCoreProtected 가 안 나므로 이 케이스는 틀린다 → no-fake-green.
Longinus 바인딩(R10): emit site(verify)가 must_emit 이벤트를 낸다.
# KG: span_lakatotree_design_audit_20260625
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.programme.agm import (  # noqa: E402
    Belief,
    HardCoreProtected,
    demote_canonical,
)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.H4", "event": name, **attrs}


def verify(backend, cid):
    """H4 가드 구동 — hard_core 정본을 동의 없이 demote 하면 HardCoreProtected,
    명시 동의(allow_hard_core=True)에서만 강등 성공함을 구조화 이벤트로 증언.
    테스트 픽스처(tests/test_design_audit_h4_hardcore.py) 그대로 차용."""
    # 픽스처: hard_core 추측 + 경쟁 정본(protective_belt) — test_demote_canonical_protects_hard_core 그대로.
    hc = Belief("hc", "하드코어 추측", kind="hard_core", credence=0.95)
    new = Belief("rival", "경쟁 정본", kind="protective_belt", credence=0.8)

    # (1) 음성 오라클 — 동의 없는 hard_core demote 는 HardCoreProtected 로 *차단*되어야.
    #     결함(가드 부재)이면 raise 가 안 나고 조용히 강등 성공 → 이 분기는 틀린다(no-fake-green).
    refused = False
    try:
        demote_canonical([hc], "hc", new)            # allow_hard_core 기본 False
    except HardCoreProtected as exc:
        refused = True
        reason = str(exc)
    assert refused, "결함 회귀: hard_core 가 동의 없이 demote 됨(HardCoreProtected 미발생)"
    backend.ship([_ev(cid, "hard_core_demote_refused",
                      exception="HardCoreProtected", reason=reason[:80])])

    # (2) 양성 — 명시 동의(allow_hard_core=True)면 강등 성공. 옛 정본은 제거가 아니라 강등(여전히 base 내).
    r = demote_canonical([hc], "hc", new, allow_hard_core=True)
    assert any(b.belief_id == "hc" for b in r.base), "동의 강등 후 옛 정본이 base 에 남아야(제거 아님)"
    demoted = next(b for b in r.base if b.belief_id == "hc")
    # credence 가 새 정본(0.8) - DEMOTE_PENALTY(0.1)=0.7 아래로 실제로 깎였는지(강등의 구동 증거).
    assert demoted.credence < hc.credence, "강등인데 credence 가 안 깎임"
    # demote 는 제거가 아니라 강등 — kind(hard_core)는 보존되고 credence 만 내려간다(THEORY §2).
    assert demoted.kind == "hard_core", "demote 는 kind 보존(제거/형변환 아님)"
    backend.ship([_ev(cid, "consented_demote_ok",
                      old_id="hc", old_credence=hc.credence,
                      demoted_credence=demoted.credence,
                      demoted_kind=demoted.kind)])
