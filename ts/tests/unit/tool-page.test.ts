/** Scenario TOOL-PAGE: 게이트웨이의 유일 성공 반환형 — 커서 재개 가능한 유계 페이지.
 * cap 단위는 UTF-8 실바이트(와이어·원장·실측과 동일 단위 — recon 리스크 #4 봉합),
 * 절단 경계는 코드포인트(서로게이트 분할 절대 금지). 잘림은 숨기지 않는다:
 * offsetBytes + emittedBytes + remainingBytes = totalBytes 보존 공시. */
import { describe, expect, it } from "vitest";
import { emitPage } from "../../src/domain/page.ts";

describe("emitPage (byte-cap, code-point-safe)", () => {
  it("guard_mechanism: ASCII — cap 바이트만큼 자르고 커서·잔량·전체를 공시", () => {
    expect(emitPage("get_tree", "0123456789", 4, "")).toEqual({
      _tag: "ToolPage", surface: "get_tree",
      body: "0123", capBytes: 4,
      offsetChars: 0, offsetBytes: 0,
      emittedBytes: 4, remainingBytes: 6,
      totalChars: 10, totalBytes: 10,
      nextCursor: "4",
    });
  });

  it("guard_mechanism: 한국어(3바이트/자) — 코드포인트 경계에서 cap 이하 최대 절단", () => {
    // cap 8바이트: '가'(3)+'나'(3)=6 ≤ 8, '다' 추가 시 9 초과 → body '가나'
    expect(emitPage("s", "가나다라마", 8, "")).toEqual({
      _tag: "ToolPage", surface: "s",
      body: "가나", capBytes: 8,
      offsetChars: 0, offsetBytes: 0,
      emittedBytes: 6, remainingBytes: 9,
      totalChars: 5, totalBytes: 15,
      nextCursor: "2",
    });
  });

  it("guard_mechanism: 커서 재개 — offsetBytes 공시 + 마지막 페이지 nextCursor 빈 문자열", () => {
    expect(emitPage("s", "가나다라마", 9, "2")).toEqual({
      _tag: "ToolPage", surface: "s",
      body: "다라마", capBytes: 9,
      offsetChars: 2, offsetBytes: 6,
      emittedBytes: 9, remainingBytes: 0,
      totalChars: 5, totalBytes: 15,
      nextCursor: "",
    });
  });

  it("서로게이트 쌍(4바이트)은 절대 쪼개지 않는다 — cap 이 쌍 중간이면 앞에서 멈춤", () => {
    // '😀' = U+1F600, UTF-8 4바이트, UTF-16 2 code unit
    const page = emitPage("s", "ab😀cd", 5, "");
    expect(page).toMatchObject({
      body: "ab", emittedBytes: 2, nextCursor: "2", totalBytes: 2 + 4 + 2,
    });
    const next = emitPage("s", "ab😀cd", 6, "2");
    expect(next).toMatchObject({ body: "😀cd", emittedBytes: 6, nextCursor: "" });
  });

  it("빈 원본은 단일 빈 페이지 — 합법", () => {
    expect(emitPage("s", "", 10, "")).toMatchObject({
      body: "", nextCursor: "", totalBytes: 0, remainingBytes: 0,
    });
  });

  it("offset == totalChars 커서는 합법인 끝 읽기", () => {
    expect(emitPage("s", "abc", 8, "3")).toMatchObject({ body: "", nextCursor: "" });
  });

  it("guard_defect: cap < 4바이트(최대 코드포인트)는 fail-closed — 진행 보장 하한", () => {
    for (const cap of [0, 3, -1, 4.5, Number.NaN]) {
      expect(emitPage("s", "abc", cap, "")).toEqual({
        _tag: "invalid_page", reason: "cap_below_min4_or_non_integer",
      });
    }
  });

  it("guard_defect: 무효 커서(비정수·음수·범위 밖)는 fail-closed", () => {
    for (const cursor of ["abc", "-1", "1.5", "4", "1e2"]) {
      expect(emitPage("s", "abc", 8, cursor)).toEqual({
        _tag: "invalid_page", reason: "invalid_cursor",
      });
    }
  });

  it("guard_defect: 비정준 표기 커서는 값이 범위 안이어도 거부 — 한 개념 한 표현 (왕복 검사)", () => {
    for (const cursor of ["07", "+5", " 5", "5 ", "0x5", "5e0", "-0"]) {
      expect(emitPage("s", "abcdefghij", 8, cursor)).toEqual({
        _tag: "invalid_page", reason: "invalid_cursor",
      });
    }
    expect(emitPage("s", "abcdefghij", 8, "5")).toMatchObject({ _tag: "ToolPage", offsetChars: 5 });
  });

  it("guard_defect: 서로게이트 쌍 한가운데를 가리키는 커서는 거부", () => {
    expect(emitPage("s", "a😀b", 8, "2")).toEqual({
      _tag: "invalid_page", reason: "invalid_cursor",
    });
  });
});
