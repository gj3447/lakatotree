"""Euler's polyhedron conjecture as a packaged LakatoTree demonstration.

The scored nodes never carry a hand-written verdict. Each contains an in-process
``Prediction``; topology data and Proofs-and-Refutations responses are attached
where the historical scenario supplies them. ``run()`` derives the result through
``judge`` -> ``appraise_response`` -> ``dialectical_verdict``. This demonstrates
the pure scoring contract, not the service's timestamped registration lock.

Run this module from an installed package with::

    python -m lakatos.demos.euler

The programme follows the historical arc from ``V-E+F=2`` through a global
counterexample, monster/exception barring, and the progressive generalization
``V-E+F=2c-2Σg_i`` for ``c`` closed orientable connected components.

Mathematical scope: the connected formula ``χ=2-2g`` is the classification of
closed oriented surfaces (Danny Calegari, *Introduction to Knot Theory*,
Theorem 2.8); additivity under disjoint union yields the ``c``-component form.
The source notes are published at https://math.uchicago.edu/~dannyc/notes/.

# KG: span_lakatotree_euler_dogfood
"""
from __future__ import annotations

from dataclasses import dataclass

from lakatos.verdict.judge import NovelTarget, Prediction, judge
from lakatos.verdict.pnr import (
    CounterexampleType,
    ProofGeneratedConcept,
    Response,
    appraise_response,
)
from lakatos.verdict.spine import dialectical_verdict


def closed_orientable_euler_characteristic(components: int, genus_sum: int) -> int:
    """Return ``2c-2Σg_i`` for closed orientable surface components."""
    if components < 1:
        raise ValueError("components must be positive")
    if genus_sum < 0:
        raise ValueError("genus_sum must be non-negative")
    return 2 * components - 2 * genus_sum


@dataclass(frozen=True)
class EulerNode:
    """One programme node; deliberately has no verdict field."""

    tag: str
    parent: str | None
    story: str
    V: int | None = None
    E: int | None = None
    F: int | None = None
    components: int | None = None
    genus_sum: int | None = None
    prediction: Prediction | None = None
    measured: float | None = None
    novel_target: NovelTarget | None = None
    novel_measured: float | None = None
    response: Response | None = None
    excess_content: bool = False
    in_heuristic_spirit: bool | None = None
    proof_generated_concept: ProofGeneratedConcept | None = None
    counterexample_type: CounterexampleType | None = None
    hard_core_preserved: bool = True

    @property
    def euler_characteristic(self) -> int | None:
        """Return the exact integer Euler characteristic ``V-E+F``."""
        if self.V is None or self.E is None or self.F is None:
            return None
        return self.V - self.E + self.F

    @property
    def classified_euler_characteristic(self) -> int | None:
        """Return the surface-classification prediction when its inputs exist."""
        if self.components is None or self.genus_sum is None:
            return None
        return closed_orientable_euler_characteristic(self.components, self.genus_sum)


_EULER_CHI = ProofGeneratedConcept(
    name="Euler characteristic χ = V−E+F = 2c−2Σgᵢ (closed orientable components)",
    born_from_counterexample="hollow_cube boundary (c=2, Σgᵢ=0, χ=4)",
    incorporated_lemma=(
        "연결성분 수 c와 각 성분의 genus가 χ를 결정한다 — "
        "속빈 정육면체 경계는 genus 1이 아니라 구면형 성분 2개"
    ),
)


