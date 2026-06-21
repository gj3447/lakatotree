"""C3 Phase-0/1 — 엔진 효과성 retrospective corpus + harness (docs/C3_EFFECTIVENESS_PROTOCOL.md).

외부리뷰 B-5 를 실측으로: 역사적 Lakatos 정전 사례(결과 기지=ground-truth)에 두 조건을 돌려 비교한다.
  A. engine     = lakatos.verdict.judge.judge (사전등록 + use-novelty 게이트)
  B. self-report = "어떤 개선이라도 있으면 진보" (사전등록·novelty 무시 = confabulation baseline)
ground-truth = 역사적 Lakatos 평가(외부 사실). 차이는 *ad-hoc 패치* 사례에서 난다: 데이터는 맞췄지만(improved)
novel 예측이 없는 프로그램 — engine 은 partial(퇴행)로 정직, self-report 는 progressive 로 속는다(가짜 aha).

★정직(프로토콜 §6 위협#1 순환성): 이 corpus 는 Lakatos *자신의 예시*다 → 엔진이 잘 맞히는 건 "Lakatos 를
올바로 기계화했다"는 *construct validity* 이지, 독립 효과성 증명이 아니다. 독립 증명은 Phase-2(전향 사전등록).
이 harness 가 측정하는 것: (1) 엔진이 역사적 평가를 재현하는가 (2) self-report(confabulation)보다 나은가.
"""
from __future__ import annotations

from lakatos.grounding import wilson_lower_bound
from lakatos.verdict.judge import NovelTarget, Prediction, judge

PROGRESSIVE, DEGENERATING = 'progressive', 'degenerating'

