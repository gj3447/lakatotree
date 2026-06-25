"""설계감사 M2 guard — run_cycle 의 fail-loud 경계를 채점거부까지 확장한다.

결함(harness.py:83-86 / harness_run.py:24-25): _submit_and_judge 가 서버 응답을 무검사로
반환하고 run_cycle 은 res.get('verdict')만 읽는다. 그래서 서버가 채점을 거부(admissibility
위반 등 404/422/409 → harness_run._http 가 {'error': code} dict 반환)하거나 verdict 가
생성조차 안 됐는데도 사이클이 exit 0(green) + stands=True 로 끝난다. fail-loud 가 빌드
(BuildFailed)에만 있고 judge 거부엔 없다 — fail-silent 가 default 인 비대칭.

처방(RED-first): 서버 응답에 'error' 키가 있거나 verdict 가 None 이면 ScoringRefused 를
raise(BuildFailed 의 형제). raise 가 default, 삼킴은 명시 정책.
# KG: span_lakatotree_harness
"""
import pytest

from lakatos.harness import LakatoHarness, CycleSpec, ScoringRefused


def _harness(test_result_resp, calls=None):
    """test_result POST 응답만 주입해 바꿔 끼우는 mock 하네스 (test_harness.make_harness 변주)."""
    calls = calls if calls is not None else []

    def run_bash(cmd):
        calls.append(('bash', cmd))
        if 'build' in cmd or 'pytest' in cmd:
            return ('... 49 passed', 0)                  # 하계: TDD/빌드 green
        return ('metric=49', 0)                          # 하계: 채점 스크립트

    def http(method, path, body=None):
        calls.append((method, path))
        if path.endswith('/prediction'):
            return {'ok': True}
        if path.endswith('/test_result'):
            return test_result_resp                      # ← 채점거부/verdict 없음 주입
        if path.endswith('/standing'):
            return {'stands': True, 'grounded_extension': ['verdict:x']}
        return {'ok': True}

    def git_sha():
        return 'abc1234'

    return LakatoHarness(http=http, run_bash=run_bash,
                         read_internet=None, git_sha=git_sha), calls


_SPEC = CycleSpec(tree='T', tag='v7', parent='v6', metric='tests', baseline=34,
                  direction='higher', build_cmd='pytest tests/ -q',
                  judge_cmd='python judges/count.py', judge_script='judges/count.py')


def test_run_cycle_loud_fails_on_judge_reject():
    """서버가 채점을 거부(error 키)하거나 verdict 를 안 내면 run_cycle 이 ScoringRefused 를 raise.

    조용히 삼켜 exit 0(green) + stands=True 로 끝나지 않는다 — fail-loud default.
    """
    # ① 채점거부: harness_run._http 가 HTTPError(422/404/409)를 {'error': code, ...} 로 반환
    h, _ = _harness({'error': 422, 'detail': 'admissibility 위반: novel 독립측정 없음'})
    with pytest.raises(ScoringRefused):
        h.run_cycle(_SPEC)

    # ② verdict 없는 200 응답: 서버가 200 을 줬어도 verdict 가 생성 안 됐으면 채점 미성립
    h2, _ = _harness({'ok': True, 'novel': None, 'delta': None})  # verdict 키 부재 = None
    with pytest.raises(ScoringRefused):
        h2.run_cycle(_SPEC)

    # ③ verdict=None 명시 응답도 동일하게 raise
    h3, _ = _harness({'ok': True, 'verdict': None})
    with pytest.raises(ScoringRefused):
        h3.run_cycle(_SPEC)
