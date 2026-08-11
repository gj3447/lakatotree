/** Scenario CANONICAL-SORT: 정준 키 정렬 = 유니코드 코드포인트 순 — Python json.dumps(sort_keys=True)
 * 파리티. guard_defect(제3자 리뷰 실결함 재현): astral 키(U+10000)와 U+FFFF 가 공존하면 JS 기본
 * sort(UTF-16 코드유닛 순)는 U+10000(서로게이트 D800 시작)을 U+FFFF 앞에 놓아 Python 과 다른
 * 정준 바이트/sha 를 만든다. 정본 선택 명시: RFC 8785(JCS)는 UTF-16 순이 표준이지만 이 repo 의
 * 정본은 Python 오라클 파리티다. 픽스처는 .venv reconcile 실측 (2026-08-11). */
import { describe, expect, it } from "vitest";
import { canonicalHistoryPayload } from "../../src/domain/eventlog.ts";

describe("Scenario CANONICAL-SORT", () => {
  it("guard_defect: U+FFFF vs U+10000 키 순서 — Python 실측 정준 문자열과 동일", () => {
    const payload = { "￿": 1, "\u{10000}": 2, z: 3, "가": 4 };
    // Python: {"z":3,"가":4,"￿":1,"𐀀":2}
    expect(canonicalHistoryPayload(payload)).toBe('{"z":3,"가":4,"￿":1,"\u{10000}":2}');
  });

  it("guard_mechanism: BMP 전용 키는 기존 정렬과 동일 (회귀 없음)", () => {
    expect(canonicalHistoryPayload({ b: 1, a: 2, "한": 3 })).toBe('{"a":2,"b":1,"한":3}');
  });
});
