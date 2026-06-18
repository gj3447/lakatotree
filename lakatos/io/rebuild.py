"""재빌드 자동실행 — RebuildManifest → 하네스 bash 로 ZDF(raw root)서 완성본 실제 재생성.

매니페스트는 "이렇게 재생성하라"는 레시피만 줬다(lineage). 이 모듈이 실제로 실행한다:
  ①env 일치 확인 ②기존 버퍼 무시하고 recipe topo 순서대로 bash 재실행(ZDF→버퍼→완성본)
  ③재생성된 완성본 metric 을 기록값과 대조(float 파이프라인 tolerance) → rebuildable
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
        # ② 버퍼 무시하고 recipe topo 재실행
        last_out = None
        trace = []
        for step in manifest.recipe:
            out, code = self._bash(cmd_for(step))
            self._ev('step_exec', output=step['output'], producer=step['producer'], exit_code=code)
            if code != 0:
                self._ev('rebuild_verdict', verdict='step_failed', cid=self._cid)
                return RebuildResult('step_failed', None, recorded_metric, False, trace)
            last_out = out
        # ③ 재생성 완성본 metric 대조
        regen = _parse_metric(last_out or '')
        within = regen is not None and abs(regen - recorded_metric) <= tol
        self._ev('metric_compare', regenerated=regen, recorded=recorded_metric,
                 tolerance=tol, within=within)
        verdict = 'rebuildable' if within else 'metric_mismatch'
        self._ev('rebuild_verdict', verdict=verdict, cid=self._cid)
        return RebuildResult(verdict, regen, recorded_metric, within, trace)
