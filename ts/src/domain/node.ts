/** 노드 애그리게이트 — F 커널 합성: 이벤트 소싱 apply = judge(순수) ∘ step(순수).
 * 판정은 저자 페이로드가 아니라 여기서 도출된다 (측정주권). 리플레이 결정론:
 * 같은 이벤트열 → 같은 상태·같은 커맨드열. */
import type { Configuration, EffectCommand, FsmEvent } from "../contracts/fsm.ts";
import { machineById } from "./machines.ts";
import { productionGuardEval, step } from "./step.ts";
import { judge, type Direction, type PredictionSpec } from "./judge.ts";

export interface NodeState {
  readonly config: Configuration;
  readonly spec: PredictionSpec | null;
  readonly receiptCount: number;
}

export const initialNodeState: NodeState = {
  config: {
    state: "draft",
    context: { head_receipt_sha: "", prediction_sealed: false, last_verdict: "" },
  },
  spec: null,
  receiptCount: 0,
};

export interface ApplyResult {
  readonly next: NodeState;
  readonly commands: readonly EffectCommand[];
  readonly admitted: boolean;
}

const num = (event: FsmEvent, key: string): number => {
  const value = event.payload[key];
  return typeof value === "number" ? value : Number.NaN;
};

const strField = (event: FsmEvent, key: string): string => {
  const value = event.payload[key];
  return typeof value === "string" ? value : "";
};

const specFromEvent = (event: FsmEvent): PredictionSpec | null => {
  const direction = strField(event, "direction");
  if (direction !== "higher" && direction !== "lower") return null;
  return {
    baselineMicro: num(event, "baseline"),
    direction: direction as Direction,
    noiseBandMicro: num(event, "noise_band"),
  };
};

/** 제출 이벤트에 대해 판정을 선계산해 컨텍스트에 주입 — step 은 스펙 그대로 유지된다. */
const withComputedVerdict = (state: NodeState, event: FsmEvent): Configuration => {
  if (
    (event.type !== "RESULT_SUBMITTED" && event.type !== "REJUDGE_SUBMITTED") ||
    state.spec === null
  ) {
    return state.config;
  }
  const judged = judge(state.spec, num(event, "value"), false);
  const verdict = "_tag" in judged ? `rejected:${judged.reason}` : judged.finalVerdict;
  return {
    state: state.config.state,
    context: { ...state.config.context, last_verdict: verdict },
  };
};

/** 수리 후 head 갱신 — 콘텐츠 주소 해시 어댑터 도입 전까지 event_id 유도 자리표시 식별자.
 * (실제 receipt_sha 봉인은 canonical-bytes+sha256 슬라이스의 몫 — 여기선 CAS 사슬 형태만.) */
const nextHead = (event: FsmEvent): string => `receipt:${event.event_id}`;

export const applyNodeEvent = (state: NodeState, event: FsmEvent): ApplyResult => {
  const machine = machineById("node-judgment");
  if (machine === undefined) {
    return { next: state, commands: [], admitted: false };
  }
  const config = withComputedVerdict(state, event);
  const result = step(machine, config, event, productionGuardEval);
  if (!result.admitted) {
    return { next: { ...state, config: { ...state.config } }, commands: result.commands, admitted: false };
  }
  const sealsVerdict = result.commands.some((c) => c.effect === "SealVerdictReceipt");
  const sealsPrediction = result.commands.some((c) => c.effect === "SealPredictionReceipt");
  const next: NodeState = {
    config: {
      state: result.next.state,
      context: {
        head_receipt_sha: sealsVerdict ? nextHead(event) : result.next.context.head_receipt_sha,
        prediction_sealed: sealsPrediction ? true : result.next.context.prediction_sealed,
        last_verdict: result.next.context.last_verdict,
      },
    },
    spec: sealsPrediction ? specFromEvent(event) : state.spec,
    receiptCount: state.receiptCount + (sealsVerdict || sealsPrediction ? 1 : 0),
  };
  return { next, commands: result.commands, admitted: true };
};

export const replay = (events: readonly FsmEvent[]): NodeState =>
  events.reduce((state, event) => applyNodeEvent(state, event).next, initialNodeState);
