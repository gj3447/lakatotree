-- Exact, additive/fresh PostgreSQL migration for critique-history storage v1.
-- The installable predeploy coordinator supplies a bounded statement/lock timeout,
-- validates a target-bound drain receipt at every boundary, and performs exhaustive
-- cross-store readback before publishing a receipt.

BEGIN;
SELECT pg_advisory_xact_lock(497116920260802001);

CREATE TABLE IF NOT EXISTS public.history(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  op TEXT NOT NULL,
  node_tag TEXT,
  payload JSONB,
  event_id TEXT,
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

CREATE TABLE IF NOT EXISTS public.metric_snapshots(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  tree TEXT NOT NULL,
  metrics JSONB
);

CREATE TABLE IF NOT EXISTS public.lineage(
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  output TEXT NOT NULL,
  output_sha TEXT,
  producer TEXT,
  producer_sha TEXT,
  inputs JSONB,
  params JSONB,
  kind TEXT,
  env TEXT
);

LOCK TABLE public.metric_snapshots, public.lineage
  IN SHARE ROW EXCLUSIVE MODE;

DO $auxiliary_shape$
DECLARE
  metric_shape text[];
  lineage_shape text[];
  metric_keys text[];
  lineage_keys text[];
  seq_last bigint;
  seq_called boolean;
  max_id bigint;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.metric_snapshots'::regclass
      AND relkind='r' AND relpersistence='p'
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.lineage'::regclass
      AND relkind='r' AND relpersistence='p'
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid=to_regclass('public.metric_snapshots_id_seq')
      AND relkind='S' AND relpersistence='p'
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid=to_regclass('public.lineage_id_seq')
      AND relkind='S' AND relpersistence='p'
  ) THEN
    RAISE EXCEPTION 'auxiliary storage objects must be permanent ordinary storage';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid IN ('public.metric_snapshots'::regclass,
                  'public.lineage'::regclass)
      AND (relhassubclass OR relispartition)
  ) OR EXISTS (
    SELECT 1 FROM pg_inherits
    WHERE inhparent IN ('public.metric_snapshots'::regclass,
                        'public.lineage'::regclass)
       OR inhrelid IN ('public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)
  ) THEN
    RAISE EXCEPTION 'auxiliary storage tables must not participate in inheritance';
  END IF;

  SELECT array_agg(
           a.attname || ':' || format_type(a.atttypid,a.atttypmod) || ':' ||
           CASE WHEN a.attnotnull THEN 'not-null' ELSE 'nullable' END || ':' ||
           coalesce(regexp_replace(lower(pg_get_expr(d.adbin,d.adrelid)),
                                   '[[:space:]]', '', 'g'), '') || ':' ||
           coalesce(a.attidentity::text, '') || ':' ||
           coalesce(a.attgenerated::text, '')
           ORDER BY a.attnum
         ) INTO metric_shape
  FROM pg_attribute AS a
  LEFT JOIN pg_attrdef AS d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid='public.metric_snapshots'::regclass
    AND a.attnum>0 AND NOT a.attisdropped;
  IF array_length(metric_shape,1) <> 4
     OR metric_shape[1] !~ '^id:bigint:not-null:nextval[(]''(public[.])?metric_snapshots_id_seq''::regclass[)]::$'
     OR metric_shape[2] <> 'ts:timestamp with time zone:not-null:now()::'
     OR metric_shape[3] <> 'tree:text:not-null:::'
     OR metric_shape[4] <> 'metrics:jsonb:nullable:::'
  THEN
    RAISE EXCEPTION 'public.metric_snapshots column shape mismatch: %', metric_shape;
  END IF;

  SELECT array_agg(
           a.attname || ':' || format_type(a.atttypid,a.atttypmod) || ':' ||
           CASE WHEN a.attnotnull THEN 'not-null' ELSE 'nullable' END || ':' ||
           coalesce(regexp_replace(lower(pg_get_expr(d.adbin,d.adrelid)),
                                   '[[:space:]]', '', 'g'), '') || ':' ||
           coalesce(a.attidentity::text, '') || ':' ||
           coalesce(a.attgenerated::text, '')
           ORDER BY a.attnum
         ) INTO lineage_shape
  FROM pg_attribute AS a
  LEFT JOIN pg_attrdef AS d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid='public.lineage'::regclass
    AND a.attnum>0 AND NOT a.attisdropped;
  IF array_length(lineage_shape,1) <> 10
     OR lineage_shape[1] !~ '^id:bigint:not-null:nextval[(]''(public[.])?lineage_id_seq''::regclass[)]::$'
     OR lineage_shape[2] <> 'ts:timestamp with time zone:not-null:now()::'
     OR lineage_shape[3] <> 'output:text:not-null:::'
     OR lineage_shape[4] <> 'output_sha:text:nullable:::'
     OR lineage_shape[5] <> 'producer:text:nullable:::'
     OR lineage_shape[6] <> 'producer_sha:text:nullable:::'
     OR lineage_shape[7] <> 'inputs:jsonb:nullable:::'
     OR lineage_shape[8] <> 'params:jsonb:nullable:::'
     OR lineage_shape[9] <> 'kind:text:nullable:::'
     OR lineage_shape[10] <> 'env:text:nullable:::'
  THEN
    RAISE EXCEPTION 'public.lineage column shape mismatch: %', lineage_shape;
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_attribute AS a
    WHERE a.attrelid IN ('public.metric_snapshots'::regclass,
                         'public.lineage'::regclass)
      AND a.attnum>0 AND NOT a.attisdropped
      AND a.attcollation<>0
      AND a.attcollation<>'pg_catalog.default'::regcollation
  ) THEN
    RAISE EXCEPTION 'auxiliary storage has a non-default column collation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid IN ('public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)
      AND contype='c'
  ) THEN
    RAISE EXCEPTION 'unexpected auxiliary storage CHECK constraint';
  END IF;

  SELECT array_agg(
           c.conname || ':' || c.contype::text || ':' ||
           c.convalidated::text || ':' || c.condeferrable::text || ':' ||
           c.condeferred::text || ':' || array_to_string(c.conkey, ',')
           ORDER BY c.conname
         ) INTO metric_keys
  FROM pg_constraint AS c
  WHERE c.conrelid='public.metric_snapshots'::regclass
    AND c.contype IN ('p','u','f','x');
  IF metric_keys <> ARRAY[
       'metric_snapshots_pkey:p:true:false:false:' ||
       (SELECT attnum::text FROM pg_attribute
        WHERE attrelid='public.metric_snapshots'::regclass AND attname='id')
     ] THEN
    RAISE EXCEPTION 'public.metric_snapshots key shape mismatch: %', metric_keys;
  END IF;
  SELECT array_agg(
           c.conname || ':' || c.contype::text || ':' ||
           c.convalidated::text || ':' || c.condeferrable::text || ':' ||
           c.condeferred::text || ':' || array_to_string(c.conkey, ',')
           ORDER BY c.conname
         ) INTO lineage_keys
  FROM pg_constraint AS c
  WHERE c.conrelid='public.lineage'::regclass
    AND c.contype IN ('p','u','f','x');
  IF lineage_keys <> ARRAY[
       'lineage_pkey:p:true:false:false:' ||
       (SELECT attnum::text FROM pg_attribute
        WHERE attrelid='public.lineage'::regclass AND attname='id')
     ] THEN
    RAISE EXCEPTION 'public.lineage key shape mismatch: %', lineage_keys;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_sequences AS s
    WHERE s.schemaname='public'
      AND s.sequencename='metric_snapshots_id_seq'
      AND s.data_type='bigint'::regtype AND s.start_value=1 AND s.min_value=1
      AND s.max_value=9223372036854775807 AND s.increment_by=1
      AND s.cycle IS FALSE AND s.cache_size=1
      AND pg_get_serial_sequence('public.metric_snapshots','id') IN (
        'metric_snapshots_id_seq', 'public.metric_snapshots_id_seq'
      )
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_sequences AS s
    WHERE s.schemaname='public' AND s.sequencename='lineage_id_seq'
      AND s.data_type='bigint'::regtype AND s.start_value=1 AND s.min_value=1
      AND s.max_value=9223372036854775807 AND s.increment_by=1
      AND s.cycle IS FALSE AND s.cache_size=1
      AND pg_get_serial_sequence('public.lineage','id') IN (
        'lineage_id_seq', 'public.lineage_id_seq'
      )
  ) THEN
    RAISE EXCEPTION 'auxiliary id sequence is not exact/owned BIGSERIAL';
  END IF;

  SELECT max(id) INTO max_id FROM public.metric_snapshots;
  IF max_id = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.metric_snapshots id space is exhausted';
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.metric_snapshots_id_seq;
  IF max_id IS NOT NULL
     AND (seq_last < max_id OR (seq_last=max_id AND NOT seq_called)) THEN
    PERFORM setval('public.metric_snapshots_id_seq'::regclass, max_id, true);
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.metric_snapshots_id_seq;
  IF seq_called AND seq_last = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.metric_snapshots id sequence is exhausted';
  END IF;

  SELECT max(id) INTO max_id FROM public.lineage;
  IF max_id = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.lineage id space is exhausted';
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.lineage_id_seq;
  IF max_id IS NOT NULL
     AND (seq_last < max_id OR (seq_last=max_id AND NOT seq_called)) THEN
    PERFORM setval('public.lineage_id_seq'::regclass, max_id, true);
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.lineage_id_seq;
  IF seq_called AND seq_last = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.lineage id sequence is exhausted';
  END IF;
