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
import html, json, os, secrets, sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hashlib
from lakatos.judge import (Prediction, NovelTarget, judge, PredictionMissing,
                           PredictionLocked, check_registration)
from lakatos.metrics import tree_metrics, branch_inputs
from lakatos.stack import evaluate_stack
from lakatos.lifecycle import lifecycle_state
from lakatos.leaderboard import Competitor, leaderboard as build_leaderboard
from lakatos.kuhn import assess_paradigm
from lakatos.certify import gate_check, certify_claim, next_actions as cert_next_actions
from lakatos.prov import prov_triples, replay_command
from lakatos.explore import rank_questions
from lakatos.argue import grounded_extension, verdict_stands
from lakatos.promote import promotion_gate
from lakatos.spine import (reconcile_verdict, promotion_decision, synthesize_promotion,
                           credibility_from_trust, dialectical_verdict)
from lakatos.pnr import appraise_response, Response, CounterexampleType, ProofGeneratedConcept
from lakatos.agm import (Belief, expansion, contraction, revision, demote_canonical,
                         HardCoreProtected, ENTRENCHMENT_POLICY)
from lakatos.adapters import (lineage_result_to_openlineage_events, derivations_to_dvc_pipeline,
                              derivations_to_dvc_lock, derivations_to_prov_document,
                              prov_document_to_prov_json)
from lakatos.calibrate import brier_score, log_score, calibration_error
from lakatos.trust import evidence_weight
from lakatos.verdicts import ADMIN_VERDICTS, is_admin_verdict
from lakatos.engine import (FoundationMap, FoundationRequirement, KnowledgeKind,
                            LineageReplayGate, Possibility, Realm, ResearchEvent,
                            ResearchFrame, ResearchProject, LakatosGate, LakatosEvidence)
from lakatos.claim import ClaimStandingPolicy, evaluate_claim_standing
from lakatos.lineage import (Derivation, by_output, roots as lin_roots, rebuild_plan,
                             reproducibility_gaps, stale_inputs, script_history,
                             build_manifest, env_drift)   # OPS-DEAD-5: is_reproducible/RawRoot/RebuildManifest 미사용 제거
from lakatos.envfp import environment_fingerprint, fingerprint_sha, env_matches
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, TypeAdapter
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired
import psycopg2, psycopg2.extras, psycopg2.pool
from psycopg2 import OperationalError as PgOperationalError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

