/** 유계 방출 성질 — 어떤 입력·유효 cap 에서도 출력 ≤ cap (구조적 유계) · 보존(원본=방출+잘림) · 멱등. */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { boundList, boundText } from "../../src/domain/bound.ts";

const validCap = fc.integer({ min: 1, max: 1000 });
const invalidCap = fc.oneof(
  fc.integer({ min: -1000, max: 0 }),
  fc.constantFrom(1.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 53),
);

describe("bounded emission laws", () => {
  it("구조적 유계 + 보존: items ≤ cap && 원본 길이 = 방출 + truncated && prefix 동일", () => {
    fc.assert(
      fc.property(fc.array(fc.integer(), { maxLength: 200 }), validCap, (items, cap) => {
        const bounded = boundList(items, cap);
        expect(bounded._tag).toBe("BoundedList");
        if (bounded._tag !== "BoundedList") return;
        expect(bounded.items.length).toBeLessThanOrEqual(cap);
        expect(bounded.items.length + bounded.truncated).toBe(items.length);
        expect([...bounded.items]).toEqual(items.slice(0, bounded.items.length));
        expect(bounded.cap).toBe(cap);
      }),
      { numRuns: 300 },
    );
  });

  it("멱등: bound ∘ bound = bound (같은 cap 재적용은 무손실)", () => {
    fc.assert(
      fc.property(fc.array(fc.string(), { maxLength: 100 }), validCap, (items, cap) => {
        const once = boundList(items, cap);
        if (once._tag !== "BoundedList") return;
        const twice = boundList(once.items, cap);
        expect(twice).toEqual({ ...once, truncated: 0, items: once.items });
      }),
      { numRuns: 200 },
    );
  });

  it("guard_defect: 무효 cap 은 입력과 무관하게 항상 오류 값", () => {
    fc.assert(
      fc.property(fc.array(fc.integer(), { maxLength: 20 }), invalidCap, (items, cap) => {
        expect(boundList(items, cap)).toEqual({
          _tag: "invalid_cap",
          reason: "non_positive_or_non_integer_cap",
        });
      }),
      { numRuns: 200 },
    );
  });

  it("boundText 도 같은 법칙: 길이 ≤ cap && 보존 && prefix", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 300 }), validCap, (text, cap) => {
        const bounded = boundText(text, cap);
        expect(bounded._tag).toBe("BoundedText");
        if (bounded._tag !== "BoundedText") return;
        expect(bounded.text.length).toBeLessThanOrEqual(cap);
        expect(bounded.text.length + bounded.truncatedChars).toBe(text.length);
        expect(bounded.text).toBe(text.slice(0, bounded.text.length));
      }),
      { numRuns: 300 },
    );
  });
});