NODES: tuple[EulerNode, ...] = (
    EulerNode(
        tag="convex_conjecture",
        parent=None,
        story="코시 증명: 볼록 다면체에서 V−E+F=2 (정육면체 8−12+6=2)",
        V=8,
        E=12,
        F=6,
        components=1,
        genus_sum=0,
    ),
    EulerNode(
        tag="hollow_cube",
        parent="convex_conjecture",
        story=(
            "속빈 정육면체의 바깥·안쪽 경계는 구면형 성분 2개: "
            "16−24+12=4 — 연결성분을 누락한 전역 반례"
        ),
        V=16,
        E=24,
        F=12,
        components=2,
        genus_sum=0,
        prediction=Prediction(
            metric_name="euler_defect",
            direction="lower",
            baseline_value=0.0,
            noise_band=0.0,
            novel_prediction="",
            closes_question="q-hollow-cube",
        ),
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,
    ),
    EulerNode(
        tag="monster_barring",
        parent="hollow_cube",
        story="'속빈 정육면체는 진짜 다면체가 아니다'(개념 재정의로 반례 배제)",
        prediction=Prediction(
            metric_name="model_error",
            direction="lower",
            baseline_value=2.0,
            noise_band=0.0,
            novel_prediction="",
            closes_question="q-hollow-cube",
        ),
        measured=0.0,
        response=Response.MONSTER_BARRING,
        hard_core_preserved=True,
    ),
    EulerNode(
        tag="exception_barring",
        parent="hollow_cube",
        story="'정리는 단순 다면체에서만 성립'(도메인 조각적 축소, 초과내용 없음)",
        prediction=Prediction(
            metric_name="model_error",
            direction="lower",
            baseline_value=2.0,
            noise_band=0.0,
            novel_prediction="",
            closes_question="q-hollow-cube",
        ),
        measured=0.0,
        response=Response.EXCEPTION_BARRING,
        excess_content=False,
        in_heuristic_spirit=False,
        hard_core_preserved=True,
    ),
    EulerNode(
        tag="proofs_refutations",
        parent="hollow_cube",
        story=(
            "성숙 일반화: 닫힌 가향 경계 c개의 χ=2c−2Σgᵢ. "
            "속빈 정육면체(c=2)는 χ=4로 흡수하고 토러스(c=1, g=1) χ=0을 예측·적중"
        ),
        V=16,
        E=32,
        F=16,
        components=1,
        genus_sum=1,
        prediction=Prediction(
            metric_name="model_error",
            direction="lower",
            baseline_value=2.0,
            noise_band=0.0,
            novel_prediction="연결된 genus-1 닫힌 가향 표면 V−E+F=0",
            closes_question="q-generalize-euler",
        ),
        novel_target=NovelTarget(
            metric_name="torus_euler_char",
            direction="lower",
            threshold=0.0,
        ),
        response=Response.PROOFS_AND_REFUTATIONS,
        excess_content=True,
        in_heuristic_spirit=True,
        proof_generated_concept=_EULER_CHI,
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,
        hard_core_preserved=True,
    ),
)


def scored_measured(node: EulerNode) -> float | None:
    """Derive the primary scoring input from topology where applicable."""
    if (
        node.prediction is not None
        and node.prediction.metric_name == "euler_defect"
        and node.euler_characteristic is not None
    ):
        return float(abs(node.euler_characteristic - 2))
    if (
        node.prediction is not None
        and node.prediction.metric_name == "model_error"
        and node.euler_characteristic is not None
        and node.classified_euler_characteristic is not None
    ):
        return float(abs(node.euler_characteristic - node.classified_euler_characteristic))
    return node.measured


def scored_novel_measured(node: EulerNode) -> float | None:
    """Derive the novel-target measurement from topology where applicable."""
    if (
        node.novel_target is not None
        and node.novel_target.metric_name == "torus_euler_char"
        and node.euler_characteristic is not None
    ):
        return float(node.euler_characteristic)
    return node.novel_measured


def run() -> list[dict]:
    """Run the programme and return engine-derived results for every node."""
    output: list[dict] = []
    for node in NODES:
        if node.prediction is None:
            # The root is an administrative stage, not a scored verdict.
            output.append(
                dict(
                    tag=node.tag,
                    metric_verdict=None,
                    pnr_verdict=None,
                    dialectic_status="root",
                    verdict="canonical_stage",
                    euler_char=node.euler_characteristic,
                    reasons=(),
                )
            )
            continue

        metric = judge(
            node.prediction,
            scored_measured(node),
            node.novel_target,
            scored_novel_measured(node),
        )
        appraisal = None
        if node.response is not None:
            appraisal = appraise_response(
                node.response,
                excess_content=node.excess_content,
                novel_corroborated=metric.novel,
                in_heuristic_spirit=node.in_heuristic_spirit,
                hard_core_preserved=node.hard_core_preserved,
                proof_generated_concept=node.proof_generated_concept,
                counterexample_type=node.counterexample_type,
            )
        final = dialectical_verdict(metric.verdict, appraisal, lakatos_result=None)
        output.append(
            dict(
                tag=node.tag,
                metric_verdict=metric.verdict,
                pnr_verdict=appraisal.verdict if appraisal else None,
                pnr_reasons=tuple(appraisal.reasons) if appraisal else (),
                dialectic_status=final["status"],
                verdict=final["verdict"],
                euler_char=node.euler_characteristic,
                reasons=tuple(final.get("reasons", ())),
            )
        )
    return output


def main() -> None:
    """Print the stable, human-readable demonstration output."""
    for result in run():
        print(
            f"{result['tag']:20} χ={str(result['euler_char']):>4}  "
            f"metric={str(result['metric_verdict']):>11}  "
            f"pnr={str(result['pnr_verdict']):>14}  → {result['verdict']}"
        )


if __name__ == "__main__":
    main()
