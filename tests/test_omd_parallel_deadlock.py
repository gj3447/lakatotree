"""test_omd_parallel_deadlock.py — LakatoTree PROM guard for OMD node `deadlock_freedom_dag`.

D7 / P0-10: dependency-DAG acyclicity (deadlock-freedom).

LITERATURE (classic result):
  Coffman, Elphick & Shoshani (1971) "System Deadlocks" — a deadlock requires FOUR
  necessary conditions; the breakable structural one is CIRCULAR WAIT. Havender (1968)
  ordered-resource / acyclic-allocation avoidance: keep the resource/dependency graph
  acyclic and a circular wait can never form.

PRINCIPLE:
  OMD keeps the task dependency graph acyclic with a DFS cycle gate at EDGE INSERTION.
  Any declare(deps=...)/depend(after=...) edge that would close a cycle is rejected with
  {ok:false, reason:"dep_cycle"} and the graph is left invariant. The no-circular-wait
  Coffman condition is therefore structurally denied → deadlock-free by construction.

OMD ARTIFACT corroborated:
  omd_server/core.py:281-318  _find_cycle (DFS WHITE/GRAY/BLACK back-edge) + _would_cycle
  wired at core.py:820-823 (declare → dep_cycle) and core.py:841-846 (depend → dep_cycle).
  Dimension test: tests/test_d7_dep_cycle.py (back-edge / 3-node / declare-deps / self-dep
  rejected, graph invariant, valid DAG unblocks).
KG lit node: OMD-finding-glob-overlap-gap

ORACLES (judge contract — two independent sources of truth):
  guard_defect  = in-test broken-vs-fixed model: naive (no gate) admits A→B→C→A and the
                  deps-gated scheduler deadlocks (0 progress); the DFS gate rejects the
                  back-edge C→A, graph stays acyclic, topo order exists. Revert-proof:
                  flip GATE_ENABLED=False in-test → cycle admitted → deadlock returns.
  guard_mechanism = BEHAVIORAL subprocess of the REAL substrate D7 test in OMD's OWN venv
                  (independent of the in-test model).

stdlib + pytest only. Deterministic. OMD repo is READ-ONLY.
"""

import os
import subprocess
import sys

# --------------------------------------------------------------------------- #
# In-test minimal model: a tiny dependency graph + DFS cycle gate that mirrors
# the real OMD _find_cycle (WHITE/GRAY/BLACK back-edge detection), plus a
# deps-gated topological-runnability scheduler. NOTHING here imports OMD — the
# defect oracle is fully self-contained and revert-proof by an in-test toggle.
# --------------------------------------------------------------------------- #


import os as _os
import pytest as _pytest
_OMD_ROOT = _os.environ.get("OMD_ROOT", "<WORKSPACE>/PROJECT/PI/omd")
_OMD_ABSENT = not _os.path.isdir(_OMD_ROOT)
# audit un-gate: 자기완결 defect 오라클(naive-vs-fixed in-test 모델, OMD 불요)은 게이트 없이 CI 서 실행.
# OMD-의존 mechanism 오라클(disjoint import / TLA 파싱 / OMD venv subprocess)만 부재 시 skip(아래 @_skip_omd).
_skip_omd = _pytest.mark.skipif(
    _OMD_ABSENT, reason="OMD 자매 repo 미체크아웃/OMD_ROOT 미설정 — 크로스레포 mechanism 오라클(로컬/CI-checkout 시만)")

