#!/usr/bin/env python3
"""라카토스 서버 — 연구 프로그램 트리의 KG+DB 백엔드 (알기 쉬운 단일 파일).

3층:
  Neo4j (KG)      = 나무/노드/질문 그래프 정본 (LakatosTree / PrismExperiment·LakatosNode / OpenQuestion)
  PostgreSQL      = append-only 이력 (lakatos.history, metric_snapshots) — 누가 언제 무엇을
  MongoDB         = 산출물 보관 (결과 json/지표 원본; db=lakatos, col=artifacts)

env: NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD, LAKATOS_PG_HOST/PORT/USER/PASSWORD/DB, LAKATOS_MONGO_URI,
     (선택) LAKATOS_API_TOKEN (run.sh 가 .env 에서 주입)  # OPS-HON-4: LAKATOS_PG_DSN 은 미존재였음
실행: bash run.sh   → http://localhost:55170  (대시보드 = / , API = /api/*)
"""
import json, logging, os, secrets, sys
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lakatos.quant.metrics import branch_inputs
from lakatos.programme.stack import evaluate_stack
from lakatos.programme.lifecycle import lifecycle_state
from lakatos.programme.leaderboard import Competitor, leaderboard as build_leaderboard
from lakatos.programme.kuhn import assess_paradigm, propose_supersession
from lakatos.programme.explore import rank_questions
from lakatos.programme.agm import (Belief, expansion, contraction, revision, demote_canonical,
                         HardCoreProtected)
from lakatos.engine import FoundationMap, FoundationRequirement, KnowledgeKind
from lakatos.io.lineage import by_output, roots as lin_roots
from lakatos.io.envfp import environment_fingerprint, fingerprint_sha
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import TypeAdapter
from neo4j.exceptions import ServiceUnavailable, SessionExpired
import psycopg2.pool
from psycopg2 import OperationalError as PgOperationalError
from server.adapters.mongo import LazyMongoDatabase
from server.adapters.neo4j import LazyNeo4jDriver
from server.api_schemas import (
    AgmReviseIn,
    ArtifactIn,
    BeliefIn,
    CritiqueIn,
    CycleIn,
    DerivationIn,
    ElementIn,
    ElementUseIn,
    FoundationRequirementIn,
    LonginusRefIn,
    NodeIn,
    ObservationIn,
    ParentEdgeIn,
    PredictionIn,
    QuestionIn,
    ResearchEventIn,
    TestResultIn,
    VerdictIn,
    WorldActionIn,
)
from server.composition import create_fastapi_app
from server.contexts.lineage.api import create_lineage_router
from server.contexts.lineage.service import LineageService
from server.contexts.tree.api import create_tree_router
from server.contexts.tree.evidence_claim import create_evidence_claim_router
from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.judgement import create_judgement_router
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.programme import create_programme_router
from server.contexts.tree.programme_service import ProgrammeService
from server.contexts.tree.service import TreeService
from server.dashboard_view import VERDICT_COLORS, render_dashboard
from server.graph_view import tree_dot, tree_dot_view, tree_graph
from server.file_hashing import file_sha as _file_sha, path_sha as _path_sha
from server.container import AppContainer
from server.settings import ServerSettings

NEO = LazyNeo4jDriver()
PG_KW = ServerSettings.from_env().pg_kw
MONGO = LazyMongoDatabase()

logger = logging.getLogger('lakatotree.server')   # OPS-OBSERVABILITY-1: print → 구조화 logger

# 합성 루트: 외부 자원(Neo4j/Mongo/PG) 생성·운용·종료를 한 객체가 소유(server.container).
# 아래 모듈 API(kg/kg_tx/pg/hist/_close_resources)는 컨테이너로 위임만 — 하위호환 유지.
_container = AppContainer(neo=NEO, mongo=MONGO, pg_kw=PG_KW, logger=logger)


def _close_resources() -> list:
    """OPS-LIFECYCLE-1: 종료 시 자원을 best-effort 로 닫고 실패목록 반환(→ AppContainer.close)."""
    return _container.close()


def _startup_reconcile():
    """startup best-effort outbox 복구(#③ outbox 경화) — PG-down 중 쌓인 OutboxEntry 를 *자동* 재적용해
    KG↔PG 발산을 부팅 시 좁힌다(진짜 2PC 아님 — outbox 정답패턴의 자동복구 절반). 실패해도 startup 안 막음
    (멱등이라 재호출 안전; 수동 트리거 POST /api/ops/reconcile-outbox 도 남아있음)."""
    try:
        r = _container.reconcile_outbox()
        if r.get('replayed_count'):
            logger.info('startup outbox reconcile: %s 재적용, %s pending', r['replayed_count'], r['still_pending'])
        return r
    except Exception as e:   # noqa: BLE001 — 부팅 복구 실패가 서버 기동을 막지 않음
        logger.warning('startup outbox reconcile 실패(무시 — 수동 트리거 가능): %s', type(e).__name__)
        return None


