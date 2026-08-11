/** lakatos-ts 정준 JSON v0 — 결정론 바이트: 키 유니코드 정렬, 공백 0, UTF-8,
 * 정수만(float/NaN/Inf 거부 — 도메인은 마이크로 정수), null 허용, 배열은 순서 보존.
 * Python 엔진의 canonical-JSON 영수증 프리이미지 관례(sort_keys)와 합치하는 보수적 부분집합.
 * 새 봉인 타입은 자기 type_header 를 가진다 (도메인 분리 — C1 S3 관례). */

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
  const keys = Object.keys(value).sort();
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