# 각 사례: 사전등록 예측(metric/baseline/measured) + (있으면) 독립 novel 예측 + 역사적 ground-truth.
# improved=measured 가 baseline 보다 개선. novel=별도 metric 의 사전예측이 외부 확증됐는가(use-novelty).
CORPUS = [
    # ── 진보(novel 예측 확증) — Lakatos/Popper 정전 ──────────────────────────
    dict(name='einstein_gr_mercury', era='1915', baseline=43.0, measured=0.0, direction='lower',
         novel=('perihelion_arcsec', 'higher', 42.0, 43.0),  # GR 가 사전예측한 43"/cy 가 관측 확증
         ground_truth=PROGRESSIVE, note='GR: 수성 근일점 43"/cy novel 예측 확증 (Lorentz 대비 progressive)'),
    dict(name='copernicus_venus_phases', era='1610', baseline=1.0, measured=0.4, direction='lower',
         novel=('venus_full_phase', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='태양중심: 금성 위상(full phase) novel 예측 → Galileo 확증'),
    dict(name='halley_comet_return', era='1758', baseline=1.0, measured=0.2, direction='lower',
         novel=('comet_return_year', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='Newton/Halley: 1758 혜성 회귀 novel 예측 → 확증'),
    dict(name='leverrier_neptune', era='1846', baseline=1.0, measured=0.1, direction='lower',
         novel=('new_planet_position', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='Newtonian: 미지 행성(해왕성) 위치 novel 예측 → 발견'),
    dict(name='mendeleev_gallium', era='1875', baseline=1.0, measured=0.15, direction='lower',
         novel=('eka_aluminium_density', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='주기율표: eka-alumin(gallium) 성질 novel 예측 → 확증'),
    dict(name='bohr_balmer_spectra', era='1913', baseline=1.0, measured=0.2, direction='lower',
         novel=('spectral_line_nm', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='Bohr 원자: 수소 스펙트럼선 novel 예측 → 확증'),
    dict(name='platetectonics_seafloor', era='1963', baseline=1.0, measured=0.3, direction='lower',
         novel=('magnetic_striping', 'higher', 0.5, 1.0),
         ground_truth=PROGRESSIVE, note='판구조론: 해저 자기 줄무늬 novel 예측 → Vine-Matthews 확증'),
    # ── 퇴행(ad-hoc 패치: 데이터는 맞췄으나 novel 없음) — self-report 가 속는 지점 ──
    dict(name='lorentz_ether_contraction', era='1892', baseline=1.0, measured=0.3, direction='lower',
         novel=None,  # 에테르 구제용 수축 = Michelson-Morley 사후 맞춤, 독립 novel 예측 0
         ground_truth=DEGENERATING, note='Lorentz: ad-hoc 수축으로 MM 결과 맞춤, novel 없음 → 퇴행'),
    dict(name='ptolemy_epicycles', era='150', baseline=1.0, measured=0.25, direction='lower',
         novel=None,  # 주전원 추가 = 관측 곡선맞춤, novel 예측 0
         ground_truth=DEGENERATING, note='Ptolemy: 주전원 추가로 관측 맞춤(curve-fit), novel 없음 → 퇴행'),
    dict(name='phlogiston_negative_weight', era='1770', baseline=1.0, measured=0.4, direction='lower',
         novel=None,  # 음의 무게 phlogiston = 연소 질량증가 사후 맞춤
         ground_truth=DEGENERATING, note='Phlogiston: 음의 무게 ad-hoc 으로 질량증가 맞춤 → 퇴행(Lavoisier 가 대체)'),
    dict(name='marxism_adhoc_auxiliary', era='1900s', baseline=1.0, measured=0.45, direction='lower',
         novel=None,  # 빗나간 예측마다 보조가설 추가(Popper 의 비반증성 예시)
         ground_truth=DEGENERATING, note='실패 예측마다 ad-hoc 보조가설 추가, novel 0 → 퇴행(Popper/Lakatos)'),
    dict(name='caloric_heat_fluid', era='1800', baseline=1.0, measured=0.5, direction='lower',
         novel=None,  # 열=유체 caloric: 마찰열 등 사후 맞춤, novel 없음(Joule 가 대체)
         ground_truth=DEGENERATING, note='Caloric: 마찰열 사후 맞춤, novel 없음 → 퇴행(에너지보존이 대체)'),
]


def engine_verdict(case: dict) -> str:
    """A. engine — judge(사전등록 + use-novelty). progressive↔progressive, 그 외(partial/equivalent/rejected)↔퇴행."""
    pred = Prediction(metric_name='fit', direction=case['direction'],
                      baseline_value=case['baseline'], noise_band=0.0)
    nt = nm = None
    if case['novel'] is not None:
        nmetric, ndir, nthr, nmeas = case['novel']
        nt = NovelTarget(metric_name=nmetric, direction=ndir, threshold=nthr)
        nm = nmeas
    v = judge(pred, case['measured'], novel_target=nt, novel_measured=nm)
    return PROGRESSIVE if v.verdict == 'progressive' else DEGENERATING


def self_report_verdict(case: dict) -> str:
    """B. self-report — 사전등록·novelty 무시, 어떤 개선이라도 있으면 진보 선언(confabulation baseline)."""
    improved = (case['measured'] < case['baseline'] if case['direction'] == 'lower'
                else case['measured'] > case['baseline'])
    return PROGRESSIVE if improved else DEGENERATING


def _score(verdict_fn) -> dict:
    n = len(CORPUS)
    correct = sum(1 for c in CORPUS if verdict_fn(c) == c['ground_truth'])
    claimed_prog = [c for c in CORPUS if verdict_fn(c) == PROGRESSIVE]
    false_prog = [c for c in claimed_prog if c['ground_truth'] != PROGRESSIVE]
    return dict(n=n, correct=correct, accuracy=round(correct / n, 3),
                accuracy_wilson_lb=round(wilson_lower_bound(correct, n), 3),
                claimed_progressive=len(claimed_prog),
                hallucination_rate=round(len(false_prog) / max(1, len(claimed_prog)), 3),
                false_progressives=[c['name'] for c in false_prog])


def run() -> dict:
    """retrospective Phase-1 측정 — engine vs self-report 정확도/Wilson LB/환각률 (외부 ground-truth 대조)."""
    return {'corpus_size': len(CORPUS),
            'engine': _score(engine_verdict),
            'self_report': _score(self_report_verdict)}


if __name__ == '__main__':
    import json
    print(json.dumps(run(), ensure_ascii=False, indent=2))
