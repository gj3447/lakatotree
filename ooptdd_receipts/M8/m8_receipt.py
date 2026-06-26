"""OOPTDD emit-adapter — LakatoTree 설계감사 M8(claim doubt-resolution actor 독립성)을
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/claim.py·engine.py 는 불변).
verify 가 실제 lakatos.claim.evaluate_claim_standing 을 *구동*해, 동일 actor self-resolve 가
doubt 해소로 인정되지 않고(self_resolution_rejected), 독립 actor 의 해소는 정상 작동함
(independent_resolution_ok)을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 결함이 있었다면(self-resolve 를 해소로 인정) self_standing.stands 가
True 가 되어 첫 assert 가 깨진다. 즉 이 영수증은 결함이 살아있으면 *틀린다*.
Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

참고 테스트: lakatotree/tests/test_design_audit_m8.py 의 픽스처/패턴을 그대로 차용.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.claim import ClaimStandingPolicy, evaluate_claim_standing  # noqa: E402
from lakatos.engine import (  # noqa: E402
    FoundationMap,
    FoundationRequirement,
    KnowledgeKind,
    Possibility,
    Realm,
    ResearchEvent,
    ResearchFrame,
    ResearchProject,
)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M8", "event": name, **attrs}


# ── 픽스처(test_design_audit_m8.py 차용) ──────────────────────────────────────
def _satisfied_foundation() -> FoundationMap:
    foundation = FoundationMap()
    for name, kind in (
        ("research-program-theory", KnowledgeKind.THEORY),
        ("metric-contract", KnowledgeKind.METRIC),
    ):
        foundation.add(
            FoundationRequirement(
                name=name,
                kind=kind,
                question=f"{name}?",
                why_needed="claim standing needs explicit base knowledge",
                evidence_refs=(f"doc:{name}",),
                status="satisfied",
            )
        )
    return foundation


def _frame_with_evidence() -> ResearchFrame:
    frame = ResearchFrame(ResearchProject(name="lab", goal="judge claim standing"))
    frame.open_possibility(Possibility("claim-1", "does the branch currently stand?"))
    frame.record_event(
        ResearchEvent(
            name="evt-web",
            realm=Realm.INTERNET,
            actor="agent:researcher",
            action="fetch_source",
            target="claim-1",
            evidence_refs=("obs:source",),
            payload=(("trust", "0.9"),),
        )
    )
    frame.record_event(
        ResearchEvent(
            name="evt-bash",
            realm=Realm.BASH,
            actor="agent:builder",
            action="test_passed",
            target="claim-1",
            evidence_refs=("bash:pytest",),
            payload=(("exit_code", "0"),),
        )
    )
    return frame


def _doubt(actor: str) -> ResearchEvent:
    return ResearchEvent(
        name="evt-doubt",
        realm=Realm.HUMAN,
        actor=actor,
        action="doubt",
        target="claim-1",
        evidence_refs=("comment:why?",),
    )


def _resolve(actor: str) -> ResearchEvent:
    return ResearchEvent(
        name="evt-resolve",
        realm=Realm.HUMAN,
        actor=actor,
        action="resolve_doubt",
        target="claim-1",
        evidence_refs=("comment:ok",),
        payload=(("resolves", "evt-doubt"), ("confidence", "0.8")),
    )


# ── 구동 ─────────────────────────────────────────────────────────────────────
def verify(backend, cid):
    """M8 구동 — 실제 evaluate_claim_standing 으로 self-resolve 거부 + 독립 해소 정상을 증언."""
    # (1) 음성(self-resolution): 같은 actor 가 자기 doubt 를 자기가 닫음 → 막혀 있어야 한다.
    #     결함이 있었다면(self-resolve 인정) self_standing.stands == True 가 되어 여기서 깨진다.
    frame = _frame_with_evidence()
    frame.record_event(_doubt("human:reviewer"))
    frame.record_event(_resolve("human:reviewer"))  # 동일 actor self-resolve

    self_standing = evaluate_claim_standing(
        "claim-1",
        frame=frame,
        foundation=_satisfied_foundation(),
        policy=ClaimStandingPolicy(require_replay=False),
    )

    assert not self_standing.stands, "self-resolve 로 claim 이 서면 안 된다(약속 #2 위반)"
    assert "evt-doubt" in self_standing.unresolved_doubts, (
        "self-resolve 된 doubt 는 unresolved 로 남아야 한다"
    )
    assert "human_doubt:evt-doubt" in self_standing.blocking_reasons
    backend.ship([_ev(cid, "self_resolution_rejected",
                      stands=bool(self_standing.stands),
                      unresolved_doubts=list(self_standing.unresolved_doubts),
                      blocking="human_doubt:evt-doubt")])

    # (2) 양성 대조군(독립 해소): *다른* actor 가 resolve → 정상 해소(과잉차단 회귀가드).
    other = _frame_with_evidence()
    other.record_event(_doubt("human:reviewer"))
    other.record_event(_resolve("human:independent-verifier"))  # 독립 actor

    other_standing = evaluate_claim_standing(
        "claim-1",
        frame=other,
        foundation=_satisfied_foundation(),
        policy=ClaimStandingPolicy(require_replay=False),
    )

    assert other_standing.stands, "독립 actor 의 정당한 해소는 여전히 claim 을 세워야 한다"
    assert other_standing.unresolved_doubts == ()
    assert "human_doubt:evt-doubt" not in other_standing.blocking_reasons
    backend.ship([_ev(cid, "independent_resolution_ok",
                      stands=bool(other_standing.stands),
                      unresolved_doubts=list(other_standing.unresolved_doubts),
                      resolver="human:independent-verifier")])