END
$auxiliary_shape$;

LOCK TABLE public.history IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE public.history ADD COLUMN IF NOT EXISTS event_id TEXT;

DO $history_persistence$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.history'::regclass
      AND relkind='r' AND relpersistence='p'
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.history_id_seq'::regclass
      AND relkind='S' AND relpersistence='p'
  ) THEN
    RAISE EXCEPTION 'critique-history objects must be permanent ordinary storage';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.history'::regclass
      AND (relhassubclass OR relispartition)
  ) OR EXISTS (
    SELECT 1 FROM pg_inherits
    WHERE inhparent='public.history'::regclass
       OR inhrelid='public.history'::regclass
  ) THEN
    RAISE EXCEPTION 'critique-history tables must not participate in inheritance';
  END IF;
END
$history_persistence$;

DO $history_shape$
DECLARE
  shape text[];
  key_shape text[];
  seq_last bigint;
  seq_called boolean;
  max_id bigint;
BEGIN
  SELECT array_agg(
           a.attname || ':' || format_type(a.atttypid,a.atttypmod) || ':' ||
           CASE WHEN a.attnotnull THEN 'not-null' ELSE 'nullable' END || ':' ||
           coalesce(regexp_replace(lower(pg_get_expr(d.adbin,d.adrelid)),
                                   '[[:space:]]', '', 'g'), '') || ':' ||
           coalesce(a.attidentity::text, '') || ':' ||
           coalesce(a.attgenerated::text, '')
           ORDER BY a.attnum
         ) INTO shape
  FROM pg_attribute AS a
  LEFT JOIN pg_attrdef AS d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid='public.history'::regclass
    AND a.attnum>0 AND NOT a.attisdropped;

  IF array_length(shape,1) <> 7
     OR shape[1] !~ '^id:bigint:not-null:nextval[(]''(public[.])?history_id_seq''::regclass[)]::$'
     OR shape[2] <> 'ts:timestamp with time zone:not-null:now()::'
     OR shape[3] <> 'tree:text:not-null:::'
     OR shape[4] <> 'op:text:not-null:::'
     OR shape[5] <> 'node_tag:text:nullable:::'
     OR shape[6] <> 'payload:jsonb:nullable:::'
     OR shape[7] <> 'event_id:text:nullable:::'
  THEN
    RAISE EXCEPTION 'public.history column shape mismatch: %', shape;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_attribute AS a
    WHERE a.attrelid='public.history'::regclass
      AND a.attnum>0 AND NOT a.attisdropped
      AND a.attcollation<>0
      AND a.attcollation<>'pg_catalog.default'::regcollation
  ) THEN
    RAISE EXCEPTION 'public.history has a non-default column collation';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_sequences AS s
    WHERE s.schemaname='public' AND s.sequencename='history_id_seq'
      AND s.data_type='bigint'::regtype AND s.start_value=1 AND s.min_value=1
      AND s.max_value=9223372036854775807 AND s.increment_by=1
      AND s.cycle IS FALSE AND s.cache_size=1
      AND pg_get_serial_sequence('public.history','id') IN (
        'history_id_seq', 'public.history_id_seq'
      )
  ) THEN
    RAISE EXCEPTION 'public.history id sequence is not exact/owned BIGSERIAL';
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.history_id_seq;
  SELECT max(id) INTO max_id FROM public.history;
  IF max_id = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.history id space is exhausted';
  END IF;
  IF max_id IS NOT NULL
     AND (seq_last < max_id OR (seq_last=max_id AND NOT seq_called))
  THEN
    PERFORM setval('public.history_id_seq'::regclass, max_id, true);
  END IF;
  SELECT last_value, is_called INTO seq_last, seq_called
  FROM public.history_id_seq;
  IF seq_called AND seq_last = 9223372036854775807 THEN
    RAISE EXCEPTION 'public.history id sequence is exhausted';
  END IF;

  SELECT array_agg(
           c.conname || ':' || c.contype::text || ':' ||
           c.condeferrable::text || ':' || c.condeferred::text || ':' ||
           array_to_string(c.conkey, ',')
           ORDER BY c.conname
         ) INTO key_shape
  FROM pg_constraint AS c
  WHERE c.conrelid='public.history'::regclass AND c.contype IN ('p','u','f','x');
  IF key_shape <> ARRAY[
       'history_pkey:p:false:false:' ||
       (SELECT attnum::text FROM pg_attribute
        WHERE attrelid='public.history'::regclass AND attname='id')
     ]
  THEN
    RAISE EXCEPTION 'public.history key shape mismatch: %', key_shape;
  END IF;
