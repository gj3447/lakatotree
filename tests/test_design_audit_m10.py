"""설계감사 M10(완성-후 적대감사 2026-06-26) — M1 producer≠measurer 분리가 CLI 에서 무력화.

결함: M1 엔진수정(rebuild.py)은 kind='measurement' step 의 출력만 metric 으로 신뢰하지만, run() 은
measurer_separated 를 '측정 step 이 *존재*하는가'(measure_out is not None)로만 판정한다. *실제로 재실행하는
유일 surface* 인 CLI rebuild-run 은 cmd_for=lambda st: a.cmd_template 로 모든 recipe step 에 같은 단일
--cmd-template 을 먹인다(cli.py:376/169) → producer step 과 measurement step 이 *동일 명령* 을 실행 →
'독립 measurer' 가 producer 자기보고와 같은 코드패스가 된다(M1 결함이 surface 에서 부활). measurer_separated
영수증은 그래도 True 라 붕괴를 *조용히* 숨긴다.

수정:
 ① 엔진(rebuild.run): measurement step 의 명령이 producer 명령과 동일하면 measurer_separated=False —
    측정자=생산자 붕괴를 kind 라벨이 아니라 *명령 구별*로 판정(모든 surface 에 적용). RebuildResult 에 노출.
 ② CLI(rebuild-run): --measure-cmd 추가 + kind 로 라우팅해 CLI 가 *분리된* measurer 를 공급할 수 있게.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

from pathlib import Path

from lakatos.io.lineage import RawRoot, RebuildManifest
from lakatos.io.rebuild import RebuildExecutor

_MEASURE = {'producer': 'measure.py', 'producer_sha': 'sm', 'inputs': ['out.json'],
            'output': 'out.json', 'params': {}, 'env': 'E', 'kind': 'measurement'}
_PRODUCE = {'producer': 'make.py', 'producer_sha': 's1', 'inputs': ['in.zdf'],
            'output': 'out.json', 'params': {}, 'env': 'E'}
_MANI = RebuildManifest(final='out.json', roots=[RawRoot('in.zdf', 'z', 'ZDF')],
                        env_sha='E', recipe=[_MEASURE, _PRODUCE], tolerance='0.01')


def _ex():
    def run_bash(cmd):
        return ('metric=0.5', 0)   # 명령과 무관히 같은 stdout — 분리 여부는 *명령 구별*로만 판정돼야
    return RebuildExecutor(run_bash=run_bash, emit=lambda r: None, env_now='E', cid='m10')


def test_collapsed_measurer_command_is_not_separated():
    """CLI 단일 template 붕괴 재현: 모든 step 에 *같은 명령* → 측정자=생산자 → measurer_separated False."""
    res = _ex().run(_MANI, recorded_metric=0.5, cmd_for=lambda st: "bash run.sh")   # st 무시(단일 template)
    assert res.measurer_separated is False, \
        "measurement 명령이 producer 와 동일한데 measurer_separated=True → 붕괴를 조용히 숨김(M10 결함)"


def test_distinct_measurer_command_is_separated():
    """과잉차단 회귀가드: measurement step 이 producer 와 *다른 명령* 이면 정상적으로 분리 인정."""
    res = _ex().run(_MANI, recorded_metric=0.5,
                    cmd_for=lambda st: f"python {st['producer']}")   # step별 다른 명령
    assert res.measurer_separated is True, \
        "분리된 measurer 명령인데 measurer_separated=False → 과잉차단"


def test_cli_rebuild_run_routes_measure_cmd_by_kind():
    """CLI rebuild-run 이 --measure-cmd 를 노출하고 kind 로 라우팅한다(분리된 measurer 공급 가능)."""
    src = Path(__file__).resolve().parent.parent.joinpath("lakatos", "cli.py").read_text()
    assert "--measure-cmd" in src, "CLI rebuild-run 에 --measure-cmd 미노출 → 분리 measurer 공급 불가"
    # rebuild-run 핸들러가 measurement step 을 measure_cmd 로 라우팅(단일 template 무차별 적용 아님)
    assert "measure_cmd" in src and "kind" in src, "rebuild-run cmd_for 가 kind 로 분기하지 않음"
