"""FIX-HARNESS #1 (P2 honesty — the central guarantee): the CANONICAL floor treated 'judge-scored'
as an *unforgeable* receipt, but the underlying measurement is an unverified client float never re-executed.

finding id: #1 (P2 honesty — central guarantee overstatement)
locations:
  - lakatos/verdict/spine.py  synthesize_promotion CANONICAL floor (judge_receipt | reproducible | human).
  - lakatos/judge.py:98-110  judge() takes measured/novel_measured as CLIENT floats (finiteness only);
      submit never re-executes the scoring script (_recompute_script_sha hashes the script FILE identity).
  - server/app.py:395  itself states real producer replay is unimplemented.

the bug (overstatement):
  The floor called a scripted-judged progressive a '위조불가(unforgeable)' receipt. But PROM-A only blocks
  self-WRITING the verdict LABEL; the MEASUREMENT behind it (metric_value/novel_measured) is an unverified
  client float that submit never re-executes. So a scripted progressive with reproducible=None and no human
  opens CANONICAL on a measurement that was never externally verified — yet the system reported it as the
  unforgeable receipt, hiding the gap.

the fix (honest exposure — behavior unchanged; option-(b)+):
  Forcing an external anchor for *every* CANONICAL (option-(a)) is a central-semantics change (empirically
  breaks 11 floor tests = the engine's documented promotion contract) and the forge cannot truly close until
  producer replay lands. So this fix does NOT block promotion; it makes the system *honest*: the floor gate
  now reports `measurement_externally_anchored` (True iff reproducible==True or human attestation; False if
  the floor opened on judge_receipt alone). The '위조불가' overstatement is closed — a judge_receipt-only
  CANONICAL is now explicitly flagged as NOT externally anchored. Option-(a) enforcement and producer replay
  remain documented frontier (see tests/fix_harness/README.md).

contract pinned below (post-fix): the floor exposes measurement_externally_anchored, and it is False exactly
when the floor opened on judge_receipt alone (the gap is now visible, not hidden). xfail(strict) until fixed.
"""
from __future__ import annotations

import pytest

from lakatos.verdict.spine import synthesize_promotion
from lakatos.verdicts import force_of


# mechanism/positive oracle: an *externally-anchored* receipt (real reproducible replay) opens the floor
# AND is reported as anchored. This path stays green and pins that the flag tracks real external anchoring.
def test_external_receipt_is_flagged_externally_anchored():
    assert force_of('progressive', 'scripted') == 'COUNTS'   # SSOT predicate the floor reads
    ext = synthesize_promotion(scripted_verdict='progressive', stands=True,
                               reproducible=True, verdict_source='reproducible')
    assert ext['ok'] is True
    assert ext['gates']['floor']['passed'] is True
    assert ext['gates']['floor']['measurement_externally_anchored'] is True


# [FIXED 2026-06-28] #1 — green regression (spine floor exposes measurement_externally_anchored; overstatement closed)
def test_judge_receipt_only_canonical_is_flagged_not_externally_anchored():
    """Defect-axis negative oracle: a scripted 'progressive' whose ONLY receipt is judge_receipt —
    reproducible=None and no human — still opens the floor (promotion behavior unchanged), but the floor
    must now *honestly* report measurement_externally_anchored=False (the measurement behind 'progressive'
    was never externally re-executed). Before the fix the floor exposed no such flag — it presented the
    judge_receipt as an unforgeable receipt, hiding the gap."""
    out = synthesize_promotion(
        scripted_verdict='progressive',   # scripted progressive (PROM-A blocks the LABEL only)
        stands=True,                       # no unresolved doubt
        reproducible=None,                 # NO real lineage replay (the only external-measurement gate)
        verdict_source='scripted',         # force_of==COUNTS → judge_receipt True
        credibility=None,                  # no credibility receipt, and has_human=False
        foundation=None,
        qualitative_self_report=False,
    )
    floor = out['gates']['floor']
    # promotion behavior unchanged — the floor still opens on judge_receipt (no central-semantics change)…
    assert floor['passed'] is True
    # …but the gap is now HONESTLY exposed: this CANONICAL's measurement is NOT externally anchored.
    assert floor['measurement_externally_anchored'] is False, (
        'floor opened on judge_receipt alone but did not honestly flag the measurement as '
        'not-externally-anchored (the overstatement #1 closes)')


# dual-guard exports
guard_defect = 'test_judge_receipt_only_canonical_is_flagged_not_externally_anchored'
guard_mechanism = 'test_external_receipt_is_flagged_externally_anchored'
