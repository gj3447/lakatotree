"""FIX-HARNESS #1 (P2 honesty — the central guarantee): the CANONICAL floor treats
'judge-scored' as an unforgeable receipt, but the underlying measurement is an
unverified client float that is never re-executed.

finding id: #1 (P2 honesty — central guarantee overstatement)
locations:
  - lakatos/verdict/spine.py:167-189  synthesize_promotion CANONICAL floor.
      lakatos/verdict/spine.py:177-178  judge_receipt = (force_of(scripted_verdict, verdict_source)=='COUNTS').
      lakatos/verdict/spine.py:185      floor opens if `judge_receipt or reproducible is True or has_human`.
  - lakatos/judge.py:98-110  judge() takes measured/novel_measured as CLIENT floats and only
      checks finiteness; submit never re-executes the scoring script (_recompute_script_sha only
      hashes the script FILE identity, not the measurement).
  - server/app.py:395  itself states real producer replay is unimplemented.

the bug:
  The floor is advertised as requiring a *위조불가(unforgeable)* receipt — "영수증은 현실이
  끊어준다"(reality issues the receipt). But judge_receipt counts as that receipt whenever the
  verdict is a scripted progressive with a FORCEFUL verdict_source (e.g. 'scripted'):
  force_of('progressive','scripted')=='COUNTS'. PROM-A blocks a node from self-WRITING the verdict
  LABEL, but it does NOT make the MEASUREMENT external — the metric_value behind 'progressive' is an
  unverified client float that submit never re-executes. The only externally-anchored gate
  (reproducible == real lineage replay) is an ALTERNATIVE to judge_receipt and is non-blocking when
  absent (reproducible=None). So a scripted progressive whose ONLY receipt is judge_receipt, with
  reproducible=None and no human attestation, opens the CANONICAL floor on a measurement that was
  never externally verified.

the exact fix (pins option-(a)):
  lakatos/verdict/spine.py:185 — require an EXTERNAL/anchored receipt for CANONICAL when no
  externally-anchored measurement exists: `reproducible is True` (real replay) OR `has_human`
  (human attestation). judge_receipt alone (a scripted client measurement) must NOT open the floor.
  (Option (b) would instead make the README/docstrings honest that 'external measurement' is enforced
  only by pre-registration + script-sha identity until producer replay lands; we encode (a).)

This is a guarantee-overstatement: the stricter post-fix contract is encoded as the assertion
(floor must stay CLOSED on an unverified client measurement). xfail(strict) until fixed.
"""
from __future__ import annotations

import pytest

from lakatos.verdict.spine import synthesize_promotion
from lakatos.verdicts import force_of


# Pre-condition sanity (mechanism exists): a scripted progressive with a FORCEFUL verdict_source is
# what the floor currently treats as the unforgeable receipt. This is the exact predicate spine uses.
def test_judge_receipt_predicate_is_the_floor_signal():
    # mechanism/positive oracle: force_of is the SSOT predicate the floor reads. With reproducible=True
    # (a REAL externally-anchored receipt) the floor legitimately opens — this path must stay green.
    assert force_of('progressive', 'scripted') == 'COUNTS'
    ext = synthesize_promotion(scripted_verdict='progressive', stands=True,
                               reproducible=True, verdict_source='reproducible')
    assert ext['ok'] is True
    assert ext['gates']['floor']['passed'] is True


@pytest.mark.xfail(reason="FIX-HARNESS #1: CANONICAL floor opens on judge_receipt alone — an "
                          "unverified client measurement is never re-executed — RED until "
                          "lakatos/verdict/spine.py:185 (require reproducible=True OR human, not "
                          "judge_receipt alone); strict trips when fixed",
                   strict=True)
def test_canonical_floor_must_close_on_unverified_client_measurement():
    """Defect-axis negative oracle: a scripted 'progressive' whose ONLY receipt is judge_receipt —
    reproducible=None and no human attestation — must NOT pass the CANONICAL floor, because the
    measurement behind that progressive verdict was never externally verified (submit never
    re-executes the scoring script). Today synthesize_promotion returns ok=True via judge_receipt
    alone (bug = the floor opens on an unverified client measurement)."""
    out = synthesize_promotion(
        scripted_verdict='progressive',   # scripted progressive (PROM-A blocks the LABEL only)
        stands=True,                       # no unresolved doubt
        reproducible=None,                 # NO real lineage replay (the only external-measurement gate)
        verdict_source='scripted',         # force_of==COUNTS → judge_receipt True (the unforgeable-claim)
        credibility=None,                  # no credibility receipt, and has_human=False
        foundation=None,
        qualitative_self_report=False,
    )
    # Correct post-fix behavior (fix-option-(a)): judge_receipt alone is an UNVERIFIED client
    # measurement and must not be honored as the unforgeable receipt for CANONICAL.
    assert out['gates']['floor']['passed'] is False, (
        'CANONICAL floor opened on an unverified client measurement (judge_receipt alone) — '
        'no real replay (reproducible) and no human attestation')
    assert out['ok'] is False
    assert 'no_receipt_for_canonical' in out['gates']['floor']['reasons']


# dual-guard exports
guard_defect = 'test_canonical_floor_must_close_on_unverified_client_measurement'
guard_mechanism = 'test_judge_receipt_predicate_is_the_floor_signal'
