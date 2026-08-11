/** 페이지 법칙 (byte-cap) — ∀원본·유효 cap: 각 페이지 emittedBytes ≤ cap · 보존
 * (offsetBytes+emitted+remaining=totalBytes) · 무손실 재조립 · 코드포인트 경계 보존 ·
 * 커서 체인 항상 종료(진행 보장). */
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { emitPage, type ToolPage } from "../../src/domain/page.ts";

const validCap = fc.integer({ min: 4, max: 60 });
// 서로게이트 쌍 포함 유니코드 원본 — grapheme 단위 문자열
const arbText = fc.string({ maxLength: 200, unit: "grapheme" });

const utf8Len = (s: string): number => new TextEncoder().encode(s).length;

const walkPages = (text: string, cap: number): readonly ToolPage[] => {
  const pages: ToolPage[] = [];
  let cursor = "";
  for (let guard = 0; guard < 10_000; guard += 1) {
    const page = emitPage("s", text, cap, cursor);
    expect(page._tag).toBe("ToolPage");
    if (page._tag !== "ToolPage") return pages;
    pages.push(page);
    if (page.nextCursor === "") return pages;
    cursor = page.nextCursor;
  }
  throw new Error("cursor chain did not terminate");
};

describe("tool page laws (bytes)", () => {
  it("각 페이지 emittedBytes ≤ cap(빈 원본 제외 진행 보장) && 보존 공시 && 무손실 재조립", () => {
    fc.assert(
      fc.property(arbText, validCap, (text, cap) => {
        const pages = walkPages(text, cap);
        for (const page of pages) {
          expect(page.emittedBytes).toBeLessThanOrEqual(cap);
          expect(page.emittedBytes).toBe(utf8Len(page.body));
          expect(page.offsetBytes + page.emittedBytes + page.remainingBytes).toBe(
            page.totalBytes,
          );
          expect(page.totalBytes).toBe(utf8Len(text));
          if (text.length > 0 && page.body.length === 0) {
            // 진행 보장: 비어있는 body 는 끝 읽기에서만 가능
            expect(page.nextCursor).toBe("");
          }
        }
        expect(pages.map((p) => p.body).join("")).toBe(text);
      }),
      { numRuns: 300 },
    );
  });

  it("코드포인트 경계 보존 — 어느 페이지 body 도 lone surrogate 로 시작/끝나지 않는다", () => {
    fc.assert(
      fc.property(arbText, validCap, (text, cap) => {
        for (const page of walkPages(text, cap)) {
          if (page.body.length === 0) continue;
          const first = page.body.charCodeAt(0);
          const last = page.body.charCodeAt(page.body.length - 1);
          // 시작이 low surrogate 면 쌍이 쪼개진 것
          expect(first >= 0xdc00 && first <= 0xdfff).toBe(false);
          // 끝이 high surrogate 면 쌍이 쪼개진 것
          expect(last >= 0xd800 && last <= 0xdbff).toBe(false);
        }
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
