"""OMD 채택마찰 PROM — 2026-07-02 병렬-dev 실전에서 실측된 마찰 5건의 라카토스 하네스.

현장 영수증(같은 날, 같은 워크트리): ① 병렬 세션 충돌 2회(아무도 OMD lease 안 잡음) ② 30분 편집
중 agent RETIRED+fenced_out(agent_ttl 90s = 기계 페이스 가정) ③ sweep 이 TTL 남은 orbit 회수
④ lease-only 태스크 PENDING 영구 잔류(finish 는 IN_ORBIT 전용) ⑤ :55170 creds 단일사본 소멸
(무-creds 재기동 → 무음 degraded). omd-engine-prom(OmdEngine_20260702)의 '현장 adoption 0%' 실측과
합류하는 채택마찰 클러스터 — 이 하네스가 그 봉합을 판결한다.

★규율(git_absorption/omd_parallel 하네스 계승): verdict 손입력 0 — 노드는 사전등록 Prediction +
독립 NovelTarget + 명명된 이중 가드만 들고, receipt() 가 pytest 를 실행해 judge() 가 채점한다.
F2/F4 의 실 substrate 가드는 omd 자신의 venv 로 구동(subprocess)된다(재구현 금지).

  guard_defect    → 개선축: 그 마찰(실측 사고)이 *죽었나* — 재현 시나리오가 이제 봉합됨 (음성)
  guard_mechanism → novel축: 봉합 *메커니즘이 실 substrate 에 있나* — API/훅/러너 실재 (양성)

# KG: OmdAdoptionFriction_20260702
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
_RECEIPT_GLOB = "tests/test_omd_friction_*.py"
_TREE = "OmdAdoptionFriction_20260702"


def receipt() -> dict[str, bool]:
    """외부 측정 — repo .venv pytest 로 마찰 가드를 돌려 {test_func: passed} 수집(self-report 아님)."""
    matches = glob.glob(os.path.join(_ROOT, _RECEIPT_GLOB))
    if not matches:
        return {}
    cmd = (f"cd {_ROOT} && python -m pytest {_RECEIPT_GLOB} -v --no-header -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", f". .venv/bin/activate 2>/dev/null; {cmd}"],
                         capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


@dataclass(frozen=True)
class FrictionNode:
    tag: str
    rank: int
    parent: str | None
    friction: str                 # 실측 사고(현장 영수증)
    fix: str                      # 봉합 설계(어디에 무엇이 착륙했나)
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_defect: str = ""
    guard_mechanism: str = ""
    anti: str = ""                # 하지 않기로 한 것(문제이동의 정직 경계)


NODES_SPEC = (
    FrictionNode(
        tag="thesis", rank=0, parent=None,
        friction="조율(OMD)×측정(ooptdd)×판정(judge) 3층 스택은 *구조로 채택*되지 않으면 세션 간에 살아남지 않는다",
        fix="채택은 지시가 아니라 구조 — 규율층(CLAUDE.md)+이빨(훅/CI)+페이스 계약(per-agent liveness)+"
            "종결 verb+creds 러너. 이 테제 자체는 채점하지 않는다(하드코어).",
    ),
    FrictionNode(
        tag="F1_session_bypasses_omd", rank=1, parent="thesis",
        friction="병렬충돌 2회(G6/G7·G10) — 세션들이 OMD 를 아예 안 봄; CLAUDE.md 는 지시일 뿐 이빨 없음",
        fix="omd P1 bypass 감지(warn-only)를 lakatotree 에 실설치 + 글로벌 core.hooksPath(ooptdd-hooks)가 "
            "repo-local 훅을 가리는 footgun 을 체인-스루로 관통(설치했는데 무발화 = 죽은 이빨).",
        prediction=Prediction(metric_name="unleased_edit_undetected", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="OMD 안 거친 push 가 기계적으로 감지·경고된다(warn-only, 채택 후 enforce 전환)",
                              closes_question="q-f1-bypass-tooth"),
        novel_target=NovelTarget(metric_name="hook_chain_fires_oracle", direction="higher", threshold=1.0),
        guard_defect="test_bypass_gate_detects_unleased_commits_warn_only",
        guard_mechanism="test_pre_push_hook_installed_and_chained",
        anti="hard-block 은 이식하지 않는다(채택 0% 에서 닭-달걀 — omd 44b6187 의 warn-only 결정 존중).",
    ),
    FrictionNode(
        tag="F2_liveness_pace_mismatch", rank=2, parent="F1_session_bypasses_omd",
        friction="claim(ttl=3600) 후 30분 편집 중 RETIRED+fenced_out(agent_ttl 90s) + sweep 이 TTL 남은 "
                 "orbit 회수(F3) — 기계 물방울 페이스 가정이 인터랙티브 세션을 구조적으로 죽임",
        fix="lease≠liveness 계약(§D2 crash-fast 불변 — 초기 blanket lease-shield 안은 기존 좀비 테스트 "
            "6개가 반증해 기각). 대신 heartbeat(agent, ttl=)로 per-agent 생존창 *명시 선언* + "
            "활동=생존신호(release/commit/finish 가 liveness touch). agents.liveness_ttl 마이그레이션.",
        prediction=Prediction(metric_name="mid_lease_interactive_retirement", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="페이스 선언 세션은 verb 간 침묵 수십 분에도 생존; 미선언 물방울 crash-fast 불변",
                              closes_question="q-f2-pace-contract"),
        novel_target=NovelTarget(metric_name="pace_declaration_api_oracle", direction="higher", threshold=1.0),
        guard_defect="test_interactive_pace_survives_and_crash_fast_preserved",
        guard_mechanism="test_omd_substrate_has_pace_declaration_api",
        anti="lease 보유를 자동 생존신호로 삼지 않는다 — 죽은 agent 의 긴 lease 를 빨리 회수하는 §D2 가 "
             "OMD 의 핵심 가치(기존 6개 좀비 가드가 이 경계의 박제).",
    ),
    FrictionNode(
        tag="F4_lease_only_no_terminal_verb", rank=3, parent="F1_session_bypasses_omd",
        friction="lease-only 흐름(declare+claim, start 미경유)의 태스크가 종결 불가 — finish 는 IN_ORBIT "
                 "전용, complete_task 도 start 전제 → PENDING 영구 잔류(next() 오염)",
        fix="cancel(task, reason) verb — 미시작(PENDING/READY/BLOCKED) 전용 종결. FSM 기존 abort "
            "전이(source='*') 재사용 = 상태기계/TLA 모델 무변경. 시작된 태스크는 거부. MCP 노출.",
        prediction=Prediction(metric_name="lease_only_task_permanent_pending", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="lease-only 태스크가 한 verb 로 종결되고 추천 큐에서 사라진다",
                              closes_question="q-f4-terminal-verb"),
        novel_target=NovelTarget(metric_name="cancel_verb_substrate_oracle", direction="higher", threshold=1.0),
        guard_defect="test_lease_only_task_closable_and_started_protected",
        guard_mechanism="test_omd_substrate_exposes_cancel_verb",
        anti="시작된(IN_ORBIT+) 태스크의 cancel 은 이식하지 않는다 — 진행중 작업의 무단 증발 금지(finish/bail 경유).",
    ),
    FrictionNode(
        tag="F5_server_creds_single_copy", rank=4, parent="thesis",
        friction=":55170 creds 원본이 죽은 프로세스 environ 단일사본 — 무-creds 재기동이 무음 degraded"
                 "(/version 200 이 건강을 위장), 복구는 공통비번 후보 대입 요행",
        fix="정본 env(~/.config/lakatotree/server.env 0600) + scripts/dev_server_restart.sh — env 부재 시 "
            "기동 거부(fail-loud+복구 안내), 죽이기 전 environ 백업, healthz 3/3 수렴 게이트.",
        prediction=Prediction(metric_name="credless_silent_degraded_boot", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="무-creds 기동이 러너에서 표현 불가(거부) + 건강판정=healthz 3/3(version 아님)",
                              closes_question="q-f5-creds-runbook"),
        novel_target=NovelTarget(metric_name="canonical_env_runbook_oracle", direction="higher", threshold=1.0),
        guard_defect="test_restart_script_refuses_without_canonical_env",
        guard_mechanism="test_canonical_env_and_runbook_wiring",
        anti="시크릿을 repo 에 커밋하지 않는다 — 정본 env 는 box-local(0600), 러너만 커밋.",
    ),
)


def _score(n: FrictionNode, defect_closed: bool, mech_present: bool) -> dict:
    measured = 0.0 if defect_closed else n.prediction.baseline_value
    novel_measured = 1.0 if mech_present else 0.0
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, rank=n.rank, parent=n.parent, verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """verdict 는 judge() 가 생성(손입력 0). 가드 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_SPEC:
        if n.prediction is None:
            out.append(dict(tag=n.tag, rank=n.rank, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        if not (n.guard_defect in rc or n.guard_mechanism in rc):
            out.append(dict(tag=n.tag, rank=n.rank, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, str]]:
    """이중가드 판별력 — judge() 4-칸(단일비트 하네스는 progressive/pending 만 낸다)."""
    probe = next(n for n in NODES_SPEC if n.tag == "F2_liveness_pace_mismatch")
    return [(f"defect={d}, mech={m}", _score(probe, d, m)["verdict"])
            for d, m in ((True, True), (True, False), (False, True), (False, False))]


if __name__ == "__main__":
    rc = receipt()
    print(f"omd-friction guard receipt: {sum(rc.values())}/{len(rc)} green ({_RECEIPT_GLOB})\n")
    rows = run(rc)
    for r in sorted(rows, key=lambda r: (r["rank"], r["tag"])):
        tail = r.get("note", "") if r["verdict"].startswith("pending") else \
            (f"novel={r.get('novel')} improved={r.get('improved')}" if r["status"] != "ROOT" else "(테제·루트)")
        print(f"  [rank {r['rank']}] {r['tag']:35} → {r['verdict']:20} {tail}")
    n_closed = sum(1 for r in rows if r["status"] == "CLOSED")
    print(f"\n총 {len(rows) - 1} 마찰: CLOSED(progressive) {n_closed} · verdict 전부 judge() 생성(손입력 0).")
    print("\n이중가드 판별력(_discrimination_demo):")
    for label, v in _discrimination_demo():
        print(f"  {label:28} → {v}")
    print(f"\nKG 거울: {_TREE}")
