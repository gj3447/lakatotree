"""Prom B / C1 — PIDNA conformance: the *Python engine* obeys the 12 Lean theorems.

The external review's sharpest critique (B-1): `formal/Pidna.lean` machine-checks a hand-written
MODEL, not the Python. `lake build sorry=0` proves the theory; it does NOT prove judge.py/bayes.py
conform to it. The model<->implementation gap is exactly where a bug would live.

This file closes that gap with a runtime receipt: it re-derives each Lean theorem as a property over
the REAL `lakatos.verdict.judge.judge` and `lakatos.quant.bayes.branch_credence`, and asserts the
Python obeys it. Paired with `lake build`, "machine-checked theory" becomes "machine-checked theory
AND a Python conformance receipt", drift-guarded and reproducible from a clean clone.

Why exhaustive enumeration, not random (Hypothesis): the kernel is an INTEGER-domain decision
function, so a bounded grid is *exhaustive* over the band — a strictly stronger receipt than
sampling — and stays deterministic (no new dependency, no flaky CI), which is this project's core
value (the review flagged broken reproducibility). Genuine float inputs can differ only by rounding
at the boundary; the kernel theorems are about the decision STRUCTURE, exact at integer scale —
verified directly against the Lean boundary forms (Pidna.lean:38-45) which already match judge.py:86-90.

Lean -> Python vocabulary bridge (the one explicit mapping the conformance rests on):
    Lean .progressive == 'progressive' · .partialV == 'partial'
    Lean .equivalent  == 'equivalent'  · .rejected == 'rejected'
"""
import math

from lakatos.quant.bayes import branch_credence
from lakatos.verdict.judge import NovelTarget, Prediction, judge

# ── Lean -> Python verdict vocabulary (Pidna.lean:33-35 Verdict ↔ verdicts.py) ──
LEAN_TO_PY = {'progressive': 'progressive', 'partialV': 'partial',
              'equivalent': 'equivalent', 'rejected': 'rejected'}
VERDICTS = set(LEAN_TO_PY.values())


def _lean_judge_enum(baseline: int, noise_band: int, direction: str,
                     measured: int, novel: bool) -> str:
    """Pure re-derivation of the Lean kernel `judge` (Pidna.lean:53-56), integer-scaled,
    including the boundary forms `improved` (Pidna.lean:38-41) and `withinNoise` (Pidna.lean:44-45).
    Returns the Lean enum NAME ('partialV' etc) — mapped to Python vocab by the caller."""
    delta = measured - baseline
    improved = (delta < -noise_band) if direction == 'lower' else (delta > noise_band)
    within = (-noise_band <= delta <= noise_band)
    if improved:
        return 'progressive' if novel else 'partialV'
    return 'equivalent' if within else 'rejected'


def _grid():
    """Bounded integer grid over (baseline, noise_band≥0, direction, measured, novel)."""
    for baseline in range(-4, 5):
        for noise_band in range(0, 5):
            for direction in ('lower', 'higher'):
                for measured in range(-12, 13):
                    for novel in (False, True):
                        yield baseline, noise_band, direction, measured, novel


def _run_judge(baseline, noise_band, direction, measured, novel):
    """Invoke the REAL judge.py. `novel` is driven through an independent NovelTarget that always
    corroborates (so we exercise judge's novel=True branch without coupling it to the main metric);
    novel=False is the no-target path (F-CON-3: text alone never grants novelty)."""
    pred = Prediction(metric_name='m', direction=direction,
                      baseline_value=float(baseline), noise_band=float(noise_band))
    if novel:
        nt = NovelTarget(metric_name='novel_m', direction='higher', threshold=0.0)
        v = judge(pred, float(measured), novel_target=nt, novel_measured=1.0)  # 1.0>=0 → corroborated
    else:
        v = judge(pred, float(measured))
    return v


# ════════════════════════════════════════════════════════════════════════════
#  Master conformance — Python judge == Lean judge truth-table, exhaustively
# ════════════════════════════════════════════════════════════════════════════
def test_judge_conforms_to_lean_truth_table_exhaustive():
    """Pidna.lean:53 `judge` — for every grid point the REAL judge.py verdict equals the Lean
    model's verdict (via the vocab bridge). The boundary forms match exactly (Pidna.lean:38-45 ↔
    judge.py:86-90), so this passes — that *is* the conformance receipt, not a bug hunt."""
    cases = checked = 0
    for case in _grid():
        cases += 1
        v = _run_judge(*case)
        expected = LEAN_TO_PY[_lean_judge_enum(*case)]
        assert v.verdict == expected, f'divergence at {case}: py={v.verdict} lean={expected}'
        checked += 1
    assert checked == cases and cases > 3000   # 4500 cases — exhaustive over the band


