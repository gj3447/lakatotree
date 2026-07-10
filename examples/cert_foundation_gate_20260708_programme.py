"""cert-foundation-gate programme — 첫 적대적 인증서 *소비자*(keystone) 진보 채점.

deep-think 2026-07-08(wf_e41a7b9d-d64) GO게이트=NONE: 어떤 결정도 certified 를 읽지 않는다
(G6/attested/engine_rule_sha 전부 prophylactic). 이 게이트가 그 빈 소비자 슬롯을 채운다 —
opt-in 트리(require_certified_evidence)에서 근거-기반 satisfied foundation requirement 의 evidence_refs
가 실제 certified 노드(node_certificate=true ∧ 영수증 체인 무결)로 해소될 때만 satisfied 유지, 아니면
needed 강등 → FoundationGate gap → synthesize_promotion → CANONICAL 승격 fail-closed.

★규율: verdict 손입력 금지 — judge() 생성. 진보축=음성 오라클(미인증/배선 강등), novel축=양성+fail-safe+비파괴.
★단방향 안전: satisfied→gap 만(fail-open 아님). non-colliding: 커널·CANONICAL floor 미편집, 기존 검증기 재사용.
# KG 거울: LakatosTree_JudgeProprioception_20260708 / jp7-cert-consumer
쓰임:  .venv/bin/python examples/cert_foundation_gate_20260708_programme.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUARD = "tests/test_cert_foundation_gate.py"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 가드 전수 실행 → {test_func: passed} (self-report 아님)."""
    cmd = f"cd {_ROOT} && .venv/bin/python -m pytest {_GUARD} -v --no-header -p no:cacheprovider 2>&1"
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            res[m.group(1)] = res.get(m.group(1), True) and (m.group(2) == "PASSED")
    return res


def main() -> int:
    r = receipt()
    # 진보축(defect-closed): 음성 오라클 — 미인증 근거가 강등되고(순수) 서버 배선도 강등한다(통합).
    defect_ok = (r.get("test_guard_defect_uncertified_evidence_downgrades_to_gap", False)
                 and r.get("test_provider_flag_on_downgrades_uncertified", False))
    # novel축(mechanism 실재): 양성 오라클(인증 근거 보존=over-broad 방지) + fail-safe + 비파괴(flag-off 바이트동일).
    mech_ok = all(r.get(k, False) for k in (
        "test_guard_mechanism_certified_evidence_stays_satisfied",
        "test_evidence_ok_failsafe_on_lookup_error",
        "test_provider_flag_off_is_byte_identical"))

    measured = 1.0 if defect_ok else 0.0
    novel_measured = 1.0 if mech_ok else 0.0

    pred = Prediction(metric_name="cert_consumer_blocks", direction="higher", baseline_value=0.0)
    nt = NovelTarget(metric_name="cert_consumer_mechanism", direction="higher", threshold=1.0)
    v = judge(pred, measured, novel_target=nt, novel_measured=novel_measured,
              measured_sha="cfg_defect_oracle", novel_sha="cfg_mech_oracle")   # distinct 출처

    print(f"cert-foundation-gate keystone — 가드 {len(r)}개 실행")
    print(f"  defect_ok(강등)={defect_ok}  mech_ok(양성+failsafe+비파괴)={mech_ok}")
    print(f"  ⇒ verdict={v.verdict}  (measured={measured} novel_measured={novel_measured}) [엔진 생성·손입력 0]")
    if v.verdict != "progressive":
        print("  ⚠ 가드 미착륙 — 정직 pending (fake green 금지)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
