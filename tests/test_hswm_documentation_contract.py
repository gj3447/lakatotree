"""Keep the HSWM direction causal, optional-BHGMAN, and honest about runtime scope."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_does_not_claim_the_target_is_already_the_runtime():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "does **not yet** provide a generic agent-attachment protocol" in readme
    assert "changing only the verdict must change the next dispatch" in readme
    assert "BHGMAN is not required" in readme


def test_hswm_contract_defines_attachment_as_causal_feedback():
    contract = (ROOT / "docs" / "HSWM_AGENT_NETWORK.md").read_text(encoding="utf-8")

    for phase in ("Proposal", "Observation", "Verdict", "Commit"):
        assert phase in contract
    for step in ("Attach", "Context", "Propose", "Execute", "Observe", "Adjudicate", "Commit", "Redispatch"):
        assert f"**{step}**" in contract

    assert "X != Y" in contract
    assert "BHGMAN 결합 | 예제 adapter | 선택 사항" in contract
    assert "범용 agent attach/capability 계약 | 미구현" in contract
    assert "verdict가 다음 agent 행동을 자동 변경 | 미구현" in contract


def test_hswm_feedback_freezes_runtime_done_and_stop_gates():
    contract = (ROOT / "docs" / "HSWM_AGENT_NETWORK.md").read_text(encoding="utf-8")

    assert "지금 HSWM의 가장 큰 문제" in contract
    assert "runtime code owner" in contract
    assert "causal A/B receipt" in contract
    assert "재실행 가능한 demo receipt" in contract
    assert "duplicate event는 exactly-once effect" in contract
    assert "설계 문서나 mock trace만으로 runtime gap을 `covered`로 승격" in contract


def test_pidna_marks_the_hswm_runtime_as_a_target_not_a_current_claim():
    pidna = (ROOT / "docs" / "PIDNA.md").read_text(encoding="utf-8")

    assert "HSWM 네트워크에서 회전의 실행 의미" in pidna
    assert "현재 구현 경계" in pidna
    assert "verdict-driven 자동" in pidna


def test_research_programme_preregisters_value_baselines_and_kill_criteria():
    programme = (ROOT / "docs" / "HSWM_RESEARCH_PROGRAMME.md").read_text(encoding="utf-8")

    assert "RUN THE NEXT DISCRIMINATING EXPERIMENT" in programme
    assert "Validated Progress per Cost (VPC)" in programme
    for baseline in ("B0 Plain agent", "B1 Shared log/KG", "B2 LakatoTree audit", "B3 Full HSWM", "B4 HSWM non-hypergraph ablation"):
        assert baseline in programme

    assert "두 개의 사전등록되고 충분한 검정력을 가진 서로 다른 task family" in programme
    assert "H2 실패 → hypergraph 본질 주장만 prune" in programme
    assert "H1 실패 → HSWM 성능 주장 prune" in programme
    assert "H1 vertical slice 전에 새로운 철학자·메타포·판정층을 추가하지 않는다" in programme


def test_readme_links_the_design_and_the_research_decision_separately():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/HSWM_AGENT_NETWORK.md" in readme
    assert "docs/HSWM_RESEARCH_PROGRAMME.md" in readme