END
$history_shape$;

DO $preflight$
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.history
    WHERE op='critique' AND (
      payload IS NULL OR jsonb_typeof(payload)<>'object'
      OR NOT payload ? 'arg_id'
      OR jsonb_typeof(payload->'arg_id')<>'string'
      OR coalesce(payload->>'arg_id','')=''
      OR strpos(payload->>'arg_id','/')<>0
    )
  ) THEN
    RAISE EXCEPTION 'malformed critique identity exists';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.history WHERE op='critique'
    GROUP BY tree, payload->>'arg_id' HAVING count(*)<>1
  ) THEN
    RAISE EXCEPTION 'duplicate critique logical identity exists';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.history WHERE event_id IS NOT NULL
    GROUP BY event_id HAVING count(*)<>1
  ) THEN
    RAISE EXCEPTION 'duplicate history event_id exists';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.history
    WHERE op='critique' AND event_id IS NOT NULL
      AND event_id !~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'
  ) THEN
    RAISE EXCEPTION 'unsupported critique event binding exists';
  END IF;
END
$preflight$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_history_event_id
  ON public.history(event_id) WHERE event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.history_event_claims(
  stable_event_id TEXT PRIMARY KEY,
  history_id BIGINT NOT NULL UNIQUE REFERENCES public.history(id),
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

LOCK TABLE public.history_event_claims IN SHARE ROW EXCLUSIVE MODE;

DO $claims_persistence$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.history_event_claims'::regclass
      AND relkind='r' AND relpersistence='p'
  ) THEN
    RAISE EXCEPTION 'critique-history objects must be permanent ordinary storage';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid='public.history_event_claims'::regclass
      AND (relhassubclass OR relispartition)
  ) OR EXISTS (
    SELECT 1 FROM pg_inherits
    WHERE inhparent='public.history_event_claims'::regclass
       OR inhrelid='public.history_event_claims'::regclass
  ) THEN
    RAISE EXCEPTION 'critique-history tables must not participate in inheritance';
  END IF;
