#!/usr/bin/env python3
"""Sync a Lakatos research-programme python module → Neo4j KG (idempotent, MERGE-only).

WHY THIS EXISTS
---------------
The sibling registration hub `LakatosTree_BPC_20View_20260612` in the KG was
HAND-AUTHORED and drifted (50 KG nodes vs 14 python nodes). Hand-curation of KG
prose for a programme that ALSO lives in a python module is a drift factory.

This script makes the **python module the single source of truth**: it imports
NODES / FRONTIER / RIVAL_NODES / RIVAL_FRONTIER / canonical from a given examples
module and emits idempotent Cypher (MERGE-only, never DELETE) so that:

  * re-running is safe (idempotent) and never duplicates,
  * concurrent hand-curation in the KG is NOT clobbered (no DELETE),
  * `--verify` asserts the KG counts == python source counts (drift alarm).

The default module is `examples.bpc_analysis_contract_programme` — the consumer_b
MEASUREMENT (analysis-contract: 측정·운반·DT) Lakatos programme, a different
*scope* from the registration programme (`bpc_icp_programme`). The two never
alias: this hub uses the node-name prefix `lk-bpc-ac-` (analysis-contract),
distinct from the registration hub's `lk-bpc-hist-`.

MODES
-----
  --dry-run  (default)  parse the module, print the Cypher + parsed counts.
                        DOES NOT connect to any database.
  --verify              connect (NEO4J_* from env), assert KG node/frontier
                        counts == python source counts; exit 1 on mismatch.
                        DOES NOT write.
  --apply               run the MERGEs (KG write — confirm/escalate gated).

ENV (for --verify / --apply only):
    set -a && source .env && set +a
    NEO4J_URI       (e.g. bolt://localhost:55013)   [also accepts NEO4J_URL]
    NEO4J_USERNAME  (e.g. neo4j)                       [also accepts NEO4J_USER]
    NEO4J_PASSWORD

USAGE
-----
    python scripts/sync_lakatos_programme_to_kg.py --dry-run
    python scripts/sync_lakatos_programme_to_kg.py --dry-run --module examples.bpc_icp_programme
    set -a && source .env && set +a
    python scripts/sync_lakatos_programme_to_kg.py --verify
    python scripts/sync_lakatos_programme_to_kg.py --apply       # KG write — user GO required

The metadata of the target hub (name, scope, hard_core, anchor) is for the consumer_b
analysis-contract programme. If you point --module elsewhere, also override
--hub-name / --node-prefix / --anchor so you do not collide with this hub.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# Make the repo root importable so `examples.*` / `lakatos.*` resolve regardless
# of cwd (this file lives in <repo>/scripts/). Mirrors what `python -m` does.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lakatos.verdicts import (  # noqa: E402 — repo root 를 path 에 넣은 뒤 import(cwd 독립)
    FORCEFUL_SOURCES,
    MUTATION_PROTECTED_SOURCES,
)


# ── target identity (consumer_b analysis-contract programme) ──────────────────────────
DEFAULT_MODULE = 'examples.bpc_analysis_contract_programme'
DEFAULT_HUB_NAME = 'LakatosTree_BPC_AnalysisContract_20260615'
DEFAULT_NODE_PREFIX = 'lk-bpc-ac-'          # never aliases registration 'lk-bpc-hist-'
DEFAULT_FRONTIER_PREFIX = 'q-bpc-ac-'
DEFAULT_RIVAL_INFIX = 'rival-'              # name = <prefix>rival-<tag>
DEFAULT_ANCHOR = 'SA_BpcAnalysisContract_Prismv2DtChain_20260614'


# R11(후속 PROM): 명명 프리픽스 레지스트리 — hub_name → node_prefix 고정 매핑(한계비용 0 으로 드리프트
#   봉합). 미등록 허브에 임의 프리픽스로 write 하면 KG 에 같은 프로그램이 두 이름공간으로 갈라진다.
#   신규 허브는 여기 등록해야 sync 가능(fail-loud).
class NamingRegistryError(ValueError):
    """미등록 허브/프리픽스로 sync 시도 — KG 이름공간 드리프트 방지(fail-loud)."""


NAME_REGISTRY: dict[str, str] = {
    DEFAULT_HUB_NAME: DEFAULT_NODE_PREFIX,
}
FRONTIER_NAME_REGISTRY: dict[str, str] = {
    DEFAULT_HUB_NAME: DEFAULT_FRONTIER_PREFIX,
}
RIVAL_INFIX_REGISTRY: dict[str, str] = {
    DEFAULT_HUB_NAME: DEFAULT_RIVAL_INFIX,
}
ANCHOR_REGISTRY: dict[str, str] = {
    DEFAULT_HUB_NAME: DEFAULT_ANCHOR,
}


def resolve_prefix(hub_name: str) -> str:
    """허브명 → 정본 노드 프리픽스. 미등록 = NamingRegistryError(조용한 임의 프리픽스 금지)."""
    if hub_name not in NAME_REGISTRY:
        raise NamingRegistryError(
            f"미등록 허브 {hub_name!r} — NAME_REGISTRY 에 정본 프리픽스를 등록하라(이름공간 드리프트 방지). "
            f"등록됨: {sorted(NAME_REGISTRY)}")
    return NAME_REGISTRY[hub_name]


def validate_registered_target(
    hub_name: str,
    node_prefix: str,
    frontier_prefix: str,
    rival_infix: str,
    anchor: str,
) -> None:
    """Bind both live namespaces to the registered hub before any build/apply."""
    expected_node = resolve_prefix(hub_name)
    expected_frontier = FRONTIER_NAME_REGISTRY.get(hub_name)
    expected_rival = RIVAL_INFIX_REGISTRY.get(hub_name)
    expected_anchor = ANCHOR_REGISTRY.get(hub_name)
    if (
        expected_frontier is None
        or expected_rival is None
        or expected_anchor is None
    ):
        raise NamingRegistryError(
            f"미등록 허브 {hub_name!r} — frontier prefix 정본이 없다"
        )
    if (
        node_prefix != expected_node
        or frontier_prefix != expected_frontier
        or rival_infix != expected_rival
        or anchor != expected_anchor
    ):
        raise NamingRegistryError(
            f"허브 {hub_name!r} namespace 불일치: "
            f"node={node_prefix!r} (expected {expected_node!r}), "
            f"frontier={frontier_prefix!r} (expected {expected_frontier!r}), "
            f"rival={rival_infix!r} (expected {expected_rival!r}), "
            f"anchor={anchor!r} (expected {expected_anchor!r})"
        )


# 미러 행 assurance_tier — 공유 KG 미러는 서버 원장(receipt) 이 아니라 손큐레이션 노트북이다.
# notebook 만 허용(소급 CANONICAL/anchored 위장 봉쇄 — 미러는 판결 권위가 없다).
_MIRROR_TIER_ALLOWED = frozenset({'notebook'})

HUB_SCOPE = 'measurement (analysis-contract: geometry 측정 + AI + 운반 + DT/PLC verdict)'
HUB_PART = 'consumer_b/part_375'
HUB_METRIC_RULE = ('contract_output_count (end-to-end LTDD-green + Windows-verified '
                   'analysis-contract output 누적; higher=progress; scope=measurement)')
HUB_HARD_CORE = ('2D seg=위치/coarse만; 치수=3D geometry/RecipeV2/HALCON; hole 3종=parent '
                 'plane void boundary(center XY + parent/base Z); CUP=CAD band z+nadir; '
                 'TAB_BOLT/washer=3층(base_tab/washer_top/head_top) 보존; LABEL=ROI helper '
                 '(decoded truth=v16 policy); bulk numpy proto-bytes 금지(ShmHandle); '
                 'PLC 제어 loop은 Python이 안 닫음(verdict NG=fail-closed)')
HUB_NAMED_BY = 'sync_lakatos_programme_to_kg.py'
HUB_CREATED_AT = '2026-06-15'

# constant per-node measurement-axis metadata (whole hub is one scope)
METRIC_NAME = 'contract_output_count'
METRIC_DIRECTION = 'higher'
METRIC_SCOPE = 'measurement'

RIVAL_BRANCH = 'rival_monolithic'


# ── parsed-programme container (derived purely from the python module) ─────────
@dataclass
class Programme:
    module_name: str
    nodes: list[dict[str, Any]]
    frontier: list[dict[str, Any]]
    rival_nodes: list[dict[str, Any]]
    rival_frontier: list[dict[str, Any]]
    canonical_tag: str | None
    certified: bool | None = None
    canonical_imp_pct: float | None = None

    # ----- derived counts -----
    @property
    def total_nodes(self) -> int:
        return len(self.nodes) + len(self.rival_nodes)

    @property
    def total_frontiers(self) -> int:
        return len(self.frontier) + len(self.rival_frontier)

    @property
    def total_branched_from(self) -> int:
        return (sum(1 for n in self.nodes if n.get('parent'))
                + sum(1 for n in self.rival_nodes if n.get('parent')))


def load_programme(module_name: str) -> Programme:
    """Import the examples module and read its programme constants.

    The module is the single source of truth — nothing is duplicated here.
    """
    mod = importlib.import_module(module_name)

    def _req(attr: str) -> list:
        if not hasattr(mod, attr):
            sys.exit(f"ERROR: module {module_name!r} has no {attr!r} "
                     f"(not a lakatos programme module?)")
        return list(getattr(mod, attr))

    nodes = _req('NODES')
    frontier = _req('FRONTIER')
    rival_nodes = list(getattr(mod, 'RIVAL_NODES', []) or [])
    rival_frontier = list(getattr(mod, 'RIVAL_FRONTIER', []) or [])

    # canonical = the (single) node whose verdict == 'CANONICAL', derived from module
    canon = [n['tag'] for n in nodes if n.get('verdict') == 'CANONICAL']
    canonical_tag = canon[0] if canon else None
    if len(canon) > 1:
        print(f"WARN: module has {len(canon)} CANONICAL nodes {canon}; using first.",
              file=sys.stderr)

    # certified / improvement — best-effort, only if the module exposes run()
    certified: bool | None = None
    canonical_imp_pct: float | None = None
    # We intentionally DO NOT call run() here (it prints a banner). The hub's
    # certified flag is a programme fact recorded as a static literal below;
    # we still surface the module's certify result if cheaply available via the
    # certify gate without side effects.
    try:
        from lakatos.quant.metrics import tree_metrics  # type: ignore
        m = tree_metrics(nodes, frontier)
        prog = m.get('progress') or {}
        canonical_imp_pct = prog.get('improvement_pct')
    except Exception:  # pragma: no cover - metrics are advisory only
        pass

    return Programme(
        module_name=module_name,
        nodes=nodes, frontier=frontier,
        rival_nodes=rival_nodes, rival_frontier=rival_frontier,
        canonical_tag=canonical_tag,
        certified=certified,
        canonical_imp_pct=canonical_imp_pct,
    )


# ── Cypher emission (parameterized; MERGE-only) ────────────────────────────────
@dataclass
class CypherBatch:
    statements: list[tuple[str, dict]] = field(default_factory=list)
    target_identity: tuple[str, str, str, str, str] | None = None

    def add(self, cypher: str, params: dict | None = None) -> None:
        self.statements.append((cypher.strip(), params or {}))

    def __len__(self) -> int:
        return len(self.statements)


def _node_records(prog: Programme, node_prefix: str, rival_infix: str) -> list[dict]:
    """Flatten main + rival nodes into KG-row dicts (single source = module)."""
    rows: list[dict] = []
    for n in prog.nodes:
        rows.append(_node_row(n, name=f"{node_prefix}{n['tag']}",
                              branch='canonical_path'))
    for n in prog.rival_nodes:
        rows.append(_node_row(n, name=f"{node_prefix}{rival_infix}{n['tag']}",
                              branch=RIVAL_BRANCH))
    return rows


# G4(git-흡수 2026-07-02, S4 봉합): 미러 행의 *내용 무결성 필드*. content_sha 계산에서 제외(자기참조 방지).
_SHA_EXCLUDE = frozenset({'content_sha'})


def _node_content_sha(row: dict) -> str:
    """행의 정본 필드 튜플에 대한 sha256(content_sha 자신 제외). git commit-graph verify 패턴 —
    verify 는 카운트가 아니라 이 sha 를 KG 행에서 *재유도*해 대조한다. 변조 = sha 불일치 = 검출."""
    canon = {k: row[k] for k in sorted(row) if k not in _SHA_EXCLUDE}
    blob = json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def _node_row(n: dict, *, name: str, branch: str) -> dict:
    verdict_source = n.get('verdict_source')   # 모듈이 선언한 영수증 출처(대개 None=구조/행정 노드)
    row = dict(
        name=name,
        tag=n.get('tag'),
        verdict=n.get('verdict'),
        # S4 봉합: provenance 튜플 전량 export — KG 가 force_of(영수증 vs 자기보고)를 표현할 수 있게.
        verdict_source=verdict_source,
        node_state=n.get('node_state'),
        judged_at=n.get('judged_at'),
        # engine_scored 는 *파생 전용* — verdict_source 가 영수증(FORCEFUL)일 때만 True. 손기록 불가(S4 위조 봉합).
        engine_scored=verdict_source in FORCEFUL_SOURCES,
        comment=n.get('comment', ''),
        limitation=n.get('limitation', ''),
        algorithm=n.get('algorithm', ''),
        metric_value=n.get('metric_value'),
        metric_name=METRIC_NAME,
        metric_direction=METRIC_DIRECTION,
        metric_scope=METRIC_SCOPE,
        branch=branch,
        parent_tag=n.get('parent'),
        # R11: 미러는 노트북 tier — 엔진 판결이 아니라 손큐레이션(위 engine_scored 파생과 함께 미러 진위 명시).
        assurance_tier='notebook',
    )
    row['content_sha'] = _node_content_sha(row)
    return row


def verify_content(source_rows: list[dict], kg_rows_by_name: dict[str, dict]) -> list[dict]:
    """행별 content-sha 재유도 대조(카운트 아님) → 불일치 목록. git commit-graph verify 이식.

    각 소스 행의 content_sha 를 재유도해 KG 저장 행의 content_sha 와 비교. KG 행 변조·필드 표류·행 부재를
    검출한다. 빈 리스트 = 미러가 소스와 내용까지 일치(무결).
    """
    drift: list[dict] = []
    for src in source_rows:
        want = src.get('content_sha') or _node_content_sha(src)
        kg = kg_rows_by_name.get(src['name'])
        if kg is None:
            drift.append(dict(name=src['name'], reason='missing_in_kg', want=want, got=None))
        else:
            stored = kg.get('content_sha')
            derived = _node_content_sha(kg)
            if stored != derived:
                drift.append(dict(
                    name=src['name'], reason='kg_content_sha_invalid',
                    want=derived, got=stored,
                ))
            elif derived != want:
                drift.append(dict(name=src['name'], reason='content_sha_mismatch',
                                  want=want, got=derived))
    return drift


def _lineage_records(prog: Programme, node_prefix: str, rival_infix: str) -> list[dict]:
    """(child_name, parent_name) for every non-null parent — BRANCHED_FROM edges."""
    rows: list[dict] = []
    for n in prog.nodes:
        if n.get('parent'):
            rows.append(dict(child=f"{node_prefix}{n['tag']}",
                             parent=f"{node_prefix}{n['parent']}"))
    for n in prog.rival_nodes:
        if n.get('parent'):
            rows.append(dict(child=f"{node_prefix}{rival_infix}{n['tag']}",
                             parent=f"{node_prefix}{rival_infix}{n['parent']}"))
    return rows


def _frontier_records(prog: Programme, frontier_prefix: str) -> list[dict]:
    rows: list[dict] = []
    for q in (list(prog.frontier) + list(prog.rival_frontier)):
        rows.append(dict(
            name=f"{frontier_prefix}{q['name']}",
            status=q.get('status'),
            body=q.get('body', ''),
            domain='measurement',
            closed_by=q.get('closed_by') or [],
        ))
    return rows


_RETIRED_STAGING_MESSAGE = (
    "the unbound staging/migration prototype is retired; "
    "use do_apply(), which binds namespace, constraints, tree lock, "
    "protected-node guards, and a durable receipt in one transaction"
)


def build_staging_cypher(
    rows: list[dict], *, import_batch: str, hub_name: str
) -> list:
    """Fail closed for callers of the retired, unauthorised staging API."""
    del rows, import_batch, hub_name
    raise RuntimeError(_RETIRED_STAGING_MESSAGE)


def build_migrate_cypher(*, import_batch: str, hub_name: str) -> tuple:
    """Fail closed: the old migration could overwrite protected live nodes."""
    del import_batch, hub_name
    raise RuntimeError(_RETIRED_STAGING_MESSAGE)


def migrate_is_gated_by_verify() -> bool:
    """Fail closed instead of advertising the former constant-True gate."""
    raise RuntimeError(_RETIRED_STAGING_MESSAGE)


def build_cypher(prog: Programme, *, hub_name: str, node_prefix: str,
                 frontier_prefix: str, rival_infix: str, anchor: str) -> CypherBatch:
    validate_registered_target(
        hub_name, node_prefix, frontier_prefix, rival_infix, anchor
    )
    b = CypherBatch(
        target_identity=(
            hub_name, node_prefix, frontier_prefix, rival_infix, anchor
        )
    )

    # 1) hub — MERGE on name, set programme facts (ON CREATE + ON MATCH so re-run refreshes)
    hub_props = dict(
        scope=HUB_SCOPE,
        part=HUB_PART,
        metric_rule=HUB_METRIC_RULE,
        hard_core=HUB_HARD_CORE,
        canonical_node=prog.canonical_tag or 'dt_render',
        certified=False,
        status='ACTIVE',
        source_python=prog.module_name,
        named_by=HUB_NAMED_BY,
        created_at=HUB_CREATED_AT,
        assurance_tier='notebook',
    )
    target_names = [
        row["name"] for row in _node_records(prog, node_prefix, rival_infix)
    ]
    target_question_names = [
        row["name"] for row in _frontier_records(prog, frontier_prefix)
    ]
    if len(target_names) != len(set(target_names)):
        raise NamingRegistryError(
            "programme source creates duplicate live node names"
        )
    if len(target_question_names) != len(set(target_question_names)):
        raise NamingRegistryError(
            "programme source creates duplicate live frontier names"
        )
    lineage_rows = _lineage_records(prog, node_prefix, rival_infix)
    target_name_set = set(target_names)
    invalid_lineage = [
        row for row in lineage_rows
        if row['child'] not in target_name_set or row['parent'] not in target_name_set
    ]
    if invalid_lineage:
        raise NamingRegistryError(
            f"programme lineage escapes exact target set: {invalid_lineage!r}"
        )
    b.add(
        """
