/** Scenario RED3-HALT: B3 — '같은 게이트가 3회 연속 같은 이유로 RED면 정지하고 보고한다.
 * 밤새 같은 벽을 때리지 않는다.' red_without_reason fail-closed(이유 은폐로 3연속 비교 회피 봉쇄),
 * 게이트별 독립 스트릭(인터리빙이 남의 스트릭을 리셋하지 못한다 — 설계 패널 D2 결함의 음성 가드). */
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { GateResult } from "../../src/domain/streak.ts";
import { NO_PROGRESS_RED_LIMIT } from "../../src/domain/streak.ts";
import { applyRunEvent, replayRun, type RunEvent } from "../../src/domain/run.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "r1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_000_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};
const gate = (
  gateId: string,
  outcome: "green" | "red",
  reason: string,
): GateResult => ({ _tag: "GateResultRecorded", runId: "r1", gateId, outcome, reason });

const red = (id: string, reason: string): GateResult => gate(id, "red", reason);

describe("B3 무진전 정지", () => {
  it("조문 상수는 3 — 설정화 금지", () => {
    expect(NO_PROGRESS_RED_LIMIT).toBe(3);
  });

  it("guard_mechanism: 같은 게이트 같은 이유 red×3 → halted + 증거(gateId/이유/횟수)", () => {
    const primed = replayRun([decl, red("pnpm-verify", "type_error"), red("pnpm-verify", "type_error")]);
    expect(primed.halt).toBeNull();
    const result = applyRunEvent(primed, red("pnpm-verify", "type_error"));
    expect(result.decision).toEqual({
      _tag: "halted",
      report: {
        _tag: "no_progress_halt",
        reason: "no_progress_same_gate_red3",
        gateId: "pnpm-verify",
        gateReason: "type_error",
        reds: 3,
      },
    });
  });

  it("guard_defect: green 개입은 스트릭 소거 — 진전이 있으면 벽이 아니다", () => {
    const state = replayRun([
      decl,
      red("g", "x"), red("g", "x"), gate("g", "green", ""),
      red("g", "x"), red("g", "x"),
    ]);
    expect(state.halt).toBeNull();
  });

  it("guard_defect: 이유가 바뀌면 1로 재시작 — '같은 이유' 3연속만 정지", () => {
    const state = replayRun([decl, red("g", "x"), red("g", "x"), red("g", "y"), red("g", "y")]);
    expect(state.halt).toBeNull();
    expect(applyRunEvent(state, red("g", "y")).decision).toMatchObject({
      _tag: "halted",
      report: { gateId: "g", gateReason: "y", reds: 3 },
    });
  });

  it("guard_defect: 게이트 인터리빙은 서로의 스트릭을 건드리지 못한다 (A,B,A,B,A → A 가 3에서 정지)", () => {
    const events: readonly RunEvent[] = [
      decl,
      red("A", "x"), red("B", "z"), red("A", "x"), red("B", "z"), red("A", "x"),
    ];
    const state = replayRun(events);
    expect(state.halt).toMatchObject({
      _tag: "no_progress_halt", gateId: "A", gateReason: "x", reds: 3,
    });
  });

  it("guard_defect: red 인데 이유가 비면 fail-closed 거부 — 이유 은폐로 B3 를 회피할 수 없다", () => {
    const declared = replayRun([decl]);
    const result = applyRunEvent(declared, red("g", ""));
    expect(result.decision).toEqual({ _tag: "rejected", reason: "red_without_reason" });
    expect(result.next).toEqual(declared);
  });

  it("게이트 결과는 계량 이벤트가 아니다 — calls·원장 무접촉", () => {
    const state = replayRun([decl, red("g", "x"), gate("g", "green", ""), red("h", "y")]);
    expect(state.calls).toBe(0);
    expect(state.budget.token.entries).toBe(0);
    expect(state.budget.compute.entries).toBe(0);
  });

  it("guard_defect: 스트릭 정지도 흡수 상태 — 이후 전부 거부", () => {
    const halted = replayRun([decl, red("g", "x"), red("g", "x"), red("g", "x")]);
    expect(halted.halt).not.toBeNull();
    const result = applyRunEvent(halted, gate("g", "green", ""));
    expect(result.decision).toEqual({ _tag: "rejected", reason: "already_halted" });
    expect(result.next).toEqual(halted);
  });
});