@asynccontextmanager
async def _lifespan(app):
    _startup_reconcile()                     # startup: outbox 자동복구(best-effort, #③)
    yield
    for e in _close_resources():             # shutdown: 커넥션 누수 차단
        logger.warning('shutdown 리소스 close 실패: %s', e)


app = create_fastapi_app(lifespan=_lifespan)
_BOOL = TypeAdapter(bool)   # FastAPI bool 쿼리 강제와 동일 파싱(미들웨어 snapshot 게이트용, OPS-ROB-1)


# ── 운영 안전망 (나생문 ROB-2/4, DEPLOY-1) ──

@app.exception_handler(ServiceUnavailable)
@app.exception_handler(SessionExpired)
async def _neo4j_down(request: Request, exc):
    # DB 다운이 500 으로 누수되지 않게 — graceful 503. 단 이미 적용된 부분 KG write 는
    # 롤백 안 됨(ROB-1 비원자성 미해결, THEORY P5). 드라이버 클래스명은 노출 안 함(정보누설 차단).
    return JSONResponse(status_code=503, content={'detail': 'Neo4j 연결 불가 (의존성 down)'})


@app.exception_handler(PgOperationalError)
async def _pg_down(request: Request, exc):
    return JSONResponse(status_code=503, content={'detail': 'PostgreSQL 연결 불가 (의존성 down)'})


@app.middleware('http')
async def _bearer_auth(request: Request, call_next):
    """opt-in 쓰기 보호 — LAKATOS_API_TOKEN 설정 시에만 mutating 요청에 Bearer 강제.
    미설정이면 no-op(하위호환). 정본 연구그래프 무단 변조 방지(ROB-4).
    method 만이 아니라 side-effect GET(?snapshot=true=DB insert)도 게이트(AUTH-BYPASS 수정).
    상수시간 비교(secrets.compare_digest)로 timing 누수 차단."""
    token = os.environ.get('LAKATOS_API_TOKEN')
    if token:
        snap = request.query_params.get('snapshot')
        snap_true = False
        if snap is not None:   # OPS-ROB-1: FastAPI bool 강제와 동일하게(1/yes/on/True) — 'true' 만 보면 우회됨
            try:
                snap_true = bool(_BOOL.validate_python(snap))
            except Exception:
                snap_true = False
        mutating = request.method in ('POST', 'PUT', 'PATCH', 'DELETE') or snap_true
        if mutating and not secrets.compare_digest(
                request.headers.get('authorization', ''), f'Bearer {token}'):
            return JSONResponse(status_code=401,
                                content={'detail': '유효한 Bearer 토큰 필요 (LAKATOS_API_TOKEN)'})
    return await call_next(request)


@app.get('/healthz')
def healthz():
    """liveness/readiness — 의존성 도달성. 하나라도 down 이면 503 (LB/systemd 게이트용)."""
    svc = {}
    try:
        kg('RETURN 1 AS ok')
        svc['neo4j'] = 'ok'
    except Exception:
        svc['neo4j'] = 'down'        # 드라이버/예외 클래스명 노출 안 함(정보누설 차단)
    try:
        with pg() as c, c.cursor() as cur:
            cur.execute('SELECT 1')
        svc['pg'] = 'ok'
    except Exception:
        svc['pg'] = 'down'
    try:
        MONGO.command('ping')
        svc['mongo'] = 'ok'
    except Exception:
        svc['mongo'] = 'down'
    healthy = all(v == 'ok' for v in svc.values())
    return JSONResponse(status_code=200 if healthy else 503,
                        content={'status': 'ok' if healthy else 'degraded', 'services': svc})


@app.post('/api/ops/reconcile-outbox')
def reconcile_outbox_op():
    """B1 복구 운영 트리거(#4) — pending OutboxEntry(KG 정본)를 PG history 에 *멱등* 재적용.
    PG-down 동안 쌓인 outbox 가 영영 미적용(KG↔PG 발산)되지 않도록 운영자가 명시 호출한다 —
    in-process 메서드(container.reconcile_outbox)는 전엔 테스트 외 호출자가 없는 고아였다.
    멱등(ON CONFLICT event_id DO NOTHING)이라 재호출 안전. mutating → LAKATOS_API_TOKEN 설정 시
    Bearer 강제(_bearer_auth). 반환 {pending, replayed, replayed_count, still_pending, pg_down}."""
    return _container.reconcile_outbox()