END
$claims_persistence$;

DO $behavioral_objects$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid IN ('public.history'::regclass,
                      'public.history_event_claims'::regclass,
                      'public.metric_snapshots'::regclass,
                      'public.lineage'::regclass)
      AND NOT tgisinternal
  ) OR EXISTS (
    SELECT 1 FROM pg_rewrite
    WHERE ev_class IN ('public.history'::regclass,
                       'public.history_event_claims'::regclass,
                       'public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)
      AND rulename <> '_RETURN'
  ) OR EXISTS (
    SELECT 1 FROM pg_policy
    WHERE polrelid IN ('public.history'::regclass,
                       'public.history_event_claims'::regclass,
                       'public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)
  ) OR EXISTS (
    SELECT 1 FROM pg_class
    WHERE oid IN ('public.history'::regclass,
                  'public.history_event_claims'::regclass,
                  'public.metric_snapshots'::regclass,
                  'public.lineage'::regclass)
      AND (relrowsecurity OR relforcerowsecurity)
  ) THEN
    RAISE EXCEPTION 'unexpected behavioral object on critique-history tables';
  END IF;
END
$behavioral_objects$;

DO $internal_trigger_shape$
DECLARE
  trigger_shape text[];
BEGIN
  SELECT array_agg(
           r.relname || ':' || p.proname || ':' || t.tgenabled::text || ':' ||
           t.tgtype::text || ':' || coalesce(c.conname, '')
           ORDER BY r.relname, p.proname, t.tgtype
         ) INTO trigger_shape
  FROM pg_trigger AS t
  JOIN pg_class AS r ON r.oid=t.tgrelid
  JOIN pg_proc AS p ON p.oid=t.tgfoid
  LEFT JOIN pg_constraint AS c ON c.oid=t.tgconstraint
  WHERE t.tgrelid IN ('public.history'::regclass,
                      'public.history_event_claims'::regclass,
                      'public.metric_snapshots'::regclass,
                      'public.lineage'::regclass)
    AND t.tgisinternal;
  IF trigger_shape <> ARRAY[
    'history:RI_FKey_noaction_del:O:9:history_event_claims_history_id_fkey',
    'history:RI_FKey_noaction_upd:O:17:history_event_claims_history_id_fkey',
    'history_event_claims:RI_FKey_check_ins:O:5:history_event_claims_history_id_fkey',
    'history_event_claims:RI_FKey_check_upd:O:17:history_event_claims_history_id_fkey'
  ] THEN
    RAISE EXCEPTION 'critique-history internal trigger shape mismatch: %',
                    trigger_shape;
  END IF;
END
$internal_trigger_shape$;

DO $claims_shape$
DECLARE
  column_shape text[];
  constraint_shape text[];
BEGIN
  SELECT array_agg(
           a.attname || ':' || format_type(a.atttypid,a.atttypmod) || ':' ||
           CASE WHEN a.attnotnull THEN 'not-null' ELSE 'nullable' END || ':' ||
           coalesce(regexp_replace(lower(pg_get_expr(d.adbin,d.adrelid)),
                                   '[[:space:]]', '', 'g'), '') || ':' ||
           coalesce(a.attidentity::text, '') || ':' ||
           coalesce(a.attgenerated::text, '')
           ORDER BY a.attnum
         ) INTO column_shape
  FROM pg_attribute AS a
  LEFT JOIN pg_attrdef AS d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid='public.history_event_claims'::regclass
    AND a.attnum>0 AND NOT a.attisdropped;
  IF column_shape <> ARRAY[
    'stable_event_id:text:not-null:::',
    'history_id:bigint:not-null:::',
    'claimed_at:timestamp with time zone:not-null:now()::'
  ] THEN
    RAISE EXCEPTION 'history_event_claims column shape mismatch: %', column_shape;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_attribute AS a
    WHERE a.attrelid='public.history_event_claims'::regclass
      AND a.attnum>0 AND NOT a.attisdropped
      AND a.attcollation<>0
      AND a.attcollation<>'pg_catalog.default'::regcollation
  ) THEN
    RAISE EXCEPTION 'history_event_claims has a non-default column collation';
  END IF;

  SELECT array_agg(
           c.conname || ':' || c.contype::text || ':' ||
           c.convalidated::text || ':' || c.condeferrable::text || ':' ||
           c.condeferred::text || ':' || c.confupdtype::text || ':' ||
           c.confdeltype::text || ':' || c.confmatchtype::text || ':' ||
           coalesce(n.nspname,'') || ':' || coalesce(r.relname,'') || ':' ||
           array_to_string(c.conkey, ',') || ':' || array_to_string(c.confkey, ',')
           ORDER BY c.conname
         ) INTO constraint_shape
  FROM pg_constraint AS c
  LEFT JOIN pg_class AS r ON r.oid=c.confrelid
  LEFT JOIN pg_namespace AS n ON n.oid=r.relnamespace
  WHERE c.conrelid='public.history_event_claims'::regclass;

  IF array_length(constraint_shape,1) <> 3
     OR NOT EXISTS (
       SELECT 1 FROM pg_constraint AS c
       WHERE c.conrelid='public.history_event_claims'::regclass
         AND c.conname='history_event_claims_pkey' AND c.contype='p'
         AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred
         AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
           WHERE attrelid=c.conrelid AND attname='stable_event_id')]::smallint[]
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_constraint AS c
       WHERE c.conrelid='public.history_event_claims'::regclass
         AND c.conname='history_event_claims_history_id_key' AND c.contype='u'
         AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred
         AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
           WHERE attrelid=c.conrelid AND attname='history_id')]::smallint[]
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_constraint AS c
       WHERE c.conrelid='public.history_event_claims'::regclass
         AND c.conname='history_event_claims_history_id_fkey' AND c.contype='f'
         AND c.convalidated AND NOT c.condeferrable AND NOT c.condeferred
         AND c.confrelid='public.history'::regclass
         AND c.confupdtype='a' AND c.confdeltype='a' AND c.confmatchtype='s'
         AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
           WHERE attrelid=c.conrelid AND attname='history_id')]::smallint[]
         AND c.confkey=ARRAY[(SELECT attnum FROM pg_attribute
           WHERE attrelid=c.confrelid AND attname='id')]::smallint[]
     )
  THEN
    RAISE EXCEPTION 'history_event_claims exact constraints mismatch: %', constraint_shape;
  END IF;
