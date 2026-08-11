/** Scenario BOUND-EMIT: AI-facing 방출은 구조적으로 유계 — 자르되 잘린 양을 공시한다.
 * 선례 승격: fsck findings[:500]+truncated 카운터 (server/app.py:1202). 실측 근거: get_tree
 * 단일 응답 733,838B(≈18만 토큰) — 무제한 방출이 토큰 폭식의 1번 표면 (진단 2026-08-11). */
import { describe, expect, it } from "vitest";
import { boundList, boundText } from "../../src/domain/bound.ts";

const INVALID_CAPS = [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 53];

describe("boundList", () => {
  it("guard_defect: 무효 cap(0·음수·비정수)은 fail-closed 오류 값 — 조용히 열리는 무제한 경로 없음", () => {
    for (const cap of INVALID_CAPS) {
      expect(boundList([1, 2, 3], cap)).toEqual({
        _tag: "invalid_cap",
        reason: "non_positive_or_non_integer_cap",
      });
    }
  });

  it("guard_mechanism: prefix 보존 + truncated 정확 공시 + cap 자기 공시", () => {
    expect(boundList(["a", "b", "c", "d", "e"], 3)).toEqual({
      _tag: "BoundedList",
      cap: 3,
      items: ["a", "b", "c"],
      truncated: 2,
    });
  });

  it("cap 이상이면 무손실 — truncated 0", () => {
    expect(boundList(["a"], 5)).toEqual({
      _tag: "BoundedList",
      cap: 5,
      items: ["a"],
      truncated: 0,
    });
  });
});

describe("boundText", () => {
  it("guard_defect: 무효 cap 은 동일한 fail-closed 오류 값", () => {
    for (const cap of INVALID_CAPS) {
      expect(boundText("abc", cap)).toEqual({
        _tag: "invalid_cap",
        reason: "non_positive_or_non_integer_cap",
      });
    }
  });

  it("guard_mechanism: prefix 보존 + truncatedChars 정확 공시", () => {
    expect(boundText("가나다라마", 2)).toEqual({
      _tag: "BoundedText",
      cap: 2,
      text: "가나",
      truncatedChars: 3,
    });
  });
});
