"""라카토트리 하네스 TDD — 상계(인터넷)·하계(bash/KG/git)·인간·agent 를 한 사이클로 엮는다.
포트(주입)로 테스트: 모든 계의 호출이 일어나고 ground-truth 게이트가 작동하는가.
# KG: span_lakatotree_harness
"""
import pytest
from lakatos.harness import LakatoHarness, CycleSpec, BuildFailed


def make_harness(build_exit=0, judge_out='metric=49', calls=None):
    calls = calls if calls is not None else []
    def run_bash(cmd):
        calls.append(('bash', cmd))
        if 'build' in cmd or 'pytest' in cmd:
            return ('... 49 passed', build_exit)        # 하계: TDD/빌드
        return (judge_out, 0)                            # 하계: 채점 스크립트
    def http(method, path, body=None):
        calls.append((method, path))
        if path.endswith('/prediction'):
            return {'ok': True}
        if path.endswith('/test_result'):
            return {'ok': True, 'verdict': 'progressive', 'novel': True, 'delta': 15}
        if path.endswith('/standing'):
            return {'stands': True, 'grounded_extension': ['verdict:x']}
        return {'ok': True}
    def read_internet(url, prompt):
        calls.append(('internet', url))
        return ('EigenTrust converges to eigenvector', 0.9)   # 상계: read-only + trust
    def git_sha():
        return 'abc1234'
    return LakatoHarness(http=http, run_bash=run_bash,
                         read_internet=read_internet, git_sha=git_sha), calls


SPEC = CycleSpec(tree='T', tag='v7', parent='v6', metric='tests', baseline=34,
                 direction='higher', novel_metric='tests', novel_direction='higher',
                 novel_threshold=45, build_cmd='pytest tests/ -q',
                 judge_cmd='python judges/count.py', judge_script='judges/count.py',
                 internet_sources=[('https://nlp.stanford.edu/pubs/eigentrust.pdf', None)],
                 human_critiques=[('doubt:h1', 'v7', 'human:kjra', 'doubt', '진짜 엮였나')])


def test_full_weave_all_realms():
    h, calls = make_harness()
    prov = h.run_cycle(SPEC)
    kinds = {c[0] for c in calls}
    assert 'internet' in kinds          # 상계 read
    assert 'bash' in kinds              # 하계 execute
    assert 'POST' in kinds              # 하계 write (KG/DB)
    assert prov['verdict'] == 'progressive'
    assert prov['git_sha'] == 'abc1234'           # 이력관리
    assert prov['standing']['stands'] is True     # 인간/agent 논증
    assert prov['internet_evidence'][0]['trust'] == 0.9   # 상계 신뢰가중
    assert prov['metric'] == 49.0                 # 하계 ground truth 측정


def test_build_failure_aborts_before_judge():
    # 하계 ground truth 게이트: 빌드(TDD) 실패면 채점·판결 안 함
    h, calls = make_harness(build_exit=1)
    with pytest.raises(BuildFailed):
        h.run_cycle(SPEC)
    assert not any(p.endswith('/test_result') for m, p in calls if m == 'POST')


def test_internet_evidence_trust_weighted_into_result():
    # 상계 증거 신뢰가 test_result 의 source_trust 로 흘러간다 (베이즈 결합)
    h, calls = make_harness()
    prov = h.run_cycle(SPEC)
    assert prov['source_trust'] == 0.9   # 인터넷 출처 신뢰 → 판결 증거 가중


def test_no_internet_is_pure_haegye():
    # 인터넷 없이도 동작 (순수 하계 실행만) — source_trust=1.0
    h, calls = make_harness()
    spec2 = CycleSpec(tree='T', tag='v7b', parent='v6', metric='tests', baseline=34,
                      direction='higher', build_cmd='pytest', judge_cmd='python x.py',
                      judge_script='x.py')
    prov = h.run_cycle(spec2)
    assert prov['source_trust'] == 1.0
    assert prov['internet_evidence'] == []
