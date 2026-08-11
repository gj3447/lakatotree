/** 실행 애그리게이트 — CLAUDE.md §5 실행 예산의 기계 게이트 (B5: 산문→기계 강등).
 * B1: 예산 없는 자율 실행은 시작하지 않는다 — 선언 전 모든 이벤트 거부.
 * 정지는 리듀서 파생 전용 — 정지 입력 이벤트가 존재하지 않아 날조 정지가 타입상 표현 불가.
 * 초과 = 기재 후 정지(소비는 사실 — 계량이 숨기지 않는다) + 흡수 상태(재시도 아님).
 * 어휘·숫자의 기계 정본은 spec/run-budget.v0.json (드리프트 = run-conform RED). */
import type { BudgetState, ComputeSpend, TokenSpend } from "./ledger.ts";
import {
  emptyBudget,
  reduceBudget,
  validateComputeSpend,
  validateTokenSpend,
} from "./ledger.ts";
import type { BudgetDeclaration, CapBreach, Usage } from "./budget.ts";
import { checkCaps, usageOf, validateBudgetDeclaration } from "./budget.ts";
import type { GateResult, GateStreak } from "./streak.ts";
import { NO_PROGRESS_RED_LIMIT, reduceStreaks, streakOf } from "./streak.ts";
import type { EmissionLedger, EmissionRecorded } from "./emission.ts";
import { emptyEmissionLedger, reduceEmission, validateEmission } from "./emission.ts";
import type { WaitEvent } from "./wait.ts";
import { applyWait } from "./wait.ts";

export type RunEvent =
  | BudgetDeclaration
  | TokenSpend
  | ComputeSpend
  | GateResult
  | EmissionRecorded
  | WaitEvent;

export const REJECT_REASONS = [
  "budget_not_declared",
  "budget_already_declared",
  "empty_run_id",
  "negative_or_non_integer_cap",
  "run_id_mismatch",
  "negative_or_non_integer_tokens",
  "negative_or_non_integer_compute",
  "negative_or_non_integer_emission",
  "red_without_reason",
  "duplicate_wait_poll",
  "wait_not_open",
  "already_halted",
] as const;
export type RejectReason = (typeof REJECT_REASONS)[number];

export const HALT_REASONS = [
  "call_cap_exceeded",
  "token_cap_exceeded",
  "wall_cap_exceeded",
  "emission_cap_exceeded",
  "no_progress_same_gate_red3",
] as const;

export type HaltReport =
  | {
      readonly _tag: "cap_halt";
      readonly reason: CapBreach;
      readonly capValue: number;
      readonly usedValue: number;
    }
  | {
      readonly _tag: "no_progress_halt";
      readonly reason: "no_progress_same_gate_red3";
      readonly gateId: string;
      readonly gateReason: string;
      readonly reds: number;
    }
  | {
      readonly _tag: "emission_halt";
      readonly reason: "emission_cap_exceeded";
      readonly surface: string;
      readonly capBytes: number;
      readonly emittedBytes: number;
      readonly capItems: number;
      readonly emittedItems: number;
    };

export type RunDecision =
  | { readonly _tag: "admitted" }
  | { readonly _tag: "rejected"; readonly reason: RejectReason }
  | { readonly _tag: "halted"; readonly report: HaltReport };

export interface RunState {
  readonly declared: BudgetDeclaration | null;
  readonly budget: BudgetState;
  readonly emission: EmissionLedger;
  readonly streaks: readonly GateStreak[];
  readonly openWaits: readonly string[];
  readonly calls: number;
  readonly halt: HaltReport | null;
}

export const initialRunState: RunState = {
  declared: null,
  budget: emptyBudget,
  emission: emptyEmissionLedger,
  streaks: [],
  openWaits: [],
  calls: 0,
  halt: null,
};

export interface RunApplyResult {
  readonly next: RunState;
  readonly decision: RunDecision;
}

const rejected = (state: RunState, reason: RejectReason): RunApplyResult => ({
  next: state,
  decision: { _tag: "rejected", reason },
});

const capValueOf = (decl: BudgetDeclaration, breach: CapBreach): number =>
  breach === "call_cap_exceeded"
    ? decl.callCap
    : breach === "token_cap_exceeded"
      ? decl.tokenCap
      : decl.wallMsCap;

const usedValueOf = (usage: Usage, breach: CapBreach): number =>
  breach === "call_cap_exceeded"
    ? usage.calls
    : breach === "token_cap_exceeded"
      ? usage.tokens
      : usage.wallMs;

