"""Programme-as-series diagnostic OOPTDD receipts."""

import pytest

from lakatos.programme.series import (
    DIAGNOSTIC_ONLY_AUTHORITY,
    ProgrammeSeriesRecord,
    programme_series_appraisal,
    series_from_path,
)
from lakatos.quant.laudan import RivalProblemRecord


# ── #5: bridge — series_from_path 가 laudan 개념/비교 진단을 실제로 호출(두 고아 절반 연결) ──

def test_series_from_path_invokes_laudan_conceptual_and_rival():
    """경로 노드의 internal/external 개념문제 → laudan.conceptual_problem_score, 라이벌 해결 →
    laudan.rival_relative_anomaly 가 series 레코드를 채운다(전엔 둘이 단절)."""
    path = [
        {'tag': 'n1', 'verdict': 'progressive', 'problem_balance_delta': 1},
        {'tag': 'n2', 'verdict': 'partial', 'problem_balance_delta': -1,
         'internal_inconsistency': 2, 'external_conflict': 1,        # → conceptual_problem_score=3.0
         'problem': 'P'},                                            # 라이벌이 P 해결 → anomaly
    ]
    rivals = [RivalProblemRecord('rivalX', 'P', solved=True)]
    appraisal = series_from_path(path, rival_records=rivals, target_programme='target')

    assert appraisal.authority == DIAGNOSTIC_ONLY_AUTHORITY and appraisal.promotion_authority is False
    assert appraisal.conceptual_problem_score == 3.0      # laudan.conceptual_problem_score 실호출
    assert appraisal.rival_anomaly_count == 1             # laudan.rival_relative_anomaly 실호출
    assert appraisal.problem_balance_total == 0           # 1 + (-1)
    assert appraisal.trend == 'degenerating'             # 비진보 + 진단 압력


def test_series_from_path_skips_offdiagnostic_verdicts_honestly():
    """CANONICAL/progressive_conditional 등 series 어휘 밖 판결은 진단 레코드로 만들지 않는다(날조 금지)."""
    path = [
        {'tag': 'root', 'verdict': 'CANONICAL'},                # 진단축 밖 → 제외
        {'tag': 'n1', 'verdict': 'progressive'},
    ]
    appraisal = series_from_path(path)
    assert appraisal.steps == 1 and appraisal.progressive_count == 1


def test_series_from_path_no_rival_data_no_anomaly():
    """라이벌 레코드 없으면 anomaly 안 뜸 — 데이터 부재를 압력으로 날조하지 않음."""
    path = [{'tag': 'n1', 'verdict': 'progressive', 'problem': 'P'}]
    appraisal = series_from_path(path, target_programme='target')
    assert appraisal.rival_anomaly_count == 0


def test_series_appraisal_marks_sustained_progress_without_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive", problem_balance_delta=1),
            ProgrammeSeriesRecord("n2", "progressive", problem_balance_delta=0),
        ]
    )

    assert appraisal.trend == "progressive"
    assert appraisal.authority == DIAGNOSTIC_ONLY_AUTHORITY
    assert appraisal.promotion_authority is False
    assert appraisal.progressive_count == 2
    assert appraisal.problem_balance_total == 1


def test_series_appraisal_marks_degenerating_series_with_rival_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "partial", problem_balance_delta=-1),
            ProgrammeSeriesRecord("n2", "rejected", problem_balance_delta=-1, rival_anomaly=True),
            ProgrammeSeriesRecord("n3", "equivalent", problem_balance_delta=0),
        ]
    )

    assert appraisal.trend == "degenerating"
    assert appraisal.nonprogressive_count == 3
    assert appraisal.rival_anomaly_count == 1
    assert any("rival" in reason for reason in appraisal.reasons)


def test_different_programme_is_off_axis_not_degenerating_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("fork", "different_programme", problem_balance_delta=-5),
        ]
    )

    assert appraisal.trend == "off_axis"
    assert appraisal.off_axis_count == 1
    assert appraisal.nonprogressive_count == 0
    assert appraisal.problem_balance_total == 0


def test_conceptual_pressure_stays_diagnostic_only():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive"),
            ProgrammeSeriesRecord("n2", "progressive", conceptual_problem_score=2.0),
        ]
    )

    assert appraisal.trend == "mixed"
    assert appraisal.conceptual_problem_score == 2.0
    assert appraisal.promotion_authority is False
    assert any("conceptual" in reason for reason in appraisal.reasons)


def test_series_record_rejects_empty_tag_unknown_verdict_and_bad_scores():
    with pytest.raises(ValueError, match="tag"):
        ProgrammeSeriesRecord("", "progressive")
    with pytest.raises(ValueError, match="verdict"):
        ProgrammeSeriesRecord("n1", "magic")
    with pytest.raises(ValueError, match="conceptual_problem_score"):
        ProgrammeSeriesRecord("n1", "progressive", conceptual_problem_score=-0.1)


def test_recent_window_is_positive_and_uses_latest_steps():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive"),
            ProgrammeSeriesRecord("n2", "rejected", rival_anomaly=True),
        ],
        recent_window=1,
    )

    assert appraisal.trend == "degenerating"
    assert appraisal.steps == 1
    assert appraisal.progressive_count == 0

    with pytest.raises(ValueError, match="recent_window"):
        programme_series_appraisal([], recent_window=0)
