"""하네스 실행기 — 실 포트(HTTP/bash/git) 주입. spec json 으로 한 사이클 구동.

사용: python -m lakatos.harness_run <spec.json>
spec.json = CycleSpec 필드. internet_sources 는 [[url, trust], ...] (parent 가 미리 read).
환경: LAKATOTREE_URL (기본 http://localhost:55170)
# KG: span_lakatotree_harness
"""
import json, os, subprocess, sys
import urllib.request, urllib.error
from lakatos.harness import LakatoHarness, CycleSpec, BuildFailed

BASE = os.environ.get('LAKATOTREE_URL', 'http://localhost:55170')


def _http(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=(json.dumps(body).encode() if body is not None else None),
        headers={'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        return {'error': e.code, 'detail': e.read().decode()[:200]}


def _bash(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    return (p.stdout + p.stderr, p.returncode)


def _git_sha():
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'],
                                       text=True).strip()
    except Exception:
        return None


def main(path):
    spec = CycleSpec(**json.loads(open(path).read()))
    # 상계는 read-only — 인터넷 fetch 는 parent(상위 agent)가 미리 채워 internet_sources 에 (url,trust) 로 주입.
    # 하네스는 그 신뢰가중만 결합 (실 WebFetch 는 agent 도구, 하네스 안에서 호출 안 함 = 권한 경계 존중).
    h = LakatoHarness(http=_http, run_bash=_bash, read_internet=None, git_sha=_git_sha)
    if spec.internet_sources:
        h._internet = lambda url, prompt: ('(상계 read: parent 제공)', 0.0)
        # seed_trust(주입값) 우선 — None 이면 0
    prov = h.run_cycle(spec)
    print(json.dumps(prov, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1])
