/** Scenario EVENT-ID: 안정 이벤트 식별 he-sha — Python reconcile.history_event_id 와 바이트 동일.
 * guard_mechanism: 실 Python(.venv, lakatos.io.reconcile) 생성 픽스처 6종 일치 —
 *   한글·따옴표/역슬래시 이스케이프·빈 문자열·64hex 경계 포함 (교차 언어 파리티 핀).
 * guard_defect: 성분 하나만 달라져도 다른 id, 형식 ^he-[0-9a-f]{64}$ 고정, 헤더 상수 핀. */
import { describe, expect, it } from "vitest";
import { HISTORY_EVENT_DOMAIN, historyEventId } from "../../src/domain/eventlog.ts";

/** .venv/bin/python -c "from lakatos.io.reconcile import history_event_id; ..." 로 생성 (2026-08-11). */
const PYTHON_ORACLE: readonly (readonly [string, string, string, string])[] = [
  ["HSWM", "critique", "HSWM/arg-1",
    "he-80521ae8330ce3052b4ffa90703175892d9f34c49cdd78274f0499e1cf110f3d"],
  ["한글트리", "node", "한글트리/노드-α",
    "he-3e01d90d7f7e6824d51c7e2bdbbd197a333bbe146884e71b6450adbff6f04f3a"],
  ["t", "", "",
    "he-e89e3d82adc24a88a9f7aa941b28d2d1cca3de4f6cf6dabf2c23128ec740a8f2"],
  ['tree-with-"quote"', "op\\slash", "s/♥",
    "he-0daa624420cfc1ecf2ac7e7b0d1a7237eba18e3c164ed50c50dfd601b8ee8c7e"],
  ["LakatoTree_TemporalWitnessProbe_20260723", "cycle_result", "deadbeef".repeat(8),
    "he-a8f6b4d813c23671ef366fbc1c2c315e2668df08e619e1a05a6987edcc9c4709"],
  // NUL 은 Python 이 id 를 만든다 (\u0000 이스케이프 후 해시) — 파리티 유지
  ["t\u0000ree", "op", "s",
    "he-f88a4ccaeff48b830876afea99c786d0cd8111278077ea30caac66d53556a473"],
];

describe("Scenario EVENT-ID", () => {
  it("guard_mechanism: Python 오라클 픽스처 6종과 바이트 동일", () => {
    for (const [tree, op, subjectId, expected] of PYTHON_ORACLE) {
      expect(historyEventId(tree, op, subjectId)).toBe(expected);
    }
  });

  it("guard_defect: 도메인 헤더는 조문 상수 — 바꾸면 전 픽스처 RED", () => {
    expect(HISTORY_EVENT_DOMAIN).toBe("lakatotree-history-event-v1");
  });

  it("guard_defect: 성분 하나만 달라져도 다른 id (충돌 없는 판별)", () => {
    const base = historyEventId("HSWM", "critique", "HSWM/arg-1");
    expect(historyEventId("HSWM2", "critique", "HSWM/arg-1")).not.toBe(base);
    expect(historyEventId("HSWM", "critique2", "HSWM/arg-1")).not.toBe(base);
    expect(historyEventId("HSWM", "critique", "HSWM/arg-2")).not.toBe(base);
    // 성분 경계 이동(tree 끝 vs op 앞)도 다른 id — 연접이 아니라 JSON 배열이라 구분된다
    expect(historyEventId("HSWMc", "ritique", "HSWM/arg-1")).not.toBe(base);
  });

  it("guard_defect: 형식은 he-<64 lowercase hex> 고정", () => {
    for (const [tree, op, subjectId] of PYTHON_ORACLE) {
      expect(historyEventId(tree, op, subjectId)).toMatch(/^he-[0-9a-f]{64}$/);
    }
  });

  it("결정론: 같은 입력 → 같은 id (리플레이 안정)", () => {
    const a = historyEventId("한글트리", "node", "한글트리/노드-α");
    expect(historyEventId("한글트리", "node", "한글트리/노드-α")).toBe(a);
  });

  it("guard_defect: lone surrogate 는 오류 값 — Python 은 raise, TS 는 값 (무음 U+FFFD 대체 금지)", () => {
    // TextEncoder 는 lone surrogate 를 조용히 U+FFFD 로 바꿔 Python 과 다른 해시를 만든다 —
    // 그 경로가 존재하면 파리티 위장 green. 세 성분 모두에서 선검출 거부해야 한다.
    for (const bad of ["t\ud800ree", "\udfff", "pair\ud800"]) {
      expect(historyEventId(bad, "op", "s")).toMatchObject({ _tag: "event_id_error", reason: "lone_surrogate" });
      expect(historyEventId("t", bad, "s")).toMatchObject({ _tag: "event_id_error", reason: "lone_surrogate" });
      expect(historyEventId("t", "op", bad)).toMatchObject({ _tag: "event_id_error", reason: "lone_surrogate" });
    }
    // 정상 서로게이트 쌍(이모지)은 통과한다 — 과잉 거부 금지
    expect(typeof historyEventId("tree-🌳", "op", "s")).toBe("string");
  });
});