@app.get('/api/ops/outbox-status')
def outbox_status_op():
    """관측(#③ outbox 경화): 미적용 OutboxEntry depth = KG↔PG 발산 깊이. GET=비변이(무인증).
    pending>0 = reconcile 필요(startup 자동 + POST /api/ops/reconcile-outbox 수동). -1=KG 미상."""
    return {'pending': _container.outbox_pending_count()}


# 자원 접근 모듈 API — AppContainer 위임(구현은 server.container, server.app 은 얇은 facade).
# 모듈 전역 `global _PG_POOL` 변이 제거: 풀 lazy 상태가 컨테이너 인스턴스에 캡슐화됨.
def pg():
    return _container.pg()

def hist(tree, op, node_tag=None, payload=None):
    return _container.hist(tree, op, node_tag, payload)

def kg(q, **kw):
    return _container.kg(q, **kw)

def kg_tx(ops):
    return _container.kg_tx(ops)

def _safe_rebuild_plan(artifact, bo):
    """ENGINE-ROB-3: 계보 사이클이면 rebuild_plan 이 ValueError → 500 누수 대신 빈 plan(재현불가).
    reproducibility_gaps 도 사이클을 갭으로 보므로 reproducible=False 와 일관."""
    return LineageService.safe_rebuild_plan(artifact, bo)

NODE_LABELS = 'PrismExperiment|LakatosNode'

def _tree_service():
    return TreeService(kg=kg, kg_tx=kg_tx, hist=hist, pg=pg)


def _evidence_claim_service(*, store_research_event=None):
    return EvidenceClaimService(
        kg=kg,
        kg_tx=kg_tx,   # B1-step1: bind_embedded_observation 의 다중 KG write 를 단일 트랜잭션으로
        hist=hist,
        foundation=lambda name: _foundation_from_rows(_foundation_rows(name)),
        load_lineage=_load_lineage,
        reproducible_for_node=_reproducible_for_node,
        standing=standing,
        calibration=calibration,
        store_research_event=store_research_event,
        environment_fingerprint=environment_fingerprint,
        fingerprint_sha=fingerprint_sha,
    )


def _programme_service():
    cycle_ports = {
        "add_node": add_node,
        "register_prediction": register_prediction,
        "submit_test_result": submit_test_result,
        "add_critique": add_critique,
        "standing": standing,
    }
    return ProgrammeService(
        kg=kg,
        hist=hist,
        pg=pg,
        tree_data=tree_data,
        compute_metrics=compute_metrics,
        insert_artifact=lambda doc: MONGO.artifacts.insert_one(doc),
        rank_questions=rank_questions,
        **cycle_ports,
    )


def _judgement_service():
    return JudgementService(
        kg=kg,
        kg_tx=kg_tx,
        hist=hist,
        foundation=lambda name: _foundation_from_rows(_foundation_rows(name)),
        reproducible_for_node=_reproducible_for_node,
    )


def _lineage_service(*, use_load_facade: bool = True):
    return LineageService(
        kg=kg,
        pg=pg,
        path_sha=_path_sha,
        load_lineage=_load_lineage if use_load_facade else None,
        safe_rebuild_plan=_safe_rebuild_plan,
        environment_fingerprint=environment_fingerprint,
        fingerprint_sha=fingerprint_sha,
    )


app.include_router(create_tree_router(_tree_service))
app.include_router(create_evidence_claim_router(_evidence_claim_service))
app.include_router(create_programme_router(_programme_service))
app.include_router(create_judgement_router(_judgement_service))
app.include_router(create_lineage_router(_lineage_service))


# Compatibility facade: tests and in-process orchestration still import these
# names from server.app. HTTP ownership is in server.contexts.tree.api.
def tree_data(name):
    return _tree_service().tree_data(name)

def compute_metrics(td):
    return _tree_service().compute_metrics(td)

def trees():
    return _tree_service().list_trees()

def tree(name: str):
    return tree_data(name)

def metrics(name: str, snapshot: bool = False):
    return _tree_service().metrics(name, snapshot=snapshot)

def _normalized_parent_edges(n: NodeIn) -> list[ParentEdgeIn]:
    return _tree_service().normalized_parent_edges(n)


def add_node(name: str, n: NodeIn):
    return _tree_service().add_node(name, n, tree_data=tree_data(name))

def set_verdict(name: str, tag: str, v: VerdictIn):
    return _judgement_service().set_verdict(name, tag, v)

def open_question(name: str, q: QuestionIn):
    return _tree_service().open_question(name, q)

def close_question(name: str, qname: str, closed_by: str = ''):
    # closed_by 는 *그 질문을 닫은 노드 tag* 여야 한다 — 라우든 규칙③ per-branch 귀속(gap4)이
    # closed_by∩노드tag 로 집계하므로, 비-노드 문자열로 닫으면 문제수지에 미집계(metrics.laudan.
    # unattributed_closed 로 노출). 외부 증거로 닫을 땐 미귀속이 정상이나 가지 수지엔 안 들어간다.
    return _tree_service().close_question(name, qname, closed_by=closed_by)

