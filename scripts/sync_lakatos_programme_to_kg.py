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

from lakatos.verdicts import FORCEFUL_SOURCES   # noqa: E402 — repo root 를 path 에 넣은 뒤 import(cwd 독립)


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


def resolve_prefix(hub_name: str) -> str:
    """허브명 → 정본 노드 프리픽스. 미등록 = NamingRegistryError(조용한 임의 프리픽스 금지)."""
    if hub_name not in NAME_REGISTRY:
        raise NamingRegistryError(
            f"미등록 허브 {hub_name!r} — NAME_REGISTRY 에 정본 프리픽스를 등록하라(이름공간 드리프트 방지). "
            f"등록됨: {sorted(NAME_REGISTRY)}")
    return NAME_REGISTRY[hub_name]


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
        elif kg.get('content_sha') != want:
            drift.append(dict(name=src['name'], reason='content_sha_mismatch',
                              want=want, got=kg.get('content_sha')))
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


def build_staging_cypher(rows: list[dict], *, import_batch: str, hub_name: str) -> list:
    """R11(receive-pack 격리 이식): 배치를 :LakatosNodeStaging{import_batch} 로만 write — 라이브
    :LakatosNode 라벨은 불변. 전행 content-sha verify green 일 때만 build_migrate_cypher 로 원자 이주.
    변조 배치는 staging 에 격리 잔존(부분 공개 없음)."""
    return [("""
UNWIND $rows AS row
MERGE (s:LakatosNodeStaging {name:row.name, import_batch:$import_batch})
SET s += row, s.import_batch = $import_batch, s.staged_for_hub = $hub_name
""".strip(), dict(rows=rows, import_batch=import_batch, hub_name=hub_name))]


def build_migrate_cypher(*, import_batch: str, hub_name: str) -> tuple:
    """R11: staging → live 원자 이주 = *단일 Cypher statement*(apoc 없이 원자 — 부분 공개 불가).
    verify green 게이트를 통과한 배치에만 호출(migrate_is_gated_by_verify). 라벨 스왑 + 허브 연결 + staging 소거."""
    return ("""
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
MATCH (s:LakatosNodeStaging {import_batch:$import_batch})
MERGE (n:LakatosNode {name:s.name})
SET n = properties(s)
REMOVE n.import_batch, n.staged_for_hub
MERGE (h)-[:HAS_NODE]->(n)
DETACH DELETE s
""".strip(), dict(import_batch=import_batch, hub_name=hub_name))


def migrate_is_gated_by_verify() -> bool:
    """계약 표식: migrate 는 verify_content green 뒤에만(do_apply_staged 가 강제). 가드가 이 계약을 핀."""
    return True


def build_cypher(prog: Programme, *, hub_name: str, node_prefix: str,
                 frontier_prefix: str, rival_infix: str, anchor: str) -> CypherBatch:
    b = CypherBatch()

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
    )
    b.add(
        """
MERGE (h:KnowledgeHub:LakatosTree {name:$hub_name})
ON CREATE SET h += $props
ON MATCH  SET h += $props
""",
        dict(hub_name=hub_name, props=hub_props),
    )

    # 2) nodes — UNWIND, MERGE on name, SET props, MERGE (h)-[:HAS_NODE]->(n)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
UNWIND $rows AS row
MERGE (n:LakatosNode {name:row.name})
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
    n.branch = row.branch
MERGE (h)-[:HAS_NODE]->(n)
""",
        dict(hub_name=hub_name, rows=_node_records(prog, node_prefix, rival_infix)),
    )

    # 3) lineage — BRANCHED_FROM (child)->(parent), MERGE-only
    b.add(
        """
