"""ClaimStanding TDD — 상계/하계 evidence 를 한 claim standing 으로 합친다.
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
from lakatos.io.replay import LineageReplayGate
from lakatos.io.lineage import Derivation


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


def _frame_with_claim() -> ResearchFrame:
    frame = ResearchFrame(ResearchProject(name="lab", goal="judge claim standing"))
    frame.open_possibility(Possibility("claim-1", "does the branch currently stand?"))
    return frame


def _lineage_result(*, stale: bool = False):
    raw = Derivation("raw://lot", "raw0", "", "", [], kind="source", ts="t0")
    final = Derivation(
        "artifact://final",
        "final0",
        "solve.py",
        "sha-solve",
        [("raw://lot", "raw0")],
        kind="final",
        ts="t1",
        env="env1",
    )
    current = {"raw://lot": "raw_NEW" if stale else "raw0"}
    return LineageReplayGate.evaluate(
        "artifact://final",
        [raw, final],
        sources={"raw://lot"},
        current_shas=current,
        current_env="env1",
    )


def test_claim_standing_blocks_on_foundation_gap_human_doubt_and_lineage_failure():
    foundation = FoundationMap()
    foundation.add(
        FoundationRequirement(
            name="metric-contract",
            kind=KnowledgeKind.METRIC,
            question="which metric judges progress?",
            why_needed="avoid relabel-as-progress",
        )
    )
    frame = _frame_with_claim()
    frame.record_event(
        ResearchEvent(
            name="evt-web",
            realm=Realm.INTERNET,
            actor="agent:researcher",
            action="fetch_source",
            target="claim-1",
            evidence_refs=("obs:paper",),
            payload=(("trust", "0.82"),),
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
    frame.record_event(
        ResearchEvent(
            name="evt-human-doubt",
            realm=Realm.HUMAN,
            actor="human:reviewer",
            action="doubt",
            target="claim-1",
            evidence_refs=("comment:needs-replay",),
        )
    )

    standing = evaluate_claim_standing(
        "claim-1",
        frame=frame,
        foundation=foundation,
        lineage=_lineage_result(stale=True),
        policy=ClaimStandingPolicy(require_replay=True),
    )

    assert not standing.stands
    assert standing.status == "blocked"
    assert "foundation:metric-contract" in standing.blocking_reasons
    assert "human_doubt:evt-human-doubt" in standing.blocking_reasons
    assert "lineage:stale_inputs" in standing.blocking_reasons
    assert standing.upper_confidence >= 0.82
    assert standing.lower_confidence >= 0.80
    assert standing.to_dict()["claim"] == "claim-1"
    actions = {a["reason"]: a for a in standing.to_dict()["next_actions"]}
    assert actions["foundation:metric-contract"]["action"] == "satisfy_foundation_requirement"
    assert actions["human_doubt:evt-human-doubt"]["action"] == "resolve_human_doubt"
    assert actions["lineage:stale_inputs"]["action"] == "run_rebuild_or_refresh_lineage"


def test_claim_standing_stands_when_foundation_replay_and_upper_lower_evidence_pass():
    frame = _frame_with_claim()
    frame.record_event(
        ResearchEvent(
            name="evt-web",
            realm=Realm.INTERNET,
            actor="agent:researcher",
            action="fetch_source",
            target="claim-1",
            evidence_refs=("obs:primary-source",),
            payload=(("trust", "0.82"),),
        )
    )
    frame.record_event(
        ResearchEvent(
            name="evt-human",
            realm=Realm.HUMAN,
            actor="human:reviewer",
            action="human_verdict",
            target="claim-1",
            evidence_refs=("review:accept",),
            payload=(("confidence", "0.76"),),
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
    frame.record_event(
        ResearchEvent(
            name="evt-data",
            realm=Realm.DATA,
            actor="agent:lineage",
            action="replay_passed",
            target="claim-1",
            evidence_refs=("lineage:artifact://final",),
            payload=(("confidence", "0.85"),),
        )
    )

    standing = evaluate_claim_standing(
        "claim-1",
        frame=frame,
        foundation=_satisfied_foundation(),
        lineage=_lineage_result(stale=False),
        policy=ClaimStandingPolicy(require_replay=True),
    )

    assert standing.stands
    assert standing.status == "stands"
    assert standing.confidence >= 0.80
    assert standing.blocking_reasons == ()
    assert standing.realms == ("bash", "data", "human", "internet")


def test_claim_standing_resolves_human_doubt_append_only():
    frame = _frame_with_claim()
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
        )
    )
    frame.record_event(
        ResearchEvent(
            name="evt-doubt",
            realm=Realm.HUMAN,
            actor="human:reviewer",
            action="doubt",
            target="claim-1",
            evidence_refs=("comment:why?",),
        )
    )
    frame.record_event(
        ResearchEvent(
            name="evt-resolve",
            realm=Realm.HUMAN,
            # M8(design-audit): resolver 는 doubt 제기자(human:reviewer)와 *독립* 한 actor 여야
            #   해소로 인정된다(self-resolution 차단). 이 테스트의 의도는 resolve_doubt 의
            #   append-only 해소이지 self-resolution 이 아니므로 독립 actor 로 명시.
            actor="human:second-reviewer",
            action="resolve_doubt",
            target="claim-1",
            evidence_refs=("comment:ok",),
            payload=(("resolves", "evt-doubt"), ("confidence", "0.8")),
        )
    )

    standing = evaluate_claim_standing(
        "claim-1",
        frame=frame,
        foundation=_satisfied_foundation(),
        policy=ClaimStandingPolicy(require_replay=False),
    )

    assert standing.stands
    assert standing.unresolved_doubts == ()
    assert "human_doubt:evt-doubt" not in standing.blocking_reasons


def test_claim_standing_can_make_missing_lower_world_evidence_explicit():
    frame = _frame_with_claim()
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

    standing = evaluate_claim_standing(
        "claim-1",
        frame=frame,
        foundation=_satisfied_foundation(),
        policy=ClaimStandingPolicy(require_replay=False),
    )

    assert not standing.stands
    assert "lower_confidence_below_threshold" in standing.blocking_reasons
    assert standing.upper_confidence > standing.lower_confidence
    actions = {a["reason"]: a for a in standing.to_dict()["next_actions"]}
    assert actions["lower_confidence_below_threshold"]["realm"] == "bash|data|git|agent"
    assert actions["lineage:not_checked"]["action"] == "check_lineage_replay"


# ── SRP 분해 payoff: 각 blocking 소스(의미)를 *독립* 테스트 (전엔 frame/event 통째로만 가능) ──
from lakatos.claim import (
    ClaimStandingPolicy, _combined_confidence, _confidence_evidence_block,
    _standing_status, _foundation_block, _lineage_block,
)


def test_combined_confidence_min_when_both_required():
    pol = ClaimStandingPolicy(require_upper=True, require_lower=True)
    assert _combined_confidence(0.9, 0.3, pol) == 0.3        # 둘 다 요구 → 약한 쪽이 끈다
    pol2 = ClaimStandingPolicy(require_upper=False, require_lower=False)
    assert _combined_confidence(0.9, 0.3, pol2) == 0.9        # 요구 없으면 max


def test_confidence_evidence_block_isolated():
    pol = ClaimStandingPolicy(require_upper=True, require_lower=False, min_confidence=0.5)
    assert 'evidence:missing_refs' in _confidence_evidence_block(0.9, 0.1, [], pol)
    assert 'upper_confidence_below_threshold' in _confidence_evidence_block(0.3, 0.9, ['ref'], pol)
    assert _confidence_evidence_block(0.9, 0.1, ['ref'], pol) == []   # 통과


def test_foundation_and_lineage_block_isolated():
    req = ClaimStandingPolicy(require_foundation=True, require_replay=True)
    off = ClaimStandingPolicy(require_foundation=False, require_replay=False)
    assert _foundation_block(None, req) == (['foundation:missing'], ())
    assert _foundation_block(None, off) == ([], ())                   # 요구 안 하면 무블록
    assert _lineage_block(None, req) == (['lineage:missing'], ('missing',))
    assert _lineage_block(None, off) == ([], ())


def test_standing_status_isolated():
    pol = ClaimStandingPolicy(strong_confidence=0.7)
    assert _standing_status(False, 0.99, pol) == 'blocked'           # 막힌 의문 → blocked
    assert _standing_status(True, 0.8, pol) == 'stands'              # 강한 신뢰
    assert _standing_status(True, 0.5, pol) == 'conditional'         # 약한 신뢰


# ── 바인딩 owner+test 메움: claim 2개 ──────────────────────────────────────────
from lakatos.claim import _realm_confidences, _doubt_block
from lakatos.engine import ResearchEvent as _RE, Realm as _Realm


def _ev(name, realm):
    return _RE(name=name, realm=realm, actor='a', action='fetch', target='claim-1', evidence_refs=('r',))


def test_realm_confidences_isolated_bounded():
    upper, lower = _realm_confidences((_ev('e1', _Realm.INTERNET), _ev('e2', _Realm.BASH)), None)
    assert 0 <= upper <= 1 and 0 <= lower <= 1


def test_doubt_block_isolated_empty_when_no_doubt():
    block, unresolved = _doubt_block(())
    assert block == [] and unresolved == ()
