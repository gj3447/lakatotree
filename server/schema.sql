CREATE TABLE IF NOT EXISTS history(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  op TEXT NOT NULL,
  node_tag TEXT,
  payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_history_tree_ts ON history(tree, ts DESC);
-- B1(override 2026-06-21): reconcile_outbox 멱등 재적용 키. 정상 hist 는 event_id=NULL(append-only),
-- KG OutboxEntry 재적용분만 event_id 채워 ON CONFLICT DO NOTHING 으로 이중적재 차단(부분 unique).
ALTER TABLE history ADD COLUMN IF NOT EXISTS event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_history_event_id ON history(event_id) WHERE event_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS metric_snapshots(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  metrics JSONB
);
CREATE TABLE IF NOT EXISTS lineage(
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  output TEXT NOT NULL, output_sha TEXT, producer TEXT, producer_sha TEXT,
  inputs JSONB, params JSONB, kind TEXT, env TEXT
);
CREATE INDEX IF NOT EXISTS idx_lineage_output ON lineage(output);
