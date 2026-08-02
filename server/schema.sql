CREATE TABLE IF NOT EXISTS public.history(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  op TEXT NOT NULL,
  node_tag TEXT,
  payload JSONB,
  CONSTRAINT ck_history_critique_identity CHECK (
    op <> 'critique' OR (
      payload IS NOT NULL
      AND jsonb_typeof(payload)='object'
      AND payload ? 'arg_id'
      AND jsonb_typeof(payload->'arg_id')='string'
      AND payload->>'arg_id' <> ''
      AND strpos(payload->>'arg_id','/')=0
    )
  )
);
CREATE INDEX IF NOT EXISTS idx_history_tree_ts ON public.history(tree, ts DESC);
-- B1(override 2026-06-21): reconcile_outbox 멱등 재적용 키. 과거 정상 hist 는 event_id=NULL,
-- 과거 outbox 재적용분은 ob-*; 신규 stable append 는 he-*다. 이미 적힌 history 행은 바꾸지 않는다.
ALTER TABLE public.history ADD COLUMN IF NOT EXISTS event_id TEXT;
-- Keep NULL/ob-* compatible until a new writer adopts them as stable he-* rows.
-- This makes a failed cross-store cutover safely resumable after the drain lease.
DO $stable_event_gate$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='public.history'::regclass
      AND conname='ck_history_new_critique_stable_event'
  ) THEN
    ALTER TABLE public.history
      ADD CONSTRAINT ck_history_new_critique_stable_event
      CHECK (
        op <> 'critique' OR event_id IS NULL
        OR event_id ~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'
      ) NOT VALID;
  END IF;
END
$stable_event_gate$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_history_event_id ON public.history(event_id) WHERE event_id IS NOT NULL;
-- One immutable critique identity (tree/arg_id) can project to at most one append-only row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_history_critique_logical_identity
  ON public.history(tree, (payload->>'arg_id')) WHERE op='critique';
-- Stable logical identities may adopt an exact legacy NULL/ob-* row without rewriting history.
-- The claim table is append-only too: one stable event per history row and one row per stable event.
CREATE TABLE IF NOT EXISTS public.history_event_claims(
  stable_event_id TEXT PRIMARY KEY,
  history_id BIGINT NOT NULL UNIQUE REFERENCES public.history(id),
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.metric_snapshots(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  metrics JSONB
);
CREATE TABLE IF NOT EXISTS public.lineage(
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  output TEXT NOT NULL, output_sha TEXT, producer TEXT, producer_sha TEXT,
  inputs JSONB, params JSONB, kind TEXT, env TEXT
);
CREATE INDEX IF NOT EXISTS idx_lineage_output ON public.lineage(output);
