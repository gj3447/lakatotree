"""Dogfood — BPC/ICP 멀티뷰 정합 연구를 라카토트리 프로그램으로 모델링.

목적: 합성 audit 이 아니라 *실제 연구사*(메모리 정본)로 엔진을 end-to-end 구동해
      엔진이 진짜 데이터에서 옳은 결론을 내는지, 어디서 깨지는지 본다.

연구 프로그램 = "20 BPC 뷰를 DC375 검사용 sub-1mm 로 정합한다."
출처(실측, 메모리): ArUco metric 정합 1 component, frozen calib cross-lot 4.05mm,
  v8 interior 0.90mm(CAD pts-NN 2.44 floor 제거 후 진짜값), 6-DOF per-view seam 0.93→2.81(3x악화),
  free-ICP collapse 876mm vs 실 footprint 2353mm, non-rigid CPD 결함 4.34mm 흡수(기각),
  markerless cloud-relax 19.4→12.0mm 악화(기각).

실행: python -m examples.bpc_icp_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.metrics import tree_metrics, branch_inputs
from lakatos.stack import evaluate_stack
from lakatos.lifecycle import lifecycle_state
from lakatos.leaderboard import Competitor, leaderboard as build_leaderboard
from lakatos.certify import gate_check, certify_claim, next_actions
from lakatos.fertility import predictive_fertility


def _n(tag, verdict, parent, *, m=None, base=None, scope='registration',
       direction='lower', nr=False, nc=False, q=None, comment='', limitation='', algo=''):
    return dict(tag=tag, verdict=verdict, parent=parent,
                metric_value=m, metric_scope=scope, pred_baseline=base,
                pred_noise_band=0.05, pred_direction=direction,
                novel_registered=nr, novel_confirmed=nc,
                algorithm=algo or 'classical', comment=comment, limitation=limitation,
                questions=q or [])


# ── BPC/ICP 프로그램 트리 (실제 연구사) ──────────────────────────────────────
NODES = [
    # 정본 경로(progressive → CANONICAL)
    _n('prob_statement', 'canonical_stage', None,
       comment='20 BPC 뷰 metric 정합 → DC375 검사 sub-1mm', algo='problem'),
    _n('aruco_metric', 'progressive', 'prob_statement', m=1.60, base=12.0,
       nr=True, nc=True, q=['q_markerless_reuse'],
       comment='ArUco shared-marker Kabsch+BA — 21뷰 1 connected component',
       limitation='격자이웃≠마커공유, dup-ID 가짜다리 주의'),
    _n('frozen_calib_reuse', 'progressive', 'aruco_metric', m=1.026, base=1.60,
       nr=True, nc=True, q=['q_crosslot'],
       comment='board calib 동결→markerless lot 직접 T_view_to_world 재사용(0040→0049 1.384→1.026)',
       limitation='seam=self-consistency, accuracy vs CAD 미검증'),
    _n('v8_pipeline', 'CANONICAL', 'frozen_calib_reuse', m=0.90, base=1.026,
       nr=True, nc=True, q=['q_dc375_tol', 'q_outer004', 'q_washer_step'],
       comment='v8: ZDF stride3 srgb+frozen calib+colfix+v7보정, mesh-exact QC, cross-lot 4.05mm',
       limitation='interior 0.90mm CMM 미검증(precision≠accuracy)'),

    # 퇴행 가지(보존) — per-view 6-DOF ICP 를 3회 시도, 매번 악화
    _n('pv6dof_a', 'degenerating', 'aruco_metric', m=1.80, base=0.93,
       comment='per-view 6-DOF ICP refine 시도1', limitation='in-plane rank deficiency 끌림'),
    _n('pv6dof_b', 'degenerating', 'pv6dof_a', m=2.40, base=1.80,
       comment='damping 조정 재시도', limitation='seam 더 악화'),
    _n('pv6dof_c', 'degenerating', 'pv6dof_b', m=2.81, base=2.40,
       comment='iteration 늘림', limitation='seam 0.93→2.81 3x악화 — per-view 6-DOF 유해 확정'),

    # 퇴행 가지(보존) — free multi-view ICP
    _n('free_multiview_icp', 'degenerating', 'prob_statement', m=12.0, base=None,
       comment='free global ICP / cloud-relax markerless',
       limitation='주기 포켓 aliasing → collapse(876mm vs 실 2353mm), 40iter 19.4→12.0 악화'),

    # 기각 가지(보존)
    _n('non_rigid_cpd', 'rejected', 'frozen_calib_reuse', m=4.34, base=1.026,
       comment='non-rigid CPD warp 시도',
       limitation='결함 4.34mm 를 변형으로 흡수=진짜오차 은폐 → 기각'),
    _n('spurious_90lock', 'rejected', 'aruco_metric',
       comment='dup-marker 가짜다리 → spurious 90° lock',
       limitation='dup ID 가 BA collapse 연료 → 기각'),
]

FRONTIER = [
    dict(name='q_markerless_reuse', status='CLOSED', body='markerless lot 에 board calib 재사용 되나',
         closed_by=['frozen_calib_reuse']),
    dict(name='q_crosslot', status='CLOSED', body='cross-lot per-view T 전이 <5mm',
         closed_by=['v8_pipeline']),
    dict(name='q_dc375_tol', status='OPEN', body='interior 0.90mm 가 DC375 공차 T0 에 충분한가', closed_by=None),
    dict(name='q_outer004', status='OPEN', body='OUTER_004 분기 — outer hole 검출 커버리지', closed_by=None),
    dict(name='q_washer_step', status='OPEN', body='washer step +0.83mm 진짜인가 artifact 인가', closed_by=None),
]


# ── 경쟁 프로그램(gap7 패러다임) — 학습기반 6D pose (보류된 rival) ──────────────
RIVAL_NODES = [
    _n('learn_root', 'canonical_stage', None, comment='GDRN/GigaPose 6D pose 학습', algo='learning'),
    _n('gigapose_try', 'degenerating', 'learn_root', m=10.0, base=12.0,
       comment='GigaPose 시도', limitation='x86-only → GB10 aarch64 blocked'),
    _n('gdrn_try', 'degenerating', 'gigapose_try', m=9.0, base=10.0,
       comment='GDRN++ 시도', limitation='markerless flat-panel partial-view underconstrained + 데이터/라이선스 제약'),
]
RIVAL_FRONTIER = [dict(name='q_compute', status='OPEN', body='GB10 aarch64 학습 컴퓨트', closed_by=None)]


def _line(c=''):
    print(c)


def run():
    _line('═' * 72)
    _line('  BPC/ICP 멀티뷰 정합 — 라카토스 연구 프로그램 (dogfood)')
    _line('═' * 72)

    # 1) 트리 지표
    m = tree_metrics(NODES, FRONTIER)
    _line('\n[1] 프로그램 지표')
    _line(f"  정본(CANONICAL)     : {m['canonical']}")
    prog = m.get('progress') or {}
    _line(f"  진보율              : {prog.get('improvement_pct')}%  "
          f"({prog.get('first', {}).get('m')} → {prog.get('last', {}).get('m')} mm, scope={prog.get('scope')})")
    _line(f"  기각률              : {m['rejection_ratio']}")
    _line(f"  최대 퇴행깊이       : {m['max_degeneration_depth']}  (≥3 경보)")
    _line(f"  주석 커버리지       : {m['annotation_coverage']}")
    _line(f"  경보                : {m.get('alerts')}")

    # 2) 베이즈 신뢰도 + 발전성
    _line('\n[2] 베이즈 + 발전성(novel 예측)')
    _line(f"  정본경로 신뢰도     : {m['bayes']['canonical_credence']}")
    _line(f"  저신뢰 가지         : {m['bayes']['low_credence_branches']}")
    fert = predictive_fertility(NODES)
    _line(f"  novel 등록/확증     : {fert['registered']} / {fert['confirmed']}")
    _line(f"  발전성 지표         : {m.get('fertility')}")

    # 3) 라우든 — 문제수지 + 폐기 후보 + 미귀속(P7-F)
    _line('\n[3] 라우든 문제해결력')
    _line(f"  frontier 수지       : {m['laudan']['frontier_balance']}  (closed−open)")
    _line(f"  폐기 후보           : {m['laudan']['abandon_candidates']}")
    _line(f"  미귀속 폐쇄(P7-F)   : {m['laudan']['unattributed_closed']}")

    # 4) 3층 스택 + 수명주기 (정본 가지)
    _line('\n[4] 3층 메타규칙 + 수명주기 (정본 가지)')
    bi = branch_inputs(NODES, FRONTIER)
    sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                        bi['prediction_hits'], bi['problem_balance_windowed'])
    _line(f"  스택 결정           : {sv.decision}  (정족수 {sv.quorum}, conflict={sv.conflict})")
    _line(f"  스택 사유           : {sv.reason}")
    ls = lifecycle_state(bi['verdicts'], sv, bi['novel_registered_recent'],
                         bi['problem_balance_windowed'], bi['canonical_improved_recent'])
    _line(f"  수명주기 상태       : {ls.state}  — {ls.reason}")

    # 4b) 퇴행 가지(6-DOF) 스택 — 폐기 합의 나는가?
    bi6 = branch_inputs(NODES, FRONTIER, leaf='pv6dof_c')
    sv6 = evaluate_stack(bi6['verdicts'], bi6['consecutive_nonprogressive'], bi6['nodes_spent'],
                         bi6['prediction_hits'], bi6['problem_balance_windowed'])
    ls6 = lifecycle_state(bi6['verdicts'], sv6, bi6['novel_registered_recent'],
                          bi6['problem_balance_windowed'], bi6['canonical_improved_recent'])
    _line(f"  6-DOF 가지 스택     : {sv6.decision}  → 수명주기 {ls6.state}")

    # 5) 리더보드 — classical vs learning 프로그램 (gap7)
    _line('\n[5] 경쟁 프로그램 리더보드 (classical vs learning)')
    mr = tree_metrics(RIVAL_NODES, RIVAL_FRONTIER)
    def _comp(name, nodes, frontier, met):
        bi_ = branch_inputs(nodes, frontier) if any(n['verdict'] == 'CANONICAL' for n in nodes) else None
        verdicts = bi_['verdicts'] if bi_ else []
        imp = (met.get('progress') or {}).get('improvement_pct') or 0.0
        return Competitor(name=name, verdicts=verdicts, nodes=nodes, metric_improvement_pct=imp,
                          closed=met['frontier']['closed'], opened=met['frontier']['open'])
    lb = build_leaderboard([
        _comp('classical_halcon', NODES, FRONTIER, m),
        _comp('learning_6dpose', RIVAL_NODES, RIVAL_FRONTIER, mr),
    ])
    _line(f"  Pareto front        : {lb['pareto_front']}")
    for row in lb['rows']:
        _line(f"  {row['name']:18s} borda={row['borda']} laudan={row['laudan_score']} "
              f"credence={row['credence']} fertility_lb={row['fertility_lb']}")

    # 6) 인증 — 정본 노드 5게이트
    _line('\n[6] 정본(v8_pipeline) 5게이트 인증')
    checks = [
        gate_check('preregistered', True, 'judge:cross-lot 4.05mm novel 사전등록'),
        gate_check('reproducible', False, ''),   # ★ 솔직: mesh-exact QC 는 있으나 manifest 미작성
        gate_check('stands', True, 'argue:미해소 의문 0(정본경로)'),
        gate_check('calibrated', False, ''),      # ★ 솔직: credence 보정 이력 부재
        gate_check('grounded', True, 'grounding:정합 임계 tier 공개'),
    ]
    cert = certify_claim('v8_pipeline_canonical', checks, {'as_of': '2026-06-14'})
    _line(f"  인증 여부           : {cert.certified}")
    _line(f"  미통과 게이트       : {cert.missing}")
    for a in next_actions(cert):
        _line(f"    → {a['gate']}: {a['action']}")

    _line('\n' + '═' * 72)
    return dict(metrics=m, stack=sv.decision, lifecycle=ls.state,
                rival_stack=sv6.decision, leaderboard=lb, certified=cert.certified,
                missing=cert.missing)


if __name__ == '__main__':
    run()