MERGE (h:KnowledgeHub:LakatosTree {name:$hub_name})
SET h._tree_write_cas=coalesce(h._tree_write_cas, 0) + 0
WITH h
OPTIONAL MATCH (prior:ProgrammeSyncReceipt {id:$sync_event_id})
WITH h, [r IN collect(prior) WHERE r IS NOT NULL] AS priors
OPTIONAL MATCH (semantic_anchor:SemanticAnchor {name:$anchor})
WITH h, priors,
     [a IN collect(semantic_anchor) WHERE a IS NOT NULL] AS semantic_anchors
FOREACH (a IN CASE WHEN size(priors)=0 THEN semantic_anchors ELSE [] END |
  SET a._sync_write_cas=coalesce(a._sync_write_cas,0)+0)
WITH h, priors, size(semantic_anchors) AS anchor_count
OPTIONAL MATCH (target:LakatosNode)
  WHERE target.name IN $target_names
WITH h, priors, anchor_count,
     [n IN collect(DISTINCT target) WHERE n IS NOT NULL] AS targets
FOREACH (n IN CASE WHEN size(priors)=0 THEN targets ELSE [] END |
  SET n._sync_write_cas=coalesce(n._sync_write_cas,0)+0)
OPTIONAL MATCH (question:OpenQuestion {tree:$hub_name})
  WHERE question.name IN $target_question_names
