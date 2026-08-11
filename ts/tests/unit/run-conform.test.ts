/** Scenario RUN-CONFORM: B5 — 산문 §5 의 숫자·어휘는 기계 정본(spec/run-budget.v0.json)이 소유하고,
 * TS 구현과의 드리프트는 RED 다. 코드만 고치거나 스펙만 고치면 이 테스트가 울린다. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import type { BudgetDeclaration } from "../../src/domain/budget.ts";
import { usageOf } from "../../src/domain/budget.ts";
import { reduceBudget, emptyBudget } from "../../src/domain/ledger.ts";
import { NO_PROGRESS_RED_LIMIT } from "../../src/domain/streak.ts";
import { HALT_REASONS, REJECT_REASONS, applyRunEvent, replayRun } from "../../src/domain/run.ts";

const here = dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(
  readFileSync(join(here, "..", "..", "spec", "run-budget.v0.json"), "utf8"),
) as {
  schema_version: string;
  cap_check_order: string[];
  token_sum_formula: string;
  no_progress_red_limit: number;
  reject_reasons: string[];
  halt_reasons: string[];
};

describe("spec-pin: 어휘 드리프트 가드", () => {
  it("schema_version", () => {
    expect(spec.schema_version).toBe("run-budget/v1");
  });

  it("reject 어휘 완전 동치", () => {
    expect([...REJECT_REASONS].sort()).toEqual([...spec.reject_reasons].sort());
  });

  it("halt 어휘 완전 동치", () => {
    expect([...HALT_REASONS].sort()).toEqual([...spec.halt_reasons].sort());
  });

  it("B3 조문 상수 — 코드·스펙 한쪽만 고치면 RED", () => {
    expect(NO_PROGRESS_RED_LIMIT).toBe(spec.no_progress_red_limit);
  });
});

describe("spec-pin: 의미론 행동 합치", () => {
  const decl: BudgetDeclaration = {
    _tag: "BudgetDeclared", runId: "r1",
    callCap: 0, tokenCap: 0, wallMsCap: 0,
    emissionByteCap: 0, emissionItemCap: 0,
  };

  it("cap_check_order — 동시 초과 시 spec 순서의 앞 축이 사유가 된다", () => {
    expect(spec.cap_check_order).toEqual(["calls", "tokens", "wallMs"]);
    // tokens·wallMs 동시 초과는 평면 분리상 한 이벤트로 불가 — 관측 가능한 두 쌍만 핀한다.
    // calls+tokens 동시 초과 → calls 우선
    const callsBeforeTokens = applyRunEvent(replayRun([decl]), {
      _tag: "TokenSpendRecorded", actor: "a", runId: "r1",
      inputTokens: 1, cacheReadTokens: 0, outputTokens: 0,
    });
    expect(callsBeforeTokens.decision).toMatchObject({
      _tag: "halted", report: { reason: "call_cap_exceeded" },
    });
    // calls+wallMs 동시 초과 → calls 우선
    const callsBeforeWall = applyRunEvent(replayRun([decl]), {
      _tag: "ComputeSpendRecorded", actor: "a", runId: "r1",
      cpuMs: 0, gpuMs: 0, wallMs: 1,
    });
    expect(callsBeforeWall.decision).toMatchObject({
      _tag: "halted", report: { reason: "call_cap_exceeded" },
    });
    // calls 여유 시 tokens 축 단독 초과가 그 사유로 보고된다
    const tokensAlone = applyRunEvent(replayRun([{ ...decl, callCap: 10 }]), {
      _tag: "TokenSpendRecorded", actor: "a", runId: "r1",
      inputTokens: 1, cacheReadTokens: 0, outputTokens: 0,
    });
    expect(tokensAlone.decision).toMatchObject({
      _tag: "halted", report: { reason: "token_cap_exceeded" },
    });
  });

  it("token_sum_formula — 세 필드 합산 (cacheRead 포함: 고래 세션의 주범이 캐시리드였다)", () => {
    expect(spec.token_sum_formula).toBe("inputTokens+cacheReadTokens+outputTokens");
    const budget = reduceBudget(emptyBudget, {
      _tag: "TokenSpendRecorded", actor: "a", runId: "r1",
      inputTokens: 1, cacheReadTokens: 2, outputTokens: 3,
    });
    expect(usageOf(0, budget).tokens).toBe(6);
  });
});