END
$claims_shape$;

-- Existing stable rows predate the side claim table.  Preserve the append-only
-- row and bind it once; the Python exact readback below the coordinator verifies
-- that each he-* value is the hash of its actual tree/argument identity.
INSERT INTO public.history_event_claims(stable_event_id, history_id)
SELECT h.event_id, h.id
FROM public.history AS h
WHERE h.op='critique' AND h.event_id ~ '^he-[0-9a-f]{64}$'
ON CONFLICT DO NOTHING;

DO $check_create$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='public.history'::regclass
      AND conname='ck_history_critique_identity'
  ) THEN
    ALTER TABLE public.history
      ADD CONSTRAINT ck_history_critique_identity
      CHECK (
        op <> 'critique' OR (
          payload IS NOT NULL
          AND jsonb_typeof(payload)='object'
          AND payload ? 'arg_id'
          AND jsonb_typeof(payload->'arg_id')='string'
          AND payload->>'arg_id' <> ''
          AND strpos(payload->>'arg_id','/')=0
        )
      ) NOT VALID;
  END IF;
  -- Keep the cross-store cutover backward-compatible if receipt publication
  -- fails after this PostgreSQL transaction commits.  New writers emit he-*,
  -- while a drained old writer may resume with NULL/ob-* until cutover succeeds;
  -- the side-claim/adoption protocol upgrades those rows without duplication.
  ALTER TABLE public.history
    DROP CONSTRAINT IF EXISTS ck_history_new_critique_stable_event;
  ALTER TABLE public.history
    ADD CONSTRAINT ck_history_new_critique_stable_event
    CHECK (
      op <> 'critique' OR event_id IS NULL
      OR event_id ~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'
    ) NOT VALID;
