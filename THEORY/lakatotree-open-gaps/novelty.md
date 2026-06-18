# Novelty Axis

Prometheus decision: `MAINTAIN_DONT_DO_CLOSED`.

Current code is intentionally conservative:

- `zahar_use_novelty` is scored through pre-registration and structural
  corroboration.
- `temporal_novelty` and `worrall_use_novelty` are surfaced as tags.
- Tests assert that changing the tag does not change scoring.
- `NOVELTY_SENSE_SCORING_POLICY = "tag_only"` is the single owner of this
  negative policy.

This should stay that way. The literature does not give one uncontested scoring
oracle for all novelty senses. Adding numeric scoring for temporal or Worrall
novelty would create false precision.

OOPTDD receipt: `tests/test_novelty_policy.py` exercises the policy object and
the outcome boundary. The outcome must stay invariant across `zahar`,
`temporal`, and `worrall` novelty tags while the audit reason still surfaces the
selected sense.
