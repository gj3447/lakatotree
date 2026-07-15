"""OOPTDD emit-adapter — PROM16 루프-경계 표준(예산·벽시계·타입종단)을 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만. verify 는 *실제 엔진 코드*
(ProgrammeService.run_cycle / harness_run._bash / cli.main — 재구현 금지)를 in-process 구동하고,
fake 는 세계(KG/하위 verb/subprocess)만 모델한다. 음성 오라클 2종으로 vacuous green 차단.

측정이 곧 판정 근거: 여기서 세는 '거부 시 write 수 0'·'새 인스턴스 거부 재현'·'초과 시 예외 타입'이
judge() 채점(pytest 가드)과 *같은 사실*의 트레이스-측 영수증이다 — LTDD(측정) × judge(판정) 이중층.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_LKT = Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos import cli, harness_run  # noqa: E402 — 실코드(재구현 금지)
from lakatos.harness import BashTimeout  # noqa: E402
from server.contexts.tree.programme_service import ProgrammeService  # noqa: E402 — 실코드
from server.contexts.tree.schemas import CycleIn  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.PROM16_LOOP", "event": name, **attrs}


class _World:
    """fake 세계 — 트리 예산 메타 + 채점노드 count 파생 조회 + 하위 verb.

    budget=None 이면 cycle_budget *미선언*(기존 트리 전부) 재현. scored = 저장소에 이미 있는
    채점노드 수(= 소모량의 정본). 인메모리 카운터가 아니라 이 값이 답을 결정해야 한다.
    """

    def __init__(self, budget=None, scored=0):
        self.budget, self.scored = budget, scored
        self.nodes: dict[str, dict] = {}
        self.pipeline: list[str] = []

    def kg(self, query, **p):
        if "cycle_budget" in query:
            return [{"cycle_budget": self.budget, "used": self.scored}]
        if "HAS_NODE" in query and p.get("tag") is not None:
            return [{"tag": p["tag"]}] if p["tag"] in self.nodes else []
        return []

    def add_node(self, name, node):
        self.pipeline.append("node")
        self.nodes.setdefault(node.tag, {})
        return {"ok": True}

    def register_prediction(self, name, tag, p):
        self.pipeline.append("predict")
        return {"ok": True}

    def submit_test_result(self, name, tag, r):
        self.pipeline.append("submit")
        self.nodes[tag]["verdict_source"] = "scripted"
        return {"verdict": "progressive", "novel": None, "delta": -0.9}

    def add_critique(self, name, tag, c):
        self.pipeline.append("critique")
        return {"ok": True}


def _svc(world: _World) -> ProgrammeService:
    return ProgrammeService(
        kg=world.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {"nodes": [], "frontier": []}, compute_metrics=lambda td: {},
        add_node=world.add_node, register_prediction=world.register_prediction,
        submit_test_result=world.submit_test_result, add_critique=world.add_critique,
        standing=lambda n, t: {"stands": True}, insert_artifact=lambda a: None)


def _cycle(**kw) -> CycleIn:
    return CycleIn(**{"tag": "n", "metric_name": "seam", "baseline": 10.0,
                      "direction": "lower", "measured": 1.0, "script": "inline", **kw})


def _spec_file(tmp: Path, **over) -> str:
    spec = dict(tree="T", tag="exp1", parent="root", metric="p95", baseline=0.5,
                judge_cmd="echo metric=0.3")
    spec.update(over)
    p = tmp / "spec.json"
    p.write_text(json.dumps(spec))
    return str(p)


def verify(backend, cid):
    """실 엔진 구동 → PROM16 루프-경계 오라클을 이벤트로 ship. 실패는 assert(RED)."""
    # ① 예산 소진 → 타입 거부 + 쓰기 0(첫 write 전에 멈춤).
    w = _World(budget=3, scored=3)
    out = _svc(w).run_cycle("T", _cycle())
    assert out["status"] == "budget_exhausted" and out["remaining_budget"] == 0, \
        f"소진 트리가 거부되지 않음: {out}"
    assert w.pipeline == [] and w.nodes == {}, f"거부인데 write 발생: {w.pipeline}/{w.nodes}"
    backend.ship([_ev(cid, "cycle_budget_exhausted_refusal_zero_writes",
                      writes=len(w.pipeline), nodes=len(w.nodes), status=out["status"])])

    # ② 내구성 — 소모는 *저장소*서 파생. 새 인스턴스(프로세스 재시작 재현)도 같은 거부.
    assert _svc(_World(budget=1, scored=1)).run_cycle("T", _cycle())["status"] == "budget_exhausted"
    fresh = _svc(_World(budget=1, scored=1))     # 카운터라면 여기서 0 으로 리셋돼 통과해버림
    assert fresh.run_cycle("T", _cycle())["status"] == "budget_exhausted", \
        "새 인스턴스에서 예산 부활 — 인메모리 카운터(비내구)"
    backend.ship([_ev(cid, "cycle_budget_durable_across_instances", derived_from="storage_count")])

    # ③ 미선언 = 무제한 + 응답 shape 불변(하위호환).
    w = _World(budget=None, scored=99)
    out = _svc(w).run_cycle("T", _cycle())
    assert out["verdict"] == "progressive" and w.pipeline[:3] == ["node", "predict", "submit"]
    assert "remaining_budget" not in out and "status" not in out, f"shape 오염: {sorted(out)}"
    backend.ship([_ev(cid, "cycle_budget_unset_is_unlimited_shape_stable", scored_ignored=99)])

    # ④ bash 벽시계 — env 가 subprocess 까지 관통하고, 초과는 타입 실패(BashTimeout).
    seen = {}
    real_run = subprocess.run
    try:
        subprocess.run = lambda cmd, **kw: seen.update(kw) or (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd, kw["timeout"]))
        import os
        os.environ["LAKATOTREE_BASH_TIMEOUT"] = "7"
        try:
            harness_run._bash("sleep 999")
            raise AssertionError("벽시계 초과가 타입 실패를 안 냄")
        except BashTimeout as e:
            assert "7" in str(e), f"초과 예산이 증거로 안 남음: {e}"
        assert seen["timeout"] == 7, f"env 예산이 subprocess 로 관통 안 됨: {seen}"
        backend.ship([_ev(cid, "bash_wallclock_timeout_typed", budget_s=7,
                          exc="BashTimeout")])

        # ⑦ (음성 오라클) timeout 타입화를 제거하면 *생* TimeoutExpired 가 새는가 — 오라클 이빨.
        leaked = None
        try:
            subprocess.run("sleep 999", shell=True, capture_output=True, text=True, timeout=7)
        except subprocess.TimeoutExpired as e:
            leaked = type(e).__name__
        assert leaked == "TimeoutExpired", "타입화 없는 경로에서 생 예외가 안 샘 — 오라클 vacuous"
        backend.ship([_ev(cid, "bash_timeout_negative_oracle", bare_exception=leaked)])
    finally:
        subprocess.run = real_run
        import os
        os.environ.pop("LAKATOTREE_BASH_TIMEOUT", None)

    # ⑤ CLI 'cycle' 표면 = 타입 종단(이유코드 + exit≠0), 생 스택트레이스 아님.
    #    포트는 전부 fake 주입 — 실 HTTP(:55170)/실 bash 를 절대 안 친다(hermetic: 영수증이 살아있는
    #    서버나 네트워크에 의존하면 그건 측정이 아니라 사고다). tmp 는 자동 청소(repo 오염 금지).
    real_http, real_bash, real_git = harness_run._http, harness_run._bash, harness_run._git_sha
    try:
        harness_run._http = lambda m, p, b=None: {"verdict": "progressive", "delta": -0.2}
        harness_run._bash = lambda cmd: ("boom", 1)      # 하계 ground-truth 실패
        harness_run._git_sha = lambda: "abc1234"
        with tempfile.TemporaryDirectory() as td:
            code = harness_run.run_typed(_spec_file(Path(td), build_cmd="make"))
        assert code != 0, "실패 사이클이 exit 0(가짜 green)"
        backend.ship([_ev(cid, "cli_cycle_typed_terminal", exit_code=code,
                          status="build_failed", surface="cli.cycle->run_typed")])
    finally:
        harness_run._http, harness_run._bash, harness_run._git_sha = real_http, real_bash, real_git

    # ⑥ (음성 오라클) 예산 게이트를 무력화하면 소진 트리가 *써버리는가* — 오라클 이빨 증명.
    w = _World(budget=1, scored=5)
    svc = _svc(w)
    svc._cycle_budget_state = lambda name: (None, 0)   # 결함 주입: 예산 미상=무제한(게이트 이전 상태)
    out = svc.run_cycle("T", _cycle())
    assert w.pipeline != [] and out.get("status") != "budget_exhausted", \
        "게이트 무력화에도 거부됨 — 오라클이 vacuous(항상-green 위험)"
    backend.ship([_ev(cid, "cycle_budget_negative_oracle", wrote_without_gate=len(w.pipeline))])
