/** 게이트웨이 유일 성공 반환형 — 커서 재개 가능한 유계 페이지 (순수 총함수).
 * cap 단위는 UTF-8 실바이트 — 와이어·EmissionRecorded 원장·실측(733,838B)과 같은 단위
 * (recon 리스크 #4: 문자 cap 은 한국어에서 바이트 계량을 3배 초과해 예방선-탐지선이 어긋난다).
 * 절단 경계는 코드포인트 — 서로게이트 쌍 분할 절대 금지. cap ≥ 4바이트(최대 코드포인트)로
 * 진행 보장(무한 커서 루프 원천 차단). 커서는 UTF-16 code unit 오프셋의 정준 십진 문자열
 * (왕복 검사 — 한 개념 한 표현), "" = 처음/끝. 잘림은 숨기지 않는다:
 * offsetBytes + emittedBytes + remainingBytes = totalBytes 보존 공시.
 * lone surrogate 는 3바이트로 계상(TextEncoder 의 U+FFFD 대체와 동일 크기). */

export interface ToolPage {
  readonly _tag: "ToolPage";
  readonly surface: string;
  readonly body: string;
  readonly capBytes: number;
  readonly offsetChars: number;
  readonly offsetBytes: number;
  readonly emittedBytes: number;
  readonly remainingBytes: number;
  readonly totalChars: number;
  readonly totalBytes: number;
  readonly nextCursor: string;
}

export type PageError = {
  readonly _tag: "invalid_page";
  readonly reason: "cap_below_min4_or_non_integer" | "invalid_cursor";
};

export const MIN_CAP_BYTES = 4;

const utf8Bytes = (codePoint: number): number =>
  codePoint < 0x80 ? 1 : codePoint < 0x800 ? 2 : codePoint < 0x10000 ? 3 : 4;

const byteLength = (text: string): number => {
  let bytes = 0;
  for (const ch of text) {
    bytes += utf8Bytes(ch.codePointAt(0) ?? 0);
  }
  return bytes;
};

const isLowSurrogate = (unit: number): boolean => unit >= 0xdc00 && unit <= 0xdfff;
const isHighSurrogate = (unit: number): boolean => unit >= 0xd800 && unit <= 0xdbff;

const parseCursor = (cursor: string, fullText: string): number | null => {
  if (cursor === "") return 0;
  const offset = Number(cursor);
  // 왕복 검사 = 정준 십진 표기만 수용("1e2"·"0x10"·" 5 "·"007" 거부) — 한 개념 한 표현.
  if (
    !Number.isSafeInteger(offset) ||
    offset < 0 ||
    offset > fullText.length ||
    String(offset) !== cursor
  ) {
    return null;
  }
  // 서로게이트 쌍 한가운데 오프셋 거부 — 코드포인트 경계만 합법.
  if (
    offset > 0 &&
    offset < fullText.length &&
    isLowSurrogate(fullText.charCodeAt(offset)) &&
    isHighSurrogate(fullText.charCodeAt(offset - 1))
  ) {
    return null;
  }
  return offset;
};

export const emitPage = (
  surface: string,
  fullText: string,
  capBytes: number,
  cursor: string,
): ToolPage | PageError => {
  if (!Number.isSafeInteger(capBytes) || capBytes < MIN_CAP_BYTES) {
    return { _tag: "invalid_page", reason: "cap_below_min4_or_non_integer" };
  }
  const offsetChars = parseCursor(cursor, fullText);
  if (offsetChars === null) {
    return { _tag: "invalid_page", reason: "invalid_cursor" };
  }
  const offsetBytes = byteLength(fullText.slice(0, offsetChars));
  const rest = fullText.slice(offsetChars);
  const restBytes = byteLength(rest);
  let endChars = offsetChars;
  let emittedBytes = 0;
  for (const ch of rest) {
    const chBytes = utf8Bytes(ch.codePointAt(0) ?? 0);
    if (emittedBytes + chBytes > capBytes) break;
    emittedBytes += chBytes;
    endChars += ch.length;
  }
  const body = fullText.slice(offsetChars, endChars);
  const remainingBytes = restBytes - emittedBytes;
  return {
    _tag: "ToolPage",
    surface,
    body,
    capBytes,
    offsetChars,
    offsetBytes,
    emittedBytes,
    remainingBytes,
    totalChars: fullText.length,
    totalBytes: offsetBytes + restBytes,
    nextCursor: remainingBytes > 0 ? String(endChars) : "",
  };
};
