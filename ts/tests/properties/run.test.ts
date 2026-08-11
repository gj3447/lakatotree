/** RUN-LAWS — 실행 애그리게이트 종합 법칙: 리플레이 결정론 · 거부 무변이 · 흡수성(재시도 아님) ·
 * 평면 격리(run 경유 spend ≡ 단독 reduceBudget fold — 재구현 아님 실증) · 예방-탐지 정합
 * (bound.ts 산출로 구성한 방출은 절대 overBound 아님). */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ComputeSpend, TokenSpend } from "../../src/domain/ledger.ts";
import { emptyBudget, reduceBudget } from "../../src/domain/ledger.ts";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { EmissionRecorded } from "../../src/domain/emission.ts";
import { boundList } from "../../src/domain/bound.ts";
import {
  applyRunEvent,
  initialRunState,
  replayRun,
  type RunEvent,
  type RunState,
} from "../../src/domain/run.ts";

const nat = (max: number): fc.Arbitrary<number> => fc.nat({ max });

const arbDecl: fc.Arbitrary<BudgetDeclaration> = fc.record({
  _tag: fc.constant("BudgetDeclared" as const),
  runId: fc.constant("r1"),
  callCap: nat(12),
  tokenCap: nat(5000),
  wallMsCap: nat(5000),
  emissionByteCap: nat(2000),
  emissionItemCap: nat(50),
});

const arbToken: fc.Arbitrary<TokenSpend> = fc.record({
  _tag: fc.constant("TokenSpendRecorded" as const),
  actor: fc.constantFrom("claude", "codex"),
  runId: fc.constantFrom("r1", "r2"),
  inputTokens: nat(800), cacheReadTokens: nat(800), outputTokens: nat(800),
});

const arbCompute: fc.Arbitrary<ComputeSpend> = fc.record({
  _tag: fc.constant("ComputeSpendRecorded" as const),
  actor: fc.constant("delltower"),
  runId: fc.constantFrom("r1", "r2"),
  cpuMs: nat(800), gpuMs: nat(800), wallMs: nat(800),
});

const arbGate: fc.Arbitrary<RunEvent> = fc.record({
  _tag: fc.constant("GateResultRecorded" as const),
  runId: fc.constantFrom("r1", "r2"),
  gateId: fc.constantFrom("verify", "audit"),
  outcome: fc.constantFrom("green" as const, "red" as const),
  reason: fc.constantFrom("", "type_error", "lint"),
});

const arbEmission: fc.Arbitrary<EmissionRecorded> = fc.record({
  _tag: fc.constant("EmissionRecorded" as const),
  runId: fc.constantFrom("r1", "r2"),
  surface: fc.constantFrom("get_tree", "graph"),
  emittedBytes: nat(3000), emittedItems: nat(80),
  truncatedBytes: nat(500), truncatedItems: nat(20),
});

const arbWait: fc.Arbitrary<RunEvent> = fc.record({
  _tag: fc.constantFrom("WaitScheduled" as const, "WaitCompleted" as const),
  runId: fc.constantFrom("r1", "r2"),
  target: fc.constantFrom("ci", "deploy"),
});

const arbEvent: fc.Arbitrary<RunEvent> = fc.oneof(
  arbToken, arbCompute, arbGate, arbEmission, arbWait,
);

const arbRun = fc
  .tuple(arbDecl, fc.array(arbEvent, { maxLength: 40 }))
  .map(([decl, events]) => [decl, ...events] as readonly RunEvent[]);

/** 각 이벤트의 (직전 상태, 결정, 직후 상태) 궤적 — 법칙 검증용 fold. */
const trace = (events: readonly RunEvent[]) => {
  const steps: {
    prev: RunState;
    event: RunEvent;
    decision: ReturnType<typeof applyRunEvent>["decision"];
    next: RunState;
  }[] = [];
  let state = initialRunState;
  for (const event of events) {
    const result = applyRunEvent(state, event);
    steps.push({ prev: state, event, decision: result.decision, next: result.next });
    state = result.next;
  }
  return steps;
};

