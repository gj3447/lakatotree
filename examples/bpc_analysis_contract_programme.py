"""Dogfood — BPC analysis-contract(측정·운반·DT) 파이프라인을 라카토트리 프로그램으로 모델링.

`bpc_icp_programme.py` 가 *정합*(20뷰→sub-1mm) 연구사라면, 본 프로그램은 그 **하류**:
  "정합된 DC375 → 16-output analysis contract(geometry 측정 + AI) → DT/PLC verdict,
   sub-mm + fail-closed 필드안전."
다른 scope(measurement) = 다른 tree. 정합 프로그램의 pins(v8/43.8%)는 건드리지 않는다.

출처(실측·실작업, 2026-06-14 jg_bpc kjra LTDD 캠페인 W1~W5 + 운반 수렴 + SOLID 디커플):
  W3 merged cloud bytes(same-host ShmHandle / cross-host MinIO .bin), 운반 3-way 수렴
  (same-host=ShmHandle / cross-merged=MinIO / cross-per-view=Arrow Flight :50090, wire-compat),
  #1,2 distortion grid, #3,4 panel plane fit, #6,7 panel-relative, #11 cup z단차(nadir-only),
  #12 TAB_BOLT 3층(base_tab/washer_top/head_top), #16 v16 DataMatrix barcode HUD,
  XC PLC forced-NG(cycle error→fail-closed) + NG threshold 활성, DT 렌더 전종(QThread, main 부담0),
  Windows tester PC(DESKTOP-SNAP5I3) 133 pytest green.
기각 연구사: bulk numpy proto-bytes(30MB+ gRPC 한계), MinIO presigned 브라우저 직접(host baked-in),
  >2s sync RPC(Next.js dev proxy socket hang up), UI→connector 직접 import(tight coupling).

Hard core(정본 = docs/BPC_PRISMV2_LONGINUS_20260612.md):
  2D seg=위치/coarse만, 치수=3D geometry/RecipeV2/HALCON, hole 3종=parent plane void boundary
  (center XY + parent/base Z, per-view fitted center를 물리 truth로 안 씀), CUP=CAD band z+nadir,
  TAB_BOLT/washer=3층 보존, LABEL=ROI helper(decoded truth=v16 policy),
  bulk numpy는 proto bytes 금지(ShmHandle), PLC 제어 loop은 Python이 안 닫음(verdict NG=fail-closed).

실행: python -m examples.bpc_analysis_contract_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.metrics import tree_metrics, branch_inputs
from lakatos.stack import evaluate_stack
from lakatos.lifecycle import lifecycle_state
from lakatos.leaderboard import Competitor, leaderboard as build_leaderboard
from lakatos.certify import gate_check, certify_claim, next_actions
from lakatos.fertility import predictive_fertility


def _n(tag, verdict, parent, *, m=None, base=None, scope='measurement',
       direction='higher', nr=False, nc=False, q=None, comment='', limitation='', algo=''):
    """measurement scope = '검증된 contract output 누적'(higher=진보). 정합(lower=mm)과 다른 축."""
    return dict(tag=tag, verdict=verdict, parent=parent,
                metric_value=m, metric_scope=scope, pred_baseline=base,
                pred_noise_band=0.05, pred_direction=direction,
                novel_registered=nr, novel_confirmed=nc,
                algorithm=algo or 'hexagonal', comment=comment, limitation=limitation,
                questions=q or [])


# ── BPC analysis-contract 프로그램 트리 (실 작업사: W1~W5 + 운반 수렴 + SOLID) ──────
# metric = end-to-end LTDD-green + Windows-verified contract output 누적 개수 (higher=진보)
NODES = [
    _n('prob_statement', 'canonical_stage', None,
       comment='정합된 DC375 → 16-output analysis contract → DT/PLC verdict (sub-mm + fail-closed)',
       algo='problem'),

    # 정본 경로(progressive → CANONICAL) — 운반 토대 → 측정 산출 누적 → DT 통합
    _n('merged_dt', 'progressive', 'prob_statement', m=1, base=0,
       nr=True, nc=True, q=['q_transport_map', 'q_flight_consumer'],
       comment='W3: merged cloud bytes 운반(same-host ShmHandle / cross-host MinIO .bin) → DT 렌더. '
               '운반 경계조건별 분리 + sha256(ascontiguousarray.tobytes) 검증',
       limitation='cross-host per-view 실시간 Flight 라우팅은 prismv2 F4 deferred'),
    _n('panel_geom', 'progressive', 'merged_dt', m=4, base=1,
       nr=True, nc=True,
       comment='W2-a/d: #3,4 panel plane fit(상/하판 z·기울기 pure) + #1,2 distortion grid 히트맵',
       limitation='plane fit residual=면 평탄도 가정(결함은 belt 가설)'),
    _n('feature_rel', 'progressive', 'panel_geom', m=6, base=4,
       nr=True, nc=True, q=['q_w2prod'],
       comment='W2-e: #6,7 panel-relative feature 위치 — parent plane void boundary center XY + base Z '
               '(per-view fitted center를 물리 truth로 안 씀, hard core 정렬)',
       limitation='DC375 authoritative measure_lot per-view snr 운반 미배선(W2-prod)'),
    _n('cup_tab_z', 'progressive', 'feature_rel', m=8, base=6,
       nr=True, nc=True, q=['q_tab_seat'],
       comment='#11 cup z단차(CAD band, nadir-only z) + #12 TAB_BOLT 3층(base_tab/washer_top/head_top) glyph',
       limitation='TAB 2.1mm=볼트안착 가설(belt), CMM 미검증'),
    _n('barcode', 'progressive', 'cup_tab_z', m=9, base=8,
       nr=True, nc=True,
       comment='W4: #16 v16 DataMatrix decode → DT HUD. LABEL=ROI helper, decoded truth=v16 policy',
       limitation='#14 label AI 실 weight(ontable pointnet_best.pt) 미배선'),
    _n('dt_render', 'CANONICAL', 'barcode', m=9, base=9,
       nr=True, nc=True, q=['q_seg', 'q_label_weight'],
       comment='W5: DT 렌더 전종 통합(3z stacked bar / panel plane mesh / panel-relative label / merged render) '
               '+ 렌더층 trace(analysis.dt.*) + QThread(main 부담0). Windows tester PC 133 pytest green',
       limitation='seg overlay(#15)는 ultralytics infra 대기'),
    _n('safety_forced_ng', 'progressive', 'dt_render', m=10, base=9,
       nr=True, nc=True,
       comment='XC: PLC forced-NG(cycle error→fail-closed NG verdict) + NG threshold 활성 — 필드안전 hard core. '
               'Python은 PLC 제어 loop 안 닫음(verdict 전달만)',
       limitation='threshold 정책=Mongo ng_thresholds repo(현장 튜닝 여지)'),

    # 기각/퇴행 가지(보존) — 운반·아키텍처 연구사 교훈
    _n('proto_bytes_bulk', 'rejected', 'merged_dt',
       comment='bulk numpy(30MB+)를 proto bytes 로 직접 전송 시도',
       limitation='gRPC 메시지 한계 + 직렬화 메모리 2배 → 기각, ShmHandle/MinIO 로 교정'),
    _n('minio_presigned_browser', 'rejected', 'merged_dt',
       comment='MinIO presigned URL 브라우저 직접 접근 시도',
       limitation='k8s pod host baked-in → 외부 접근불가 → FastAPI .bin proxy 로 교정'),
    _n('sync_rpc_blocking', 'degenerating', 'prob_statement', m=0, base=1,
       comment='>2s sync RPC 로 측정 결과 반환 시도',
       limitation='Next.js dev proxy socket hang up → Job pattern(async ack+stream) 으로 교정'),
]

FRONTIER = [
    dict(name='q_transport_map', status='CLOSED',
         body='운반 3-way 수렴 — same-host=ShmHandle / cross-merged=MinIO / cross-per-view=Arrow Flight',
         closed_by=['merged_dt']),
    dict(name='q_tab_seat', status='CLOSED',
         body='TAB_BOLT 3층(base_tab/washer_top/head_top) 운반·렌더 되나', closed_by=['cup_tab_z']),
    dict(name='q_flight_consumer', status='OPEN',
         body='cross-host per-view 실시간 Arrow Flight 라우팅(consumer 배선)', closed_by=None),
    dict(name='q_w2prod', status='OPEN',
         body='DC375 authoritative measure_lot per-view snr 운반(option A snr_handle / B disk)', closed_by=None),
    dict(name='q_seg', status='OPEN',
         body='#15 YOLO11m-seg 2D position/coarse production 배선(ultralytics infra)', closed_by=None),
    dict(name='q_label_weight', status='OPEN',
         body='#14 label AI 실 weight(ontable pointnet_best.pt) MinIO upload + 배선', closed_by=None),
]


# ── 경쟁 프로그램 — monolithic/tight-coupling rival (SOLID 디커플 이전) ──────────────
RIVAL_NODES = [
    _n('mono_root', 'canonical_stage', None,
       comment='monolithic: UI→connector 직접 import + proto-bytes 운반 + sync RPC', algo='monolith'),
    _n('mono_tight', 'degenerating', 'mono_root', m=0, base=1,
       comment='UI 가 connector.emit 직접 호출(tight coupling)',
       limitation='ui↔connector 순환 + tach/import-linter 경계 위반'),
    _n('mono_block', 'degenerating', 'mono_tight', m=0, base=0,
       comment='sync RPC + proto-bytes 누적',
       limitation='socket hang up + 메모리 2배 → DIP 디커플(analysis_trace top-level)로 교정'),
    _n('mono_ci_block', 'degenerating', 'mono_block', m=0, base=0,
       comment='tach/import-linter 경계 게이트 위반으로 머지 불가',
       limitation='경계 위반 누적 → 폐기, hexagonal(ports/strategy/seams)로 전환'),
]
RIVAL_FRONTIER = [dict(name='q_decouple', status='OPEN', body='SOLID/DIP 경계 강제', closed_by=None)]


def _line(c=''):
    print(c)


def run():
    _line('═' * 72)
    _line('  BPC analysis-contract(측정·운반·DT) — 라카토스 연구 프로그램 (dogfood)')
    _line('═' * 72)

    # 1) 트리 지표
    m = tree_metrics(NODES, FRONTIER)
    _line('\n[1] 프로그램 지표')
    _line(f"  정본(CANONICAL)     : {m['canonical']}")
    prog = m.get('progress') or {}
    _line(f"  진보율              : {prog.get('improvement_pct')}%  "
          f"({prog.get('first', {}).get('m')} → {prog.get('last', {}).get('m')} output, scope={prog.get('scope')})")
    _line(f"  기각률              : {m['rejection_ratio']}")
    _line(f"  최대 퇴행깊이       : {m['max_degeneration_depth']}")
    _line(f"  주석 커버리지       : {m['annotation_coverage']}")
    _line(f"  경보                : {m.get('alerts')}")

    # 2) 베이즈 신뢰도 + 발전성
    _line('\n[2] 베이즈 + 발전성(novel 예측)')
    _line(f"  정본경로 신뢰도     : {m['bayes']['canonical_credence']}")
    _line(f"  저신뢰 가지         : {m['bayes']['low_credence_branches']}")
    fert = predictive_fertility(NODES)
    _line(f"  novel 등록/확증     : {fert['registered']} / {fert['confirmed']}")
    _line(f"  발전성 지표         : {m.get('fertility')}")

    # 3) 라우든 — 문제수지
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

    # 4b) monolithic rival 스택 — 폐기 합의 나는가?
    bir = branch_inputs(RIVAL_NODES, RIVAL_FRONTIER, leaf='mono_ci_block')
    svr = evaluate_stack(bir['verdicts'], bir['consecutive_nonprogressive'], bir['nodes_spent'],
                         bir['prediction_hits'], bir['problem_balance_windowed'])
    lsr = lifecycle_state(bir['verdicts'], svr, bir['novel_registered_recent'],
                          bir['problem_balance_windowed'], bir['canonical_improved_recent'])
    _line(f"  monolithic 가지 스택: {svr.decision}  → 수명주기 {lsr.state}")

    # 5) 리더보드 — hexagonal vs monolithic
    _line('\n[5] 경쟁 프로그램 리더보드 (hexagonal vs monolithic)')
    mr = tree_metrics(RIVAL_NODES, RIVAL_FRONTIER)

    def _comp(name, nodes, frontier, met):
        bi_ = branch_inputs(nodes, frontier) if any(n['verdict'] == 'CANONICAL' for n in nodes) else None
        verdicts = bi_['verdicts'] if bi_ else []
        imp = (met.get('progress') or {}).get('improvement_pct') or 0.0
        return Competitor(name=name, verdicts=verdicts, nodes=nodes, metric_improvement_pct=imp,
                          closed=met['frontier']['closed'], opened=met['frontier']['open'])
    lb = build_leaderboard([
        _comp('hexagonal_contract', NODES, FRONTIER, m),
        _comp('monolithic_coupled', RIVAL_NODES, RIVAL_FRONTIER, mr),
    ])
    _line(f"  Pareto front        : {lb['pareto_front']}")
    for row in lb['rows']:
        _line(f"  {row['name']:18s} borda={row['borda']} laudan={row['laudan_score']} "
              f"credence={row['credence']} fertility_lb={row['fertility_lb']}")

    # 6) 인증 — 정본 노드 5게이트 (정직: W4 blocked + credence 보정 부재)
    _line('\n[6] 정본(dt_render) 5게이트 인증')
    checks = [
        gate_check('preregistered', True, 'judge:LTDD red-trace oo analysis.* 사전등록'),
        gate_check('reproducible', True, 'repro:133 pytest LTDD + Windows tester PC green'),
        gate_check('stands', False, ''),        # ★ 솔직: W4 seg/label weight OPEN(미해소 의문)
        gate_check('calibrated', False, ''),    # ★ 솔직: credence 보정 이력 부재
        gate_check('grounded', True, 'grounding:NG threshold + tolerance tier 공개'),
    ]
    cert = certify_claim('dt_render_canonical', checks, {'as_of': '2026-06-14'})
    _line(f"  인증 여부           : {cert.certified}")
    _line(f"  미통과 게이트       : {cert.missing}")
    for a in next_actions(cert):
        _line(f"    → {a['gate']}: {a['action']}")

    _line('\n' + '═' * 72)
    return dict(metrics=m, stack=sv.decision, lifecycle=ls.state,
                rival_stack=svr.decision, leaderboard=lb, certified=cert.certified,
                missing=cert.missing)


if __name__ == '__main__':
    run()
