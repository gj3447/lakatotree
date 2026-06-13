"""라카토트리 MCP 서버 — Claude/Codex 가 라카토스 나무를 조작.

FastAPI(:55170) 위의 얇은 MCP 도구층. 도구는 서버 API 를 호출(단일 정본).
등록: claude mcp add lakatotree -- python -m lakatos.mcp_server
환경: LAKATOTREE_URL (기본 http://localhost:55170)
# KG: span_lakatotree_mcp
"""
import json, os
import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get('LAKATOTREE_URL', 'http://localhost:55170')
mcp = FastMCP('lakatotree')


def _get(path):
    r = httpx.get(BASE + path, timeout=30); r.raise_for_status(); return r.json()


def _post(path, body):
    r = httpx.post(BASE + path, json=body, timeout=30)
    if r.status_code >= 400:
        return {'error': r.status_code, 'detail': r.text[:200]}
    return r.json()


@mcp.tool()
def list_trees() -> str:
    """모든 라카토스 나무 목록."""
    return json.dumps(_get('/api/trees'), ensure_ascii=False)


@mcp.tool()
def tree_metrics(name: str) -> str:
    """나무 지표: 진보율/기각률/퇴행깊이/베이즈 신뢰도/이론 발전성(novel 예측 적중)/frontier."""
    return json.dumps(_get(f'/api/tree/{name}/metrics'), ensure_ascii=False)


@mcp.tool()
def next_directions(name: str) -> str:
    """다음 어느 가지를 확장할지 — VoI/UCB 우선순위 frontier 질문."""
    return json.dumps(_get(f'/api/tree/{name}/directions'), ensure_ascii=False)


# ── 신규 층(2026-06-13): stack 메타규칙 / lifecycle / 리더보드 / 패러다임 / 인증 ──

@mcp.tool()
def stack(name: str, leaf: str = '') -> str:
    """3층(포퍼/베이즈/라우든) 명시투표+정족수 2/3 메타규칙 — gap3. leaf 생략=정본 leaf."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'leaf': leaf})) if leaf else ''
    return json.dumps(_get(f'/api/tree/{name}/stack{q}'), ensure_ascii=False)


@mcp.tool()
def lifecycle(name: str, leaf: str = '') -> str:
    """프로그램 종료판정 — 수확/발산/소멸/활성(P1). extinct 는 stack 정족수만 선고."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'leaf': leaf})) if leaf else ''
    return json.dumps(_get(f'/api/tree/{name}/lifecycle{q}'), ensure_ascii=False)


@mcp.tool()
def leaderboard(trees_csv: str, snapshot: bool = False) -> str:
    """경쟁 트리 리더보드 — Pareto+Borda 3기준(P2). trees_csv=a,b(≥2). snapshot=패러다임 판정용 축적."""
    import urllib.parse as up
    q = up.urlencode({'trees': trees_csv, 'snapshot': str(snapshot).lower()})
    return json.dumps(_get(f'/api/leaderboard?{q}'), ensure_ascii=False)


@mcp.tool()
def paradigm(incumbent: str, rivals_csv: str) -> str:
    """패러다임 판정 — 정상과학/위기/shift_candidate(gap7). shift=인간 안건, 자동 교체 금지."""
    import urllib.parse as up
    q = up.urlencode({'incumbent': incumbent, 'rivals': rivals_csv})
    return json.dumps(_get(f'/api/paradigm?{q}'), ensure_ascii=False)


@mcp.tool()
def certificate(name: str, tag: str) -> str:
    """5게이트 AND 인증서(P2) — 사전등록/재현/standing/보정/grounding, 증거 ref 동봉."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/certificate'), ensure_ascii=False)


@mcp.tool()
def agm_revise(spec_json: str) -> str:
    """AGM 신념개정(P1) — spec_json={op('expansion'|'contraction'|'revision'|'demote_canonical'),
    base[],new?,target_id?,contradicts[]?,old_canonical_id?,allow_hard_core?}.
    hard core 는 PROTECTED(allow_hard_core 없이 깎으면 409). 결과에 programme_shift_candidate(Kuhn 연동)."""
    try:
        spec = json.loads(spec_json or '{}')
    except json.JSONDecodeError as e:
        return json.dumps({'error': 'invalid_spec_json', 'detail': str(e)}, ensure_ascii=False)
    return json.dumps(_post('/api/agm/revise', spec), ensure_ascii=False)


@mcp.tool()
def calibration(name: str) -> str:
    """예측 신뢰도 보정 — Brier/log/ECE proper scoring (gap2 완화 근거). 표본=credence 단 prediction 들."""
    return json.dumps(_get(f'/api/tree/{name}/calibration'), ensure_ascii=False)


@mcp.tool()
def open_question(name: str, qname: str, body: str = '',
                  expected_gain: float = 0.1, cost: float = 1.0) -> str:
    """frontier 질문 열기. expected_gain/cost = VoI 입력(directions 우선순위). 안 주면 default."""
    return json.dumps(_post(f'/api/tree/{name}/question',
        dict(qname=qname, body=body, expected_gain=expected_gain, cost=cost)), ensure_ascii=False)


@mcp.tool()
def close_question(name: str, qname: str, closed_by: str = '') -> str:
    """frontier 질문 닫기 — append-only QuestionClosure 이벤트 + n_visits 증가(UCB 탐색)."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'closed_by': closed_by})) if closed_by else ''
    return json.dumps(_post(f'/api/tree/{name}/question/{qname}/close{q}', {}), ensure_ascii=False)