WITH h, priors, anchor_count, targets,
     [q IN collect(DISTINCT question) WHERE q IS NOT NULL] AS questions
FOREACH (q IN CASE WHEN size(priors)=0 THEN questions ELSE [] END |
  SET q._sync_write_cas=coalesce(q._sync_write_cas,0)+0)
WITH h, priors, anchor_count, targets, questions,
  size([n IN targets WHERE n._cycle_created_by IS NOT NULL]) AS active_claims,
  size([n IN targets WHERE
          n.current_receipt_sha IS NOT NULL
          OR n.pred_receipt_sha IS NOT NULL
          OR n.verdict_source IN $forceful
          OR toUpper(coalesce(n.verdict,''))='CANONICAL'
          OR toUpper(coalesce(n.node_state,''))='CANONICAL'
          OR EXISTS { MATCH (n)-[:HAS_RECEIPT]->() }
          OR EXISTS { MATCH (n)-[:HAS_ARGUMENT]->() }
          OR EXISTS {
               MATCH (history:OutboxEntry {tree:$hub_name, node_tag:n.tag})
               WHERE history.op='critique'
             }
       ]) AS protected_nodes,
  size([n IN targets WHERE EXISTS {
          MATCH (other:LakatosTree)-[:HAS_NODE]->(n)
          WHERE other <> h
       }]) AS foreign_node_owners,
  size([q IN questions WHERE
          toUpper(coalesce(q.status,''))='CLOSED'
          OR size(coalesce(q.closed_by,[])) > 0
          OR q.closed_events IS NOT NULL
          OR EXISTS { MATCH (q)-[:HAS_CLOSURE]->() }
       ]) AS protected_questions,
  size([q IN questions WHERE EXISTS {
          MATCH (other:LakatosTree)-[:HAS_FRONTIER]->(q)
          WHERE other <> h
       }]) AS foreign_question_owners
