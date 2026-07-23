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


def test_pidna_marks_the_hswm_runtime_as_a_target_not_a_current_claim():
    pidna = (ROOT / "docs" / "PIDNA.md").read_text(encoding="utf-8")

    assert "HSWM 네트워크에서 회전의 실행 의미" in pidna
    assert "현재 구현 경계" in pidna
    assert "verdict-driven 자동" in pidna
