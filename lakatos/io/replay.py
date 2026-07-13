"""계보 재현 게이트 — io 계층 (engine 에서 분리, 2026-06-18 strict-layers).

LineageReplayGate/Result/ReproducibilityContract 는 io.lineage(DAG)를 *소비*하는 게이트라
engine(foundation) 이 아니라 io 에 속한다. engine→io straddle 제거 → strict layers 성립.
# KG: span_lakatotree_engine
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from lakatos.engine import GateResult
from lakatos.io.lineage import (
    Derivation, by_output, rebuild_plan, reproducibility_gaps, roots, stale_inputs,
)


@dataclass(frozen=True)
class LineageReplayResult(GateResult):
    roots: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    rebuild_plan: tuple[Derivation, ...] = ()
    stale: bool = False
    changed: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = ()
    env_drift: bool = False
    env_changed: tuple[str, ...] = ()   # 환경 지문 바뀐 산출물


class LineageReplayGate:
    """데이터 가지가 source root 에서 다시 만들어질 수 있는지 판정한다."""

    @staticmethod
    def evaluate(
        final_artifact: str,
        derivations: Iterable[Derivation],
        *,
        sources: set[str] | None = None,
        current_shas: dict[str, str] | None = None,
        current_env: str | None = None,
    ) -> LineageReplayResult:
        derivs = list(derivations)
        bo = by_output(derivs)
        if final_artifact not in bo:
            return LineageReplayResult(
                passed=False,
                reasons=("artifact_unrecorded",),
            )

        source_set = sources or {d.output for d in derivs if d.kind == "source"}
        try:
            root_set = roots(final_artifact, bo)
            gaps = reproducibility_gaps(final_artifact, bo, source_set)
            plan = tuple(rebuild_plan(final_artifact, bo))
        except ValueError as exc:
            return LineageReplayResult(
                passed=False,
                reasons=("lineage_cycle", str(exc)),
            )

        changed: list[tuple[str, tuple[tuple[str, str, str], ...]]] = []
        if current_shas is not None:
            for deriv in plan:
                bad = tuple(stale_inputs(deriv, current_shas))
                if bad:
                    changed.append((deriv.output, bad))

        env_changed: list[str] = []
        if current_env is not None:
            for deriv in plan:
                if deriv.env and deriv.env != current_env:
                    env_changed.append(deriv.output)   # 환경 바뀜 → float 결과 달라질 수 있음

        reasons: list[str] = []
        if gaps:
            reasons.append("reproducibility_gaps")
        if changed:
            reasons.append("stale_inputs")
        if env_changed:
            reasons.append("env_drift")
        return LineageReplayResult(
            passed=not reasons,
            reasons=tuple(reasons),
            roots=tuple(sorted(root_set)),
            gaps=tuple(sorted(gaps)),
            rebuild_plan=plan,
            stale=bool(changed),
            changed=tuple(changed),
            env_drift=bool(env_changed),
            env_changed=tuple(env_changed),
        )


@dataclass(frozen=True)
class ReproducibilityContract:
    """프로젝트별 root 데이터에서 final artifact 를 다시 만들 수 있어야 한다."""

    final_artifact: str
    root_artifacts: tuple[str, ...]
    tolerance: str | None = None

    def evaluate(
        self,
        derivations: Iterable[Derivation],
        *,
        current_shas: dict[str, str] | None = None,
        current_env: str | None = None,   # 나생문 F-ARCH-3: env 전달 (계약이 env-blind 였음)
    ) -> LineageReplayResult:
        return LineageReplayGate.evaluate(
            self.final_artifact,
            derivations,
            sources=set(self.root_artifacts),
            current_shas=current_shas,
            current_env=current_env,
        )


# ── Producer replay — 채점 스크립트 *재실행* 으로 client metric_value 검증 (나생문 #1 근본 봉합) ──────
#   LineageReplayGate 는 계보 DAG *모양*(source/staleness/env)을 본다. 그러나 #1 의 forge 는 노드의
#   metric_value 가 서버가 재실행하지 않는 client float 라는 것 — judge 가 그 숫자를 ground truth 로 신뢰한다.
#   producer_replay 는 score_cmd 를 (주입 포트로) 다시 돌려 재생성 metric 이 recorded 와 일치하는지 대조해
#   위조를 끊는다. io/rebuild.RebuildExecutor 가 recipe 전체를 재실행하는 것의 *채점경로 한정* 판(板).
from lakatos.io.rebuild import _parse_metric   # noqa: E402 — 같은 io 층 metric 파서 재사용(DRY)


@dataclass(frozen=True)
class ProducerReplayVerdict:
    """채점 스크립트 재실행 결과. verified: True=외부검증 / False=위조·크래시·metric부재 / None=재실행불가(비차단)."""
    verified: bool | None
    regenerated: float | None
    recorded: float
    reason: str


def producer_replay(*, score_cmd: str | None, recorded_metric: float, run_bash,
                    tolerance: float = 1e-9) -> ProducerReplayVerdict:
    """채점 스크립트를 *재실행*해 client 가 보고한 recorded_metric 을 검증 (나생문 #1 근본 봉합).

    judge 는 결정론적이나 그 입력(metric_value)은 서버가 재실행 안 하던 client float 였다(app.py:395 자인).
    여기서 score_cmd 를 주입된 run_bash 포트((cmd)→(stdout, exit_code))로 다시 돌려 재생성 metric 이
    recorded 와 일치하는지 대조한다 — '영수증은 현실이 끊어준다'를 측정 자체에 적용.

      verified=True  : 재실행 성공 ∧ |regen−recorded|≤tolerance → 측정 외부검증(외부앵커 자격)
      verified=False : 불일치(위조)·exit≠0(크래시, #24 정합)·metric 부재 → 신뢰 불가(forge 적발)
      verified=None  : score_cmd 없음 *또는 CLI 계약 비호환* → 재실행 불가(증명 못 함, *차단 안 함*
                       — reproducible=None 동형)

    CLI 계약 비호환(2026-07-13, consumer_b FalseOK E16/E17 실사에서 발견): 서버 재현명령은
    'python <script> <result_path>'(positional) 형태인데 argparse-only 하네스는 positional 을
    거부한다 — argparse usage-error(exit 2 + 'unrecognized arguments'/'the following arguments
    are required')는 *스코어러가 측정을 시작조차 못 한 것*이지 측정의 반증이 아니다(dead-σ:
    검증 불가 ≠ 반증). 좁은 시그니처만 면제: exit 2 단독·일반 크래시는 여전히 False.

    포트 주입이라 순수/hermetic: 실 실행은 호출자(서버 integration tier)가 sandbox 로 공급한다 — 본 함수는
    *판정 로직*만. (live HTTP 서버가 client 스크립트를 직접 실행하는 것은 보안상 별도 gated 통합 — 미연결.)
    """
    if not score_cmd:
        return ProducerReplayVerdict(verified=None, regenerated=None,
                                     recorded=recorded_metric, reason='no_rerunnable_scorer')
    out, code = run_bash(score_cmd)
    if code != 0:
        if code == 2 and ('unrecognized arguments' in (out or '')
                          or 'the following arguments are required' in (out or '')):
            return ProducerReplayVerdict(verified=None, regenerated=None,
                                         recorded=recorded_metric, reason='cli_contract_incompatible')
        return ProducerReplayVerdict(verified=False, regenerated=None,
                                     recorded=recorded_metric, reason=f'scorer_nonzero_exit:{code}')
    regen = _parse_metric(out)
    if regen is None:
        return ProducerReplayVerdict(verified=False, regenerated=None,
                                     recorded=recorded_metric, reason='no_metric_in_output')
    if abs(regen - recorded_metric) <= tolerance:
        return ProducerReplayVerdict(verified=True, regenerated=regen,
                                     recorded=recorded_metric, reason='externally_verified')
    return ProducerReplayVerdict(verified=False, regenerated=regen,
                                 recorded=recorded_metric, reason='metric_mismatch')
