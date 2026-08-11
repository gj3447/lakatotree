/** Scenario PG-EVENTLOG-INT: 실 PG 왕복 — LAKATOS_TS_PG_DSN 설정 시에만 실행
 * (hermetic-skip 관례, CLAUDE.md §4 — dev-box 자원 결합 테스트는 경로/env 부재 시 skip).
 * DSN 은 일회용 테스트 DB 를 가리켜야 한다 (테스트가 자기 tree 행을 정리한다).
 * 검증: DDL(IF NOT EXISTS) → 같은 intent 2회 append (2회째 inserted=false = ON CONFLICT
 * 멱등 실증 — 가짜 포트로는 불가능한 실 DB 거동) → 유계 readSince 왕복. */
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { appendEvent, readSince, type SqlPort } from "../../src/adapters/pgeventlog.ts";

const DSN = process.env["LAKATOS_TS_PG_DSN"] ?? "";

describe.skipIf(DSN === "")("Scenario PG-EVENTLOG-INT", () => {
  it("실 PG: DDL → 멱등 append 2회 → 유계 readSince", async () => {
    const { default: pg } = await import("pg");
    const pool = new pg.Pool({ connectionString: DSN, max: 1 });
    const port: SqlPort = {
      query: async (text, params) => {
        const result = await pool.query(text, [...params]);
        return { rowCount: result.rowCount, rows: result.rows as Record<string, unknown>[] };
      },
    };
    try {
      const here = dirname(fileURLToPath(import.meta.url));
      const ddl = await readFile(join(here, "..", "..", "sql", "ts_history.v0.sql"), "utf8");
      await pool.query(ddl);
      const tree = `int-test-${process.pid}-${Date.now()}`;
      const intent = { tree, op: "node", subjectId: `${tree}/n1`, payload: { v: 1, "한": "값" } };
      const first = await appendEvent(port, intent);
      expect(first).toMatchObject({ inserted: true });
      const second = await appendEvent(port, intent);
      expect(second).toMatchObject({ inserted: false });
      if ("_tag" in first) throw new Error("unexpected");
      const rows = await readSince(port, 0, 500);
      if ("_tag" in rows) throw new Error(rows.detail);
      const mine = rows.filter((row) => row.tree === tree);
      expect(mine).toHaveLength(1);
      expect(mine[0]).toMatchObject({ eventId: first.eventId, subjectId: `${tree}/n1` });
      await pool.query("DELETE FROM public.ts_history WHERE tree = $1", [tree]);
    } finally {
      await pool.end();
    }
  });
});
