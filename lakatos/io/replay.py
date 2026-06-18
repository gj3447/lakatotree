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
