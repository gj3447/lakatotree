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


def _headers():
    tok = os.environ.get('LAKATOS_API_TOKEN')   # 서버 auth 켜져 있으면 토큰 전달 (REG-1)
    return {'Authorization': f'Bearer {tok}'} if tok else {}


def _get(path):
    r = httpx.get(BASE + path, headers=_headers(), timeout=30); r.raise_for_status(); return r.json()


def _post(path, body):
    r = httpx.post(BASE + path, json=body, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        return {'error': r.status_code, 'detail': r.text[:200]}
    return r.json()


def _delete(path):
    r = httpx.delete(BASE + path, headers=_headers(), timeout=30)
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
def series(name: str, leaf: str = '') -> str:
    """프로그램-시계열 진단(#5) — 정본경로 verdict 시퀀스의 진보/퇴행 경향(diagnostic_only, verdict 권위 없음)."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'leaf': leaf})) if leaf else ''
    return json.dumps(_get(f'/api/tree/{name}/series{q}'), ensure_ascii=False)


@mcp.tool()
def tradition(name: str) -> str:
    """Laudan 연구전통 조회(①) — ontology/methodology/exemplars + commitments (diagnostic_only)."""
    return json.dumps(_get(f'/api/tree/{name}/tradition'), ensure_ascii=False)


@mcp.tool()
def tradition_set(name: str, spec_json: str) -> str:
    """연구전통 선언/갱신(①) — spec_json={tradition_id,name,commitments[{commitment_id,kind,statement,
    revisability}],ontology_commitments[],methodology_rules[],exemplars[],...}. diagnostic_only(hard core 불침범)."""
    try:
        spec = json.loads(spec_json or '{}')
    except json.JSONDecodeError as e:
        return json.dumps({'error': 'invalid_spec_json', 'detail': str(e)}, ensure_ascii=False)
    return json.dumps(_post(f'/api/tree/{name}/tradition', spec), ensure_ascii=False)


@mcp.tool()
def tradition_appraise(name: str, commitment_id: str, operation: str = 'modify',
                       reason: str = '', compatibility_claim: str = '') -> str:
    """전통 commitment 수정 진단(①) — same_tradition_revision / tradition_drift / different_programme_candidate
    (diagnostic_only; identity_boundary 도 *후보*일 뿐 hard-core 는 LakatosGate/AGM 경유 확정)."""
    return json.dumps(_post(f'/api/tree/{name}/tradition/appraise',
                            dict(commitment_id=commitment_id, operation=operation, reason=reason,
                                 compatibility_claim=compatibility_claim)), ensure_ascii=False)


@mcp.tool()
def heuristic(name: str, leaf: str = '') -> str:
    """MSRP 연구정책 — negative heuristic(hard core 보호/redirect) + positive heuristic(다음 실험 생성:
    ABANDON 퇴행가지/PUSH 진보전선/PROBE 미검 hard-core/PRIORITIZE 문제압). leaf 생략=정본 leaf."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'leaf': leaf})) if leaf else ''
    return json.dumps(_get(f'/api/tree/{name}/heuristic{q}'), ensure_ascii=False)


@mcp.tool()
def trust(name: str) -> str:
    """eigentrust 글로벌 출처신뢰 — 트리의 실 인터넷 관측 그래프에 전이적 신뢰 고유벡터(P6 배선).
    coverage.mode=graph_propagated/seed_dominated/uniform_unlearned 로 현 데이터 두께 정직표기."""
    return json.dumps(_get(f'/api/tree/{name}/trust'), ensure_ascii=False)


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
def eureka(name: str, tag: str) -> str:
    """노드별 measurement-grade eureka — felt(novel 등록) vs true(확증+substantial BF+순문제폐쇄) vs
    hallucinated(felt∧¬true, the false aha). 판결 seam 산출, standing(promotion)은 별도 층."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/eureka'), ensure_ascii=False)


@mcp.tool()
def graph(name: str) -> str:
    """시각 트리 GUI 데이터 척추(E Phase 1) — node(색/klass 본류·퇴행·생존/클릭 패널) + edge(BRANCHED_FROM)
    + frontier + agenda(human-in-the-loop 안건). 프론트엔드(Phase 2)가 이걸 렌더."""
    return json.dumps(_get(f'/api/graph/{name}'), ensure_ascii=False)


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
def run_cycle(name: str, spec_json: str) -> str:
    """한 연구 사이클 오케스트레이션(서버 in-process, **bash 미실행**) — spec_json=CycleIn 필드:
    tag/metric_name/baseline/measured 필수 + 선택 parent/novel_*/credence/source_trust/critiques[].
    build/judge(bash)가 필요하면 CLI `cycle <spec.json>` 사용(서버는 RCE 회피로 bash 안 돎)."""
    try:
        spec = json.loads(spec_json or '{}')
    except json.JSONDecodeError as e:
        return json.dumps({'error': 'invalid_spec_json', 'detail': str(e)}, ensure_ascii=False)
    return json.dumps(_post(f'/api/tree/{name}/cycle', spec), ensure_ascii=False)


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
    """frontier 질문 닫기 — append-only QuestionClosure 이벤트 + n_visits 증가(UCB 탐색).
    closed_by 는 *닫은 노드 tag* 여야 라우든 규칙③ per-branch 귀속(gap4)에 집계된다
    (비-노드면 metrics.laudan.unattributed_closed 로 노출, 가지 문제수지엔 미집계)."""
    import urllib.parse as up
    q = ('?' + up.urlencode({'closed_by': closed_by})) if closed_by else ''
    return json.dumps(_post(f'/api/tree/{name}/question/{qname}/close{q}', {}), ensure_ascii=False)


@mcp.tool()
def create_tree(name: str, title: str = '', hard_core: str = '', frontier_rule: str = '',
                doc: str = '', coverage_statement: str = '', coverage_backlog_csv: str = '',
                ontology: str = '') -> str:
    """새 라카토스 나무 생성/메타 upsert — MERGE (t:LakatosTree {name}). add_node 전에 먼저 호출(없는 나무에
    add_node 는 404 '나무 없음'). 멱등이되 last-write-wins: 같은 name 재호출은 보낸 title/hard_core/
    frontier_rule 로 덮어씀(생략 필드 = 빈값으로 초기화). hard_core/frontier_rule 비우면 policy_warnings
    (hard_core_required 등) 경고만 — 차단 아님. coverage_backlog_csv = 쉼표구분 백로그(REST/CLI 와 패리티)."""
    backlog = [b.strip() for b in coverage_backlog_csv.split(',') if b.strip()]
    return json.dumps(_post(f'/api/tree/{name}',
        dict(title=title, hard_core=hard_core, frontier_rule=frontier_rule,
             doc=doc, coverage_statement=coverage_statement, coverage_backlog=backlog,
             ontology=ontology)), ensure_ascii=False)


@mcp.tool()
def delete_tree(name: str, cascade: bool = False) -> str:
    """나무 삭제(★파괴적·복구불가) — create_tree 의 짝. 미존재=404. 노드가 있으면 cascade=True 일 때만
    전체 삭제(아니면 409, typo 로 진짜 연구트리 날리기 방지). 빈 나무는 cascade 없이 삭제 가능."""
    return json.dumps(_delete(f'/api/tree/{name}?cascade={"true" if cascade else "false"}'),
                      ensure_ascii=False)


@mcp.tool()
def add_node(name: str, tag: str, parent: str = '', parents_csv: str = '',
             comment: str = '', algorithm: str = '', result_path: str = '') -> str:
    """나무에 노드 추가(나무가 먼저 있어야 — 없으면 404, create_tree 로 생성). parent/parents_csv 로 DAG 다중 부모.
    result_path = 이 노드의 산출물(영수증) 경로 — reproducible 게이트(F-CON-1)의 앵커. 계보
    (record_derivation)의 최종 output 과 일치해야 하고, 그 궁극 root 들은 kind='source' 로 선언된
    **raw_root 안의 실존 파일**이어야 서버가 sha 를 디스크에서 재계산해 인증서 reproducible 을 준다."""
    parents = [p.strip() for p in parents_csv.split(',') if p.strip()]
    if parent:
        parents.insert(0, parent)
    body = dict(tag=tag, parents=parents, comment=comment, algorithm=algorithm)
    if result_path:
        body['result_path'] = result_path
    return json.dumps(_post(f'/api/tree/{name}/node', body), ensure_ascii=False)


@mcp.tool()
def register_prediction(name: str, tag: str, metric: str, baseline: float,
                        direction: str = 'lower', noise_band: float = 0.0,
                        novel_metric: str = '', novel_direction: str = '',
                        novel_threshold: float = 0.0, script_sha: str = '',
                        credence: float | None = None, closes_question: str = '') -> str:
    """실행 전 사전등록 예측(의무). 구조적 novel(novel_metric/threshold) 권장 — 텍스트 아닌 실측 대조.
    credence[0,1]=예측 신뢰도 → calibration/certify G4(calibrated) 입력. 안 주면 인증서 G4 영구 미통과.
    closes_question = 이 예측이 적중하면 닫히는 frontier 질문 — **여기 선언해야** judgement seam 이
    채점시점 problem_balance(closed−opened)를 계산해 eureka 가 살아난다('submit 후 close' 관례는
    balance 0 → 전부 hallucinated 공회전). 사후 closure 소급집계는 없음(false-부양 방지 seam)."""
    body = dict(metric_name=metric, direction=direction, baseline_value=baseline, noise_band=noise_band)
    if novel_metric:
        body.update(novel_metric=novel_metric, novel_direction=novel_direction or 'higher',
                    novel_threshold=novel_threshold)
    if script_sha:
        body['judge_script_sha'] = script_sha
    if credence is not None:
        body['credence'] = credence
    if closes_question:
        body['closes_question'] = closes_question
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/prediction', body), ensure_ascii=False)


@mcp.tool()
def submit_result(name: str, tag: str, value: float, script: str,
                  script_sha: str = '', novel_measured: float = None,
                  data_branch: bool = False, data_replay_passed: bool = True,
                  human_verdict_required: bool = False, result_path: str = '') -> str:
    """채점 스크립트 결과 제출 → 자동 판결(LLM 점수 금지). progressive/partial/equivalent/rejected.
    ENG-DU-2: data_branch(데이터 재생성 의존)+data_replay_passed=false → progressive_conditional;
    human_verdict_required=true → ambiguous(인간 판정 보류).
    result_path = 산출물(영수증) 경로 — 서버가 노드에 비파괴 병합(coalesce). reproducible 게이트
    (F-CON-1) 앵커: record_derivation 계보의 최종 output 과 일치, root 는 raw_root 안 실존 source."""
    body = dict(metric_value=value, script=script,
                data_branch=data_branch, data_replay_passed=data_replay_passed,
                human_verdict_required=human_verdict_required)
    if script_sha:
        body['script_sha'] = script_sha
    if novel_measured is not None:
        body['novel_measured'] = novel_measured
    if result_path:
        body['result_path'] = result_path
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/test_result', body), ensure_ascii=False)


@mcp.tool()
def provenance(name: str, tag: str) -> str:
    """판결의 W3C PROV-O 계보 + 재현 명령."""
    return json.dumps(_get(f'/api/tree/{name}/node/{tag}/provenance'), ensure_ascii=False)


@mcp.tool()
def set_verdict(name: str, tag: str, verdict: str, note: str = '', scope: str = '',
                human_verdict: bool = False) -> str:
    """행정 판결 지정 — CANONICAL 승격 등(ADMIN_VERDICTS 만; scripted 판결은 submit_result 전용).
    CANONICAL 은 승격 게이트(헌법+Foundation+Credibility) 통과해야 — 퇴행/미해소 의문 노드는 409."""
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/verdict',
        dict(verdict=verdict, note=note, scope=scope, human_verdict=human_verdict)), ensure_ascii=False)


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


# ── P7-B: CLI↔MCP 대칭 — lineage/rebuild/manifest 계열(전엔 CLI-only) ──────────

@mcp.tool()
def get_tree(name: str) -> str:
    """나무 전체 구조(노드/엣지/판결) — metrics 가 아닌 raw 트리. CLI `tree` 대칭."""
    return json.dumps(_get(f'/api/tree/{name}'), ensure_ascii=False)


@mcp.tool()
def get_lineage(artifact: str, stale: bool = False) -> str:
    """artifact 의 데이터 계보(DERIVED_FROM 그래프). stale=True 면 sha 불일치 입력도 표시."""
    import urllib.parse as up
    suffix = '?stale=true' if stale else ''
    return json.dumps(_get(f'/api/lineage/{up.quote(artifact)}{suffix}'), ensure_ascii=False)


@mcp.tool()
def script_history(producer: str) -> str:
    """채점/생성 스크립트(producer) 의 sha 이력 — 무결성 추적. CLI `script-history` 대칭."""
    import urllib.parse as up
    return json.dumps(_get(f'/api/lineage-script/{up.quote(producer)}'), ensure_ascii=False)


@mcp.tool()
def rebuild_verify(artifact: str) -> str:
    """artifact 를 raw 로부터 재생성할 수 있는지 검증(manifest+env_sha). 실행 아닌 검증만.
    실제 재실행(bash)은 RCE 회피로 CLI `rebuild-run` 전용 — MCP 미노출."""
    import urllib.parse as up
    return json.dumps(_get(f'/api/rebuild-verify/{up.quote(artifact)}'), ensure_ascii=False)


@mcp.tool()
def record_derivation(output: str, output_sha: str, producer: str = '', producer_sha: str = '',
                      inputs_csv: str = '', kind: str = 'intermediate') -> str:
    """데이터 계보 기록 — output 이 어느 raw/intermediate 에서 파생됐는지. CLI `lineage-record` 대칭.
    inputs_csv = 'path:sha, path:sha' (쉼표구분). kind=source|intermediate|final."""
    inputs = [[p.rsplit(':', 1)[0].strip(), p.rsplit(':', 1)[1].strip()]
              for p in inputs_csv.split(',') if ':' in p]
    return json.dumps(_post('/api/lineage/derivation',
        dict(output=output, output_sha=output_sha, producer=producer,
             producer_sha=producer_sha, inputs=inputs, kind=kind)), ensure_ascii=False)


@mcp.tool()
def manifest_verify(manifest_path: str, current_sha_csv: str = '',
                    require_environment: bool = True) -> str:
    """데이터셋 manifest 무결성 검증 — **로컬** 파일 read+검증(서버 무관). CLI `manifest-verify` 대칭.
    current_sha_csv = 'path:sha, ...' (현재 파일 sha; 안 주면 manifest 기록값만 검사)."""
    from lakatos.io.lineage import load_dataset_manifest, verify_dataset_manifest
    current = {p.rsplit(':', 1)[0].strip(): p.rsplit(':', 1)[1].strip()
               for p in current_sha_csv.split(',') if ':' in p}
    res = verify_dataset_manifest(
        load_dataset_manifest(manifest_path),
        current_shas=(current or None),
        require_environment=require_environment,
    )
    return json.dumps(res.as_dict(), ensure_ascii=False)


# ── prom32 G-Web / G-WorldAction enforced gates ──────────────────────────────

@mcp.tool()
def add_observation(name: str, tag: str, event_id: str, url: str = '', source_type: str = '',
                    lakatos_location: str = '', retrieved_at: str = '', content_hash: str = '',
                    raw_snapshot_path: str = '', trust: float = None, link_authority: float = None,
                    source_class_weight: float = None, primary_source_bonus: float = None,
                    provenance_score: float = None, corroboration_score: float = None,
                    recency_score: float = None, supply_chain_score: float = None,
                    content: str = '', theory_basis: str = '', foundation_refs_csv: str = '',
                    rival_name: str = '', rival_relation: str = '', rival_node: str = '',
                    comparison_axes_csv: str = '', longinus_refs_json: str = '') -> str:
    """G-Web 강제 — 인터넷 fetch 증거 적재. url/retrieved_at/content_hash|snapshot/source_type/
    lakatos_location(hard_core|protective_belt|positive_heuristic|negative_heuristic) + 신뢰성분 전수.
    ★G-Trust: 신뢰는 *분해* 권장(source_class_weight/link_authority/primary_source_bonus/
    provenance_score/corroboration_score/recency_score/supply_chain_score) — bare trust 는 lower-assurance.
    content 는 인젝션 스캔 대상(F07, injection_penalty 로 흐름). 미통과=422 → claim-standing 상계 공급.
    theory/rival/longinus 필드는 인터넷 관측을 이론 좌표와 경쟁 프로그램 증거로 임베딩한다."""
    body = dict(event_id=event_id, url=url, source_type=source_type, lakatos_location=lakatos_location,
                retrieved_at=retrieved_at, content_hash=content_hash,
                raw_snapshot_path=raw_snapshot_path, content=content)
    if theory_basis:
        body['theory_basis'] = theory_basis
    if foundation_refs_csv:
        body['foundation_refs'] = [x.strip() for x in foundation_refs_csv.split(',') if x.strip()]
    if rival_name:
        body['rival_name'] = rival_name
    if rival_relation:
        body['rival_relation'] = rival_relation
    if rival_node:
        body['rival_node'] = rival_node
    if comparison_axes_csv:
        body['comparison_axes'] = [x.strip() for x in comparison_axes_csv.split(',') if x.strip()]
    if longinus_refs_json:
        try:
            refs = json.loads(longinus_refs_json)
        except json.JSONDecodeError as exc:
            return json.dumps({'error': 'invalid_longinus_refs_json', 'detail': str(exc)}, ensure_ascii=False)
        body['longinus_refs'] = refs if isinstance(refs, list) else [refs]
    for k, v in dict(trust=trust, link_authority=link_authority, source_class_weight=source_class_weight,
                     primary_source_bonus=primary_source_bonus, provenance_score=provenance_score,
                     corroboration_score=corroboration_score, recency_score=recency_score,
                     supply_chain_score=supply_chain_score).items():
        if v is not None:
            body[k] = v
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/observation', body), ensure_ascii=False)


@mcp.tool()
def add_world_action(name: str, tag: str, event_id: str, command: str = '', cwd: str = '',
                     exit_code: int = None, stdout_summary: str = '', stderr_summary: str = '',
                     git_diff_hash: str = '', require_git_diff: bool = False) -> str:
    """G-WorldAction 강제 — bash 실행 증거 적재. command/cwd/exit_code/stdout|stderr 전수
    (+git_diff_hash if require_git_diff). 미통과=422. 통과시 claim-standing 하계(bash) 공급."""
    body = dict(event_id=event_id, command=command, cwd=cwd, stdout_summary=stdout_summary,
                stderr_summary=stderr_summary, git_diff_hash=git_diff_hash,
                require_git_diff=require_git_diff)
    if exit_code is not None:
        body['exit_code'] = exit_code
    return json.dumps(_post(f'/api/tree/{name}/node/{tag}/world-action', body), ensure_ascii=False)


@mcp.tool()
def longinus_audit() -> str:
    """Longinus 바인딩 drift 감사 — 코드↔KG ReferenceSite 정합성(L4 심볼소멸/L6 시그니처변경).
    로컬 파일(docs/longinus_bindings.json + 소스) 기반, 서버 불필요. 결과 JSON."""
    from lakatos.longinus import audit
    return json.dumps(audit(), ensure_ascii=False)


if __name__ == '__main__':
    mcp.run()
