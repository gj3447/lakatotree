-- lakatotree-ts append-only 감사 투영 v0 — Python public.history 형태 계승.
-- 멱등 키 = he-sha (domain/eventlog.historyEventId, Python reconcile.history_event_id 파리티).
-- append-only: 기존 행 재작성 금지 — 재적용은 ON CONFLICT (event_id) DO NOTHING 으로 무해.
CREATE TABLE IF NOT EXISTS public.ts_history (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  op TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  event_id TEXT NOT NULL,
  CONSTRAINT ck_ts_history_event_id CHECK (event_id ~ '^he-[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ts_history_event_id ON public.ts_history (event_id);
CREATE INDEX IF NOT EXISTS idx_ts_history_tree ON public.ts_history (tree, id);
