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
                 human_critiques=[('doubt:h1', 'v7', 'human:user', 'doubt', '진짜 엮였나')])


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


# ── 바인딩 owner+test 메움: harness phase 6개 (각 realm/step 독립) ──────────────
def test_upper_internet_phase_isolated():
    h, calls = make_harness()
    evidence, trust = h._upper_internet(SPEC)
    assert len(evidence) == 1 and trust == 0.9 and ('internet', SPEC.internet_sources[0][0]) in calls


def test_register_node_phase_posts_node_and_prediction():
    h, calls = make_harness()
    h._register_node(SPEC)
    paths = [p for _, p in calls]
    assert any(p.endswith('/node') for p in paths) and any(p.endswith('/prediction') for p in paths)


def test_build_gate_phase_pass_and_fail():
    assert make_harness(build_exit=0)[0]._build_gate(SPEC)['exit'] == 0
    with pytest.raises(BuildFailed):
        make_harness(build_exit=1)[0]._build_gate(SPEC)


def test_measure_phase_isolated():
    assert make_harness(judge_out='metric=49')[0]._measure(SPEC) == 49


def test_submit_and_judge_phase_isolated():
    assert make_harness()[0]._submit_and_judge(SPEC, 49, 'sha', 0.9)['verdict'] == 'progressive'


def test_critiques_and_standing_phase_isolated():
    h, calls = make_harness()
    st = h._critiques_and_standing(SPEC)
    assert st['stands'] is True and any(p.endswith('/critique') for _, p in calls)
