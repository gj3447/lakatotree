# `lakato-evidence-record/v1` — a portable honesty contract for evidence

A tiny, tool-agnostic JSON format for **evidence about a claim** — designed so the
party that *produces* a result can never *grade* it. If an AI agent or a researcher
emits one of these, a reader (or any judge) can check, by construction, that the
claim was **pre-registered**, **measured against grounded inputs**, and **carries no
self-authored verdict**.

> This format is **independent of any tool**. Any producer can emit it; any consumer
> can validate it in ~25 lines. LakatoTree's `lakatos.programme.evidence` is one
> reference implementation, not a dependency.

## The problem it encodes away

A model (or a person) that both *does* the work and *judges* whether the work
succeeded will, on average, report success. "We made progress" is cheap when the
producer writes the verdict. `lakato-evidence-record/v1` moves three checks into the
**data itself**, so a vacuous or self-graded claim fails validation before any judge
is even consulted.

## The three invariants (a record that violates any of them is invalid)

1. **No verdict.** The record — and its `measurement` — must **not** contain a
   `verdict`/`progressive`/`pass` field. The judgement is derived *downstream* from
   the measurement by someone other than the producer. (This is the whole point:
   *the producer never grades itself.*)
2. **Grounded.** `measurement` must cite where its numbers came from —
   `provenance.inputs` (named sources) and/or a `provenance.data_manifest`. A number
   with no traceable origin is not evidence.
3. **Pre-registered.** `preregistration.registered_before_measurement` must be
   `true`, and the record must state the prediction and a kill condition **before**
   the measurement — which blocks HARKing (hypothesizing after results are known).

## Schema

| field | required | meaning |
|---|---|---|
| `schema` | ✓ | the literal string `"lakato-evidence-record/v1"` |
| `programme` / `conjecture` | ✓ | which research programme / specific claim this measures (`branch`, `node_tag` optional) |
| `preregistration` | ✓ | the prediction locked **before** measuring: `predicted {metric,value,unit}`, `kill_condition`, `registered_before_measurement: true` |
| `measurement` | ✓ | the observed `metric` / `value` / `unit` (+ optional `derived`). **No verdict.** |
| `provenance` | ✓ | `inputs` (named sources) and/or `data_manifest`, plus a `grounded` flag |
| `harness` | ✓ | how to reproduce it: `script`, `git_commit`, `env`, `timestamp` |
| `findings` | | proposed `closes` / `opens` frontiers — *interpreted* downstream, not decided here |
| `gauge` | | optional measurement-system analysis (repeatability/reproducibility) |

## Example

```json
{
  "schema": "lakato-evidence-record/v1",
  "programme": "coding-agent-refactor",
  "conjecture": "extract_auth_module_no_regression",
  "preregistration": {
    "claim": "extracting the auth module does not regress the suite",
    "predicted": {"metric": "tests_failing_after", "value": 0, "unit": "count"},
    "kill_condition": "any test that passed before now fails",
    "registered_before_measurement": true
  },
  "measurement": {
    "metric": "tests_failing_after",
    "value": 0,
    "unit": "count",
    "derived": {"tests_total": 1668, "duration_s": 41.2}
  },
  "provenance": {
    "inputs": [
      {"name": "pytest_junit", "source": "artifacts/junit-after.xml", "sha256": "…"},
      {"name": "baseline_junit", "source": "artifacts/junit-before.xml", "sha256": "…"}
    ],
    "grounded": true
  },
  "harness": {
    "script": "scripts/run_suite.sh",
    "git_commit": "8a09d29",
    "env": "python3.12",
    "timestamp": "2026-07-15T12:00:00Z"
  },
  "findings": [
    {"kind": "closes", "frontier": "q_auth_extract_safe",
     "body": "0/1668 regressions after extraction"}
  ]
}
```

Note what is **absent**: nowhere does the record say "PASS" or "progressive". A
consumer derives that from `predicted` vs `measured` against the grounded inputs.

## Reference validator (language-agnostic)

```python
SCHEMA   = "lakato-evidence-record/v1"
REQUIRED = ("schema","programme","conjecture","preregistration",
            "measurement","provenance","harness")

def validate(rec: dict) -> list[str]:
    errs = []
    if rec.get("schema") != SCHEMA:
        errs.append("wrong schema")
    for k in REQUIRED:
        if k not in rec:
            errs.append(f"missing: {k}")
    # 1. no self-authored verdict
    if "verdict" in rec:                      errs.append("verdict at top level")
    if "verdict" in (rec.get("measurement") or {}): errs.append("verdict in measurement")
    # 2. grounded
    prov = rec.get("provenance") or {}
    if not prov.get("inputs") and not prov.get("data_manifest"):
        errs.append("ungrounded: no inputs / data_manifest")
    # 3. pre-registered
    if (rec.get("preregistration") or {}).get("registered_before_measurement") is not True:
        errs.append("not pre-registered")
    return errs        # [] == valid
```

That is the entire contract. Adopt it by emitting the JSON from your own harness;
a record that passes `validate()` is one whose author did not get to mark their own
homework.

## Relationship to LakatoTree

LakatoTree consumes these records as `source_record` grounding for its deterministic,
replayable verdicts (`pre-register → measure → derive judgement`). But the format
stands on its own: it is useful anywhere an autonomous producer's claims need to be
audit-ready without trusting the producer. See
[`EVIDENCE_RECORD.md`](EVIDENCE_RECORD.md) for the reference loader/validator API.