@mcp.tool()
def add_node(name: str, tag: str, parent: str = '', parents_csv: str = '',
             comment: str = '', algorithm: str = '') -> str:
    """나무에 노드 추가. parent/parents_csv 로 DAG 다중 부모를 기록."""
    parents = [p.strip() for p in parents_csv.split(',') if p.strip()]
    if parent:
        parents.insert(0, parent)
    return json.dumps(_post(f'/api/tree/{name}/node',
        dict(tag=tag, parents=parents, comment=comment, algorithm=algorithm)), ensure_ascii=False)


@mcp.tool()
def register_prediction(name: str, tag: str, metric: str, baseline: float,
                        direction: str = 'lower', noise_band: float = 0.0,
                        novel_metric: str = '', novel_direction: str = '',
                        novel_threshold: float = 0.0, script_sha: str = '',
                        credence: float = None) -> str:
    """실행 전 사전등록 예측(의무). 구조적 novel(novel_metric/threshold) 권장 — 텍스트 아닌 실측 대조.
    credence[0,1]=예측 신뢰도 → calibration/certify G4(calibrated) 입력. 안 주면 인증서 G4 영구 미통과."""
    body = dict(metric_name=metric, direction=direction, baseline_value=baseline, noise_band=noise_band)
    if novel_metric:
        body.update(novel_metric=novel_metric, novel_direction=novel_direction or 'higher',
                    novel_threshold=novel_threshold)
    if script_sha:
        body['judge_script_sha'] = script_sha
    if credence is not None:
        body['credence'] = credence
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/prediction', body), ensure_ascii=False)


@mcp.tool()
def submit_result(name: str, tag: str, value: float, script: str,
                  script_sha: str = '', novel_measured: float = None) -> str:
    """채점 스크립트 결과 제출 → 자동 판결(LLM 점수 금지). progressive/partial/equivalent/rejected."""
    body = dict(metric_value=value, script=script)
    if script_sha:
        body['script_sha'] = script_sha
    if novel_measured is not None:
        body['novel_measured'] = novel_measured
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/test_result', body), ensure_ascii=False)


@mcp.tool()
def provenance(name: str, tag: str) -> str:
    """판결의 W3C PROV-O 계보 + 재현 명령."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/provenance'), ensure_ascii=False)


@mcp.tool()
def critique(name: str, tag: str, arg_id: str, attacks: str, by: str = '',
             kind: str = 'doubt', body: str = '') -> str:
    """인간/agent 의 의문·코멘트·반박 등재(Dung attack). kind=doubt|comment|rebuttal|evaluation."""
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/critique',
        dict(arg_id=arg_id, attacks=attacks, by=by, kind=kind, body=body)), ensure_ascii=False)


@mcp.tool()
def add_research_event(name: str, tag: str, event_id: str, realm: str,
                       action: str, actor: str = '',
                       evidence_csv: str = '', payload_json: str = '{}') -> str:
    """ClaimStanding 용 상계/하계 evidence event 를 append-only 로 기록."""
    try:
        payload = json.loads(payload_json or '{}')
    except json.JSONDecodeError as exc:
        return json.dumps({'error': 'invalid_payload_json', 'detail': str(exc)}, ensure_ascii=False)
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/event',
        dict(event_id=event_id, realm=realm, actor=actor, action=action,
             evidence_refs=[x.strip() for x in evidence_csv.split(',') if x.strip()],
             payload=payload)), ensure_ascii=False)


@mcp.tool()
def research_events(name: str, tag: str) -> str:
    """ClaimStanding 이 소비하는 append-only ResearchEvent 목록."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/events'), ensure_ascii=False)


@mcp.tool()
def standing(name: str, tag: str) -> str:
    """판결이 의문들을 막아내고 서는가 — grounded extension."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/standing'), ensure_ascii=False)


@mcp.tool()
def claim_standing(name: str, tag: str, require_replay: bool = True) -> str:
    """상계/하계 confidence, foundation gap, human doubt, lineage block 을 합친 claim standing."""
    suffix = '?require_replay=false' if not require_replay else ''
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/claim-standing{suffix}'), ensure_ascii=False)


@mcp.tool()
def add_element(name: str, element_name: str, definition: str = '',
                implication: str = '', lifecycle: str = '',
                scope: str = 'domain-agnostic') -> str:
    """기법/요소를 LakatosElement 로 등록하고 나무에 연결."""
    return json.dumps(_post(f'/api/tree/{name}/element',
        dict(name=element_name, definition=definition, implication=implication,
             lifecycle=lifecycle, scope=scope)), ensure_ascii=False)


@mcp.tool()
def use_element(name: str, tag: str, element_name: str,
                note: str = '', evidence_ref: str = '') -> str:
    """노드가 어떤 LakatosElement 를 사용했는지 연결."""
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/element/{element_name}',
        dict(note=note, evidence_ref=evidence_ref)), ensure_ascii=False)


@mcp.tool()
def foundation_requirements(name: str) -> str:
    """나무의 기반지식 requirement 와 gap summary."""
    return json.dumps(_get(f'/api/tree/{name}/foundation'), ensure_ascii=False)


@mcp.tool()
def add_foundation(name: str, requirement_name: str, kind: str,
                   question: str = '', why_needed: str = '',
                   acceptance_csv: str = '', evidence_csv: str = '',
                   status: str = 'needed', optional: bool = False,
                   owner: str = '', risk_if_missing: str = '') -> str:
    """연구 시작/판정 전 필요한 기반지식 requirement 를 기록."""
    return json.dumps(_post(f'/api/tree/{name}/foundation',
        dict(name=requirement_name, kind=kind, question=question, why_needed=why_needed,
             acceptance_criteria=[x.strip() for x in acceptance_csv.split(',') if x.strip()],
             evidence_refs=[x.strip() for x in evidence_csv.split(',') if x.strip()],
             status=status, optional=optional, owner=owner,
             risk_if_missing=risk_if_missing)), ensure_ascii=False)


if __name__ == '__main__':
    mcp.run()
