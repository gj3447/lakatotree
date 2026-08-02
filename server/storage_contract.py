"""Exact, exhaustive deployment audit for critique-history durability.

This module is intentionally read-only.  It validates the public PostgreSQL
objects, every critique/claim binding, every Neo4j outbox state, stable Argument
provenance, and finalized cross-store projections.  It is suitable for explicit
predeploy/startup audit, not a per-request health probe.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Iterable

from lakatos.io.reconcile import history_event_id, validate_history_record
from server.contexts.tree.admin_intents import (
    AdminIntentError,
    validate_admin_verdict_intent,
)
from server.contexts.tree.verdict_intents import (
    VerdictIntentError,
    validate_verdict_intent_group,
)
from server.contexts.tree.prediction_intents import (
    PredictionIntentError,
    validate_prediction_register_intent,
)
from server.contexts.tree.receipt_chain import (
    RECEIPT_CHAIN_ROWS_CYPHER,
    RECEIPT_IDENTITIES_CYPHER,
    ReceiptGraphError,
    validate_receipt_graph,
)


CONTRACT_ID = "lakatotree-critique-history-storage/v1"


class StorageContractError(RuntimeError):
    """The reachable datastores do not implement ``CONTRACT_ID`` exactly."""


_PG_OBJECTS_SQL = """
SELECT to_regclass('public.history') IS NOT NULL AS history_exists,
       to_regclass('public.history_event_claims') IS NOT NULL AS claims_exists,
       to_regclass('public.metric_snapshots') IS NOT NULL AS metrics_exists,
       to_regclass('public.lineage') IS NOT NULL AS lineage_exists,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.history')) AS history_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.history')) AS history_persistence,
       (SELECT relhassubclass FROM pg_class
         WHERE oid=to_regclass('public.history')) AS history_has_subclass,
       (SELECT relispartition FROM pg_class
         WHERE oid=to_regclass('public.history')) AS history_is_partition,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.history_event_claims')) AS claims_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.history_event_claims')) AS claims_persistence,
       (SELECT relhassubclass FROM pg_class
         WHERE oid=to_regclass('public.history_event_claims')) AS claims_has_subclass,
       (SELECT relispartition FROM pg_class
         WHERE oid=to_regclass('public.history_event_claims')) AS claims_is_partition,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots')) AS metrics_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots')) AS metrics_persistence,
       (SELECT relhassubclass FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots')) AS metrics_has_subclass,
       (SELECT relispartition FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots')) AS metrics_is_partition,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.lineage')) AS lineage_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.lineage')) AS lineage_persistence,
       (SELECT relhassubclass FROM pg_class
         WHERE oid=to_regclass('public.lineage')) AS lineage_has_subclass,
       (SELECT relispartition FROM pg_class
         WHERE oid=to_regclass('public.lineage')) AS lineage_is_partition,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.history_id_seq')) AS sequence_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.history_id_seq')) AS sequence_persistence,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots_id_seq'))
         AS metrics_sequence_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.metric_snapshots_id_seq'))
         AS metrics_sequence_persistence,
       (SELECT relkind::text FROM pg_class
         WHERE oid=to_regclass('public.lineage_id_seq')) AS lineage_sequence_kind,
       (SELECT relpersistence::text FROM pg_class
         WHERE oid=to_regclass('public.lineage_id_seq'))
         AS lineage_sequence_persistence,
       (SELECT count(*) FROM pg_inherits
         WHERE inhparent IN (to_regclass('public.history'),
                             to_regclass('public.history_event_claims'),
                             to_regclass('public.metric_snapshots'),
                             to_regclass('public.lineage'))
            OR inhrelid IN (to_regclass('public.history'),
                            to_regclass('public.history_event_claims'),
                            to_regclass('public.metric_snapshots'),
                            to_regclass('public.lineage')))
         AS inheritance_edges
"""

_PG_HISTORY_COLUMNS_SQL = """
SELECT a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS not_null,
       CASE WHEN a.attcollation=0 THEN NULL
            ELSE cns.nspname || '.' || coll.collname END AS collation,
       pg_get_expr(d.adbin, d.adrelid) AS default_expr,
       a.attidentity AS identity_kind,
       a.attgenerated AS generated_kind
FROM pg_attribute AS a
LEFT JOIN pg_attrdef AS d
  ON d.adrelid=a.attrelid AND d.adnum=a.attnum
LEFT JOIN pg_collation AS coll ON coll.oid=a.attcollation
LEFT JOIN pg_namespace AS cns ON cns.oid=coll.collnamespace
WHERE a.attrelid='public.history'::regclass
  AND a.attnum>0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

_PG_CLAIMS_COLUMNS_SQL = """
SELECT a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS not_null,
       CASE WHEN a.attcollation=0 THEN NULL
            ELSE cns.nspname || '.' || coll.collname END AS collation,
       pg_get_expr(d.adbin, d.adrelid) AS default_expr,
       a.attidentity AS identity_kind,
       a.attgenerated AS generated_kind
FROM pg_attribute AS a
LEFT JOIN pg_attrdef AS d
  ON d.adrelid=a.attrelid AND d.adnum=a.attnum
LEFT JOIN pg_collation AS coll ON coll.oid=a.attcollation
LEFT JOIN pg_namespace AS cns ON cns.oid=coll.collnamespace
WHERE a.attrelid='public.history_event_claims'::regclass
  AND a.attnum>0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

_PG_AUX_COLUMNS_SQL = """
SELECT r.relname AS table_name, a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS not_null,
       CASE WHEN a.attcollation=0 THEN NULL
            ELSE cns.nspname || '.' || coll.collname END AS collation,
       pg_get_expr(d.adbin, d.adrelid) AS default_expr,
       a.attidentity AS identity_kind,
       a.attgenerated AS generated_kind
FROM pg_attribute AS a
JOIN pg_class AS r ON r.oid=a.attrelid
LEFT JOIN pg_attrdef AS d
  ON d.adrelid=a.attrelid AND d.adnum=a.attnum
LEFT JOIN pg_collation AS coll ON coll.oid=a.attcollation
LEFT JOIN pg_namespace AS cns ON cns.oid=coll.collnamespace
WHERE a.attrelid IN ('public.metric_snapshots'::regclass,
                     'public.lineage'::regclass)
  AND a.attnum>0 AND NOT a.attisdropped
ORDER BY r.relname, a.attnum
"""

_PG_CONSTRAINTS_SQL = """
SELECT c.conname AS name, c.contype AS kind, c.convalidated AS validated,
       ns.nspname AS table_schema, r.relname AS table_name,
       r.oid AS table_oid,
       rns.nspname AS referenced_schema, rr.relname AS referenced_table,
       c.confrelid AS referenced_oid,
       c.condeferrable AS deferrable, c.condeferred AS initially_deferred,
       c.confupdtype AS update_action, c.confdeltype AS delete_action,
       c.confmatchtype AS match_type,
       ARRAY(
         SELECT a.attname
         FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
         JOIN pg_attribute AS a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
         ORDER BY k.ord
       ) AS columns,
       ARRAY(
         SELECT a.attname
         FROM unnest(coalesce(c.confkey, ARRAY[]::smallint[]))
              WITH ORDINALITY AS k(attnum, ord)
         JOIN pg_attribute AS a ON a.attrelid=c.confrelid AND a.attnum=k.attnum
         ORDER BY k.ord
       ) AS referenced_columns
FROM pg_constraint AS c
JOIN pg_class AS r ON r.oid=c.conrelid
JOIN pg_namespace AS ns ON ns.oid=r.relnamespace
LEFT JOIN pg_class AS rr ON rr.oid=c.confrelid
LEFT JOIN pg_namespace AS rns ON rns.oid=rr.relnamespace
WHERE c.conrelid IN (
  'public.history'::regclass,
  'public.history_event_claims'::regclass,
  'public.metric_snapshots'::regclass,
  'public.lineage'::regclass
)
  AND c.contype IN ('p','u','f','x')
ORDER BY ns.nspname, r.relname, c.conname
"""

_PG_HISTORY_INDEXES_SQL = """
SELECT ic.relname AS name, ns.nspname AS table_schema,
       tc.relname AS table_name,
       am.amname AS access_method,
       i.indisunique AS is_unique, i.indisvalid AS is_valid,
       i.indisexclusion AS is_exclusion,
       i.indisready AS is_ready, i.indislive AS is_live,
       i.indnullsnotdistinct AS nulls_not_distinct,
       i.indnkeyatts AS key_count, i.indnatts AS total_count,
       ARRAY(
         SELECT pg_get_indexdef(i.indexrelid, pos, false)
         FROM generate_series(1, i.indnkeyatts) AS pos
         ORDER BY pos
       ) AS keys,
       i.indoption::smallint[] AS options,
       ARRAY(
         SELECT opns.nspname || '.' || opc.opcname
         FROM unnest(i.indclass::oid[]) WITH ORDINALITY AS item(opc_oid, ord)
         JOIN pg_opclass AS opc ON opc.oid=item.opc_oid
         JOIN pg_namespace AS opns ON opns.oid=opc.opcnamespace
         ORDER BY item.ord
       ) AS opclasses,
       ARRAY(
         SELECT CASE WHEN item.coll_oid=0 THEN NULL
                     ELSE cns.nspname || '.' || coll.collname END
         FROM unnest(i.indcollation::oid[]) WITH ORDINALITY AS item(coll_oid, ord)
         LEFT JOIN pg_collation AS coll ON coll.oid=item.coll_oid
         LEFT JOIN pg_namespace AS cns ON cns.oid=coll.collnamespace
         ORDER BY item.ord
       ) AS collations,
       pg_get_expr(i.indpred, i.indrelid) AS predicate