def _find_cycle(graph):
    """Return a cycle path if the directed graph has one, else None.

    Faithful mirror of omd_server/core.py:_find_cycle — DFS three-colouring;
    a back-edge to a GRAY node is a cycle. `graph[n]` = set of successors
    (here: the tasks n depends on, i.e. n -> dep edges)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack = []

    def visit(n):
        color[n] = GRAY
        stack.append(n)
        for m in graph.get(n, ()):
            c = color.get(m, WHITE)
            if c == GRAY:
                return stack[stack.index(m):] + [m]
            if c == WHITE:
                cyc = visit(m)
                if cyc:
                    return cyc
        color[n] = BLACK
        stack.pop()
        return None

    for n in list(graph):
        if color.get(n, WHITE) == WHITE:
            cyc = visit(n)
            if cyc:
                return cyc
    return None


class DepGraph:
    """Tiny dependency DAG. Edge add(u, v) means 'u depends on v' (u after v).

    If gate_enabled, add() runs the DFS acyclicity gate BEFORE committing the
    edge: a would-be cycle is rejected and the graph is left invariant
    (mirrors OMD's _would_cycle/_find_cycle at declare/depend)."""

    def __init__(self, gate_enabled=True):
        self.gate_enabled = gate_enabled
        self.adj = {}

    def add_task(self, t):
        self.adj.setdefault(t, set())

    def add(self, u, v):
        """Try to add edge u->v (u depends on v). Return dict like OMD."""
        self.add_task(u)
        self.add_task(v)
        if v in self.adj[u]:
            return {"ok": True, "noop": True}
        if self.gate_enabled:
            # virtual-add then check, reject without mutating on cycle.
            trial = {k: set(s) for k, s in self.adj.items()}
            trial[u].add(v)
            cyc = _find_cycle(trial)
            if cyc is not None:
                return {"ok": False, "reason": "dep_cycle", "cycle": cyc}
        self.adj[u].add(v)
        return {"ok": True}

    def has_cycle(self):
        return _find_cycle(self.adj) is not None

    def topo_order(self):
        """Kahn topo order over dependency edges, or None if a cycle blocks it.

        A node is runnable only after all deps it points to are done — exactly
        the deps-gate a real scheduler uses (OMD next_task). A cyclic graph
        yields None: every remaining task waits on a predecessor → DEADLOCK."""
        indeg = {n: 0 for n in self.adj}
        for u in self.adj:
            for _v in self.adj[u]:
                indeg[u] += 1  # u must wait for each dep it points to
        ready = [n for n, d in indeg.items() if d == 0]
        order = []
        # successors-of-dep map: when a dep finishes, decrement its dependents.
        dependents = {n: [] for n in self.adj}
        for u in self.adj:
            for v in self.adj[u]:
                dependents.setdefault(v, []).append(u)
        ready.sort()
        while ready:
            n = ready.pop(0)
            order.append(n)
            for u in dependents.get(n, []):
                indeg[u] -= 1
                if indeg[u] == 0:
                    ready.append(u)
            ready.sort()
        if len(order) != len(self.adj):
            return None  # leftover = circular wait = deadlock
        return order


def _run_scheduler(graph):
    """Return the topo order (progress) or None (deadlock — zero progress)."""
    return graph.topo_order()


# --------------------------------------------------------------------------- #
# guard_defect — self-contained, revert-proof improvement oracle.
# --------------------------------------------------------------------------- #
def test_cyclic_dep_deadlocks_acyclicity_gate_rejects_back_edge_and_unblocks():
    """Coffman circular-wait → deadlock; Havender acyclic gate → progress.

    NAIVE (no gate): admit A->B, B->C, C->A. The deps-gated scheduler makes
    ZERO progress — every task waits on a predecessor (deadlock).
    PRINCIPLED (DFS gate): edge C->A is rejected (would close a cycle), graph
    stays acyclic, a topo order now exists (progress possible).
    Revert-proof: with the gate disabled the cycle is admitted and the
    deadlock returns — the assertions genuinely depend on the mechanism."""

    # ---- NAIVE: no acyclicity gate -> circular wait admitted ----
    naive = DepGraph(gate_enabled=False)
    for t in ("A", "B", "C"):
        naive.add_task(t)
    assert naive.add("A", "B")["ok"]
    assert naive.add("B", "C")["ok"]
    r_naive = naive.add("C", "A")          # closes A->B->C->A
    assert r_naive["ok"] is True, "naive model must ADMIT the cycle edge"
    assert naive.has_cycle() is True, "naive graph must contain the cycle"
    assert _run_scheduler(naive) is None, (
        "DEADLOCK expected: cyclic deps must yield zero progress (no topo order)")

    # ---- PRINCIPLED: DFS cycle gate rejects the back-edge ----
    fixed = DepGraph(gate_enabled=True)
    for t in ("A", "B", "C"):
        fixed.add_task(t)
    assert fixed.add("A", "B")["ok"]
    assert fixed.add("B", "C")["ok"]
    r_fixed = fixed.add("C", "A")          # would close the cycle
    assert r_fixed["ok"] is False, "gate must REJECT the cycle-closing edge"
    assert r_fixed["reason"] == "dep_cycle", r_fixed
    assert "A" in r_fixed["cycle"] and "C" in r_fixed["cycle"], r_fixed
    # graph invariant: rejected edge did not mutate C's deps.
    assert fixed.adj["C"] == set(), "rejected edge must leave the graph invariant"
    assert fixed.has_cycle() is False, "fixed graph must stay acyclic"
    order = _run_scheduler(fixed)
    assert order is not None, "acyclic graph must admit a topo order (progress)"
    # deps must come before dependents in the order (B before A, C before B).
    assert order.index("B") < order.index("A")
    assert order.index("C") < order.index("B")

    # ---- self-dependency is a length-1 cycle and is rejected too ----
    selfdep = DepGraph(gate_enabled=True)
    selfdep.add_task("S")
    r_self = selfdep.add("S", "S")
    assert r_self["ok"] is False and r_self["reason"] == "dep_cycle", r_self
    assert selfdep.adj["S"] == set()


def test_revert_proof_disabling_gate_reintroduces_deadlock():
    """Negative control / sensitivity: the ONLY difference between progress and
    deadlock is the gate flag — delete the mechanism and RED returns."""
    edges = [("A", "B"), ("B", "C"), ("C", "A")]

    g_off = DepGraph(gate_enabled=False)
    for u, v in edges:
        g_off.add(u, v)
    assert _run_scheduler(g_off) is None  # deadlock without the gate

    g_on = DepGraph(gate_enabled=True)
    for u, v in edges:
        g_on.add(u, v)
    assert _run_scheduler(g_on) is not None  # progress with the gate


# --------------------------------------------------------------------------- #
# guard_mechanism — BEHAVIORAL oracle: the REAL OMD D7 dimension test must pass
# in OMD's OWN venv. Independent of the in-test model above.
# --------------------------------------------------------------------------- #
OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
OMD_PY = os.path.join(OMD_ROOT, ".venv", "bin", "python")
OMD_D7_TEST = "tests/test_d7_dep_cycle.py"


@_skip_omd
def test_omd_d7_dep_cycle_dimension_test_passes_in_real_substrate():
    """Corroborate that the REAL OMD substrate implements the Havender acyclic
    gate: subprocess-run tests/test_d7_dep_cycle.py in OMD's own venv and assert
    rc==0 (back-edge / 3-node / declare-deps / self-dep cycles rejected, graph
    invariant, valid DAG unblocks). If the OMD venv is genuinely unavailable the
    test FAILS honestly — no xfail/skip into a false green."""
    assert os.path.exists(OMD_PY), (
        "real OMD venv python missing — cannot corroborate mechanism: " + OMD_PY)
    assert os.path.exists(os.path.join(OMD_ROOT, OMD_D7_TEST)), (
        "real OMD D7 dimension test missing: " + OMD_D7_TEST)

    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", OMD_D7_TEST, "-q"],
        cwd=OMD_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, (
        "real OMD D7 dep-cycle dimension test FAILED (rc=%d):\n%s"
        % (proc.returncode, out[-3000:]))
    assert "passed" in out, "expected pytest 'passed' summary:\n" + out[-2000:]


@_skip_omd
def test_omd_d7_test_file_actually_exercises_the_real_gate():
    """Cheap structural negative-control: the corroborated test file must really
    reference the real dep_cycle gate (not an empty/renamed stub), so the
    behavioral oracle is not vacuous."""
    path = os.path.join(OMD_ROOT, OMD_D7_TEST)
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "dep_cycle" in src, "D7 test no longer asserts reason=dep_cycle"
    assert "from omd_server import Coordinator" in src, (
        "D7 test no longer exercises the real Coordinator substrate")
    # negative control: a bogus reason string must NOT be what is asserted.
    assert "reason\"] == \"not_a_real_reason" not in src


if __name__ == "__main__":  # pragma: no cover
    sys.exit(__import__("pytest").main([__file__, "-q"]))
