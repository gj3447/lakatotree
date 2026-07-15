"""라카토트리 CLI — 서버 API(:55170) 위의 얇은 조작층.

사용: python -m lakatos.cli <command> [args]
  trees                          나무 목록
  tree <name>                    나무 구조
  metrics <name>                 지표(진보율/기각률/퇴행/베이즈/발전성/다중비교 보정 gap8)
  directions <name>              VoI 우선순위 다음 방향 (분자=positive heuristic 실계산)
  heuristic <name> [--leaf L]    MSRP 연구정책 — negative(hard core 보호)+positive(다음 수 생성)
  trust <name>                   eigentrust 글로벌 출처신뢰(실 관측 그래프, coverage 정직표기, P6)
  stack <name> [--leaf L]        포퍼/베이즈/라우든 3층 명시투표+정족수 메타규칙(gap3)
  lifecycle <name> [--leaf L]    프로그램 종료판정 — 수확/발산/소멸/활성(P1)
  series <name> [--leaf L]       프로그램-시계열 진단 — 정본경로 verdict 진보/퇴행 경향(diagnostic_only, #5)
  tradition <name>               Laudan 연구전통 조회(ontology/methodology/exemplars, diagnostic_only, ①)
  tradition-set <name> <spec>    연구전통 선언/갱신 — TraditionIn JSON 파일
  tradition-appraise <name> <cid> [--operation modify] [--receipt R] [--compat C]   commitment 수정 진단
  leaderboard <a,b,..> [--snapshot]  경쟁 트리 Pareto+Borda 리더보드(P2)
  paradigm <incumbent> <a,b>     정상과학/위기/shift_candidate(gap7, shift=인간 안건)
  certificate <name> <tag>       5게이트 AND 인증서(P2)
  verdict <name> <tag> <verdict> [--note --scope --human]  행정판결(CANONICAL 승격 등, 게이트 통과 필요)
  critique <name> <tag> <arg_id> <attacks> [--by --kind --body]  Dung 의문/반박 등재
  standing <name> <tag>          판결 정당성(grounded extension)
  calibration <name>             예측 신뢰도 보정 Brier/log/ECE (gap2 완화 근거)
  question <name> <qname> [--body B --gain G --cost C]  frontier 질문 열기(VoI 메타 포함)
  question-close <name> <qname> [--by B]                질문 닫기(append-only closure)
  agm <spec.json>                AGM 신념개정 — hard core revision/contraction(P1)
  cycle <spec.json>              하네스 한 사이클 — 상계read→하계build/judge→critique→standing
  cycle-dry <name> <spec.json>   run_cycle 미리보기(REST dry_run=true 직행, 쓰기 0) — verdict_preview
                                 + would_demote_to_partial(FF1 novel-anchor 강등 사전 예고, R2-NOVEL)
  tree-create <name> [--title T --hard-core H --frontier-rule F]  새 나무 생성/메타 upsert (add_node 전 필수)
  tree-delete <name> [--cascade]  나무 삭제(파괴적; 노드 있으면 --cascade 필수)
  node <name> <tag> [--parent P] [--parent P2] 노드 생성
  predict <name> <tag> --metric M --baseline B [--dir lower|higher]
          [--noise N] [--novel-metric M --novel-dir D --novel-thr T] [--sha S]
  result <name> <tag> --value V --script S [--sha S] [--novel-measured X] [질적/PnR 증거]
  provenance <name> <tag>        판결 PROV 계보 + 재현명령
  event <name> <tag> <event_id>  ClaimStanding 용 상계/하계 evidence event 기록
  events <name> <tag>            ClaimStanding 이 소비하는 evidence event 목록
  claim-standing <name> <tag>    상계/하계 confidence + blocking reason
  foundation <name>              기반지식 requirement 목록
  manifest-verify <manifest.json> [--current-sha path:sha]
  observation <name> <tag> <event_id> --url U --source-type T --lakatos-location L [...]  G-Web 강제 인터넷증거
  world-action <name> <tag> <event_id> --command C --cwd D --exit-code N [...]            G-WorldAction 강제 bash증거
환경: LAKATOTREE_URL (기본 http://localhost:55170)
# KG: span_lakatotree_cli
"""
import argparse, json, os, sys
import urllib.request, urllib.error

BASE = os.environ.get('LAKATOTREE_URL', 'http://localhost:55170')


