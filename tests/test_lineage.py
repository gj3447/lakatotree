"""데이터 계보 TDD — 버퍼는 임시, 완성본은 root data 서 재생성.
# KG: span_lakatotree_lineage
"""
import json
import pytest
from lakatos.lineage import (
    DatasetManifest,
    Derivation,
    EnvironmentFingerprint,
    by_output,
    dataset_manifest_from_derivations,
    fingerprint_environment,
    is_reproducible,
    load_dataset_manifest,
    manifest_to_dict,
    rebuild_plan,
    reproducibility_gaps,
    roots,
    stale_inputs,
    verify_dataset_manifest,
)

# root(source) → cache(buffer) → final
ROOT = Derivation(output='raw://experiment/lot-0060', output_sha='raw0', producer='', producer_sha='',
                  inputs=[], params={}, kind='source', ts='t0')
CACHE = Derivation(output='cache://observations-0060', output_sha='cache0',
                   producer='extract_observations.py', producer_sha='sha-extract',
                   inputs=[('raw://experiment/lot-0060', 'raw0')],
                   params={'stride': 2}, kind='intermediate', ts='t1')
FINAL = Derivation(output='artifact://model-v22', output_sha='model0',
                   producer='solve_model.py', producer_sha='sha-solve',
                   inputs=[('cache://observations-0060', 'cache0')],
                   params={'lots': 6}, kind='final', ts='t2')

def test_roots_trace_to_root_data():
    bo = by_output([ROOT, CACHE, FINAL])
    assert roots('artifact://model-v22', bo) == {'raw://experiment/lot-0060'}

def test_rebuild_plan_topo_order():
    bo = by_output([ROOT, CACHE, FINAL])
    plan = rebuild_plan('artifact://model-v22', bo)
    outs = [d.output for d in plan]
    assert outs.index('cache://observations-0060') < outs.index('artifact://model-v22')
    assert 'raw://experiment/lot-0060' not in outs   # source 는 재생성 안 함

