# Programme-Series Axis

Prometheus decision: `DIAGNOSTIC_LAYER_IMPLEMENTED`.

Lakatos appraises research programmes through series of theories and
progressive or degenerating problem-shifts. Lakatotree already has partial
coverage:

- node-local verdict authority;
- `metrics.tree_metrics` aggregation;
- `lifecycle.lifecycle_state`;
- `stack.stack_verdict`.

Implemented safe step:

- `ProgrammeSeriesRecord` is a time-ordered step with verdict, problem-balance
  delta, rival anomaly pressure, optional conceptual pressure, and lifecycle tag.
- `programme_series_appraisal` summarizes the series as `progressive`,
  `degenerating`, `mixed`, `off_axis`, or `insufficient`.
- `different_programme` and `withdrawn` are off-axis identity events, not
  within-programme degeneration pressure.
- `ProgrammeSeriesAppraisal.authority == "diagnostic_only"` and
  `promotion_authority is False`; this module does not rewrite canonical
  promotion or abandonment.

OOPTDD receipt: `tests/test_programme_series.py` fixes the object roles and
observable outcomes for sustained progress, rival-pressure degeneration,
off-axis forks, conceptual pressure, validation, and recent-window behavior.
