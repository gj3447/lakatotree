/** FSM wire 타입 — 기계 정본 ts/spec/lakatos-node-fsm.v0.json 의 TS 투영.
 * spec-pin 테스트가 이 테이블과 스펙 JSON 의 합치를 게이트한다 (드리프트 = RED). */

export type MachineId =
  | "node-judgment"
  | "node-standing"
  | "question"
  | "evidence-bundle"
  | "tree";

export type ActorRole =
  | "author"
  | "anchor_verifier"
  | "engine_auditor"
  | "judgment_seam"
  | "human_owner";

export type EventType =
  | "PREDICTION_REGISTERED"
  | "RESULT_SUBMITTED"
  | "REJUDGE_SUBMITTED"
  | "ENGINE_RULE_STALE"
  | "ENGINE_RULE_REFRESHED"
  | "STANDING_RETRACTED"
  | "STANDING_REINSTATED"
  | "QUESTION_CLOSED"
  | "QUESTION_REOPENED"
  | "BUNDLE_SHA_VERIFIED"
  | "BUNDLE_REJECTED"
  | "TREE_ARCHIVED";

export type GuardName =
  | "is_author"
  | "is_engine_auditor"
  | "is_human_owner"
  | "from_judgment_seam"
  | "supersedes_matches_head"
  | "sha_matches";

export type EffectName =
  | "SealPredictionReceipt"
  | "SealVerdictReceipt"
  | "MovePointerCAS"
  | "RecordQuestionClosure"
  | "RecordQuestionReopen"
  | "RecordBundleSealed"
  | "RecordBundleRejected"
  | "RecordTreeArchived"
  | "AuditInvalidTransition";

export interface FsmEvent {
  readonly type: EventType;
  readonly event_id: string;
  readonly actor_role: ActorRole;
  readonly payload: Readonly<Record<string, string | number>>;
}

export interface Configuration {
  readonly state: string;
  readonly context: {
    readonly head_receipt_sha: string;
    readonly prediction_sealed: boolean;
    readonly last_verdict: string;
  };
}

export interface EffectCommand {
  readonly effect: EffectName;
  readonly payload: Readonly<Record<string, string | number>>;
}

export interface StepResult {
  readonly next: Configuration;
  readonly commands: readonly EffectCommand[];
  readonly admitted: boolean;
  readonly rejection_reason: string;
}

export interface TransitionDef {
  readonly id: string;
  readonly from: string;
  readonly event: EventType;
  readonly to: string;
  readonly guard: GuardName | null;
  readonly effects: readonly EffectName[];
}

export interface MachineDef {
  readonly id: MachineId;
  readonly initial: string;
  readonly states: readonly string[];
  readonly finals: readonly string[];
  readonly events: readonly EventType[];
  readonly transitions: readonly TransitionDef[];
}