END
$check_create$;

-- The data preflight above proves validation is safe.  Validate before exact
-- convalidated readback so additive upgrades and fresh installs converge.
ALTER TABLE public.history VALIDATE CONSTRAINT ck_history_critique_identity;

CREATE TEMP TABLE expected_critique_check(
  op TEXT,
  payload JSONB,
  CONSTRAINT expected_critique_check_shape CHECK (
    op <> 'critique' OR (
      payload IS NOT NULL
      AND jsonb_typeof(payload)='object'
      AND payload ? 'arg_id'
      AND jsonb_typeof(payload->'arg_id')='string'
      AND payload->>'arg_id' <> ''
      AND strpos(payload->>'arg_id','/')=0
    )
  )
) ON COMMIT DROP;

CREATE TEMP TABLE expected_stable_event_check(
  op TEXT,
  event_id TEXT
) ON COMMIT DROP;
ALTER TABLE expected_stable_event_check
  ADD CONSTRAINT expected_stable_event_check_shape
  CHECK (
    op <> 'critique' OR event_id IS NULL
    OR event_id ~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'
  ) NOT VALID;

DO $check_shape$
DECLARE
  actual text;
  expected text;
  stable_actual text;
  stable_expected text;
  identity_validated boolean;
  stable_validated boolean;
  check_names text[];
