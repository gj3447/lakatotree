/** B1 예산 선언 — CLAUDE.md §5: '자율 실행은 시작 전에 호출·토큰·wall-time 상한을 선언한다.
 * 초과 = 정지 + 보고 (재시도 아님).' 방출 상한(emission*)이 필수 필드다 —
 * '출력 무제한 예산'은 타입상 표현 불가 (canon: AI-facing 출력 유계).
 * cacheReadTokens 도 합산한다 — 폭식 실측의 주범이 캐시리드(일 ~18억)였다. */
import type { BudgetState } from "./ledger.ts";

export interface BudgetDeclaration {
  readonly _tag: "BudgetDeclared";
  readonly runId: string;
  readonly callCap: number;
  readonly tokenCap: number;
  readonly wallMsCap: number;
  readonly emissionByteCap: number;
  readonly emissionItemCap: number;
}

export interface Usage {
  readonly calls: number;
  readonly tokens: number;
  readonly wallMs: number;
}

export type CapBreach = "call_cap_exceeded" | "token_cap_exceeded" | "wall_cap_exceeded";

export type DeclarationError = {
  readonly _tag: "invalid_declaration";
  readonly reason: "empty_run_id" | "negative_or_non_integer_cap";
};

const nonNegInt = (n: number): boolean => Number.isSafeInteger(n) && n >= 0;

export const validateBudgetDeclaration = (
  decl: BudgetDeclaration,
): DeclarationError | null => {
  if (decl.runId === "") {
    return { _tag: "invalid_declaration", reason: "empty_run_id" };
  }
  return nonNegInt(decl.callCap) &&
    nonNegInt(decl.tokenCap) &&
    nonNegInt(decl.wallMsCap) &&
    nonNegInt(decl.emissionByteCap) &&
    nonNegInt(decl.emissionItemCap)
    ? null
    : { _tag: "invalid_declaration", reason: "negative_or_non_integer_cap" };
};

/** 사용량 투영 — calls 의 정의(승인된 계량 이벤트 수)는 spec/run-budget.v0.json 이 핀한다. */
export const usageOf = (calls: number, budget: BudgetState): Usage => ({
  calls,
  tokens:
    budget.token.inputTokens + budget.token.cacheReadTokens + budget.token.outputTokens,
  wallMs: budget.compute.wallMs,
});

/** 초과 판정 — used > cap 만 초과(도달=합법). 검사 순서는 spec cap_check_order 가 핀한다. */
export const checkCaps = (decl: BudgetDeclaration, usage: Usage): CapBreach | null =>
  usage.calls > decl.callCap
    ? "call_cap_exceeded"
    : usage.tokens > decl.tokenCap
      ? "token_cap_exceeded"
      : usage.wallMs > decl.wallMsCap
        ? "wall_cap_exceeded"
        : null;
