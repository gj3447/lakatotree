/** Scenario EMISSION-BOUND: 유계의 탐지선 — 방출은 보존 공시와 함께 기재되고, 선언된 단일 응답
 * 캡 초과는 기재 후 정지로 격상된다. bound.ts(예방선)를 우회한 방출도 여기서 기록되고 죽는다.
 * 실측 근거: get_tree 단일 응답 733,838B — '작은 응답 다발' 우회는 callCap 이 잡는다. */
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import type { EmissionRecorded } from "../../src/domain/emission.ts";
import { applyRunEvent, replayRun } from "../../src/domain/run.ts";

const decl: BudgetDeclaration = {
  _tag: "BudgetDeclared", runId: "r1",
  callCap: 100, tokenCap: 1_000_000, wallMsCap: 3_000_000,
  emissionByteCap: 60_000, emissionItemCap: 500,
};
const emit = (over: Partial<EmissionRecorded> = {}): EmissionRecorded => ({
  _tag: "EmissionRecorded", runId: "r1", surface: "get_tree",
  emittedBytes: 35_000, emittedItems: 100, truncatedBytes: 0, truncatedItems: 0,
  ...over,
});

describe("emission 탐지 평면", () => {
  it("guard_mechanism: 캡 이내 방출은 승인 — 합산·보존 공시·calls 계량", () => {
    const state = replayRun([decl, emit(), emit({ truncatedBytes: 5000, truncatedItems: 65 })]);
    expect(state.halt).toBeNull();
    expect(state.emission).toEqual({
      emittedBytes: 70_000, emittedItems: 200,
      truncatedBytes: 5000, truncatedItems: 65,
      entries: 2, overCapEntries: 0,
    });
    expect(state.calls).toBe(2);
  });

  it("guard_defect: 바이트 캡 초과 → 기재(overCapEntries) 후 halted + 전체 증거", () => {
    const result = applyRunEvent(replayRun([decl]), emit({ emittedBytes: 733_838, emittedItems: 165 }));
    expect(result.decision).toEqual({
      _tag: "halted",
      report: {
        _tag: "emission_halt", reason: "emission_cap_exceeded", surface: "get_tree",
        capBytes: 60_000, emittedBytes: 733_838, capItems: 500, emittedItems: 165,
      },
    });
    expect(result.next.emission).toMatchObject({ entries: 1, overCapEntries: 1 });
  });

  it("guard_defect: 아이템 캡 초과도 같은 기계", () => {
    const result = applyRunEvent(replayRun([decl]), emit({ emittedItems: 501 }));
    expect(result.decision).toMatchObject({
      _tag: "halted", report: { reason: "emission_cap_exceeded", emittedItems: 501 },
    });
  });

  it("도달 = 합법: emittedBytes == cap 은 승인", () => {
    const result = applyRunEvent(replayRun([decl]), emit({ emittedBytes: 60_000 }));
    expect(result.decision).toEqual({ _tag: "admitted" });
  });

  it("guard_defect: 음수·비정수 방출 수치는 거부 + 상태 무변경", () => {
    const declared = replayRun([decl]);
    for (const bad of [{ emittedBytes: -1 }, { emittedItems: 0.5 }, { truncatedBytes: Number.NaN }]) {
      const result = applyRunEvent(declared, emit(bad));
      expect(result.decision).toEqual({
        _tag: "rejected", reason: "negative_or_non_integer_emission",
      });
      expect(result.next).toEqual(declared);
    }
  });

  it("방출은 계량 이벤트 — callCap 을 소비하고, 자기 캡 위반이 누적 캡보다 우선한다", () => {
    const tight = { ...decl, callCap: 0 };
    // over-size + over-calls 동시: 이벤트 자신의 위반(emission)이 사유
    const both = applyRunEvent(replayRun([tight]), emit({ emittedBytes: 100_000 }));
    expect(both.decision).toMatchObject({ _tag: "halted", report: { _tag: "emission_halt" } });
    // 캡 이내 방출이지만 callCap 초과 → cap_halt
    const callOnly = applyRunEvent(replayRun([tight]), emit());
    expect(callOnly.decision).toMatchObject({
      _tag: "halted", report: { _tag: "cap_halt", reason: "call_cap_exceeded" },
    });
  });

  it("guard_defect: 방출 정지도 흡수 상태", () => {
    const halted = replayRun([decl, emit({ emittedBytes: 100_000 })]);
    const result = applyRunEvent(halted, emit());
    expect(result.decision).toEqual({ _tag: "rejected", reason: "already_halted" });
    expect(result.next).toEqual(halted);
  });
});
