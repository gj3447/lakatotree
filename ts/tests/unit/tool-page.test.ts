/** Scenario TOOL-PAGE: 게이트웨이의 유일 성공 반환형 — 모든 도구 응답은 커서 재개 가능한
 * 유계 페이지다. 무제한 응답이 반환 타입으로 표현 불가('unbounded 어휘가 없는 것이 증명').
 * 잘림은 숨기지 않는다: offset+body+remaining=total 보존 공시. */
import { describe, expect, it } from "vitest";
import { emitPage } from "../../src/domain/page.ts";

describe("emitPage", () => {
  it("guard_mechanism: 첫 페이지 — cap 만큼 자르고 다음 커서·잔량·전체를 공시", () => {
    expect(emitPage("get_tree", "abcdefghij", 4, "")).toEqual({
      _tag: "ToolPage", surface: "get_tree",
      body: "abcd", capChars: 4, offsetChars: 0,
      remainingChars: 6, nextCursor: "4", totalChars: 10,
    });
  });

  it("guard_mechanism: 커서 재개 — 이어서 자르고 마지막 페이지는 nextCursor 빈 문자열", () => {
    expect(emitPage("get_tree", "abcdefghij", 4, "8")).toEqual({
      _tag: "ToolPage", surface: "get_tree",
      body: "ij", capChars: 4, offsetChars: 8,
      remainingChars: 0, nextCursor: "", totalChars: 10,
    });
  });

  it("정확히 나누어떨어지면 마지막 페이지에서 끝난다 (빈 꼬리 페이지 없음)", () => {
    const page = emitPage("s", "abcdefgh", 4, "4");
    expect(page).toMatchObject({ body: "efgh", nextCursor: "", remainingChars: 0 });
  });

  it("빈 원본은 단일 빈 페이지 — 합법", () => {
    expect(emitPage("s", "", 10, "")).toMatchObject({
      body: "", nextCursor: "", totalChars: 0, remainingChars: 0,
    });
  });

  it("offset == total 커서는 합법인 끝 읽기 (빈 페이지, 종료)", () => {
    expect(emitPage("s", "abc", 2, "3")).toMatchObject({ body: "", nextCursor: "" });
  });

  it("guard_defect: 무효 cap 은 fail-closed — bound.ts 와 같은 닫힌 사유", () => {
    for (const cap of [0, -1, 1.5, Number.NaN]) {
      expect(emitPage("s", "abc", cap, "")).toEqual({
        _tag: "invalid_page", reason: "non_positive_or_non_integer_cap",
      });
    }
  });

  it("guard_defect: 무효 커서(비정수·음수·범위 밖)는 fail-closed", () => {
    for (const cursor of ["abc", "-1", "1.5", "4", "1e2"]) {
      expect(emitPage("s", "abc", 2, cursor)).toEqual({
        _tag: "invalid_page", reason: "invalid_cursor",
      });
    }
  });
});
