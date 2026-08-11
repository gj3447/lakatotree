/** Scenario LEDGER-SPLIT: AI 토큰 원장과 컴퓨팅 원장은 별개 평면 — 교차 오염 불가. */
import { describe, expect, it } from "vitest";
import {
  emptyBudget,
  reduceBudget,
  validateComputeSpend,
  validateTokenSpend,
  type ComputeSpend,
  type TokenSpend,
} from "../../src/domain/ledger.ts";

const token: TokenSpend = {
  _tag: "TokenSpendRecorded", actor: "claude", runId: "r1",
  inputTokens: 1000, cacheReadTokens: 50_000, outputTokens: 200,
};
const compute: ComputeSpend = {
  _tag: "ComputeSpendRecorded", actor: "delltower", runId: "r1",
  cpuMs: 3_600_000, gpuMs: 0, wallMs: 7_200_000,
};

describe("dual-plane budget", () => {
  it("token spend updates ONLY the token ledger", () => {
    const next = reduceBudget(emptyBudget, token);
    expect(next.token).toMatchObject({ inputTokens: 1000, cacheReadTokens: 50_000, entries: 1 });
    expect(next.compute).toEqual(emptyBudget.compute);
  });

  it("compute spend updates ONLY the compute ledger", () => {
    const next = reduceBudget(emptyBudget, compute);
    expect(next.compute).toMatchObject({ cpuMs: 3_600_000, wallMs: 7_200_000, entries: 1 });
    expect(next.token).toEqual(emptyBudget.token);
  });

  it("interleaved spends keep both planes independently additive", () => {
    const s1 = reduceBudget(reduceBudget(reduceBudget(emptyBudget, token), compute), token);
    expect(s1.token.entries).toBe(2);
    expect(s1.compute.entries).toBe(1);
    expect(s1.token.inputTokens).toBe(2000);
    expect(s1.compute.cpuMs).toBe(3_600_000);
  });

  it("negative or fractional amounts are typed errors", () => {
    expect(validateTokenSpend({ ...token, inputTokens: -1 })).toMatchObject({ _tag: "invalid_spend" });
    expect(validateComputeSpend({ ...compute, cpuMs: 0.5 })).toMatchObject({ _tag: "invalid_spend" });
    expect(validateTokenSpend(token)).toBeNull();
    expect(validateComputeSpend(compute)).toBeNull();
  });
});
