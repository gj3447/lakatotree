/** 회계 이중 평면 — AI 토큰 원장과 컴퓨팅 원장은 타입·이벤트·리듀서가 분리된 별개 평면이다.
 * 교차 오염(한 평면 이벤트가 다른 평면 상태 변경)은 구조적으로 불가능하고 property 게이트가 지킨다. */

export interface TokenSpend {
  readonly _tag: "TokenSpendRecorded";
  readonly actor: string;
  readonly runId: string;
  readonly inputTokens: number;
  readonly cacheReadTokens: number;
  readonly outputTokens: number;
}

export interface ComputeSpend {
  readonly _tag: "ComputeSpendRecorded";
  readonly actor: string;
  readonly runId: string;
  readonly cpuMs: number;
  readonly gpuMs: number;
  readonly wallMs: number;
}

export interface TokenLedger {
  readonly inputTokens: number;
  readonly cacheReadTokens: number;
  readonly outputTokens: number;
  readonly entries: number;
}

export interface ComputeLedger {
  readonly cpuMs: number;
  readonly gpuMs: number;
  readonly wallMs: number;
  readonly entries: number;
}

export type LedgerError = { readonly _tag: "invalid_spend"; readonly reason: string };

export const emptyTokenLedger: TokenLedger = {
  inputTokens: 0, cacheReadTokens: 0, outputTokens: 0, entries: 0,
};

export const emptyComputeLedger: ComputeLedger = {
  cpuMs: 0, gpuMs: 0, wallMs: 0, entries: 0,
};

const nonNegInt = (n: number): boolean => Number.isSafeInteger(n) && n >= 0;

export const validateTokenSpend = (spend: TokenSpend): LedgerError | null =>
  nonNegInt(spend.inputTokens) && nonNegInt(spend.cacheReadTokens) && nonNegInt(spend.outputTokens)
    ? null
    : { _tag: "invalid_spend", reason: "negative_or_non_integer_tokens" };

export const validateComputeSpend = (spend: ComputeSpend): LedgerError | null =>
  nonNegInt(spend.cpuMs) && nonNegInt(spend.gpuMs) && nonNegInt(spend.wallMs)
    ? null
    : { _tag: "invalid_spend", reason: "negative_or_non_integer_compute" };

export const reduceTokenLedger = (ledger: TokenLedger, spend: TokenSpend): TokenLedger => ({
  inputTokens: ledger.inputTokens + spend.inputTokens,
  cacheReadTokens: ledger.cacheReadTokens + spend.cacheReadTokens,
  outputTokens: ledger.outputTokens + spend.outputTokens,
  entries: ledger.entries + 1,
});

export const reduceComputeLedger = (ledger: ComputeLedger, spend: ComputeSpend): ComputeLedger => ({
  cpuMs: ledger.cpuMs + spend.cpuMs,
  gpuMs: ledger.gpuMs + spend.gpuMs,
  wallMs: ledger.wallMs + spend.wallMs,
  entries: ledger.entries + 1,
});

/** 합성 상태 — 두 평면을 담지만 라우팅은 _tag 로만 하며 교차 갱신 경로가 없다. */
export interface BudgetState {
  readonly token: TokenLedger;
  readonly compute: ComputeLedger;
}

export const emptyBudget: BudgetState = { token: emptyTokenLedger, compute: emptyComputeLedger };

export const reduceBudget = (
  state: BudgetState,
  spend: TokenSpend | ComputeSpend,
): BudgetState =>
  spend._tag === "TokenSpendRecorded"
    ? { token: reduceTokenLedger(state.token, spend), compute: state.compute }
    : { token: state.token, compute: reduceComputeLedger(state.compute, spend) };