def register_prediction(name: str, tag: str, p: PredictionIn):
    return _judgement_service().register_prediction(name, tag, p)

def submit_test_result(name: str, tag: str, r: TestResultIn):
    return _judgement_service().submit_test_result(name, tag, r)

def provenance(name: str, tag: str):
    return _evidence_claim_service().provenance(name, tag)

def add_critique(name: str, tag: str, c: CritiqueIn):
    return _evidence_claim_service().add_critique(name, tag, c)


def add_research_event(name: str, tag: str, ev: ResearchEventIn):
    return _evidence_claim_service().add_research_event(name, tag, ev)


def _store_research_event(name, tag, event_id, realm, action, actor, evidence_refs, payload):
    return _evidence_claim_service().store_research_event(
        name, tag, event_id, realm, action, actor, evidence_refs, payload)


def add_observation(name: str, tag: str, o: ObservationIn):
    return _evidence_claim_service(store_research_event=_store_research_event).add_observation(name, tag, o)


def add_world_action(name: str, tag: str, a: WorldActionIn):
    return _evidence_claim_service(store_research_event=_store_research_event).add_world_action(name, tag, a)


def standing(name: str, tag: str):
    return _evidence_claim_service().standing(name, tag)


def _foundation_from_rows(rows) -> FoundationMap | None:
    if not rows:
        return None
    foundation = FoundationMap()
    for r in rows:
        if not r.get('name') or not r.get('kind'):
            continue
        try:
            kind = KnowledgeKind(r['kind'])
        except ValueError:
            continue
        foundation.add(FoundationRequirement(
            name=r['name'],
            kind=kind,
            question=r.get('question') or '',
            why_needed=r.get('why_needed') or '',
            acceptance_criteria=tuple(r.get('acceptance_criteria') or []),
            evidence_refs=tuple(r.get('evidence_refs') or []),
            status=r.get('status') or 'needed',
            optional=bool(r.get('optional')),
            owner=r.get('owner') or '',
            risk_if_missing=r.get('risk_if_missing') or '',
        ))
    return foundation