def test_reproducibility_gap_when_link_missing():
    # 버퍼 derivation 없으면 완성본 재생성 불가 (계보 끊김)
    bo = by_output([ROOT, FINAL])   # CACHE 누락
    gaps = reproducibility_gaps('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})
    assert 'cache://observations-0060' in gaps
    assert not is_reproducible('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})

def test_full_chain_reproducible():
    bo = by_output([ROOT, CACHE, FINAL])
    assert is_reproducible('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})

def test_stale_when_input_changed():
    # root data 가 바뀌면(sha 변경) 하류 버퍼가 stale → 완성본 재생성 필요
    bo = by_output([ROOT, CACHE, FINAL])
    bad = stale_inputs(CACHE, current_shas={'raw://experiment/lot-0060': 'raw_NEW'})
    assert bad and bad[0][0] == 'raw://experiment/lot-0060'
    assert not stale_inputs(CACHE, current_shas={'raw://experiment/lot-0060': 'raw0'})

def test_cycle_guard():
    a = Derivation('a', 'a0', 'p', 'sp', [('b', 'b0')], {}, 'intermediate', 't')
    b = Derivation('b', 'b0', 'p', 'sp', [('a', 'a0')], {}, 'intermediate', 't')
    with pytest.raises(ValueError):
        rebuild_plan('a', by_output([a, b]))


# === 스크립트 버전 이력 (생산 코드도 중간에 바뀐다) ===
def test_script_history_tracks_versions():
    from lakatos.lineage import script_history
    # 생산 스크립트가 수정되면 각 버전이 만든 산출물을 시간순으로 추적
    ds = [
        Derivation('cache://run-A', 'rA', 'extract.py', 'sha_v1', [('raw://lot','raw0')], {}, 'intermediate', 't1'),
        Derivation('cache://run-B', 'rB', 'extract.py', 'sha_v1', [('raw://lot','raw0')], {}, 'intermediate', 't2'),
        Derivation('cache://run-C', 'rC', 'extract.py', 'sha_v2', [('raw://lot','raw0')], {}, 'intermediate', 't3'),
    ]
    h = script_history(ds, 'extract.py')
    assert len(h) == 2                          # 2개 버전
    assert h[0]['sha'] == 'sha_v1' and set(h[0]['outputs']) == {'cache://run-A', 'cache://run-B'}
    assert h[1]['sha'] == 'sha_v2' and h[1]['outputs'] == ['cache://run-C']
    assert h[0]['first_seen'] < h[1]['first_seen']   # 시간순

def test_script_history_empty():
    from lakatos.lineage import script_history
    assert script_history([], 'x.py') == []


def test_dataset_manifest_groups_roots_environment_and_rebuild_plan():
    env = EnvironmentFingerprint(
        python="3.12.0",
        platform="linux-x86_64",
        package_locks={"requirements.txt": "locksha"},
        env_vars={"CUDA_VISIBLE_DEVICES": "0"},
        tool_versions={"zivid": "2.14"},
    )

    manifest = dataset_manifest_from_derivations(
        "artifact://model-v22",
        [ROOT, CACHE, FINAL],
        environment=env,
        metadata={"project": "bpc"},
    )

    assert manifest.schema_version == "lakatotree.dataset-manifest.v1"
    assert manifest.root_artifacts == ("raw://experiment/lot-0060",)
    assert [d.output for d in manifest.rebuild_plan()] == [
        "cache://observations-0060",
        "artifact://model-v22",
    ]
    as_dict = manifest_to_dict(manifest)
    assert as_dict["environment"]["package_locks"]["requirements.txt"] == "locksha"
    assert as_dict["metadata"]["project"] == "bpc"


def test_verify_dataset_manifest_blocks_gaps_stale_and_root_mismatch():
    good = dataset_manifest_from_derivations(
        "artifact://model-v22",
        [ROOT, CACHE, FINAL],
        environment=EnvironmentFingerprint(python="3.12.0"),
    )
    missing_cache = DatasetManifest(
        final_artifact="artifact://model-v22",
        root_artifacts=("raw://experiment/lot-0060",),
        derivations=(ROOT, FINAL),
        environment=EnvironmentFingerprint(python="3.12.0"),
    )
    wrong_root = DatasetManifest(
        final_artifact="artifact://model-v22",
        root_artifacts=("raw://other-lot",),
        derivations=(ROOT, CACHE, FINAL),
        environment=EnvironmentFingerprint(python="3.12.0"),
    )

    ok = verify_dataset_manifest(good, current_shas={"raw://experiment/lot-0060": "raw0"})
    gap = verify_dataset_manifest(missing_cache)
    stale = verify_dataset_manifest(good, current_shas={"raw://experiment/lot-0060": "rawNEW"})
    mismatch = verify_dataset_manifest(wrong_root)

    assert ok.passed
    assert not gap.passed and "reproducibility_gaps" in gap.reasons
    assert not stale.passed and stale.stale
    assert not mismatch.passed and "root_manifest_mismatch" in mismatch.reasons


def test_verify_dataset_manifest_requires_environment_when_enabled():
    manifest = DatasetManifest(
        final_artifact="artifact://model-v22",
        root_artifacts=("raw://experiment/lot-0060",),
        derivations=(ROOT, CACHE, FINAL),
    )

    result = verify_dataset_manifest(manifest, require_environment=True)

    assert not result.passed
    assert "environment_fingerprint_missing" in result.reasons


def test_dataset_manifest_json_round_trip(tmp_path):
    manifest = dataset_manifest_from_derivations(
        "artifact://model-v22",
        [ROOT, CACHE, FINAL],
        environment=EnvironmentFingerprint(python="3.12.0"),
    )
    manifest.derivations[1].env = "env-sha"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")

    loaded = load_dataset_manifest(path)
    result = verify_dataset_manifest(loaded)

    assert loaded.final_artifact == "artifact://model-v22"
    assert loaded.derivations[1].params == {"stride": 2}
    assert loaded.derivations[1].env == "env-sha"
    assert result.passed


def test_fingerprint_environment_hashes_lock_files_and_selected_env(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("pytest==8\n", encoding="utf-8")

    fp = fingerprint_environment(
        package_lock_paths=[lock],
        env_vars=["CUDA_VISIBLE_DEVICES", "MISSING_ENV"],
        environ={"CUDA_VISIBLE_DEVICES": "0"},
        tool_versions={"halcon": "24.11"},
    )

    assert fp.python
    assert fp.platform
    assert fp.package_locks[str(lock)]
    assert fp.env_vars == {"CUDA_VISIBLE_DEVICES": "0"}
    assert fp.tool_versions["halcon"] == "24.11"


def test_reproducibility_gaps_and_plan_consistent_on_cycle():
    # ENGINE-ROB-3: 사이클 = 재현불가(gap) 로 일관 + rebuild_plan 은 ValueError, 둘이 안 어긋남
    from lakatos.lineage import (reproducibility_gaps, is_reproducible, rebuild_plan,
                                 Derivation, by_output)
    import pytest
    a = Derivation('a', 'sa', 'p', 'ps', [('b', 'sb')], kind='final')
    b = Derivation('b', 'sb', 'p', 'ps', [('a', 'sa')], kind='intermediate')
    bo = by_output([a, b])
    assert reproducibility_gaps('a', bo, set())            # 사이클 → 갭(전엔 빈 set=재현가능 오보)
    assert is_reproducible('a', bo, set()) is False        # rebuild_plan(아래)과 일관
    with pytest.raises(ValueError):
        rebuild_plan('a', bo)                              # 사이클은 topo 불가
