"""OOPTDD emit-adapter — LakatoTree 판정엔진 감사 finding A(유일 CRITICAL: metric progressive + ZERO
Lakatos 정성검증이 full 'progressive' 로 발행)를 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 spine/bayes/eureka 는 불변).
verify 가 실제 lakatos.verdict.spine / quant.bayes / eureka 를 *구동*해:
  ① metric progressive + lakatos None + PnR None → verdict 'progressive_unverified'(emit, 유일 producer)
  ② PnR progressive appraisal(= dialectical 정성검증) → full 'progressive' 로 rescue / PnR conditional →
     'progressive_conditional' (present PnR 은 무검증 아님 — pinning test_pnr 정합)
  ③ FORK3 E2: 발견 축(eureka_verdict)은 pu 를 'progressive' 로 읽어 BF 6.0(novel⊥belt) — 반면 abandon-stack
     bayes 는 raw 'progressive_unverified' 로 BF 1.0(credence 축적·폐기면책 없음). 두 축 분리.
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 옛 결함(spine.reconcile_verdict 가 'progressive' 를 그대로 발행)이 살아있었다면
①의 verdict 가 'progressive' 라 첫 assert 가 깨진다. E2 매핑(eureka_verdict)이 제거됐다면 ③의 discovery BF
가 1.0 이라 깨진다. PnR-rescue dialectical 분기가 미갱신이면 ②가 'progressive_unverified' 를 반환해 깨진다.
즉 이 영수증은 어느 결함이든 살아있으면 *틀린다*. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit.

참고 테스트: lakatotree/tests/test_progressive_unverified_20260713.py.
# KG: lakatotree-judge-engine-audit finding A / progressive-unverified-2026-07-12
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.eureka import eureka_verdict  # noqa: E402
from lakatos.quant.bayes import bayes_factor  # noqa: E402
from lakatos.verdict.pnr import Response, appraise_response  # noqa: E402
from lakatos.verdict.spine import dialectical_verdict, reconcile_verdict  # noqa: E402

PU = "progressive_unverified"


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.spine.finding_A", "event": name, **attrs}


def verify(backend, cid):
    """finding A 구동 — 실제 spine/bayes/eureka 로 emit + PnR-rescue + E2-orthogonality 증언."""
    # (1) 음성 오라클: metric progressive + Lakatos None + PnR None → progressive_unverified.
    #     옛 코드(reconcile 가 'progressive' 발행)가 살아있었다면 여기서 깨진다.
    base = reconcile_verdict("progressive", None)
    assert base["verdict"] == PU, f"emit 결함 부활: {base['verdict']} (progressive_unverified 여야)"
    assert base["status"] == "qualitative_unverified"
    zero = dialectical_verdict("progressive")  # PnR·Lakatos 완전 부재
    assert zero["verdict"] == PU, f"완전 무검증인데 {zero['verdict']}"
    backend.ship([_ev(cid, "unverified_emitted", verdict=zero["verdict"], status=base["status"],
                      reasons=list(base["reasons"]))])

    # (2) PnR rescue: present appraisal IS 정성검증 → pu 를 승격(무검증 아님).
    prog = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=True, in_heuristic_spirit=True)
    cond = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=False, in_heuristic_spirit=True)
    lifted_prog = dialectical_verdict("progressive", pnr_appraisal=prog)["verdict"]
    lifted_cond = dialectical_verdict("progressive", pnr_appraisal=cond)["verdict"]
    assert lifted_prog == "progressive", f"PnR progressive rescue 미발화: {lifted_prog}"
    assert lifted_cond == "progressive_conditional", f"PnR conditional rescue 미발화: {lifted_cond}"
    backend.ship([_ev(cid, "pnr_rescue_lifts", pnr_progressive=lifted_prog, pnr_conditional=lifted_cond)])

    # (3) FORK3 E2 직교: 발견 축은 pu→'progressive'(BF 6.0), abandon-stack 은 raw pu(BF 1.0).
    #     E2 매핑(eureka_verdict)이 제거됐다면 discovery_bf 가 1.0 이라 깨진다.
    abandon_bf = bayes_factor(PU, delta=5.0, noise_band=0.1)                 # raw pu → 1.0
    discovery_bf = bayes_factor(eureka_verdict(PU), delta=5.0, noise_band=0.1)  # mapped → 6.0
    assert abandon_bf == 1.0, f"abandon-stack 이 pu 로 credence 축적: BF={abandon_bf}"
    assert discovery_bf > 3.162, f"발견 축이 pu 로 굶음(E2 매핑 결함): BF={discovery_bf}"
    assert eureka_verdict("progressive") == "progressive"  # 항등(진짜 progressive 무영향)
    backend.ship([_ev(cid, "eureka_orthogonal", abandon_bf=abandon_bf, discovery_bf=discovery_bf)])