NEO = GraphDatabase.driver(os.environ['NEO4J_URI'],
                           auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']))
PG_KW = dict(host=os.environ.get('LAKATOS_PG_HOST', 'localhost'),
             port=int(os.environ.get('LAKATOS_PG_PORT', '55100')),
             user=os.environ.get('LAKATOS_PG_USER', 'admin'),
             password=os.environ.get('LAKATOS_PG_PASSWORD', ''),
             dbname=os.environ.get('LAKATOS_PG_DB', 'lakatos'))
MONGO = MongoClient(os.environ.get('LAKATOS_MONGO_URI', 'mongodb://localhost:27017'))['lakatos']
app = FastAPI(title='Lakatos Server', version='1.0')
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


_PG_POOL = None

def _pg_pool():
    global _PG_POOL
    if _PG_POOL is None:   # lazy init — import 시 미연결(테스트/오프라인 안전)
        _PG_POOL = psycopg2.pool.ThreadedConnectionPool(1, 16, **PG_KW)
    return _PG_POOL

@contextmanager
def pg():
    """OPS-DEAD-1: ThreadedConnectionPool 에서 빌려 쓰고 반납 — 매 요청 새 커넥션 생성·누수 방지.
    성공 시 commit, 예외 시 rollback, 항상 putconn (psycopg2 conn 의 with 는 tx 만 닫고 conn 은 안 닫았음)."""
    conn = _pg_pool().getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pg_pool().putconn(conn)

def hist(tree, op, node_tag=None, payload=None):
    # ROB-1: 이력(PG)은 best-effort audit, KG=truth. KG 커밋 후 PG 다운이 mutation 을 503 으로
    # 되돌리면 그래프-이력 분기가 *더 나빠지므로*, PG 연결오류는 삼키고 경고만(이력만 유실).
    try:
        with pg() as c, c.cursor() as cur:
            cur.execute('INSERT INTO history(tree, op, node_tag, payload) VALUES (%s,%s,%s,%s)',
                        (tree, op, node_tag, json.dumps(payload or {}, ensure_ascii=False)))
    except PgOperationalError as e:
        print(f'[hist] PG 적재 실패(best-effort, KG 는 정상): {type(e).__name__}', file=sys.stderr)

def kg(q, **kw):
    with NEO.session() as s:
        return s.run(q, **kw).data()

def kg_tx(ops):
    """여러 Cypher 를 단일 managed write 트랜잭션으로 (all-or-nothing) — KG-내부 부분쓰기
    (노드만 생성·엣지 누락 등) 분기 차단 (ROB-1). ops = [(cypher, params), ...]."""
    def _unit(tx):
        return [tx.run(cypher, **params).data() for cypher, params in ops]
    with NEO.session() as s:
        return s.execute_write(_unit)

def _file_sha(path, chunk=1 << 20):
    """파일 sha256 을 청크 스트리밍 — GB(ZDF) 파일도 메모리 bounded (ROB-5). OSError 는 호출부."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(chunk), b''):
            h.update(blk)
    return h.hexdigest()

def _path_sha(path):
    """파일/디렉토리 current sha — 단일 정본 헬퍼(OPS-COR-2/3). isfile=스트리밍 _file_sha(메모리 bounded),
    isdir(ZDF lot)=내용 파일 이름+크기 합성(내용 미독), 읽기 실패=__unreadable__(stale 로 표면화),
    경로 부재=None. get_lineage?stale·rebuild_verify 가 공유(전엔 rebuild_verify 만 전체파일 read + dir 무시)."""
    try:
        if os.path.isfile(path):
            return _file_sha(path)
        if os.path.isdir(path):
            h = hashlib.sha256()
            for f in sorted(os.listdir(path)):
                fp = os.path.join(path, f)
                if os.path.isfile(fp):
                    h.update(f.encode()); h.update(str(os.path.getsize(fp)).encode())
            return h.hexdigest()
    except OSError as e:
        return f'__unreadable__:{type(e).__name__}'
    return None

def _safe_rebuild_plan(artifact, bo):
    """ENGINE-ROB-3: 계보 사이클이면 rebuild_plan 이 ValueError → 500 누수 대신 빈 plan(재현불가).
    reproducibility_gaps 도 사이클을 갭으로 보므로 reproducible=False 와 일관."""
    try:
        return rebuild_plan(artifact, bo)
    except ValueError:
        return []

NODE_LABELS = 'PrismExperiment|LakatosNode'

def tree_data(name):
    t = kg('MATCH (t:LakatosTree {name:$n}) RETURN t.title AS title, t.hard_core AS hard_core, '
           't.frontier_rule AS frontier_rule, t.doc AS doc, '
           't.coverage_backlog AS coverage_backlog, t.coverage_statement AS coverage_statement', n=name)
    if not t:
        raise HTTPException(404, f'나무 없음: {name}')
    nodes = kg(f'''MATCH (t:LakatosTree {{name:$n}})-[:HAS_NODE]->(e)
        OPTIONAL MATCH (e)-[bf:BRANCHED_FROM]->(p)
        WITH e, collect(DISTINCT {{tag:p.tag, inferred:coalesce(bf.inferred,false),
             relation_kind:coalesce(bf.relation_kind,'knowledge_inheritance'),
             evidence_ref:coalesce(bf.evidence_ref,'')}}) AS raw_parent_edges
        OPTIONAL MATCH (e)-[:RAISES_QUESTION]->(q)
        WITH e, [pe IN raw_parent_edges WHERE pe.tag IS NOT NULL] AS parent_edges,
             collect(DISTINCT q.name) AS questions
        RETURN e.tag AS tag, e.verdict AS verdict, e.note AS note, e.script AS script,
               e.result_path AS result_path, e.algorithm AS algorithm, e.comment AS comment,
               e.limitation AS limitation, e.open_question AS open_question,
               e.metric_name AS metric_name, e.metric_value AS metric_value,
               e.metric_scope AS metric_scope, e.novel_registered AS novel_registered,
               e.novel_confirmed AS novel_confirmed,
               e.pred_baseline AS pred_baseline, e.pred_noise_band AS pred_noise_band,
               e.pred_direction AS pred_direction,
               CASE WHEN size(parent_edges)>0 THEN parent_edges[0].tag ELSE null END AS parent,
               [pe IN parent_edges | pe.tag] AS parents, parent_edges AS parent_edges,
               questions AS questions
        ORDER BY tag''', n=name)
    qs = kg('MATCH (t:LakatosTree {name:$n})-[:HAS_FRONTIER]->(q) '
            'RETURN q.name AS name, q.status AS status, q.body AS body, '
            'q.closed_by AS closed_by, q.expected_gain AS expected_gain, '
            'q.cost AS cost, q.n_visits AS n_visits', n=name)
    return dict(name=name, **t[0], nodes=nodes, frontier=qs)

def compute_metrics(td):
    return tree_metrics(td['nodes'], td['frontier'], cfg={
        'coverage_backlog': td.get('coverage_backlog') or [],
        'coverage_statement': td.get('coverage_statement') or '',
    })

@app.get('/api/trees')
def trees():
    return kg('MATCH (t:LakatosTree) RETURN t.name AS name, t.title AS title')

@app.get('/api/tree/{name}')
def tree(name: str):
    return tree_data(name)

@app.get('/api/tree/{name}/metrics')
def metrics(name: str, snapshot: bool = False):
    m = compute_metrics(tree_data(name))
    if snapshot:   # 나생문 F-FG-8: GET 부작용 제거 — 명시적 요청시만 적재
        with pg() as c, c.cursor() as cur:
            cur.execute('INSERT INTO metric_snapshots(tree, metrics) VALUES (%s,%s)',
                        (name, json.dumps(m, ensure_ascii=False)))
    return m

class ParentEdgeIn(BaseModel):
    tag: str
    inferred: bool = False
    relation_kind: str = 'knowledge_inheritance'
    evidence_ref: str = ''


class NodeIn(BaseModel):
    tag: str = Field(min_length=1)   # ROB-6: 빈 tag 금지(KG 합성키 $tree+'/'+$tag 오염 방지)
    parent: str | None = None
    parents: list[str] = Field(default_factory=list)
    parent_edges: list[ParentEdgeIn] = Field(default_factory=list)
    verdict: str = 'proof'
    script: str = ''
    result_path: str = ''
    algorithm: str = ''
    comment: str = ''
    limitation: str = ''
    open_question: str = ''
    metric_name: str | None = None
    metric_value: float | None = None
    metric_scope: str | None = None


def _normalized_parent_edges(n: NodeIn) -> list[ParentEdgeIn]:
    edges: dict[str, ParentEdgeIn] = {}
    if n.parent:
        edges[n.parent] = ParentEdgeIn(tag=n.parent)
    for p in n.parents:
        edges.setdefault(p, ParentEdgeIn(tag=p))
    for edge in n.parent_edges:
        edges[edge.tag] = edge
    if n.tag in edges:
        raise HTTPException(400, '자기 자신을 parent 로 둘 수 없음')
    return list(edges.values())


@app.post('/api/tree/{name}/node')
def add_node(name: str, n: NodeIn):
    td = tree_data(name)   # 존재 검증
    existing = {r['tag'] for r in td['nodes']}
    parent_edges = _normalized_parent_edges(n)
    missing = [e.tag for e in parent_edges if e.tag not in existing]
    if missing:
        raise HTTPException(400, f'부모 노드 없음: {missing}')
    # ROB-1: 노드 생성 + 모든 부모엣지를 단일 트랜잭션으로 (부분쓰기=노드만/엣지누락 분기 차단)
    ops = [('''MATCH (t:LakatosTree {name:$tree})
               MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+$tag})
               SET e.tag=$tag, e.verdict=$verdict, e.script=$script, e.result_path=$result_path,
                   e.algorithm=$algorithm, e.comment=$comment, e.limitation=$limitation,
                   e.open_question=$open_question, e.metric_name=$metric_name,
                   e.metric_value=$metric_value, e.metric_scope=$metric_scope,
                   e.recorded_at=$ts
               MERGE (t)-[:HAS_NODE]->(e)''',
            dict(tree=name, ts=datetime.now(timezone.utc).isoformat(), **n.model_dump()))]
    for edge in parent_edges:
        ops.append(('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       MATCH (t)-[:HAS_NODE]->(p {tag:$parent})
                       MERGE (e)-[r:BRANCHED_FROM]->(p)
                       SET r.inferred=$inferred, r.relation_kind=$relation_kind, r.evidence_ref=$evidence_ref''',
                    dict(tree=name, tag=n.tag, parent=edge.tag, inferred=edge.inferred,
                         relation_kind=edge.relation_kind, evidence_ref=edge.evidence_ref)))
    kg_tx(ops)
    hist(name, 'node_create', n.tag, n.model_dump())
    return {'ok': True, 'tag': n.tag}

class VerdictIn(BaseModel):
    verdict: str
    note: str = ''
    scope: str = ''
    assumptions: list[str] = Field(default_factory=list)
    evidence_window: str = ''
    valid_until_rebutted: bool = True
    human_verdict: bool = False     # 인간이 직접 vouch — CredibilityPromotionGate 인간판정 신호

@app.post('/api/tree/{name}/node/{tag}/verdict')
def set_verdict(name: str, tag: str, v: VerdictIn):
    if not is_admin_verdict(v.verdict):   # 나생문 F-FG-1: 판결 어휘 수동 덮어쓰기 금지
        raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                 f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
    if v.verdict == 'CANONICAL':   # demote+promote 단일 트랜잭션 (F-FG-5)
        # 나생문 F-CON-2/5 강제: 승격 전 헌법 게이트 — 퇴행 가지·막지못한 의문 차단
        pre = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                    OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                    RETURN cur.verdict AS verdict,
                           cur.source_trust AS source_trust,
                           cur.novel_confirmed AS novel_confirmed,
                           collect({id:a.id, attacks:a.attacks}) AS args''', tree=name, tag=tag)
        if not pre:
            raise HTTPException(404, f'노드 없음: {tag}')
        cand = pre[0]
        varg = f'verdict:{tag}'
        arguments = {varg}
        attacks = []
        for a in (cand.get('args') or []):
            if not a.get('id'):
                continue
            short = a['id'].split('/')[-1]
            arguments.add(short)
            attacks.append((short, varg if a.get('attacks') == tag else a.get('attacks')))
        stands = varg in grounded_extension(arguments, attacks)
        # 완전 합성: 헌법 + FoundationGate(나무 준비도) + CredibilityPromotionGate(인터넷 등급)
        #  — 강건한 엔진 척추. source_trust<0.70 인 저신뢰 인터넷 영향 노드는 직접출처/인간판정 없이 CANONICAL 차단.
        foundation = _foundation_from_rows(_foundation_rows(name))
        st = cand.get('source_trust')
        credibility = credibility_from_trust(
            float(st) if st is not None else 1.0,
            novel_confirmed=bool(cand.get('novel_confirmed')),
            has_human_verdict=bool(v.human_verdict),
        )
        # F-CON-1: 노드↔계보 링크(result_path) → 재현성 게이트 자동 공급.
        #  완성본이 raw root(ZDF)서 재생성 불가하면 CANONICAL 차단. None=비파이프라인 노드(비적용).
        #  재현성은 CANONICAL(현재best 진리주장)에만 의도적 적용 — proof/superseded/canonical_stage 등
        #  행정상태는 재현불가여도 마킹 가능해야 하므로 게이트 비대상(나생문 REPRODUCIBLE_ONLY_CANONICAL_GATE 의도).
        reproducible = _reproducible_for_node(name, tag)
        decision = synthesize_promotion(scripted_verdict=cand.get('verdict') or 'proof',
                                        stands=stands, foundation=foundation,
                                        credibility=credibility, reproducible=reproducible)
        if not decision['ok']:
            raise HTTPException(409, f"CANONICAL 승격 차단(합성 엔진 게이트): {list(decision['reasons'])}. "
                                     f"게이트별: {decision['gates']}")
        kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
              WITH t, cur
              OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
              WHERE old.tag <> $tag
              SET old.verdict='former_canonical', old.current_best_pointer=false
              SET cur.verdict='CANONICAL', cur.verdict_source='admin',
                  cur.current_best_pointer=true,
                  cur.canonical_scope=$scope,
                  cur.canonical_assumptions=$assumptions,
                  cur.canonical_evidence_window=$evidence_window,
                  cur.valid_until_rebutted=$valid_until_rebutted ''',
           tree=name, tag=tag, scope=v.scope, assumptions=v.assumptions,
           evidence_window=v.evidence_window, valid_until_rebutted=v.valid_until_rebutted)
        r = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag}) RETURN e.tag AS tag''',
               tree=name, tag=tag)
    else:
        r = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  SET e.verdict=$verdict, e.verdict_source='admin' RETURN e.tag AS tag''',
               tree=name, tag=tag, verdict=v.verdict)
    if not r:
        raise HTTPException(404, f'노드 없음: {tag}')
    hist(name, 'verdict', tag, v.model_dump())
    return {'ok': True}

class QuestionIn(BaseModel):
    qname: str = Field(min_length=1)   # ROB-6
    body: str = ''
    # 탐색배분(VoI/UCB) 입력 — 이게 write 안 되면 directions 가 전부 default 로 떨어져 dead (WIRE-1)
    expected_gain: float = Field(0.1, ge=0)   # 이 질문이 닫히면 기대되는 진보 이득
    cost: float = Field(1.0, gt=0)            # 검증 비용 (VoI = gain/cost)

@app.post('/api/tree/{name}/question')
def open_question(name: str, q: QuestionIn):
    kg('''MATCH (t:LakatosTree {name:$tree})
          MERGE (qn:OpenQuestion {name:$qn})
          SET qn.body=$body, qn.status='OPEN', qn.created_at=$ts,
              qn.expected_gain=$expected_gain, qn.cost=$cost,
              qn.n_visits=coalesce(qn.n_visits, 0)
          MERGE (t)-[:HAS_FRONTIER]->(qn)''',
       tree=name, qn=q.qname, body=q.body, expected_gain=q.expected_gain, cost=q.cost,
       ts=datetime.now(timezone.utc).isoformat())
    hist(name, 'question_open', None, q.model_dump())
    return {'ok': True}

@app.post('/api/tree/{name}/question/{qname}/close')
def close_question(name: str, qname: str, closed_by: str = ''):
    ts = datetime.now(timezone.utc).isoformat()
    closure_id = f'{name}/{qname}/closure/{closed_by or "unknown"}@{ts}'
    r = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn})
              SET q.status='CLOSED',
                  q.n_visits=coalesce(q.n_visits, 0) + 1,
                  q.closed_by=CASE
                    WHEN q.closed_by IS NULL THEN [$by]
                    WHEN $by IN q.closed_by THEN q.closed_by
                    ELSE q.closed_by + $by
                  END,
                  q.closed_events=CASE
                    WHEN q.closed_events IS NULL THEN [$closure_id]
                    ELSE q.closed_events + $closure_id
                  END
              MERGE (c:QuestionClosure {id:$closure_id})
              SET c.closed_by=$by, c.at=$ts, c.tree=$tree, c.question=$qn
              MERGE (q)-[:HAS_CLOSURE]->(c)
              RETURN q.name AS name''',
           tree=name, qn=qname, by=closed_by, closure_id=closure_id, ts=ts)
    if not r:
        raise HTTPException(404, f'질문 없음: {qname}')
    hist(name, 'question_close', closed_by, {'question': qname})
    return {'ok': True}

class PredictionIn(BaseModel):
    """사전등록 (실행 전 의무) — 라카토스: 진보 = 새로운 예측이 적중하는 것."""
    metric_name: str
    direction: str = 'lower'          # lower|higher = 개선 방향
    baseline_value: float             # 비교 기준 (보통 CANONICAL 의 값)
    noise_band: float = Field(0.0, ge=0)   # 나생문 F-FG-2: 음수 금지(worse-is-progressive 차단)
    novel_prediction: str = ''        # (구) 자유텍스트 — 구조적 명세 권장
    novel_metric: str | None = None   # (신) 구조적 corroboration: 예측 metric
    novel_direction: str | None = None    # lower|higher
    novel_threshold: float | None = None  # 이 값 넘어야 적중
    judge_script_sha: str | None = None   # 채점 스크립트 sha256 사전고정 (무결성)
    closes_question: str = ''         # 닫으려는 OpenQuestion
    # 발급자가 사전등록 시 밝히는 예측 신뢰도 [0,1] — calibrate(Brier/ECE) 입력. 이게 없으면
    # /calibration 이 영구 n=0 → certify G4(calibrated) 영원히 fail → 인증서 발급 불가 (T3-1)
    credence: float | None = Field(None, ge=0, le=1)

@app.post('/api/tree/{name}/node/{tag}/prediction')
def register_prediction(name: str, tag: str, p: PredictionIn):
    r = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
              WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
              SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                  e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                  e.pred_novel=$novel_prediction, e.pred_closes=$closes_question,
                  e.pred_novel_metric=$novel_metric, e.pred_novel_direction=$novel_direction,
                  e.pred_novel_threshold=$novel_threshold, e.pred_script_sha=$judge_script_sha,
                  e.pred_credence=$credence,
                  e.novel_registered = ($novel_metric IS NOT NULL),
                  e.pred_registered_at=$ts
              RETURN e.tag AS tag""",
           tree=name, tag=tag, ts=datetime.now(timezone.utc).isoformat(), **p.model_dump())
    if not r:
        raise HTTPException(409, '노드 없음 또는 이미 채점됨 — 사후 예측등록 금지')
    if p.closes_question:   # WIRE1-UCB: 이 질문에 대한 attempt → OPEN 질문 n_visits++ → UCB 탐색항 차등 부활
        kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$cq})
              SET q.n_visits=coalesce(q.n_visits, 0) + 1''', tree=name, cq=p.closes_question)
    hist(name, 'prediction_register', tag, p.model_dump())
    return {'ok': True, 'note': '예측 사전등록 완료 — 이제 실험을 실행하고 test_result 를 스크립트로 제출'}

class TestResultIn(BaseModel):
    """채점 스크립트 산출 — LLM 점수 금지, 판결은 규칙으로 자동."""
    metric_value: float
    script: str = Field(min_length=1)   # 채점 스크립트 경로 (ROB-6/R2: 빈 script→cert 고무도장 차단)
    script_sha: str | None = None    # 제출 스크립트 sha256 (사전등록과 대조)
    novel_measured: float | None = None   # 구조적 novel 예측의 실측값
    source_trust: float = 1.0        # 상계(인터넷) 증거 신뢰 [0,1] — 베이즈 결합용
    result_path: str = ''            # 원본 결과 파일
    log: str = ''
    # 라카토스 질적 증거(LakatosGate) — 4 기준 다 주면 spine 이 메트릭 진보를 질적으로 검증
    lakatos_anomaly: bool | None = None        # theory_laden_anomaly
    lakatos_consequence: bool | None = None    # independent_testable_consequence
    lakatos_excess: bool | None = None         # excess_empirical_content
    lakatos_hardcore: bool | None = None       # hard_core_preserved
    implementation_complete: bool = True
    # 증명과반박 변증법(PnR) — 이 노드가 반례에 대응한 것이면 *대응 방식*이 진보/퇴행을 가른다
    counterexample_response: str | None = None  # surrender|monster_barring|exception_barring|monster_adjustment|lemma_incorporation|proofs_and_refutations
    counterexample_type: str | None = None       # (선택) global|local|local_and_global|local_not_global|global_not_local — 숨은 보조정리 진단
    ce_excess_content: bool = False             # 대응이 초과 경험내용을 더했나
    ce_novel_corroborated: bool = False         # 그 초과내용 중 확증된 novel 사실
    ce_in_heuristic_spirit: bool | None = None  # 양의 휴리스틱 정신 내인가(미지정=미검증)
    # 증명-생성 개념(ENG-DU-1) — PnR 성숙 진보 표식. 3 필드 다 주면 progressive 확정(없으면 conditional)
    ce_proof_concept_name: str | None = None
    ce_proof_born_from: str | None = None        # 어느 반례가 낳았나
    ce_proof_incorporated_lemma: str | None = None  # 어느 숨은 보조정리를 조건화했나

@app.post('/api/tree/{name}/node/{tag}/test_result')
def submit_test_result(name: str, tag: str, r: TestResultIn):
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 RETURN e.pred_metric AS m, e.pred_direction AS d, e.pred_baseline AS b,
                        e.pred_noise_band AS nb, e.pred_novel AS novel, e.verdict_source AS vsrc,
                        e.pred_novel_metric AS nmet, e.pred_novel_direction AS ndir,
                        e.pred_novel_threshold AS nthr, e.pred_script_sha AS psha""", tree=name, tag=tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    pr = rows[0]
    if pr['vsrc'] == 'scripted':   # 나생문 F-FG-1: re-roll 금지
        raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). 새 노드로 분기할 것')
    # P0 스크립트 무결성: 사전등록 sha 와 제출 sha 불일치 시 거부 (재현성 강제)
    if pr['psha'] and r.script_sha and pr['psha'] != r.script_sha:
        raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 제출 {r.script_sha[:12]}")
    nt = None
    if pr['nmet'] and pr['ndir'] and pr['nthr'] is not None:
        nt = NovelTarget(metric_name=pr['nmet'], direction=pr['ndir'], threshold=pr['nthr'])
    try:
        v = judge(None if pr['m'] is None else Prediction(
            metric_name=pr['m'], direction=pr['d'], baseline_value=pr['b'],
            noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or ''),
            r.metric_value, novel_target=nt, novel_measured=r.novel_measured)
    except PredictionMissing as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    delta = v.delta
    # 엔진 spine: judge(메트릭) + LakatosGate(질적) 합의 — F-ARCH-1 두 엔진 통합
    lak_result = None
    if None not in (r.lakatos_anomaly, r.lakatos_consequence, r.lakatos_excess, r.lakatos_hardcore):
        lak_result = LakatosGate.evaluate(LakatosEvidence(
            theory_laden_anomaly=r.lakatos_anomaly,
            independent_testable_consequence=r.lakatos_consequence,
            excess_empirical_content=r.lakatos_excess,
            hard_core_preserved=r.lakatos_hardcore,
            implementation_complete=r.implementation_complete))
    # PnR 변증법: 반례 대응이면 *대응 방식*이 판결을 가른다(monster-barring 은 메트릭 진보도 강등)
    pnr_appraisal = None
    if r.counterexample_response:
        try:
            resp = Response(r.counterexample_response)
        except ValueError:
            raise HTTPException(422, f'알 수 없는 반례 대응: {r.counterexample_response} — '
                                     f'{[e.value for e in Response]} 중 하나')
        ce_type = None
        if r.counterexample_type:
            try:
                ce_type = CounterexampleType(r.counterexample_type)
            except ValueError:
                raise HTTPException(422, f'알 수 없는 반례유형: {r.counterexample_type} — '
                                         f'{[e.value for e in CounterexampleType]} 중 하나')
        pgc = None   # ENG-DU-1: 증명-생성 개념(있으면 PnR 성숙 진보로 확정)
        if r.ce_proof_concept_name:
            pgc = ProofGeneratedConcept(
                name=r.ce_proof_concept_name,
                born_from_counterexample=r.ce_proof_born_from or '',
                incorporated_lemma=r.ce_proof_incorporated_lemma or '')
        pnr_appraisal = appraise_response(
            resp, excess_content=r.ce_excess_content, novel_corroborated=r.ce_novel_corroborated,
            in_heuristic_spirit=r.ce_in_heuristic_spirit,
            hard_core_preserved=(r.lakatos_hardcore if r.lakatos_hardcore is not None else True),
            counterexample_type=ce_type, proof_generated_concept=pgc)
    decided = dialectical_verdict(v.verdict, pnr_appraisal=pnr_appraisal, lakatos_result=lak_result)
    verdict = decided['verdict']
    lakatos_status = decided['lakatos']
    ts = datetime.now(timezone.utc).isoformat()
    # OPS-HON-2: 판결 SET + PROV-O 계보(W3C) 를 단일 tx 로 — 부분쓰기(판결만 기록·PROV 누락) 분기 차단
    ops = [("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
               SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                   e.verdict_source='scripted', e.judge_script=$script, e.judge_script_sha=$sha,
                   e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts,
                   e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat""",
            dict(tree=name, tag=tag, mn=pr['m'], mv=r.metric_value, v=verdict,
                 script=r.script, sha=r.script_sha, rp=r.result_path, ts=ts, novel=v.novel,
                 st=r.source_trust, lstat=lakatos_status))]
    for tr in prov_triples(name, tag, r.script, r.result_path, verdict, r.script_sha or '', ts):
        if tr.get('kind'):
            ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  MERGE (p:ProvNode {id:$id}) SET p.kind=$kind, p.type=$type, p.sha256=$sha
                  MERGE (e)-[:HAS_PROV]->(p)""",
                        dict(tree=name, tag=tag, id=tr['id'], kind=tr['kind'],
                             type=tr.get('type'), sha=tr.get('sha256'))))
        else:
            ops.append(("""MERGE (a:ProvNode {id:$f}) MERGE (b:ProvNode {id:$to})
                  MERGE (a)-[rel:PROV_REL {kind:$rk}]->(b)""",
                        dict(f=tr['from'], to=tr['to'], rk=tr['rel'])))
    kg_tx(ops)
    hist(name, 'test_result', tag, dict(value=r.metric_value, baseline=pr['b'],
                                        delta=round(delta, 4), verdict=verdict, script=r.script,
                                        novel=v.novel, script_sha=r.script_sha))
    return {'ok': True, 'verdict': verdict, 'delta': round(delta, 4), 'novel': v.novel,
            'lakatos': lakatos_status, 'metric_verdict': v.verdict,
            'rule': v.reason, 'replay': replay_command(r.script, r.result_path)}

@app.get('/api/tree/{name}/node/{tag}/provenance')
def provenance(name: str, tag: str):
    """판결의 W3C PROV-O 계보 + 재현 명령."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 OPTIONAL MATCH (e)-[:HAS_PROV]->(p:ProvNode)
                 RETURN e.judge_script AS script, e.result_path AS rp, e.verdict AS verdict,
                        e.judge_script_sha AS sha, collect({id:p.id,kind:p.kind,type:p.type}) AS prov""",
              tree=name, tag=tag)
    if not rows or rows[0]['script'] is None:
        raise HTTPException(404, '채점 이력 없음')
    x = rows[0]
    return dict(tag=tag, verdict=x['verdict'], script=x['script'], script_sha=x['sha'],
                result_path=x['rp'], prov_graph=[p for p in x['prov'] if p['id']],
                replay=replay_command(x['script'] or '', x['rp'] or ''))

class CritiqueIn(BaseModel):
    """인간/agent 의 의문·코멘트·반박 (Dung argument attack). 역할: 인간+agent=비판."""
    arg_id: str                      # 이 논증의 식별자 (예: doubt:reviewer1)
    attacks: str                     # 무엇을 공격하는가 (노드 tag, 또는 다른 arg_id)
    by: str = ''                     # 누가 (human:name / agent:name)
    kind: str = 'doubt'              # doubt | comment | rebuttal | evaluation
    body: str = ''


class ResearchEventIn(BaseModel):
    """ClaimStanding 용 상계/하계 event. 판결을 바꾸지 않는 append-only evidence."""
    event_id: str
    realm: str
    actor: str = ''
    action: str
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, str] = Field(default_factory=dict)
    created_at: str | None = None

    def to_engine(self, target: str) -> ResearchEvent:
        try:
            realm = Realm(self.realm)
        except ValueError as exc:
            raise HTTPException(422, f'unknown research event realm: {self.realm}') from exc
        return ResearchEvent(
            name=self.event_id,
            realm=realm,
            actor=self.actor,
            action=self.action,
            target=target,
            evidence_refs=tuple(self.evidence_refs),
            payload=tuple((str(k), str(v)) for k, v in self.payload.items()),
        )

@app.post('/api/tree/{name}/node/{tag}/critique')
def add_critique(name: str, tag: str, c: CritiqueIn):
    kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
          MERGE (a:Argument {id:$tree+'/'+$arg}) SET a.by=$by, a.kind=$kind, a.body=$body,
                a.attacks=$attacks, a.at=$ts
          MERGE (e)-[:HAS_ARGUMENT]->(a)""",
       tree=name, tag=tag, arg=c.arg_id, by=c.by, kind=c.kind, body=c.body,
       attacks=c.attacks, ts=datetime.now(timezone.utc).isoformat())
    hist(name, 'critique', tag, c.model_dump())
    return {'ok': True, 'note': '비판 등재 — 코드 빌딩은 순수 agent(test_result) 담당'}


@app.post('/api/tree/{name}/node/{tag}/event')
def add_research_event(name: str, tag: str, ev: ResearchEventIn):
    engine_event = ev.to_engine(tag)
    ts = ev.created_at or datetime.now(timezone.utc).isoformat()
    event_id = f'{name}/{tag}/event/{engine_event.name}'
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 MERGE (ev:ResearchEvent {id:$id})
                 ON CREATE SET ev.name=$event_name, ev.realm=$realm, ev.actor=$actor,
                               ev.action=$action, ev.target=$tag,
                               ev.evidence_refs=$evidence_refs, ev.payload=$payload,
                               ev.created_at=$ts
                 MERGE (e)-[:HAS_RESEARCH_EVENT]->(ev)
                 RETURN ev.id AS id""",
              tree=name, tag=tag, id=event_id, event_name=engine_event.name,
              realm=engine_event.realm.value, actor=engine_event.actor,
              action=engine_event.action, evidence_refs=list(engine_event.evidence_refs),
              payload=json.dumps(dict(engine_event.payload), ensure_ascii=False), ts=ts)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    hist(name, 'research_event', tag, {**engine_event.db_record(), 'id': event_id})
    return {'ok': True, 'id': event_id, 'event': engine_event.name}

@app.get('/api/tree/{name}/node/{tag}/standing')
def standing(name: str, tag: str):
    """판결이 의문들을 막아내고 서는가 — Dung grounded extension."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                 RETURN e.verdict AS verdict, collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
              tree=name, tag=tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    verdict_arg = f'verdict:{tag}'
    arguments = {verdict_arg}
    attacks = []
    for a in rows[0]['args']:
        if not a['id']:
            continue
        short = a['id'].split('/')[-1]
        arguments.add(short)
        tgt = verdict_arg if a['attacks'] == tag else a['attacks']
        attacks.append((short, tgt))
    ext = grounded_extension(arguments, attacks)
    stands = verdict_arg in ext
    return dict(tag=tag, verdict=rows[0]['verdict'], stands=stands,
                grounded_extension=sorted(ext),
                note='stands=False → 막지 못한 의문 존재, 판결 재검토 필요 (코드빌딩=순수agent)')


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
    """F-CON-1: 노드 result_path 가 계보에 기록된 완성본이면 raw-root 재현가능 여부.

    엄격 재현성 = 완성본의 *모든 궁극 root 가 선언된 source(kind='source')* 일 때만 True.
    reproducibility_gaps 단독은 "derivation 기록은 됐지만 inputs 빈 비-source(dangling leaf)"
    를 못 잡아 가짜 reproducible=True 를 냈다(나생문 CON-1/F-CON-1-A/B/LINEAGE-1 수렴 확인).
    roots() 는 그런 leaf 도 root 로 반환하므로 ⊆declared 검사가 갭+dangling 둘 다 포섭한다.
    result_path 없음 or 계보 미기록 → None(증명 노드 등 — 재현성 게이트 비적용, 차단 안 함).
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
    declared = {d.output for d in ds if d.kind == 'source'}
    if rp in declared:
        return True
    rts = lin_roots(rp, bo)   # 궁극 root 집합 (derivation 없거나 inputs 빈 leaf 포함)
    return bool(rts) and rts.issubset(declared)   # 빈 closure(사이클/고립)=재현불가


def _foundation_rows(name: str):
    return kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_FOUNDATION]->(fr:FoundationRequirement)
                 RETURN fr.short_name AS name, fr.kind AS kind, fr.question AS question,
                        fr.why_needed AS why_needed, fr.acceptance_criteria AS acceptance_criteria,
                        fr.evidence_refs AS evidence_refs, fr.status AS status,
                        fr.optional AS optional, fr.owner AS owner,
                        fr.risk_if_missing AS risk_if_missing, fr.satisfied AS satisfied
                 ORDER BY fr.kind, fr.short_name""", tree=name)


def _event_from_argument(tag: str, arg: dict) -> ResearchEvent | None:
    if not arg.get('id'):
        return None
    short = arg['id'].split('/')[-1]
    kind = (arg.get('kind') or 'comment').lower()
    action = 'doubt' if kind == 'doubt' else ('human_verdict' if kind in {'evaluation', 'verdict'} else kind)
    payload = (('confidence', '0.75'),) if action == 'human_verdict' else ()
    return ResearchEvent(
        name=short,
        realm=Realm.HUMAN,
        actor=arg.get('by') or 'human',
        action=action,
        target=tag,
        evidence_refs=(arg['id'],),
        payload=payload,
    )


def _research_event_rows(name: str, tag: str):
    return kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 OPTIONAL MATCH (e)-[:HAS_RESEARCH_EVENT]->(ev:ResearchEvent)
                 RETURN ev.id AS id, ev.name AS name, ev.realm AS realm, ev.actor AS actor,
                        ev.action AS action, ev.evidence_refs AS evidence_refs,
                        ev.payload AS payload, ev.created_at AS created_at
                 ORDER BY ev.created_at, ev.name""", tree=name, tag=tag)


def _event_from_row(tag: str, row: dict) -> ResearchEvent | None:
    if not row.get('name') or not row.get('realm'):
        return None
    try:
        realm = Realm(row['realm'])
    except ValueError:
        return None
    payload_raw = row.get('payload') or '{}'
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = payload_raw
    return ResearchEvent(
        name=row['name'],
        realm=realm,
        actor=row.get('actor') or '',
        action=row.get('action') or '',
        target=tag,
        evidence_refs=tuple(row.get('evidence_refs') or []),
        payload=tuple((str(k), str(v)) for k, v in payload.items()),
    )


def _event_row_dict(tag: str, row: dict) -> dict | None:
    event = _event_from_row(tag, row)
    if event is None:
        return None
    return {
        "id": row.get("id") or "",
        "name": event.name,
        "realm": event.realm.value,
        "actor": event.actor,
        "action": event.action,
        "target": event.target,
        "evidence_refs": list(event.evidence_refs),
        "payload": dict(event.payload),
        "created_at": row.get("created_at"),
    }


@app.get('/api/tree/{name}/node/{tag}/events')
def research_events(name: str, tag: str):
    """ClaimStanding 이 소비하는 append-only ResearchEvent 목록."""
    rows = _research_event_rows(name, tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    events = [event for row in rows if (event := _event_row_dict(tag, row)) is not None]
    return {"tag": tag, "count": len(events), "events": events}


@app.get('/api/tree/{name}/node/{tag}/claim-standing')
def claim_standing(name: str, tag: str, require_replay: bool = True):
    """상계/하계 evidence + foundation + lineage 를 합친 claim standing."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                 RETURN e.tag AS tag, e.verdict AS verdict, e.source_trust AS source_trust,
                        e.verdict_source AS verdict_source, e.judge_script AS judge_script,
                        e.judge_script_sha AS judge_script_sha, e.result_path AS result_path,
                        collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
              tree=name, tag=tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    x = rows[0]
    result_path = x.get('result_path') or ''
    frame = ResearchFrame(ResearchProject(name=name, goal='claim standing'))
    frame.open_possibility(Possibility(tag, f'claim standing for {name}/{tag}',
                                       evidence_refs=((result_path,) if result_path else ())))
    if x.get('source_trust') is not None:
        frame.record_event(ResearchEvent(
            name=f'{tag}:source-trust',
            realm=Realm.INTERNET,
            actor='server:node',
            action='source_trust',
            target=tag,
            evidence_refs=((result_path,) if result_path else ()),
            payload=(('trust', str(x['source_trust'])),),
        ))
    if x.get('verdict_source') == 'scripted' or x.get('judge_script') or result_path:
        action = 'test_failed' if x.get('verdict') == 'rejected' else 'test_passed'
        refs = tuple(v for v in (result_path, x.get('judge_script_sha') or '') if v)
        frame.record_event(ResearchEvent(
            name=f'{tag}:scripted-result',
            realm=Realm.BASH,
            actor=x.get('judge_script') or 'server:judge',
            action=action,
            target=tag,
            evidence_refs=refs,
            payload=(('exit_code', '0'),) if action == 'test_passed' else (('exit_code', '1'),),
        ))
    for arg in x.get('args') or []:
        event = _event_from_argument(tag, arg)
        if event is not None:
            frame.record_event(event)
    for row in _research_event_rows(name, tag):
        event = _event_from_row(tag, row)
        if event is not None:
            frame.record_event(event)

    lineage = None
    if result_path:
        ds = _load_lineage()
        if result_path in by_output(ds):
            cur_env = fingerprint_sha(environment_fingerprint())
            lineage = LineageReplayGate.evaluate(
                result_path,
                ds,
                sources={d.output for d in ds if d.kind == 'source'},
                current_env=cur_env,
            )

    standing_result = evaluate_claim_standing(
        tag,
        frame=frame,
        foundation=_foundation_from_rows(_foundation_rows(name)),
        lineage=lineage,
        policy=ClaimStandingPolicy(require_replay=require_replay),
    )
    return standing_result.to_dict()

@app.get('/api/tree/{name}/calibration')
def calibration(name: str):
    """예측 신뢰도 보정 — proper scoring(Brier/log/ECE). **트리(발급자) 수준** 트랙레코드(노드별 아님).

    표본 = novel target 을 *등록한* 예측만(novel_registered) — 그래야 credence vs 적중(novel_confirmed)
    대조가 의미. novel 없는 예측까지 넣으면 항상 (credence, 미적중)으로 들어가 정직한 발급자를
    overconfident 로 오염시킴(나생문 CREDENCE-CALIBRATION-TARGET-MISMATCH 수정)."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
                 WHERE e.pred_credence IS NOT NULL AND e.novel_confirmed IS NOT NULL
                       AND e.novel_registered = true
                 RETURN e.pred_credence AS p, e.novel_confirmed AS o""", tree=name)
    fc = [(r['p'], 1 if r['o'] else 0) for r in rows]
    return dict(n=len(fc), brier=round(brier_score(fc), 4), log_score=round(log_score(fc), 4),
                calibration_error=round(calibration_error(fc), 4),
                scope='tree_level',
                note='Brier 0=완벽, log=overconfidence 강벌, ECE=보정오차. novel 등록 예측만, 트리(발급자) 수준')

@app.get('/api/tree/{name}/directions')
def directions(name: str):
    """frontier → 다음 가지 방향 자동 생성 (규칙 기반)."""
    td = tree_data(name)
    can = next((r for r in td['nodes'] if r['verdict'] == 'CANONICAL'), None)
    m = compute_metrics(td)
    cred = (m.get('bayes') or {}).get('canonical_credence') or 0.5
    opens = [q for q in td['frontier'] if q['status'] == 'OPEN']
    # VoI/UCB 우선순위 (bandit 탐색배분). 투영이 키를 항상 포함하되 옛 질문은 None →
    # dict.get default 가 안 먹으므로 None-coalesce 필수(아니면 voi(None) crash) (WIRE-1)
    def _num(q, k, d):
        v = q.get(k)
        return d if v is None else v
    qmeta = [dict(name=q['name'], body=(q['body'] or '')[:160],
                  expected_gain=_num(q, 'expected_gain', 0.1), cost=_num(q, 'cost', 1.0),
                  credence=cred, n_visits=_num(q, 'n_visits', 1)) for q in opens]
    # UCB N = 전체 pull 수 = 질문 방문 합(P5-D). 노드 수 proxy 대신 실제 n_visits 총합 → 탐색항 정합.
    total_visits = max(sum(q['n_visits'] for q in qmeta), len(qmeta), 1)
    ranked = rank_questions(qmeta, total_visits=total_visits)
    for q in ranked:
        q['branch_from'] = (can or {}).get('tag')
        q['suggested_tag'] = q['name'].replace('q-', 'exp-') + '-try1'
    return dict(canonical=(can or {}).get('tag'), canonical_credence=cred,
                ranked_directions=ranked,
                protocol=['① prediction 사전등록(구조적 novel_metric/threshold + script_sha 권장)',
                          '② 변경 하나 실행', '③ test_result 스크립트 채점', '④ 자동 판결+질문 close'])

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

@app.get('/api/tree/{name}/stack')
def stack_view(name: str, leaf: str | None = None):
    """3층(포퍼/베이즈/라우든) 명시투표 + 정족수 메타규칙 — gap3. leaf 생략=정본 leaf."""
    _, bi, sv = _branch_stack(name, leaf)
    return dict(leaf=bi['leaf'], inputs={k: bi[k] for k in
                ('consecutive_nonprogressive', 'nodes_spent', 'prediction_hits',
                 'problem_balance_windowed')}, **_stack_dict(sv))

@app.get('/api/tree/{name}/lifecycle')
def lifecycle_view(name: str, leaf: str | None = None):
    """프로그램 종료판정 — 수확/발산/소멸/활성 (P1). extinct 는 stack 정족수만 선고."""
    _, bi, sv = _branch_stack(name, leaf)
    ls = lifecycle_state(bi['verdicts'], sv, bi['novel_registered_recent'],
                         bi['problem_balance_windowed'], bi['canonical_improved_recent'])
    return dict(leaf=bi['leaf'], state=ls.state, reason=ls.reason, regret=ls.regret,
                window=ls.window, stack=_stack_dict(sv))

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
                snapshots=len(snaps), incumbent_lifecycle=ls.state,
                note=('' if len(snaps) >= pa.window else
                      f'스냅샷 {len(snaps)} < 윈도우 {pa.window} — '
                      f'/api/leaderboard?trees={key}&snapshot=true 로 축적 필요'))

@app.get('/api/tree/{name}/node/{tag}/certificate')
def node_certificate(name: str, tag: str):
    """5게이트 AND 인증서 (P2) — 사전등록/재현/standing/보정/grounding, 증거 ref 동봉."""
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 RETURN e.verdict AS verdict, e.verdict_source AS vsrc,
                        e.pred_metric AS pm, e.judge_script AS script,
                        e.judge_script_sha AS sha, e.result_path AS rp""", tree=name, tag=tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    x = rows[0]
    checks = []
    # script 가 실재해야 prereg PASS — 빈 script 면 evidence_ref 가 bare ':' 로 고무도장 우회됨 (나생문 R2)
    prereg = x['vsrc'] == 'scripted' and x['pm'] is not None and bool(x['script'])
    checks.append(gate_check('preregistered', prereg,
                             f"{x['script']}:{(x['sha'] or '')[:12]}" if prereg else '',
                             '' if prereg else '사전등록+스크립트 채점 이력 없음(또는 script 미기록)'))
    rep = _reproducible_for_node(name, tag)
    checks.append(gate_check('reproducible', rep is True,
                             x['rp'] or '' if rep is True else '',
                             '' if rep is True else
                             ('계보 미기록 — 인증은 기록을 요구' if rep is None else 'raw root 재생성 불가')))
    st = standing(name, tag)
    checks.append(gate_check('stands', bool(st['stands']),
                             ','.join(st['grounded_extension']) if st['stands'] else '',
                             '' if st['stands'] else '미해소 의문 존재'))
    cal = calibration(name)   # 트리(발급자) 수준 보정 — 노드별 아님(G4-TREE-GLOBAL 정직 표기)
    checks.append(gate_check('calibrated', cal['n'] >= 1,
                             f"/api/tree/{name}/calibration n={cal['n']} (tree-level)" if cal['n'] >= 1 else '',
                             '' if cal['n'] >= 1 else 'novel 등록 예측의 보정 기록 0건(트리 수준)'))
    # G5 는 노드별이 아니라 *시스템 수준 불변식*: 채점 상수 전수 tier 공개. literal True 대신
    # 레지스트리에서 파생 → 미표기 상수 유입 시 게이트가 실제로 False 로 뒤집힌다 (나생문 F3).
    from lakatos.grounding import GROUNDED
    # T3-4: tier *키 존재*만 보면 오타/빈 tier 가 통과 → tier *값*이 유효 enum 인지 검증
    _VALID_TIERS = {'literature', 'policy_in_scale', 'policy'}
    grounded_ok = bool(GROUNDED) and all(g.get('tier') in _VALID_TIERS for g in GROUNDED.values())
    checks.append(gate_check('grounded', grounded_ok,
                             'lakatos/grounding.py GROUNDED tier registry' if grounded_ok else '',
                             '시스템 수준 불변식 — 채점 상수 전부 tier 공개(노드별 아님)'
                             if grounded_ok else 'GROUNDED 레지스트리에 tier 미표기 상수 존재'))
    cert = certify_claim(f'{name}/{tag}', checks, dict(
        as_of=datetime.now(timezone.utc).isoformat(),
        shas={k: v for k, v in {(x['script'] or ''): (x['sha'] or '')}.items() if k and v}))
    return dict(claim_id=cert.claim_id, certified=cert.certified, missing=list(cert.missing),
                checks=[dict(gate=c.gate, passed=c.passed, evidence_ref=c.evidence_ref,
                             note=c.note) for c in cert.checks],
                evidence_window=cert.evidence_window, limits=cert.limits,
                next_actions=cert_next_actions(cert))

# ── AGM 신념개정 (P1) — hard core revision/contraction 추론 surface (나생문 WIRE-3) ──
# 무상태 reasoning 엔드포인트: belief base 를 받아 AGM 연산 결과를 돌려준다(what-if).
# (트리 노드↔belief 영구 매핑은 더 깊은 모델 — 후속. 여기선 형식층을 *호출 가능*하게 만든다.)

class BeliefIn(BaseModel):
    belief_id: str
    statement: str = ''
    kind: str = 'protective_belt'      # hard_core | protective_belt
    credence: float = Field(0.5, ge=0, le=1)
    problem_balance: int = 0
    connectivity: int = 0
    depends_on: list[str] = Field(default_factory=list)


class AgmReviseIn(BaseModel):
    op: str = 'revision'               # expansion | contraction | revision | demote_canonical
    base: list[BeliefIn] = Field(default_factory=list)
    new: BeliefIn | None = None        # expansion | revision | demote_canonical
    target_id: str | None = None       # contraction
    contradicts: list[str] = Field(default_factory=list)   # revision
    old_canonical_id: str | None = None                    # demote_canonical
    allow_hard_core: bool = False


def _belief(b: BeliefIn) -> Belief:
    return Belief(belief_id=b.belief_id, statement=b.statement, kind=b.kind,
                  credence=b.credence, problem_balance=b.problem_balance,
                  connectivity=b.connectivity, depends_on=tuple(b.depends_on))


@app.post('/api/agm/revise')
def agm_revise(req: AgmReviseIn):
    """AGM 신념개정(P1) — expansion/contraction/revision/demote_canonical.
    hard core 는 PROTECTED: allow_hard_core 없이 깎으면 409, 깎이면 programme_shift_candidate=True."""
    base = [_belief(b) for b in req.base]
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
            r = demote_canonical(base, req.old_canonical_id, _belief(req.new))
        else:
            raise HTTPException(422, f'미지원 op: {req.op} (expansion|contraction|revision|demote_canonical)')
    except HardCoreProtected as e:
        raise HTTPException(409, str(e))
    return dict(
        op=req.op,
        base=[dict(belief_id=b.belief_id, statement=b.statement, kind=b.kind,
                   credence=b.credence, problem_balance=b.problem_balance,
                   connectivity=b.connectivity, depends_on=list(b.depends_on)) for b in r.base],
        removed=list(r.removed), added=list(r.added),
        programme_shift_candidate=r.programme_shift_candidate,
        entrenchment_policy=r.entrenchment_policy)


# ── 하네스 사이클 (P5-C) — 서버 in-process 오케스트레이션, bash 미실행(no RCE) ──

class CycleIn(BaseModel):
    """한 사이클 입력. 서버는 bash(build/judge)를 실행하지 않는다(RCE 회피) — client/CLI 가
    build/judge 를 돌려 *사전계산 metric*(measured)을 준다. 서버는 graph 오케스트레이션만."""
    tag: str = Field(min_length=1)
    parent: str = ''
    metric_name: str
    baseline: float
    direction: str = 'lower'
    noise_band: float = Field(0.0, ge=0)
    measured: float
    script: str = 'inline'
    script_sha: str | None = None
    novel_metric: str | None = None
    novel_direction: str | None = None
    novel_threshold: float | None = None
    novel_measured: float | None = None
    credence: float | None = Field(None, ge=0, le=1)
    source_trust: float = 1.0
    algorithm: str = ''
    comment: str = ''
    closes_question: str = ''
    critiques: list[CritiqueIn] = Field(default_factory=list)
    # PnR/Lakatos 질적 증거(F2) — 전엔 /cycle 이 dialectical heart 를 우회했음(반례 대응이 판결에 미반영)
    counterexample_response: str | None = None
    counterexample_type: str | None = None
    ce_excess_content: bool = False
    ce_novel_corroborated: bool = False
    ce_in_heuristic_spirit: bool | None = None
    lakatos_anomaly: bool | None = None
    lakatos_consequence: bool | None = None
    lakatos_excess: bool | None = None
    lakatos_hardcore: bool | None = None


@app.post('/api/tree/{name}/cycle')
def run_cycle(name: str, c: CycleIn):
    """한 연구 사이클을 한 콜로 — node→prediction→test_result(judge)→critique→standing.
    기존 핸들러 재사용(로직 단일출처). **bash 미실행**: build/judge 는 client(CLI `cycle`) 책임."""
    add_node(name, NodeIn(tag=c.tag, parent=(c.parent or None),
                          algorithm=c.algorithm, comment=c.comment))
    register_prediction(name, c.tag, PredictionIn(
        metric_name=c.metric_name, direction=c.direction, baseline_value=c.baseline,
        noise_band=c.noise_band, novel_metric=c.novel_metric, novel_direction=c.novel_direction,
        novel_threshold=c.novel_threshold, judge_script_sha=c.script_sha,
        closes_question=c.closes_question, credence=c.credence))
    res = submit_test_result(name, c.tag, TestResultIn(
        metric_value=c.measured, script=c.script, script_sha=c.script_sha,
        novel_measured=c.novel_measured, source_trust=c.source_trust,
        counterexample_response=c.counterexample_response, counterexample_type=c.counterexample_type,
        ce_excess_content=c.ce_excess_content, ce_novel_corroborated=c.ce_novel_corroborated,
        ce_in_heuristic_spirit=c.ce_in_heuristic_spirit,
        lakatos_anomaly=c.lakatos_anomaly, lakatos_consequence=c.lakatos_consequence,
        lakatos_excess=c.lakatos_excess, lakatos_hardcore=c.lakatos_hardcore))
    for cr in c.critiques:
        add_critique(name, c.tag, cr)
    return dict(tree=name, tag=c.tag, verdict=res.get('verdict'), novel=res.get('novel'),
                delta=res.get('delta'), critiques=len(c.critiques),
                standing=standing(name, c.tag),
                note='in-process 오케스트레이션 — bash(build/judge)는 client/CLI 책임(서버 no-RCE)')


class ArtifactIn(BaseModel):
    node_tag: str
    kind: str
    data: dict

@app.post('/api/tree/{name}/artifact')
def add_artifact(name: str, a: ArtifactIn):
    MONGO.artifacts.insert_one(dict(tree=name, node_tag=a.node_tag, kind=a.kind,
                                    data=a.data, ts=datetime.now(timezone.utc)))
    hist(name, 'artifact', a.node_tag, {'kind': a.kind})
    return {'ok': True}


class ElementIn(BaseModel):
    name: str
    definition: str = ''
    implication: str = ''
    lifecycle: str = ''
    scope: str = 'domain-agnostic'


class ElementUseIn(BaseModel):
    note: str = ''
    evidence_ref: str = ''


class FoundationRequirementIn(BaseModel):
    name: str
    kind: str
    question: str = ''
    why_needed: str = ''
    acceptance_criteria: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = 'needed'
    optional: bool = False
    owner: str = ''
    risk_if_missing: str = ''

    def to_engine(self) -> FoundationRequirement:
        try:
            kind = KnowledgeKind(self.kind)
        except ValueError as exc:
            raise HTTPException(422, f'unknown foundation kind: {self.kind}') from exc
        return FoundationRequirement(
            name=self.name,
            kind=kind,
            question=self.question,
            why_needed=self.why_needed,
            acceptance_criteria=tuple(self.acceptance_criteria),
            evidence_refs=tuple(self.evidence_refs),
            status=self.status,
            optional=self.optional,
            owner=self.owner,
            risk_if_missing=self.risk_if_missing,
        )


@app.post('/api/tree/{name}/element')
def add_element(name: str, el: ElementIn):
    kg("""MATCH (t:LakatosTree {name:$tree})
          MERGE (el:LakatosElement {name:$elname})
          SET el.definition=$definition, el.implication=$implication,
              el.lifecycle=$lifecycle, el.scope=$scope, el.updated_at=$ts
          MERGE (t)-[:HAS_ELEMENT]->(el)
          RETURN el.name AS name""",
       tree=name, elname=el.name, definition=el.definition, implication=el.implication,
       lifecycle=el.lifecycle, scope=el.scope, ts=datetime.now(timezone.utc).isoformat())
    hist(name, 'element_upsert', el.name, el.model_dump())
    return {'ok': True, 'name': el.name}


@app.post('/api/tree/{name}/node/{tag}/element/{element_name}')
def attach_element(name: str, tag: str, element_name: str, use: ElementUseIn):
    r = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
              MATCH (t)-[:HAS_ELEMENT]->(el:LakatosElement {name:$elname})
              MERGE (e)-[u:USES_ELEMENT]->(el)
              SET u.note=$note, u.evidence_ref=$evidence_ref, u.at=$ts
              RETURN e.tag AS tag, el.name AS element""",
           tree=name, tag=tag, elname=element_name, note=use.note,
           evidence_ref=use.evidence_ref, ts=datetime.now(timezone.utc).isoformat())
    if not r:
        raise HTTPException(404, f'노드 또는 엘리멘트 없음: {tag}, {element_name}')
    hist(name, 'element_use', tag, {'element': element_name, **use.model_dump()})
    return {'ok': True, 'tag': tag, 'element': element_name}


@app.post('/api/tree/{name}/foundation')
def add_foundation_requirement(name: str, req: FoundationRequirementIn):
    engine_req = req.to_engine()
    kg("""MATCH (t:LakatosTree {name:$tree})
          MERGE (fr:FoundationRequirement {name:$tree+'/'+$name})
          SET fr.short_name=$name, fr.kind=$kind, fr.question=$question,
              fr.why_needed=$why_needed, fr.acceptance_criteria=$acceptance_criteria,
              fr.evidence_refs=$evidence_refs, fr.status=$status, fr.optional=$optional,
              fr.owner=$owner, fr.risk_if_missing=$risk_if_missing,
              fr.satisfied=$satisfied, fr.updated_at=$ts
          MERGE (t)-[:HAS_FOUNDATION]->(fr)
          RETURN fr.name AS name""",
       tree=name, ts=datetime.now(timezone.utc).isoformat(), **engine_req.db_record())
    hist(name, 'foundation_upsert', req.name, engine_req.db_record())
    return {'ok': True, 'name': req.name, 'satisfied': engine_req.satisfied}


@app.get('/api/tree/{name}/foundation')
def get_foundation_requirements(name: str):
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_FOUNDATION]->(fr:FoundationRequirement)
                 RETURN fr.short_name AS name, fr.kind AS kind, fr.question AS question,
                        fr.why_needed AS why_needed, fr.acceptance_criteria AS acceptance_criteria,
                        fr.evidence_refs AS evidence_refs, fr.status AS status,
                        fr.optional AS optional, fr.owner AS owner,
                        fr.risk_if_missing AS risk_if_missing, fr.satisfied AS satisfied
                 ORDER BY fr.kind, fr.short_name""", tree=name)
    gaps = [r['name'] for r in rows if not r.get('satisfied')]
    return {'requirements': rows, 'summary': {'required': len(rows),
            'satisfied': len(rows) - len(gaps), 'gaps': gaps}}

@app.get('/api/tree/{name}/history')
def history(name: str, limit: int = 100):
    limit = max(1, min(limit, 1000))   # ROB-6: 무제한 limit 차단 (OOM/DoS)
    with pg() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT ts, op, node_tag, payload FROM history WHERE tree=%s '
                    'ORDER BY id DESC LIMIT %s', (name, limit))
        return [dict(r, ts=r['ts'].isoformat()) for r in cur.fetchall()]

class DerivationIn(BaseModel):
    """데이터 산출물 계보 기록 — 입력 sha + 생산코드 sha → 출력 sha."""
    output: str
    output_sha: str
    producer: str = ''
    producer_sha: str = ''
    inputs: list = []            # [[path, sha], ...]
    params: dict = {}
    kind: str = 'intermediate'   # source|intermediate|final
    env: str = ''                # 환경 지문 sha (envfp.fingerprint_sha)

@app.post('/api/lineage/derivation')
def record_derivation(d: DerivationIn):
    # 나생문 CON-2: 계보 DAG 불변식 — 비-source 산출물은 반드시 입력에서 파생.
    #  inputs 빈 비-source = dangling leaf(재현불가)를 기록단계서 차단(write-path 게이트).
    if d.kind != 'source' and not d.inputs:
        raise HTTPException(400, f"비-source 산출물(kind={d.kind})은 inputs 필수 — "
                                 f"inputs 빈 산출물은 source 로만 기록 가능(재현성 불변식).")
    # PROV-O: output Entity wasDerivedFrom input Entities, wasGeneratedBy producer Activity
    kg("""MERGE (o:DataArtifact {path:$out}) SET o.sha=$osha, o.kind=$kind, o.producer=$prod,
              o.producer_sha=$psha, o.params=$params, o.env=$env, o.recorded_at=$ts""",
       out=d.output, osha=d.output_sha, kind=d.kind, prod=d.producer, psha=d.producer_sha,
       params=json.dumps(d.params, ensure_ascii=False), env=d.env, ts=datetime.now(timezone.utc).isoformat())
    for path, sha in d.inputs:
        kg("""MERGE (i:DataArtifact {path:$ip}) ON CREATE SET i.sha=$ish
              WITH i MATCH (o:DataArtifact {path:$out})
              MERGE (o)-[:DERIVED_FROM {input_sha:$ish}]->(i)""",
           ip=path, ish=sha, out=d.output)
    with pg() as c, c.cursor() as cur:
        cur.execute('INSERT INTO lineage(output, output_sha, producer, producer_sha, inputs, params, kind, env) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (d.output, d.output_sha, d.producer, d.producer_sha,
                     json.dumps(d.inputs), json.dumps(d.params, ensure_ascii=False), d.kind, d.env))
    return {'ok': True}

def _load_lineage():
    rows = kg("""MATCH (o:DataArtifact) OPTIONAL MATCH (o)-[r:DERIVED_FROM]->(i:DataArtifact)
                 RETURN o.path AS out, o.sha AS osha, o.producer AS prod, o.producer_sha AS psha,
                        o.kind AS kind, o.env AS env, collect({path:i.path, sha:r.input_sha}) AS inputs""")
    ds = []
    for x in rows:
        inp = [(a['path'], a['sha']) for a in x['inputs'] if a['path']]
        ds.append(Derivation(output=x['out'], output_sha=x['osha'] or '', producer=x['prod'] or '',
                             producer_sha=x['psha'] or '', inputs=inp, kind=x['kind'] or 'intermediate',
                             env=x.get('env') or ''))
    return ds

@app.get('/api/openlineage/{artifact:path}')
def artifact_openlineage(artifact: str):
    """완성본의 OpenLineage RunEvent 들 (생태계 표준 — 어댑터 노출, F-ARCH-5)."""
    ds = _load_lineage(); bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    src = {d.output for d in ds if d.kind == 'source'}
    res = LineageReplayGate.evaluate(artifact, ds, sources=src)
    return {'artifact': artifact, 'events': lineage_result_to_openlineage_events(res)}

@app.post('/api/openlineage/{artifact:path}/marquez')
def send_artifact_to_marquez(artifact: str):
    """완성본 OpenLineage event 를 Marquez 로 전송 (전송층, F-ARCH-5 완결).

    직렬화는 /api/openlineage 가, 전송만 여기서 — MARQUEZ_URL env-gated(미설정 503).
    토큰 필요 시 MARQUEZ_TOKEN env. 자격증명 없으면 조용히 비활성(골방 아님, 흘려보낼 길은 열림).
    """
    from lakatos import marquez_sink
    from lakatos.adapters import MarquezClientError
    if not marquez_sink.enabled():
        raise HTTPException(503, 'MARQUEZ_URL 미설정 — 전송 비활성. 직렬화는 GET /api/openlineage/{artifact} '
                                 '로 가능. 환경변수 MARQUEZ_URL(+선택 MARQUEZ_TOKEN) 설정 후 재시도.')
    ds = _load_lineage(); bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    src = {d.output for d in ds if d.kind == 'source'}
    res = LineageReplayGate.evaluate(artifact, ds, sources=src)
    events = lineage_result_to_openlineage_events(res)
    try:   # 나생문 BLOCKER: Marquez 도달 불가/HTTP 에러 → 500 누수 금지, 502 로 명시
        sent = marquez_sink.ship(events)
    except MarquezClientError as exc:
        raise HTTPException(502, f'Marquez 전송 실패(upstream): {exc}')
    return {'artifact': artifact, 'sent_events': len(events), 'marquez': sent}

@app.get('/api/dvc/{artifact:path}')
def artifact_dvc(artifact: str):
    """완성본 계보를 DVC dvc.yaml/dvc.lock 형태로 (raw-rooted replay, F-ARCH-5)."""
    ds = _load_lineage(); bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    plan = _safe_rebuild_plan(artifact, bo)
    return {'artifact': artifact, 'dvc_yaml': derivations_to_dvc_pipeline(plan),
            'dvc_lock': derivations_to_dvc_lock(plan)}

@app.get('/api/prov/{artifact:path}')
def artifact_prov(artifact: str, format: str | None = None):
    """완성본 계보의 W3C PROV 문서 (Entity/Activity/Agent, F-ARCH-5).
    ?format=prov-json 으로 표준 W3C PROV-JSON 직렬화(ENG-DU-3: 전엔 내부 dict 를 'W3C PROV'라 반환)."""
    ds = _load_lineage(); bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    plan = _safe_rebuild_plan(artifact, bo)
    doc = derivations_to_prov_document(plan)
    if format == 'prov-json':
        return prov_document_to_prov_json(doc)   # 표준 PROV-JSON(prefix/entity/activity/agent/관계)
    return {'artifact': artifact, 'prov': doc}

@app.get('/api/rebuild-verify/{artifact:path}')
def rebuild_verify(artifact: str):
    """G-RebuildFromRaw — 완성본이 raw root + 현재 환경에서 재생성 가능한가."""
    ds = _load_lineage()
    bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    src = {d.output for d in ds if d.kind == 'source'}
    gaps = reproducibility_gaps(artifact, bo, src)
    # 현재 디스크 sha 로 stale + 현재 환경으로 env drift (OPS-COR-2/3: 스트리밍·dir·graceful 공통 헬퍼)
    cur = {}
    for d in ds:
        for path, _ in d.inputs:
            if path not in cur:
                s = _path_sha(path)
                if s is not None:
                    cur[path] = s
    cur_env = fingerprint_sha(environment_fingerprint())
    plan = _safe_rebuild_plan(artifact, bo)
    stale = {d.output: True for d in plan if stale_inputs(d, cur)}
    env_changed = {d.output: {'recorded': d.env[:12], 'current': cur_env[:12]}
                   for d in plan if env_drift(d, cur_env)}
    mani = build_manifest(artifact, bo, env_sha=cur_env)
    ok = (not gaps) and (not stale) and (not env_changed)
    verdict = 'rebuildable' if ok else 'progressive_conditional'
    return dict(artifact=artifact, verdict=verdict,
                reproducible=(not gaps), gaps=sorted(gaps),
                stale=list(stale), env_changed=env_changed,
                manifest=dict(final=mani.final,
                              roots=[{'path': r.path, 'sha': r.sha[:12], 'schema': r.schema} for r in mani.roots],
                              env_sha=mani.env_sha[:12],
                              recipe=[{k: v for k, v in step.items() if k != 'params'} for step in mani.recipe]),
                note='rebuildable=raw root+현재환경서 재생성 가능. progressive_conditional=env/데이터 바뀜 → 재실행 필요(consumer_b ZDF Rule #5)')

@app.get('/api/lineage-script/{producer:path}')
def get_script_history(producer: str):
    """생산 스크립트 버전 이력 — 중간에 수정되면 sha 바뀜, 각 버전이 만든 산출물(시간순)."""
    with pg() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT output, producer_sha, ts FROM lineage WHERE producer=%s ORDER BY ts',
                    (producer,))
        rows = cur.fetchall()
    ds = [Derivation(output=r['output'], output_sha='', producer=producer,
                     producer_sha=r['producer_sha'] or '', inputs=[], ts=r['ts'].isoformat())
          for r in rows]
    return dict(producer=producer, versions=script_history(ds, producer),
                note='sha 바뀐 지점 = 스크립트 수정. 어느 버전이 어느 데이터 만들었나 추적')

@app.get('/api/lineage/{artifact:path}')
def get_lineage(artifact: str, stale: bool = False):
    """완성본의 계보 — source(ZDF) 추적 + 재빌드 플랜 + 재현 가능성 + 끊긴 링크."""
    ds = _load_lineage()
    bo = by_output(ds)
    if artifact not in bo:
        raise HTTPException(404, f'산출물 미기록: {artifact}')
    src = {d.output for d in ds if d.kind == 'source'} | \
          {r for r in lin_roots(artifact, bo) if bo.get(r) is None or not bo[r].inputs}
    gaps = reproducibility_gaps(artifact, bo, src)
    plan = _safe_rebuild_plan(artifact, bo)
    out = dict(artifact=artifact, roots=sorted(lin_roots(artifact, bo)),
               reproducible=(not gaps), gaps=sorted(gaps),
               rebuild_plan=[dict(output=d.output, producer=d.producer,
                                  inputs=[p for p, _ in d.inputs]) for d in plan],
               note='reproducible=True → source(ZDF)서 plan 순서대로 재실행하면 완성본 재생성')
    if stale:   # 입력 데이터 변경 감지(현 디스크 sha vs 기록) — 느려서 opt-in. 공통 _path_sha(DRY)
        cur = {}
        for d in ds:
            for path, _ in d.inputs:
                if path in cur:
                    continue
                s = _path_sha(path)
                if s is not None:
                    cur[path] = s
        changed = {}
        for d in plan:
            bad = stale_inputs(d, cur)
            if bad:
                changed[d.output] = [{'input': p, 'recorded': r[:12], 'current': c[:12]} for p, r, c in bad]
        out['stale'] = bool(changed)
        out['changed'] = changed
    return out

VC = {'CANONICAL': '#1a7f37', 'canonical_stage': '#2da44e', 'former_canonical': '#6e7781',
      'rejected': '#cf222e', 'partial': '#bf8700', 'equivalent': '#0969da',
      'proof': '#8250df', 'repurposed_measurement': '#bc4c00'}

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
    out = ['<html><head><meta charset="utf-8"><title>라카토스 서버</title><style>'
           'body{font-family:monospace;margin:24px;background:#fafafa}'
           'h2{border-bottom:2px solid #333}.n{margin:2px 0;padding:2px 6px;border-radius:4px}'
           'table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px;font-size:13px}'
           '.lay{background:#fff;border:1px solid #ddd;border-radius:5px;padding:6px 10px;margin:6px 0;font-size:13px}'
           'a.api{color:#0969da;text-decoration:none;font-size:11px;margin-left:6px}'
           '</style></head><body><h1>라카토스 서버 — 연구 프로그램 트리</h1>']
    all_trees = trees()
    # ── 경쟁 프로그램 리더보드 (트리 ≥2, Pareto+Borda) ──
    names = [t['name'] for t in all_trees]
    if len(names) >= 2:
        try:
            lb = build_leaderboard([_competitor_for_tree(n) for n in names])
            front = set(lb.get('pareto_front') or [])
            out.append('<h2>🏆 리더보드 (Pareto+Borda 다기준)</h2><ol>')
            for row in lb.get('rows', []):
                nm = row.get('name', '?')
                out.append(f"<li><b>{html.escape(str(nm))}</b>"
                           f"{' <span style=color:#1a7f37>◆Pareto</span>' if nm in front else ''}</li>")
            out.append(f"</ol><p><small>shift_candidate 는 인간 안건 — "
                       f"<a class=api href='/api/paradigm?incumbent={html.escape(names[0])}"
                       f"&rivals={html.escape(','.join(names[1:]))}'>/api/paradigm</a> (스냅샷 축적 필요)</small></p>")
        except Exception as e:                              # 리더보드 실패가 대시보드를 깨선 안 됨
            out.append(f"<p><small>리더보드 산출 불가: {html.escape(type(e).__name__)}</small></p>")
    for t in all_trees:
        td = tree_data(t['name'])
        m = compute_metrics(td)
        nm = html.escape(t['name'])
        out.append(f"<h2>{nm}</h2><p>{html.escape(td['title'] or '')}</p>")
        out.append(f"<p><b>정본 경로</b>: {' → '.join(m['canonical_path'])}</p>")
        prog = m['progress']
        out.append('<table><tr><th>진보율</th><th>기각률</th><th>퇴행깊이</th><th>frontier</th><th>주석</th></tr>')
        out.append(f"<tr><td>{(str(prog['improvement_pct'])+'%') if prog else '—'}</td>"
                   f"<td>{m['rejection_ratio']}</td><td>{m['max_degeneration_depth']}</td>"
                   f"<td>OPEN {m['frontier']['open']} / CLOSED {m['frontier']['closed']}</td>"
                   f"<td>{m['annotation_coverage']}</td></tr></table>")
        # ── 층 패널: 엄격도 스택 / lifecycle / 베이즈 / 발전성 / 커버리지 (전엔 전부 비가시) ──
        fert, bayes, cov = m['fertility'], m['bayes'], m['coverage']
        out.append(f"<div class='lay'>📊 <b>베이즈 신뢰도</b> {bayes['canonical_credence']} · "
                   f"<b>발전성</b> 적중 {fert.get('hits','?')}/{fert.get('registered','?')} "
                   f"(nobel_grade={fert.get('nobel_grade')}) · "
                   f"<b>커버리지</b> backlog {cov['backlog_count']}건"
                   f"{' (전수)' if cov['exhaustive'] else ''}</div>")
        sl = _tree_stack_lifecycle(td)
        if sl:
            leaf, sv, ls = sl
            sc = {'abandon': '#cf222e', 'retain': '#1a7f37', 'undecided': '#bf8700'}.get(sv.decision, '#333')
            lc = {'extinct': '#cf222e', 'diverging': '#bf8700', 'harvesting': '#0969da',
                  'active': '#1a7f37'}.get(ls.state, '#333')
            votes = ' '.join(f"{v.layer}={v.vote}" for v in sv.votes)
            out.append(f"<div class='lay'>⚖️ <b>3층 스택</b>(leaf {html.escape(leaf)}): "
                       f"<span style='color:{sc}'>{sv.decision}</span> "
                       f"<small>[{votes}{', conflict' if sv.conflict else ''}]</small> · "
                       f"🔄 <b>lifecycle</b> <span style='color:{lc}'>{ls.state}</span> "
                       f"<small>{html.escape(ls.reason[:80])}</small>"
                       f"<a class=api href='/api/tree/{nm}/stack'>stack</a>"
                       f"<a class=api href='/api/tree/{nm}/lifecycle'>lifecycle</a></div>")
        if m['multiplicity']:                               # gap8 다중비교 — family 별 상세(alert 만 아니라)
            out.append("<div class='lay'>🔬 <b>다중비교(gap8)</b>: " + ' · '.join(
                f"{html.escape(k)}: improved {v['family_size']} → BH생존 {len(v['survivors_bh'])}/"
                f"Bonf {len(v['survivors_bonferroni'])}" for k, v in m['multiplicity'].items()) + "</div>")
        for a in m['alerts']:
            out.append(f"<p style='color:#cf222e'>⚠ {a}</p>")
        kids = {}
        for r in td['nodes']:
            # OPS-HON-5: 대시보드는 DAG 를 단일-부모(첫 엣지) 투영으로 렌더(다중부모 노드는 첫 부모 아래만).
            # 전체 N:N DAG(parents/parent_edges)는 /api/tree 참조 — 시각적 트리는 가독성 위해 단일부모 투영.
            kids.setdefault(r.get('parent'), []).append(r)

        def render(tag, depth, seen):
            if tag in seen:                                 # ROB-3: BRANCHED_FROM 사이클 가드(무한재귀 차단)
                out.append(f"<div class='n' style='margin-left:{depth*26}px'>"
                           f"<small>↺ {html.escape(tag)} (cycle)</small></div>")
                return
            seen = seen | {tag}
            r = next(x for x in td['nodes'] if x['tag'] == tag)
            col = VC.get(r['verdict'], '#333')
            mv = f" <small>[{r['metric_name']}={r['metric_value']}]</small>" if r.get('metric_value') else ''
            et = html.escape(tag)
            links = (f"<a class=api href='/api/tree/{nm}/node/{et}/certificate'>cert</a>"
                     f"<a class=api href='/api/tree/{nm}/node/{et}/claim-standing'>standing</a>"
                     f"<a class=api href='/api/tree/{nm}/node/{et}/provenance'>prov</a>")
            out.append(f"<div class='n' style='margin-left:{depth*26}px'>"
                       f"<span style='color:{col}'>●</span> <b>{et}</b> "
                       f"<span style='color:{col}'>{html.escape(r['verdict'])}</span>{mv}{links}"
                       f"<br><small style='margin-left:14px;color:#555'>{html.escape((r.get('comment') or '')[:120])}</small></div>")
            for c in sorted(kids.get(tag, []), key=lambda x: x['tag']):
                render(c['tag'], depth+1, seen)
        for root in sorted(kids.get(None, []), key=lambda x: x['tag']):
            render(root['tag'], 0, set())
        out.append('<h3>Frontier (열린 질문)</h3><ul>')
        for q in td['frontier']:
            mark = '🟢' if q['status'] == 'OPEN' else '✅'
            out.append(f"<li>{mark} <b>{html.escape(q['name'])}</b> — {html.escape((q['body'] or '')[:150])}</li>")
        out.append('</ul>')
        out.append(f"<p><a class=api href='/api/tree/{nm}/directions'>다음 방향(VoI)</a> "
                   f"<a class=api href='/api/tree/{nm}/calibration'>보정</a> "
                   f"<a class=api href='/api/tree/{nm}/metrics'>전체 지표</a></p>")
    out.append('</body></html>')
    return ''.join(out)
