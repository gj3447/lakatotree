#!/usr/bin/env python3
"""라카토스 서버 — 연구 프로그램 트리의 KG+DB 백엔드 (알기 쉬운 단일 파일).

3층:
  Neo4j (KG)      = 나무/노드/질문 그래프 정본 (LakatosTree / PrismExperiment·LakatosNode / OpenQuestion)
  PostgreSQL      = append-only 이력 (lakatos.history, metric_snapshots) — 누가 언제 무엇을
  MongoDB         = 산출물 보관 (결과 json/지표 원본; db=lakatos, col=artifacts)

env: NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD, LAKATOS_PG_DSN, LAKATOS_MONGO_URI (run.sh 가 .env 에서 주입)
실행: bash run.sh   → http://localhost:55170  (대시보드 = / , API = /api/*)
"""
import html, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lakatos.judge import Prediction, judge, PredictionMissing, PredictionLocked, check_registration
from lakatos.metrics import tree_metrics
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from neo4j import GraphDatabase
import psycopg2, psycopg2.extras
from pymongo import MongoClient

NEO = GraphDatabase.driver(os.environ['NEO4J_URI'],
                           auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']))
PG_KW = dict(host=os.environ.get('LAKATOS_PG_HOST', 'localhost'),
             port=int(os.environ.get('LAKATOS_PG_PORT', '55100')),
             user=os.environ.get('LAKATOS_PG_USER', 'admin'),
             password=os.environ.get('LAKATOS_PG_PASSWORD', ''),
             dbname=os.environ.get('LAKATOS_PG_DB', 'lakatos'))
MONGO = MongoClient(os.environ.get('LAKATOS_MONGO_URI', 'mongodb://localhost:27017'))['lakatos']
app = FastAPI(title='Lakatos Server', version='1.0')

def pg():
    return psycopg2.connect(**PG_KW)

def hist(tree, op, node_tag=None, payload=None):
    with pg() as c, c.cursor() as cur:
        cur.execute('INSERT INTO history(tree, op, node_tag, payload) VALUES (%s,%s,%s,%s)',
                    (tree, op, node_tag, json.dumps(payload or {}, ensure_ascii=False)))

def kg(q, **kw):
    with NEO.session() as s:
        return s.run(q, **kw).data()

NODE_LABELS = 'PrismExperiment|LakatosNode'

def tree_data(name):
    t = kg('MATCH (t:LakatosTree {name:$n}) RETURN t.title AS title, t.hard_core AS hard_core, '
           't.frontier_rule AS frontier_rule, t.doc AS doc', n=name)
    if not t:
        raise HTTPException(404, f'나무 없음: {name}')
    nodes = kg(f'''MATCH (t:LakatosTree {{name:$n}})-[:HAS_NODE]->(e)
        OPTIONAL MATCH (e)-[:BRANCHED_FROM]->(p)
        OPTIONAL MATCH (e)-[:RAISES_QUESTION]->(q)
        RETURN e.tag AS tag, e.verdict AS verdict, e.note AS note, e.script AS script,
               e.result_path AS result_path, e.algorithm AS algorithm, e.comment AS comment,
               e.limitation AS limitation, e.open_question AS open_question,
               e.metric_name AS metric_name, e.metric_value AS metric_value,
               e.metric_scope AS metric_scope, p.tag AS parent, collect(q.name) AS questions
        ORDER BY tag''', n=name)
    qs = kg('MATCH (t:LakatosTree {name:$n})-[:HAS_FRONTIER]->(q) '
            'RETURN q.name AS name, q.status AS status, q.body AS body', n=name)
    return dict(name=name, **t[0], nodes=nodes, frontier=qs)

def compute_metrics(td):
    return tree_metrics(td['nodes'], td['frontier'])

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

class NodeIn(BaseModel):
    tag: str
    parent: str | None = None
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

@app.post('/api/tree/{name}/node')
def add_node(name: str, n: NodeIn):
    td = tree_data(name)   # 존재 검증
    if n.parent and n.parent not in {r['tag'] for r in td['nodes']}:
        raise HTTPException(400, f'부모 노드 없음: {n.parent}')
    kg('''MATCH (t:LakatosTree {name:$tree})
          MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+$tag})
          SET e.tag=$tag, e.verdict=$verdict, e.script=$script, e.result_path=$result_path,
              e.algorithm=$algorithm, e.comment=$comment, e.limitation=$limitation,
              e.open_question=$open_question, e.metric_name=$metric_name,
              e.metric_value=$metric_value, e.metric_scope=$metric_scope,
              e.recorded_at=$ts
          MERGE (t)-[:HAS_NODE]->(e)''',
       tree=name, ts=datetime.now(timezone.utc).isoformat(), **n.model_dump())
    if n.parent:
        kg(f'''MATCH (t:LakatosTree {{name:$tree}})-[:HAS_NODE]->(e {{tag:$tag}})
               MATCH (t)-[:HAS_NODE]->(p {{tag:$parent}})
               MERGE (e)-[:BRANCHED_FROM]->(p)''', tree=name, tag=n.tag, parent=n.parent)
    hist(name, 'node_create', n.tag, n.model_dump())
    return {'ok': True, 'tag': n.tag}

class VerdictIn(BaseModel):
    verdict: str
    note: str = ''

# 행정 상태만 수동 지정 가능 — 판결 어휘(progressive/partial/...)는 test_result 스크립트 전용
ADMIN_VERDICTS = {'CANONICAL', 'former_canonical', 'canonical_stage', 'repurposed_measurement', 'proof'}

@app.post('/api/tree/{name}/node/{tag}/verdict')
def set_verdict(name: str, tag: str, v: VerdictIn):
    if v.verdict not in ADMIN_VERDICTS:   # 나생문 F-FG-1: 판결 어휘 수동 덮어쓰기 금지
        raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                 f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
    if v.verdict == 'CANONICAL':   # demote+promote 단일 트랜잭션 (F-FG-5)
        kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
              WITH t, cur
              OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
              WHERE old.tag <> $tag
              SET old.verdict='former_canonical'
              SET cur.verdict='CANONICAL', cur.verdict_source='admin' ''', tree=name, tag=tag)
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
    qname: str
    body: str = ''

@app.post('/api/tree/{name}/question')
def open_question(name: str, q: QuestionIn):
    kg('''MATCH (t:LakatosTree {name:$tree})
          MERGE (qn:OpenQuestion {name:$qn})
          SET qn.body=$body, qn.status='OPEN', qn.created_at=$ts
          MERGE (t)-[:HAS_FRONTIER]->(qn)''',
       tree=name, qn=q.qname, body=q.body, ts=datetime.now(timezone.utc).isoformat())
    hist(name, 'question_open', None, q.model_dump())
    return {'ok': True}

@app.post('/api/tree/{name}/question/{qname}/close')
def close_question(name: str, qname: str, closed_by: str = ''):
    r = kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn})
              SET q.status='CLOSED', q.closed_by=$by RETURN q.name AS name''',
           tree=name, qn=qname, by=closed_by)
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
    novel_prediction: str = ''        # 무엇이 "새로" 맞아야 하는가 (없으면 땜빵=퇴행 후보)
    closes_question: str = ''         # 닫으려는 OpenQuestion