describe("run aggregate laws", () => {
  it("리플레이 결정론 — 같은 이벤트열 2회는 동일 상태", () => {
    fc.assert(
      fc.property(arbRun, (events) => {
        expect(replayRun(events)).toEqual(replayRun(events));
      }),
      { numRuns: 200 },
    );
  });

  it("거부 무변이 — 모든 rejected 결정에서 상태 deep-equal 동결", () => {
    fc.assert(
      fc.property(arbRun, (events) => {
        for (const step of trace(events)) {
          if (step.decision._tag === "rejected") {
            expect(step.next).toEqual(step.prev);
          }
        }
      }),
      { numRuns: 200 },
    );
  });

  it("흡수성 — 최초 halt 이후 적용(승인·정지)된 이벤트 0건, 전부 already_halted", () => {
    fc.assert(
      fc.property(arbRun, (events) => {
        let halted = false;
        for (const step of trace(events)) {
          if (halted) {
            expect(step.decision).toEqual({ _tag: "rejected", reason: "already_halted" });
            expect(step.next).toEqual(step.prev);
          }
          if (step.decision._tag === "halted") halted = true;
        }
      }),
      { numRuns: 300 },
    );
  });

  it("평면 격리 — run 경유 원장 == 적용된 spend 만 단독 reduceBudget fold (재도출 검증)", () => {
    fc.assert(
      fc.property(arbRun, (events) => {
        const steps = trace(events);
        const appliedSpends = steps
          .filter((s) => s.decision._tag !== "rejected")
          .map((s) => s.event)
          .filter(
            (e): e is TokenSpend | ComputeSpend =>
              e._tag === "TokenSpendRecorded" || e._tag === "ComputeSpendRecorded",
          );
        const finalState = steps.length > 0 ? steps[steps.length - 1].next : initialRunState;
        expect(finalState.budget).toEqual(appliedSpends.reduce(reduceBudget, emptyBudget));
      }),
      { numRuns: 300 },
    );
  });

  it("비계량 이벤트는 원장 무접촉, spend 는 emission·streaks·openWaits 무접촉", () => {
    fc.assert(
      fc.property(arbRun, (events) => {
        for (const step of trace(events)) {
          const tag = step.event._tag;
          if (tag === "GateResultRecorded" || tag === "WaitScheduled" || tag === "WaitCompleted") {
            expect(step.next.budget).toEqual(step.prev.budget);
            expect(step.next.emission).toEqual(step.prev.emission);
            expect(step.next.calls).toBe(step.prev.calls);
          }
          if (tag === "TokenSpendRecorded" || tag === "ComputeSpendRecorded") {
            expect(step.next.emission).toEqual(step.prev.emission);
            expect(step.next.streaks).toEqual(step.prev.streaks);
            expect(step.next.openWaits).toEqual(step.prev.openWaits);
          }
        }
      }),
      { numRuns: 200 },
    );
  });

  it("예방-탐지 정합 — boundList 산출로 구성한 방출은 캡 동일 선언에서 절대 overBound 아님", () => {
    fc.assert(
      fc.property(
        fc.array(fc.integer(), { maxLength: 120 }),
        fc.integer({ min: 1, max: 60 }),
        (items, cap) => {
          const bounded = boundList(items, cap);
          expect(bounded._tag).toBe("BoundedList");
          if (bounded._tag !== "BoundedList") return;
          const decl: BudgetDeclaration = {
            _tag: "BudgetDeclared", runId: "r1",
            callCap: 10, tokenCap: 0, wallMsCap: 0,
            emissionByteCap: 1_000_000, emissionItemCap: cap,
          };
          const emission: EmissionRecorded = {
            _tag: "EmissionRecorded", runId: "r1", surface: "get_tree",
            emittedBytes: 0, emittedItems: bounded.items.length,
            truncatedBytes: 0, truncatedItems: bounded.truncated,
          };
          const state = replayRun([decl, emission]);
          expect(state.halt).toBeNull();
          expect(state.emission.overCapEntries).toBe(0);
          // 보존 공시: 방출 + 잘림 = 원본
          expect(state.emission.emittedItems + state.emission.truncatedItems).toBe(items.length);
        },
      ),
      { numRuns: 300 },
    );
  });
});
