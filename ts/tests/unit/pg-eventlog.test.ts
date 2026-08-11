/** Scenario PG-EVENTLOG: append-only 감사 투영 어댑터 — he-sha 멱등, 유계 읽기, 오류=값.
 * guard_mechanism: INSERT ... ON CONFLICT (event_id) DO NOTHING + 파라미터 정확성(가짜 포트 캡처),
 *   rowCount 1→inserted / 0→멱등 재적용, canonicalHistoryPayload 는 Python
 *   reconcile.canonical_history_payload 실측 픽스처와 문자열 동일.
 * guard_defect: NUL·lone surrogate 페이로드는 포트 미호출 로컬 거부(오염된 durable intent 선차단 —
 *   reconcile.py 교훈 '투영 시점 검증은 영구 오염을 남긴다'), 포트 예외는 pg_error 값(throw 없음),
 *   readSince limit 은 [1,500] 강제 클램프(무제한 읽기 표현 불가). */
import { describe, expect, it } from "vitest";
import { canonicalHistoryPayload } from "../../src/domain/eventlog.ts";
import {
  READ_LIMIT_MAX,
  appendEvent,
  readSince,
  type SqlPort,
} from "../../src/adapters/pgeventlog.ts";

interface Captured {
  text: string;
  params: readonly (string | number | null)[];
}

const fakePort = (
  result: { rowCount: number | null; rows: readonly Record<string, unknown>[] },
  captured: Captured[],
): SqlPort => ({
  query: (text, params) => {
    captured.push({ text, params });
    return Promise.resolve(result);
  },
});

const intent = {
  tree: "한글트리",
  op: "node",
  subjectId: "한글트리/노드-α",
  payload: { b: 1, a: { "한": 2 }, arr: [1, "x", null], neg: -5, flag: true },
} as const;

/** .venv reconcile.canonical_history_payload 실측 (2026-08-11). */
const PYTHON_CANONICAL = '{"a":{"한":2},"arr":[1,"x",null],"b":1,"flag":true,"neg":-5}';

describe("Scenario PG-EVENTLOG", () => {
  it("guard_mechanism: 페이로드 정준화는 Python 오라클과 문자열 동일", () => {
    expect(canonicalHistoryPayload(intent.payload)).toBe(PYTHON_CANONICAL);
  });

  it("guard_defect: NUL·lone surrogate 는 값·키 모두 로컬 거부 (Python REJECT 파리티)", () => {
    expect(canonicalHistoryPayload({ k: "a\u0000b" }))
      .toMatchObject({ _tag: "payload_error", reason: "nul_not_representable", path: "/k" });
    expect(canonicalHistoryPayload({ k: "\ud800" }))
      .toMatchObject({ _tag: "payload_error", reason: "lone_surrogate", path: "/k" });
    expect(canonicalHistoryPayload({ "a\u0000": 1 }))
      .toMatchObject({ _tag: "payload_error", reason: "nul_not_representable" });
    // TS 는 정수만 — float 는 Python 보다 엄격한 부분집합 (canonical.ts 규율, 문서화된 분기)
    expect(canonicalHistoryPayload({ f: 1.5 }))
      .toMatchObject({ _tag: "payload_error", reason: "non_canonical" });
  });

  it("guard_mechanism: appendEvent — ON CONFLICT 멱등 INSERT + 정확한 파라미터", async () => {
    const captured: Captured[] = [];
    const port = fakePort({ rowCount: 1, rows: [] }, captured);
    const result = await appendEvent(port, intent);
    expect(result).toMatchObject({ inserted: true });
    if ("_tag" in result) throw new Error("unexpected error");
    expect(result.eventId).toMatch(/^he-[0-9a-f]{64}$/);
    expect(captured).toHaveLength(1);
    const call = captured[0];
    if (call === undefined) throw new Error("no capture");
    expect(call.text).toContain("INSERT INTO public.ts_history");
    expect(call.text).toContain("ON CONFLICT (event_id) DO NOTHING");
    expect(call.params).toEqual([
      intent.tree, intent.op, intent.subjectId, PYTHON_CANONICAL, result.eventId,
    ]);
  });

  it("guard_mechanism: rowCount 0 = 멱등 재적용 (inserted=false, 오류 아님)", async () => {
    const port = fakePort({ rowCount: 0, rows: [] }, []);
    expect(await appendEvent(port, intent)).toMatchObject({ inserted: false });
  });

  it("guard_defect: 무효 페이로드는 포트 미호출 — 오염 durable intent 선차단", async () => {
    const captured: Captured[] = [];
    const port = fakePort({ rowCount: 1, rows: [] }, captured);
    const result = await appendEvent(port, { ...intent, payload: { k: "a\u0000b" } });
    expect(result).toMatchObject({ _tag: "payload_error" });
    expect(captured).toHaveLength(0);
  });

  it("guard_defect: 포트 예외도 값으로 — throw 없는 어댑터", async () => {
    const port: SqlPort = { query: () => Promise.reject(new Error("connection refused")) };
    expect(await appendEvent(port, intent)).toMatchObject({ _tag: "pg_error" });
  });

  it("guard_mechanism: readSince — 커서 이후 유계 읽기, id 오름차순", async () => {
    const captured: Captured[] = [];
    const rows = [{ id: "7", tree: "t", op: "node", subject_id: "s", event_id: "he-" + "0".repeat(64), payload_text: "{}" }];
    const port = fakePort({ rowCount: 1, rows }, captured);
    const result = await readSince(port, 6, 10);
    if ("_tag" in result) throw new Error("unexpected error");
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: 7, tree: "t", eventId: "he-" + "0".repeat(64) });
    const call = captured[0];
    if (call === undefined) throw new Error("no capture");
    expect(call.text).toContain("ORDER BY id ASC");
    expect(call.params).toEqual([6, 10]);
  });

  it("guard_defect: limit 은 [1,500] 클램프 — 무제한 읽기가 표현 불가", async () => {
    const captured: Captured[] = [];
    const port = fakePort({ rowCount: 0, rows: [] }, captured);
    await readSince(port, 0, 99999);
    await readSince(port, 0, 0);
    await readSince(port, 0, -3);
    expect(captured.map((c) => c.params[1])).toEqual([READ_LIMIT_MAX, 1, 1]);
    expect(READ_LIMIT_MAX).toBe(500);
  });
});
