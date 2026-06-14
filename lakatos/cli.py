"""라카토트리 CLI — 서버 API(:55170) 위의 얇은 조작층.

사용: python -m lakatos.cli <command> [args]
  trees                          나무 목록
  tree <name>                    나무 구조
  metrics <name>                 지표(진보율/기각률/퇴행/베이즈/발전성/다중비교 보정 gap8)
  directions <name>              VoI 우선순위 다음 방향
  stack <name> [--leaf L]        포퍼/베이즈/라우든 3층 명시투표+정족수 메타규칙(gap3)
  lifecycle <name> [--leaf L]    프로그램 종료판정 — 수확/발산/소멸/활성(P1)
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
  node <name> <tag> [--parent P] [--parent P2] 노드 생성
  predict <name> <tag> --metric M --baseline B [--dir lower|higher]
          [--noise N] [--novel-metric M --novel-dir D --novel-thr T] [--sha S]
  result <name> <tag> --value V --script S [--sha S] [--novel-measured X]
  provenance <name> <tag>        판결 PROV 계보 + 재현명령
  event <name> <tag> <event_id>  ClaimStanding 용 상계/하계 evidence event 기록
  events <name> <tag>            ClaimStanding 이 소비하는 evidence event 목록
  claim-standing <name> <tag>    상계/하계 confidence + blocking reason
  foundation <name>              기반지식 requirement 목록
  manifest-verify <manifest.json> [--current-sha path:sha]
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


def main(argv=None):
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
    sp = sub.add_parser('leaderboard'); sp.add_argument('trees', help='쉼표구분 트리명 (≥2)')
    sp.add_argument('--snapshot', action='store_true', help='리더보드 스냅샷 축적(패러다임 판정용)')
    sp = sub.add_parser('paradigm'); sp.add_argument('incumbent')
    sp.add_argument('rivals', help='쉼표구분 경쟁 트리명')
    sp = sub.add_parser('certificate'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('calibration'); sp.add_argument('name')
    sp = sub.add_parser('question'); sp.add_argument('name'); sp.add_argument('qname')
    sp.add_argument('--body', default=''); sp.add_argument('--gain', type=float, default=0.1)
    sp.add_argument('--cost', type=float, default=1.0)
    sp = sub.add_parser('question-close'); sp.add_argument('name'); sp.add_argument('qname')
    sp.add_argument('--by', default='', help='닫은 *노드 tag* (라우든 규칙③ per-branch 귀속; '
                                             '비-노드면 문제수지 미집계=metrics.unattributed_closed)')
    sp = sub.add_parser('agm'); sp.add_argument('spec', help='AgmReviseIn JSON 파일(신념개정)')
    sp = sub.add_parser('cycle'); sp.add_argument('spec', help='CycleSpec JSON 파일(하네스 한 사이클)')
    # P6-2: CLI↔MCP 비대칭 해소 — verdict(행정판결)/critique(Dung 의문)/standing(정당성) 추가
    sp = sub.add_parser('verdict'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('verdict')
    sp.add_argument('--note', default=''); sp.add_argument('--scope', default='')
    sp.add_argument('--human', action='store_true', help='인간이 직접 vouch')
    sp = sub.add_parser('critique'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('arg_id'); sp.add_argument('attacks')
    sp.add_argument('--by', default=''); sp.add_argument('--body', default='')
    sp.add_argument('--kind', default='doubt', choices=['doubt', 'comment', 'rebuttal', 'evaluation'])
    sp = sub.add_parser('standing'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('claim-standing'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--no-replay', action='store_true')
    sp = sub.add_parser('events'); sp.add_argument('name'); sp.add_argument('tag')
    sp = sub.add_parser('event'); sp.add_argument('name'); sp.add_argument('tag'); sp.add_argument('event_id')
    sp.add_argument('--realm', required=True, choices=['internet','human','agent','bash','data','kg','git'])
    sp.add_argument('--actor', default=''); sp.add_argument('--action', required=True)
    sp.add_argument('--evidence', action='append', default=[])
    sp.add_argument('--payload', action='append', default=[], help='key=value (반복)')
    sp = sub.add_parser('node'); sp.add_argument('name'); sp.add_argument('tag')
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
    sp = sub.add_parser('rebuild-verify'); sp.add_argument('artifact')
    sp = sub.add_parser('rebuild-run'); sp.add_argument('artifact'); sp.add_argument('--recorded', type=float, required=True)
    sp.add_argument('--cmd-template', default='echo metric=0')
    sp = sub.add_parser('lineage-record'); sp.add_argument('output'); sp.add_argument('--sha', required=True)
    sp.add_argument('--producer', default=''); sp.add_argument('--producer-sha', default='')
    sp.add_argument('--input', action='append', default=[], help='path:sha (반복)')
    sp.add_argument('--kind', default='intermediate', choices=['source','intermediate','final'])
    sp = sub.add_parser('manifest-verify'); sp.add_argument('manifest')
    sp.add_argument('--current-sha', action='append', default=[], help='path:sha (반복)')
    sp.add_argument('--no-require-environment', action='store_true')
    a = p.parse_args(argv)

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
        out = call('POST', f'/api/tree/{a.name}/question',
                   dict(qname=a.qname, body=a.body, expected_gain=a.gain, cost=a.cost))
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
    elif a.cmd == 'agm':
        out = call('POST', '/api/agm/revise', json.loads(open(a.spec).read()))
    elif a.cmd == 'cycle':
        from lakatos.harness_run import main as run_cycle
        run_cycle(a.spec)   # 하네스가 직접 prov JSON 출력 (bash 실행은 client-side, server RCE 회피)
        return
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
    elif a.cmd == 'node':
        parent_edges = []
        for item in a.inferred_parent:
            parts = item.split(':', 2)
            parent_edges.append(dict(tag=parts[0], inferred=True,
                                     relation_kind=(parts[1] if len(parts) > 1 else 'backfill'),
                                     evidence_ref=(parts[2] if len(parts) > 2 else '')))
        out = call('POST', f'/api/tree/{a.name}/node',
                   dict(tag=a.tag, parents=a.parent, parent_edges=parent_edges,
                        comment=a.comment, algorithm=a.algorithm))
    elif a.cmd == 'predict':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/prediction',
                   dict(metric_name=a.metric, direction=a.dir, baseline_value=a.baseline,
                        noise_band=a.noise, novel_metric=a.novel_metric,
                        novel_direction=a.novel_dir, novel_threshold=a.novel_thr,
                        judge_script_sha=a.sha, credence=a.credence))
    elif a.cmd == 'result':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/test_result',
                   dict(metric_value=a.value, script=a.script, script_sha=a.sha, novel_measured=a.novel_measured))
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
    elif a.cmd == 'rebuild-run':
        import urllib.parse as up, subprocess, uuid
        from lakatos.rebuild import RebuildExecutor
        from lakatos.lineage import RebuildManifest, RawRoot
        from lakatos.envfp import environment_fingerprint, fingerprint_sha
        from lakatos import oo_sink
        v = call('GET', f'/api/rebuild-verify/{up.quote(a.artifact)}')
        m = v['manifest']
        mani = RebuildManifest(final=m['final'], roots=[RawRoot(**r) for r in m['roots']],
                               env_sha=m['env_sha'], recipe=m['recipe'])
        cid = 'rebuild-' + uuid.uuid4().hex[:8]
        recs = []
        def emit(rec):
            recs.append(rec); oo_sink.ship([rec])   # oo 적재(게이트 OFF면 no-op)
        ex = RebuildExecutor(run_bash=lambda c: (subprocess.run(c, shell=True, capture_output=True, text=True).stdout, 0),
                             emit=emit, env_now=fingerprint_sha(environment_fingerprint())[:12], cid=cid)
        res = ex.run(mani, recorded_metric=a.recorded, cmd_for=lambda st: a.cmd_template)
        out = dict(cid=cid, verdict=res.verdict, regenerated=res.regenerated_metric,
                   recorded=res.recorded_metric, within_tolerance=res.within_tolerance,
                   trace_events=[r['event'] for r in recs], oo_shipped=oo_sink.enabled())
    elif a.cmd == 'lineage-record':
        inputs = [[p.rsplit(':',1)[0], p.rsplit(':',1)[1]] for p in a.input]
        out = call('POST', '/api/lineage/derivation', dict(output=a.output, output_sha=a.sha,
                   producer=a.producer, producer_sha=a.producer_sha, inputs=inputs, kind=a.kind))
    elif a.cmd == 'manifest-verify':
        from .lineage import load_dataset_manifest, verify_dataset_manifest
        current_shas = {p.rsplit(':', 1)[0]: p.rsplit(':', 1)[1] for p in a.current_sha}
        out = verify_dataset_manifest(
            load_dataset_manifest(a.manifest),
            current_shas=(current_shas or None),
            require_environment=not a.no_require_environment,
        ).as_dict()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
