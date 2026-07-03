"""FIX-HARNESS #2 (P3 dead-code / latent fail-open): promotion_decision() lacks the CANONICAL floor gate.

finding id: #2
locations:
  - lakatos/verdict/spine.py:133-143  promotion_decision  — composes ONLY
      constitution(promotion_gate) + foundation + credibility. NO floor gate.
  - lakatos/verdict/spine.py:146-191  synthesize_promotion — the sibling spine that
      added (R3 fix, :167-189) the CANONICAL FLOOR: a *forgery-proof receipt* (≥1) is
      required, else gates collapse to constitution-only ("not-rejected + no critique")
      and an internal proof node becomes CANONICAL with ZERO receipt
      ('no_receipt_for_canonical'). promotion_decision never got that gate.
  - lakatos/verdict/promote.py:19  PROMOTABLE = (SCRIPTED ∩ PROGRESS) | ADMIN | {progressive_conditional}
      — so promotable verdicts exist that are NOT scripted judge-receipts.

the bug:
  promotion_decision(scripted_verdict='progressive_conditional', stands=True, reproducible=None,
  no foundation/credibility) → (passed=True, ()). The candidate is PROMOTABLE (passes the
  constitution gate) yet carries ZERO forgery-proof receipt: is_scripted_verdict('progressive_conditional')
  is False (engine-derived label, not a judge-scored verdict), reproducible is None (non-final, check
  skipped), and there is no human verdict. synthesize_promotion BLOCKS this exact candidate with
  'no_receipt_for_canonical' (floor gate). promotion_decision PASSES it → constitution-only collapse →
  receipt-0 CANONICAL, the precise failure mode R3 closed for synthesize_promotion.
  (Note: the literal scripted 'progressive' case is masked because the floor's legacy vocabulary
  fallback treats a scripted verdict as a receipt; the gap is exposed cleanly by any promotable
  *non-scripted* verdict — progressive_conditional or an ADMIN verdict — which both spines reach.)
  promotion_decision has NO production caller (only 2 isolation unit tests), so this is latent /
  dead-code today, but it is a live fail-open the moment anything routes through it.

the exact fix (lakatos/verdict/spine.py:133-143):
  delete promotion_decision, OR route it through the same floor gate / delegate to
  synthesize_promotion so it carries the identical 'no_receipt_for_canonical' floor.
  Post-fix contract: a progressive(_conditional)+stands=True+reproducible=None candidate with no
  forgery-proof receipt must NOT pass — it must agree with synthesize_promotion's block.

xfail(strict) until fixed: the negative-oracle assertion encodes the post-fix block; it FAILS today
(promotion_decision returns passed=True, ()), so it is RED while the bug is present and strict trips
the moment promotion_decision gains (or delegates to) the floor gate. The companion test is a
positive/mechanism oracle: it pins that synthesize_promotion DOES carry the floor (green today),
making the missing-mechanism axis explicit.
"""
from __future__ import annotations

import pytest

from lakatos.verdict.spine import promotion_decision, synthesize_promotion

# A PROMOTABLE but NON-scripted-receipt candidate: passes the constitution gate yet carries no
# forgery-proof receipt (not a judge verdict, reproducible=None, no human). Real shared surface of
# both spines — no synthetic kwargs.
_RECEIPT0_CANONICAL = dict(scripted_verdict='progressive_conditional', stands=True, reproducible=None)


# --- negative oracle (defect axis): promotion_decision must carry the floor that synthesize_promotion has.
# [FIXED 2026-06-27] #2 — green regression (spine.promotion_decision carries the no_receipt_for_canonical floor)
def test_promotion_decision_carries_no_receipt_floor():
    # Pre-conditions: sibling spine BLOCKS this exact candidate via the R3 floor gate.
    sp = synthesize_promotion(**_RECEIPT0_CANONICAL)
    assert sp['ok'] is False
    assert 'no_receipt_for_canonical' in sp['reasons']

    # Post-fix contract: promotion_decision must AGREE — a promotable-but-receipt-0 candidate
    # does NOT pass, carrying the same floor reason. Today it fail-opens to (True, ()).
    passed, reasons = promotion_decision(**_RECEIPT0_CANONICAL)
    assert passed is False, (
        "promotion_decision passed a receipt-0 CANONICAL candidate (constitution-only collapse); "
        "synthesize_promotion blocks it with no_receipt_for_canonical")
    assert 'no_receipt_for_canonical' in reasons


# --- positive / mechanism oracle (green today): the floor gate EXISTS in synthesize_promotion.
# This is the mechanism that promotion_decision is missing; pinning it keeps both spines honest.
def test_synthesize_promotion_floor_blocks_receipt0_canonical():
    out = synthesize_promotion(**_RECEIPT0_CANONICAL)
    assert out['ok'] is False
    assert 'no_receipt_for_canonical' in out['reasons']
    assert out['gates']['floor']['passed'] is False
    # Sanity: a genuine judge receipt (scripted progressive, default source vocabulary) still passes
    # the floor, so the gate is a floor and not a blanket deny.
    assert synthesize_promotion(scripted_verdict='progressive', stands=True, reproducible=None)['ok'] is True
