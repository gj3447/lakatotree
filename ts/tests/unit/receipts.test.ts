/** 정준화·콘텐츠 주소 법칙 — 생산자는 자기 성공의 유일 검증자가 아니다 (node:crypto 교차 검증). */
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { canonicalBytes } from "../../src/contracts/canonical.ts";
import { sha256Hex } from "../../src/contracts/sha256.ts";
import { receiptSha, RECEIPT_TYPE_HEADER, type VerdictReceipt } from "../../src/domain/receipts.ts";

const receipt: VerdictReceipt = {
  type_header: RECEIPT_TYPE_HEADER,
  tree: "t", tag: "n1", verdict: "partial", value_micro: 40_000,
  bundle_sha: "b1", event_id: "e2", prev_receipt_sha: "",
};

describe("canonical bytes", () => {
  it("key order does not change the bytes", () => {
    const a = canonicalBytes({ b: 1, a: "x" });
    const b = canonicalBytes({ a: "x", b: 1 });
    expect(a).toEqual(b);
  });

  it("floats are rejected as typed errors (총함수)", () => {
    const bad = canonicalBytes({ x: 1.5 });
    expect(bad).toMatchObject({ _tag: "canonical_error", reason: "non_integer_number" });
  });

  it("nesting depth is bounded", () => {
    let value: unknown = 1;
    for (let index = 0; index < 70; index += 1) value = [value];
    const bad = canonicalBytes(value as Parameters<typeof canonicalBytes>[0]);
    expect(bad).toMatchObject({ _tag: "canonical_error", reason: "nesting_depth_exceeded" });
  });
});

describe("content-addressed receipts", () => {
  it("pure sha256 matches node:crypto on the same canonical bytes", () => {
    const bytes = canonicalBytes({ b: 1, a: "x" });
    expect(bytes).toBeInstanceOf(Uint8Array);
    if (!(bytes instanceof Uint8Array)) return;
    const independent = createHash("sha256").update(bytes).digest("hex");
    expect(sha256Hex(bytes)).toBe(independent);
  });

  it("same content -> same sha (freshen), different content -> different sha", () => {
    expect(receiptSha(receipt)).toBe(receiptSha({ ...receipt }));
    expect(receiptSha(receipt)).not.toBe(receiptSha({ ...receipt, verdict: "rejected" }));
    expect(receiptSha(receipt)).not.toBe(receiptSha({ ...receipt, prev_receipt_sha: "sha256:x" }));
  });

  it("sha is prefixed and 64-hex", () => {
    const sha = receiptSha(receipt);
    expect(typeof sha).toBe("string");
    if (typeof sha !== "string") return;
    expect(sha).toMatch(/^sha256:[0-9a-f]{64}$/);
  });
});
