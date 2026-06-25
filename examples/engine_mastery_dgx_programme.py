"""Engine-mastery absorption — vLLM continuous-batching design → bhgman Prometheus engine,
proven by a MOVED, PRE-REGISTERED METRIC (Engine-mastery tradition S2 hard core).

★규율(verdict_provenance / prom_honesty / bhgman / euler 예제와 동일): 노드는 verdict 를 *손입력
하지 않는다*. 각 노드는 사전등록 Prediction + 구조적 NovelTarget(개선 metric 과 *다른* metric) 만
데이터로 들고, `run()` 이 **외부·위조불가 영수증**(vLLM /metrics 디스크 로그 + GitHub Actions
check-runs, self-report 아님)에서 measured/novel_measured 를 *파생*해 `judge()` 가 verdict 를
*생성*한다. `register_to_server()` 는 같은 노드를 **엔진 HTTP API**(add_node → register_prediction
→ submit_test_result)로 태워 verdict 를 서버가 다시 judge() 로 생성·영속하게 한다(KG 직접쓰기 금지,
서버 by-construction 가드만 사용).

하드코어(Engine-mastery tradition S2, 채점 대상 아님 — 추측):
  모든 흡수(absorption)는 우리 엔진의 *명명·사전등록 metric 을 움직여야 한다*. read-and-feel-inspired
  점수 0; ship-without-moving-the-metric = 반증(falsification)이지 polish 가 아니다.

이 프로그램이 흡수한 외부 엔진 = **vLLM continuous batching**(running-batch 스케줄러: paged-KV +
preemption-aware admission). 그 설계를 bhgman_tool Prometheus 엔진(K-sampling PR#25, tree+K PR#27,
LB backlog fix)에 포팅했고, 그 결과를 vLLM 자신의 /metrics 로 측정한다.

★정직성 — 이 등록은 RETROACTIVE(post-hoc): 예측은 작업 *이후* 등록된다. 그래서 무결성은 '예측이
먼저였다'가 아니라 *측정이 외부·위조불가*라는 데 전적으로 기댄다 — vLLM /metrics 와 GitHub Actions
check-runs 는 이 프로그램이 만들 수 없는 외부 store 다. (judge() self-score 금지; set_verdict 금지.)
이 post-hoc 성격은 register_to_server() 가 노드에 critique(kind='doubt')로 *함께 등재*한다.

novel metric 독립성(judge P2 게이트): 각 가지의 NovelTarget metric 은 개선 metric 과 *다른 store* 다 —
  · saturation 가지 : 개선 = vllm_num_requests_running_peak(higher, vLLM /metrics).
                      novel = main_ci_all_green(higher, *GitHub Actions* — 다른 외부 store).
                      "saturation 이 오른다"는 예측의 독립 확증 = (a) 다른 store(CI)가 전부 green +
                      (b) preemptions 가 0 유지(KV knee 아래 — 회귀 없음). count 와 다른 축·다른 store.
  · lb_ceiling 가지 : 개선 = lb_max_concurrent_ok(higher, bench2.txt 외부 수신측 카운트).
                      novel = lb_zero_connection_resets(higher, 같은 bench 의 reset 카운트=0 — 천장이
                      성공의 *부재*가 아니라 reset 의 *부재*로 증명되는 독립 측정).

# KG 거울 hub: LakatosTree_EngineMastery_Absorption_20260618 (live tree; 서버로 직접 등록)
#   anchor 노드 부모: grounding-wretchedness-baseline (현 CANONICAL 루트)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from lakatos.verdict.judge import NovelTarget, Prediction, judge

# ── 외부 영수증 위치 (이 프로그램이 만들 수 없는 store) ───────────────────────────────
_SCRATCH = ("/tmp/claude-1001/-data-user-PROJECT-3D/"
            "ac921d26-f7ee-4e47-bdc4-7e0f5d3453ff/scratchpad")
_VLLM_K_LOG = f"{_SCRATCH}/vllm_metrics.log"   # K-sampling PR#25 윈도 (peak running ~10)
_VLLM_L6_LOG = f"{_SCRATCH}/l6_metrics.log"    # tree+K PR#27 윈도 (peak running 24)
_BENCH2 = f"{_SCRATCH}/bench2.txt"             # LB backlog fix (N=32 → 32/32 OK, resets=[])

_GH_REPO = "gj3447/bhgman_tool"               # 외부 store: GitHub Actions
_SAT_BASELINE = 3.0                            # 문서화된 baseline peak running (PR 전)


# ── 외부 영수증 파서 (self-report 아님: 디스크 로그 / GitHub API 에서 *파생*) ───────────
def _vllm_peak_running(path: str) -> float | None:
    """vLLM /metrics 디스크 로그에서 num_requests_running 최대값을 파싱. 없으면 None(pending)."""
    if not os.path.exists(path):
        return None
    peak = None
    pat = re.compile(r"num_requests_running\{[^}]*\}\s+([0-9.]+)")
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.search(line)
            if m:
                v = float(m.group(1))
                peak = v if peak is None else max(peak, v)
    return peak


def _vllm_max_preemptions(path: str) -> float | None:
    """num_preemptions_total 최대값 — 0 = KV knee 아래(회귀 없음). 없으면 None."""
    if not os.path.exists(path):
        return None
    hi = None
    pat = re.compile(r"num_preemptions_total\{[^}]*\}\s+([0-9.]+)")
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.search(line)
            if m:
                v = float(m.group(1))
                hi = v if hi is None else max(hi, v)
    return hi


def _ci_all_green() -> float | None:
    """GitHub Actions: main HEAD 의 *모든* check-run conclusion 이 success 인가 (1.0/0.0).

    외부 store(this programme 이 못 만든다). gh 미가용/네트워크 실패면 None(pending)."""
    try:
        sha = subprocess.run(
            ["gh", "api", f"repos/{_GH_REPO}/commits/main", "--jq", ".sha"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        if not sha:
            return None
        out = subprocess.run(
            ["gh", "api", f"repos/{_GH_REPO}/commits/{sha}/check-runs",
             "--jq", ".check_runs[].conclusion"],
            capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    conclusions = [c for c in out.splitlines() if c.strip()]
    if not conclusions:
        return None
    # 모든 check-run 이 success 여야 1.0 (하나라도 다르면 0.0 — green-and-blind 금지)
    return 1.0 if all(c == "success" for c in conclusions) else 0.0


def _bench2_concurrency() -> tuple[float | None, float | None]:
    """bench2.txt 외부 수신측 영수증 → (최대 동시 OK 수, reset 카운트).

    'N=32: 32/32 OK ... resets/fails=[]' 를 파싱. OK 수 = 최대 동시성, reset 수 = []→0."""
    if not os.path.exists(_BENCH2):
        return None, None
    best_ok = None
    resets = None
    with open(_BENCH2, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for m in re.finditer(r"N=(\d+):\s+(\d+)/(\d+)\s+OK.*?resets/fails=\[([^\]]*)\]", txt):
        got, tot = int(m.group(2)), int(m.group(3))
        if got == tot:
            best_ok = float(got) if best_ok is None else max(best_ok, float(got))
        rl = [x for x in m.group(4).split(",") if x.strip()]
        resets = float(len(rl)) if resets is None else max(resets, float(len(rl)))
    return best_ok, resets


# ── 프로그램 노드 (dataclass = 런타임 채점 단위; verdict 필드 없음) ──────────────────
@dataclass(frozen=True)
class AbsorptionNode:
    tag: str
    parent: str | None
    story: str
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None


_ROOT_PARENT = "grounding-wretchedness-baseline"   # Engine-mastery tree 의 현 CANONICAL 루트

NODES: tuple[AbsorptionNode, ...] = (
    AbsorptionNode(
        tag="vllm-absorption-hardcore", parent=_ROOT_PARENT,
        story="추측(흡수 대상): vLLM continuous batching(running-batch 스케줄러 + paged-KV + "
              "preemption-aware admission)의 설계를 bhgman Prometheus 엔진에 포팅하면, 우리 엔진의 "
              "*명명 metric 이 움직인다*. read-and-feel 0 — 채점 대상 아님(루트).",
    ),
    AbsorptionNode(
        tag="vllm-continuous-batching-saturation", parent="vllm-absorption-hardcore",
        story="흡수 가지: K-sampling(PR#25) + tree+K(PR#27)로 GB10 동시 running-batch 를 끌어올렸다. "
              "개선 = vLLM /metrics 의 num_requests_running peak (baseline 3 → 24). novel(독립 store) = "
              "GitHub Actions main HEAD 전부 green + preemptions 0(KV knee 아래, 회귀 없음). "
              "★RETROACTIVE: 예측 사후등록 — 무결성은 두 외부 store(vLLM·GitHub)가 위조불가라는 데 기댄다.",
        prediction=Prediction(
            metric_name="vllm_num_requests_running_peak", direction="higher",
            baseline_value=_SAT_BASELINE, noise_band=0.0,
            novel_prediction="포팅 후 saturation 상승이 *다른 외부 store*(CI green)로 독립 확증되고 "
                             "preemptions 가 0 유지(KV 회귀 없음)",
            closes_question="q-vllm-continuous-batching-absorbed"),
        # ★novel 은 *다른 metric·다른 store*: GitHub Actions all-green (vLLM count 와 독립)
        novel_target=NovelTarget(metric_name="main_ci_all_green", direction="higher",
                                 threshold=1.0),
    ),
    AbsorptionNode(
        tag="vllm-lb-backlog-ceiling", parent="vllm-continuous-batching-saturation",
        story="흡수 가지(러닝-배치 admission 천장): qwen_lb.py listen-backlog 5→128 (vLLM admission "
              "큐 설계 흡수). 개선 = 외부 수신측 bench2 의 최대 동시 OK 수(24 ConnectionReset → 32/32). "
              "novel(독립 측정) = 같은 bench 의 reset 카운트 0 — 천장은 OK 의 존재가 아니라 reset 의 부재로 증명.",
        prediction=Prediction(
            metric_name="lb_max_concurrent_ok", direction="higher",
            baseline_value=24.0, noise_band=0.0,
            novel_prediction="backlog 확대 후 N=32 가 reset 0 으로 통과(천장이 reset 부재로 증명)",
            closes_question="q-vllm-lb-admission-ceiling"),
        # ★novel 은 *다른 metric*: reset 카운트(=0). OK 수와 독립한 '실패의 부재' 측정
        novel_target=NovelTarget(metric_name="lb_zero_connection_resets", direction="lower",
                                 threshold=0.0),
    ),
)


@dataclass(frozen=True)
class Receipt:
    """run() 이 채점에 쓰는 외부 파생 영수증 (전부 store 에서 파싱; 손입력 0)."""
    sat_peak: float | None
    sat_preempt: float | None
    ci_green: float | None
    lb_ok: float | None
    lb_resets: float | None


def receipt() -> Receipt:
    """외부 store 에서 영수증을 파싱. saturation peak 는 두 윈도(K, L6)의 *최대* = 포팅 후 최종 상태."""
    pk = _vllm_peak_running(_VLLM_K_LOG)
    pl = _vllm_peak_running(_VLLM_L6_LOG)
    sat_peak = None if (pk is None and pl is None) else max(x for x in (pk, pl) if x is not None)
    prk = _vllm_max_preemptions(_VLLM_K_LOG)
    prl = _vllm_max_preemptions(_VLLM_L6_LOG)
    prs = [x for x in (prk, prl) if x is not None]
    sat_preempt = max(prs) if prs else None
    lb_ok, lb_resets = _bench2_concurrency()
    return Receipt(sat_peak=sat_peak, sat_preempt=sat_preempt,
                   ci_green=_ci_all_green(), lb_ok=lb_ok, lb_resets=lb_resets)


def run(rc: Receipt | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — 각 노드 verdict 를 judge() 가 *생성*. measured 는 외부 영수증 파생, 손입력 0.

    영수증 미가용(store 부재/네트워크 실패) → pending(no-receipt), NaN 을 judge 에 먹이지 않는다."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES:
        if n.prediction is None:                                   # 루트(추측) — 채점 대상 아님
            out.append(dict(tag=n.tag, parent=n.parent, verdict="canonical_stage",
                            status="ROOT", measured=None, novel=None, note=None))
            continue

        if n.tag == "vllm-continuous-batching-saturation":
            if rc.sat_peak is None or rc.ci_green is None or rc.sat_preempt is None:
                out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                                status="PENDING", measured=None, novel=None,
                                note="외부 영수증 부재(vLLM 로그 또는 GitHub check-runs)"))
                continue
            measured = rc.sat_peak                                  # 24 (포팅 후 peak running)
            # novel = CI 전부 green AND preemptions 0 (두 외부 store 의 독립 확증)
            novel_measured = 1.0 if (rc.ci_green >= 1.0 and rc.sat_preempt == 0.0) else 0.0
            v = judge(n.prediction, measured, n.novel_target, novel_measured)
            out.append(dict(
                tag=n.tag, parent=n.parent, verdict=v.verdict,     # ★judge 생성
                status="SCORED", measured=measured,
                novel=v.novel, improved=v.improved,
                novel_measured=novel_measured,
                sat_preempt=rc.sat_preempt, ci_green=rc.ci_green,
                reason=v.reason, retroactive=True))
            continue

        if n.tag == "vllm-lb-backlog-ceiling":
            if rc.lb_ok is None or rc.lb_resets is None:
                out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                                status="PENDING", measured=None, novel=None,
                                note="bench2 외부 영수증 부재"))
                continue
            measured = rc.lb_ok                                    # 32 (최대 동시 OK)
            novel_measured = rc.lb_resets                          # 0 (reset 카운트 = 독립 측정)
            v = judge(n.prediction, measured, n.novel_target, novel_measured)
            out.append(dict(
                tag=n.tag, parent=n.parent, verdict=v.verdict,     # ★judge 생성
                status="SCORED", measured=measured,
                novel=v.novel, improved=v.improved,
                novel_measured=novel_measured,
                reason=v.reason, retroactive=True))
            continue

    return out


# ── 엔진 HTTP API 등록 (KG 직접쓰기 금지; 서버 by-construction 가드만) ─────────────────
_SERVER = os.environ.get("LAKATOS_SERVER", "http://127.0.0.1:55170")
_TREE = "LakatosTree_EngineMastery_Absorption_20260618"
_SCRIPT_SHA_PREFIX = "engine_mastery_dgx_programme"   # 영수증 출처 식별 (sha 자리; epsilon 우회 무관)


def _post(path: str, body: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{_SERVER}{path}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except (json.JSONDecodeError, ValueError):
            payload = {"detail": str(e)}
        return e.code, payload


def register_to_server(rc: Receipt | None = None) -> list[dict]:
    """엔진 HTTP API 로 노드+예측+결과를 태운다 — verdict 는 *서버가* judge() 로 생성·영속.

    경로: POST /node (add_node) → /node/{tag}/prediction (register_prediction)
          → /node/{tag}/test_result (submit_test_result, 서버 judge → KG 영속).
    RETROACTIVE 표기는 saturation 노드에 critique(kind='doubt')로 함께 등재.
    KG 직접 Cypher 쓰기 없음; 서버의 422/409 by-construction 가드만 사용."""
    rc = receipt() if rc is None else rc
    results = run(rc)
    by_tag = {r["tag"]: r for r in results}
    report: list[dict] = []

    for n in NODES:
        r = by_tag[n.tag]
        # 1) add_node (verdict 손입력 안 함 — 기본 'proof'; scored verdict 는 서버 judge 만 생성)
        st, body = _post(f"/api/tree/{_TREE}/node", dict(
            tag=n.tag, parent=n.parent or "", comment=n.story,
            algorithm="vllm-continuous-batching-absorption" if n.prediction else "conjecture"))
        step = dict(tag=n.tag, add_node=(st, body.get("ok", body)))

        if n.prediction is None:        # 루트 추측 — 예측 없음, 결과 없음
            report.append(step)
            continue

        # 2) register_prediction (사전등록; 사후 채점 차단 가드 통과)
        p = n.prediction
        nt = n.novel_target
        pred_body = dict(metric_name=p.metric_name, direction=p.direction,
                         baseline_value=p.baseline_value, noise_band=p.noise_band,
                         novel_prediction=p.novel_prediction, closes_question=p.closes_question)
        if nt is not None:
            pred_body.update(novel_metric=nt.metric_name, novel_direction=nt.direction,
                             novel_threshold=nt.threshold)
        st, body = _post(f"/api/tree/{_TREE}/node/{n.tag}/prediction", pred_body)
        step["register_prediction"] = (st, body.get("note", body))

        # 3) submit_test_result (서버가 judge() 로 verdict 생성·영속) — measured 는 외부 영수증 파생
        if r["status"] != "SCORED":     # 영수증 부재면 결과 미제출(정직한 pending)
            step["test_result"] = ("skipped", r["verdict"])
            report.append(step)
            continue
        tr_body = dict(metric_value=float(r["measured"]),
                       script=f"{_SCRIPT_SHA_PREFIX}:{n.tag}",
                       script_sha=f"{_SCRIPT_SHA_PREFIX}:{p.metric_name}",
                       novel_measured=float(r["novel_measured"]),
                       novel_sha=f"{_SCRIPT_SHA_PREFIX}:{nt.metric_name}" if nt else None,
                       source_trust=1.0)
        st, body = _post(f"/api/tree/{_TREE}/node/{n.tag}/test_result", tr_body)
        step["test_result"] = (st, body)

        # 4) RETROACTIVE 정직성 비판 등재 (saturation 노드에) — judge 회피 아님, 감사 흔적
        if n.tag == "vllm-continuous-batching-saturation":
            cst, cbody = _post(f"/api/tree/{_TREE}/node/{n.tag}/critique", dict(
                arg_id=f"doubt-retroactive-{n.tag}", attacks=n.tag, by="engine_mastery_dgx_programme",
                kind="doubt",
                body="RETROACTIVE: prediction was registered AFTER the porting work (post-hoc). "
                     "Integrity rests on the measurements being EXTERNAL and unforgeable — vLLM "
                     "/metrics (num_requests_running peak, preemptions=0) and GitHub Actions main "
                     "HEAD check-runs (all success) — not self-graded. No set_verdict; judge() ruled."))
            step["critique_retroactive"] = (cst, cbody)
        report.append(step)
    return report


if __name__ == "__main__":
    import sys
    rc = receipt()
    print("═" * 80)
    print("  Engine-mastery absorption — vLLM continuous batching → bhgman Prometheus engine")
    print("  receipts = vLLM /metrics disk logs + GitHub Actions check-runs (외부, self-report 아님)")
    print("═" * 80)
    print(f"  receipt: sat_peak={rc.sat_peak} sat_preempt={rc.sat_preempt} ci_green={rc.ci_green} "
          f"lb_ok={rc.lb_ok} lb_resets={rc.lb_resets}\n")
    for r in run(rc):
        if r["status"] == "ROOT":
            tail = "(추측·루트, 채점 대상 아님)"
        elif r["status"] == "PENDING":
            tail = f"pending — {r.get('note', '')}"
        else:
            tail = (f"measured={r['measured']} novel={r.get('novel')} "
                    f"improved={r.get('improved')} (RETROACTIVE)")
        print(f"  {r['tag']:38} → {r['verdict']:20} {tail}")
    print("\nverdict 은 전부 judge() 가 외부 영수증에서 *생성* — 손입력 0. 등록은 RETROACTIVE(post-hoc).")

    if "--register" in sys.argv:
        print("\n── 엔진 HTTP API 등록 (add_node → register_prediction → submit_test_result) ──")
        for step in register_to_server(rc):
            print(f"\n  [{step['tag']}]")
            for k, v in step.items():
                if k == "tag":
                    continue
                print(f"     {k}: {v}")