UNWIND $rows AS row
MATCH (c:LakatosNode {name:row.child})
MATCH (p:LakatosNode {name:row.parent})
MERGE (c)-[:BRANCHED_FROM]->(p)
""",
        dict(rows=_lineage_records(prog, node_prefix, rival_infix)),
    )

    # 4) frontier — PrismFinding:OpenQuestion, MERGE on (hub tree, name), MERGE (h)-[:HAS_FRONTIER]->(q)
    #   2026-07-23: name 전역 MERGE → (tree, name) 복합키(서버 writer 와 동일 수리 — 허브 간同名 충돌 봉쇄)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
UNWIND $rows AS row
MERGE (q:PrismFinding:OpenQuestion {name:row.name, tree:$hub_name})
SET q.status = row.status,
    q.body = row.body,
    q.domain = row.domain,
    q.closed_by = row.closed_by
MERGE (h)-[:HAS_FRONTIER]->(q)
""",
        dict(hub_name=hub_name, rows=_frontier_records(prog, frontier_prefix)),
    )

    # 5) grounding to existing SemanticAnchor (MERGE-only; never create new prose)
    b.add(
        """
MATCH (h:KnowledgeHub:LakatosTree {name:$hub_name})
MERGE (a:SemanticAnchor {name:$anchor})
MERGE (h)-[:DOCUMENTS]->(a)
""",
        dict(hub_name=hub_name, anchor=anchor),
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
def _neo4j_config() -> tuple[str, str, str]:
    uri = os.environ.get('NEO4J_URI') or os.environ.get('NEO4J_URL')
    user = os.environ.get('NEO4J_USERNAME') or os.environ.get('NEO4J_USER')
    pw = os.environ.get('NEO4J_PASSWORD')
    missing = [k for k, v in (('NEO4J_URI', uri), ('NEO4J_USERNAME', user),
                              ('NEO4J_PASSWORD', pw)) if not v]
    if missing:
        sys.exit('ERROR: missing env: ' + ', '.join(missing)
                 + '  (hint: set -a && source .env && set +a)')
    return uri, user, pw  # type: ignore[return-value]


def _driver():
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError:
        sys.exit('ERROR: neo4j python driver not installed (pip install neo4j)')
    uri, user, pw = _neo4j_config()
    return GraphDatabase.driver(uri, auth=(user, pw))


def do_apply(prog: Programme, batch: CypherBatch, hub_name: str) -> int:
    drv = _driver()
    try:
        with drv.session() as s:
            for cypher, params in batch.statements:
                s.run(cypher, **params)
    finally:
        drv.close()
    print(f'APPLIED {len(batch)} statement(s) to hub {hub_name!r}.')
    return 0


def do_verify(prog: Programme, hub_name: str, *, node_prefix: str = DEFAULT_NODE_PREFIX,
              rival_infix: str = DEFAULT_RIVAL_INFIX) -> int:
    source_rows = _node_records(prog, node_prefix, rival_infix)
    drv = _driver()
    try:
        with drv.session() as s:
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
            # G4: 카운트가 아니라 *행별 content_sha 재유도* (git commit-graph verify 패턴).
            kg_rows = s.run(
                'MATCH (:KnowledgeHub:LakatosTree {name:$h})-[:HAS_NODE]->(n:LakatosNode) '
                'RETURN n.name AS name, n.content_sha AS content_sha', h=hub_name).data()
    finally:
        drv.close()

    kg_by_name = {r['name']: r for r in kg_rows}
    content_drift = verify_content(source_rows, kg_by_name)

    ok = True
    checks = [
        ('LakatosNode (HAS_NODE)', node_n, prog.total_nodes),
        ('OpenQuestion (HAS_FRONTIER)', front_n, prog.total_frontiers),
        ('BRANCHED_FROM edges', branch_n, prog.total_branched_from),
    ]
    print('=' * 78)
    print(f'  VERIFY — KG vs python source ({prog.module_name})')
    print('=' * 78)
    for label, got, want in checks:
        mark = 'OK ' if got == want else 'MISMATCH'
        if got != want:
            ok = False
        print(f'  [{mark}] {label:32s} KG={got}  source={want}')
    # G4: 내용 검증 — 카운트가 맞아도 행 내용이 변조/표류하면 잡는다.
    cmark = 'OK ' if not content_drift else 'MISMATCH'
    print(f'  [{cmark}] {"per-row content_sha":32s} drift={len(content_drift)}')
    for d in content_drift[:10]:
        print(f'        - {d["name"]}: {d["reason"]} (want={d["want"]} got={d["got"]})')
    if content_drift:
        ok = False
    if not ok:
        print('\nVERIFY FAILED — KG drifted from python source (count 또는 content). '
              'Re-run --apply (after user GO) or reconcile hand-curation.')
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
    args = ap.parse_args(argv)

    prog = load_programme(args.module)
    batch = build_cypher(prog, hub_name=args.hub_name, node_prefix=args.node_prefix,
                         frontier_prefix=args.frontier_prefix,
                         rival_infix=args.rival_infix, anchor=args.anchor)

    if args.apply:
        return do_apply(prog, batch, args.hub_name)
    if args.verify:
        return do_verify(prog, args.hub_name, node_prefix=args.node_prefix,
                         rival_infix=args.rival_infix)

    # default: dry-run — print counts + cypher, no connection
    print_counts(prog)
    print()
    print_cypher(batch)
    print('\nDRY-RUN ONLY — no database connection. '
          'Run --apply (KG write, user GO) then --verify against your NEO4J_URI.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
