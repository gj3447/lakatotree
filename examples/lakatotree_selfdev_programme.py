"""LakatoTree self-dev — create_tree 온보딩 갭 수정을 LakatoTree 가 *자기 자신의* R&D 로 도그푸드.

★규율(prom_honesty / bhgman 예제와 동일): 노드는 verdict 를 *손입력하지 않는다*. 각 노드는 사전등록
Prediction + 독립 NovelTarget + guard_test 만 들고, run() 이 **실제 pytest receipt**(이 repo .venv pytest,
독립 측정)에서 measured/novel_measured 를 *파생*해 judge() 가 verdict 를 *생성*한다. 즉 create_tree 를
노출하는 작업 자체를 그 작업이 손본 엔진으로 채점한다(재귀 도그푸드).

추측: 나무 생성은 published surface(REST POST + MCP tool + CLI)에서 first-class 여야 하고, 존재하지 않는
나무로의 add_node 는 침묵 성공이 아니라 fail-loud(404)여야 한다 — 온보딩은 일급 표면이며, 침묵 무성공은
환각 표면이다.

PROM-B 독립성: 개선 metric(노출 안 된 생성 표면 수, lower)과 novel metric(add_node-missing=404 fail-loud,
다른 코드경로의 다른 축)이 *다르다* → judge 독립성 게이트 통과(가짜 재활용 아님).

# KG: span_lakatotree_selfdev_create_tree_dogfood / LakatosTree_LakatoTree_SelfDev_20260612
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
_RECEIPT_TESTS = (
    "tests/test_create_tree_surface.py "          # REST(service)+MCP+CLI 노출
    "tests/test_add_node_missing_tree_404.py"     # novel 축: missing-tree add_node = 404
)


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 를 돌려 {test_func: passed} 수집(self-report 아님)."""
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
    """(위협 테스트 수, 실패 수). 실패 0 = 그 표면 갭이 닫힘(green=노출됨)."""
    hit = [ok for name, ok in rc.items() if any(n in name for n in needles)]
    return len(hit), sum(1 for ok in hit if not ok)


@dataclass(frozen=True)
class SelfDevNode:
    tag: str
    parent: str | None
    story: str
    threat_needles: tuple[str, ...] = ()
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_test: str = ""          # novel 축의 *독립* 측정(통과=1.0). receipt 에 없으면 pending.


