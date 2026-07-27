/-
  AxiomAudit — "machine-checked"의 정직 조건: 허용 공리 Ω={propext, Classical.choice,
  Quot.sound} 외의 공리(특히 `sorryAx`)에 의존하는 선언이 있으면 CI를 탈락시킨다.

  `set_option warningAsError true`(Pidna.lean)는 sorry를 빌드 에러로 승격하지만,
  이 파일은 그 *결과*를 감사한다 — 각 정리가 실제로 어떤 공리 위에 서 있는지 열거.
  실행: formal/axiom_audit.sh (lake build 후 `lake env lean AxiomAudit.lean`).
-/
import Pidna

-- §1 verdict kernel
#print axioms Pidna.progressive_requires_novel
#print axioms Pidna.progressive_requires_improved
#print axioms Pidna.no_novel_no_progressive
#print axioms Pidna.judge_total

-- §2 PIDNA rung
#print axioms Pidna.rung_is_receipt
#print axioms Pidna.progressive_rung_is_novel
#print axioms Pidna.rung_verdict_unique

-- §3 credence dedup
#print axioms Pidna.reconfirm_idempotent
#print axioms Pidna.confirm_order_independent
#print axioms Pidna.confirm_monotone
#print axioms Pidna.stronger_confirm_strict
#print axioms Pidna.imax_assoc