WITH h, priors, anchor_count,
  CASE
    WHEN size(priors)>1 THEN 'intent_conflict'
    WHEN size(priors)=1 AND coalesce(
      priors[0].hub_name=$hub_name
      AND priors[0].request_sha256=$sync_request_sha256
      AND priors[0].status='applied'
      AND priors[0].applied_at IS NOT NULL,
      false) THEN 'already_committed'
    WHEN size(priors)=1 THEN 'intent_conflict'
    WHEN anchor_count<>1 THEN 'anchor_conflict'
    WHEN h.assurance_tier IS NOT NULL AND h.assurance_tier <> 'notebook'
      THEN 'tier_conflict'
    WHEN active_claims>0 THEN 'claim_conflict'
    WHEN foreign_node_owners>0 OR foreign_question_owners>0
      THEN 'scope_conflict'
    WHEN protected_nodes>0 OR protected_questions>0 THEN 'receipt_conflict'
    ELSE 'ok'
  END AS guard_status
FOREACH (_ IN CASE WHEN guard_status='ok' THEN [1] ELSE [] END |
  SET h += $props)
RETURN guard_status
""",
        dict(
            hub_name=hub_name,
            props=hub_props,
            target_names=target_names,
            target_question_names=target_question_names,
            forceful=sorted(MUTATION_PROTECTED_SOURCES),
            anchor=anchor,
            sync_event_id=None,
            sync_request_sha256=None,
        ),
    )

    # 2) nodes — UNWIND, MERGE on name, SET props, MERGE (h)-[:HAS_NODE]->(n)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
UNWIND $rows AS row
MERGE (n:LakatosNode {name:row.name})
SET n._sync_write_cas=coalesce(n._sync_write_cas,0)+0
WITH h, row, n,
  CASE
    WHEN EXISTS {
      MATCH (other:LakatosTree)-[:HAS_NODE]->(n) WHERE other <> h
    } THEN 'scope_conflict'
    WHEN n._cycle_created_by IS NOT NULL
      OR n.current_receipt_sha IS NOT NULL
      OR n.pred_receipt_sha IS NOT NULL
      OR n.verdict_source IN $forceful
      OR toUpper(coalesce(n.verdict,''))='CANONICAL'
      OR toUpper(coalesce(n.node_state,''))='CANONICAL'
      OR EXISTS { MATCH (n)-[:HAS_RECEIPT]->() }
      OR EXISTS { MATCH (n)-[:HAS_ARGUMENT]->() }
      OR EXISTS {
        MATCH (history:OutboxEntry {tree:$hub_name, node_tag:n.tag})
        WHERE history.op='critique'
      }
      THEN 'receipt_conflict'
    ELSE 'ok'
  END AS row_status
FOREACH (_ IN CASE WHEN row_status='ok' THEN [1] ELSE [] END |
  SET n.tag = row.tag,
      n.verdict = row.verdict,
      n.verdict_source = row.verdict_source,
      n.node_state = row.node_state,
      n.judged_at = row.judged_at,
      n.engine_scored = row.engine_scored,
      n.content_sha = row.content_sha,
      n.comment = row.comment,
      n.limitation = row.limitation,
      n.algorithm = row.algorithm,
      n.metric_value = row.metric_value,
      n.metric_name = row.metric_name,
      n.metric_direction = row.metric_direction,
      n.metric_scope = row.metric_scope,
      n.branch = row.branch,
      n.parent_tag = row.parent_tag,
      n.assurance_tier = row.assurance_tier
  MERGE (h)-[:HAS_NODE]->(n))
WITH collect(row_status) AS statuses
RETURN CASE
  WHEN 'scope_conflict' IN statuses THEN 'scope_conflict'
  WHEN 'receipt_conflict' IN statuses THEN 'receipt_conflict'
  ELSE 'ok'
END AS mutation_status
""",
        dict(
            hub_name=hub_name,
            rows=_node_records(prog, node_prefix, rival_infix),
            forceful=sorted(MUTATION_PROTECTED_SOURCES),
        ),
    )

    # 3) lineage — BRANCHED_FROM (child)->(parent), MERGE-only
    b.add(
        """
UNWIND $rows AS row
MATCH (c:LakatosNode {name:row.child})
MATCH (p:LakatosNode {name:row.parent})
MERGE (c)-[:BRANCHED_FROM]->(p)
""",
        dict(rows=lineage_rows),
    )

    # 4) frontier — PrismFinding:OpenQuestion, MERGE on (hub tree, name), MERGE (h)-[:HAS_FRONTIER]->(q)
    #   2026-07-23: name 전역 MERGE → (tree, name) 복합키(서버 writer 와 동일 수리 — 허브 간同名 충돌 봉쇄)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