BEGIN
  SELECT pg_get_expr(c.conbin,c.conrelid), c.convalidated
    INTO actual, identity_validated
  FROM pg_constraint AS c
  WHERE c.conrelid='public.history'::regclass
    AND c.conname='ck_history_critique_identity' AND c.contype='c';
  SELECT pg_get_expr(c.conbin,c.conrelid)
    INTO expected
  FROM pg_constraint AS c
  WHERE c.conrelid='expected_critique_check'::regclass
    AND c.conname='expected_critique_check_shape' AND c.contype='c';
  SELECT pg_get_expr(c.conbin,c.conrelid), c.convalidated
    INTO stable_actual, stable_validated
  FROM pg_constraint AS c
  WHERE c.conrelid='public.history'::regclass
    AND c.conname='ck_history_new_critique_stable_event' AND c.contype='c';
  SELECT pg_get_expr(c.conbin,c.conrelid)
    INTO stable_expected
  FROM pg_constraint AS c
  WHERE c.conrelid='expected_stable_event_check'::regclass
    AND c.conname='expected_stable_event_check_shape' AND c.contype='c';
  IF actual IS DISTINCT FROM expected OR identity_validated IS NOT TRUE THEN
    RAISE EXCEPTION 'ck_history_critique_identity wrong semantics: %', actual;
  END IF;
  IF stable_actual IS DISTINCT FROM stable_expected OR stable_validated IS NOT FALSE THEN
    RAISE EXCEPTION 'ck_history_new_critique_stable_event wrong semantics: %',
                    stable_actual;
  END IF;
  SELECT array_agg(c.conname ORDER BY c.conname) INTO check_names
  FROM pg_constraint AS c
  WHERE c.conrelid='public.history'::regclass AND c.contype='c';
  IF check_names <> ARRAY[
       'ck_history_critique_identity',
       'ck_history_new_critique_stable_event'
     ] THEN
    RAISE EXCEPTION 'unexpected public.history CHECK constraints: %', check_names;
  END IF;
END
$check_shape$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_history_critique_logical_identity
  ON public.history(tree, (payload->>'arg_id')) WHERE op='critique';
