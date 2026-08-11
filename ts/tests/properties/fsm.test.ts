/** FSM 총함수 성질 — 임의 이벤트열·임의 가드 결과에서 리듀서 법칙 유지. */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ActorRole, Configuration, EventType, FsmEvent } from "../../src/contracts/fsm.ts";
import { MACHINES } from "../../src/domain/machines.ts";
import { initialConfiguration, step } from "../../src/domain/step.ts";

const ALL_EVENTS: readonly EventType[] = [
  "PREDICTION_REGISTERED", "RESULT_SUBMITTED", "REJUDGE_SUBMITTED",
  "ENGINE_RULE_STALE", "ENGINE_RULE_REFRESHED", "STANDING_RETRACTED",
  "STANDING_REINSTATED", "QUESTION_CLOSED", "QUESTION_REOPENED",
  "BUNDLE_SHA_VERIFIED", "BUNDLE_REJECTED", "TREE_ARCHIVED",
];

const arbEvent = fc.record({
  type: fc.constantFrom(...ALL_EVENTS),
  event_id: fc.string({ minLength: 4, maxLength: 8 }),
  actor_role: fc.constantFrom<ActorRole>(
    "author", "anchor_verifier", "engine_auditor", "judgment_seam", "human_owner",
  ),
  payload: fc.constant({}),
}) satisfies fc.Arbitrary<FsmEvent>;

describe("step total-function laws", () => {
  it("state stays in the machine's state set; rejected steps change nothing and audit exactly once", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...MACHINES),
        fc.array(fc.tuple(arbEvent, fc.boolean()), { maxLength: 30 }),
        (machine, script) => {
          let config: Configuration = initialConfiguration(machine);
          for (const [event, guardOutcome] of script) {
            const result = step(machine, config, event, () => guardOutcome);
            expect(machine.states).toContain(result.next.state);
            if (!result.admitted) {
              expect(result.next.state).toBe(config.state);
              expect(result.commands.map((c) => c.effect)).toEqual(["AuditInvalidTransition"]);
            } else {
              expect(result.commands.length).toBeGreaterThan(0);
              expect(result.commands.every((c) => c.effect !== "AuditInvalidTransition")).toBe(true);
            }
            config = result.next;
          }
        },
      ),
      { numRuns: 200 },
    );
  });

  it("replay determinism: same script twice yields identical final state", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...MACHINES),
        fc.array(fc.tuple(arbEvent, fc.boolean()), { maxLength: 20 }),
        (machine, script) => {
          const run = () => {
            let config: Configuration = initialConfiguration(machine);
            for (const [event, guardOutcome] of script) {
              config = step(machine, config, event, () => guardOutcome).next;
            }
            return config;
          };
          expect(run()).toEqual(run());
        },
      ),
      { numRuns: 100 },
    );
  });

  it("final states accept no event (terminal isolation)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...MACHINES), arbEvent, (machine, event) => {
        for (const finalState of machine.finals) {
          const config: Configuration = {
            state: finalState,
            context: { head_receipt_sha: "", prediction_sealed: false, last_verdict: "" },
          };
          const result = step(machine, config, event, () => true);
          expect(result.admitted).toBe(false);
          expect(result.next.state).toBe(finalState);
        }
      }),
      { numRuns: 100 },
    );
  });
});