SELFDEV_NODES: tuple[SelfDevNode, ...] = (
    SelfDevNode(
        tag="hard_core", parent=None,
        story="추측: 나무 생성은 REST/MCP/CLI 일급 표면이어야 하고, 없는 나무로의 add_node 는 fail-loud(404). "
              "온보딩은 일급 표면이며 침묵 무성공은 환각 표면이다 (채점 대상 아님, 루트).",
    ),
    # ── 닫힌 가지(DONE) — judge 가 실제 receipt 에서 progressive 를 *생성* ─────────────────────
    SelfDevNode(
        tag="create_tree_surface", parent="hard_core",
        story="create_tree 를 REST(POST /api/tree/{name}) + MCP tool + CLI(tree-create) 세 표면에 노출 — "
              "기존 upsert_tree 에 배선. 전엔 POST /api/tree/{name}=405·MCP/CLI 툴 없음이라 신규 트리에 "
              "add_node 가 404 만 받고 만들 길이 없었다. 개선=노출 안 된 생성 표면 0 으로. "
              "novel=add_node-missing-tree fail-loud 404(다른 코드경로의 독립 축).",
        threat_needles=("create_tree", "tree_create"),
        prediction=Prediction(metric_name="unexposed_tree_creation_surfaces", direction="lower",
                              baseline_value=3.0, noise_band=0.0,
                              novel_prediction="create_tree REST+MCP+CLI 노출",
                              closes_question="q-create-tree-surface"),
        # ★novel 은 *다른* metric·다른 코드경로(write-path 의 missing-tree 가드) — judge P2 독립성 통과
        novel_target=NovelTarget(metric_name="add_node_missing_tree_fails_loud_404",
                                 direction="higher", threshold=1.0),
        guard_test="test_add_node_to_missing_tree_is_404_not_silent",
    ),
    # ── 열린 가지(OPEN) — guard_test 미존재 → receipt 없음 → 정직하게 pending ──────────────────
    SelfDevNode(
        tag="writer_silent_match_hardening", parent="create_tree_surface",
        story="[OPEN] defense-in-depth 잔여: writer.add_node 의 raw MATCH 는 직접 호출 시(service/load_tree_data "
              "우회) 여전히 침묵 no-op 가능. RETURN t 로 0행 감지→TreeNotFound 하드닝은 kg_tx 테스트 스텁 대거 "
              "갱신을 요해 별도 작업으로 남김. guard 착륙 시 재실행이 자동 채점.",
        threat_needles=("writer_add_node_missing_tree_raises",),
        prediction=Prediction(metric_name="writer_silent_match_noop_open", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="writer 레벨에서도 missing-tree 가 0 노드 write + raise",
                              closes_question="q-writer-silent-match"),
        novel_target=NovelTarget(metric_name="writer_level_fail_loud",
                                 direction="higher", threshold=1.0),
        guard_test="test_writer_add_node_missing_tree_raises",
    ),
)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 열린 가지는 receipt 없으면 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in SELFDEV_NODES:
        if n.prediction is None:                                  # 루트(추측)
            out.append(dict(tag=n.tag, parent=n.parent, verdict="canonical_stage",
                            status="ROOT", surface=None, novel=None))
            continue
        if n.guard_test not in rc:                                # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                            status="OPEN", surface=0, novel=None,
                            note=f"guard 미존재: {n.guard_test}"))
            continue
        surface, failures = _select(rc, n.threat_needles)
        novel_measured = 1.0 if rc.get(n.guard_test, False) else 0.0
        v = judge(n.prediction, float(failures), n.novel_target, novel_measured)
        out.append(dict(tag=n.tag, parent=n.parent, verdict=v.verdict,   # ★judge 생성
                        status="CLOSED" if v.verdict == "progressive" else "OPEN",
                        surface=surface, failures=failures,
                        novel=v.novel, improved=v.improved, reason=v.reason))
    return out


# ── KG 거울용 dict (sync_lakatos_programme_to_kg.py 가 읽는 단일 진실) — verdict 는 stage 라벨만 ──
def _kg_node(n: SelfDevNode) -> dict:
    pred, nov = n.prediction, n.novel_target
    return dict(
        tag=n.tag,
        verdict="canonical_stage",          # stage 라벨(채점 아님) — 진보성은 run() 의 judge() 권위
        parent=n.parent,
        comment=n.story,
        limitation=("novel metric != 개선 metric (judge P2 독립성): "
                    f"improve={pred.metric_name} / novel={nov.metric_name}" if pred else
                    "하드코어 추측: 나무 생성=일급 표면, missing-tree add_node=fail-loud"),
        algorithm="surface-exposure" if pred else "conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in SELFDEV_NODES]

FRONTIER = [
    dict(name="q-writer-silent-match", status="OPEN", closed_by=None,
         body="writer.add_node 의 raw MATCH no-op 을 writer 레벨에서도 fail-loud 로(RETURN t→TreeNotFound). "
              "kg_tx 테스트 스텁 대거 갱신 필요 → 별도 작업(defense-in-depth)."),
]


if __name__ == "__main__":
    rc = receipt()
    passed = sum(1 for ok in rc.values() if ok)
    print(f"receipt: {passed}/{len(rc)} self-dev test funcs PASSED (.venv pytest, 독립 측정)\n")
    for r in run(rc):
        if r["status"] == "ROOT":
            tail = "(추측·루트)"
        elif r["verdict"].startswith("pending"):
            tail = f"pending — {r.get('note', '')}"
        else:
            tail = f"failures={r['failures']}/{r['surface']}  novel={r.get('novel')}  improved={r.get('improved')}"
        print(f"  {r['tag']:30} → {r['verdict']:20} {tail}")
    print("\nKG 거울: LakatosTree_LakatoTree_SelfDev_20260612 "
          "(닫힘 1: create_tree_surface · 열림 1: writer_silent_match_hardening). verdict 전부 judge() 생성.")
