CREATE TABLE IF NOT EXISTS history(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  op TEXT NOT NULL,
  node_tag TEXT,
  payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_history_tree_ts ON history(tree, ts DESC);
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
