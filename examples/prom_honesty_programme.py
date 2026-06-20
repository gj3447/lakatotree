"""prom-honesty self-audit — LakatoTree 가 *자기 자신의* 정직성 회복을 Lakatos 프로그램으로 도그푸드.

★규율(verdict_provenance / euler 예제와 동일): 노드는 verdict 를 *손입력하지 않는다*. 각 노드는
사전등록 Prediction + NovelTarget + guard_test 만 들고, `run()` 이 **실제 pytest receipt**(이 repo 의
.venv pytest — 독립 측정, self-report 아님)에서 measured/novel_measured 를 *파생*해 `judge()` 가
verdict 를 *생성*한다. 즉 회사가 자기 honesty-recovery 를 자기 결정론 엔진으로 채점한다 = TOUCH THE SKY.

PROM-B 자체를 정직하게 도그푸드한다: novel_measured(guard 통과)는 measured(위협 실패 수)와 *다른*
독립 측정이고 novel metric 도 예측 metric 과 *다르다* → judge 의 독립성 게이트를 통과(가짜 재활용 아님).

KG 계획 거울: LakatosTree_PromHonesty_20260620 (nodes/frontier 는 거기에 사전등록됨).
  · 닫힌 가지(progressive): promA_node_gating(a9d314b) · promB_novel_independence(5743b21)
  · 열린 가지(receipt 미도래 → pending): sha_provenance · promC_oo_roundtrip · promD_doc_honesty
                                          · db_boundary · longinus_grounding
열린 노드는 guard_test 가 아직 없으므로 receipt 에 안 잡힌다 → '영수증 없는 green 은 거짓말'대로 pending.
그 guard_test 가 착륙하면(해당 prom 구현), 같은 harness 재실행이 자동으로 progressive 로 채점한다.

# KG: span_lakatotree_prom_honesty_dogfood / LakatosTree_PromHonesty_20260620
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
# receipt 를 만드는 테스트 파일들 — *닫힌* 가지의 guard 가 사는 곳. 새 prom 구현 시 그 테스트 파일을 추가.
_RECEIPT_TESTS = (
    "tests/test_prom_honesty_node_gating.py "   # promA
    "tests/test_judge.py "                       # promB (novel 독립성) + sha_provenance
    "tests/test_oo_roundtrip.py"                 # promC (외부 store 왕복)
)


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo 의 .venv pytest 를 돌려 {test_func: passed} 수집. self-report 아님.

    같은 함수의 파라미터(SCORED 어휘 등)는 AND 집계 — 하나라도 FAIL 이면 그 함수는 False."""
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {_RECEIPT_TESTS} -v --no-header -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


def _select(rc: dict[str, bool], needles: tuple[str, ...]) -> tuple[int, int]:
    """(위협 테스트 수, 실패 수) — needle 부분일치. 실패 0 = 그 우회/구멍이 닫힘(green=봉쇄)."""
    hit = [ok for name, ok in rc.items() if any(n in name for n in needles)]
    return len(hit), sum(1 for ok in hit if not ok)


@dataclass(frozen=True)
class PromNode:
    tag: str
    parent: str | None
    story: str
    threat_needles: tuple[str, ...] = ()
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_test: str = ""          # 이 가지가 닫은 novel 위협의 *독립* 측정(통과=1.0). receipt 에 없으면 pending.


