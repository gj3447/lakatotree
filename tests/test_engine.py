"""라카토트리 엔진 결합부 TDD.

인터넷 관측, 인간/agent 비판, 하계 bash 실행, 데이터 계보를 기존 순수층
trust/judge/lineage 위에서 한 번 더 잠그는 게이트를 검증한다.
# KG: span_lakatotree_engine
"""
from datetime import datetime, timezone

from lakatos.engine import (
    BashAct,
    CredibilityPromotionGate,
    CredibilityTier,
    InternetObservation,
    LakatosEvidence,
    LakatosGate,
    LakatosNode,
    LakatosTree,
    LakatosVerdict,
    LineageReplayGate,
    ObservationLedger,
    SourceCredibilityScore,
)
from lakatos.lineage import Derivation


def test_source_credibility_uses_trust_components_and_existing_weight():
    score = SourceCredibilityScore(
        source_class_weight=1.0,
        link_authority=0.9,
        primary_source_bonus=1.0,
        provenance_score=1.0,
        corroboration_score=0.8,
        recency_score=0.8,
        supply_chain_score=0.9,
    )

    assert score.tier == CredibilityTier.EXTRACTED
    assert score.evidence_weight > 0.8
    assert score.as_components()["provenance_score"] == 1.0


def test_no_silent_promotion_from_ambiguous_internet_to_extracted_claim():
    blocked = CredibilityPromotionGate.evaluate(
        current=CredibilityTier.AMBIGUOUS,
        target=CredibilityTier.EXTRACTED,
        has_direct_source=False,
        has_independent_corroboration=True,
        has_human_verdict=False,
    )

    allowed = CredibilityPromotionGate.evaluate(
        current=CredibilityTier.AMBIGUOUS,
        target=CredibilityTier.EXTRACTED,
        has_direct_source=True,
        has_independent_corroboration=True,
        has_human_verdict=True,
    )

    assert not blocked.passed
    assert "direct_source_or_human_verdict" in blocked.reasons
    assert "ambiguous_to_extracted_requires_human_verdict" in blocked.reasons
    assert allowed.passed


def test_observation_ledger_refetch_is_append_only():
    ledger = ObservationLedger()
    first = InternetObservation(
        name="obs-1",
        url="https://example.test/paper",
        query="q",
        retrieved_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        content_hash="h1",
        fetch_tool="web.fetch",
        source_type="paper",
        credibility=SourceCredibilityScore(provenance_score=1.0),
    )
    ledger.add(first)
    second = ledger.refetch(
        previous_name="obs-1",
        name="obs-2",
        retrieved_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        content_hash="h2",
        fetch_tool="web.fetch",
    )

    assert ledger.get("obs-1").content_hash == "h1"
    assert second.revision_of == "obs-1"
    assert [x.name for x in ledger.by_url(first.url)] == ["obs-1", "obs-2"]


def test_lakatos_gate_requires_progressive_content_and_replay_for_data_branch():
    progressive = LakatosGate.evaluate(
        LakatosEvidence(
            theory_laden_anomaly=True,
            independent_testable_consequence=True,
            excess_empirical_content=True,
            hard_core_preserved=True,
            implementation_complete=True,
            data_branch=True,
            data_replay_passed=True,
        )
    )
    conditional = LakatosGate.evaluate(
        LakatosEvidence(
            theory_laden_anomaly=True,
            independent_testable_consequence=True,
            excess_empirical_content=True,
            hard_core_preserved=True,
            implementation_complete=True,
            data_branch=True,
            data_replay_passed=False,
        )
    )
    degenerating = LakatosGate.evaluate(
        LakatosEvidence(
            theory_laden_anomaly=True,
            independent_testable_consequence=False,
            excess_empirical_content=False,
            hard_core_preserved=True,
            implementation_complete=True,
        )
    )

    assert progressive.verdict == LakatosVerdict.PROGRESSIVE
    assert conditional.verdict == LakatosVerdict.PROGRESSIVE_CONDITIONAL
    assert "data_replay_not_proven" in conditional.reasons
    assert degenerating.verdict == LakatosVerdict.DEGENERATING


def test_tree_retains_rejected_branches_but_excludes_them_from_canonical_path():
    tree = LakatosTree(name="T", hard_core=("internet-first",))
    tree.add_node(LakatosNode(name="root", verdict=LakatosVerdict.PROGRESSIVE))
    tree.branch(
        parent="root",
        node=LakatosNode(name="good", verdict=LakatosVerdict.PROGRESSIVE),
    )
    tree.branch(
        parent="root",
        node=LakatosNode(name="bad", verdict=LakatosVerdict.DEGENERATING),
    )

    assert tree.get("bad").verdict == LakatosVerdict.DEGENERATING
    assert [n.name for n in tree.canonical_nodes()] == ["root", "good"]


def test_bash_act_distinguishes_recorded_evidence_from_successful_world_action():
    failed = BashAct(
        name="red",
        command="pytest tests/ -q",
        cwd="/repo",
        exit_code=1,
        stdout_summary="1 failed",
    )
    clean = BashAct(
        name="green",
        command="pytest tests/ -q",
        cwd="/repo",
        exit_code=0,
        stdout_summary="75 passed",
        git_sha="abc123",
    )

    assert failed.evidence_ready().passed
    assert not failed.evidence_ready(require_success=True, require_git_sha=True).passed
    assert clean.evidence_ready(require_success=True, require_git_sha=True).passed


def test_lineage_replay_gate_uses_existing_derivation_topology_and_stale_detection():
    zdf = Derivation("VFEZ0060.zdf", "z0", "", "", [], kind="source", ts="t0")
    rim = Derivation(
        "_rimobs.npz",
        "r0",
        "319.py",
        "s319",
        [("VFEZ0060.zdf", "z0")],
        {"stride": 2},
        "intermediate",
        "t1",
    )
    final = Derivation(
        "perview_v22.json",
        "p0",
        "334.py",
        "s334",
        [("_rimobs.npz", "r0")],
        {"lots": 6},
        "final",
        "t2",
    )

    ok = LineageReplayGate.evaluate(
        "perview_v22.json",
        [zdf, rim, final],
        sources={"VFEZ0060.zdf"},
        current_shas={"VFEZ0060.zdf": "z0", "_rimobs.npz": "r0"},
    )
    stale = LineageReplayGate.evaluate(
        "perview_v22.json",
        [zdf, rim, final],
        sources={"VFEZ0060.zdf"},
        current_shas={"VFEZ0060.zdf": "zNEW", "_rimobs.npz": "r0"},
    )
    gap = LineageReplayGate.evaluate(
        "perview_v22.json",
        [zdf, final],
        sources={"VFEZ0060.zdf"},
    )

    assert ok.passed
    assert [d.output for d in ok.rebuild_plan] == ["_rimobs.npz", "perview_v22.json"]
    assert not stale.passed and stale.stale
    assert "_rimobs.npz" in gap.gaps