def _reproducible_for_node(name: str, tag: str) -> bool | None:
    """F-CON-1 + R-AUDIT-1(적대 재검증 2026-06-21): 노드 result_path 가 raw-root 서 재현가능한지 —
    *현실이 끊는 영수증*으로만 True.

    엄격 재현성 = 완성본의 모든 궁극 root 가 선언된 source(kind='source')이고, ★그 source 들의 sha 를
    서버가 *디스크에서 재계산*해 기록값과 일치할 때만 True. client 가 lineage ledger 에 kind='source'/sha 를
    자기선언하는 것만으론 절대 True 가 아니다 — 그게 R-AUDIT-1 forge 였다(노드 자기 출력을 kind='source' 로
    POST → roots ⊆ declared 통과 → floor 가 위조 영수증으로 CANONICAL 승격). 영수증은 우리가 쓰는 게 아니라
    현실이 끊어 준다.
      • 계보 SHAPE 끊김(dangling/비-source root) → False(차단; 기존 F-CON-1 동작 보존, 나생문 CON-1/F-CON-1-A/B).
      • SHAPE 는 맞으나 source sha 검증 불가(파일 부재/불일치) → None(증명 못 함 → floor 영수증 못 줌, 차단은 안 함).
      • result_path 없음/계보 미기록 → None(증명 노드 등 — 게이트 비적용).
    ★완전 무위조(실제 producer replay 실행)는 G-Web Part A 후속(미구현). 현재는 root source 산출물의 sha 현실대조까지.
    이게 set_verdict 에서 synthesize_promotion(reproducible=) 으로 흘러 RebuildFromRaw 게이트 발동.
    """
    rows = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 RETURN e.result_path AS rp''', tree=name, tag=tag)
    if not rows:
        return None
    rp = rows[0].get('rp')
    if not rp:
        return None
    ds = _load_lineage()
    bo = by_output(ds)
    if rp not in bo:
        return None
    rts = lin_roots(rp, bo)   # 궁극 root 집합 (derivation 없거나 inputs 빈 leaf 포함)
    declared = {d.output for d in ds if d.kind == 'source'}
    if not rts or not rts.issubset(declared):
        return False   # 빈 closure(사이클/고립)·dangling·비-source root = 재현불가(차단)
    recorded = {d.output: d.output_sha for d in ds}
    for src in rts:   # ★현실 대조: 선언 source 의 sha 를 서버가 디스크서 재계산해 일치 확인
        server_sha = _path_sha(src)
        if not server_sha or server_sha != recorded.get(src):
            return None   # 파일 부재/sha 불일치 → client 자기선언만으론 영수증 못 줌(증명 불가)
    return True


def _foundation_rows(name: str):
    return kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_FOUNDATION]->(fr:FoundationRequirement)
                 RETURN fr.short_name AS name, fr.kind AS kind, fr.question AS question,
                        fr.why_needed AS why_needed, fr.acceptance_criteria AS acceptance_criteria,
                        fr.evidence_refs AS evidence_refs, fr.status AS status,
                        fr.optional AS optional, fr.owner AS owner,
                        fr.risk_if_missing AS risk_if_missing, fr.satisfied AS satisfied
                 ORDER BY fr.kind, fr.short_name""", tree=name)


def research_events(name: str, tag: str):
    return _evidence_claim_service().research_events(name, tag)


def claim_standing(name: str, tag: str, require_replay: bool = True):
    """Claim standing for a node. ``require_replay`` gates the verdict on a
    successful lineage replay (set False to read standing without replay)."""
    return _evidence_claim_service().claim_standing(name, tag, require_replay=require_replay)

def calibration(name: str):
    return _programme_service().calibration(name)

def directions(name: str):
    return _programme_service().directions(name)

# ── 신규 층 (2026-06-13): stack 메타규칙 / lifecycle / 리더보드 / 패러다임 / 인증 ──

def _branch_stack(name: str, leaf: str | None):
    td = tree_data(name)
    try:
        bi = branch_inputs(td['nodes'], td['frontier'], leaf=leaf)
    except KeyError as e:
        raise HTTPException(404, str(e))
    sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                        bi['prediction_hits'], bi['problem_balance_windowed'])
    return td, bi, sv

def _stack_dict(sv):
    return dict(decision=sv.decision, conflict=sv.conflict, quorum=sv.quorum, reason=sv.reason,
                votes=[dict(layer=v.layer, vote=v.vote, reason=v.reason, detail=v.detail)
                       for v in sv.votes])

def stack_view(name: str, leaf: str | None = None):
    return _programme_service().stack_view(name, leaf=leaf)

def lifecycle_view(name: str, leaf: str | None = None):
    return _programme_service().lifecycle_view(name, leaf=leaf)

def series_view(name: str, leaf: str | None = None):
    return _programme_service().series_view(name, leaf=leaf)   # #5 프로그램-시계열 진단(diagnostic_only)

def _competitor_for_tree(n: str) -> Competitor:
    td = tree_data(n)
    m = compute_metrics(td)
    try:
        bi = branch_inputs(td['nodes'], td['frontier'])
        verdicts = bi['verdicts']
    except KeyError:                        # 정본 없음 — 빈 시퀀스(신뢰도 prior 유지)
        verdicts = []
    imp = (m.get('progress') or {}).get('improvement_pct') or 0.0
    return Competitor(name=n, verdicts=verdicts, nodes=td['nodes'],
                      metric_improvement_pct=imp,
                      closed=m['frontier']['closed'], opened=m['frontier']['open'])

@app.get('/api/graph/{name}')
def tree_graph_view(name: str):
    """E Phase 1 — 시각 트리 GUI 데이터 척추: node(색/klass/패널) + edge + frontier + 안건.
    프론트엔드(Phase 2)가 렌더(브랜치 줌, 노드 클릭 패널, 본류·퇴행·생존 색). /api/tree 아님(app-owned)."""
    td = tree_data(name)
    return tree_graph(td, compute_metrics(td))


@app.get('/api/graph/{name}/dot', response_class=PlainTextResponse)
def tree_graph_dot(name: str):
    """E Phase 2 — 트리를 Graphviz DOT(표준 시각 포맷)로. `dot -Tsvg` 로 렌더."""
    td = tree_data(name)
    return tree_dot(tree_graph(td, compute_metrics(td)))


@app.get('/api/graph/{name}/view', response_class=HTMLResponse)
def tree_graph_html(name: str):
    """E Phase 2 — 브라우저 뷰어(빌드 0): DOT 임베드 + viz.js CDN 렌더. 본류/퇴행/생존 색."""
    td = tree_data(name)
    g = tree_graph(td, compute_metrics(td))
    return tree_dot_view(name, tree_dot(g))


@app.get('/api/leaderboard')
def leaderboard_view(trees: str, snapshot: bool = False):
    """경쟁 프로그램(트리) 리더보드 — Pareto+Borda 3기준 (P2). ?snapshot=true 로 축적."""
    names = [t.strip() for t in trees.split(',') if t.strip()]
    if len(names) < 2:
        raise HTTPException(422, '비교는 트리 ≥2 (trees=a,b,...)')
    lb = build_leaderboard([_competitor_for_tree(n) for n in names])
    if snapshot:
        MONGO['leaderboard_snapshots'].insert_one(dict(
            key=','.join(sorted(names)), at=datetime.now(timezone.utc).isoformat(), board=lb))
    return lb

@app.get('/api/paradigm')
def paradigm_view(incumbent: str, rivals: str):
    """패러다임 판정 — 정상과학/위기/shift_candidate (gap7). shift=인간 안건, 자동 교체 금지."""
    rivals_l = [r.strip() for r in rivals.split(',') if r.strip()]
    if not rivals_l:
        raise HTTPException(422, 'rivals 필수 (rivals=b,c)')
    key = ','.join(sorted([incumbent] + rivals_l))
    snaps = [s['board'] for s in
             reversed(list(MONGO['leaderboard_snapshots'].find({'key': key})
                           .sort('at', -1).limit(50)))]   # OPS-ROB-2: 누적 전수로드 금지(최신 50)
    td, bi, sv = _branch_stack(incumbent, None)
    ls = lifecycle_state(bi['verdicts'], sv, bi['novel_registered_recent'],
                         bi['problem_balance_windowed'], bi['canonical_improved_recent'])
    # 프로그램 퇴행 = 정본경로(과거 성공 기록)가 아니라 *최근 가지들*의 비진보 —
    # 트리 전체 max_degeneration_depth 가 프로그램 수준 신호
    m = compute_metrics(td)
    consec = max(bi['consecutive_nonprogressive'], m['max_degeneration_depth'])
    pa = assess_paradigm(incumbent, rivals_l, snaps, [ls.state], consec)
    return dict(state=pa.state, incumbent=pa.incumbent, rival=pa.rival, reason=pa.reason,
                window=pa.window, requires_human_oracle=pa.requires_human_oracle,
                # shift_candidate 면 구조화된 대체 *제안* 안건(verdict mutation 0, 인간확정 필요).
                # 신호가 prose reason 으로 증발하지 않고 machine-readable 레코드로 박힌다.
                proposal=propose_supersession(pa),
                snapshots=len(snaps), incumbent_lifecycle=ls.state,
                note=('' if len(snaps) >= pa.window else
                      f'스냅샷 {len(snaps)} < 윈도우 {pa.window} — '
                      f'/api/leaderboard?trees={key}&snapshot=true 로 축적 필요'))

def node_certificate(name: str, tag: str):
    return _evidence_claim_service().node_certificate(name, tag)

# ── AGM 신념개정 (P1) — hard core revision/contraction 추론 surface (나생문 WIRE-3) ──
# 무상태 reasoning 엔드포인트: belief base 를 받아 AGM 연산 결과를 돌려준다(what-if).
# (트리 노드↔belief 영구 매핑은 더 깊은 모델 — 후속. 여기선 형식층을 *호출 가능*하게 만든다.)

def _belief(b: BeliefIn) -> Belief:
    return Belief(belief_id=b.belief_id, statement=b.statement, kind=b.kind,
                  credence=b.credence, problem_balance=b.problem_balance,
                  connectivity=b.connectivity, depends_on=tuple(b.depends_on))


def _load_belief_base(tree: str) -> list:
    """A4: 트리의 영속 belief base 를 KG 에서 로드 (HAS_BELIEF). 없으면 빈 base."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_BELIEF]->(b:Belief)
                 RETURN b.belief_id AS belief_id, b.statement AS statement, b.kind AS kind,
                        b.credence AS credence, b.problem_balance AS problem_balance,
                        b.connectivity AS connectivity, b.depends_on AS depends_on
                 ORDER BY belief_id""", tree=tree)
    return [Belief(belief_id=r['belief_id'], statement=r.get('statement') or r['belief_id'],
                   kind=r.get('kind') or 'protective_belt',
                   credence=r['credence'] if r.get('credence') is not None else 0.5,
                   problem_balance=int(r.get('problem_balance') or 0),
                   connectivity=int(r.get('connectivity') or 0),
                   depends_on=tuple(r.get('depends_on') or ())) for r in (rows or [])]


def _persist_revision(tree: str, op: str, r, old_canonical_id: str | None):
    """A4: 결과 belief base 영속 + removed/demoted belief 와 같은 tag 의 CANONICAL 노드 auto-rejudge
    (→former_canonical, verdict_source='engine') — 전부 단일 kg_tx(원자적, MERGE 멱등). 반환 demote 후보."""
    ts = datetime.now(timezone.utc).isoformat()
    beliefs = [dict(belief_id=b.belief_id, statement=b.statement, kind=b.kind, credence=b.credence,
                    problem_balance=b.problem_balance, connectivity=b.connectivity,
                    depends_on=list(b.depends_on)) for b in r.base]
    ops = [("""MATCH (t:LakatosTree {name:$tree})
               UNWIND $beliefs AS b
               MERGE (bel:Belief {belief_id: b.belief_id})
               SET bel.statement=b.statement, bel.kind=b.kind, bel.credence=b.credence,
                   bel.problem_balance=b.problem_balance, bel.connectivity=b.connectivity,
                   bel.depends_on=b.depends_on, bel.updated_at=$ts
               MERGE (t)-[:HAS_BELIEF]->(bel)""", dict(tree=tree, beliefs=beliefs, ts=ts))]
    demote = list(r.removed) + ([old_canonical_id] if op == 'demote_canonical' and old_canonical_id else [])
    if r.removed:
        ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_BELIEF]->(bel:Belief)
                       WHERE bel.belief_id IN $removed DETACH DELETE bel""",
                    dict(tree=tree, removed=list(r.removed))))
    if demote:
        # auto-rejudge: belief 가 사라진/강등된 같은 tag 의 CANONICAL 노드를 엔진이 강등(수동 재채점 0).
        # A4-richer: spine.reconcile_standing 정책 적용 — CANONICAL ∧ valid_until_rebutted=True 만
        # 자동 강등. 인간이 '반박-자동무효'를 끈 노드(valid_until_rebutted=False=human_locked)는 belief
        # contraction 으로도 자동 강등 금지(인간경계 존중). 전엔 blanket SET 이 이 lock 을 무시했음(버그).
        ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
                       WHERE e.tag IN $demote AND e.verdict='CANONICAL'
                             AND coalesce(e.valid_until_rebutted, true) = true
                       SET e.verdict='former_canonical', e.verdict_source='engine',
                           e.current_best_pointer=false, e.demoted_at=$ts""",
                    dict(tree=tree, demote=demote, ts=ts)))
    kg_tx(ops)
    hist(tree, 'agm_revise', op, {'removed': list(r.removed), 'added': list(r.added),
                                  'programme_shift_candidate': r.programme_shift_candidate,
                                  'auto_demote_candidates': demote,
                                  'demote_policy': 'reconcile_standing: CANONICAL∧valid_until_rebutted'})
    return demote


@app.post('/api/agm/revise')
def agm_revise(req: AgmReviseIn):
    """AGM 신념개정(P1) — expansion/contraction/revision/demote_canonical.
    hard core 는 PROTECTED: allow_hard_core 없이 깎으면 409, 깎이면 programme_shift_candidate=True.

    A4 (stateful): req.tree 주면 영속 belief base 를 로드(body base 없을 때)해 그 위에서 연산하고,
    결과를 한 kg_tx 로 영속하며, removed/demoted belief 와 같은 tag 의 CANONICAL 노드를 엔진이
    former_canonical 로 auto-rejudge(verdict_source='engine') — belief 변경이 verdict 변경을 수동
    재채점 없이 만든다. body-override 보존: tree 없으면 KG 미접촉(기존 stateless 계약 불변)."""
    loaded = bool(req.tree) and not req.base
    base = _load_belief_base(req.tree) if loaded else [_belief(b) for b in req.base]
    try:
        if req.op == 'expansion':
            if not req.new:
                raise HTTPException(422, 'expansion 은 new 필수')
            r = expansion(base, _belief(req.new))
        elif req.op == 'contraction':
            if not req.target_id:
                raise HTTPException(422, 'contraction 은 target_id 필수')
            r = contraction(base, req.target_id, allow_hard_core=req.allow_hard_core)
        elif req.op == 'revision':
            if not req.new:
                raise HTTPException(422, 'revision 은 new 필수')
            r = revision(base, _belief(req.new), contradicts=req.contradicts,
                         allow_hard_core=req.allow_hard_core)
        elif req.op == 'demote_canonical':
            if not (req.new and req.old_canonical_id):
                raise HTTPException(422, 'demote_canonical 은 new + old_canonical_id 필수')
            r = demote_canonical(base, req.old_canonical_id, _belief(req.new),
                                 allow_hard_core=req.allow_hard_core)
        else:
            raise HTTPException(422, f'미지원 op: {req.op} (expansion|contraction|revision|demote_canonical)')
    except HardCoreProtected as e:
        raise HTTPException(409, str(e))
    out = dict(
        op=req.op,
        base=[dict(belief_id=b.belief_id, statement=b.statement, kind=b.kind,
                   credence=b.credence, problem_balance=b.problem_balance,
                   connectivity=b.connectivity, depends_on=list(b.depends_on)) for b in r.base],
        removed=list(r.removed), added=list(r.added),
        programme_shift_candidate=r.programme_shift_candidate,
        entrenchment_policy=r.entrenchment_policy)
    if req.tree:
        out['auto_demote_candidates'] = _persist_revision(req.tree, req.op, r, req.old_canonical_id)
        out['persisted'] = True
        out['loaded_base'] = loaded
    return out


# ── 하네스 사이클 (P5-C) — 서버 in-process 오케스트레이션, bash 미실행(no RCE) ──

def run_cycle(name: str, c: CycleIn):
    return _programme_service().run_cycle(name, c)


def add_artifact(name: str, a: ArtifactIn):
    return _programme_service().add_artifact(name, a)


def add_element(name: str, el: ElementIn):
    return _programme_service().add_element(name, el)


def attach_element(name: str, tag: str, element_name: str, use: ElementUseIn):
    return _programme_service().attach_element(name, tag, element_name, use)


def add_foundation_requirement(name: str, req: FoundationRequirementIn):
    return _programme_service().add_foundation_requirement(name, req)


def get_foundation_requirements(name: str):
    return _programme_service().get_foundation_requirements(name)

def history(name: str, limit: int = 100):
    return _programme_service().history(name, limit=limit)


def neo4j_constraint_diagnostics():
    return _programme_service().neo4j_constraint_diagnostics()


def record_derivation(d: DerivationIn):
    return _lineage_service().record_derivation(d)

def _load_lineage():
    return _lineage_service(use_load_facade=False).load_lineage()

def artifact_openlineage(artifact: str):
    """완성본의 OpenLineage RunEvent 들 (생태계 표준 — 어댑터 노출, F-ARCH-5)."""
    return _lineage_service().artifact_openlineage(artifact)

def send_artifact_to_marquez(artifact: str):
    """완성본 OpenLineage event 를 Marquez 로 전송 (전송층, F-ARCH-5 완결).

    직렬화는 /api/openlineage 가, 전송만 여기서 — MARQUEZ_URL env-gated(미설정 503).
    토큰 필요 시 MARQUEZ_TOKEN env. 자격증명 없으면 조용히 비활성(골방 아님, 흘려보낼 길은 열림).
    """
    return _lineage_service().send_artifact_to_marquez(artifact)

def artifact_dvc(artifact: str):
    """완성본 계보를 DVC dvc.yaml/dvc.lock 형태로 (raw-rooted replay, F-ARCH-5)."""
    return _lineage_service().artifact_dvc(artifact)

def artifact_prov(artifact: str, format: str | None = None):
    """완성본 계보의 W3C PROV 문서 (Entity/Activity/Agent, F-ARCH-5).

    쿼리 파라미터:
      format (str|None, 기본 None): 'prov-json' 이면 표준 W3C PROV-JSON 직렬화
        (prefix/entity/activity/agent/관계). 미지정 시 내부 dict (ENG-DU-3: 전엔 내부 dict 를 'W3C PROV'라 오칭).
    """
    return _lineage_service().artifact_prov(artifact, format=format)

def rebuild_verify(artifact: str):
    """G-RebuildFromRaw — 완성본이 raw root + 현재 환경에서 재생성 가능한가."""
    return _lineage_service().rebuild_verify(artifact)

def get_script_history(producer: str):
    """생산 스크립트 버전 이력 — 중간에 수정되면 sha 바뀜, 각 버전이 만든 산출물(시간순)."""
    return _lineage_service().get_script_history(producer)

def get_lineage(artifact: str, stale: bool = False):
    """완성본의 계보 — source(ZDF) 추적 + 재빌드 플랜 + 재현 가능성 + 끊긴 링크.

    쿼리 파라미터:
      stale (bool, 기본 false): true 면 입력 sha 불일치(stale_inputs)도 포함해 표시한다.
    """
    return _lineage_service().get_lineage(artifact, stale=stale)

VC = VERDICT_COLORS

def _tree_stack_lifecycle(td):
    """대시보드용 — 정본 leaf 의 stack 판결 + lifecycle 상태 (정본 없으면 None)."""
    try:
        bi = branch_inputs(td['nodes'], td['frontier'])     # leaf=None → 정본 leaf
        sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                            bi['prediction_hits'], bi['problem_balance_windowed'])
        ls = lifecycle_state(bi['verdicts'], sv, bi['novel_registered_recent'],
                             bi['problem_balance_windowed'], bi['canonical_improved_recent'])
        return bi['leaf'], sv, ls
    except Exception:   # 엣지 데이터(정본 부재/이상 시퀀스)가 대시보드를 깨지 않게 (DASHBOARD-UNGUARDED)
        return None


@app.get('/', response_class=HTMLResponse)
def dashboard():
    return render_dashboard(
        trees=trees,
        tree_data=tree_data,
        compute_metrics=compute_metrics,
        build_leaderboard=build_leaderboard,
        competitor_for_tree=_competitor_for_tree,
        tree_stack_lifecycle=_tree_stack_lifecycle,
    )
