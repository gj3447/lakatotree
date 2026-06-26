"""bhgman_tool governance/audit substrate — Lakatos 연구 프로그램 도그푸드 (onboarding).

★규율(verdict_provenance / prom_honesty / euler 예제와 동일): 노드는 verdict 를 *손입력하지
않는다*. 각 노드는 사전등록 Prediction + 구조적 NovelTarget(개선 metric 과 *다른* metric) 만
데이터로 들고, `run()` 이 **bhgman 자신의 결정론 oracle**(subprocess → 독립 receipt, self-report
아님)에서 measured/novel_measured 를 *파생*해 `judge()` 가 verdict 를 *생성*한다. 즉 bhgman 의
정체성("결정론 검증 substrate, 추론 capability multiplier 가 아님")을 그 자신의 oracle 로 도그푸드.

하드코어(추측, 채점 대상 아님):
  bhgman = 결정론 거버넌스/감사 substrate (determinism + exhaustiveness + idempotence +
  signed audit trail) — NOT a capability multiplier. 추론력을 더하지 않는다; 추론기(ultracode)가
  *호출*하는, LLM-disjoint·zero-token·재현가능 검증면을 제공할 뿐이다 (user verdict 2026-06-04).

★이 프로그램의 핵심 정직성: capability-multiplier 는 *대담한 예측으로 등록하지 않는다*. bhgman
자신의 A/B 증거가 그것을 반증하기 때문(loop = neutral-to-worse at bhgman's scale). 대신 그것을
FRONTIER 의 q-capability-multiplier 로 *열린 채로* 둔다 ("by design open"). 등록되는 예측은 오직
substrate 속성(drift 봉쇄 / lean proof-goal 검증)뿐.

receipt 출처(전부 bhgman 의 *자기* oracle, ABSOLUTE venv 경로 — `uv run` 은 무겁고 여기선 broken):
  · drift-recount : `bhgman-tool oracle --kind drift-recount --code-root engine --local --json`
                    → 현재 score=-436 (436 KG↔code drift), passed=false = *정직한* receipt.
                    judge() 는 따라서 non-progressive(rejected) 를 *생성*한다 — 그게 POINT. 위조 금지.
  · lean-goals    : `bhgman-tool oracle --kind lean-goals --target <self-contained .lean> --json`
                    → lean 툴체인 가용 시 exit0 + closed-goal count(여기선 score=8 progressive),
                    툴체인 부재/compile 실패 시 oracle 이 -1000(또는 CLI exit2)을 낸다 → pending(no-receipt)
                    로 매핑(NaN 을 judge 에 먹이지 않는다).

novel metric 독립성(judge P2 게이트): 각 가지의 NovelTarget metric 은 개선 metric 과 *다르다* —
  · drift 가지 : 개선=kg_code_drift_count(lower) / novel=recount_idempotent(higher, oracle 2회
                 재실행이 *동일* score → 결정론·idempotence 의 독립 측정). 가짜 재활용 아님.
  · lean 가지  : 개선=closed_lean_goals(higher) / novel=proof_checker_exit0(higher, substrate-disjoint
                 proof-checker 의 exit-0 하드게이트 — count 와 다른, 건전성의 독립 측정).

# KG 거울: LakatosTree_BhgmanGovernance_20260624 (live LakatosTree_VerdictProvenanceGate_20260620 와 비충돌)
#          anchor: SA_BhgmanGovernanceAudit_20260624
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_BHGMAN = "<WORKSPACE>/PROJECT/PI/bhgman_tool"
_BIN = f"{_BHGMAN}/.venv/bin/bhgman-tool"   # ABSOLUTE venv — NOT `uv run` (heavy/broken here)
# 자족 .lean(비-prelude import 없음 → lakefile 불필요, oracle 의 self-contained 제약 충족)
_LEAN_TARGET = "lean/Measurement_MetricScale.lean"
_LEAN_DIR = "lean"

# oracle 미가용/툴체인부재 sentinel — score==-1000(lean compile/toolchain fail) 또는 CLI exit2(KG 미가용).
_LEAN_FAIL_SENTINEL = -1000.0


def _oracle(args: list[str]) -> dict | None:
    """bhgman 자신의 결정론 oracle 을 subprocess 로 호출 → JSON verdict dict. self-report 아님.

    CLI exit 2 = KG/인프라 미가용 → None(=pending, 숫자 아님). exit 0/1 은 JSON 을 그대로 반환
    (passed=false 도 *정직한* receipt 이므로 숫자로 전달). NaN/미가용을 judge 에 먹이지 않기 위해
    None 분기를 호출부가 pending 으로 처리한다."""
    proc = subprocess.run(
        [_BIN, "oracle", *args, "--json"],
        cwd=_BHGMAN, capture_output=True, text=True,
    )
    if proc.returncode == 2:          # KG/인프라 미가용 (occam/drift) — receipt 없음
        return None
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, IndexError):
        return None                   # 파싱 불가 = receipt 없음 → pending (숫자 아님)


def drift_receipt() -> dict | None:
    """KG↔code drift recount (negated score; 0=best). 현재 passed=false (정직한 비진보 receipt)."""
    return _oracle(["--kind", "drift-recount", "--code-root", "engine", "--local"])


def drift_idempotent() -> float | None:
    """novel(독립 metric): oracle 2회 재실행이 *동일* score 면 1.0 (결정론·idempotence 의 독립 측정).

    개선 metric(drift count)과 다른 축 — 같은 측정 재활용이 아니다(judge P2 독립성 게이트 통과)."""
    a = drift_receipt()
    b = drift_receipt()
    if a is None or b is None:
        return None
    return 1.0 if a.get("score") == b.get("score") else 0.0


def lean_receipt() -> dict | None:
    """self-contained .lean proof-goal oracle. 툴체인 가용 시 closed-goal count, 부재 시 -1000."""
    return _oracle(["--kind", "lean-goals", "--target", _LEAN_TARGET, "--lean-dir", _LEAN_DIR])


@dataclass(frozen=True)
class GovNode:
    """프로그램의 한 노드. ★verdict 필드 없음(런타임 judge 생성). KG 거울은 NODES dict 가 따로 든다."""
    tag: str
    parent: str | None
    story: str
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    hard_core_preserved: bool = True


# ── 프로그램 트리 (dataclass = 런타임 채점 단위) ────────────────────────────────────
GOV_NODES: tuple[GovNode, ...] = (
    GovNode(
        tag="hard_core", parent=None,
        story="추측: bhgman = 결정론 거버넌스/감사 substrate(determinism+exhaustiveness+idempotence+"
              "signed audit trail), NOT a capability multiplier (채점 대상 아님, 루트).",
    ),
    GovNode(
        tag="drift_governance", parent="hard_core",
        story="감사 가지: KG↔code drift 를 결정론 recount 로 *전수* 적발(exhaustiveness). 개선=drift 0 으로 "
              "감소(현재 436 → passed=false, 정직한 비진보). novel=재실행 idempotence(다른 축).",
        # 개선 metric: drift count(lower=better). baseline 0 = '드리프트 없음' 추측 → 436 측정이 반증.
        prediction=Prediction(metric_name="kg_code_drift_count", direction="lower",
                              baseline_value=0.0, noise_band=0.0,
                              novel_prediction="recount 가 결정론적으로 동일(idempotent)",
                              closes_question="q-bhg-drift-exhaustive"),
        # ★novel 은 *다른* metric: 같은 oracle 2회가 동일 score → 결정론/idempotence (개선 metric 과 독립)
        novel_target=NovelTarget(metric_name="recount_idempotent", direction="higher",
                                 threshold=1.0),
    ),
    GovNode(
        tag="lean_proof_gate", parent="hard_core",
        story="검증 가지: 자족 .lean 의 proof-goal 을 substrate-disjoint proof-checker(lean) 로 검증. "
              "개선=closed-goal count(higher). novel=exit-0 하드게이트(건전성의 독립 측정, count 와 다른 축).",
        # 개선 metric: closed lean goals(higher=better). baseline 0 = '검증된 goal 없음' → 측정 8 이 초과.
        prediction=Prediction(metric_name="closed_lean_goals", direction="higher",
                              baseline_value=0.0, noise_band=0.0,
                              novel_prediction="proof-checker exit-0 하드게이트 통과(LLM-disjoint 검증)",
                              closes_question="q-bhg-lean-proof-gate"),
        # ★novel 은 *다른* metric: exit-0 하드게이트(건전성) — closed-goal *수* 와 독립한 sound-gate 측정
        novel_target=NovelTarget(metric_name="proof_checker_exit0", direction="higher",
                                 threshold=1.0),
    ),
)


def run() -> list[dict]:
    """프로그램을 엔진에 태운다 — 각 노드 verdict 를 judge() 가 *생성*. measured 는 oracle receipt 파생, 손입력 0.

    오라클 미가용/툴체인부재(receipt 없음) → pending(no-receipt), 숫자(NaN 포함) 를 judge 에 먹이지 않는다."""
    out: list[dict] = []

    # receipt 를 노드별로 1회씩만 취득(중복 호출 방지). drift idempotence 는 별도 2회.
    drift = drift_receipt()
    lean = lean_receipt()

    for n in GOV_NODES:
        if n.prediction is None:                              # 루트(추측) — 채점 대상 아님
            out.append(dict(tag=n.tag, parent=n.parent, verdict="canonical_stage",
                            status="ROOT", measured=None, novel=None, receipt=None))
            continue

        if n.tag == "drift_governance":
            if drift is None:                                 # 인프라 미가용 → 정직한 pending
                out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                                status="PENDING", measured=None, novel=None,
                                note="drift oracle receipt 없음(KG/인프라 미가용)", receipt=None))
                continue
            measured = float(-drift["score"])                 # negated → 실제 drift 수(436). passed 무시 안 함.
            novel_measured = drift_idempotent()               # 독립 metric 측정(2회 재실행 동일?)
            if novel_measured is None:
                novel_measured = 0.0                          # 재현 불가 = novel 미확증(숫자, NaN 아님)
            v = judge(n.prediction, measured, n.novel_target, novel_measured)
            out.append(dict(
                tag=n.tag, parent=n.parent,
                verdict=v.verdict,                            # ★judge 생성 — 손입력 아님
                status="SCORED",
                measured=measured, drift_count=int(measured),
                oracle_passed=bool(drift["passed"]),          # bhgman 자신의 게이트 (false=정직)
                novel=v.novel, improved=v.improved,
                reason=v.reason, receipt=drift,
            ))
            continue

        if n.tag == "lean_proof_gate":
            # 툴체인 부재/compile 실패 → score==-1000 (또는 None). receipt 없음으로 pending.
            if lean is None or lean.get("score") == _LEAN_FAIL_SENTINEL:
                why = ("lean compile/toolchain 부재(score=-1000)" if lean is not None
                       else "lean oracle receipt 없음")
                out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                                status="PENDING", measured=None, novel=None,
                                note=why, receipt=lean))
                continue
            measured = float(lean["score"])                   # closed-goal count(8). passed=True 가 게이트.
            novel_measured = 1.0 if lean.get("passed") else 0.0   # 독립 metric: exit-0 하드게이트
            v = judge(n.prediction, measured, n.novel_target, novel_measured)
            out.append(dict(
                tag=n.tag, parent=n.parent,
                verdict=v.verdict,                            # ★judge 생성
                status="SCORED",
                measured=measured, closed_goals=int(measured),
                oracle_passed=bool(lean["passed"]),
                novel=v.novel, improved=v.improved,
                reason=v.reason, receipt=lean,
            ))
            continue

    return out


# ── KG 거울용 dict-shaped 소스(sync_lakatos_programme_to_kg.py 가 읽는 단일 진실) ──────────────
# ★verdict 필드는 *스테이지 라벨*(canonical_stage)만 — 진보성 주장(progressive/rejected)은 NODES 에
#   손입력하지 않는다. 진보성은 오직 run() 의 judge() 가 *실 receipt 에서* 생성한다(위 GOV_NODES).
#   KG 노드는 사전등록 가지(추측+예측)를 기록할 뿐, 그 가지의 채점결과를 박제하지 않는다.
def _kg_node(n: GovNode) -> dict:
    pred = n.prediction
    metric = pred.metric_name if pred else "(root)"
    novel = n.novel_target.metric_name if n.novel_target else ""
    return dict(
        tag=n.tag,
        verdict="canonical_stage",          # 스테이지 라벨(채점 아님) — 진보성은 judge() 권위
        parent=n.parent,
        comment=n.story,
        limitation=("novel metric != 개선 metric (judge P2 독립성): "
                    f"improve={metric} / novel={novel}" if pred else
                    "하드코어 추측: bhgman=결정론 거버넌스/감사 substrate, NOT capability multiplier"),
        algorithm="deterministic-oracle" if pred else "conjecture",
        metric_value=None,                  # 채점값은 run() 의 judge 가 생성(여기 박제 금지)
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in GOV_NODES]

FRONTIER = [
    # ★capability-multiplier 는 *열린 채로* (bhgman 자신 증거가 대담한 예측을 반증 → 등록 금지, OPEN by design)
    dict(name="capability-multiplier", status="OPEN",
         body="A/B says bhgman adds no reasoning capability — open by design. loop=neutral-to-worse "
              "at bhgman's scale(verdict 2026-06-04); substrate 가치는 검증이지 추론력 증대가 아니다. "
              "bold prediction 으로 등록하지 않음(자기 증거가 반증).",
         closed_by=None),
    dict(name="drift-exhaustive", status="OPEN",
         body="KG↔code drift 0 으로 전수 봉쇄(현재 436 drift, passed=false). drift_governance 가지가 "
              "judge() 로 채점 — 현 receipt 는 *정직한 비진보*(rejected). 0 도달 시 재실행이 자동 채점.",
         closed_by=None),
    dict(name="lean-proof-gate", status="OPEN",
         body="자족 .lean proof-goal 을 substrate-disjoint lean checker(exit-0 하드게이트)로 검증. "
              "lean_proof_gate 가지가 judge() 로 채점. 툴체인 가용 시 progressive, 부재 시 pending.",
         closed_by=None),
]


if __name__ == "__main__":
    print("═" * 78)
    print("  bhgman_tool governance/audit substrate — Lakatos 연구 프로그램 (onboarding)")
    print("  receipts = bhgman 자신의 결정론 oracle (ABSOLUTE venv, self-report 아님)")
    print("═" * 78)
    for r in run():
        if r["status"] == "ROOT":
            tail = "(추측·루트, 채점 대상 아님)"
        elif r["status"] == "PENDING":
            tail = f"pending — {r.get('note', '')}"
        else:
            tail = (f"measured={r['measured']}  oracle_passed={r.get('oracle_passed')}  "
                    f"novel={r.get('novel')}  improved={r.get('improved')}")
        print(f"  {r['tag']:18} → {r['verdict']:20} {tail}")
    print("\nKG 거울: LakatosTree_BhgmanGovernance_20260624 "
          f"(nodes={len(NODES)} + frontier={len(FRONTIER)}; q-capability-multiplier OPEN by design)")
    print("verdict 은 전부 judge() 가 실 oracle receipt 에서 *생성* — 손입력 0.")
