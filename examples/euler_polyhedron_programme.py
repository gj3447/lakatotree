"""Euler 다면체 추측 V−E+F=2 — Lakatos 『Proofs and Refutations』(1976) 연구 프로그램 도그푸드.

★이 예제의 요점: 노드는 verdict 를 *손입력하지 않는다*. 각 노드는 사전등록 Prediction + 정수
측정값(V,E,F) + 반례 대응(pnr.Response)만 데이터로 들고, `run()` 이 런타임에 엔진을 태워 verdict 를
*생성*한다 — judge()(메트릭) → appraise_response()(증명-반박 변증법) → dialectical_verdict()(합성).
기존 플래그십(bpc_icp_programme 등)이 `_n(verdict='degenerating')` 손입력이라 엔진 생성경로를 안 쓰던
decoration 결함의 교정. 라카토스 자신의 예제로 엔진이 *실제 연구 프로그램을 끝까지 몬다*는 실증.

결정론: V−E+F 는 위상 불변량(Euler characteristic χ) — 해석적 정수지 확률변수가 아니다. 그래서
noise_band=0.0 은 *정확 정수 산술*을 뜻하며(부동소수 흔들림 0), 베이즈 우도 같은 확률 해석이 아니다.

P&R 역사 매핑(코시 증명 → 전역 반례 → monster/exception-barring → 정리-반박 성숙):
  · convex_conjecture   정육면체 8−12+6=2 — 코시 증명, 추측 확립(root)
  · hollow_cube         속빈정육면체 16−24+12=4 — 전역 반례(χ≠2). 추측은 깨는데 어느 증명단계가
                        틀렸는지 불명 → GLOBAL_NOT_LOCAL(숨은 보조정리 신호) → judge rejected
  · monster_barring     "그건 진짜 다면체 아님"(개념 재정의로 반례 배제) — 안 배움 → degenerating
  · exception_barring   "단순 다면체에서만 성립"(도메인 조각적 축소, 초과내용 0) — 안 배움 → degenerating
  · proofs_refutations  푸앵카레 성숙: V−E+F=2−2g(genus). 그림틀 토러스(genus 1) χ=0 을 *새 사실로
                        예측·적중* + 증명-생성 개념(Euler characteristic) 탄생 → progressive
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


@dataclass(frozen=True)
class EulerNode:
    """프로그램의 한 노드. ★verdict 필드 없음 — 엔진이 런타임에 생성한다."""

    tag: str
    parent: str | None
    story: str
    V: int | None = None
    E: int | None = None
    F: int | None = None
    prediction: Prediction | None = None       # 사전등록(없으면 admin root)
    measured: float | None = None              # 실측(데이터 — verdict 아님)
    novel_target: NovelTarget | None = None    # 새 사실 예측(progressive 조건)
    novel_measured: float | None = None
    response: Response | None = None           # 반례 대응(없으면 변증법 미적용)
    excess_content: bool = False
    in_heuristic_spirit: bool | None = None
    proof_generated_concept: ProofGeneratedConcept | None = None
    counterexample_type: CounterexampleType | None = None
    hard_core_preserved: bool = True           # Euler 대화 전체가 *한* 프로그램 안 — 핵 이탈 없음

    @property
    def euler_characteristic(self) -> int | None:
        if self.V is None or self.E is None or self.F is None:
            return None
        return self.V - self.E + self.F        # 위상 불변량 χ (정확 정수)


# 증명-생성 개념(성숙 진보의 표식) — 반례 통합서 *탄생한* 개념
_EULER_CHI = ProofGeneratedConcept(
    name="Euler characteristic χ = V−E+F = 2−2·genus",
    born_from_counterexample="hollow_cube (전역 반례 χ=4)",
    incorporated_lemma="다면체의 genus(구멍 수)가 χ 를 결정한다 — 단순연결성 숨은 보조정리",
)

NODES: tuple[EulerNode, ...] = (
    EulerNode(
        tag="convex_conjecture", parent=None,
        story="코시 증명: 볼록 다면체에서 V−E+F=2 (정육면체 8−12+6=2)",
        V=8, E=12, F=6,            # prediction None → admin root(추측 확립)
    ),
    EulerNode(
        tag="hollow_cube", parent="convex_conjecture",
        story="속빈 정육면체(정육면체 안 정육면체 구멍): 16−24+12=4 — 전역 반례",
        V=16, E=24, F=12,
        # 추측: 결함 |χ−2| 은 0 으로 유지된다 (순진한 추측). 실측 결함=|χ−2|=|4−2|=2 → 반증.
        # ★measured 는 손입력 상수가 아니라 V,E,F 에서 run() 이 파생(토폴로지가 채점입력을 결정).
        prediction=Prediction(metric_name="euler_defect", direction="lower",
                              baseline_value=0.0, noise_band=0.0,
                              novel_prediction="", closes_question="q-hollow-cube"),
        # 추측은 깨는데 어느 증명단계가 틀렸는지 불명 → 숨은 보조정리 신호
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,
    ),
    EulerNode(
        tag="monster_barring", parent="hollow_cube",
        story="'속빈 정육면체는 진짜 다면체가 아니다'(개념 재정의로 반례 배제)",
        prediction=Prediction(metric_name="model_error", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="", closes_question="q-hollow-cube"),
        measured=0.0,              # 배제하면 오차 0 — 그러나 새 예측 없음
        response=Response.MONSTER_BARRING,
        hard_core_preserved=True,
    ),
    EulerNode(
        tag="exception_barring", parent="hollow_cube",
        story="'정리는 단순 다면체에서만 성립'(도메인 조각적 축소, 초과내용 없음)",
        prediction=Prediction(metric_name="model_error", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="", closes_question="q-hollow-cube"),
        measured=0.0,
        response=Response.EXCEPTION_BARRING,
        excess_content=False, in_heuristic_spirit=False,   # 조각적(전략적 후퇴 아님)
        hard_core_preserved=True,
    ),
    EulerNode(
        tag="proofs_refutations", parent="hollow_cube",
        story="푸앵카레 성숙: V−E+F=2−2g. 그림틀 토러스(genus 1) χ=0 을 새 사실로 예측·적중",
        V=16, E=32, F=16,          # 토러스 다면체 16−32+16=0
        # 일반화 모델의 오차가 순진모델(오차 2) 대비 0 으로 감소 + 토러스 χ=0 을 *새로* 예측
        prediction=Prediction(metric_name="model_error", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="genus-1 다면체 V−E+F=0",
                              closes_question="q-generalize-euler"),
        measured=0.0,              # 일반화 모델 오차(개념적: 토러스를 맞히므로 0)
        novel_target=NovelTarget(metric_name="torus_euler_char", direction="lower", threshold=0.0),
        # novel_measured(토러스 χ=0)는 run() 이 V,E,F 에서 파생 — 손입력 아님
        response=Response.PROOFS_AND_REFUTATIONS,
        excess_content=True, in_heuristic_spirit=True,
        proof_generated_concept=_EULER_CHI,
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,   # 숨은 보조정리에 lemma-incorporation
        hard_core_preserved=True,
    ),
)


def scored_measured(n: EulerNode) -> float | None:
    """채점 입력을 *토폴로지에서 파생* — 손입력 상수 금지. euler_defect = |χ−2| (V,E,F 가 결정)."""
    if (n.prediction is not None and n.prediction.metric_name == "euler_defect"
            and n.euler_characteristic is not None):
        return float(abs(n.euler_characteristic - 2))
    return n.measured


def scored_novel_measured(n: EulerNode) -> float | None:
    """새 사실 측정값도 토폴로지서 파생 — 토러스 χ = V−E+F (genus-1 → 0)."""
    if (n.novel_target is not None and n.novel_target.metric_name == "torus_euler_char"
            and n.euler_characteristic is not None):
        return float(n.euler_characteristic)
    return n.novel_measured


def run() -> list[dict]:
    """프로그램을 엔진에 태운다 — 각 노드 verdict 를 judge/pnr/변증법이 *생성*. 손입력 0."""
    out: list[dict] = []
    for n in NODES:
        if n.prediction is None:
            # admin root — 추측 확립(채점 대상 아님)
            out.append(dict(tag=n.tag, metric_verdict=None, pnr_verdict=None,
                            dialectic_status="root", verdict="canonical_stage",
                            euler_char=n.euler_characteristic, reasons=()))
            continue
        mv = judge(n.prediction, scored_measured(n), n.novel_target, scored_novel_measured(n))
        appraisal = None
        if n.response is not None:
            appraisal = appraise_response(
                n.response, excess_content=n.excess_content, novel_corroborated=mv.novel,
                in_heuristic_spirit=n.in_heuristic_spirit,
                hard_core_preserved=n.hard_core_preserved,
                proof_generated_concept=n.proof_generated_concept,
                counterexample_type=n.counterexample_type)
        final = dialectical_verdict(mv.verdict, appraisal, lakatos_result=None)
        out.append(dict(
            tag=n.tag,
            metric_verdict=mv.verdict,                          # judge 생성
            pnr_verdict=(appraisal.verdict if appraisal else None),   # 변증법 생성
            pnr_reasons=(tuple(appraisal.reasons) if appraisal else ()),  # _counterexample_note 포함
            dialectic_status=final["status"],
            verdict=final["verdict"],                           # 합성 최종 (손입력 아님)
            euler_char=n.euler_characteristic,
            reasons=tuple(final.get("reasons", ())),
        ))
    return out


if __name__ == "__main__":
    for r in run():
        print(f"{r['tag']:20} χ={str(r['euler_char']):>4}  metric={str(r['metric_verdict']):>11}  "
              f"pnr={str(r['pnr_verdict']):>14}  → {r['verdict']}")
