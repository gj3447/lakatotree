"""라카토트리 CLI — 서버 API(:55170) 위의 얇은 조작층.

사용: python -m lakatos.cli <command> [args]
  trees                          나무 목록
  tree <name>                    나무 구조
  metrics <name>                 지표(진보율/기각률/퇴행/베이즈/발전성)
  directions <name>              VoI 우선순위 다음 방향
  node <name> <tag> [--parent P] 노드 생성
  predict <name> <tag> --metric M --baseline B [--dir lower|higher]
          [--noise N] [--novel-metric M --novel-dir D --novel-thr T] [--sha S]
  result <name> <tag> --value V --script S [--sha S] [--novel-measured X]
  provenance <name> <tag>        판결 PROV 계보 + 재현명령
환경: LAKATOTREE_URL (기본 http://localhost:55170)
# KG: span_lakatotree_cli
"""
import argparse, json, os, sys
import urllib.request, urllib.error

BASE = os.environ.get('LAKATOTREE_URL', 'http://localhost:55170')


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Content-Type': 'application/json'})
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
    for c in ('tree', 'metrics', 'directions'):
        sp = sub.add_parser(c); sp.add_argument('name')
    sp = sub.add_parser('node'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--parent'); sp.add_argument('--comment', default=''); sp.add_argument('--algorithm', default='')
    sp = sub.add_parser('predict'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--metric', required=True); sp.add_argument('--baseline', type=float, required=True)
    sp.add_argument('--dir', default='lower', choices=['lower', 'higher'])
    sp.add_argument('--noise', type=float, default=0.0)
    sp.add_argument('--novel-metric'); sp.add_argument('--novel-dir', choices=['lower', 'higher'])
    sp.add_argument('--novel-thr', type=float); sp.add_argument('--sha')
    sp = sub.add_parser('result'); sp.add_argument('name'); sp.add_argument('tag')
    sp.add_argument('--value', type=float, required=True); sp.add_argument('--script', required=True)
    sp.add_argument('--sha'); sp.add_argument('--novel-measured', type=float)
    sp = sub.add_parser('provenance'); sp.add_argument('name'); sp.add_argument('tag')
    a = p.parse_args(argv)

    if a.cmd == 'trees':
        out = call('GET', '/api/trees')
    elif a.cmd == 'tree':
        out = call('GET', f'/api/tree/{a.name}')
    elif a.cmd == 'metrics':
        out = call('GET', f'/api/tree/{a.name}/metrics')
    elif a.cmd == 'directions':
        out = call('GET', f'/api/tree/{a.name}/directions')
    elif a.cmd == 'node':
        out = call('POST', f'/api/tree/{a.name}/node',
                   dict(tag=a.tag, parent=a.parent, comment=a.comment, algorithm=a.algorithm))
    elif a.cmd == 'predict':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/prediction',
                   dict(metric_name=a.metric, direction=a.dir, baseline_value=a.baseline,
                        noise_band=a.noise, novel_metric=a.novel_metric,
                        novel_direction=a.novel_dir, novel_threshold=a.novel_thr, judge_script_sha=a.sha))
    elif a.cmd == 'result':
        out = call('POST', f'/api/tree/{a.name}/node/{a.tag}/test_result',
                   dict(metric_value=a.value, script=a.script, script_sha=a.sha, novel_measured=a.novel_measured))
    elif a.cmd == 'provenance':
        out = call('GET', f'/api/tree/{a.name}/node/{a.tag}/provenance')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
