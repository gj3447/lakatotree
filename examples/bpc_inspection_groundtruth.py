"""BPC 검사 verdict 의 *labeled ground truth* — lakatotree 사전등록 예측으로.

(B) 문제: oo 로그는 파이프라인의 *실제* verdict 를 줄 뿐 *정답* verdict 를 주지 않는다. 정답을
외부 라벨 오라클이 아니라 **lakatotree 의 사전등록 잠금 Prediction** 으로 박는다:
  - 공차를 *미리* 잠그면(PredictionLocked, 채점 후 변경 금지) 그게 ground-truth contract.
  - ZDF 측정 위치편차(dev_xy)를 judge 에 넣으면 *재현가능·조작불가* PASS/FAIL 이 나온다.
  - PredictionMissing(사전등록 없는 채점 금지) = 사후 합리화 차단.
→ 그래서 verdict 가 *certifiable* (dogfood 의 "v8 0.90mm 는 사전등록/재현 없으면 인증불가" 와 동형).

규칙(prismv2 part_spec / jg_bpc ng_threshold 정본): dev_xy < tolerance_mm → PASS, else FAIL.
  = judge(Prediction(baseline=tolerance, dir='lower', noise=0)).improved (정확히 dev<tol).
공차(BPC tiered, vision3d_test/CLAUDE.md): bush 1.5 / b_point 1.0 / bolt 0.8 mm.
  ★정직: DC375 전용 공차는 미확정(PMI 0) — 아래 tier 는 BPC 정본값, DC375 확정은 잔여(dogfood 갭).

테스트법(전체 ZDF 기반): ZDF lot replay → 파이프라인 verdict(oo bpc_inspection) 와 *여기 ground-truth
verdict* 를 비교. 불일치 = 파이프라인 버그 또는 현장 공차 config 가 잠긴 spec 에서 drift → 잡힌다.
# KG: span_lakatotree_bpc_inspection_gt
"""
from __future__ import annotations

from lakatos.judge import Prediction, judge, PredictionMissing, PredictionLocked, check_registration

# ── 공차 spec (정답 contract 의 근거) — feature group → 위치공차 mm. grounded: BPC tiered ──
TOLERANCE_MM = {
    'bush_base': 1.5, 'big_circle': 1.5,            # mounting bush (가장 느슨)
    'b_point': 1.0,
    'bolt': 0.8, 'tab_bolt': 0.8,                   # 볼트 (가장 빡빡)
    'plate': 1.0, 'outer': 1.0, 'washer': 1.0,      # 보조 feature (잠정, DC375 확정 대기)
}
DEFAULT_TOL = 1.0


def tolerance_for(group: str) -> float:
    return TOLERANCE_MM.get(group, DEFAULT_TOL)


def preregister(group: str) -> Prediction:
    """feature group 의 공차를 *잠긴 사전등록 예측* 으로 = ground-truth contract.

    metric=dev_xy(위치편차 mm), baseline=공차, direction='lower'(작을수록 양호), noise=0(엄격 <).
    Prediction 은 frozen — 한번 만들면 못 바꾼다(채점 후 변경은 PredictionLocked 로도 차단).
    """
    return Prediction(metric_name=f'dev_xy_{group}', direction='lower',
                      baseline_value=tolerance_for(group), noise_band=0.0,
                      closes_question='within_position_tolerance')


def ground_truth_verdict(group: str, measured_dev_mm: float) -> str:
    """ZDF 측정 위치편차 → 사전등록 공차 대비 정답 PASS/FAIL (재현가능, judge 정본).

    judge(...).improved == (dev < tolerance) — prismv2/jg_bpc 의 `dev_xy < tolerance_mm` 와 동일 규칙.
    """
    v = judge(preregister(group), measured_dev_mm)
    return 'PASS' if v.improved else 'FAIL'              # dev<tol → PASS, dev>=tol → FAIL(엄격)


def check_against_pipeline(group: str, measured_dev_mm: float, pipeline_verdict: str) -> dict:
    """파이프라인 verdict(oo)가 사전등록 ground-truth 와 일치하나 — 전체-ZDF 테스트의 핵심 단언.

    불일치(match=False) = 파이프라인 verdict 버그 OR 현장 공차 config 가 잠긴 spec 에서 drift.
    """
    gt = ground_truth_verdict(group, measured_dev_mm)
    pv = pipeline_verdict.upper()
    return {'group': group, 'dev_mm': measured_dev_mm, 'tolerance_mm': tolerance_for(group),
            'ground_truth': gt, 'pipeline': pv, 'match': gt == pv}


# ── 데모: 한 inspection 의 feature 들 + (가상) 파이프라인 verdict 대조 ──────────
def run():
    print('═' * 64)
    print('  BPC 검사 ground-truth (lakatotree 사전등록 예측) — verdict 정답화')
    print('═' * 64)
    # (group, measured_dev_mm, pipeline_verdict)  ← 파이프라인 verdict 는 실제론 oo bpc_inspection 에서 옴
    inspection = [
        ('bush_base', 0.42, 'PASS'),   # 0.42 < 1.5 → PASS, 파이프라인 일치
        ('bolt',      0.31, 'PASS'),   # 0.31 < 0.8 → PASS
        ('bolt',      0.95, 'PASS'),   # 0.95 > 0.8 → 정답 FAIL 인데 파이프라인이 PASS = ★불일치(drift!)
        ('b_point',   1.40, 'FAIL'),   # 1.40 > 1.0 → FAIL, 일치
    ]
    print('\n[per-feature 정답 vs 파이프라인]')
    mismatches = []
    for grp, dev, pv in inspection:
        r = check_against_pipeline(grp, dev, pv)
        mark = '✅' if r['match'] else '❌ DRIFT'
        print(f"  {grp:10s} dev={r['dev_mm']:.2f} tol={r['tolerance_mm']:.1f}  "
              f"정답={r['ground_truth']} 파이프라인={r['pipeline']}  {mark}")
        if not r['match']:
            mismatches.append(r)
    overall_gt = 'FAIL' if any(ground_truth_verdict(g, d) == 'FAIL' for g, d, _ in inspection) else 'PASS'
    print(f"\n[종합] 정답 lot verdict = {overall_gt} (feature 1개라도 공차초과면 FAIL)")
    print(f"[테스트] 파이프라인 불일치 {len(mismatches)}건 — 불일치=파이프라인 버그/공차 drift")
    print('═' * 64)
    return {'overall_ground_truth': overall_gt, 'mismatches': mismatches}


if __name__ == '__main__':
    run()
