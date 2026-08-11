/** Scenario FSM-CONFORM: TS step 리듀서가 기계 정본 스펙과 21개 추상 트레이스에 정확히 합치. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  ActorRole,
  Configuration,
  EventType,
  FsmEvent,
  GuardName,
} from "../../src/contracts/fsm.ts";
import { MACHINES, machineById } from "../../src/domain/machines.ts";
import { initialConfiguration, step } from "../../src/domain/step.ts";

const here = dirname(fileURLToPath(import.meta.url));
const specDir = join(here, "..", "..", "spec");

interface SpecTransition {
  id: string;
  from: string;
  event: string;
  to: string;
  guard?: string;
  effects: string[];
}
interface SpecMachine {
  id: string;
  initial: string;
  states: { id: string; kind: string }[];
  events: string[];
  transitions: SpecTransition[];
}
interface TraceStep {
  event: string;
  guard_results: Record<string, boolean>;
  expected_state: string;
  expected_effects: string[];
}
interface TraceCase {
  id: string;
  machine: string;
  steps: TraceStep[];
}

const spec = JSON.parse(
  readFileSync(join(specDir, "lakatos-node-fsm.v0.json"), "utf8"),
) as { machines: SpecMachine[] };
const traces = JSON.parse(
  readFileSync(join(specDir, "lakatos-node-fsm-traces.v0.json"), "utf8"),
) as { cases: TraceCase[] };

describe("spec-pin: TS 머신 테이블 == 기계 정본", () => {
  it("machine count and ids match", () => {
    expect(MACHINES.map((m) => m.id).sort()).toEqual(
      spec.machines.map((m) => m.id).sort(),
    );
  });

  for (const specMachine of spec.machines) {
    it(`machine ${specMachine.id} states/initial/events/transitions match`, () => {
      const ts = machineById(specMachine.id);
      expect(ts).toBeDefined();
      if (ts === undefined) return;
      expect(ts.initial).toBe(specMachine.initial);
      expect([...ts.states].sort()).toEqual(
        specMachine.states.map((s) => s.id).sort(),
      );
      expect([...ts.finals].sort()).toEqual(
        specMachine.states.filter((s) => s.kind === "final").map((s) => s.id).sort(),
      );
      expect([...ts.events].sort()).toEqual([...specMachine.events].sort());
      expect(
        ts.transitions.map((t) => ({
          id: t.id, from: t.from, event: t.event, to: t.to,
          guard: t.guard ?? undefined, effects: [...t.effects],
        })),
      ).toEqual(
        specMachine.transitions.map((t) => ({
          id: t.id, from: t.from, event: t.event, to: t.to,
          guard: t.guard, effects: t.effects,
        })),
      );
    });
  }
});

describe("abstract trace conformance (21 cases)", () => {
  it("fixture has 21 cases", () => {
    expect(traces.cases.length).toBe(21);
  });

  for (const traceCase of traces.cases) {
    it(traceCase.id, () => {
      const machine = machineById(traceCase.machine);
      expect(machine).toBeDefined();
      if (machine === undefined) return;
      let config: Configuration = initialConfiguration(machine);
      // 리듀서 계약: SealVerdictReceipt 방출 전에 판정이 채워져 있어야 한다 —
      // 추상 트레이스에서는 고정 센티널로 주입한다.
      config = {
        state: config.state,
        context: { ...config.context, last_verdict: "partial", head_receipt_sha: "sha-head" },
      };
      for (const traceStep of traceCase.steps) {
        const event: FsmEvent = {
          type: traceStep.event as EventType,
          event_id: `${traceCase.id}-${traceStep.event}`,
          actor_role: "author" as ActorRole,
          payload: { supersedes_receipt_sha: "sha-head" },
        };
        const result = step(machine, config, event, (guard: GuardName) => {
          const injected = traceStep.guard_results[guard];
          return injected ?? false;
        });
        expect(result.next.state).toBe(traceStep.expected_state);
        expect(result.commands.map((c) => c.effect)).toEqual(
          traceStep.expected_effects,
        );
        config = result.next;
      }
    });
  }
});