/** 승인된 계량 이벤트 반영 후 캡 검사 — 초과면 기재된 상태 위에 halt 를 새긴다. */
const metered = (
  state: RunState,
  declared: BudgetDeclaration,
  budget: BudgetState,
): RunApplyResult => {
  const calls = state.calls + 1;
  const usage = usageOf(calls, budget);
  const breach = checkCaps(declared, usage);
  if (breach === null) {
    return { next: { ...state, budget, calls }, decision: { _tag: "admitted" } };
  }
  const report: HaltReport = {
    _tag: "cap_halt",
    reason: breach,
    capValue: capValueOf(declared, breach),
    usedValue: usedValueOf(usage, breach),
  };
  return {
    next: { ...state, budget, calls, halt: report },
    decision: { _tag: "halted", report },
  };
};

export const applyRunEvent = (state: RunState, event: RunEvent): RunApplyResult => {
  if (state.halt !== null) {
    return rejected(state, "already_halted");
  }
  if (event._tag === "BudgetDeclared") {
    if (state.declared !== null) {
      return rejected(state, "budget_already_declared");
    }
    const invalid = validateBudgetDeclaration(event);
    if (invalid !== null) {
      return rejected(state, invalid.reason);
    }
    return { next: { ...state, declared: event }, decision: { _tag: "admitted" } };
  }
  const declared = state.declared;
  if (declared === null) {
    return rejected(state, "budget_not_declared");
  }
  if (event.runId !== declared.runId) {
    return rejected(state, "run_id_mismatch");
  }
  if (event._tag === "EmissionRecorded") {
    if (validateEmission(event) !== null) {
      return rejected(state, "negative_or_non_integer_emission");
    }
    const over =
      event.emittedBytes > declared.emissionByteCap ||
      event.emittedItems > declared.emissionItemCap;
    const emission = reduceEmission(state.emission, event, over);
    const calls = state.calls + 1;
    if (over) {
      // 이벤트 자신의 위반(단일 응답 캡)이 누적 캡보다 우선한다 — spec emission_check 핀.
      const report: HaltReport = {
        _tag: "emission_halt",
        reason: "emission_cap_exceeded",
        surface: event.surface,
        capBytes: declared.emissionByteCap,
        emittedBytes: event.emittedBytes,
        capItems: declared.emissionItemCap,
        emittedItems: event.emittedItems,
      };
      return {
        next: { ...state, emission, calls, halt: report },
        decision: { _tag: "halted", report },
      };
    }
    const usage = usageOf(calls, state.budget);
    const breach = checkCaps(declared, usage);
    if (breach === null) {
      return { next: { ...state, emission, calls }, decision: { _tag: "admitted" } };
    }
    const report: HaltReport = {
      _tag: "cap_halt",
      reason: breach,
      capValue: capValueOf(declared, breach),
      usedValue: usedValueOf(usage, breach),
    };
    return {
      next: { ...state, emission, calls, halt: report },
      decision: { _tag: "halted", report },
    };
  }
  if (event._tag === "WaitScheduled" || event._tag === "WaitCompleted") {
    const outcome = applyWait(state.openWaits, event);
    if (outcome._tag === "invalid_wait") {
      return rejected(state, outcome.reason);
    }
    return {
      next: { ...state, openWaits: outcome.openWaits },
      decision: { _tag: "admitted" },
    };
  }
  if (event._tag === "GateResultRecorded") {
    if (event.outcome === "red" && event.reason === "") {
      return rejected(state, "red_without_reason");
    }
    const streaks = reduceStreaks(state.streaks, event);
    const updated = streakOf(streaks, event.gateId);
    if (updated !== undefined && updated.consecutiveReds >= NO_PROGRESS_RED_LIMIT) {
      const report: HaltReport = {
        _tag: "no_progress_halt",
        reason: "no_progress_same_gate_red3",
        gateId: updated.gateId,
        gateReason: updated.reason,
        reds: updated.consecutiveReds,
      };
      return { next: { ...state, streaks, halt: report }, decision: { _tag: "halted", report } };
    }
    return { next: { ...state, streaks }, decision: { _tag: "admitted" } };
  }
  if (event._tag === "TokenSpendRecorded") {
    if (validateTokenSpend(event) !== null) {
      return rejected(state, "negative_or_non_integer_tokens");
    }
    return metered(state, declared, reduceBudget(state.budget, event));
  }
  if (validateComputeSpend(event) !== null) {
    return rejected(state, "negative_or_non_integer_compute");
  }
  return metered(state, declared, reduceBudget(state.budget, event));
};

export const replayRun = (events: readonly RunEvent[]): RunState =>
  events.reduce((state, event) => applyRunEvent(state, event).next, initialRunState);