FROM pg_index AS i
JOIN pg_class AS ic ON ic.oid=i.indexrelid
JOIN pg_class AS tc ON tc.oid=i.indrelid
JOIN pg_namespace AS ns ON ns.oid=tc.relnamespace
JOIN pg_am AS am ON am.oid=ic.relam
WHERE i.indrelid IN ('public.history'::regclass,
                     'public.history_event_claims'::regclass,
                     'public.metric_snapshots'::regclass,
                     'public.lineage'::regclass)
ORDER BY tc.relname, ic.relname
"""

_PG_HISTORY_CHECK_SQL = """
SELECT r.relname AS table_name, c.conname AS name,
       c.convalidated AS validated,
       pg_get_expr(c.conbin, c.conrelid) AS expression
FROM pg_constraint AS c
JOIN pg_class AS r ON r.oid=c.conrelid
WHERE c.conrelid IN ('public.history'::regclass,
                     'public.history_event_claims'::regclass,
                     'public.metric_snapshots'::regclass,
                     'public.lineage'::regclass)
  AND c.contype='c'
ORDER BY r.relname, c.conname
"""

_PG_HISTORY_SEQUENCE_SQL = """
SELECT schemaname, sequencename, data_type, start_value, min_value, max_value,
       increment_by, cycle, cache_size,
       CASE sequencename
         WHEN 'history_id_seq' THEN pg_get_serial_sequence('public.history','id')
         WHEN 'metric_snapshots_id_seq' THEN
           pg_get_serial_sequence('public.metric_snapshots','id')
         WHEN 'lineage_id_seq' THEN pg_get_serial_sequence('public.lineage','id')
       END AS owned_sequence
FROM pg_sequences
WHERE schemaname='public'
  AND sequencename IN ('history_id_seq', 'metric_snapshots_id_seq',
                       'lineage_id_seq')
ORDER BY sequencename
"""

_PG_HISTORY_SEQUENCE_STATE_SQL = """
SELECT 'history' AS table_name, 'history_id_seq' AS sequence_name,
       last_value, is_called, (SELECT max(id) FROM public.history) AS max_id
FROM public.history_id_seq
UNION ALL
SELECT 'metric_snapshots', 'metric_snapshots_id_seq', last_value, is_called,
       (SELECT max(id) FROM public.metric_snapshots)
FROM public.metric_snapshots_id_seq
UNION ALL
SELECT 'lineage', 'lineage_id_seq', last_value, is_called,
       (SELECT max(id) FROM public.lineage)
FROM public.lineage_id_seq
ORDER BY table_name
"""

_PG_BEHAVIORAL_OBJECTS_SQL = """
SELECT
  (SELECT count(*)
     FROM pg_trigger
    WHERE tgrelid IN ('public.history'::regclass,
                      'public.history_event_claims'::regclass,
                      'public.metric_snapshots'::regclass,
                      'public.lineage'::regclass)
      AND NOT tgisinternal) AS user_triggers,
  (SELECT count(*)
     FROM pg_rewrite
    WHERE ev_class IN ('public.history'::regclass,
                       'public.history_event_claims'::regclass,
                       'public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)
      AND rulename <> '_RETURN') AS rewrite_rules,
  (SELECT count(*)
     FROM pg_policy
    WHERE polrelid IN ('public.history'::regclass,
                       'public.history_event_claims'::regclass,
                       'public.metric_snapshots'::regclass,
                       'public.lineage'::regclass)) AS policies,
  (SELECT count(*)
     FROM pg_class
    WHERE oid IN ('public.history'::regclass,
                  'public.history_event_claims'::regclass,
                  'public.metric_snapshots'::regclass,
                  'public.lineage'::regclass)
      AND (relrowsecurity OR relforcerowsecurity)) AS rls_tables
"""

_PG_INTERNAL_TRIGGERS_SQL = """
SELECT ns.nspname AS table_schema, r.relname AS table_name,
       p.proname AS function_name, t.tgenabled::text AS enabled,
       t.tgisinternal AS is_internal, t.tgtype::integer AS trigger_type,
       c.conname AS constraint_name
FROM pg_trigger AS t
JOIN pg_class AS r ON r.oid=t.tgrelid
JOIN pg_namespace AS ns ON ns.oid=r.relnamespace
JOIN pg_proc AS p ON p.oid=t.tgfoid
LEFT JOIN pg_constraint AS c ON c.oid=t.tgconstraint
WHERE t.tgrelid IN ('public.history'::regclass,
                    'public.history_event_claims'::regclass,
                    'public.metric_snapshots'::regclass,
                    'public.lineage'::regclass)
  AND t.tgisinternal
ORDER BY ns.nspname, r.relname, p.proname, t.tgtype
"""

_PG_BLOCKERS_SQL = """
SELECT
  (SELECT count(*) FROM public.history
    WHERE op='critique' AND (
      payload IS NULL OR jsonb_typeof(payload)<>'object'
      OR NOT payload ? 'arg_id'
      OR jsonb_typeof(payload->'arg_id')<>'string'
      OR coalesce(payload->>'arg_id','')=''
      OR strpos(payload->>'arg_id','/')<>0
    )) AS malformed_critique_rows,
  (SELECT count(*) FROM (
     SELECT tree, payload->>'arg_id'
     FROM public.history WHERE op='critique'
     GROUP BY tree, payload->>'arg_id' HAVING count(*)<>1
   ) AS d) AS duplicate_critique_identities,
  (SELECT count(*) FROM (
     SELECT event_id FROM public.history WHERE event_id IS NOT NULL
     GROUP BY event_id HAVING count(*)<>1
   ) AS d) AS duplicate_event_ids,
  (SELECT count(*)
     FROM public.history AS h
     LEFT JOIN public.history_event_claims AS c ON c.history_id=h.id
    WHERE h.op='critique' AND h.event_id LIKE 'he-%'
      AND c.history_id IS NULL) AS unclaimed_stable_critique_rows
"""

_PG_CRITIQUE_ROWS_SQL = """
SELECT h.id AS history_id, h.tree, h.op, h.node_tag, h.payload, h.event_id,
       c.stable_event_id
FROM public.history AS h
LEFT JOIN public.history_event_claims AS c ON c.history_id=h.id
WHERE h.op='critique'
ORDER BY h.id
"""

_PG_CLAIMS_ROWS_SQL = """
SELECT c.stable_event_id, c.history_id,
       h.tree, h.op, h.node_tag, h.payload, h.event_id
FROM public.history_event_claims AS c
LEFT JOIN public.history AS h ON h.id=c.history_id
ORDER BY c.stable_event_id
"""

_PG_PROJECTION_ROWS_SQL = """
SELECT h.id AS history_id, h.tree, h.op, h.node_tag, h.payload, h.event_id,
       c.stable_event_id
FROM public.history AS h
LEFT JOIN public.history_event_claims AS c ON c.history_id=h.id
WHERE h.event_id IS NOT NULL OR c.stable_event_id IS NOT NULL
ORDER BY h.id
"""

_NEO_OUTBOX_CONSTRAINT_SQL = """
SHOW CONSTRAINTS
YIELD name, type, entityType, labelsOrTypes, properties
WHERE name IN ['lkt_outbox_id_unique', 'lkt_argument_id_unique',
               'lkt_runtime_writer_lease_name_unique']
   OR any(label IN labelsOrTypes
          WHERE label IN ['OutboxEntry', 'Argument', 'LakatosArgument',
                          'RuntimeWriterLease'])
RETURN name, type, entityType, labelsOrTypes, properties
ORDER BY name
"""

_NEO_OUTBOX_IDENTITIES_CYPHER = """
MATCH (o:OutboxEntry)
RETURN o.id AS id, count(*) AS copies
ORDER BY id
"""

_NEO_ARGUMENT_IDENTITIES_CYPHER = """
MATCH (a:LakatosArgument)
RETURN a.id AS id, count(*) AS copies
ORDER BY id
"""

_NEO_WRITER_LEASE_IDENTITIES_CYPHER = """
MATCH (lease:RuntimeWriterLease)
RETURN lease.name AS name, lease.generation AS generation,
       lease.owner_token AS owner_token, count(*) AS copies
ORDER BY name, generation, owner_token
"""

_NEO_RECEIPT_CHAIN_ROWS_CYPHER = RECEIPT_CHAIN_ROWS_CYPHER
_NEO_RECEIPT_IDENTITIES_CYPHER = RECEIPT_IDENTITIES_CYPHER

_NEO_OUTBOX_ROWS_CYPHER = """
MATCH (o:OutboxEntry)
RETURN elementId(o) AS element_id, o.id AS id, o.tree AS tree, o.op AS op,
       o.node_tag AS node_tag, o.payload AS payload, o.status AS status,
       o.created_at AS created_at, o.reason AS reason,
       o.applied_at AS applied_at, o.adopted_by AS adopted_by,
       o.adopted_at AS adopted_at, o.receipt_sha AS receipt_sha,
       o.causal_group AS causal_group, o.causal_index AS causal_index,
       o.request_sha256 AS request_sha256,
       o.demoted_tag AS demoted_tag,
       o.demoted_receipt_sha AS demoted_receipt_sha
ORDER BY id, element_id
"""

_NEO_CAUSAL_RECEIPT_AUTHORITIES_CYPHER = """
UNWIND $specs AS spec
OPTIONAL MATCH (t:LakatosTree {name:spec.tree})-[:HAS_NODE]->
               (e {tag:spec.tag})
OPTIONAL MATCH (e)-[binding:HAS_RECEIPT]->
               (rec:VerdictReceipt {receipt_sha:spec.group})
OPTIONAL MATCH (t)-[:HAS_FRONTIER]->
               (q:OpenQuestion {name:rec.target_id})
OPTIONAL MATCH (q)-[:HAS_CLOSURE]->
               (closure:QuestionClosure {id:spec.group})
RETURN spec.group AS group, spec.tree AS expected_tree,
       spec.tag AS expected_tag,
       count(DISTINCT t) AS trees, count(DISTINCT e) AS nodes,
       count(DISTINCT binding) AS bindings,
       count(DISTINCT rec) AS receipts,
       t.name AS current_tree, e.tag AS current_tag,
       e.current_receipt_sha AS current_receipt_sha,
       e.verdict AS current_verdict,
       e.verdict_source AS current_verdict_source,
       e.lakatos_status AS current_lakatos_status,
       e.metric_value AS current_metric_value,
       properties(rec) AS receipt,
       q.status AS question_state,
       q.closed_by AS question_closed_by,
       q.closed_events AS question_closed_events,
       closure.id AS closure_id,
       closure.closed_by AS closure_closed_by,
       closure.at AS closure_at,
       closure.tree AS closure_tree,
       closure.question AS closure_question,
       closure.trigger AS closure_trigger,
       closure.verdict AS closure_verdict,
       closure.receipt_sha AS closure_receipt_sha,
       COUNT { MATCH (q)-[:HAS_CLOSURE]->
               (:QuestionClosure {id:spec.group})-[:CAUSED_BY]->(rec) }
         AS closure_bound_count,
       COUNT { MATCH (:QuestionClosure {id:spec.group}) }
         AS closure_global_count,
       COUNT { MATCH (e)-[:CLOSES_QUESTION]->(q) }
         AS closes_rel_count,
       head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.receipt_sha])
         AS closes_rel_receipt_sha,
       head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.verdict])
         AS closes_rel_verdict,
       head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.at])
         AS closes_rel_at
