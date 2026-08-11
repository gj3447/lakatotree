/** Scenario BUDGET-DECLARE: B1 — '예산 없는 자율 실행은 시작하지 않는다.'
 * 선언은 write-once(중도 증액 세탁 차단), 스트림은 1 run 전용(run_id_mismatch). */
import { describe, expect, it } from "vitest";
import type { ComputeSpend, TokenSpend } from "../../src/domain/ledger.ts";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import { applyRunEvent, initialRunState, replayRun } from "../../src/domain/run.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "r1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_000_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};
const token: TokenSpend = {
  _tag: "TokenSpendRecorded", actor: "claude", runId: "r1",
  inputTokens: 1000, cacheReadTokens: 50_000, outputTokens: 200,
};
const compute: ComputeSpend = {
  _tag: "ComputeSpendRecorded", actor: "delltower", runId: "r1",
  cpuMs: 60_000, gpuMs: 0, wallMs: 120_000,
};

describe("B1 예산 선언", () => {
  it("guard_defect: 선언 전 계량 이벤트는 전부 거부 + 상태 무변경", () => {
    const result = applyRunEvent(initialRunState, token);
    expect(result.decision).toEqual({ _tag: "rejected", reason: "budget_not_declared" });
    expect(result.next).toEqual(initialRunState);
  });

  it("guard_defect: 빈 runId 선언은 fail-closed 거부", () => {
    const result = applyRunEvent(initialRunState, { ...decl, runId: "" });
    expect(result.decision).toEqual({ _tag: "rejected", reason: "empty_run_id" });
  });

  it("guard_defect: 음수·비정수 cap 선언은 거부", () => {
    for (const bad of [{ callCap: -1 }, { tokenCap: 0.5 }, { emissionByteCap: Number.NaN }]) {
      const result = applyRunEvent(initialRunState, { ...decl, ...bad });
      expect(result.decision).toEqual({
        _tag: "rejected",
        reason: "negative_or_non_integer_cap",
      });
    }
  });

  it("guard_defect: 재선언은 거부 — 예산은 write-once", () => {
    const declared = applyRunEvent(initialRunState, decl).next;
    const result = applyRunEvent(declared, { ...decl, tokenCap: 9_999_999 });
    expect(result.decision).toEqual({ _tag: "rejected", reason: "budget_already_declared" });
    expect(result.next).toEqual(declared);
  });

  it("guard_defect: 다른 runId 의 이벤트는 거부 — 1 스트림 = 1 run", () => {
    const declared = applyRunEvent(initialRunState, decl).next;
    const result = applyRunEvent(declared, { ...token, runId: "r2" });
    expect(result.decision).toEqual({ _tag: "rejected", reason: "run_id_mismatch" });
    expect(result.next).toEqual(declared);
  });

  it("guard_defect: ledger 검증 실패는 reason 관통 (신조어 없음)", () => {
    const declared = applyRunEvent(initialRunState, decl).next;
    expect(applyRunEvent(declared, { ...token, inputTokens: -1 }).decision).toEqual({
      _tag: "rejected", reason: "negative_or_non_integer_tokens",
    });
    expect(applyRunEvent(declared, { ...compute, cpuMs: 0.5 }).decision).toEqual({
      _tag: "rejected", reason: "negative_or_non_integer_compute",
    });
  });

  it("guard_mechanism: 선언 후 계량 정확 — 이중 평면 그대로 + calls 집계", () => {
    const state = replayRun([decl, token, compute, token]);
    expect(state.declared).toEqual(decl);
    expect(state.calls).toBe(3);
    expect(state.budget.token).toMatchObject({
      inputTokens: 2000, cacheReadTokens: 100_000, outputTokens: 400, entries: 2,
    });
    expect(state.budget.compute).toMatchObject({ cpuMs: 60_000, wallMs: 120_000, entries: 1 });
    expect(state.halt).toBeNull();
  });
});
