"""환경 지문 TDD — 같은 ZDF+코드라도 환경 다르면 결과 다르다(재현성 마지막 조각).
# KG: span_lakatotree_envfp
"""
from lakatos.envfp import environment_fingerprint, fingerprint_sha, env_matches

PROBE = dict(python='3.13.0', platform='Linux-x86_64',
             packages={'numpy': '2.1.0', 'scipy': '1.14.0'},
             env_vars={'OMP_NUM_THREADS': '8'}, tools={'zivid': '2.17.2'})

def test_fingerprint_deterministic():
    a = fingerprint_sha(environment_fingerprint(PROBE))
    b = fingerprint_sha(environment_fingerprint(PROBE))
    assert a == b and len(a) == 64

def test_package_version_change_shifts_sha():
    # numpy 버전 바뀌면 지문 바뀜 (float 결과 영향)
    p2 = {**PROBE, 'packages': {'numpy': '2.2.0', 'scipy': '1.14.0'}}
    assert fingerprint_sha(environment_fingerprint(PROBE)) != fingerprint_sha(environment_fingerprint(p2))

def test_env_matches():
    sha = fingerprint_sha(environment_fingerprint(PROBE))
    assert env_matches(sha, environment_fingerprint(PROBE))
    p2 = {**PROBE, 'python': '3.12.0'}
    assert not env_matches(sha, environment_fingerprint(p2))

def test_real_fingerprint_has_keys():
    fp = environment_fingerprint()   # 실제 환경 (probe 없이)
    assert 'python' in fp and 'platform' in fp and 'packages' in fp