NODES: tuple[PromNode, ...] = (
    PromNode(
        tag="hard_core", parent=None,
        story="추측: 환각저항은 형식검증 밖 런타임 경계(노드쓰기·novel독립성·외부readback)에 산다 — "
              "그 경계를 런타임이 강제하면 '영수증 없는 green'이 사라진다 (채점 대상 아님, 루트).",
    ),
    # ── 닫힌 가지 (DONE) — judge 가 실제 receipt 에서 progressive 를 *생성* ──────────────────
    PromNode(
        tag="promA_node_gating", parent="hard_core",
        story="[a9d314b] writer.add_node/upsert_nodes 의 무게이트 scored-verdict self-report 정문을 "
              "validator 422 + writer by-construction 으로 봉쇄(scripted∪engine).",
        threat_needles=("rejects_every_scored", "rejects_scored_verdict",
                        "byconstruction_rejects", "set_verdict_403"),
        prediction=Prediction(metric_name="ungated_scored_write_paths", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="노드-쓰기로 scored verdict 주입 봉쇄",
                              closes_question="q-node-self-scoring"),
        novel_target=NovelTarget(metric_name="node_scored_injection_blocked",
                                 direction="higher", threshold=1.0),
        guard_test="test_writer_add_node_byconstruction_rejects_scored",
    ),
    PromNode(
        tag="promB_novel_independence", parent="hard_core",
        story="[5743b21] judge 가 novel_measured==measured(같은 metric) 재활용을 partial 로 강등; "
              "harness 는 독립 novel_measured 만 전송 → 측정 1개로 progressive 공짜 금지.",
        threat_needles=("same_metric_same_measurement_is_not_novel",
                        "independent_metric_is_progressive"),
        prediction=Prediction(metric_name="recycled_novel_accepted", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="같은 측정 재활용 novel 거부(독립 초과내용만)",
                              closes_question="q-novel-independence"),
        novel_target=NovelTarget(metric_name="independence_demotes_to_partial",
                                 direction="higher", threshold=1.0),
        guard_test="test_same_metric_same_measurement_is_not_novel",
    ),
    # ── 열린 가지 (OPEN) — guard_test 미존재 → receipt 없음 → 정직하게 pending ────────────────
    PromNode(
        tag="sha_provenance", parent="promB_novel_independence",
        story="[OPEN] PROM-B 잔여: 같은 metric+값+epsilon 우회는 아직 progressive 가능. novel 측정의 "
              "출처 sha 를 예측 측정과 다르게 강제해 봉쇄.",
        threat_needles=("same_sha_epsilon_rejected", "distinct_sha_is_novel",
                        "same_sha_exact_value_still_rejected"),
        prediction=Prediction(metric_name="same_metric_epsilon_evasion_open", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="출처-sha 상이 강제로 epsilon 우회 봉쇄",
                              closes_question="q-sha-provenance"),
        novel_target=NovelTarget(metric_name="source_sha_distinct_enforced",
                                 direction="higher", threshold=1.0),
        guard_test="test_same_metric_same_sha_epsilon_rejected",
    ),
    PromNode(
        tag="promC_oo_roundtrip", parent="hard_core",
        story="[OPEN] PROM-C: 외부 store readback 이 CI 에선 같은 프로세스가 만든 응답을 대조(영수증 연극). "
              "write→독립read→compare positive 왕복을 외부 백엔드 1개로 CI 에 고정.",
        threat_needles=("oo_positive_roundtrip", "roundtrip_catches_silent"),
        prediction=Prediction(metric_name="unverified_external_arrival_open", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="positive write→read→compare 왕복 green",
                              closes_question="q-oo-roundtrip"),
        novel_target=NovelTarget(metric_name="write_read_compare_roundtrip_green",
                                 direction="higher", threshold=1.0),
        guard_test="test_oo_positive_roundtrip_memory_backend",
    ),
    PromNode(
        tag="promD_doc_honesty", parent="hard_core",
        story="[OPEN] PROM-D: bayes [0,1) 정정·README Rung.derived↔런타임 과장 완화·매니페스토 Wolfram 을 "
              "동기/이미지로 명시(이론근거 아님). 주장↔코드 1:1 대응표.",
        threat_needles=("doc_claims_match_code",),
        prediction=Prediction(metric_name="overclaim_doc_statements_open", direction="lower",
                              baseline_value=3.0, noise_band=0.0,
                              novel_prediction="주장-코드 1:1 대응표로 과장 0",
                              closes_question="q-doc-honesty"),
        novel_target=NovelTarget(metric_name="claim_to_code_1to1_table",
                                 direction="higher", threshold=1.0),
        guard_test="test_doc_claims_match_code",
    ),
    PromNode(
        tag="db_boundary", parent="hard_core",
        story="[OPEN] 감사 잔여: 서버/Neo4j 경계가 한 번도 실행 안 됨(Cypher 부분문자열만 단언). "
              "실드라이버 통합 1개로 write-path 실제 실행.",
        threat_needles=("kg_write_path_real_driver",),
        prediction=Prediction(metric_name="unexecuted_kg_write_paths_open", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="실드라이버 통합 green",
                              closes_question="q-db-boundary"),
        novel_target=NovelTarget(metric_name="real_driver_integration_green",
                                 direction="higher", threshold=1.0),
        guard_test="test_kg_write_path_real_driver",
    ),
    PromNode(
        tag="longinus_grounding", parent="hard_core",
        story="[OPEN] 감사 잔여: semantic_surface 의 external:/kg: ref 가 prefix 만으로 무조건 통과"
              "(미존재도 green). 미존재 ref 가 실패하도록 — 재-실명 회귀가드.",
        threat_needles=("absent_grounding_ref_fails",),
        prediction=Prediction(metric_name="vacuous_prefix_pass_refs_open", direction="lower",
                              baseline_value=16.0, noise_band=0.0,
                              novel_prediction="미존재 external:/kg: ref 실패",
                              closes_question="q-longinus-grounding"),
        novel_target=NovelTarget(metric_name="absent_ref_fails", direction="higher", threshold=1.0),
        guard_test="test_absent_grounding_ref_fails",
    ),
)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 열린 가지는 receipt 없으면 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES:
        if n.prediction is None:                                  # 루트(추측)
            out.append(dict(tag=n.tag, parent=n.parent, verdict="proof",
                            status="ROOT", open_gap=None, surface=None, novel=None))
            continue
        if n.guard_test not in rc:                                # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                            status="OPEN", open_gap=None, surface=0, novel=None,
                            note=f"guard 미존재: {n.guard_test}"))
            continue
        surface, failures = _select(rc, n.threat_needles)
        novel_measured = 1.0 if rc.get(n.guard_test, False) else 0.0
        v = judge(n.prediction, float(failures), n.novel_target, novel_measured)
        out.append(dict(tag=n.tag, parent=n.parent, verdict=v.verdict,   # ★judge 생성
                        status="CLOSED" if v.verdict == "progressive" else "OPEN",
                        open_gap=failures, surface=surface, novel=v.novel,
                        improved=v.improved, reason=v.reason))
    return out


if __name__ == "__main__":
    rc = receipt()
    passed = sum(1 for ok in rc.values() if ok)
    print(f"receipt: {passed}/{len(rc)} prom-honesty test funcs PASSED (.venv pytest, 독립 측정)\n")
    for r in run(rc):
        if r["status"] == "ROOT":
            tail = "(추측·루트)"
        elif r["surface"] == 0 and r["verdict"].startswith("pending"):
            tail = f"pending — {r.get('note', '')}"
        else:
            tail = f"open_gap={r['open_gap']}/{r['surface']}  novel={r.get('novel')}"
        print(f"  {r['tag']:24} → {r['verdict']:20} {tail}")
    print("\nKG 거울: LakatosTree_PromHonesty_20260620 "
          "(닫힌 2 + 열린 5 + frontier 7). 열린 가지의 guard_test 가 착륙하면 재실행이 자동 채점.")