ORDER BY group, expected_tree, expected_tag
"""

_NEO_ADMIN_AUTHORITY_CYPHER = """
MATCH (o:OutboxEntry)
WHERE o.op='verdict'
   OR o.reason='verdict_commit_intent'
   OR o.id STARTS WITH 'ob-verdict-'
OPTIONAL MATCH (t:LakatosTree {name:o.tree})-[:HAS_NODE]->
               (e {tag:o.node_tag})
OPTIONAL MATCH (e)-[:HAS_RECEIPT]->
               (rec:VerdictReceipt {receipt_sha:o.receipt_sha})
OPTIONAL MATCH (t)-[:HAS_NODE]->(demoted {tag:o.demoted_tag})
               -[:HAS_RECEIPT]->
               (demoted_rec:VerdictReceipt {
                 receipt_sha:o.demoted_receipt_sha
               })
RETURN o.id AS event_id, properties(o) AS outbox,
       e.current_receipt_sha AS current_receipt_sha,
       e.verdict AS current_verdict,
       e.verdict_source AS current_verdict_source,
       properties(rec) AS receipt,
       CASE WHEN demoted IS NULL THEN null ELSE {
         tag:demoted.tag,
         current_receipt_sha:demoted.current_receipt_sha,
         verdict:demoted.verdict,
         verdict_source:demoted.verdict_source
       } END AS demoted_current,
       properties(demoted_rec) AS demoted_receipt
ORDER BY event_id
"""

_NEO_PREDICTION_AUTHORITY_CYPHER = """
MATCH (o:OutboxEntry)
WHERE o.op='prediction_register'
   OR o.reason='prediction_register_commit_intent'
   OR o.id STARTS WITH 'ob-prediction-register-'
OPTIONAL MATCH (t:LakatosTree {name:o.tree})-[:HAS_NODE]->(e {tag:o.node_tag})
OPTIONAL MATCH (e)-[binding:HAS_RECEIPT]->
               (rec:VerdictReceipt {receipt_sha:o.receipt_sha})
RETURN o.id AS event_id, properties(o) AS outbox,
       count(DISTINCT t) AS trees, count(DISTINCT e) AS nodes,
       count(DISTINCT binding) AS bindings, count(DISTINCT rec) AS receipts,
       head(collect(DISTINCT properties(e))) AS current,
       head(collect(DISTINCT properties(rec))) AS receipt
