# Laudan Axis

Two open gaps are implementable candidates, but not as shortcuts.

## Conceptual Problems

Current code:

- `lakatos/quant/laudan.py` models empirical problem-solving with closed/open
  question balance.
- `conceptual_problem_score` models internal inconsistency and external conflict
  as a separate conceptual-problem diagnostic.

Prometheus decision:

The pure layer now exists. Do not fold these values into `opened` question
counts because that would hide the difference between empirical failure and
conceptual conflict. Higher-level stack/lifecycle integration still needs a
separate policy decision.

## Comparative Anomaly

Current code:

- Rival programmes now exist in evidence embedding.
- `RivalProblemRecord` records one programme's outcome for one problem.
- `rival_relative_anomaly` computes `target unsolved + rival solved`.

Prometheus decision:

The pure evaluator now exists. It avoids penalizing problems unsolved by
everyone by requiring at least one non-target programme to solve the same
problem with enough explanation quality. Tree-surface integration remains a
separate policy step.