CREATE INDEX IF NOT EXISTS idx_history_tree_ts ON public.history(tree, ts DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_output ON public.lineage(output);

CREATE TEMP TABLE expected_history_indexes(
  tree TEXT,
  ts TIMESTAMPTZ,
  op TEXT,
  payload JSONB,
  event_id TEXT
) ON COMMIT DROP;
CREATE UNIQUE INDEX expected_uq_history_event_id
  ON expected_history_indexes(event_id) WHERE event_id IS NOT NULL;
CREATE UNIQUE INDEX expected_uq_history_critique_logical_identity
  ON expected_history_indexes(tree, (payload->>'arg_id')) WHERE op='critique';
CREATE INDEX expected_idx_history_tree_ts
  ON expected_history_indexes(tree, ts DESC);
CREATE TEMP TABLE expected_lineage_indexes(output TEXT) ON COMMIT DROP;
CREATE INDEX expected_idx_lineage_output
  ON expected_lineage_indexes(output);

DO $index_readback$
DECLARE
  event_ok boolean;
  critique_ok boolean;
  tree_ts_ok boolean;
  lineage_output_ok boolean;
  actual_unique_names text[];
  claim_unique_names text[];
  metric_index_names text[];
  lineage_index_names text[];
BEGIN
  SELECT count(*)=1 AND bool_and(
           i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
           AND i.indnkeyatts=1 AND i.indnatts=1
           AND (i.indclass, i.indcollation, i.indoption, i.indnullsnotdistinct) =
               (SELECT e.indclass, e.indcollation, e.indoption,
                       e.indnullsnotdistinct
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_event_id')
           AND pg_get_indexdef(i.indexrelid,1,false) =
               (SELECT pg_get_indexdef(e.indexrelid,1,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_event_id')
           AND pg_get_expr(i.indpred,i.indrelid) =
               (SELECT pg_get_expr(e.indpred,e.indrelid)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_event_id')
         ) INTO event_ok
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.history'::regclass AND c.relname='uq_history_event_id';

  SELECT count(*)=1 AND bool_and(
           i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
           AND i.indnkeyatts=2 AND i.indnatts=2
           AND (i.indclass, i.indcollation, i.indoption, i.indnullsnotdistinct) =
               (SELECT e.indclass, e.indcollation, e.indoption,
                       e.indnullsnotdistinct
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_critique_logical_identity')
           AND pg_get_indexdef(i.indexrelid,1,false) =
               (SELECT pg_get_indexdef(e.indexrelid,1,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_critique_logical_identity')
           AND pg_get_indexdef(i.indexrelid,2,false) =
               (SELECT pg_get_indexdef(e.indexrelid,2,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_critique_logical_identity')
           AND pg_get_expr(i.indpred,i.indrelid) =
               (SELECT pg_get_expr(e.indpred,e.indrelid)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_uq_history_critique_logical_identity')
         ) INTO critique_ok
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.history'::regclass
    AND c.relname='uq_history_critique_logical_identity';
  SELECT count(*)=1 AND bool_and(
           NOT i.indisunique AND NOT i.indisexclusion
           AND i.indisvalid AND i.indisready AND i.indislive
           AND i.indnkeyatts=2 AND i.indnatts=2
           AND (i.indclass, i.indcollation, i.indoption, i.indnullsnotdistinct) =
               (SELECT e.indclass, e.indcollation, e.indoption,
                       e.indnullsnotdistinct
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_idx_history_tree_ts')
           AND pg_get_indexdef(i.indexrelid,1,false) =
               (SELECT pg_get_indexdef(e.indexrelid,1,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_idx_history_tree_ts')
           AND pg_get_indexdef(i.indexrelid,2,false) =
               (SELECT pg_get_indexdef(e.indexrelid,2,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_history_indexes'::regclass
                  AND ec.relname='expected_idx_history_tree_ts')
           AND i.indpred IS NULL
         ) INTO tree_ts_ok
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.history'::regclass
    AND c.relname='idx_history_tree_ts';
  IF event_ok IS NOT TRUE OR critique_ok IS NOT TRUE OR tree_ts_ok IS NOT TRUE THEN
    RAISE EXCEPTION 'history index exact readback failed: event=%, critique=%, tree_ts=%',
                    event_ok, critique_ok, tree_ts_ok;
  END IF;
  SELECT count(*)=1 AND bool_and(
           NOT i.indisunique AND NOT i.indisexclusion
           AND i.indisvalid AND i.indisready AND i.indislive
           AND i.indnkeyatts=1 AND i.indnatts=1
           AND (i.indclass, i.indcollation, i.indoption,
                i.indnullsnotdistinct) =
               (SELECT e.indclass, e.indcollation, e.indoption,
                       e.indnullsnotdistinct
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_lineage_indexes'::regclass
                  AND ec.relname='expected_idx_lineage_output')
           AND pg_get_indexdef(i.indexrelid,1,false) =
               (SELECT pg_get_indexdef(e.indexrelid,1,false)
                FROM pg_index AS e JOIN pg_class AS ec ON ec.oid=e.indexrelid
                WHERE e.indrelid='expected_lineage_indexes'::regclass
                  AND ec.relname='expected_idx_lineage_output')
           AND i.indpred IS NULL
         ) INTO lineage_output_ok
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.lineage'::regclass
    AND c.relname='idx_lineage_output';
  IF lineage_output_ok IS NOT TRUE THEN
    RAISE EXCEPTION 'lineage output index exact readback failed';
  END IF;
  SELECT array_agg(c.relname ORDER BY c.relname) INTO actual_unique_names
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.history'::regclass;
  IF actual_unique_names <> ARRAY[
       'history_pkey',
       'idx_history_tree_ts',
       'uq_history_critique_logical_identity',
       'uq_history_event_id'
     ] THEN
    RAISE EXCEPTION 'unexpected public.history rejecting indexes: %', actual_unique_names;
  END IF;
  SELECT array_agg(c.relname ORDER BY c.relname) INTO claim_unique_names
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.history_event_claims'::regclass;
  IF claim_unique_names <> ARRAY[
       'history_event_claims_history_id_key',
       'history_event_claims_pkey'
     ] THEN
    RAISE EXCEPTION 'unexpected public.history_event_claims rejecting indexes: %',
                    claim_unique_names;
  END IF;
  SELECT array_agg(c.relname ORDER BY c.relname) INTO metric_index_names
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.metric_snapshots'::regclass;
  IF metric_index_names <> ARRAY['metric_snapshots_pkey'] THEN
    RAISE EXCEPTION 'unexpected public.metric_snapshots indexes: %',
                    metric_index_names;
  END IF;
  SELECT array_agg(c.relname ORDER BY c.relname) INTO lineage_index_names
  FROM pg_index AS i JOIN pg_class AS c ON c.oid=i.indexrelid
  WHERE i.indrelid='public.lineage'::regclass;
  IF lineage_index_names <> ARRAY['idx_lineage_output', 'lineage_pkey'] THEN
    RAISE EXCEPTION 'unexpected public.lineage indexes: %', lineage_index_names;
  END IF;
END
$index_readback$;

COMMIT;
