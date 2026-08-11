/** 페이지 법칙 — ∀원본·유효 cap: 각 페이지 ≤ cap · 보존(offset+body+remaining=total) ·
 * 무손실 재조립(커서 체인 완주 concat == 원본) · 페이지 수 = ceil(n/cap). */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { emitPage, type ToolPage } from "../../src/domain/page.ts";

const validCap = fc.integer({ min: 1, max: 50 });

const walkPages = (text: string, cap: number): readonly ToolPage[] => {
  const pages: ToolPage[] = [];
  let cursor = "";
  for (;;) {
    const page = emitPage("s", text, cap, cursor);
    expect(page._tag).toBe("ToolPage");
    if (page._tag !== "ToolPage") return pages;
    pages.push(page);
    if (page.nextCursor === "") return pages;
    cursor = page.nextCursor;
  }
};

describe("tool page laws", () => {
  it("각 페이지 ≤ cap && 보존 공시 && 무손실 재조립", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 400, unit: "binary" }), validCap, (text, cap) => {
        const pages = walkPages(text, cap);
        for (const page of pages) {
          expect(page.body.length).toBeLessThanOrEqual(cap);
          expect(page.offsetChars + page.body.length + page.remainingChars).toBe(
            page.totalChars,
          );
          expect(page.totalChars).toBe(text.length);
        }
        expect(pages.map((p) => p.body).join("")).toBe(text);
      }),
      { numRuns: 300 },
    );
  });

  it("페이지 수 = max(1, ceil(n/cap)) — 커서 체인은 항상 종료한다", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 400 }), validCap, (text, cap) => {
        const pages = walkPages(text, cap);
        expect(pages.length).toBe(Math.max(1, Math.ceil(text.length / cap)));
      }),
      { numRuns: 200 },
    );
  });

  it("guard_defect: 범위 밖 커서는 원본과 무관하게 항상 오류 값", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 50 }), validCap, (text, cap) => {
        expect(emitPage("s", text, cap, String(text.length + 1))).toEqual({
          _tag: "invalid_page", reason: "invalid_cursor",
        });
      }),
      { numRuns: 100 },
    );
  });
});
