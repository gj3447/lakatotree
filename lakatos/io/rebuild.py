"""재빌드 자동실행 — RebuildManifest → 하네스 bash 로 ZDF(raw root)서 완성본 실제 재생성.

매니페스트는 "이렇게 재생성하라"는 레시피만 줬다(lineage). 이 모듈이 실제로 실행한다:
  ①env 일치 확인 ②기존 버퍼 무시하고 recipe topo 순서대로 bash 재실행(ZDF→버퍼→완성본)
  ③별개 measurement step(kind='measurement')으로 *완성된 산출물*에서 metric 을 측정해 기록값과
    대조(float 파이프라인 tolerance) → rebuildable
측정자≠생산자(감사 M1): metric 은 producer step 의 self-report stdout 이 아니라, 완성된 산출물만
  input 으로 받는 별개 measurer code path 에서 나온다 — producer 가 거짓 metric=X 를 print 해도
  독립 measurer 가 잡는다(reproducible-builds/reprotest 변주, Bazel/Nix hermetic).
LTDD: 각 단계를 cid 구조화 trace 로 emit(oo) — 로그가 ground truth, "재현됐다"는 주장이 아니라 영수증.
# KG: span_lakatotree_rebuild / q-lkt-rebuild-execute
"""
import re
from dataclasses import dataclass, field


@dataclass
class RebuildResult:
    verdict: str                 # rebuildable | metric_mismatch | env_drift | step_failed
    regenerated_metric: float | None
    recorded_metric: float
    within_tolerance: bool
    trace: list = field(default_factory=list)
    measurer_separated: bool = False   # #M10: metric 출처가 producer 와 *다른 명령* 의 measurer 인가
                                       #   (kind 라벨 존재만이 아니라 명령 구별로 판정 — CLI 단일-template 붕괴 탐지)


def _parse_metric(s):
    m = re.search(r'metric\s*[=:]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', s)  # 과학적 표기 보존(OPS-COR-1)
    return float(m.group(1)) if m else None


class RebuildExecutor:
    """매니페스트를 실제로 실행해 ZDF서 완성본을 재생성하고 metric 을 대조한다."""

    def __init__(self, run_bash, emit=None, env_now=None, cid='rebuild'):
        self._bash = run_bash
        self._emit = emit or (lambda rec: None)
        self._env = env_now
        self._cid = cid

    def _ev(self, event, **attrs):
        # correlation_id/cycle_id 동봉 — oo trace_cycle(cid) 한 콜 RCA 가 실제로 묶이도록 (나생문 F1-cid)
        rec = {'cid': self._cid, 'correlation_id': self._cid, 'cycle_id': self._cid,
               'service': 'lakatotree.rebuild', 'level': 'INFO', 'event': event, **attrs}
        self._emit(rec)
        return rec

    def run(self, manifest, recorded_metric, cmd_for, tolerance=None):
        tol = float(tolerance if tolerance is not None
                    else (manifest.tolerance or 0.0) if isinstance(manifest.tolerance, str)
                    else (manifest.tolerance or 0.0))
        self._ev('rebuild_start', final=manifest.final, n_roots=len(manifest.roots),
                 n_steps=len(manifest.recipe), env_sha=manifest.env_sha)
        # ① env 일치 (재현의 마지막 조각)
        env_ok = (self._env is None) or (manifest.env_sha == self._env)
        self._ev('env_check', recorded_env=manifest.env_sha, current_env=self._env, match=env_ok)
        if not env_ok:
            v = self._ev('rebuild_verdict', verdict='env_drift', cid=self._cid)
            return RebuildResult('env_drift', None, recorded_metric, False, [v])
        # ② 버퍼 무시하고 recipe topo 재실행.
        #    measurement step(kind='measurement')과 producer step 을 분리해 출력을 따로 보관한다.
        #    measurer 의 stdout 만 metric 으로 신뢰한다 — producer self-report 는 신뢰하지 않는다(감사 M1).
        last_producer_out = None     # 호환: measurement step 이 없을 때만 fallback (정직히 표시)
        measure_out = None           # 별개 measurer code path 의 출력 (산출물에서 측정한 참값)
        measure_cmd = None           # measurement step 의 실제 명령 (producer 명령과 구별돼야 분리)
        producer_cmds = set()        # producer step 들이 실행한 명령 집합
        trace = []
        for step in manifest.recipe:
            is_measure = step.get('kind') == 'measurement'
            cmd = cmd_for(step)
            out, code = self._bash(cmd)
            self._ev('step_exec', output=step['output'], producer=step['producer'],
                     exit_code=code, kind=step.get('kind', 'intermediate'))
            if code != 0:
                self._ev('rebuild_verdict', verdict='step_failed', cid=self._cid)
                return RebuildResult('step_failed', None, recorded_metric, False, trace)
            if is_measure:
                measure_out = out    # measurer(producer 와 다른 code path)가 완성본서 측정
                measure_cmd = cmd
            else:
                last_producer_out = out
                producer_cmds.add(cmd)
        # ③ metric 출처를 정직히 선택: measurement step 이 있으면 *그 measurer* 의 출력만 쓴다.
        #    #M10 (설계감사 2026-06-26): 분리 판정을 kind 라벨 *존재* 가 아니라 *명령 구별* 로 — measurement
        #    step 의 명령이 producer 명령과 동일하면(CLI 단일 --cmd-template 가 모든 step 에 같은 cmd 를
        #    먹이던 붕괴) 측정자=생산자라 독립 measurer 가 아니다 → measurer_separated=False(붕괴를 영수증에
        #    숨기지 않는다). 분리 안 됐으면 producer self-report fallback 을 쓰되 플래그로 명시.
        measurer_separated = measure_out is not None and measure_cmd not in producer_cmds
        source_out = measure_out if measurer_separated else last_producer_out
        regen = _parse_metric(source_out or '')
        within = regen is not None and abs(regen - recorded_metric) <= tol
        self._ev('metric_compare', regenerated=regen, recorded=recorded_metric,
                 tolerance=tol, within=within, measurer_separated=measurer_separated)
        verdict = 'rebuildable' if within else 'metric_mismatch'
        self._ev('rebuild_verdict', verdict=verdict, cid=self._cid)
        return RebuildResult(verdict, regen, recorded_metric, within, trace, measurer_separated)
