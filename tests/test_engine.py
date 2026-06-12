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
    FoundationGate,
    FoundationMap,
    FoundationRequirement,
    InternetObservation,
    KnowledgeKind,
    LakatosEvidence,
    LakatosGate,
    LakatosNode,
    LakatosTree,
    LakatosVerdict,
    LineageReplayGate,
    ObservationLedger,
    Possibility,
    Realm,
    ReproducibilityContract,
    ResearchEvent,
    ResearchFrame,
    ResearchProject,
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


def test_research_frame_keeps_sparse_possibilities_and_append_only_events():
    frame = ResearchFrame(
        ResearchProject(
            name="materials-lab",
            goal="explain repeated measurement drift",
            root_artifacts=("raw://experiment/lot-001",),
        )
    )
    frame.open_possibility(Possibility("p1", "is the drift from calibration?"))
    frame.open_possibility(Possibility("p2", "is the drift from sample geometry?", parent="p1"))
    frame.record_event(
        ResearchEvent(
            name="evt-web-1",
            realm=Realm.INTERNET,
            actor="agent:researcher",
            action="fetch_source",
            target="p1",
            evidence_refs=("obs:paper-1",),
            payload=(("trust", "0.82"),),
        )
    )
    frame.record_event(
        ResearchEvent(
            name="evt-human-1",
            realm=Realm.HUMAN,
            actor="human:reviewer",
            action="doubt",
            target="p1",
            evidence_refs=("comment:needs-replay",),
        )
    )

    standing = frame.standing("p1")
    assert [p.name for p in frame.possibilities()] == ["p1", "p2"]
    assert standing["state"] == "open"
    assert standing["event_count"] == 2
    assert standing["realms"] == ["human", "internet"]
    assert frame.events()[0].db_record()["payload"] == {"trust": "0.82"}


def test_foundation_map_tracks_required_base_knowledge_and_gates_research():
    foundation = FoundationMap()
    foundation.add(
        FoundationRequirement(
            name="lakatos-program-theory",
            kind=KnowledgeKind.THEORY,
            question="what counts as progressive rather than degenerating?",
            why_needed="prevents the tree from treating every branch as absolute truth",
            acceptance_criteria=("progressive/degenerated distinction recorded",),
            evidence_refs=("THEORY.md#lakatos",),
            status="satisfied",
        )
    )
    foundation.add(
        FoundationRequirement(
            name="metric-contract",
            kind=KnowledgeKind.METRIC,
            question="which metric judges a branch and when does it break?",
            why_needed="prevents metric relabel from looking like continuous progress",
            acceptance_criteria=("metric_name", "direction", "noise_band", "relabel rule"),
        )
    )

    gate = FoundationGate.evaluate(foundation)

    assert not gate.passed
    assert gate.reasons == ("metric-contract",)
    assert foundation.gaps()[0].kind == KnowledgeKind.METRIC
    assert foundation.summary()["required"] == 2
    assert foundation.summary()["satisfied"] == 1


def test_default_foundation_requirements_are_sparse_and_domain_agnostic():
    foundation = FoundationMap.default_for_project(
        ResearchProject(name="new-lab", goal="study a measurement problem")
    )
    kinds = {req.kind for req in foundation.requirements()}

    assert KnowledgeKind.THEORY in kinds
    assert KnowledgeKind.DATA in kinds
    assert KnowledgeKind.METRIC in kinds
    assert KnowledgeKind.REPRODUCIBILITY in kinds
    assert all("BPC" not in req.name and "ZDF" not in req.name for req in foundation.requirements())


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
    raw = Derivation("raw://experiment/lot-0060", "raw0", "", "", [], kind="source", ts="t0")
    rim = Derivation(
        "cache://edge-observations",
        "cache0",
        "extract_edges.py",
        "sha-extract",
        [("raw://experiment/lot-0060", "raw0")],
        {"stride": 2},
        "intermediate",
        "t1",
    )
    final = Derivation(
        "artifact://joint-model",
        "model0",
        "solve_model.py",
        "sha-solve",
        [("cache://edge-observations", "cache0")],
        {"lots": 6},
        "final",
        "t2",
    )

    ok = LineageReplayGate.evaluate(
        "artifact://joint-model",
        [raw, rim, final],
        sources={"raw://experiment/lot-0060"},
        current_shas={"raw://experiment/lot-0060": "raw0", "cache://edge-observations": "cache0"},
    )
    stale = LineageReplayGate.evaluate(
        "artifact://joint-model",
        [raw, rim, final],
        sources={"raw://experiment/lot-0060"},
        current_shas={"raw://experiment/lot-0060": "rawNEW", "cache://edge-observations": "cache0"},
    )
    gap = LineageReplayGate.evaluate(
        "artifact://joint-model",
        [raw, final],
        sources={"raw://experiment/lot-0060"},
    )

    assert ok.passed
    assert [d.output for d in ok.rebuild_plan] == ["cache://edge-observations", "artifact://joint-model"]
    assert not stale.passed and stale.stale
    assert "cache://edge-observations" in gap.gaps


def test_reproducibility_contract_is_project_root_agnostic():
    raw = Derivation("raw://spectrometer/run-1", "raw1", "", "", [], kind="source")
    final = Derivation(
        "artifact://report",
        "report1",
        "build_report.py",
        "sha-report",
        [("raw://spectrometer/run-1", "raw1")],
        kind="final",
    )
    contract = ReproducibilityContract(
        final_artifact="artifact://report",
        root_artifacts=("raw://spectrometer/run-1",),
    )

    result = contract.evaluate([raw, final], current_shas={"raw://spectrometer/run-1": "raw1"})

    assert result.passed
    assert result.roots == ("raw://spectrometer/run-1",)