UNWIND $rows AS row
MERGE (q:PrismFinding:OpenQuestion {name:row.name, tree:$hub_name})
SET q._sync_write_cas=coalesce(q._sync_write_cas,0)+0
WITH h, row, q,
  CASE
    WHEN EXISTS {
      MATCH (other:LakatosTree)-[:HAS_FRONTIER]->(q) WHERE other <> h
    } THEN 'scope_conflict'
    WHEN toUpper(coalesce(q.status,''))='CLOSED'
      OR size(coalesce(q.closed_by,[])) > 0
      OR q.closed_events IS NOT NULL
      OR EXISTS { MATCH (q)-[:HAS_CLOSURE]->() }
      THEN 'receipt_conflict'
    ELSE 'ok'
  END AS row_status
FOREACH (_ IN CASE WHEN row_status='ok' THEN [1] ELSE [] END |
  SET q.status = row.status,
      q.body = row.body,
      q.domain = row.domain,
      q.closed_by = row.closed_by
  MERGE (h)-[:HAS_FRONTIER]->(q))
WITH collect(row_status) AS statuses
RETURN CASE
  WHEN 'scope_conflict' IN statuses THEN 'scope_conflict'
  WHEN 'receipt_conflict' IN statuses THEN 'receipt_conflict'
  ELSE 'ok'
