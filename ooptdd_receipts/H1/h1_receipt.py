"""OOPTDD emit-adapter — LakatoTree 설계감사 H1(질적 self-report floor)을 *구조화 이벤트 trace*(R02)로 영수증화.

결함(H1): 질적 verdict(LakatosGate/PnR)가 영수증 없는 client bool 로 progressive 를 떠받친 뒤 scripted
COUNTS 영수증을 상속해 CANONICAL floor 를 통과하던 결함. 수정: synthesize_promotion 이
qualitative_self_report=True 이면 judge_receipt 를 False 로 떨어뜨려 메트릭 scripted COUNTS *단독* 으론
floor 를 안 연다(독립 영수증=reproducible 실 replay / human attestation 요구).

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/verdict/spine.py 는 불변).
verify 가 실제 spine.synthesize_promotion 을 *구동*해 관측한 사실을 구조화 이벤트로 ship.
Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

음성 오라클(no-fake-green): 결함이 살아있었다면(qualitative_self_report 분기가 judge_receipt 를
안 떨어뜨렸다면) floor 가 열려 ['ok'] is True 가 되어 (1) 케이스 assert 가 깨진다. 즉 (1)의 통과는
*실제 고친 코드*만이 만들 수 있다. 반대로 (2)는 회귀가드 — floor 가 과잉차단으로 망가지면 깨진다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.verdict.spine import synthesize_promotion   # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.H1", "event": name, **attrs}


def verify(backend, cid):
    """H1 floor 구동 — 질적 self-report 노드가 메트릭 scripted COUNTS 단독으로 CANONICAL floor 를
    못 연다(차단)는 것과, 비-질적 보통 scripted progressive 는 여전히 통과한다(회귀가드)는 것을 증언."""

    # ── (1) 양성+음성 오라클: 질적 self-report → floor 차단(결함이 있었다면 ok=True 로 틀릴 케이스) ──
    blocked = synthesize_promotion(
        scripted_verdict="progressive", verdict_source="scripted", stands=True,
        reproducible=None, credibility=None,
        qualitative_self_report=True)            # ← 질적 self-report 표식
    # 결함이 살아있었다면 judge_receipt 가 True 로 남아 floor 가 열리고 아래 assert 들이 깨진다.
    assert blocked["ok"] is False, blocked
    assert "no_receipt_for_canonical" in blocked["reasons"], blocked
    assert blocked["gates"]["floor"]["passed"] is False, blocked
    backend.ship([_ev(cid, "qual_self_report_floor_blocked",
                      ok=blocked["ok"],
                      floor_passed=blocked["gates"]["floor"]["passed"],
                      reasons=list(blocked["reasons"]))])

    # ── (2) 회귀가드: 질적 self-report 아님 → 메트릭 영수증으로 *여전히* floor 통과 ──
    passes = synthesize_promotion(
        scripted_verdict="progressive", verdict_source="scripted", stands=True,
        reproducible=None, credibility=None,
        qualitative_self_report=False)
    assert passes["ok"] is True, passes
    assert passes["gates"]["floor"]["passed"] is True, passes
    backend.ship([_ev(cid, "non_qual_floor_passes",
                      ok=passes["ok"],
                      floor_passed=passes["gates"]["floor"]["passed"])])
