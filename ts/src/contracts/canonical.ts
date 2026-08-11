/** lakatos-ts 정준 JSON v0 — 결정론 바이트: 키 **코드포인트 순** 정렬, 공백 0, UTF-8,
 * 정수만(float/NaN/Inf 거부 — 도메인은 마이크로 정수), null 허용, 배열은 순서 보존.
 * Python 엔진의 canonical-JSON 영수증 프리이미지 관례(sort_keys)와 합치하는 보수적 부분집합.
 * 정렬 정본 선택: Python str 비교 = 코드포인트 순. JS 기본 sort(UTF-16 코드유닛 순)는 astral
 * 키(U+10000+)를 U+E000~U+FFFF 앞에 놓아 같은 객체가 다른 sha 를 얻는다 (제3자 리뷰 실결함,
 * canonical-sort.test 재현 픽스처). RFC 8785(JCS)는 UTF-16 순이 표준이나 이 repo 는 Python
 * 오라클 파리티가 정본이다. 새 봉인 타입은 자기 type_header 를 가진다 (도메인 분리 — C1 S3 관례). */

export type CanonicalValue =
  | null
  | boolean
  | number
  | string
  | readonly CanonicalValue[]
  | { readonly [key: string]: CanonicalValue };

export type CanonicalError = { readonly _tag: "canonical_error"; readonly reason: string; readonly path: string };

const encoder = new TextEncoder();

const escapeString = (value: string): string => JSON.stringify(value);

/** Python str 비교 파리티 — 코드포인트 배열의 사전식 비교 (UTF-16 코드유닛 비교 금지). */
const codePointCompare = (a: string, b: string): number => {
  const aPoints = [...a];
  const bPoints = [...b];
  const shorter = Math.min(aPoints.length, bPoints.length);
  for (let index = 0; index < shorter; index += 1) {
    const pa = aPoints[index]?.codePointAt(0) ?? 0;
    const pb = bPoints[index]?.codePointAt(0) ?? 0;
    if (pa !== pb) return pa - pb;
  }
  return aPoints.length - bPoints.length;
};

const render = (
  value: CanonicalValue,
  path: string,
  depth: number,
): string | CanonicalError => {
  if (depth > 64) {
    return { _tag: "canonical_error", reason: "nesting_depth_exceeded", path };
  }
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      return { _tag: "canonical_error", reason: "non_integer_number", path };
    }
    return String(value);
  }
  if (typeof value === "string") return escapeString(value);
  if (Array.isArray(value)) {
    const parts: string[] = [];
    for (let index = 0; index < value.length; index += 1) {
      const item = value[index];
      const rendered = render(item ?? null, `${path}/${index}`, depth + 1);
      if (typeof rendered !== "string") return rendered;
      parts.push(rendered);
    }
    return `[${parts.join(",")}]`;
  }
  const keys = Object.keys(value).sort(codePointCompare);
  const parts: string[] = [];
  for (const key of keys) {
    const item = (value as { readonly [k: string]: CanonicalValue })[key];
    if (item === undefined) continue;
    const rendered = render(item, `${path}/${key}`, depth + 1);
    if (typeof rendered !== "string") return rendered;
    parts.push(`${escapeString(key)}:${rendered}`);
  }
  return `{${parts.join(",")}}`;
};

export const canonicalBytes = (value: CanonicalValue): Uint8Array | CanonicalError => {
  const rendered = render(value, "", 0);
  if (typeof rendered !== "string") return rendered;
  return encoder.encode(rendered);
};
