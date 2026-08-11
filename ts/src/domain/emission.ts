/** 유계 방출 탐지선 — 방출은 보존 공시(emitted+truncated=원본)와 함께 기재되고, 선언된 단일 응답
 * 캡 초과는 기재 후 정지 사유로 격상된다 (bound.ts 예방선의 이중선). surface 는 관측 데이터 —
 * 정규화(도구명 고정)는 emit-adapter 책임. 실측 근거: get_tree 단일 응답 733,838B(≈18만 토큰). */

export interface EmissionRecorded {
  readonly _tag: "EmissionRecorded";
  readonly runId: string;
  readonly surface: string;
  readonly emittedBytes: number;
  readonly emittedItems: number;
  readonly truncatedBytes: number;
  readonly truncatedItems: number;
}

export interface EmissionLedger {
  readonly emittedBytes: number;
  readonly emittedItems: number;
  readonly truncatedBytes: number;
  readonly truncatedItems: number;
  readonly entries: number;
  readonly overCapEntries: number;
}

export type EmissionError = {
  readonly _tag: "invalid_emission";
  readonly reason: "negative_or_non_integer_emission";
};

export const emptyEmissionLedger: EmissionLedger = {
  emittedBytes: 0,
  emittedItems: 0,
  truncatedBytes: 0,
  truncatedItems: 0,
  entries: 0,
  overCapEntries: 0,
};

const nonNegInt = (n: number): boolean => Number.isSafeInteger(n) && n >= 0;

export const validateEmission = (event: EmissionRecorded): EmissionError | null =>
  nonNegInt(event.emittedBytes) &&
  nonNegInt(event.emittedItems) &&
  nonNegInt(event.truncatedBytes) &&
  nonNegInt(event.truncatedItems)
    ? null
    : { _tag: "invalid_emission", reason: "negative_or_non_integer_emission" };

export const reduceEmission = (
  ledger: EmissionLedger,
  event: EmissionRecorded,
  overCap: boolean,
): EmissionLedger => ({
  emittedBytes: ledger.emittedBytes + event.emittedBytes,
  emittedItems: ledger.emittedItems + event.emittedItems,
  truncatedBytes: ledger.truncatedBytes + event.truncatedBytes,
  truncatedItems: ledger.truncatedItems + event.truncatedItems,
  entries: ledger.entries + 1,
  overCapEntries: ledger.overCapEntries + (overCap ? 1 : 0),
});