ORDER BY event_id
"""


def _rows(cur: Any) -> list[dict[str, Any]]:
    raw = list(cur.fetchall())
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return [dict(row) for row in raw]
    names = [item.name if hasattr(item, "name") else item[0] for item in cur.description]
    return [dict(zip(names, row, strict=True)) for row in raw]


def _one(cur: Any) -> dict[str, Any]:
    rows = _rows(cur)
    return rows[0] if len(rows) == 1 else {}


def _normalize_sql(value: Any, *, compact: bool) -> str:
    """Normalize deparsed SQL without altering quoted literal bytes.

    PostgreSQL inserts harmless casts and whitespace outside literals.  The old
    regex/lowercase implementation also rewrote literal contents, making
    ``'CRITIQUE'`` equal to ``'critique'`` and ``'arg_id::text'`` equal to
    ``'arg_id'``.  This scanner only folds unquoted syntax.
    """

    if not isinstance(value, str):
        return ""
    out: list[str] = []
    index = 0
    quoted = False
    pending_space = False
    while index < len(value):
        char = value[index]
        if char == "'":
            out.append(char)
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                out.append("'")
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if quoted:
            out.append(char)
            index += 1
            continue
        cast = re.match(r"::(?:text|jsonb)\b", value[index:], flags=re.IGNORECASE)
        if cast:
            index += len(cast.group(0))
            continue
        if char.isspace():
            pending_space = True
            index += 1
            continue
        if pending_space and not compact and out and out[-1] not in " (":
            out.append(" ")
        pending_space = False
        out.append(char.lower())
        index += 1
    return "".join(out).strip()


def _compact(value: Any) -> str:
    value = _normalize_sql(value, compact=True)
    # pg_get_expr adds harmless parentheses around JSON operands.  Remove only
    # that narrow atomic form; boolean grouping is represented by _boolean_ast.
    previous = None
    while value != previous:
        previous = value
        value = re.sub(
            r"\((payload(?:(?:->|->>)'[^']+')+)\)", r"\1", value
        )
    return value


def _strip_outer_parentheses(value: str) -> str:
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quoted = False
        encloses_all = True
        index = 0
        while index < len(value):
            char = value[index]
            if char == "'":
                if quoted and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        encloses_all = False
                        break
            index += 1
        if not encloses_all or depth != 0 or quoted:
            break
        value = value[1:-1].strip()
    return value


def _split_boolean(value: str, keyword: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    lower = value.lower()
    while index < len(value):
        char = value[index]
        if char == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif depth == 0 and lower.startswith(keyword, index):
                before = lower[index - 1] if index else " "
                after_index = index + len(keyword)
                after = lower[after_index] if after_index < len(lower) else " "
                if not (before.isalnum() or before == "_") and not (
                    after.isalnum() or after == "_"
                ):
                    parts.append(value[start:index])
                    start = after_index
                    index = after_index
                    continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:])
    return parts


def _boolean_ast(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    value = _normalize_sql(value, compact=False)
    if value.startswith("check"):
        value = value[5:].strip()
    value = _strip_outer_parentheses(value)
    or_parts = _split_boolean(value, "or")
    if len(or_parts) > 1:
        return ("or", tuple(_boolean_ast(part) for part in or_parts))
    and_parts = _split_boolean(value, "and")
    if len(and_parts) > 1:
        return ("and", tuple(_boolean_ast(part) for part in and_parts))
    return ("atom", _compact(_strip_outer_parentheses(value)))


def _exact_int(value: Any) -> int | None:
    return value if type(value) is int else None


def _timestamp_present(value: Any) -> bool:
    if hasattr(value, "iso_format"):
        value = value.iso_format()
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _column_shape(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            row.get("name"), row.get("data_type"), row.get("not_null") is True,
            row.get("collation"),
            _compact(row.get("default_expr")), row.get("identity_kind") or "",
            row.get("generated_kind") or "",
        )
        for row in rows
    ]


def _diagnose_pg_projection(
    *,
    objects: dict[str, Any],
    history_columns: list[dict[str, Any]],
    claims_columns: list[dict[str, Any]],
    aux_columns: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    indexes: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    sequences: list[dict[str, Any]],
    sequence_state: list[dict[str, Any]],
    behavioral_objects: dict[str, Any],
    internal_triggers: list[dict[str, Any]],
    blockers: dict[str, Any],
    critique_rows: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[str] = []
    if objects.get("history_exists") is not True:
        failures.append("pg.history.missing")
    if objects.get("claims_exists") is not True:
        failures.append("pg.history_event_claims.missing")
    if objects.get("metrics_exists") is not True:
        failures.append("pg.metric_snapshots.missing")
    if objects.get("lineage_exists") is not True:
        failures.append("pg.lineage.missing")
    if (
        objects.get("history_kind") != "r"
        or objects.get("history_persistence") != "p"
        or objects.get("claims_kind") != "r"
        or objects.get("claims_persistence") != "p"
        or objects.get("metrics_kind") != "r"
        or objects.get("metrics_persistence") != "p"
        or objects.get("lineage_kind") != "r"
        or objects.get("lineage_persistence") != "p"
        or objects.get("sequence_kind") != "S"
        or objects.get("sequence_persistence") != "p"
        or objects.get("metrics_sequence_kind") != "S"
        or objects.get("metrics_sequence_persistence") != "p"
        or objects.get("lineage_sequence_kind") != "S"
        or objects.get("lineage_sequence_persistence") != "p"
    ):
        failures.append("pg.object.persistence")
    if (
        objects.get("history_has_subclass") is not False
        or objects.get("history_is_partition") is not False
        or objects.get("claims_has_subclass") is not False
        or objects.get("claims_is_partition") is not False
        or objects.get("metrics_has_subclass") is not False
        or objects.get("metrics_is_partition") is not False
        or objects.get("lineage_has_subclass") is not False
        or objects.get("lineage_is_partition") is not False
        or _exact_int(objects.get("inheritance_edges")) != 0
    ):
        failures.append("pg.object.inheritance")

    actual_history_columns = _column_shape(history_columns)
    history_tail = [
        ("ts", "timestamp with time zone", True, None, "now()", "", ""),
        ("tree", "text", True, "pg_catalog.default", "", "", ""),
        ("op", "text", True, "pg_catalog.default", "", "", ""),
        ("node_tag", "text", False, "pg_catalog.default", "", "", ""),
        ("payload", "jsonb", False, None, "", "", ""),
        ("event_id", "text", False, "pg_catalog.default", "", "", ""),
    ]
    id_ok = (
        len(actual_history_columns) == 7
        and actual_history_columns[0][0:4] == ("id", "bigint", True, None)
        and re.fullmatch(
            r"nextval\('(?:public\.)?history_id_seq'(?:::regclass)?\)",
            actual_history_columns[0][4],
        ) is not None
        and actual_history_columns[0][5:] == ("", "")
        and actual_history_columns[1:] == history_tail
    )
    if not id_ok:
        failures.append("pg.history.columns")

    aux_by_table: dict[str, list[dict[str, Any]]] = {
        "metric_snapshots": [], "lineage": [],
    }
    for row in aux_columns:
        table_name = row.get("table_name")
        if table_name in aux_by_table:
            aux_by_table[table_name].append(row)
        else:
            failures.append("pg.aux_columns.projection")
    expected_aux_columns = {
        "metric_snapshots": [
            ("id", "bigint", True, None,
             "nextval('metric_snapshots_id_seq'::regclass)", "", ""),
            ("ts", "timestamp with time zone", True, None, "now()", "", ""),
            ("tree", "text", True, "pg_catalog.default", "", "", ""),
            ("metrics", "jsonb", False, None, "", "", ""),
        ],
        "lineage": [
            ("id", "bigint", True, None,
             "nextval('lineage_id_seq'::regclass)", "", ""),
            ("ts", "timestamp with time zone", True, None, "now()", "", ""),
            ("output", "text", True, "pg_catalog.default", "", "", ""),
            ("output_sha", "text", False, "pg_catalog.default", "", "", ""),
            ("producer", "text", False, "pg_catalog.default", "", "", ""),
            ("producer_sha", "text", False, "pg_catalog.default", "", "", ""),
            ("inputs", "jsonb", False, None, "", "", ""),
            ("params", "jsonb", False, None, "", "", ""),
            ("kind", "text", False, "pg_catalog.default", "", "", ""),
            ("env", "text", False, "pg_catalog.default", "", "", ""),
        ],
    }
    for table_name, expected in expected_aux_columns.items():
        actual = _column_shape(aux_by_table[table_name])
        # pg_get_serial_sequence may deparse the public schema explicitly.
        if actual:
            sequence_name = f"{table_name}_id_seq"
            actual[0] = (
                *actual[0][:4],
                re.sub(
                    rf"nextval\('public\.{re.escape(sequence_name)}'",
                    f"nextval('{sequence_name}'",
                    actual[0][4],
                ),
                *actual[0][5:],
            )
        if actual != expected:
            failures.append(f"pg.{table_name}.columns")

    expected_sequences = {
        "history_id_seq": ("history", "pg.history.id_sequence"),
        "metric_snapshots_id_seq": (
            "metric_snapshots", "pg.metric_snapshots.id_sequence"
        ),
        "lineage_id_seq": ("lineage", "pg.lineage.id_sequence"),
    }
    sequence_by_name = {
        row.get("sequencename"): row for row in sequences
        if isinstance(row.get("sequencename"), str)
    }
    if len(sequence_by_name) != len(sequences):
        failures.append("pg.id_sequence.projection")
    for sequence_name, (table_name, failure) in expected_sequences.items():
        row = sequence_by_name.get(sequence_name, {})
        sequence_ok = (
            row.get("schemaname") == "public"
            and row.get("data_type") == "bigint"
            and _exact_int(row.get("start_value")) == 1
            and _exact_int(row.get("min_value")) == 1
            and _exact_int(row.get("max_value")) == 9223372036854775807
            and _exact_int(row.get("increment_by")) == 1
            and row.get("cycle") is False
            and _exact_int(row.get("cache_size")) == 1
            and row.get("owned_sequence") in (
                sequence_name, f"public.{sequence_name}"
            )
        )
        if not sequence_ok:
            failures.append(failure)

    state_by_table = {
        row.get("table_name"): row for row in sequence_state
        if isinstance(row.get("table_name"), str)
    }
    if len(state_by_table) != len(sequence_state):
        failures.append("pg.id_sequence_head.projection")
    for sequence_name, (table_name, sequence_failure) in expected_sequences.items():
        state = state_by_table.get(table_name, {})
        last_value = _exact_int(state.get("last_value"))
        max_id = state.get("max_id")
        state_ok = (
            state.get("sequence_name") == sequence_name
            and
            last_value is not None
            and type(state.get("is_called")) is bool
            and (
                state.get("is_called") is False
                or last_value < 9223372036854775807
            )
            and (
                max_id is None
                or (_exact_int(max_id) is not None
            and last_value is not None
            and (
                last_value > max_id
                or (last_value == max_id and state.get("is_called") is True)
                ))
            )
        )
        if not state_ok:
            failures.append(sequence_failure + "_head")

    expected_behavioral_keys = {
        "user_triggers", "rewrite_rules", "policies", "rls_tables",
    }
    if set(behavioral_objects) != expected_behavioral_keys:
        failures.append("pg.behavioral_objects.projection")
    elif any(
        _exact_int(behavioral_objects.get(key)) != 0
        for key in expected_behavioral_keys
    ):
        failures.append("pg.behavioral_objects.allowlist")

    actual_internal_triggers = sorted(
        (
            row.get("table_schema"), row.get("table_name"),
            row.get("function_name"), row.get("enabled"),
            row.get("is_internal") is True,
            _exact_int(row.get("trigger_type")), row.get("constraint_name"),
        )
        for row in internal_triggers
    )
    expected_internal_triggers = sorted([
        ("public", "history", "RI_FKey_noaction_del", "O", True, 9,
         "history_event_claims_history_id_fkey"),
        ("public", "history", "RI_FKey_noaction_upd", "O", True, 17,
         "history_event_claims_history_id_fkey"),
        ("public", "history_event_claims", "RI_FKey_check_ins", "O", True, 5,
         "history_event_claims_history_id_fkey"),
        ("public", "history_event_claims", "RI_FKey_check_upd", "O", True, 17,
         "history_event_claims_history_id_fkey"),
    ])
    if actual_internal_triggers != expected_internal_triggers:
        failures.append("pg.internal_triggers")

    expected_claim_columns = [
        ("stable_event_id", "text", True, "pg_catalog.default", "", "", ""),
        ("history_id", "bigint", True, None, "", "", ""),
        ("claimed_at", "timestamp with time zone", True, None, "now()", "", ""),
    ]
    if _column_shape(claims_columns) != expected_claim_columns:
        failures.append("pg.history_event_claims.columns")

    def constraint_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            row.get("name"), row.get("kind"), row.get("validated") is True,
            row.get("table_schema"), row.get("table_name"),
            row.get("referenced_schema"), row.get("referenced_table"),
            row.get("deferrable") is True, row.get("initially_deferred") is True,
            row.get("update_action"), row.get("delete_action"), row.get("match_type"),
            tuple(row.get("columns") or ()),
            tuple(row.get("referenced_columns") or ()),
        )

    actual_constraints = {constraint_tuple(row) for row in constraints}
    expected_constraints = {
        ("history_pkey", "p", True, "public", "history", None, None,
         False, False, " ", " ", " ", ("id",), ()),
        ("history_event_claims_pkey", "p", True, "public",
         "history_event_claims", None, None, False, False, " ", " ", " ",
         ("stable_event_id",), ()),
        ("history_event_claims_history_id_key", "u", True, "public",
         "history_event_claims", None, None, False, False, " ", " ", " ",
         ("history_id",), ()),
        ("history_event_claims_history_id_fkey", "f", True, "public",
         "history_event_claims", "public", "history", False, False,
         "a", "a", "s", ("history_id",), ("id",)),
        ("metric_snapshots_pkey", "p", True, "public",
         "metric_snapshots", None, None, False, False, " ", " ", " ",
         ("id",), ()),
        ("lineage_pkey", "p", True, "public", "lineage", None, None,
         False, False, " ", " ", " ", ("id",), ()),
    }
    if actual_constraints != expected_constraints:
        failures.append("pg.constraints")

    index_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in indexes:
        index_rows.setdefault(
            (str(row.get("table_name")), str(row.get("name"))), []
        ).append(row)
    expected_indexes = {
        ("history", "history_pkey"): (
            ("id",), "", True, (0,), ("pg_catalog.int8_ops",), (None,),
        ),
        ("history", "idx_history_tree_ts"): (
            ("tree", "ts"), "", False, (0, 3),
            ("pg_catalog.text_ops", "pg_catalog.timestamptz_ops"),
            ("pg_catalog.default", None),
        ),
        ("history", "uq_history_event_id"): (
            ("event_id",), "event_idisnotnull", True, (0,),
            ("pg_catalog.text_ops",), ("pg_catalog.default",),
        ),
        ("history", "uq_history_critique_logical_identity"): (
            ("tree", "payload->>'arg_id'"), "op='critique'", True, (0, 0),
            ("pg_catalog.text_ops", "pg_catalog.text_ops"),
            ("pg_catalog.default", "pg_catalog.default"),
        ),
        ("history_event_claims", "history_event_claims_pkey"): (
            ("stable_event_id",), "", True, (0,),
            ("pg_catalog.text_ops",), ("pg_catalog.default",),
        ),
        ("history_event_claims", "history_event_claims_history_id_key"): (
            ("history_id",), "", True, (0,),
            ("pg_catalog.int8_ops",), (None,),
        ),
        ("metric_snapshots", "metric_snapshots_pkey"): (
            ("id",), "", True, (0,),
            ("pg_catalog.int8_ops",), (None,),
        ),
        ("lineage", "lineage_pkey"): (
            ("id",), "", True, (0,),
            ("pg_catalog.int8_ops",), (None,),
        ),
        ("lineage", "idx_lineage_output"): (
            ("output",), "", False, (0,),
            ("pg_catalog.text_ops",), ("pg_catalog.default",),
        ),
    }
    if set(index_rows) != set(expected_indexes):
        failures.append("pg.index.allowlist")
    for identity, expected in expected_indexes.items():
        keys, predicate, unique, options, opclasses, collations = expected
        candidates = index_rows.get(identity, [])
        valid = len(candidates) == 1
        if valid:
            row = candidates[0]
            actual_keys = tuple(
                _compact(_strip_outer_parentheses(str(item)))
                for item in (row.get("keys") or ())
            )
            valid = (
                row.get("table_schema") == "public"
                and row.get("table_name") == identity[0]
                and row.get("access_method") == "btree"
                and row.get("is_unique") is unique
                and row.get("is_exclusion") is False
                and row.get("is_valid") is True
                and row.get("is_ready") is True
                and row.get("is_live") is True
                and row.get("nulls_not_distinct") is False
                and _exact_int(row.get("key_count")) == len(keys)
                and _exact_int(row.get("total_count")) == len(keys)
                and actual_keys == keys
                and tuple(row.get("options") or ()) == options
                and tuple(row.get("opclasses") or ()) == opclasses
                and tuple(row.get("collations") or ()) == collations
                and _compact(_strip_outer_parentheses(row.get("predicate") or ""))
                == predicate
            )
        if not valid:
            failures.append(f"pg.index.{identity[0]}.{identity[1]}")

    expected_identity_check = """
      op <> 'critique' OR (
        payload IS NOT NULL
        AND jsonb_typeof(payload)='object'
        AND payload ? 'arg_id'
        AND jsonb_typeof(payload->'arg_id')='string'
        AND payload->>'arg_id' <> ''
        AND strpos(payload->>'arg_id','/')=0
      )
    """
    expected_stable_event_check = """
      op <> 'critique' OR event_id IS NULL
      OR event_id ~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'
    """
    history_checks = [
        row for row in checks if row.get("table_name") == "history"
    ]
    claims_checks = [
        row for row in checks if row.get("table_name") == "history_event_claims"
    ]
    aux_checks = [
        row for row in checks
        if row.get("table_name") in {"metric_snapshots", "lineage"}
    ]
    checks_by_name = {str(row.get("name")): row for row in history_checks}
    identity_check = checks_by_name.get("ck_history_critique_identity", {})
    stable_event_check = checks_by_name.get(
        "ck_history_new_critique_stable_event", {}
    )
    if not (
        len(history_checks) == 2
        and identity_check.get("validated") is True
        and _boolean_ast(identity_check.get("expression"))
        == _boolean_ast(expected_identity_check)
    ):
        failures.append("pg.check.ck_history_critique_identity")
    if not (
        len(history_checks) == 2
        and stable_event_check.get("validated") is False
        and _boolean_ast(stable_event_check.get("expression"))
        == _boolean_ast(expected_stable_event_check)
    ):
        failures.append("pg.check.ck_history_new_critique_stable_event")
    if claims_checks:
        failures.append("pg.check.history_event_claims_allowlist")
    if aux_checks:
        failures.append("pg.check.aux_allowlist")

    expected_blocker_keys = {
        "malformed_critique_rows", "duplicate_critique_identities",
        "duplicate_event_ids", "unclaimed_stable_critique_rows",
    }
    if set(blockers) != expected_blocker_keys:
        failures.append("pg.blocker_projection.incomplete")
    for key in sorted(expected_blocker_keys):
        if _exact_int(blockers.get(key)) != 0:
            failures.append(f"pg.blocker.{key}")

    claim_by_history = {
        row.get("history_id"): row.get("stable_event_id") for row in claims
    }
    bad_critique_rows = 0
    for row in critique_rows:
        payload = row.get("payload")
        arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
        event_id = row.get("event_id")
        tree = row.get("tree")
        expected_stable = (
            history_event_id(tree, "critique", f"{tree}/{arg_id}")
            if isinstance(tree, str) and isinstance(arg_id, str) and arg_id
            else None
        )
        try:
            validate_history_record(tree, "critique", row.get("node_tag"), payload, event_id)
        except (TypeError, ValueError, UnicodeError):
            bad_critique_rows += 1
            continue
        event_ok = (
            event_id is None
            or (isinstance(event_id, str) and re.fullmatch(r"ob-[A-Za-z0-9._:-]+", event_id))
            or (event_id == expected_stable and claim_by_history.get(row.get("history_id")) == expected_stable)
        )
        if not event_ok:
            bad_critique_rows += 1
    if bad_critique_rows:
        failures.append("pg.history.critique_binding")

    bad_claims = 0
    for row in claims:
        payload = row.get("payload")
        arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
        stable_id = row.get("stable_event_id")
        tree = row.get("tree")
        row_event_id = row.get("event_id")
        valid = (
            isinstance(tree, str) and bool(tree)
            and row.get("op") == "critique"
            and isinstance(arg_id, str) and bool(arg_id) and "/" not in arg_id
            and stable_id == history_event_id(tree, "critique", f"{tree}/{arg_id}")
            and (
                row_event_id is None
                or row_event_id == stable_id
                or (
                    isinstance(row_event_id, str)
                    and re.fullmatch(r"ob-[A-Za-z0-9._:-]+", row_event_id)
                )
            )
        )
        if not valid:
            bad_claims += 1
    if bad_claims:
        failures.append("pg.history_event_claims.binding")

    return {
        "contract_id": CONTRACT_ID,
        "ok": not failures,
        "failures": failures,
        "details": {
            "critique_rows_checked": len(critique_rows),
            "bad_critique_rows": bad_critique_rows,
            "claim_rows_checked": len(claims),
            "bad_claims": bad_claims,
            "blockers": blockers,
        },
    }


def _empty_pg_diagnosis(objects: dict[str, Any]) -> dict[str, Any]:
    return _diagnose_pg_projection(
        objects=objects, history_columns=[], claims_columns=[], constraints=[],
        aux_columns=[],
        indexes=[], checks=[], sequences=[], sequence_state=[],
        behavioral_objects={}, internal_triggers=[], blockers={},
        critique_rows=[], claims=[],
    )


def inspect_pg_history_contract(conn: Any) -> dict[str, Any]:
    """Inspect the public PostgreSQL schema and all critique/claim bindings."""

    with conn.cursor() as cur:
        cur.execute(_PG_OBJECTS_SQL)
        objects = _one(cur)
        if not all(
            objects.get(key) is True
            for key in (
                "history_exists", "claims_exists", "metrics_exists",
                "lineage_exists",
            )
        ):
            return _empty_pg_diagnosis(objects)
        cur.execute(_PG_HISTORY_COLUMNS_SQL)
        history_columns = _rows(cur)
        cur.execute(_PG_CLAIMS_COLUMNS_SQL)
        claims_columns = _rows(cur)
        cur.execute(_PG_AUX_COLUMNS_SQL)
        aux_columns = _rows(cur)
        cur.execute(_PG_CONSTRAINTS_SQL)
        constraints = _rows(cur)
        cur.execute(_PG_HISTORY_INDEXES_SQL)
        indexes = _rows(cur)
        cur.execute(_PG_HISTORY_CHECK_SQL)
        checks = _rows(cur)
        cur.execute(_PG_HISTORY_SEQUENCE_SQL)
        sequences = _rows(cur)
        sequence_state: list[dict[str, Any]] = []
        if len(sequences) == 3:
            cur.execute(_PG_HISTORY_SEQUENCE_STATE_SQL)
            sequence_state = _rows(cur)
        cur.execute(_PG_BEHAVIORAL_OBJECTS_SQL)
        behavioral_objects = _one(cur)
        cur.execute(_PG_INTERNAL_TRIGGERS_SQL)
        internal_triggers = _rows(cur)
        cur.execute(_PG_BLOCKERS_SQL)
        blockers = _one(cur)
        cur.execute(_PG_CRITIQUE_ROWS_SQL)
        critique_rows = _rows(cur)
        cur.execute(_PG_CLAIMS_ROWS_SQL)
        claims = _rows(cur)
    return _diagnose_pg_projection(
        objects=objects, history_columns=history_columns,
        claims_columns=claims_columns, aux_columns=aux_columns,
        constraints=constraints,
        indexes=indexes, checks=checks, sequences=sequences,
        sequence_state=sequence_state, behavioral_objects=behavioral_objects,
        internal_triggers=internal_triggers,
        blockers=blockers,
        critique_rows=critique_rows, claims=claims,
    )


def pg_projection_rows(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(_PG_PROJECTION_ROWS_SQL)
        return _rows(cur)


def _diagnose_neo_outbox_projection(
    constraint_rows: Iterable[dict[str, Any]],
    identity_rows: Iterable[dict[str, Any]],
    outbox_rows: Iterable[dict[str, Any]] = (),
    pg_rows: Iterable[dict[str, Any]] | None = None,
    *,
    require_canonical_payload: bool = True,
    argument_identity_rows: Iterable[dict[str, Any]] = (),
    writer_lease_identity_rows: Iterable[dict[str, Any]] | None = None,
    causal_receipt_rows: Iterable[dict[str, Any]] | None = None,
    admin_authority_rows: Iterable[dict[str, Any]] | None = None,
    prediction_authority_rows: Iterable[dict[str, Any]] | None = None,
    receipt_chain_node_rows: Iterable[dict[str, Any]] | None = None,
    receipt_identity_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    constraints = [dict(row) for row in constraint_rows]
    identities = [dict(row) for row in identity_rows]
    entries = [dict(row) for row in outbox_rows]
    projections = None if pg_rows is None else [dict(row) for row in pg_rows]
    failures: list[str] = []
    receipt_chain_checked = (
        receipt_chain_node_rows is not None and receipt_identity_rows is not None
    )
    chain_index = None
    bad_receipt_chains = 0
    if receipt_chain_checked:
        try:
            chain_index = validate_receipt_graph(
                receipt_chain_node_rows or (), receipt_identity_rows or ()
            )
        except ReceiptGraphError:
            bad_receipt_chains = 1
            failures.append("neo4j.receipt_chain")
    uniqueness_types = {
        "UNIQUENESS", "NODE_UNIQUENESS", "NODE_PROPERTY_UNIQUENESS",
    }
    expected_constraints = {
        "lkt_outbox_id_unique": ("OutboxEntry", "id"),
        "lkt_argument_id_unique": ("LakatosArgument", "id"),
        "lkt_runtime_writer_lease_name_unique": (
            "RuntimeWriterLease", "name"
        ),
    }
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in constraints:
        by_name.setdefault(str(row.get("name")), []).append(row)
    for name, (label, prop) in expected_constraints.items():
        candidates = by_name.get(name, [])
        if not candidates:
            failures.append(f"neo4j.constraint.{name}.missing")
            continue
        exact = (
            len(candidates) == 1
            and candidates[0].get("type") in uniqueness_types
            and candidates[0].get("entityType") == "NODE"
            and tuple(candidates[0].get("labelsOrTypes") or ()) == (label,)
            and tuple(candidates[0].get("properties") or ()) == (prop,)
        )
        if not exact:
            failures.append(f"neo4j.constraint.{name}.shape")
    unexpected_constraint_names = sorted(set(by_name) - set(expected_constraints))
    if unexpected_constraint_names:
        failures.append("neo4j.constraint.allowlist")

    bad_identities = sum(
        not (
            isinstance(row.get("id"), str)
            and re.fullmatch(
                r"(?:ob-[A-Za-z0-9._:-]+|ph-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})",
                row["id"],
            )
            and _exact_int(row.get("copies")) == 1
        )
        for row in identities
    )
    if bad_identities:
        failures.append("neo4j.outbox.identity")
    argument_identities = [dict(row) for row in argument_identity_rows]
    bad_argument_identities = sum(
        not (
            isinstance(row.get("id"), str)
            and bool(row["id"])
            and _exact_int(row.get("copies")) == 1
        )
        for row in argument_identities
    )
    if bad_argument_identities:
        failures.append("neo4j.argument.identity")
    writer_lease_identities = (
        None
        if writer_lease_identity_rows is None
        else [dict(row) for row in writer_lease_identity_rows]
    )
    bad_writer_lease_identities = 0
    if writer_lease_identities is not None:
        valid_writer_lease = (
            len(writer_lease_identities) == 1
            and writer_lease_identities[0].get("name")
                == "critique-history-writer-v1"
            and _exact_int(writer_lease_identities[0].get("copies")) == 1
            and isinstance(
                _exact_int(writer_lease_identities[0].get("generation")), int
            )
            and _exact_int(writer_lease_identities[0].get("generation")) >= 0
            and (
                writer_lease_identities[0].get("owner_token") is None
                or (
                    isinstance(
                        writer_lease_identities[0].get("owner_token"), str
                    )
                    and bool(writer_lease_identities[0]["owner_token"])
                )
            )
        )
        bad_writer_lease_identities = 0 if valid_writer_lease else 1
        if bad_writer_lease_identities:
            failures.append("neo4j.writer_lease.identity")

    canonical_by_id: dict[str, dict[str, Any]] = {}
    bad_entries = 0
    noncanonical_entries = 0
    bad_argument_bindings = 0
    bad_causal_bindings = 0
    causal_groups: dict[str, list[dict[str, Any]]] = {}
    admin_candidates: dict[str, dict[str, Any]] = {}
    prediction_candidates: dict[str, dict[str, Any]] = {}
    pending_entries = 0
    for row in entries:
        event_id = row.get("id")
        payload_text = row.get("payload")
        try:
            payload = json.loads(payload_text) if isinstance(payload_text, str) else None
            canonical_payload = validate_history_record(
                row.get("tree"), row.get("op"), row.get("node_tag"), payload, event_id
            )
        except (TypeError, ValueError, UnicodeError):
            bad_entries += 1
            continue
        reason = row.get("reason")
        status = row.get("status")
        stable = isinstance(event_id, str) and event_id.startswith("he-")
        arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
        critique_payload_ok = (
            row.get("op") != "critique"
            or (
                isinstance(payload, dict)
                and set(payload) == {"arg_id", "attacks", "by", "kind", "body"}
            )
        )
        if payload_text != canonical_payload:
            noncanonical_entries += 1
        identity_ok = (
            isinstance(event_id, str)
            and re.fullmatch(
                r"(?:ob-[A-Za-z0-9._:-]+|ph-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})",
                event_id,
            )
        )
        provenance_ok = (
            _timestamp_present(row.get("created_at"))
            and isinstance(reason, str) and bool(reason)
            and (
                not stable
                or (
                    row.get("op") == "critique"
                    and isinstance(arg_id, str) and bool(arg_id) and "/" not in arg_id
                    and isinstance(row.get("node_tag"), str) and bool(row.get("node_tag"))
                    and reason == "critique_commit_intent"
                    and event_id == history_event_id(
                        row["tree"], "critique", f"{row['tree']}/{arg_id}"
                    )
                )
            )
        )
        adoption_ok = (
            status != "adopted"
            or (
                isinstance(event_id, str) and event_id.startswith("ob-")
                and
                row.get("op") == "critique"
                and isinstance(arg_id, str) and bool(arg_id) and "/" not in arg_id
                and isinstance(row.get("node_tag"), str) and bool(row.get("node_tag"))
                and row.get("adopted_by") == history_event_id(
                    row["tree"], "critique", f"{row['tree']}/{arg_id}"
                )
            )
        )
        state_ok = (
            status == "pending" and row.get("applied_at") is None
            and row.get("adopted_at") is None and row.get("adopted_by") is None
        ) or (
            status == "applied" and _timestamp_present(row.get("applied_at"))
            and row.get("adopted_at") is None and row.get("adopted_by") is None
        ) or (
            status == "adopted" and _timestamp_present(row.get("adopted_at"))
            and isinstance(row.get("adopted_by"), str)
            and re.fullmatch(r"he-[0-9a-f]{64}", row["adopted_by"])
        )
        causal_specs = {
            ("test_result", "test_result_commit_intent"): (0, "test-result"),
            ("question_close", "question_close_commit_intent"): (1, "question-close"),
            ("cycle_result", "cycle_result_commit_intent"): (2, "cycle-result"),
        }
        stable_causal_namespace = (
            isinstance(event_id, str)
            and re.fullmatch(
                r"ob-(?:test-result|question-close|cycle-result)-[0-9a-f]{64}",
                event_id,
            ) is not None
        )
        causal_kind = causal_specs.get((row.get("op"), reason))
        causal_expected = (
            row.get("op") in {"test_result", "question_close", "cycle_result"}
            or stable_causal_namespace
            or causal_kind is not None
        )
        if causal_expected:
            group = row.get("causal_group")
            index = row.get("causal_index")
            causal_ok = (
                causal_kind is not None
                and isinstance(group, str)
                and re.fullmatch(r"[0-9a-f]{64}", group) is not None
                and index == causal_kind[0]
                and row.get("receipt_sha") == group
                and isinstance(payload, dict)
                and (
                    (index == 0
                     and event_id == f"ob-test-result-{group}"
                     and payload.get("receipt_sha") == group
                     and isinstance(row.get("request_sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", row["request_sha256"])
                         is not None)
                    or (index == 1
                        and event_id == f"ob-question-close-{group}"
                        and payload.get("receipt_sha") == group)
                    or (index == 2
                        and event_id.startswith("ob-cycle-result-")
                        and payload.get("verdict_receipt_sha") == group)
                )
            )
            if not causal_ok:
                bad_causal_bindings += 1
            elif isinstance(group, str):
                causal_groups.setdefault(group, []).append(row)
        elif row.get("causal_group") is not None or row.get("causal_index") is not None:
            bad_causal_bindings += 1
        if not (
            identity_ok
            and (not require_canonical_payload or payload_text == canonical_payload)
            and critique_payload_ok
            and provenance_ok
            and adoption_ok
            and state_ok
        ):
            bad_entries += 1
            continue
        if status == "pending":
            pending_entries += 1
        if (
            isinstance(event_id, str)
            and (
                row.get("op") == "verdict"
                or
                event_id.startswith("ob-verdict-")
                or reason == "verdict_commit_intent"
            )
        ):
            admin_candidates[event_id] = row
        if (
            isinstance(event_id, str)
            and (
                row.get("op") == "prediction_register"
                or
                event_id.startswith("ob-prediction-register-")
                or reason == "prediction_register_commit_intent"
            )
        ):
            prediction_candidates[event_id] = row
        if row.get("op") == "critique" and row.get("argument_copies") != 1:
            bad_argument_bindings += 1
        canonical_by_id[event_id] = {**row, "canonical_payload": canonical_payload}
    if bad_entries:
        failures.append("neo4j.outbox.record")
    if bad_argument_bindings:
        failures.append("neo4j.outbox.argument_binding")
    if bad_causal_bindings:
        failures.append("neo4j.outbox.causal_binding")

    causal_authorities = (
        []
        if causal_receipt_rows is None
        else [dict(row) for row in causal_receipt_rows]
    )
    causal_authorities_by_group: dict[str, list[dict[str, Any]]] = {}
    for row in causal_authorities:
        group = row.get("group")
        if isinstance(group, str):
            causal_authorities_by_group.setdefault(group, []).append(row)
    bad_causal_receipts = 0
    for group, members in causal_groups.items():
        scopes = {
            (row.get("tree"), row.get("node_tag")) for row in members
        }
        candidates = causal_authorities_by_group.get(group, [])
        valid = len(scopes) == 1 and len(candidates) == 1
        if valid:
            tree, tag = next(iter(scopes))
            candidate = candidates[0]
            valid = (
                candidate.get("expected_tree") == tree
                and candidate.get("expected_tag") == tag
                and _exact_int(candidate.get("trees")) == 1
                and _exact_int(candidate.get("nodes")) == 1
                and _exact_int(candidate.get("bindings")) == 1
                and _exact_int(candidate.get("receipts")) == 1
                and isinstance(candidate.get("receipt"), dict)
            )
        if valid:
            receipt = candidate["receipt"]
            current = {
                "current_receipt_sha": candidate.get("current_receipt_sha"),
                "verdict": candidate.get("current_verdict"),
                "verdict_source": candidate.get("current_verdict_source"),
                "lakatos_status": candidate.get("current_lakatos_status"),
                "metric_value": candidate.get("current_metric_value"),
            }
            closure = {
                "question_state": candidate.get("question_state"),
                "question_closed_by": candidate.get("question_closed_by"),
                "question_closed_events": candidate.get(
                    "question_closed_events"
                ),
                "closure_id": candidate.get("closure_id"),
                "closure_closed_by": candidate.get("closure_closed_by"),
                "closure_at": candidate.get("closure_at"),
                "closure_tree": candidate.get("closure_tree"),
                "closure_question": candidate.get("closure_question"),
                "closure_trigger": candidate.get("closure_trigger"),
                "closure_verdict": candidate.get("closure_verdict"),
                "closure_receipt_sha": candidate.get("closure_receipt_sha"),
                "closure_bound": (
                    _exact_int(candidate.get("closure_bound_count")) == 1
                ),
                "closure_global_count": _exact_int(
                    candidate.get("closure_global_count")
                ),
                "closes_rel_count": _exact_int(
                    candidate.get("closes_rel_count")
                ),
                "closes_rel_receipt_sha": candidate.get(
                    "closes_rel_receipt_sha"
                ),
                "closes_rel_verdict": candidate.get(
                    "closes_rel_verdict"
                ),
                "closes_rel_at": candidate.get("closes_rel_at"),
            }
            try:
                validate_verdict_intent_group(
                    tree=tree,
                    tag=tag,
                    receipt_sha=group,
                    receipt=receipt,
                    current=current,
                    outboxes=members,
                    closure=closure,
                    require_current_effect=any(
                        row.get("status") == "pending" for row in members
                    ),
                )
            except VerdictIntentError:
                valid = False
            if (
                valid
                and chain_index is not None
                and group not in chain_index.ancestors_by_scope.get(
                    (str(tree), str(tag)), frozenset()
                )
            ):
                valid = False
        if not valid:
            bad_causal_receipts += 1
    if bad_causal_receipts:
        failures.append("neo4j.outbox.causal_receipt_v6")

    admin_authorities = (
        []
        if admin_authority_rows is None
        else [dict(row) for row in admin_authority_rows]
    )
    admin_authorities_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in admin_authorities:
        event_id = row.get("event_id")
        if isinstance(event_id, str):
            admin_authorities_by_id.setdefault(event_id, []).append(row)
    bad_admin_intents = 0
    compared_outbox_fields = (
        "id", "tree", "op", "node_tag", "payload", "status",
        "created_at", "reason", "applied_at", "adopted_by", "adopted_at",
        "receipt_sha", "demoted_tag", "demoted_receipt_sha",
    )
    for event_id, entry in admin_candidates.items():
        candidates = admin_authorities_by_id.get(event_id, [])
        if len(candidates) != 1:
            bad_admin_intents += 1
            continue
        authority = candidates[0]
        outbox = authority.get("outbox")
        receipt = authority.get("receipt")
        if not isinstance(outbox, dict) or not isinstance(receipt, dict):
            bad_admin_intents += 1
            continue
        if any(
            outbox.get(field) != entry.get(field)
            for field in compared_outbox_fields
        ):
            bad_admin_intents += 1
            continue
        try:
            validate_admin_verdict_intent(
                tree=outbox.get("tree"),
                tag=outbox.get("node_tag"),
                receipt_sha=outbox.get("receipt_sha"),
                receipt=receipt,
                current={
                    "current_receipt_sha": authority.get(
                        "current_receipt_sha"
                    ),
                    "verdict": authority.get("current_verdict"),
                    "verdict_source": authority.get(
                        "current_verdict_source"
                    ),
                },
                outbox=outbox,
                demoted_receipt=authority.get("demoted_receipt"),
                demoted_current=authority.get("demoted_current"),
                require_current_effect=entry.get("status") == "pending",
            )
        except AdminIntentError:
            bad_admin_intents += 1
            continue
        if chain_index is not None:
            promoted_scope = (str(outbox.get("tree")), str(outbox.get("node_tag")))
            if outbox.get("receipt_sha") not in chain_index.ancestors_by_scope.get(
                promoted_scope, frozenset()
            ):
                bad_admin_intents += 1
                continue
            demoted_tag = outbox.get("demoted_tag")
            if demoted_tag is not None and outbox.get(
                "demoted_receipt_sha"
            ) not in chain_index.ancestors_by_scope.get(
                (str(outbox.get("tree")), str(demoted_tag)), frozenset()
            ):
                bad_admin_intents += 1
    if bad_admin_intents:
        failures.append("neo4j.outbox.admin_intent")

    prediction_authorities = (
        []
        if prediction_authority_rows is None
        else [dict(row) for row in prediction_authority_rows]
    )
    prediction_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in prediction_authorities:
        event_id = row.get("event_id")
        if isinstance(event_id, str):
            prediction_by_id.setdefault(event_id, []).append(row)
    bad_prediction_intents = 0
    prediction_fields = (
        "id", "tree", "op", "node_tag", "payload", "status",
        "created_at", "reason", "applied_at", "adopted_by", "adopted_at",
        "receipt_sha", "causal_group", "causal_index", "request_sha256",
        "demoted_tag", "demoted_receipt_sha",
    )
    for event_id, entry in prediction_candidates.items():
        candidates = prediction_by_id.get(event_id, [])
        if len(candidates) != 1:
            bad_prediction_intents += 1
            continue
        authority = candidates[0]
        outbox = authority.get("outbox")
        receipt = authority.get("receipt")
        current = authority.get("current")
        if not (
            _exact_int(authority.get("trees")) == 1
            and _exact_int(authority.get("nodes")) == 1
            and _exact_int(authority.get("bindings")) == 1
            and _exact_int(authority.get("receipts")) == 1
            and isinstance(outbox, dict)
            and isinstance(receipt, dict)
            and isinstance(current, dict)
            and not any(
                outbox.get(field) != entry.get(field)
                for field in prediction_fields
            )
        ):
            bad_prediction_intents += 1
            continue
        receipt_sha = outbox.get("receipt_sha")
        try:
            validate_prediction_register_intent(
                tree=outbox.get("tree"),
                tag=outbox.get("node_tag"),
                receipt_sha=receipt_sha,
                receipt=receipt,
                current=current,
                outbox=outbox,
                require_current_effect=entry.get("status") == "pending",
            )
        except PredictionIntentError:
            bad_prediction_intents += 1
            continue
        if (
            chain_index is not None
            and receipt_sha not in chain_index.ancestors_by_scope.get(
                (str(outbox.get("tree")), str(outbox.get("node_tag"))),
                frozenset(),
            )
        ):
            bad_prediction_intents += 1
    if bad_prediction_intents:
        failures.append("neo4j.outbox.prediction_intent_v3")
    if pending_entries:
        failures.append("neo4j.outbox.pending")

    cross_store_mismatches = 0
    if projections is not None:
        by_event: dict[str, list[dict[str, Any]]] = {}
        by_stable: dict[str, list[dict[str, Any]]] = {}
        adopted_by_stable: dict[str, list[dict[str, Any]]] = {}
        for row in projections:
            if isinstance(row.get("event_id"), str):
                by_event.setdefault(row["event_id"], []).append(row)
            if isinstance(row.get("stable_event_id"), str):
                by_stable.setdefault(row["stable_event_id"], []).append(row)
        for entry in canonical_by_id.values():
            if (
                entry.get("status") == "adopted"
                and isinstance(entry.get("adopted_by"), str)
            ):
                adopted_by_stable.setdefault(entry["adopted_by"], []).append(entry)
        cross_store_mismatches += sum(
            1 for aliases in adopted_by_stable.values() if len(aliases) > 1
        )

        def exact_content(entry: dict[str, Any], row: dict[str, Any]) -> bool:
            try:
                projected = validate_history_record(
                    row.get("tree"), row.get("op"), row.get("node_tag"),
                    row.get("payload"), row.get("event_id"),
                )
            except (TypeError, ValueError, UnicodeError):
                return False
            return (
                row.get("tree") == entry.get("tree")
                and row.get("op") == entry.get("op")
                and row.get("node_tag") == entry.get("node_tag")
                and projected == entry.get("canonical_payload")
            )

        for event_id, entry in canonical_by_id.items():
            if entry.get("status") == "pending":
                continue
            if event_id.startswith("he-"):
                candidates = by_stable.get(event_id, [])
            elif entry.get("status") == "adopted":
                candidates = by_stable.get(entry.get("adopted_by"), [])
            else:
                candidates = by_event.get(event_id, [])
            if len(candidates) != 1 or not exact_content(entry, candidates[0]):
                cross_store_mismatches += 1
            elif entry.get("status") == "adopted" and (
                candidates[0].get("stable_event_id") != entry.get("adopted_by")
            ):
                cross_store_mismatches += 1

        for row in projections:
            event_id = row.get("event_id")
            stable_id = row.get("stable_event_id")
            if isinstance(event_id, str) and event_id.startswith("ob-"):
                entry = canonical_by_id.get(event_id)
                recoverable_pending = (
                    entry is not None
                    and entry.get("status") == "pending"
                    and exact_content(entry, row)
                )
                if isinstance(stable_id, str):
                    alias_ok = (
                        entry is not None
                        and entry.get("status") == "adopted"
                        and entry.get("adopted_by") == stable_id
                        and exact_content(entry, row)
                    ) or recoverable_pending
                else:
                    alias_ok = (
                        entry is not None
                        and entry.get("status") == "applied"
                        and exact_content(entry, row)
                    ) or recoverable_pending
                if not alias_ok:
                    cross_store_mismatches += 1
            if isinstance(stable_id, str):
                entry = canonical_by_id.get(stable_id)
                adopted = adopted_by_stable.get(stable_id, [])
                stable_ok = (
                    entry is not None
                    and entry.get("status") == "applied"
                    and exact_content(entry, row)
                )
                pending_ok = (
                    entry is not None
                    and entry.get("status") == "pending"
                    and exact_content(entry, row)
                )
                adopted_ok = (
                    len(adopted) == 1
                    and adopted[0].get("status") == "adopted"
                    and exact_content(adopted[0], row)
                )
                if not (stable_ok or pending_ok or adopted_ok):
                    cross_store_mismatches += 1
        if cross_store_mismatches:
            failures.append("cross_store.outbox_projection")

    return {
        "contract_id": CONTRACT_ID,
        "ok": not failures,
        "failures": failures,
        "details": {
            "outbox_identities_checked": len(identities),
            "outbox_rows_checked": len(entries),
            "bad_outbox_identities": bad_identities,
            "argument_identities_checked": len(argument_identities),
            "bad_argument_identities": bad_argument_identities,
            "writer_lease_identities_checked": (
                None
                if writer_lease_identities is None
                else len(writer_lease_identities)
            ),
            "bad_writer_lease_identities": bad_writer_lease_identities,
            "bad_outbox_rows": bad_entries,
            "noncanonical_outbox_rows": noncanonical_entries,
            "bad_argument_bindings": bad_argument_bindings,
            "bad_causal_bindings": bad_causal_bindings,
            "causal_receipt_groups_checked": len(causal_groups),
            "bad_causal_receipts": bad_causal_receipts,
            "admin_intents_checked": len(admin_candidates),
            "bad_admin_intents": bad_admin_intents,
            "prediction_intents_checked": len(prediction_candidates),
            "bad_prediction_intents": bad_prediction_intents,
            "receipt_chain_checked": receipt_chain_checked,
            "bad_receipt_chains": bad_receipt_chains,
            "pending_outbox_rows": pending_entries,
            "cross_store_checked": projections is not None,
            "cross_store_mismatches": cross_store_mismatches,
            "unexpected_constraint_names": unexpected_constraint_names,
        },
    }


def inspect_neo_outbox_contract(
    kg: Callable[..., list[dict[str, Any]]],
    *,
    projection_rows: list[dict[str, Any]] | None = None,
    require_canonical_payload: bool = True,
) -> dict[str, Any]:
    entries = [dict(row) for row in kg(_NEO_OUTBOX_ROWS_CYPHER)]
    stable_specs: list[dict[str, str]] = []
    for row in entries:
        event_id = row.get("id")
        try:
            payload = json.loads(row.get("payload"))
        except (TypeError, ValueError):
            continue
        arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
        if (
            isinstance(event_id, str)
            and row.get("op") == "critique"
            and isinstance(row.get("tree"), str)
            and isinstance(row.get("node_tag"), str)
            and isinstance(arg_id, str)
            and all(
                isinstance(payload.get(field), str)
                for field in ("by", "kind", "body", "attacks")
            )
        ):
            stable_specs.append({
                "id": event_id, "tree": row["tree"], "tag": row["node_tag"],
                "arg_full": f"{row['tree']}/{arg_id}",
                "arg_id": arg_id,
                "by": payload["by"],
                "kind": payload["kind"],
                "body": payload["body"],
                "attacks": payload["attacks"],
            })
    bindings: dict[str, int] = {}
    if stable_specs:
        binding_rows = kg(
            "UNWIND $specs AS spec "
            "OPTIONAL MATCH (t:LakatosTree {name:spec.tree})-[:HAS_NODE]->"
            "(e {tag:spec.tag})-[:HAS_ARGUMENT]->"
            "(a:Argument:LakatosArgument {id:spec.arg_full}) "
            "RETURN spec.id AS id, count(DISTINCT t) AS trees, "
            "count(DISTINCT e) AS nodes, "
            "COUNT { MATCH (any:Argument {id:spec.arg_full}) } AS arguments, "
            "COUNT { MATCH (owner)-[:HAS_ARGUMENT]->"
            "        (:Argument {id:spec.arg_full}) } AS owners, "
            "count(DISTINCT CASE WHEN a.tree_name=spec.tree "
            "  AND a.local_id=spec.arg_id AND a.by=spec.by "
            "  AND a.kind=spec.kind AND a.body=spec.body "
            "  AND a.attacks=spec.attacks AND a.at IS NOT NULL "
            "  AND a._argument_create_claim IS NULL "
            "  THEN a END) AS exact_bindings",
            specs=stable_specs,
        )
        for row in binding_rows:
            bindings[str(row.get("id"))] = 1 if (
                row.get("trees") == 1
                and row.get("nodes") == 1
                and row.get("arguments") == 1
                and row.get("owners") == 1
                and row.get("exact_bindings") == 1
            ) else 0
    for row in entries:
        if (
            isinstance(row.get("id"), str)
            and row.get("op") == "critique"
        ):
            row["argument_copies"] = bindings.get(row["id"], 0)
    causal_specs = sorted({
        (row.get("causal_group"), row.get("tree"), row.get("node_tag"))
        for row in entries
        if isinstance(row.get("causal_group"), str)
        and re.fullmatch(r"[0-9a-f]{64}", row["causal_group"]) is not None
        and isinstance(row.get("tree"), str)
        and isinstance(row.get("node_tag"), str)
    })
    causal_receipt_rows: Iterable[dict[str, Any]] = ()
    if causal_specs:
        causal_receipt_rows = kg(
            _NEO_CAUSAL_RECEIPT_AUTHORITIES_CYPHER,
            specs=[
                {"group": group, "tree": tree, "tag": tag}
                for group, tree, tag in causal_specs
            ],
        )
    return _diagnose_neo_outbox_projection(
        kg(_NEO_OUTBOX_CONSTRAINT_SQL),
        kg(_NEO_OUTBOX_IDENTITIES_CYPHER),
        entries,
        projection_rows,
        require_canonical_payload=require_canonical_payload,
        argument_identity_rows=kg(_NEO_ARGUMENT_IDENTITIES_CYPHER),
        writer_lease_identity_rows=kg(_NEO_WRITER_LEASE_IDENTITIES_CYPHER),
        causal_receipt_rows=causal_receipt_rows,
        admin_authority_rows=kg(_NEO_ADMIN_AUTHORITY_CYPHER),
        prediction_authority_rows=kg(_NEO_PREDICTION_AUTHORITY_CYPHER),
        receipt_chain_node_rows=kg(_NEO_RECEIPT_CHAIN_ROWS_CYPHER),
        receipt_identity_rows=kg(_NEO_RECEIPT_IDENTITIES_CYPHER),
    )


def inspect_storage_contract(container: Any) -> dict[str, Any]:
    with container.pg() as conn:
        pg_report = inspect_pg_history_contract(conn)
        projections = pg_projection_rows(conn) if pg_report.get("ok") is True else []
    neo_report = inspect_neo_outbox_contract(
        container.kg,
        projection_rows=projections if pg_report.get("ok") is True else None,
    )
    return {
        "contract_id": CONTRACT_ID,
        "ok": pg_report["ok"] is True and neo_report["ok"] is True,
        "postgresql": pg_report,
        "neo4j": neo_report,
    }


def require_storage_contract(container: Any) -> dict[str, Any]:
    report = inspect_storage_contract(container)
    if report["ok"] is not True:
        failures = [
            *report["postgresql"].get("failures", []),
            *report["neo4j"].get("failures", []),
        ]
        raise StorageContractError(
            f"storage contract {CONTRACT_ID} not ready: {', '.join(failures)}"
        )
    return report


def _main() -> int:
    from server.adapters.neo4j import LazyNeo4jDriver
    from server.container import AppContainer
    from server.settings import ServerSettings

    class _NoMongo:
        def close(self) -> None:
            return None

    settings = ServerSettings.from_env()
    container = AppContainer(
        neo=LazyNeo4jDriver(), mongo=_NoMongo(), pg_kw=settings.pg_kw,
        pool_min=1, pool_max=1,
    )
    try:
        report = require_storage_contract(container)
    except Exception:  # noqa: BLE001 - non-secret, fail-closed CLI
        print(json.dumps({"contract_id": CONTRACT_ID, "ok": False}, sort_keys=True))
        return 1
    finally:
        container.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