@app.post('/api/tree/{name}/node/{tag}/prediction')
def register_prediction(name: str, tag: str, p: PredictionIn):
    r = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
              WHERE e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
              SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                  e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                  e.pred_novel=$novel_prediction, e.pred_closes=$closes_question,
                  e.pred_registered_at=$ts
              RETURN e.tag AS tag""",
           tree=name, tag=tag, ts=datetime.now(timezone.utc).isoformat(), **p.model_dump())
    if not r:
        raise HTTPException(409, '노드 없음 또는 이미 채점됨 — 사후 예측등록 금지')
    hist(name, 'prediction_register', tag, p.model_dump())
    return {'ok': True, 'note': '예측 사전등록 완료 — 이제 실험을 실행하고 test_result 를 스크립트로 제출'}

class TestResultIn(BaseModel):
    """채점 스크립트 산출 — LLM 점수 금지, 판결은 규칙으로 자동."""
    metric_value: float
    script: str                      # 채점 스크립트 경로 (재현 가능해야 함)
    result_path: str = ''            # 원본 결과 파일
    log: str = ''

@app.post('/api/tree/{name}/node/{tag}/test_result')
def submit_test_result(name: str, tag: str, r: TestResultIn):
    rows = kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                 RETURN e.pred_metric AS m, e.pred_direction AS d, e.pred_baseline AS b,
                        e.pred_noise_band AS nb, e.pred_novel AS novel,
                        e.verdict_source AS vsrc""", tree=name, tag=tag)
    if not rows:
        raise HTTPException(404, f'노드 없음: {tag}')
    pr = rows[0]
    if pr['vsrc'] == 'scripted':   # 나생문 F-FG-1: re-roll 금지 (원하는 값 나올 때까지 재제출 차단)
        raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). '
                                 '새 시도는 새 노드로 분기할 것')
    try:
        v = judge(None if pr['m'] is None else Prediction(
            metric_name=pr['m'], direction=pr['d'], baseline_value=pr['b'],
            noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or ''), r.metric_value)
    except PredictionMissing as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))   # 음수밴드/NaN 등 무효 입력
    verdict, delta = v.verdict, v.delta
    kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
          SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
              e.verdict_source='scripted', e.judge_script=$script,
              e.result_path=coalesce(nullif($rp,''), e.result_path), e.judged_at=$ts""",
       tree=name, tag=tag, mn=pr['m'], mv=r.metric_value, v=verdict,
       script=r.script, rp=r.result_path, ts=datetime.now(timezone.utc).isoformat())
    hist(name, 'test_result', tag, dict(value=r.metric_value, baseline=pr['b'],
                                        delta=round(delta, 4), verdict=verdict, script=r.script))
    return {'ok': True, 'verdict': verdict, 'delta': round(delta, 4), 'rule': v.reason}

@app.get('/api/tree/{name}/directions')
def directions(name: str):
    """frontier → 다음 가지 방향 자동 생성 (규칙 기반)."""
    td = tree_data(name)
    can = next((r for r in td['nodes'] if r['verdict'] == 'CANONICAL'), None)
    out = []
    for q in td['frontier']:
        if q['status'] != 'OPEN':
            continue
        out.append(dict(
            question=q['name'], body=(q['body'] or '')[:200],
            branch_from=(can or {}).get('tag'),
            suggested_tag=q['name'].replace('q-', 'exp-') + '-try1',
            protocol=['① prediction 사전등록 (baseline=' +
                      str((can or {}).get('metric_value')) + ', 방향/노이즈밴드/novel_prediction 명시)',
                      '② 변경 하나로 실험 실행', '③ 채점 스크립트로 test_result 제출 (LLM 점수 금지)',
                      '④ 자동 판결 — progressive 면 CANONICAL 승격 검토 + 질문 close']))
    return dict(canonical=(can or {}).get('tag'), open_directions=out)

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

@app.get('/api/tree/{name}/history')
def history(name: str, limit: int = 100):
    with pg() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT ts, op, node_tag, payload FROM history WHERE tree=%s '
                    'ORDER BY id DESC LIMIT %s', (name, limit))
        return [dict(r, ts=r['ts'].isoformat()) for r in cur.fetchall()]

VC = {'CANONICAL': '#1a7f37', 'canonical_stage': '#2da44e', 'former_canonical': '#6e7781',
      'rejected': '#cf222e', 'partial': '#bf8700', 'equivalent': '#0969da',
      'proof': '#8250df', 'repurposed_measurement': '#bc4c00'}

@app.get('/', response_class=HTMLResponse)
def dashboard():
    out = ['<html><head><meta charset="utf-8"><title>라카토스 서버</title><style>'
           'body{font-family:monospace;margin:24px;background:#fafafa}'
           'h2{border-bottom:2px solid #333}.n{margin:2px 0;padding:2px 6px;border-radius:4px}'
           'table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px;font-size:13px}'
           '</style></head><body><h1>라카토스 서버 — 연구 프로그램 트리</h1>']
    for t in trees():
        td = tree_data(t['name'])
        m = compute_metrics(td)
        out.append(f"<h2>{html.escape(t['name'])}</h2><p>{html.escape(td['title'] or '')}</p>")
        out.append(f"<p><b>정본 경로</b>: {' → '.join(m['canonical_path'])}</p>")
        prog = m['progress']
        out.append('<table><tr><th>진보율</th><th>기각률</th><th>퇴행깊이</th><th>frontier</th><th>주석</th></tr>')
        out.append(f"<tr><td>{(str(prog['improvement_pct'])+'%') if prog else '—'}</td>"
                   f"<td>{m['rejection_ratio']}</td><td>{m['max_degeneration_depth']}</td>"
                   f"<td>OPEN {m['frontier']['open']} / CLOSED {m['frontier']['closed']}</td>"
                   f"<td>{m['annotation_coverage']}</td></tr></table>")
        for a in m['alerts']:
            out.append(f"<p style='color:#cf222e'>⚠ {a}</p>")
        kids = {}
        for r in td['nodes']:
            kids.setdefault(r.get('parent'), []).append(r)
        def render(tag, depth):
            r = next(x for x in td['nodes'] if x['tag'] == tag)
            col = VC.get(r['verdict'], '#333')
            mv = f" <small>[{r['metric_name']}={r['metric_value']}]</small>" if r.get('metric_value') else ''
            out.append(f"<div class='n' style='margin-left:{depth*26}px'>"
                       f"<span style='color:{col}'>●</span> <b>{html.escape(tag)}</b> "
                       f"<span style='color:{col}'>{html.escape(r['verdict'])}</span>{mv}"
                       f"<br><small style='margin-left:14px;color:#555'>{html.escape((r.get('comment') or '')[:120])}</small></div>")
            for c in sorted(kids.get(tag, []), key=lambda x: x['tag']):
                render(c['tag'], depth+1)
        for root in sorted(kids.get(None, []), key=lambda x: x['tag']):
            render(root['tag'], 0)
        out.append('<h3>Frontier (열린 질문)</h3><ul>')
        for q in td['frontier']:
            mark = '🟢' if q['status'] == 'OPEN' else '✅'
            out.append(f"<li>{mark} <b>{html.escape(q['name'])}</b> — {html.escape((q['body'] or '')[:150])}</li>")
        out.append('</ul>')
    out.append('</body></html>')
    return ''.join(out)
