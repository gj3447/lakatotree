/** 이중 원장 성질 — 평면 격리·가산성·순서 불변. */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  emptyBudget,
  reduceBudget,
  type ComputeSpend,
  type TokenSpend,
} from "../../src/domain/ledger.ts";

const nat = fc.nat({ max: 1_000_000 });

const arbToken: fc.Arbitrary<TokenSpend> = fc.record({
  _tag: fc.constant("TokenSpendRecorded" as const),
  actor: fc.constantFrom("claude", "codex", "grok"),
  runId: fc.string({ minLength: 2, maxLength: 6 }),
  inputTokens: nat,
  cacheReadTokens: nat,
  outputTokens: nat,
});

const arbCompute: fc.Arbitrary<ComputeSpend> = fc.record({
  _tag: fc.constant("ComputeSpendRecorded" as const),
  actor: fc.constantFrom("delltower", "dev-01", "macmini"),
  runId: fc.string({ minLength: 2, maxLength: 6 }),
  cpuMs: nat,
  gpuMs: nat,
  wallMs: nat,
});

const arbSpend = fc.oneof(arbToken, arbCompute);

describe("dual-plane isolation laws", () => {
  it("token plane totals depend ONLY on token events (cross-plane isolation)", () => {
    fc.assert(
      fc.property(fc.array(arbSpend, { maxLength: 40 }), (spends) => {
        const finalState = spends.reduce(reduceBudget, emptyBudget);
        const tokenOnly = spends.filter(
          (s): s is TokenSpend => s._tag === "TokenSpendRecorded",
        );
        const computeOnly = spends.filter(
          (s): s is ComputeSpend => s._tag === "ComputeSpendRecorded",
        );
        expect(finalState.token.entries).toBe(tokenOnly.length);
        expect(finalState.compute.entries).toBe(computeOnly.length);
        expect(finalState.token.inputTokens).toBe(
          tokenOnly.reduce((sum, s) => sum + s.inputTokens, 0),
        );
        expect(finalState.compute.cpuMs).toBe(
          computeOnly.reduce((sum, s) => sum + s.cpuMs, 0),
        );
      }),
      { numRuns: 300 },
    );
  });

  it("totals are permutation-invariant (가산 원장)", () => {
    fc.assert(
      fc.property(fc.array(arbSpend, { maxLength: 20 }), (spends) => {
        const forward = spends.reduce(reduceBudget, emptyBudget);
        const backward = [...spends].reverse().reduce(reduceBudget, emptyBudget);
        expect(forward.token).toEqual(backward.token);
        expect(forward.compute).toEqual(backward.compute);
      }),
      { numRuns: 200 },
    );
  });

  it("reducers never mutate prior state (구조 공유·불변)", () => {
    fc.assert(
      fc.property(arbSpend, (spend) => {
        const before = emptyBudget;
        reduceBudget(before, spend);
        expect(before.token.entries).toBe(0);
        expect(before.compute.entries).toBe(0);
      }),
      { numRuns: 50 },
    );
  });
});
