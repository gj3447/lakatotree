/** 순수 step — spec 실행 의미론: 전이 선택 → 다음 상태 → 효과 커맨드 방출.
 * 미허용 이벤트/가드 false = reject-and-audit (상태 무변경). 총함수 — throw 없음. */
import type {
  Configuration,
  EffectCommand,
  FsmEvent,
  GuardName,
  MachineDef,
  StepResult,
  TransitionDef,
} from "../contracts/fsm.ts";
import { GUARDS } from "./guards.ts";

export type GuardEval = (
  guard: GuardName,
  config: Configuration,
  event: FsmEvent,
) => boolean;

export const productionGuardEval: GuardEval = (guard, config, event) =>
  GUARDS[guard](config, event);

const audit = (
  config: Configuration,
  event: FsmEvent,
  reason: string,
): StepResult => ({
  next: config,
  commands: [
    {
      effect: "AuditInvalidTransition",
      payload: {
        state: config.state,
        event: event.type,
        actor: event.actor_role,
        reason,
        event_id: event.event_id,
      },
    },
  ],
  admitted: false,
  rejection_reason: reason,
});

const bindEffects = (
  transition: TransitionDef,
  config: Configuration,
  event: FsmEvent,
): readonly EffectCommand[] =>
  transition.effects.map((effect) => {
    const base: Record<string, string | number> = {
      event_id: event.event_id,
      ...event.payload,
    };
    if (effect === "SealVerdictReceipt") {
      base["verdict"] = config.context.last_verdict;
    }
    if (effect === "MovePointerCAS" && transition.id === "rejudge") {
      base["pointer"] = "current_receipt_sha";
      base["expected_old"] = event.payload["supersedes_receipt_sha"] ?? "";
      base["new_value"] = config.context.head_receipt_sha;
    }
    if (effect === "MovePointerCAS" && transition.from !== transition.to && transition.id !== "rejudge") {
      base["pointer"] = "standing";
      base["expected_old"] = transition.from;
      base["new_value"] = transition.to;
    }
    return { effect, payload: base };
  });

export const step = (
  machine: MachineDef,
  config: Configuration,
  event: FsmEvent,
  guardEval: GuardEval,
): StepResult => {
  if (!machine.events.includes(event.type)) {
    return audit(config, event, "event_not_declared");
  }
  if (machine.finals.includes(config.state)) {
    return audit(config, event, "terminal_state");
  }
  const transition = machine.transitions.find(
    (t) => t.from === config.state && t.event === event.type,
  );
  if (transition === undefined) {
    return audit(config, event, "no_transition_from_state");
  }
  if (transition.guard !== null && !guardEval(transition.guard, config, event)) {
    return audit(config, event, `guard_false:${transition.guard}`);
  }
  return {
    next: { state: transition.to, context: config.context },
    commands: bindEffects(transition, config, event),
    admitted: true,
    rejection_reason: "",
  };
};

export const initialConfiguration = (machine: MachineDef): Configuration => ({
  state: machine.initial,
  context: { head_receipt_sha: "", prediction_sealed: false, last_verdict: "" },
});
