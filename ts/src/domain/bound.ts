/** 유계 방출 예방선 — canon 'AI-facing 출력은 구조적으로 유계' (StandardHarnessMcpState
 * mcp_fleet_audit: 전수스캔·무제한출력 금지)의 순수 총함수화. 자르되 잘린 양을 공시한다 —
 * 선례: fsck findings[:500]+truncated 카운터. 무효 cap 은 fail-closed 오류 값:
 * 무제한 방출로 조용히 열리는 경로가 타입상 존재하지 않는다. */

export type BoundError = {
  readonly _tag: "invalid_cap";
  readonly reason: "non_positive_or_non_integer_cap";
};

export interface BoundedList<T> {
  readonly _tag: "BoundedList";
  readonly cap: number;
  readonly items: readonly T[];
  readonly truncated: number;
}

export interface BoundedText {
  readonly _tag: "BoundedText";
  readonly cap: number;
  readonly text: string;
  readonly truncatedChars: number;
}

const invalidCap: BoundError = {
  _tag: "invalid_cap",
  reason: "non_positive_or_non_integer_cap",
};

const isValidCap = (cap: number): boolean => Number.isSafeInteger(cap) && cap > 0;

export const boundList = <T>(
  items: readonly T[],
  cap: number,
): BoundedList<T> | BoundError =>
  isValidCap(cap)
    ? {
        _tag: "BoundedList",
        cap,
        items: items.slice(0, cap),
        truncated: Math.max(0, items.length - cap),
      }
    : invalidCap;

export const boundText = (text: string, cap: number): BoundedText | BoundError =>
  isValidCap(cap)
    ? {
        _tag: "BoundedText",
        cap,
        text: text.slice(0, cap),
        truncatedChars: Math.max(0, text.length - cap),
      }
    : invalidCap;
