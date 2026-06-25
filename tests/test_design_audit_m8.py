"""설계감사 M8 — claim doubt-resolution 의 actor 독립성 게이트.

결함: `_resolved_doubt_ids` 가 resolve/close 이벤트의 payload(resolves/closes)만 보고
doubt 를 해소로 인정해, *한 행위자가 자기 doubt 를 자기가 resolve* 로 닫고 claim 을
세울 수 있다(약속 #2 "어떤 서브시스템도 자기 출력을 채점 안 함"의 약한 위반).

처방: resolve/close 이벤트의 actor 가 그 doubt 를 *제기한 actor* 와 같으면 해소로
인정하지 않는다(self_resolved → unresolved 유지). 다른 actor 의 정당한 해소는 정상 작동.

# KG: span_lakatotree_claim_standing
"""
from lakatos.claim import ClaimStandingPolicy, evaluate_claim_standing
from lakatos.engine import (
    FoundationMap,
    FoundationRequirement,
    KnowledgeKind,
    Possibility,
    Realm,
    ResearchEvent,
    ResearchFrame,
    ResearchProject,
)


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
    """상/하계 evidence 가 갖춰져 doubt 만이 standing 을 가르는 frame."""
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


def test_self_resolved_doubt_does_not_clear_standing():
    """동일 actor 가 제기하고 *같은 actor* 가 resolve 하면 doubt 는 여전히 unresolved.

    대조군: *다른* actor 가 resolve 하면 정상 해소(과잉차단 회귀가드).
    """
    # ── 음성(self-resolution): 같은 actor 가 자기 doubt 를 자기가 닫음 → 막혀 있어야 ──
    frame = _frame_with_evidence()
    frame.record_event(_doubt("human:reviewer"))
    frame.record_event(_resolve("human:reviewer"))   # 동일 actor self-resolve

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

    # ── 대조군(독립 해소): *다른* actor 가 resolve → 정상 해소(과잉차단 아님) ──
    other = _frame_with_evidence()
    other.record_event(_doubt("human:reviewer"))
    other.record_event(_resolve("human:independent-verifier"))   # 독립 actor

    other_standing = evaluate_claim_standing(
        "claim-1",
        frame=other,
        foundation=_satisfied_foundation(),
        policy=ClaimStandingPolicy(require_replay=False),
    )

    assert other_standing.stands, "독립 actor 의 정당한 해소는 여전히 claim 을 세워야 한다"
    assert other_standing.unresolved_doubts == ()
    assert "human_doubt:evt-doubt" not in other_standing.blocking_reasons
