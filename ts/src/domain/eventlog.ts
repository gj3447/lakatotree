/** append-only 감사 투영의 안정 이벤트 식별 — 정본 규약은 Python lakatos/io/reconcile.py
 * history_event_id: canonical JSON ["lakatotree-history-event-v1", tree, op, subject_id] 의 sha256.
 * 교차 언어 파리티는 event-id.test 의 실 Python 생성 픽스처가 핀한다 (드리프트 = RED).
 * lone surrogate: Python 은 utf-8 encode 에서 raise — TS 는 값으로 거부한다. TextEncoder 의
 * 무음 U+FFFD 대체가 Python 과 다른 해시를 만드는 경로를 선검출로 봉쇄 (파리티 위장 green 차단). */
import { canonicalBytes, type CanonicalValue } from "../contracts/canonical.ts";
import { sha256Hex } from "../contracts/sha256.ts";

export const HISTORY_EVENT_DOMAIN = "lakatotree-history-event-v1";

export type EventIdError = {
  readonly _tag: "event_id_error";
  readonly reason: "lone_surrogate" | "non_canonical_input";
};

const hasLoneSurrogate = (text: string): boolean => {
  for (let index = 0; index < text.length; index += 1) {
    const unit = text.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        index += 1;
        continue;
      }
      return true;
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) return true;
  }
  return false;
};

export const historyEventId = (
  tree: string,
  op: string,
  subjectId: string,
): string | EventIdError => {
  if (hasLoneSurrogate(tree) || hasLoneSurrogate(op) || hasLoneSurrogate(subjectId)) {
    return { _tag: "event_id_error", reason: "lone_surrogate" };
  }
  const bytes = canonicalBytes([HISTORY_EVENT_DOMAIN, tree, op, subjectId]);
  if (!(bytes instanceof Uint8Array)) {
    // 문자열 4-튜플 정준화는 실패할 수 없다 — 총함수 유지를 위한 닫힌 오류 값 (도달 불가 기대)
    return { _tag: "event_id_error", reason: "non_canonical_input" };
  }
  return `he-${sha256Hex(bytes)}`;
};

/** 페이로드 정준화 — Python reconcile.canonical_history_payload 파리티 (픽스처 핀).
 * NUL·lone surrogate 는 값·키 모두 선거부: 'Neo4j 는 통과시키고 PG JSONB 는 거부하는' 바이트를
 * durable intent 로 만들면 영구 오염이 남는다 (reconcile.py 교훈 — 투영 시점 검증 금지).
 * float 는 Python 보다 엄격하게 거부 (canonical.ts 마이크로 정수 규율 — 문서화된 부분집합). */
export type PayloadError = {
  readonly _tag: "payload_error";
  readonly reason: "nul_not_representable" | "lone_surrogate" | "non_canonical";
  readonly path: string;
};

const scanText = (text: string, path: string): PayloadError | null =>
  text.includes("\u0000")
    ? { _tag: "payload_error", reason: "nul_not_representable", path }
    : hasLoneSurrogate(text)
      ? { _tag: "payload_error", reason: "lone_surrogate", path }
      : null;

const scanValue = (value: CanonicalValue, path: string): PayloadError | null => {
  if (typeof value === "string") return scanText(value, path);
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const error = scanValue(value[index] ?? null, `${path}/${index}`);
      if (error !== null) return error;
    }
    return null;
  }
  if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      const keyError = scanText(key, `${path}/<key>`);
      if (keyError !== null) return keyError;
      if (item === undefined) continue;
      const error = scanValue(item, `${path}/${key}`);
      if (error !== null) return error;
    }
  }
  return null;
};

const decoder = new TextDecoder();

export const canonicalHistoryPayload = (value: CanonicalValue): string | PayloadError => {
  const scanned = scanValue(value, "");
  if (scanned !== null) return scanned;
  const bytes = canonicalBytes(value);
  if (!(bytes instanceof Uint8Array)) {
    return { _tag: "payload_error", reason: "non_canonical", path: bytes.path };
  }
  return decoder.decode(bytes);
};
