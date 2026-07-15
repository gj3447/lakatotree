"""하네스 실행기 — 실 포트(HTTP/bash/git) 주입. spec json 으로 한 사이클 구동.

사용: python -m lakatos.harness_run <spec.json>
spec.json = CycleSpec 필드. internet_sources 는 [[url, trust], ...] (parent 가 미리 read).
환경: LAKATOTREE_URL (기본 http://localhost:55170)
      LAKATOTREE_BASH_TIMEOUT (기본 600) — build/judge 서브프로세스 *벽시계* 예산(초, 양의 정수).
# KG: span_lakatotree_harness
"""
import json, os, subprocess, sys
import urllib.request, urllib.error
from lakatos.harness import (LakatoHarness, CycleSpec, BashConfigError, BashTimeout,
                             BuildFailed, ScoringRefused)

BASE = os.environ.get('LAKATOTREE_URL', 'http://localhost:55170')
BASH_TIMEOUT_DEFAULT = 600   # 종전 하드코딩값 — env 미설정 시 거동 동일(비파괴)

# 타입 종단 레지스트리(PROM16 S1) — 예외 → (이유코드, 등급). 등급은 루프 드라이버의 *정책* 구분:
#   transient = 재시도+백오프 대상 / permanent = 즉시 실패(재시도 무의미, 세계가 안 바뀜).
#   ★ 이유코드 문자열은 CLI 표면의 공개 계약 — 바꾸면 루프 드라이버가 깨진다.
TYPED_TERMINALS = {
    BashTimeout:     ('timeout', 'transient'),
    BuildFailed:     ('build_failed', 'permanent'),
    ScoringRefused:  ('scoring_refused', 'permanent'),
    BashConfigError: ('config_error', 'permanent'),
}


def _http(method, path, body=None):
    headers = {'Content-Type': 'application/json'}
    tok = os.environ.get('LAKATOS_API_TOKEN')   # 서버 auth 켜져 있으면 토큰 전달 (REG-1)
    if tok:
        headers['Authorization'] = f'Bearer {tok}'
    req = urllib.request.Request(BASE + path, method=method,
        data=(json.dumps(body).encode() if body is not None else None), headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        return {'error': e.code, 'detail': e.read().decode()[:200]}


def _bash_timeout():
    """벽시계 예산(초) — LAKATOTREE_BASH_TIMEOUT, 기본 600. 부정값은 *타입* 거부(fail-closed).

    FIX-C: 종전 int(os.environ.get(...)) 는 오염된 env(빈값/'abc'/0/음수)에서 _bash 안쪽의 생
    ValueError 로 터졌다 — 벽시계 가드가 스스로 무타입 크래시가 되는 자멸. 조용한 600 폴백도
    금지: 운영자가 선언한 경계를 무음 무시하는 우회이기 때문(불확실한 예산 < 명시적 거부).
    """
    raw = os.environ.get('LAKATOTREE_BASH_TIMEOUT')
    if raw is None or raw == '':
        return BASH_TIMEOUT_DEFAULT   # 미설정/빈값(`FOO=`)=쉘 관용상 미선언 → 기본
    # 그 외는 전부 *선언된* 값 — 공백만/문자/0/음수는 뜻이 부정하므로 조용히 안 넘긴다(아래 거부).
    try:
        secs = int(raw)
    except (TypeError, ValueError):
        raise BashConfigError(f'LAKATOTREE_BASH_TIMEOUT 이 정수가 아님: {raw!r} — '
                              f'양의 정수(초) 또는 미설정(기본 {BASH_TIMEOUT_DEFAULT})')
    if secs <= 0:
        raise BashConfigError(f'LAKATOTREE_BASH_TIMEOUT 은 양수여야 함: {secs} — '
                              f'0/음수는 벽시계 가드를 무력화(무한 대기)한다')
    return secs


def _bash(cmd):
    """하계 실행 — 벽시계 예산 초과는 BashTimeout(타입 종단). 생 TimeoutExpired 는 안 샌다."""
    secs = _bash_timeout()
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=secs)
    except subprocess.TimeoutExpired as e:
        raise BashTimeout(f'하계 명령이 벽시계 예산 {secs}s 초과 — 중단. {cmd[:80]}') from e
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


def run_typed(path):
    """CLI 타입경계 — main() 의 엔진 예외를 *이유코드*로 번역해 exit code 를 돌려준다.

    FIX-A(2026-07-15): CLI 'cycle' verb 는 main() 을 직접 불러 BuildFailed/ScoringRefused/
    BashTimeout 이 생 스택트레이스로 터졌다 — 그것도 mcp_server 의 run_cycle docstring 이
    "build/judge(bash)가 필요하면 CLI `cycle <spec.json>` 사용" 이라며 bash 사용자를 보내는
    바로 그 표면에서. PROM16 S1: 생 예외는 루프 종단이 될 수 없다(이유코드여야 분기 가능).

    경계는 *감싸는* 것이지 삼키는 게 아니다 — main() 은 그대로 raise 해 라이브러리 호출자의
    예외 계약을 보존한다(타입화는 이 프로세스 종단에서만). 미지 예외는 여기서 삼키지 않고
    그대로 올린다: 무엇인지 모르는 것에 이유코드를 붙이면 그게 거짓말이다(quarantine > 위장).
    """
    try:
        main(path)
    except tuple(TYPED_TERMINALS) as e:
        # isinstance 해석(type(e) 직접조회 아님) — 미래의 하위클래스가 KeyError 로 무타입 종단이 되면
        #   가드가 도로 자멸한다. 첫 매치 = 가장 구체적 등록 클래스.
        reason, klass = next(v for k, v in TYPED_TERMINALS.items() if isinstance(e, k))
        print(json.dumps({'status': reason, 'class': klass, 'detail': str(e)[:200]},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run_typed(sys.argv[1]))
