# Runtime Lean PROM Dossier - 2026-06-26

> 목적: "Python 런타임 전체를 Lean4 로 직접 검증"이라는 과장을 버리고,
> Lean-checkable certificate 가 중요한 런타임 상태전이의 권한경계가 되게 한다.
> 짝 하네스: `examples/runtime_lean_20260626_programme.py`.

## Headline

직접 증명 대상은 Python/FastAPI/Neo4j 전체가 아니다. 직접 증명 대상은
`judge/promotion/abandonment/receipt-force` 상태전이 헌법이다. Python runtime 은
그 헌법의 certificate 없이는 `CANONICAL`, `former_canonical`, `scripted` 같은
verdict-mutating write 를 못 하게 만든다.

이 접근은 선언문과 더 잘 맞는다. Python 을 믿는 것이 아니라, Python 에게도
자기 자신을 채점할 권리를 주지 않는다.

## Programme Nodes

| tag | missing today | guard |
|---|---|---|
| `L1_transition_system` | Lean 이 kernel judge/bayes 모델만 들고 있고 runtime 상태전이는 없음 | `test_lean_transition_system_builds_and_has_no_sorry` |
| `L2_certificate_schema` | state transition certificate 의 canonical schema 없음 | `test_certificate_schema_rejects_missing_receipt_force` |
| `L3_python_write_gate` | Python write path 가 certificate 없이 verdict state 를 바꿀 수 있음 | `test_uncertified_verdict_write_is_rejected` |
| `L4_io_three_valued_boundary` | partial/unreachable I/O 가 green 으로 붕괴할 위험 | `test_inconclusive_io_cannot_certify_transition` |
| `L5_lean_python_trace_equivalence` | Lean 모델과 Python 구현 drift 를 golden trace 로 잡지 않음 | `test_lean_python_golden_trace_equivalence` |
| `L6_no_sorry_axiom_gate` | `lake build` 성공이 `sorry=0`을 뜻하지 않음 | `test_formal_ci_rejects_sorry_and_unapproved_axioms` |

## Implementation Route

1. Extend `formal/Pidna.lean` from kernel verdict theorem to a small transition
   system: `TreeState`, `ReceiptForce`, `Transition`, `Certificate`.
2. Add a deterministic Lean checker executable or lake target that accepts a
   JSON-like input bundle and returns accept/reject for certificate claims.
3. Add Python certificate schema and verifier boundary. Missing receipt force,
   missing source hash, or inconclusive I/O cannot produce `valid=true`.
4. Route verdict-mutating server writes through the certificate verifier. This
   should reuse the existing H9 verdict CAS class-lock rather than inventing a
   parallel mutation surface.
5. Add shared golden traces: Lean checker and Python core must agree on verdict,
   receipt force, and promotion decision for the same trace corpus.
6. Harden formal CI with no-sorry/no-unapproved-axiom gates. `lake build` alone
   is necessary but not sufficient.

## Non-Goals

- Do not claim Python runtime total correctness.
- Do not model network reality inside Lean. Model I/O as `Present`, `Absent`,
  or `Inconclusive`, and force adapters to lower the world into that type.
- Do not trust a Python boolean named `valid`. Trust a certificate that can be
  independently rechecked from its input bundle.

## Expected End State

The runtime can still be Python. The authority moves: Python executes, Lean
certifies, and the database only accepts certified critical transitions.