END AS mutation_status
""",
        dict(hub_name=hub_name, rows=_frontier_records(prog, frontier_prefix)),
    )

    # 5) grounding to existing SemanticAnchor (MERGE-only; never create new prose)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
MATCH (a:SemanticAnchor {name:$anchor})
MERGE (h)-[:DOCUMENTS]->(a)
RETURN count(a) AS anchor_link_count
""",
        dict(hub_name=hub_name, anchor=anchor),
    )

    # 6) transaction-local commit receipt.  ``do_apply`` replaces the two
    # placeholders with one invocation identity before execute_write.  A
    # driver callback retry observes this receipt in the first guard and exits
    # without replaying stale SETs over an interposed writer.
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
CREATE (receipt:ProgrammeSyncReceipt {
  id:$sync_event_id,
  hub_name:$hub_name,
  request_sha256:$sync_request_sha256,
  status:'applied',
  applied_at:datetime()
})
MERGE (h)-[:HAS_SYNC_RECEIPT]->(receipt)
RETURN receipt.id AS sync_event_id
""",
        dict(
            hub_name=hub_name,
            sync_event_id=None,
            sync_request_sha256=None,
        ),
    )

    return b


# ── cypher rendering (dry-run; params inlined for human reading only) ──────────
def _render_param(v: Any) -> str:
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return 'null'
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return '[' + ', '.join(_render_param(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{' + ', '.join(f'{k}: {_render_param(val)}' for k, val in v.items()) + '}'
    return repr(v)


def print_cypher(batch: CypherBatch) -> None:
    print('=' * 78)
    print(f'  CYPHER (MERGE-only, idempotent) — {len(batch)} statement(s)')
    print('=' * 78)
    for i, (cypher, params) in enumerate(batch.statements, 1):
        print(f'\n--- statement {i}/{len(batch)} ---')
        print(cypher)
        if params:
            print('  -- params --')
            for k, v in params.items():
                rendered = _render_param(v)
                if len(rendered) > 2000:
                    rendered = rendered[:2000] + f'  ... (+{len(rendered) - 2000} chars)'
                print(f'  ${k} = {rendered}')


def print_counts(prog: Programme) -> None:
    print('=' * 78)
    print(f'  PARSED PROGRAMME — source: {prog.module_name} (single source of truth)')
    print('=' * 78)
    print(f'  NODES (canonical-path) : {len(prog.nodes)}')
    print(f'  FRONTIER               : {len(prog.frontier)}')
    print(f'  RIVAL_NODES            : {len(prog.rival_nodes)}')
    print(f'  RIVAL_FRONTIER         : {len(prog.rival_frontier)}')
    print(f'  canonical node         : {prog.canonical_tag}')
    print(f'  certified (hub flag)   : {False}')
    if prog.canonical_imp_pct is not None:
        print(f'  improvement_pct        : {prog.canonical_imp_pct}%')
    print('  ---- expected KG totals ----')
    print(f'  :LakatosNode (HAS_NODE)        : {prog.total_nodes}')
    print(f'  :OpenQuestion (HAS_FRONTIER)   : {prog.total_frontiers}')
    print(f'  :BRANCHED_FROM edges           : {prog.total_branched_from}')


# ── env / driver helpers (only used by --verify / --apply) ────────────────────
def _neo4j_database() -> str:
    database = os.environ.get('NEO4J_DATABASE')
    if not database:
        sys.exit('ERROR: missing env: NEO4J_DATABASE')
    return database


def _neo4j_config() -> tuple[str, str, str, str]:
    uri = os.environ.get('NEO4J_URI') or os.environ.get('NEO4J_URL')
    user = os.environ.get('NEO4J_USERNAME') or os.environ.get('NEO4J_USER')
    pw = os.environ.get('NEO4J_PASSWORD')
    missing = [k for k, v in (('NEO4J_URI', uri), ('NEO4J_USERNAME', user),
                              ('NEO4J_PASSWORD', pw)) if not v]
    if missing:
        sys.exit('ERROR: missing env: ' + ', '.join(missing)
                 + '  (hint: set -a && source .env && set +a)')
    return uri, user, pw, _neo4j_database()  # type: ignore[return-value]


def _driver():
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError:
        sys.exit('ERROR: neo4j python driver not installed (pip install neo4j)')
    uri, user, pw, _database = _neo4j_config()
    return GraphDatabase.driver(uri, auth=(user, pw))


def _assert_database_identity(session, expected: str) -> None:
    rows = session.run('CALL db.info() YIELD name RETURN name').data()
    observed = rows[0].get('name') if len(rows) == 1 else None
    if observed != expected:
        raise RuntimeError(
            f'Neo4j database identity mismatch: expected={expected!r}, '
            f'observed={observed!r}'
        )


def bind_apply_operation(
    batch: CypherBatch,
    *,
    operation_nonce: str | None = None,
) -> CypherBatch:
    """Bind one callback-stable identity without changing semantic source hash."""

    semantic_statements = []
    for cypher, params in batch.statements:
        semantic_statements.append({
            "cypher": cypher,
            "params": {
                key: value
                for key, value in params.items()
                if key not in {"sync_event_id", "sync_request_sha256"}
            },
        })
    request_sha256 = hashlib.sha256(json.dumps(
        semantic_statements,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')).hexdigest()
    # Default retries must converge across separate CLI processes, not merely
    # within one driver callback.  The semantic request digest is therefore the
    # stable default operation key; an explicit nonce remains available for an
    # operator who intentionally starts a distinct attempt.
    nonce = operation_nonce or request_sha256
    if not (
        isinstance(nonce, str)
        and 1 <= len(nonce) <= 256
        and nonce.isascii()
        and nonce.isprintable()
    ):
        raise ValueError('programme sync operation nonce must be printable ASCII')
    hub_names = {
        params.get('hub_name')
        for _cypher, params in batch.statements
        if params.get('hub_name') is not None
    }
    if len(hub_names) != 1:
        raise ValueError('programme sync batch must bind exactly one hub identity')
    hub_name = next(iter(hub_names))
    event_sha256 = hashlib.sha256(
        json.dumps(
            {
                'schema': 'lakatotree-programme-sync-operation/v2',
                'hub_name': hub_name,
                'nonce': nonce,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
    ).hexdigest()
    event_id = f'programme-sync-{event_sha256}'
    bound = CypherBatch(target_identity=batch.target_identity)
    for cypher, params in batch.statements:
        exact = dict(params)
        if 'sync_event_id' in exact:
            exact['sync_event_id'] = event_id
        if 'sync_request_sha256' in exact:
            exact['sync_request_sha256'] = request_sha256
        bound.add(cypher, exact)
    return bound


def validate_apply_batch(batch: CypherBatch, hub_name: str) -> None:
    """Recheck immutable namespace identity at the mutating boundary."""
    identity = batch.target_identity
    if identity is None or identity[0] != hub_name:
        raise NamingRegistryError(
            "programme sync apply requires a build-validated target identity"
        )
    validate_registered_target(*identity)
    if not batch.statements:
        raise ValueError("programme sync batch is empty")
    first_params = batch.statements[0][1]
    node_names = list(first_params.get('target_names') or [])
    question_names = list(first_params.get('target_question_names') or [])
    if (
        first_params.get('hub_name') != hub_name
        or any(not name.startswith(identity[1]) for name in node_names)
        or any(not name.startswith(identity[2]) for name in question_names)
        or len(node_names) != len(set(node_names))
        or len(question_names) != len(set(question_names))
    ):
        raise NamingRegistryError(
            "programme sync batch target names do not match its registered identity"
        )


_SYNC_REQUIRED_CONSTRAINTS = {
    'lkt_tree_name_unique': ('LakatosTree', ('name',)),
    'lkt_node_name_unique': ('LakatosNode', ('name',)),
    'lkt_open_question_tree_name_key': ('OpenQuestion', ('tree', 'name')),
    'lkt_semantic_anchor_name_unique': ('SemanticAnchor', ('name',)),
}


def assert_apply_constraints(session) -> None:
    """Prove the uniqueness primitives used by MERGE before any mutation."""
    rows = session.run(
        "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
        "RETURN name, type, entityType, labelsOrTypes, properties"
    ).data()
    exact = {
        row.get('name'): (
            row.get('type'),
            row.get('entityType'),
            tuple(row.get('labelsOrTypes') or ()),
            tuple(row.get('properties') or ()),
        )
        for row in rows
    }
    missing = []
    for name, (label, properties) in _SYNC_REQUIRED_CONSTRAINTS.items():
        if exact.get(name) != ('UNIQUENESS', 'NODE', (label,), properties):
            missing.append(name)
    if missing:
        raise RuntimeError(
            'programme sync requires exact uniqueness constraints: '
            + ', '.join(sorted(missing))
        )


def do_apply(
    prog: Programme,
    batch: CypherBatch,
    hub_name: str,
    *,
    operation_nonce: str | None = None,
) -> int:
    validate_apply_batch(batch, hub_name)
    bound_batch = bind_apply_operation(
        batch, operation_nonce=operation_nonce
    )
    database = _neo4j_database()
    drv = _driver()
    try:
        with drv.session(database=database) as s:
            _assert_database_identity(s, database)
            assert_apply_constraints(s)
            def _unit(tx):
                for index, (cypher, params) in enumerate(bound_batch.statements):
                    rows = tx.run(cypher, **params).data()
                    if index == 0:
                        status = (
                            rows[0].get('guard_status')
                            if len(rows) == 1 else None
                        )
                        if status == 'already_committed':
                            return status
                        if status != 'ok':
                            raise RuntimeError(
                                'programme sync rejected by tree/receipt/intent guard: '
                                f'{status!r}'
                            )
                    elif ' AS mutation_status' in cypher:
                        status = (
                            rows[0].get('mutation_status')
                            if len(rows) == 1 else None
                        )
                        if status != 'ok':
                            raise RuntimeError(
                                'programme sync rejected by atomic target guard: '
                                f'{status!r}'
                            )
                    elif ' AS anchor_link_count' in cypher:
                        count = (
                            rows[0].get('anchor_link_count')
                            if len(rows) == 1 else None
                        )
                        if count != 1:
                            raise RuntimeError(
                                'programme sync semantic anchor link failed: '
                                f'{count!r}'
                            )
                return 'applied'
            apply_status = s.execute_write(_unit)
    finally:
        drv.close()
    print(
        f'{str(apply_status).upper()} {len(bound_batch)} statement(s) '
        f'to hub {hub_name!r}.'
    )
    return 0


def do_verify(
    prog: Programme,
    hub_name: str,
    *,
    node_prefix: str = DEFAULT_NODE_PREFIX,
    frontier_prefix: str = DEFAULT_FRONTIER_PREFIX,
    rival_infix: str = DEFAULT_RIVAL_INFIX,
    anchor: str = DEFAULT_ANCHOR,
) -> int:
    validate_registered_target(
        hub_name, node_prefix, frontier_prefix, rival_infix, anchor
    )
    source_rows = _node_records(prog, node_prefix, rival_infix)
    database = _neo4j_database()
    drv = _driver()
    try:
        with drv.session(database=database) as s:
            _assert_database_identity(s, database)
            hub_rows = s.run(
                'MATCH (h:KnowledgeHub:LakatosTree {name:$h}) '
                'RETURN h.assurance_tier AS assurance_tier', h=hub_name
            ).data()
            node_n = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:HAS_NODE]->(n:LakatosNode) '
                'RETURN count(n) AS c', h=hub_name).single()['c']
            front_n = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:HAS_FRONTIER]->'
                '(q:OpenQuestion) RETURN count(q) AS c', h=hub_name).single()['c']
            branch_n = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:HAS_NODE]->'
                '(c:LakatosNode)-[:BRANCHED_FROM]->(:LakatosNode) '
                'RETURN count(*) AS c', h=hub_name).single()['c']
            anchor_n = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:DOCUMENTS]->'
                '(:SemanticAnchor {name:$anchor}) RETURN count(*) AS c',
                h=hub_name,
                anchor=anchor,
            ).single()['c']
            # G4: 카운트가 아니라 *행별 content_sha 재유도* (git commit-graph verify 패턴).
            kg_rows = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:HAS_NODE]->(n:LakatosNode) '
                'RETURN n.name AS name, n.tag AS tag, n.verdict AS verdict, '
                'n.verdict_source AS verdict_source, n.node_state AS node_state, '
                'n.judged_at AS judged_at, n.engine_scored AS engine_scored, '
                'n.comment AS comment, n.limitation AS limitation, '
                'n.algorithm AS algorithm, n.metric_value AS metric_value, '
                'n.metric_name AS metric_name, n.metric_direction AS metric_direction, '
                'n.metric_scope AS metric_scope, n.branch AS branch, '
                'n.parent_tag AS parent_tag, n.assurance_tier AS assurance_tier, '
                'n.content_sha AS content_sha', h=hub_name).data()
    finally:
        drv.close()

    kg_by_name = {r['name']: r for r in kg_rows}
    content_drift = verify_content(source_rows, kg_by_name)

    ok = True
    hub_tier = (
        hub_rows[0].get('assurance_tier') if len(hub_rows) == 1 else None
    )
    checks = [
        ('LakatosNode (HAS_NODE)', node_n, prog.total_nodes),
        ('OpenQuestion (HAS_FRONTIER)', front_n, prog.total_frontiers),
        ('BRANCHED_FROM edges', branch_n, prog.total_branched_from),
        ('DOCUMENTS registered anchor', anchor_n, 1),
    ]
    print('=' * 78)
    print(f'  VERIFY — KG vs python source ({prog.module_name})')
    print('=' * 78)
    for label, got, want in checks:
        mark = 'OK ' if got == want else 'MISMATCH'
        if got != want:
            ok = False
        print(f'  [{mark}] {label:32s} KG={got}  source={want}')
    tier_mark = 'OK ' if hub_tier == 'notebook' else 'MISMATCH'
    print(
        f'  [{tier_mark}] {"hub assurance_tier":32s} '
        f'KG={hub_tier!r}  source={"notebook"!r}'
    )
    if hub_tier != 'notebook':
        ok = False
    # G4: 내용 검증 — 카운트가 맞아도 행 내용이 변조/표류하면 잡는다.
    cmark = 'OK ' if not content_drift else 'MISMATCH'
    print(f'  [{cmark}] {"per-row content_sha":32s} drift={len(content_drift)}')
    for d in content_drift[:10]:
        print(f'        - {d["name"]}: {d["reason"]} (want={d["want"]} got={d["got"]})')
    if content_drift:
        ok = False
    if not ok:
        print('\nVERIFY FAILED — KG drifted from python source (count 또는 content). '
              'For an unprotected imported row, re-run --apply with a new explicit '
              '--operation-nonce (after user GO); otherwise reconcile protected hand-curation.')
        return 1
    print('\nVERIFY PASSED — KG matches python source (count + per-row content).')
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', default=True,
                      help='(default) parse module, print cypher + counts, NO db connection')
    mode.add_argument('--verify', action='store_true',
                      help='connect, assert KG counts == python source counts (exit 1 on mismatch)')
    mode.add_argument('--apply', action='store_true',
                      help='run the MERGEs (KG WRITE — confirm/escalate gated)')
    ap.add_argument('--module', default=DEFAULT_MODULE,
                    help=f'examples programme module (default: {DEFAULT_MODULE})')
    ap.add_argument('--hub-name', default=DEFAULT_HUB_NAME)
    ap.add_argument('--node-prefix', default=DEFAULT_NODE_PREFIX)
    ap.add_argument('--frontier-prefix', default=DEFAULT_FRONTIER_PREFIX)
    ap.add_argument('--rival-infix', default=DEFAULT_RIVAL_INFIX)
    ap.add_argument('--anchor', default=DEFAULT_ANCHOR)
    ap.add_argument(
        '--operation-nonce',
        help=(
            'explicit printable operation identity for intentional drift repair; '
            'default exact --apply retries are stable no-ops'
        ),
    )
    args = ap.parse_args(argv)

    if args.operation_nonce is not None and not args.apply:
        ap.error('--operation-nonce is valid only with --apply')

    prog = load_programme(args.module)
    batch = build_cypher(prog, hub_name=args.hub_name, node_prefix=args.node_prefix,
                         frontier_prefix=args.frontier_prefix,
                         rival_infix=args.rival_infix, anchor=args.anchor)

    if args.apply:
        return do_apply(
            prog,
            batch,
            args.hub_name,
            operation_nonce=args.operation_nonce,
        )
    if args.verify:
        return do_verify(
            prog,
            args.hub_name,
            node_prefix=args.node_prefix,
            frontier_prefix=args.frontier_prefix,
            rival_infix=args.rival_infix,
            anchor=args.anchor,
        )

    # default: dry-run — print counts + cypher, no connection
    print_counts(prog)
    print()
    print_cypher(batch)
    print('\nDRY-RUN ONLY — no database connection. '
          'Run --apply (KG write, user GO) then --verify against your NEO4J_URI.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