def call(method, path, body=None):
    headers = {'Content-Type': 'application/json'}
    tok = os.environ.get('LAKATOS_API_TOKEN')   # 서버 auth 켜져 있으면 토큰 전달 (REG-1)
    if tok:
        headers['Authorization'] = f'Bearer {tok}'
    req = urllib.request.Request(BASE + path, method=method,
        data=(json.dumps(body).encode() if body is not None else None), headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        sys.exit(f'HTTP {e.code}: {e.read().decode()[:200]}')
    except urllib.error.URLError as e:
        sys.exit(f'서버 연결 실패({BASE}): {e}. server/run.sh 가동 확인')


def _build_parser() -> argparse.ArgumentParser:
    """CLI 표면 *선언* — 모든 서브커맨드+인자 정의(한 책임). main 의 dispatch/네트워크와 분리(SRP):
    전엔 한 함수에 ~100 LOC 선언 + ~180 LOC dispatch 가 융합. parser 만 필요한 테스트/도구가
    dispatch·서버호출 없이 parse_args 할 수 있다(표면 변경의 단일 findable home)."""
    p = argparse.ArgumentParser(prog='lakatos', description='라카토트리 CLI')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('trees')
    for c in ('tree', 'metrics', 'directions', 'foundation'):
        sp = sub.add_parser(c); sp.add_argument('name')
    # 신규 층(2026-06-13) — stack 메타규칙 / lifecycle / 리더보드 / 패러다임 / 인증
    sp = sub.add_parser('stack'); sp.add_argument('name')
    sp.add_argument('--leaf', default='', help='가지 leaf tag (생략=정본 leaf)')
    sp = sub.add_parser('lifecycle'); sp.add_argument('name')
    sp.add_argument('--leaf', default='', help='가지 leaf tag (생략=정본 leaf)')
    sp = sub.add_parser('series'); sp.add_argument('name')   # #5 프로그램-시계열 진단(diagnostic_only)
    sp.add_argument('--leaf', default='', help='가지 leaf tag (생략=정본 leaf)')
    sp = sub.add_parser('tradition'); sp.add_argument('name')   # ① Laudan 연구전통 조회(diagnostic_only)
    sp = sub.add_parser('tradition-set'); sp.add_argument('name'); sp.add_argument('spec', help='TraditionIn JSON 파일')
    sp = sub.add_parser('tradition-appraise'); sp.add_argument('name'); sp.add_argument('commitment_id')
    sp.add_argument('--operation', default='modify', choices=['add', 'modify', 'retire', 'reclassify'])
    sp.add_argument('--reason', default=''); sp.add_argument('--receipt', action='append', default=[])
    sp.add_argument('--compat', default='', help='compatibility_claim(양립 정당화 — costly 표류 막음)')
    sp = sub.add_parser('heuristic'); sp.add_argument('name')
    sp.add_argument('--leaf', default='', help='가지 leaf tag (생략=정본 leaf)')
    sub.add_parser('trust').add_argument('name')
    sp = sub.add_parser('leaderboard'); sp.add_argument('trees', help='쉼표구분 트리명 (≥2)')
    sp.add_argument('--snapshot', action='store_true', help='리더보드 스냅샷 축적(패러다임 판정용)')
    sp = sub.add_parser('paradigm'); sp.add_argument('incumbent')
    sp.add_argument('rivals', help='쉼표구분 경쟁 트리명')
    sp = sub.add_parser('certificate'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('calibration'); sp.add_argument('name')
    sp = sub.add_parser('question'); sp.add_argument('name'); sp.add_argument('qname')
    sp.add_argument('--body', default=''); sp.add_argument('--gain', type=float)
    sp.add_argument('--cost', type=float)
    sp = sub.add_parser('question-close'); sp.add_argument('name'); sp.add_argument('qname')
    sp.add_argument('--by', default='', help='닫은 *노드 tag* (라우든 규칙③ per-branch 귀속; '
                                             '비-노드면 문제수지 미집계=metrics.unattributed_closed)')
    sp = sub.add_parser('agm'); sp.add_argument('spec', help='AgmReviseIn JSON 파일(신념개정)')
    sp = sub.add_parser('cycle'); sp.add_argument('spec', help='CycleSpec JSON 파일(하네스 한 사이클)')
    # R2-NOVEL: 서버 run_cycle dry_run 미리보기 — harness_run(CycleSpec bash 실행기) 경유 금지, REST 직행.
    sp = sub.add_parser('cycle-dry')
    sp.add_argument('name')
    sp.add_argument('spec', help='CycleIn JSON 파일 — dry_run=true 로 POST /api/tree/{name}/cycle '
                                 '(쓰기 0 미리보기: verdict_preview + would_demote_to_partial)')
    # P6-2: CLI↔MCP 비대칭 해소 — verdict(행정판결)/critique(Dung 의문)/standing(정당성) 추가
    sp = sub.add_parser('verdict'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('verdict')
    sp.add_argument('--note', default=''); sp.add_argument('--scope', default='')
    sp.add_argument('--human', action='store_true', help='인간이 직접 vouch')
    sp = sub.add_parser('critique'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('arg_id'); sp.add_argument('attacks')
    sp.add_argument('--by', default=''); sp.add_argument('--body', default='')
    sp.add_argument('--kind', default='doubt', choices=['doubt', 'comment', 'rebuttal', 'evaluation'])
    sp = sub.add_parser('standing'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('eureka', help='노드별 measurement-grade eureka (felt/true/hallucinated)')
    sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('graph', help='시각 트리 GUI 데이터 척추 (node 색/klass/패널 + edge + frontier + 안건, E Phase 1)')
    sp.add_argument('name')
    sp = sub.add_parser('claim-standing'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--no-replay', action='store_true')
    sp = sub.add_parser('events'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('event'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('event_id')
    sp.add_argument('--realm', required=True, choices=['internet','human','agent','bash','data','kg','git'])
    sp.add_argument('--actor', default=''); sp.add_argument('--action', required=True)
    sp.add_argument('--evidence', action='append', default=[])
    sp.add_argument('--payload', action='append', default=[], help='key=value (반복)')
    sp = sub.add_parser('tree-create'); sp.add_argument('name')
    sp.add_argument('--title', default=''); sp.add_argument('--hard-core', default='')
    sp.add_argument('--frontier-rule', default=''); sp.add_argument('--doc', default='')
    sp.add_argument('--coverage-status', default='unknown',
                    choices=['unknown', 'partial', 'exhaustive'],
                    help='커버리지 선언; exhaustive 는 scope 문장+빈 backlog 필수')
    sp.add_argument('--coverage-statement', default='')
    sp.add_argument('--coverage-backlog', action='append', default=[], help='(반복) 커버리지 백로그')
    sp.add_argument('--ontology', default='', help='도메인 온톨로지 JSON(선언 시 엔진이 노드 강제)')
    sp.add_argument('--assurance-tier', default='', choices=['', 'notebook', 'receipted', 'anchored'],
                    help='G6 보증 tier — 생략 시 신규=anchored 기본/기존=유지, 하향 선언은 409(단조 ratchet)')
    sp.add_argument('--attestor-did', action='append', default=[],
                    help='(반복) G10 서명자 allow-list(did:key) — 선언 시 anchored 판결쓰기에 write-cert 강제')
    sp = sub.add_parser('cert-keygen', help='G10 열쇠공: Ed25519 키쌍 생성 → {secret_hex, did} (secret 은 보관 책임 사용자)')
    sp = sub.add_parser('cert-sign', help='G10 열쇠공: 판결쓰기 명령 서명 → WriteCertIn JSON(stdout). prev 는 서버 receipts 에서 회수')
    sp.add_argument('name')
    sp.add_argument('tag')
    sp.add_argument('--secret-hex', required=True, help='cert-keygen 의 secret_hex')
    sp.add_argument('--metric-value', type=float, required=True)
    sp.add_argument('--script-sha', default='', help='채점 스크립트 sha256(서버 재계산과 일치해야)')
    sp = sub.add_parser('tree-delete'); sp.add_argument('name')
    sp.add_argument('--cascade', action='store_true', help='노드 포함 전체 삭제(파괴적·복구불가)')
    sp = sub.add_parser('node'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--author', default='', help='노드 작성자 actor (FF3: CANONICAL floor human attestation actor≠author 강제)')
    sp.add_argument('--parent', action='append', default=[])
    sp.add_argument('--inferred-parent', action='append', default=[], help='tag[:relation_kind[:evidence_ref]]')
    sp.add_argument('--comment', default=''); sp.add_argument('--algorithm', default='')
    sp = sub.add_parser('predict'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--metric', required=True); sp.add_argument('--baseline', type=float, required=True)
    sp.add_argument('--dir', default='lower', choices=['lower', 'higher'])
    sp.add_argument('--noise', type=float, default=0.0)
    sp.add_argument('--novel-metric'); sp.add_argument('--novel-dir', choices=['lower', 'higher'])
    sp.add_argument('--novel-thr', type=float); sp.add_argument('--sha')
    sp.add_argument('--credence', type=float, help='예측 신뢰도[0,1] — calibration/certify G4 입력')
    sp = sub.add_parser('result'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--value', type=float, required=True); sp.add_argument('--script', required=True)
    sp.add_argument('--sha'); sp.add_argument('--novel-measured', type=float)
    sp.add_argument('--novel-script', default='',
                    help='서버앵커 novel 측정 스크립트(file 또는 file::symbol) — cross-metric novel 독립성 영수증(FF1)')
    sp.add_argument('--data-branch', action='store_true', help='데이터 재생성 의존 분기(ENG-DU-2)')
    sp.add_argument('--no-data-replay', action='store_true', help='데이터 재현 미통과 → progressive_conditional')
    sp.add_argument('--human-verdict', action='store_true', help='인간 판정 보류 → ambiguous')
    # PU: REST TestResultIn 의 질적/PnR 증거를 basic CLI 에도 그대로 노출한다. Lakatos 4축과
    # heuristic-spirit 은 부재(unknown)와 명시적 false 가 다르므로 BooleanOptionalAction 3상이다.
    sp.add_argument('--lakatos-anomaly', action=argparse.BooleanOptionalAction, default=None,
                    help='이론의존적 anomaly 여부(--no-lakatos-anomaly 로 false)')
    sp.add_argument('--lakatos-consequence', action=argparse.BooleanOptionalAction, default=None,
                    help='독립 검증가능 귀결 여부')
    sp.add_argument('--lakatos-excess', action=argparse.BooleanOptionalAction, default=None,
                    help='초과 경험내용 여부')
    sp.add_argument('--lakatos-hardcore', action=argparse.BooleanOptionalAction, default=None,
                    help='hard core 보존 여부(touched-assumption 구조판정이 우선)')
    sp.add_argument('--touched-assumption', action='append', default=[],
                    help='변경이 건드린 가정(반복); tree hard_core 와 교집합을 서버가 판정')
    sp.add_argument('--implementation-complete', action=argparse.BooleanOptionalAction, default=True)
    sp.add_argument('--counterexample-response', choices=[
        'surrender', 'monster_barring', 'exception_barring', 'monster_adjustment',
        'lemma_incorporation', 'proofs_and_refutations'])
    sp.add_argument('--counterexample-type', choices=[
        'global', 'local', 'local_and_global', 'local_not_global', 'global_not_local'])
    sp.add_argument('--ce-excess-content', action='store_true')
    sp.add_argument('--ce-novel-corroborated', action='store_true')
    sp.add_argument('--ce-in-heuristic-spirit', action=argparse.BooleanOptionalAction, default=None)
    sp.add_argument('--ce-proof-concept-name', default='')
    sp.add_argument('--ce-proof-born-from', default='')
    sp.add_argument('--ce-proof-incorporated-lemma', default='')
    sp = sub.add_parser('provenance'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('element'); sp.add_argument('name'); sp.add_argument('element_name')
    sp.add_argument('--definition', default=''); sp.add_argument('--implication', default='')
    sp.add_argument('--lifecycle', default=''); sp.add_argument('--scope', default='domain-agnostic')
    sp = sub.add_parser('use-element'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('element_name')
    sp.add_argument('--note', default=''); sp.add_argument('--evidence-ref', default='')
    sp = sub.add_parser('foundation-record'); sp.add_argument('name'); sp.add_argument('requirement_name')
    sp.add_argument('--kind', required=True, choices=['theory','domain','data','metric','method','tool',
                                                     'trust','reproducibility','human_protocol'])
    sp.add_argument('--question', default=''); sp.add_argument('--why-needed', default='')
    sp.add_argument('--accept', action='append', default=[]); sp.add_argument('--evidence', action='append', default=[])
    sp.add_argument('--status', default='needed', choices=['needed','satisfied','waived'])
    sp.add_argument('--optional', action='store_true'); sp.add_argument('--owner', default='')
    sp.add_argument('--risk-if-missing', default='')
    sp = sub.add_parser('lineage'); sp.add_argument('artifact'); sp.add_argument('--stale', action='store_true')
    sp = sub.add_parser('script-history'); sp.add_argument('producer')
    sp = sub.add_parser('reconcile-outbox')   # B1 복구 운영 트리거(#4) — pending OutboxEntry 멱등 재적용
    sp = sub.add_parser('rebuild-verify'); sp.add_argument('artifact')
    sp = sub.add_parser('rebuild-run'); sp.add_argument('artifact'); sp.add_argument('--recorded', type=float, required=True)
    sp.add_argument('--cmd-template', default='echo metric=0')
    sp.add_argument('--measure-cmd', default='',   # #M10: kind='measurement' step 전용(producer 와 분리).
                    help="measurement step 전용 명령 — 미지정 시 모든 step 이 단일 cmd-template 로 붕괴(measurer=producer)")
    sp = sub.add_parser('lineage-record'); sp.add_argument('output'); sp.add_argument('--sha', required=True)
    sp.add_argument('--producer', default=''); sp.add_argument('--producer-sha', default='')
    sp.add_argument('--input', action='append', default=[], help='path:sha (반복)')
    sp.add_argument('--kind', default='intermediate', choices=['source','intermediate','final'])
    sp = sub.add_parser('manifest-verify'); sp.add_argument('manifest')
    sp.add_argument('--current-sha', action='append', default=[], help='path:sha (반복)')
    sp.add_argument('--no-require-environment', action='store_true')   # manifest-verify 전용 (merge 사고 복구)
    sp = sub.add_parser('longinus', help='코드↔KG ReferenceSite 바인딩 drift 감사 (로컬, 서버 불필요)')
    sp.add_argument('--json', action='store_true', help='JSON 출력')
    sp.add_argument('--dashboard', action='store_true', help='오프라인 HTML 대시보드 생성(lakatos.longinus_dashboard)')
    # prom32 G-Web / G-WorldAction enforced gates
    sp = sub.add_parser('observation'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('event_id')
    sp.add_argument('--url', default=''); sp.add_argument('--source-type', default='')
    sp.add_argument('--lakatos-location', default='', choices=['', 'hard_core', 'protective_belt',
                                                               'positive_heuristic', 'negative_heuristic'])
    sp.add_argument('--retrieved-at', default=''); sp.add_argument('--content-hash', default='')
    sp.add_argument('--snapshot', default=''); sp.add_argument('--trust', type=float, help='레거시 집계(분해 권장)')
    sp.add_argument('--link-authority', type=float); sp.add_argument('--content', default='', help='injection scan 대상')
    # G-Trust 분해 신뢰 성분(권장 — bare trust 는 lower-assurance)
    sp.add_argument('--source-class', type=float); sp.add_argument('--primary-source', type=float)
    sp.add_argument('--provenance', type=float); sp.add_argument('--corroboration', type=float)
    sp.add_argument('--recency', type=float); sp.add_argument('--supply-chain', type=float, help='F04 supply-chain 축')
    # 나생문 #21: rival/theory/longinus 증거 필드 — MCP/REST add_observation 패리티(관측을 이론좌표·경쟁프로그램 증거로 임베딩)
    sp.add_argument('--theory-basis', default=''); sp.add_argument('--foundation-refs', default='', help='CSV')
    sp.add_argument('--rival-name', default=''); sp.add_argument('--rival-relation', default='')
    sp.add_argument('--rival-node', default=''); sp.add_argument('--comparison-axes', default='', help='CSV')
    sp.add_argument('--longinus-refs', default='', help='JSON list')
    sp = sub.add_parser('world-action'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('event_id')
    sp.add_argument('--command', default=''); sp.add_argument('--cwd', default='')
    sp.add_argument('--exit-code', type=int); sp.add_argument('--stdout', default=''); sp.add_argument('--stderr', default='')
    sp.add_argument('--git-diff', default=''); sp.add_argument('--require-git-diff', action='store_true')
    return p


def main(argv=None):
    """CLI dispatch — parser(=_build_parser)로 파싱 후 명령을 서버 API/로컬 감사로 라우팅(한 책임)."""
    p = _build_parser()
    a = p.parse_args(argv)

    if a.cmd == 'longinus':   # 로컬 감사 — 서버 호출 안 함 (코드↔KG 바인딩 정합성)
        if getattr(a, 'dashboard', False):
            from lakatos.longinus_dashboard import run as _dash
            out = _dash(write=True)
            print(f"대시보드: {out['html_path']}  (audit {out['audit']['passed']}/{out['audit']['total']})")
            sys.exit(0 if out['audit']['ok'] else 1)
        from lakatos.longinus import audit, report
        res = audit()
        print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else report(res))
        sys.exit(0 if res['ok'] else 1)

    if a.cmd == 'trees':
        out = call('GET', '/api/trees')
    elif a.cmd == 'tree':
        out = call('GET', f'/api/tree/{a.name}')
    elif a.cmd == 'metrics':
        out = call('GET', f'/api/tree/{a.name}/metrics')
    elif a.cmd == 'directions':
        out = call('GET', f'/api/tree/{a.name}/directions')
    elif a.cmd == 'foundation':
        out = call('GET', f'/api/tree/{a.name}/foundation')
    elif a.cmd == 'stack':
        import urllib.parse as up
        q = ('?' + up.urlencode({'leaf': a.leaf})) if a.leaf else ''
        out = call('GET', f'/api/tree/{a.name}/stack{q}')
    elif a.cmd == 'lifecycle':
        import urllib.parse as up
        q = ('?' + up.urlencode({'leaf': a.leaf})) if a.leaf else ''
        out = call('GET', f'/api/tree/{a.name}/lifecycle{q}')
    elif a.cmd == 'series':
        import urllib.parse as up
        q = ('?' + up.urlencode({'leaf': a.leaf})) if a.leaf else ''
        out = call('GET', f'/api/tree/{a.name}/series{q}')   # #5 프로그램-시계열 진단
    elif a.cmd == 'tradition':
        out = call('GET', f'/api/tree/{a.name}/tradition')   # ① 연구전통 조회
    elif a.cmd == 'tradition-set':
        out = call('POST', f'/api/tree/{a.name}/tradition', json.loads(open(a.spec).read()))
    elif a.cmd == 'tradition-appraise':
        out = call('POST', f'/api/tree/{a.name}/tradition/appraise',
                   dict(commitment_id=a.commitment_id, operation=a.operation, reason=a.reason,
                        receipt_refs=a.receipt, compatibility_claim=a.compat))
    elif a.cmd == 'heuristic':
        import urllib.parse as up
        q = ('?' + up.urlencode({'leaf': a.leaf})) if a.leaf else ''
        out = call('GET', f'/api/tree/{a.name}/heuristic{q}')
    elif a.cmd == 'trust':
        out = call('GET', f'/api/tree/{a.name}/trust')
    elif a.cmd == 'leaderboard':
        import urllib.parse as up
        q = up.urlencode({'trees': a.trees, 'snapshot': str(a.snapshot).lower()})
        out = call('GET', f'/api/leaderboard?{q}')
    elif a.cmd == 'paradigm':
        import urllib.parse as up
        q = up.urlencode({'incumbent': a.incumbent, 'rivals': a.rivals})
        out = call('GET', f'/api/paradigm?{q}')
    elif a.cmd == 'certificate':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/certificate')
    elif a.cmd == 'calibration':
        out = call('GET', f'/api/tree/{a.name}/calibration')
    elif a.cmd == 'question':
        body = dict(qname=a.qname, body=a.body)
        if a.gain is not None:
            body['expected_gain'] = a.gain
        if a.cost is not None:
            body['cost'] = a.cost
        out = call('POST', f'/api/tree/{a.name}/question', body)
    elif a.cmd == 'question-close':
        import urllib.parse as up
        q = ('?' + up.urlencode({'closed_by': a.by})) if a.by else ''
        out = call('POST', f'/api/tree/{a.name}/question/{a.qname}/close{q}')
    elif a.cmd == 'verdict':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/verdict',
                   dict(verdict=a.verdict, note=a.note, scope=a.scope, human_verdict=a.human))
    elif a.cmd == 'critique':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/critique',
                   dict(arg_id=a.arg_id, attacks=a.attacks, by=a.by, kind=a.kind, body=a.body))
    elif a.cmd == 'standing':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/standing')
    elif a.cmd == 'eureka':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/eureka')
    elif a.cmd == 'graph':
        out = call('GET', f'/api/graph/{a.name}')
    elif a.cmd == 'agm':
        out = call('POST', '/api/agm/revise', json.loads(open(a.spec).read()))
    elif a.cmd == 'cycle':
        # 타입경계 경유(FIX-A) — main() 직행이면 BuildFailed/ScoringRefused/BashTimeout 이 생
        #   스택트레이스로 샌다. run_typed 가 이유코드+exit code 로 번역(성공은 prov JSON + 0 그대로).
        from lakatos.harness_run import run_typed
        sys.exit(run_typed(a.spec))   # 하네스가 prov JSON 출력 (bash 실행은 client-side, server RCE 회피)
    elif a.cmd == 'cycle-dry':
        # R2-NOVEL: REST run_cycle dry_run 직행(harness_run/CycleSpec 의 bash 실행기 의미론과 무관).
        #   서버 incore trial(쓰기 0) + would_demote_to_partial(FF1 novel-anchor 강등 사전 예고) 반환.
        spec = json.loads(open(a.spec).read())
        spec['dry_run'] = True   # 이 verb 의 계약: 항상 미리보기(스펙의 dry_run=false 를 덮어씀)
        out = call('POST', f'/api/tree/{a.name}/cycle', spec)
    elif a.cmd == 'claim-standing':
        suffix = '?require_replay=false' if a.no_replay else ''
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/claim-standing{suffix}')
    elif a.cmd == 'events':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/events')
    elif a.cmd == 'event':
        payload = {}
        for item in a.payload:
            if '=' not in item:
                sys.exit(f'payload 형식 오류: {item} (key=value)')
            k, v = item.split('=', 1)
            payload[k] = v
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/event',
                   dict(event_id=a.event_id, realm=a.realm, actor=a.actor,
                        action=a.action, evidence_refs=a.evidence, payload=payload))
    elif a.cmd == 'tree-create':
        out = call('POST', f'/api/tree/{a.name}',
                   dict(title=a.title, hard_core=a.hard_core, frontier_rule=a.frontier_rule,
                        doc=a.doc, coverage_status=a.coverage_status,
                        coverage_statement=a.coverage_statement,
                        coverage_backlog=a.coverage_backlog, ontology=a.ontology,
                        assurance_tier=(a.assurance_tier or None),
                        attestor_dids=(a.attestor_did or None)))
    elif a.cmd == 'cert-keygen':
        from lakatos.write_cert import keygen
        secret_hex, did = keygen()
        out = dict(secret_hex=secret_hex, did=did,
                   note='secret 은 출력물 밖에 저장하지 말 것 — 트리 attestor_dids 에 did 를 등록하면 강제 발동')
    elif a.cmd == 'cert-sign':
        from lakatos.write_cert import build_write_cert
        chain = call('GET', f'/api/tree/{a.name}/node/{a.tag}/receipts')   # prev 포인터 회수(CAS 바인딩)
        command = dict(tree=a.name, tag=a.tag, prev_receipt_sha=chain.get('head'),
                       metric_value=a.metric_value, script_sha=a.script_sha,
                       verb=(getattr(a, 'verb', None) or 'submit_test_result'))   # AG5-IDENT: verb 바인딩
        out = build_write_cert(bytes.fromhex(a.secret_hex), command)
    elif a.cmd == 'tree-delete':
        out = call('DELETE', f'/api/tree/{a.name}' + ('?cascade=true' if a.cascade else ''))
    elif a.cmd == 'node':
        parent_edges = []
        for item in a.inferred_parent:
            parts = item.split(':', 2)
            parent_edges.append(dict(tag=parts[0], inferred=True,
                                     relation_kind=(parts[1] if len(parts) > 1 else 'backfill'),
                                     evidence_ref=(parts[2] if len(parts) > 2 else '')))
        out = call('POST', f'/api/tree/{a.name}/node',
                   dict(tag=a.tag, parents=a.parent, parent_edges=parent_edges,
                        comment=a.comment, algorithm=a.algorithm, author=a.author))
    elif a.cmd == 'predict':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/prediction',
                   dict(metric_name=a.metric, direction=a.dir, baseline_value=a.baseline,
                        noise_band=a.noise, novel_metric=a.novel_metric,
                        novel_direction=a.novel_dir, novel_threshold=a.novel_thr,
                        judge_script_sha=a.sha, credence=a.credence))
    elif a.cmd == 'result':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/test_result',
                   dict(metric_value=a.value, script=a.script, script_sha=a.sha, novel_measured=a.novel_measured,
                        novel_script=a.novel_script,
                        data_branch=a.data_branch, data_replay_passed=not a.no_data_replay,
                        human_verdict_required=a.human_verdict,
                        lakatos_anomaly=a.lakatos_anomaly,
                        lakatos_consequence=a.lakatos_consequence,
                        lakatos_excess=a.lakatos_excess,
                        lakatos_hardcore=a.lakatos_hardcore,
                        touched_assumptions=a.touched_assumption,
                        implementation_complete=a.implementation_complete,
                        counterexample_response=a.counterexample_response,
                        counterexample_type=a.counterexample_type,
                        ce_excess_content=a.ce_excess_content,
                        ce_novel_corroborated=a.ce_novel_corroborated,
                        ce_in_heuristic_spirit=a.ce_in_heuristic_spirit,
                        ce_proof_concept_name=a.ce_proof_concept_name,
                        ce_proof_born_from=a.ce_proof_born_from,
                        ce_proof_incorporated_lemma=a.ce_proof_incorporated_lemma))
    elif a.cmd == 'provenance':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/provenance')
    elif a.cmd == 'element':
        out = call('POST', f'/api/tree/{a.name}/element',
                   dict(name=a.element_name, definition=a.definition, implication=a.implication,
                        lifecycle=a.lifecycle, scope=a.scope))
    elif a.cmd == 'use-element':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/element/{a.element_name}',
                   dict(note=a.note, evidence_ref=a.evidence_ref))
    elif a.cmd == 'foundation-record':
        out = call('POST', f'/api/tree/{a.name}/foundation',
                   dict(name=a.requirement_name, kind=a.kind, question=a.question,
                        why_needed=a.why_needed, acceptance_criteria=a.accept,
                        evidence_refs=a.evidence, status=a.status, optional=a.optional,
                        owner=a.owner, risk_if_missing=a.risk_if_missing))
    elif a.cmd == 'lineage':
        import urllib.parse as up
        out = call('GET', f'/api/lineage/{up.quote(a.artifact)}' + ('?stale=true' if a.stale else ''))
    elif a.cmd == 'script-history':
        import urllib.parse as up
        out = call('GET', f'/api/lineage-script/{up.quote(a.producer)}')
    elif a.cmd == 'rebuild-verify':
        import urllib.parse as up
        out = call('GET', f'/api/rebuild-verify/{up.quote(a.artifact)}')
    elif a.cmd == 'reconcile-outbox':
        out = call('POST', '/api/ops/reconcile-outbox')   # B1 복구(#4) — 멱등 재적용
    elif a.cmd == 'rebuild-run':
        import urllib.parse as up, subprocess, uuid
        from lakatos.io.rebuild import RebuildExecutor
        from lakatos.io.lineage import RebuildManifest, RawRoot
        from lakatos.io.envfp import environment_fingerprint, fingerprint_sha
        from lakatos.io import oo_sink
        v = call('GET', f'/api/rebuild-verify/{up.quote(a.artifact)}')
        m = v['manifest']
        mani = RebuildManifest(final=m['final'], roots=[RawRoot(**r) for r in m['roots']],
                               env_sha=m['env_sha'], recipe=m['recipe'])
        cid = 'rebuild-' + uuid.uuid4().hex[:8]
        recs = []
        def emit(rec):
            recs.append(rec); oo_sink.ship([rec])   # oo 적재(게이트 OFF면 no-op)
        def run_bash(c):   # 실제 exit code 전달 — 0 박제 금지(크래시 단계가 step_failed 로 정직히 보고)
            r = subprocess.run(c, shell=True, capture_output=True, text=True)
            return (r.stdout, r.returncode)
        ex = RebuildExecutor(run_bash=run_bash,
                             emit=emit, env_now=fingerprint_sha(environment_fingerprint())[:12], cid=cid)
        # #M10: kind='measurement' step 은 --measure-cmd 로 라우팅(producer 와 분리). 미지정이면 단일
        #   cmd-template 로 떨어져 measurer=producer 붕괴 → 엔진이 measurer_separated=False 로 정직 노출.
        def cmd_for(st):
            if st.get('kind') == 'measurement' and a.measure_cmd:
                return a.measure_cmd
            return a.cmd_template
        res = ex.run(mani, recorded_metric=a.recorded, cmd_for=cmd_for)
        out = dict(cid=cid, verdict=res.verdict, regenerated=res.regenerated_metric,
                   recorded=res.recorded_metric, within_tolerance=res.within_tolerance,
                   measurer_separated=res.measurer_separated,   # 측정자≠생산자 영수증(붕괴 숨김 금지)
                   trace_events=[r['event'] for r in recs], oo_shipped=oo_sink.enabled())
    elif a.cmd == 'lineage-record':
        for p in a.input:   # 나생문 #22: ':' 없는 입력에 IndexError 크래시 방지 — MCP 가드와 동형
            if ':' not in p:
                sys.exit(f'lineage-record --input 형식 오류: {p!r} (path:sha 형식 필요)')
        inputs = [[*p.rsplit(':', 1)] for p in a.input]
        out = call('POST', '/api/lineage/derivation', dict(output=a.output, output_sha=a.sha,
                   producer=a.producer, producer_sha=a.producer_sha, inputs=inputs, kind=a.kind))
    elif a.cmd == 'manifest-verify':
        from lakatos.io.lineage import load_dataset_manifest, verify_dataset_manifest
        for p in a.current_sha:   # 나생문 #22: ':' 없는 입력에 IndexError 크래시 방지 — MCP 가드와 동형
            if ':' not in p:
                sys.exit(f'manifest-verify --current-sha 형식 오류: {p!r} (path:sha 형식 필요)')
        current_shas = {p.rsplit(':', 1)[0]: p.rsplit(':', 1)[1] for p in a.current_sha}
        out = verify_dataset_manifest(
            load_dataset_manifest(a.manifest),
            current_shas=(current_shas or None),
            require_environment=not a.no_require_environment,
        ).as_dict()
    elif a.cmd == 'observation':
        body = dict(event_id=a.event_id, url=a.url, source_type=a.source_type,
                    lakatos_location=a.lakatos_location, retrieved_at=a.retrieved_at,
                    content_hash=a.content_hash, raw_snapshot_path=a.snapshot, content=a.content)
        for k, v in dict(trust=a.trust, link_authority=a.link_authority, source_class_weight=a.source_class,
                         primary_source_bonus=a.primary_source, provenance_score=a.provenance,
                         corroboration_score=a.corroboration, recency_score=a.recency,
                         supply_chain_score=a.supply_chain).items():
            if v is not None:
                body[k] = v
        # 나생문 #21: rival/theory 증거 forward (MCP add_observation 미러)
        for k, v in dict(theory_basis=a.theory_basis, rival_name=a.rival_name,
                         rival_relation=a.rival_relation, rival_node=a.rival_node).items():
            if v:
                body[k] = v
        if a.foundation_refs:
            body['foundation_refs'] = [x.strip() for x in a.foundation_refs.split(',') if x.strip()]
        if a.comparison_axes:
            body['comparison_axes'] = [x.strip() for x in a.comparison_axes.split(',') if x.strip()]
        if a.longinus_refs:
            body['longinus_refs'] = json.loads(a.longinus_refs)
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/observation', body)
    elif a.cmd == 'world-action':
        body = dict(event_id=a.event_id, command=a.command, cwd=a.cwd, stdout_summary=a.stdout,
                    stderr_summary=a.stderr, git_diff_hash=a.git_diff, require_git_diff=a.require_git_diff)
        if a.exit_code is not None:
            body['exit_code'] = a.exit_code
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/world-action', body)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
