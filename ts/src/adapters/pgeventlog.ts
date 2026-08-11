/** PG append-only 이벤트로그 어댑터 — 스키마 정본은 ts/sql/ts_history.v0.sql.
 * 멱등 = he-sha 키에 ON CONFLICT DO NOTHING (reconcile_outbox 관례 계승 — 재적용 무해),
 * append-only: UPDATE/DELETE 문이 이 어댑터에 존재하지 않는다 (재작성 표현 불가).
 * 읽기는 유계 강제 (READ_LIMIT_MAX 클램프 — 무제한 읽기 표현 불가). 오류 전부 값, throw 없음.
 * SqlPort 는 pg.Pool 과 구조 일치 — 드라이버는 통합 테스트/엔트리포인트에서만 주입한다. */
import type { CanonicalValue } from "../contracts/canonical.ts";
import {
  canonicalHistoryPayload,
  historyEventId,
  type EventIdError,
  type PayloadError,
} from "../domain/eventlog.ts";

export interface SqlResult {
  readonly rowCount: number | null;
  readonly rows: readonly Record<string, unknown>[];
}

export interface SqlPort {
  readonly query: (
    text: string,
    params: readonly (string | number | null)[],
  ) => Promise<SqlResult>;
}

export interface AppendIntent {
  readonly tree: string;
  readonly op: string;
  readonly subjectId: string;
  readonly payload: CanonicalValue;
}

export interface AppendOutcome {
  readonly eventId: string;
  readonly inserted: boolean;
}

export type PgError = { readonly _tag: "pg_error"; readonly detail: string };

export const READ_LIMIT_MAX = 500;

const pgError = (cause: unknown): PgError => ({
  _tag: "pg_error",
  detail: cause instanceof Error ? cause.message.slice(0, 200) : "unknown",
});

const APPEND_SQL = `INSERT INTO public.ts_history (tree, op, subject_id, payload, event_id)
VALUES ($1, $2, $3, $4::jsonb, $5)
ON CONFLICT (event_id) DO NOTHING`;

export const appendEvent = async (
  port: SqlPort,
  intent: AppendIntent,
): Promise<AppendOutcome | EventIdError | PayloadError | PgError> => {
  const payloadText = canonicalHistoryPayload(intent.payload);
  if (typeof payloadText !== "string") return payloadText;
  const eventId = historyEventId(intent.tree, intent.op, intent.subjectId);
  if (typeof eventId !== "string") return eventId;
  try {
    const result = await port.query(APPEND_SQL, [
      intent.tree, intent.op, intent.subjectId, payloadText, eventId,
    ]);
    return { eventId, inserted: result.rowCount === 1 };
  } catch (cause) {
    return pgError(cause);
  }
};

export interface HistoryRow {
  readonly id: number;
  readonly tree: string;
  readonly op: string;
  readonly subjectId: string;
  readonly eventId: string;
  readonly payloadText: string;
}

const READ_SQL = `SELECT id, tree, op, subject_id, payload::text AS payload_text, event_id
FROM public.ts_history WHERE id > $1 ORDER BY id ASC LIMIT $2`;

export const readSince = async (
  port: SqlPort,
  afterId: number,
  limit: number,
): Promise<readonly HistoryRow[] | PgError> => {
  const bounded = Math.min(READ_LIMIT_MAX, Math.max(1, Math.trunc(limit)));
  try {
    const result = await port.query(READ_SQL, [afterId, bounded]);
    return result.rows.map((row) => ({
      id: Number(row["id"]),
      tree: String(row["tree"] ?? ""),
      op: String(row["op"] ?? ""),
      subjectId: String(row["subject_id"] ?? ""),
      eventId: String(row["event_id"] ?? ""),
      payloadText: String(row["payload_text"] ?? ""),
    }));
  } catch (cause) {
    return pgError(cause);
  }
};
