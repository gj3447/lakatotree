/-
  PIDNA — formal kernel for LakatoTree's verdict engine.

  This file pulls the prose manifesto (TOUCH_THE_SKY.md) and the conceptual model
  (docs/PIDNA.md) down to machine-checked theorems. Core Lean 4 only (no Mathlib).

  The hard core of the manifesto — "a rung is true only by receipt, never by
  self-report" — is encoded *in the type system*: a `Rung` cannot be constructed
  without a proof that its verdict equals the deterministic judge's output. Thus
  "an agent cannot score itself" is not a convention but a compiler-enforced invariant.

  Ground truth gate: `lake build` with error=0, sorry=0.
-/

-- M7 (design audit): *enforce* the sorry=0 gate, don't merely document it. In Lean
-- `sorry` is a warning and `lake build` exits 0 on warnings, so the `Rung.derived`
-- self-report invariant below could be forged by one `sorry` line with the build still
-- green. File-scoped `warningAsError` promotes every warning (incl. "declaration uses
-- 'sorry'") to an error → non-zero exit. Safe here: this file builds with zero warnings,
-- so the option only bites when a `sorry`/linter regression is introduced.
set_option warningAsError true

namespace Pidna

/-! ## 1. Verdict kernel (Popper layer — `lakatos/judge.py`) -/

/-- Improvement direction of a metric. -/
inductive Direction | lower | higher
deriving DecidableEq, Repr

/-- A pre-registered prediction (judge.py `Prediction`), integer-scaled.
    `noiseBand` is the dead-band; negative noise (worse-is-progressive gaming) is
    excluded at the Python boundary and irrelevant to the kernel theorems below. -/
structure Prediction where
  baseline  : Int
  noiseBand : Int
  direction : Direction
deriving Repr

/-- Scripted verdict vocabulary (subset of `lakatos/verdicts.py`). `partialV` is the
    "improved but not novel" patch verdict Lakatos warned about. -/
inductive Verdict
  | progressive | partialV | equivalent | rejected
deriving DecidableEq, Repr

/-- Did the measurement improve past the noise band, in the predicted direction? -/
def improved (p : Prediction) (measured : Int) : Bool :=
  match p.direction with
  | .lower  => decide (measured - p.baseline < - p.noiseBand)
  | .higher => decide (measured - p.baseline >   p.noiseBand)

/-- Is the change within noise (no real movement)? -/
def withinNoise (p : Prediction) (measured : Int) : Bool :=
  decide (-p.noiseBand ≤ measured - p.baseline ∧ measured - p.baseline ≤ p.noiseBand)

/-- The deterministic verdict (judge.py `judge`). `novel : Bool` is an *input* here; its
    provenance — that it is set only by external corroboration of a structural novel target,
    never by text (F-CON-3) — is enforced at the Python boundary (`NovelTarget.corroborated`,
    with a ValueError if the novel measurement is omitted), NOT proven by this kernel. What this
    kernel proves is the *propagation*: progressive REQUIRES improved ∧ novel — given an honest
    `novel`, "you cannot buy progressive with prose". -/
def judge (p : Prediction) (measured : Int) (novel : Bool) : Verdict :=
  cond (improved p measured)
    (cond novel .progressive .partialV)
    (cond (withinNoise p measured) .equivalent .rejected)

/-! ### Kernel theorems (the Popper/Lakatos guarantees) -/

/-- progressive ⟹ novel. The verdict cannot be progressive unless `novel` holds; combined with
    the Python boundary that only sets `novel` by external corroboration, a degenerating-but-fluent
    patch (no novel target) can never be scored progressive. (This theorem proves the left half.) -/
theorem progressive_requires_novel (p : Prediction) (m : Int) (novel : Bool)
    (h : judge p m novel = .progressive) : novel = true := by
  cases hi : improved p m <;> cases hn : novel <;> cases hw : withinNoise p m <;>
    simp_all [judge]

/-- progressive ⟹ improved. No regression or noise-level change is ever progress. -/
theorem progressive_requires_improved (p : Prediction) (m : Int) (novel : Bool)
    (h : judge p m novel = .progressive) : improved p m = true := by
  cases hi : improved p m <;> cases hn : novel <;> cases hw : withinNoise p m <;>
    simp_all [judge]

/-- Improved but not novel caps at `partialV` — never progressive (Lakatos's ad-hoc patch). -/
theorem no_novel_no_progressive (p : Prediction) (m : Int)
    (hi : improved p m = true) : judge p m false ≠ .progressive := by
  simp [judge, hi]

/-- `judge` is total and deterministic: a pure function of (prediction, measurement, novelty). -/
theorem judge_total (p : Prediction) (m : Int) (novel : Bool) :
    judge p m novel = .progressive ∨ judge p m novel = .partialV ∨
    judge p m novel = .equivalent ∨ judge p m novel = .rejected := by
  cases hi : improved p m <;> cases hn : novel <;>
    cases hw : withinNoise p m <;> simp_all [judge]

/-! ## 2. The PIDNA rung — "receipt, not self-report" as a *type* -/

/-- One rung of the ascending helix: a base-pair [conjecture ↔ verification].
    ★`derived` makes the verdict *unforgeable*: you cannot build a `Rung` whose
    `verdict` differs from `judge pred measured novel`. Self-reported verdicts are
    uninhabitable. This is the manifesto hard core, enforced by the elaborator. -/
structure Rung where
  pred     : Prediction
  measured : Int
  novel    : Bool
  verdict  : Verdict
  derived  : verdict = judge pred measured novel

/-- Every rung's verdict is exactly the engine's output (by construction). -/
theorem rung_is_receipt (r : Rung) : r.verdict = judge r.pred r.measured r.novel :=
  r.derived

/-- A progressive rung necessarily carries a corroborated novel prediction. -/
theorem progressive_rung_is_novel (r : Rung) (h : r.verdict = .progressive) :
    r.novel = true := by
  have hd := r.derived
  rw [h] at hd
  exact progressive_requires_novel r.pred r.measured r.novel hd.symm

/-- Verdict uniqueness: two rungs over the same evidence MUST agree. The engine's
    word is final — there is no second, negotiated verdict (no self-scoring). -/
theorem rung_verdict_unique (r₁ r₂ : Rung)
    (hp : r₁.pred = r₂.pred) (hm : r₁.measured = r₂.measured) (hn : r₁.novel = r₂.novel) :
    r₁.verdict = r₂.verdict := by
  rw [r₁.derived, r₂.derived, hp, hm, hn]

/-! ## 3. Use-novelty credence dedup (Zahar 1973 — `bayes.branch_credence`)

  Credence accumulates in log-odds space (odds *= BF ⟺ logOdds += logBF). For
  confirmations (logBF > 0) of the *same* target, only the strongest counts: repeated
  corroboration of one fact adds no excess empirical content. We model the per-target
  aggregate `best` and prove the three properties the Python `content-dedup` relies on.
-/

/-- Integer max, kept explicit so `omega` can see through it. -/
def imax (a b : Int) : Int := if a ≤ b then b else a

/-- Fold one confirmation of weight `w` into a target's running best. -/
def addConfirm (best w : Int) : Int := imax best w

/-- IDEMPOTENT: re-confirming the same target with no stronger evidence changes nothing.
    (the bug fix: same progressive ×10 no longer inflates credence) -/
theorem reconfirm_idempotent (best w : Int) (h : w ≤ best) :
    addConfirm best w = best := by
  unfold addConfirm imax; split <;> omega

/-- COMMUTATIVE / order-independent: credence does not depend on confirmation order
    (a Bayesian coherence requirement; `max` is order-free). -/
theorem confirm_order_independent (best w₁ w₂ : Int) :
    addConfirm (addConfirm best w₁) w₂ = addConfirm (addConfirm best w₂) w₁ := by
  unfold addConfirm imax
  repeat' split
  all_goals omega

/-- MONOTONE: confirming never lowers credence (assets accumulate). -/
theorem confirm_monotone (best w : Int) : best ≤ addConfirm best w := by
  unfold addConfirm imax; split <;> omega

/-- A *new, stronger* target strictly raises the per-target best — distinct novel
    predictions ARE independent evidence (use-novelty: only new facts corroborate). -/
theorem stronger_confirm_strict (best w : Int) (h : best < w) :
    best < addConfirm best w := by
  unfold addConfirm imax; split <;> omega

/-- Associativity underwrites order-independence of an N-confirmation fold. -/
theorem imax_assoc (a b c : Int) : imax (imax a b) c = imax a (imax b c) := by
  unfold imax
  repeat' split
  all_goals omega

end Pidna
