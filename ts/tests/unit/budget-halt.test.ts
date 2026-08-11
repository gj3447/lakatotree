/** Scenario CAP-HALT: B1 — '초과 = 정지 + 보고 (재시도 아님).'
 * 초과는 기재 후 정지(소비는 사실 — 계량이 숨기지 않는다), 정지는 흡수 상태(un-halt 이벤트 없음),
 * 도달=합법(used > cap 만 초과). 정지는 리듀서 파생 전용 — 날조 정지 이벤트가 타입상 표현 불가. */
import { describe, expect, it } from "vitest";
import type { ComputeSpend, TokenSpend } from "../../src/domain/ledger.ts";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import { applyRunEvent, replayRun } from "../../src/domain/run.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "r1",
  callCap: 10, tokenCap: 1000, wallMsCap: 5000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};
const spend = (tokens: number): TokenSpend => ({
  _tag: "TokenSpendRecorded", actor: "claude", runId: "r1",
  inputTokens: tokens, cacheReadTokens: 0, outputTokens: 0,
});
const wall = (wallMs: number): ComputeSpend => ({
  _tag: "ComputeSpendRecorded", actor: "delltower", runId: "r1",
  cpuMs: 0, gpuMs: 0, wallMs,
});

describe("B1 초과 = 정지 + 보고", () => {
  it("guard_mechanism: 토큰 캡 초과 → 기재 후 halted + 증거(capValue/usedValue)", () => {
    const result = applyRunEvent(replayRun([decl, spend(900)]), spend(200));
    expect(result.decision).toEqual({
      _tag: "halted",
      report: { _tag: "cap_halt", reason: "token_cap_exceeded", capValue: 1000, usedValue: 1100 },
    });
    expect(result.next.budget.token.inputTokens).toBe(1100);
    expect(result.next.halt).not.toBeNull();
  });

  it("guard_mechanism: 호출 캡·wall 캡도 같은 기계 — 각자의 닫힌 사유", () => {
    const tight = { ...decl, callCap: 1 };
    const callHalt = applyRunEvent(replayRun([tight, spend(1)]), spend(1));
    expect(callHalt.decision).toMatchObject({
      _tag: "halted",
      report: { reason: "call_cap_exceeded", capValue: 1, usedValue: 2 },
    });
    const wallHalt = applyRunEvent(replayRun([decl]), wall(5001));
    expect(wallHalt.decision).toMatchObject({
      _tag: "halted",
      report: { reason: "wall_cap_exceeded", capValue: 5000, usedValue: 5001 },
    });
  });

  it("도달 = 합법: used == cap 은 초과가 아니다", () => {
    const result = applyRunEvent(replayRun([decl]), spend(1000));
    expect(result.decision).toEqual({ _tag: "admitted" });
    expect(result.next.halt).toBeNull();
  });

  it("guard_defect: 정지 후 모든 이벤트 거부 + 상태 동결 — '재시도 아님'의 기계화", () => {
    const haltedState = replayRun([decl, spend(1100)]);
    expect(haltedState.halt).not.toBeNull();
    for (const event of [spend(1), wall(1), decl]) {
      const result = applyRunEvent(haltedState, event);
      expect(result.decision).toEqual({ _tag: "rejected", reason: "already_halted" });
      expect(result.next).toEqual(haltedState);
    }
  });

  it("guard_defect: 초과 기재는 정확히 1건 — 흡수 이후 원장 불변", () => {
    const state = replayRun([decl, spend(900), spend(300), spend(300), spend(300)]);
    expect(state.budget.token.entries).toBe(2);
    expect(state.budget.token.inputTokens).toBe(1200);
  });
});
