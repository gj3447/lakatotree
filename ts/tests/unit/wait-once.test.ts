/** Scenario WAIT-ONCE: B4 — '대기 ≠ 계산: CI·실기계·배포 대기는 1회 스케줄/완료 알림으로 처리한다.
 * 폴링 루프에 토큰을 태우지 않는다.' 열린 대상 재스케줄 = 폴링 신호 → 거부.
 * 대기 이벤트는 calls·원장 어느 평면에도 접촉하지 않는다. */
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { WaitCompleted, WaitScheduled } from "../../src/domain/wait.ts";
import { applyRunEvent, initialRunState, replayRun } from "../../src/domain/run.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "r1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_000_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};
const schedule = (target: string): WaitScheduled => ({
  _tag: "WaitScheduled", runId: "r1", target,
});
const complete = (target: string): WaitCompleted => ({
  _tag: "WaitCompleted", runId: "r1", target,
});

describe("B4 대기 ≠ 계산", () => {
  it("guard_mechanism: 스케줄 → 완료 → 재스케줄 은 합법 (재개방)", () => {
    const state = replayRun([decl, schedule("ci-run-42"), complete("ci-run-42"), schedule("ci-run-42")]);
    expect(state.halt).toBeNull();
    expect(state.openWaits).toEqual(["ci-run-42"]);
  });

  it("guard_defect: 열린 대상 재스케줄 = 폴링 → 거부 + 상태 무변경", () => {
    const opened = replayRun([decl, schedule("ci-run-42")]);
    const result = applyRunEvent(opened, schedule("ci-run-42"));
    expect(result.decision).toEqual({ _tag: "rejected", reason: "duplicate_wait_poll" });
    expect(result.next).toEqual(opened);
  });

  it("guard_defect: 미개방 완료는 거부", () => {
    const declared = replayRun([decl]);
    const result = applyRunEvent(declared, complete("never-opened"));
    expect(result.decision).toEqual({ _tag: "rejected", reason: "wait_not_open" });
    expect(result.next).toEqual(declared);
  });

  it("대기는 계량이 아니다 — calls·token·compute·emission 전 평면 무접촉", () => {
    const state = replayRun([decl, schedule("a"), schedule("b"), complete("a"), complete("b")]);
    expect(state.calls).toBe(0);
    expect(state.budget).toEqual(initialRunState.budget);
    expect(state.emission).toEqual(initialRunState.emission);
    expect(state.openWaits).toEqual([]);
  });

  it("guard_defect: 다른 runId 대기는 거부, 정지 후 대기도 거부", () => {
    const declared = replayRun([decl]);
    expect(applyRunEvent(declared, { ...schedule("x"), runId: "r2" }).decision).toEqual({
      _tag: "rejected", reason: "run_id_mismatch",
    });
    const halted = replayRun([{ ...decl, callCap: 0 }, {
      _tag: "TokenSpendRecorded", actor: "a", runId: "r1",
      inputTokens: 1, cacheReadTokens: 0, outputTokens: 0,
    }]);
    expect(halted.halt).not.toBeNull();
    expect(applyRunEvent(halted, schedule("x")).decision).toEqual({
      _tag: "rejected", reason: "already_halted",
    });
  });
});
