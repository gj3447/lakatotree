/** 머신 테이블 — spec/lakatos-node-fsm.v0.json 의 전이 구조 그대로.
 * spec-pin 테스트(tests/unit/fsm-conform.test.ts)가 스펙 JSON 과의 합치를 강제한다. */
import type { MachineDef } from "../contracts/fsm.ts";

export const MACHINES: readonly MachineDef[] = [
  {
    id: "node-judgment",
    initial: "draft",
    states: ["draft", "preregistered", "judged"],
    finals: [],
    events: ["PREDICTION_REGISTERED", "RESULT_SUBMITTED", "REJUDGE_SUBMITTED"],
    transitions: [
      { id: "register-prediction", from: "draft", event: "PREDICTION_REGISTERED", to: "preregistered", guard: "is_author", effects: ["SealPredictionReceipt"] },
      { id: "submit-result", from: "preregistered", event: "RESULT_SUBMITTED", to: "judged", guard: "is_author", effects: ["SealVerdictReceipt"] },
      { id: "rejudge", from: "judged", event: "REJUDGE_SUBMITTED", to: "judged", guard: "supersedes_matches_head", effects: ["SealVerdictReceipt", "MovePointerCAS"] },
    ],
  },
  {
    id: "node-standing",
    initial: "active",
    states: ["active", "demoted_stale", "retracted"],
    finals: [],
    events: ["ENGINE_RULE_STALE", "ENGINE_RULE_REFRESHED", "STANDING_RETRACTED", "STANDING_REINSTATED"],
    transitions: [
      { id: "demote-stale", from: "active", event: "ENGINE_RULE_STALE", to: "demoted_stale", guard: "is_engine_auditor", effects: ["MovePointerCAS"] },
      { id: "refresh-stale", from: "demoted_stale", event: "ENGINE_RULE_REFRESHED", to: "active", guard: "is_engine_auditor", effects: ["MovePointerCAS"] },
      { id: "retract", from: "active", event: "STANDING_RETRACTED", to: "retracted", guard: "is_human_owner", effects: ["MovePointerCAS"] },
      { id: "reinstate", from: "retracted", event: "STANDING_REINSTATED", to: "active", guard: "is_human_owner", effects: ["MovePointerCAS"] },
    ],
  },
  {
    id: "question",
    initial: "open",
    states: ["open", "closed"],
    finals: [],
    events: ["QUESTION_CLOSED", "QUESTION_REOPENED"],
    transitions: [
      { id: "close-by-judgment", from: "open", event: "QUESTION_CLOSED", to: "closed", guard: "from_judgment_seam", effects: ["RecordQuestionClosure"] },
      { id: "reopen", from: "closed", event: "QUESTION_REOPENED", to: "open", guard: "is_human_owner", effects: ["RecordQuestionReopen"] },
    ],
  },
  {
    id: "evidence-bundle",
    initial: "received",
    states: ["received", "sealed", "rejected"],
    finals: ["sealed", "rejected"],
    events: ["BUNDLE_SHA_VERIFIED", "BUNDLE_REJECTED"],
    transitions: [
      { id: "seal-bundle", from: "received", event: "BUNDLE_SHA_VERIFIED", to: "sealed", guard: "sha_matches", effects: ["RecordBundleSealed"] },
      { id: "reject-bundle", from: "received", event: "BUNDLE_REJECTED", to: "rejected", guard: null, effects: ["RecordBundleRejected"] },
    ],
  },
  {
    id: "tree",
    initial: "active",
    states: ["active", "archived"],
    finals: ["archived"],
    events: ["TREE_ARCHIVED"],
    transitions: [
      { id: "archive", from: "active", event: "TREE_ARCHIVED", to: "archived", guard: "is_human_owner", effects: ["RecordTreeArchived"] },
    ],
  },
];

export const machineById = (id: string): MachineDef | undefined =>
  MACHINES.find((m) => m.id === id);