def test_conformance_harness_is_not_vacuous():
    """RED-with-teeth: a deliberately WRONG bridge (Lean partialV -> 'progressive') must make the
    truth-table comparison FAIL on many cases — proof the conformance would catch a real
    model<->impl divergence (the test is not trivially green)."""
    bad = {**LEAN_TO_PY, 'partialV': 'progressive'}
    mismatches = sum(1 for case in _grid()
                     if _run_judge(*case).verdict != bad[_lean_judge_enum(*case)])
    assert mismatches > 0


# ── Judge kernel theorems (Pidna.lean §1) ───────────────────────────────────
def test_progressive_requires_novel():
    """Pidna.lean:63 progressive_requires_novel — verdict=progressive ⟹ novel."""
    for case in _grid():
        v = _run_judge(*case)
        if v.verdict == 'progressive':
            assert v.novel is True, f'progressive without novel at {case}'


def test_progressive_requires_improved():
    """Pidna.lean:69 progressive_requires_improved — verdict=progressive ⟹ improved."""
    for case in _grid():
        v = _run_judge(*case)
        if v.verdict == 'progressive':
            assert v.improved is True, f'progressive without improved at {case}'


def test_no_novel_no_progressive():
    """Pidna.lean:75 no_novel_no_progressive — improved ∧ ¬novel caps at 'partial', never progressive."""
    for baseline, noise_band, direction, measured, _novel in _grid():
        v = _run_judge(baseline, noise_band, direction, measured, False)   # force novel=False
        assert v.verdict != 'progressive'
        if v.improved:
            assert v.verdict == 'partial'   # the Lakatos ad-hoc patch


def test_judge_total():
    """Pidna.lean:80 judge_total — the verdict is always exactly one of the 4 (closed-world)."""
    for case in _grid():
        assert _run_judge(*case).verdict in VERDICTS


# ── Rung theorems (Pidna.lean §2: receipt, not self-report) ──────────────────
def test_judge_is_receipt_and_unique():
    """Pidna.lean:100 rung_is_receipt + :112 rung_verdict_unique — judge is a deterministic pure
    function: the same (pred, measured, novel) yields the same verdict every time (no second,
    negotiated re-score). The Rung.derived field's runtime shadow: a node's verdict IS judge's output."""
    for case in _grid():
        a, b = _run_judge(*case), _run_judge(*case)
        assert a.verdict == b.verdict and a.novel == b.novel and a.improved == b.improved


# ════════════════════════════════════════════════════════════════════════════
#  Credence dedup theorems (Pidna.lean §3) over the REAL branch_credence
# ════════════════════════════════════════════════════════════════════════════
def _conf(target, delta=1.0, noise=0.1, verdict='progressive'):
    """A single confirmation (BF>1) of `target` — the content-dedup key is `target`."""
    return {'verdict': verdict, 'delta': delta, 'noise_band': noise, 'target': target}


def test_reconfirm_idempotent():
    """Pidna.lean:133 reconfirm_idempotent — re-confirming the SAME target adds no excess content;
    credence([c]) == credence([c, c, c]) (the bug fix: same progressive ×N no longer inflates)."""
    one = branch_credence([_conf('q1')])
    many = branch_credence([_conf('q1'), _conf('q1'), _conf('q1')])
    assert math.isclose(one, many, abs_tol=1e-12)


def test_confirm_order_independent():
    """Pidna.lean:139 confirm_order_independent — credence is independent of confirmation order
    (Bayesian coherence; per-target max + commutative odds product)."""
    a, b = _conf('q1', delta=1.0), _conf('q2', delta=2.0)
    assert math.isclose(branch_credence([a, b]), branch_credence([b, a]), abs_tol=1e-12)


def test_confirm_monotone():
    """Pidna.lean:146 confirm_monotone — adding a confirmation never lowers credence (assets accumulate)."""
    a = _conf('q1', delta=1.0)
    base = branch_credence([a])
    with_more = branch_credence([a, _conf('q2', delta=1.0)])
    assert with_more >= base - 1e-12


def test_stronger_confirm_strict():
    """Pidna.lean:151 stronger_confirm_strict — a new, stronger distinct target STRICTLY raises
    credence (distinct novel predictions are independent evidence; use-novelty)."""
    weak = _conf('q1', delta=0.5, noise=0.4)
    strong = _conf('q2', delta=5.0, noise=0.1)
    assert branch_credence([weak, strong]) > branch_credence([weak]) + 1e-9


def test_imax_assoc_shadow_distinct_targets_fold_order_free():
    """Pidna.lean:156 imax_assoc — the N-confirmation fold is order-free: any permutation of three
    distinct confirmations yields the same credence (associativity of the per-target aggregate)."""
    a, b, c = _conf('q1', delta=1.0), _conf('q2', delta=2.0), _conf('q3', delta=3.0)
    import itertools
    creds = {round(branch_credence(list(p)), 12) for p in itertools.permutations([a, b, c])}
    assert len(creds) == 1
