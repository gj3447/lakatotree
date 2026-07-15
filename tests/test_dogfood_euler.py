"""Euler 다면체 프로그램 도그푸드 가드 — 엔진이 verdict 를 *생성*하는지(손입력 아님) 회귀 검증.

핵심 주장: 설치 패키지의 lakatos.demos.euler 는 verdict 를 손입력하지 않는다 — judge()/
appraise_response()/dialectical_verdict() 가 사전등록 예측 + 정수 측정에서 verdict 를 생성한다.
examples/euler_polyhedron_programme.py 는 기존 소비자를 위한 얇은 호환 wrapper 다.
이전 도그푸드(bpc_icp 등)의 `_n(verdict=...)` 손입력 decoration 과 대비.
# KG: span_lakatotree_euler_dogfood
"""
import fnmatch
import pathlib
import subprocess
import sys
import tomllib
from dataclasses import fields, replace

from lakatos.verdict.judge import judge
from lakatos.demos.euler import (
    NODES, EulerNode, closed_orientable_euler_characteristic, run,
    scored_measured, scored_novel_measured,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_handfed_verdicts_in_node_schema():
    # EulerNode 에 verdict 필드 자체가 없다 — 손입력 불가능(구조적 보장)
    names = {f.name for f in fields(EulerNode)}
    assert "verdict" not in names
    assert "metric_verdict" not in names


def test_packaged_module_main_matches_compatibility_script():
    """`python -m` is runnable and preserves the historical example output."""
    packaged = subprocess.run(
        [sys.executable, "-m", "lakatos.demos.euler"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    compatibility = subprocess.run(
        [sys.executable, "examples/euler_polyhedron_programme.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert packaged.stderr == ""
    assert packaged.stdout == compatibility.stdout
    assert len(packaged.stdout.splitlines()) == len(NODES) == 5
    assert packaged.stdout.splitlines()[-1].endswith("→ progressive")


def test_demo_package_is_selected_for_wheel_discovery():
    """Wheel discovery and the public console command point at the packaged demo."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert any(fnmatch.fnmatchcase("lakatos.demos", pattern) for pattern in patterns)
    assert config["project"]["scripts"]["lakatotree-demo"] == "lakatos.demos.euler:main"
    assert (ROOT / "lakatos/demos/__init__.py").is_file()
    assert (ROOT / "lakatos/demos/euler.py").is_file()


def test_compatibility_wrapper_reexports_canonical_objects():
    """Old imports resolve to the packaged implementation, not a divergent copy."""
    from examples.euler_polyhedron_programme import (
        NODES as legacy_nodes,
        EulerNode as LegacyEulerNode,
        run as legacy_run,
    )

    assert legacy_nodes is NODES
    assert LegacyEulerNode is EulerNode
    assert legacy_run is run


def test_judge_generates_each_metric_verdict_deterministically():
    # run() 의 metric_verdict 가 judge() 직접 재호출과 정확히 일치(엔진 생성 + 결정론)
    by_tag = {n.tag: n for n in NODES}
    for r in run():
        n = by_tag[r["tag"]]
        if n.prediction is None:
            assert r["metric_verdict"] is None       # admin root
            continue
        # run() 과 동일하게 토폴로지-파생 채점입력으로 재호출(빠뜨리면 progressive→partial 달라짐)
        regen = judge(n.prediction, scored_measured(n), n.novel_target, scored_novel_measured(n))
        assert regen.verdict == r["metric_verdict"]


def test_euler_characteristics_are_exact_integers():
    # V−E+F 는 위상 불변량(정수) — 부동소수 흔들림 0
    by_tag = {n.tag: n for n in NODES}
    assert by_tag["convex_conjecture"].euler_characteristic == 2     # 정육면체
    assert by_tag["hollow_cube"].euler_characteristic == 4           # 전역 반례
    assert by_tag["proofs_refutations"].euler_characteristic == 0    # 토러스(genus 1)


def test_mature_formula_absorbs_the_hollow_cube_counterexample():
    """The generalization must explain χ=4, not merely fit an unrelated torus."""
    by_tag = {n.tag: n for n in NODES}
    hollow = by_tag["hollow_cube"]
    torus = by_tag["proofs_refutations"]

    assert (hollow.components, hollow.genus_sum) == (2, 0)
    assert hollow.classified_euler_characteristic == hollow.euler_characteristic == 4
    assert closed_orientable_euler_characteristic(2, 0) == 4
    assert (torus.components, torus.genus_sum) == (1, 1)
    assert torus.classified_euler_characteristic == torus.euler_characteristic == 0
    assert "2c" in torus.proof_generated_concept.name
    assert "성분 2개" in torus.proof_generated_concept.incorporated_lemma


def test_hollow_cube_is_refuted_by_engine():
    r = next(x for x in run() if x["tag"] == "hollow_cube")
    assert r["metric_verdict"] == "rejected"     # χ=4≠2 → judge 가 반증 생성
    assert r["euler_char"] == 4


def test_monster_and_exception_barring_degenerate_via_dialectic():
    # 메트릭은 partial(오차 감소)이나 변증법이 '안 배움'으로 강등 → degenerating
    res = {x["tag"]: x for x in run()}
    for tag in ("monster_barring", "exception_barring"):
        assert res[tag]["metric_verdict"] == "partial"        # judge: 개선되나 novel 없음
        assert res[tag]["pnr_verdict"] == "degenerating"      # 변증법: 안 배움
        assert res[tag]["verdict"] == "degenerating"          # 합성: dialectic_overrides


def test_proofs_and_refutations_is_progressive_via_pnr():
    r = next(x for x in run() if x["tag"] == "proofs_refutations")
    assert r["metric_verdict"] == "progressive"               # judge: 개선 + 새 사실(토러스 χ=0) 적중
    assert r["pnr_verdict"] == "progressive"                  # PnR 성숙(증명-생성 개념)
    assert r["verdict"] == "progressive"
    assert "+pnr_progressive" in r["dialectic_status"]        # substring(상태 합성, 정확일치 아님)


def test_scoring_input_is_derived_from_topology_not_handset():
    # ★채점 입력(measured)은 손입력 상수가 아니라 V,E,F 에서 파생 — 토폴로지가 verdict 를 몬다
    by_tag = {n.tag: n for n in NODES}
    hollow = by_tag["hollow_cube"]
    assert hollow.measured is None                       # 노드에 손입력 상수 없음
    assert scored_measured(hollow) == abs(hollow.euler_characteristic - 2) == 2.0
    torus = by_tag["proofs_refutations"]
    assert torus.measured is None
    assert scored_measured(torus) == 0.0
    assert torus.novel_measured is None
    assert scored_novel_measured(torus) == float(torus.euler_characteristic) == 0.0


def test_mutating_VEF_changes_engine_verdict():
    # 토폴로지를 바꾸면 verdict 가 따라온다(채점입력이 χ 에 묶임): 속빈정육면체를 볼록(χ=2)으로
    # 만들면 결함 0 → 더는 rejected 아님(반증 사라짐).
    hollow = next(n for n in NODES if n.tag == "hollow_cube")
    as_convex = replace(hollow, V=8, E=12, F=6)          # χ=2 → 결함 |2−2|=0
    v_refuted = judge(hollow.prediction, scored_measured(hollow))
    v_convex = judge(as_convex.prediction, scored_measured(as_convex))
    assert v_refuted.verdict == "rejected"               # χ=4 → 반증
    assert v_convex.verdict != "rejected"                # χ=2 → 반증 아님(토폴로지가 결정)


def test_counterexample_note_exercised_hidden_lemma():
    # GLOBAL_NOT_LOCAL = 숨은 보조정리 신호 → _counterexample_note 가 발화돼 진단에 동봉
    r = next(x for x in run() if x["tag"] == "proofs_refutations")
    joined = " ".join(r["pnr_reasons"])
    assert "보조정리" in joined or "lemma" in joined.lower()
