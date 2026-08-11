/** 게이트웨이 유일 성공 반환형 — 커서 재개 가능한 유계 페이지 (순수 총함수).
 * canon 'AI-facing 출력 유계'의 어댑터 실사용 승격: bound.ts 3회 반복 조건 충족 후의 얇은 공통층.
 * 단위는 UTF-16 code unit(chars) — 실바이트 계량은 어댑터가 EmissionRecorded 로 별도 기재한다
 * (예방=chars 페이지네이션 / 탐지=true bytes, 이중선). 잘림은 숨기지 않는다:
 * offset + body + remaining = total 보존 공시. 커서는 십진 정수 문자열, "" = 처음/끝. */

export interface ToolPage {
  readonly _tag: "ToolPage";
  readonly surface: string;
  readonly body: string;
  readonly capChars: number;
  readonly offsetChars: number;
  readonly remainingChars: number;
  readonly nextCursor: string;
  readonly totalChars: number;
}

export type PageError = {
  readonly _tag: "invalid_page";
  readonly reason: "non_positive_or_non_integer_cap" | "invalid_cursor";
};

const isValidCap = (cap: number): boolean => Number.isSafeInteger(cap) && cap > 0;

const parseCursor = (cursor: string, totalChars: number): number | null => {
  if (cursor === "") return 0;
  const offset = Number(cursor);
  // 왕복 검사 = 정준 십진 표기만 수용("1e2"·"0x10"·" 5 "·"007" 거부) — 한 개념 한 표현 (wire 레벨).
  return Number.isSafeInteger(offset) &&
    offset >= 0 &&
    offset <= totalChars &&
    String(offset) === cursor
    ? offset
    : null;
};

export const emitPage = (
  surface: string,
  fullText: string,
  capChars: number,
  cursor: string,
): ToolPage | PageError => {
  if (!isValidCap(capChars)) {
    return { _tag: "invalid_page", reason: "non_positive_or_non_integer_cap" };
  }
  const offsetChars = parseCursor(cursor, fullText.length);
  if (offsetChars === null) {
    return { _tag: "invalid_page", reason: "invalid_cursor" };
  }
  const body = fullText.slice(offsetChars, offsetChars + capChars);
  const remainingChars = fullText.length - offsetChars - body.length;
  return {
    _tag: "ToolPage",
    surface,
    body,
    capChars,
    offsetChars,
    remainingChars,
    nextCursor: remainingChars > 0 ? String(offsetChars + body.length) : "",
    totalChars: fullText.length,
  };
};
