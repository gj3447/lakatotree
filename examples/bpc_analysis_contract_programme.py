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
       nr=True, nc=True, q=['q_tab_seat', 'q_tab_threshold', 'q_tab_coverage'],
       comment='#11 cup z단차(CAD band, nadir-only z) + #12 TAB_BOLT 3층(base_tab/washer_top/head_top) glyph. '
               'TAB_BOLT measurand=washer_h=z_washer_top−z_base_tab(상대 Δz, lot-common z~0.46mm 대수상쇄, '
               '절대z 경로 없음 panel_plane.py:15) — 모델 견고, 큰 결함(WASHER_055 0.8mm 결손 36/36 lot) 확실 검출',
       limitation='2026-06-15 TAB_BOLT 0.5 다방면검증(7-agent): (belt반증) 2.1mm 볼트안착 가설 데이터 반증 '
                  '— NG 73건 전부 low-side, high-side 0. (0.5공차) 도면근거 없는 임의값(DC375 PMI 0, awaiting-decision). '
                  '(capability) view-평균 σ0.024 P/T24% 이나 production gate min_ng_views=1 → single-view σ0.061 지배 '
                  '→ P/T 63% UNACCEPTABLE, σ는 ±0.4 clamp 안 측정이라 경계판별 미검증. (WASHER_002 borderline: '
                  'pipeline 버전간 0.94↔1.40 swing=공차 92%, CMM 없이 판가름 불가). gross-defect catcher로만 OK, '
                  'production-ready 아님 (q_tab_threshold/q_tab_coverage OPEN). 검증=BPC scripts tab_bolt 0p5 workflow'),
    _n('washer_roi_clean', 'progressive', 'cup_tab_z', m=8, base=8,
       nr=True, nc=True, q=['q_washer_tail_origin'],
       comment='2026-06-16 와샤 링 z ROI 무결성 감사(point-cloud + CAD): washer_h 반복정밀도 "꼬리"의 정체 규명. '
               'TAB_BOLT 스크류=헥사 소켓헤드(flats r≈5.0, tips r≈5.77; CAD washer clean flat r≥5.9, OD r8.25). '
               '현행 ring ROI inner(viz band 5.5 / doc-14 production annulus 5.8)가 r<6.2 의 헥사헤드 side-wall 을 '
               '링에 포함 → side-wall band(r4.7~6.1) z-spread 가 clean ring 의 6~14배, ROI z-tail(>3MAD)의 '
               '96.9%가 side-wall(r<6.2) 점(outer-wall/노이즈 반증). clean plateau 6.2~7.4(오염 0%, p90-p10 -64%, '
               'MAD -32%)로 ROI inner 5.5→6.2 교정 → 273/274 viz LANDED(드로잉 링=measured plateau 정본, '
               'rings_derived washer_top 5.5-7.5→6.2-7.4). novel 예측 확증: 꼬리=센서노이즈 아니라 헤드 옆면 기하 오염.',
       limitation='production wired 경로 = dc375_lot_pipeline._measure_tab L578 wr band (rr>=5.5, NOT '
                  'washer_ring.py 의 W_IN=5.8 — 그건 golden-tested 이나 unwired port). 실측 production delta: '
                  'median washer_h 가 +0.04mm HIGH (1.56→1.53 at 6.2, 독립 section GT 1.522 와 ~0.005mm 일치), '
                  'lot-repeat 0.012→0.007. ✅ rr>=5.5→6.2 LANDED (112 bpc test green, golden 無gating). '
                  '잔caveat=tighter inner 가 marginal washer 의 abstain↑ 가능(missing_is_defect→NG, fail-safe이나 '
                  'q_tab_coverage 와 상충) → 71-washer×2lot 실측 회귀 NEW abstain=0(view flip 0, coverage-neutral 확인)'),
    _n('washer_ev_wired_verified', 'progressive', 'cup_tab_z', m=8, base=8,
       nr=True, nc=True, q=['q_tab_coverage'],
       comment='2026-06-16 Longinus 관통 + 실측: "washer 36/71 검출 / E_v 미배선 갭" claim 이 STALE 임을 확정. '
               'E_v in-plane refine 은 dc375_lot_pipeline.apply_lot_corrections:469 에서 frozen v22_hyb3(bundle.ev_sol) '
               '를 매 lot in-place 적용(measure_lot:1573, Branch0 flag ON). 실 measure_lot 전체경로 재현(SOLVER_PKG_v12 '
               '번들+transform_camera_to_cad+E_v+feature_identity_recover=True): VFEZ0048 washer 71/71, VFEZ0049 70/71 '
               'detected. 유일 누락 WASHER_019=알려진 specular 볼트솟음(3D blind). detection coverage 갭 닫힘.',
       limitation='잔여 OPEN(detection 아님): σ/repeatability(single-view σ0.061→q_tab_threshold), specular 맹목(RGB-only). '
                  'field 일반 lot 은 v8_composite fallback=VFEZ0049 키 → VFEZ0049 run(70/71)이 대표. E_v solve 품질 √N 은 '
                  '연구repo 잔류(apply 절반만 prismv2 포트). ev_xy_correction.apply_frozen_view_xy 는 orphan(L469에 inline 복제)'),
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
    _n('field_dc375_128_deploy', 'progressive', 'safety_forced_ng', m=10, base=10,
       nr=True, nc=False, q=['q_dc375_spec128'],
       comment='2026-06-15 현장 enablement: capture-svc dimconfig(20뷰 frozen pose_cam_to_world, lot-불변, '
               'sha256 9048abd5) 배선 LIVE → inspection merge backend=concat_by_transform(free-ICP collapse 탈출, '
               'registered cloud, capture log fs2.bpc_a110 loaded 21 view poses 확인). + feature spec 정정 '
               '123 A110(boss10+washer80 phantom9)→128 DC375(big10+washer71+plate33+outer14, bpc_dc375.yaml, '
               'source feature_positions_master_v4_zlayers). watchdog respawn, .ps1 .bak revert 가능.',
       limitation='measurand 신규 0(기존 산출 enablement). ⚠"washer36/71 E_v 갭"은 STALE(pre-E_v config) — '
                  '2026-06-16 Longinus 관통 결과 E_v in-plane refine 은 이미 배선됨(dc375_lot_pipeline.apply_lot_corrections '
                  'L469, measure_lot L1573 매 lot 호출, frozen v22_hyb3). 실 measure_lot 전체경로 재현(번들+E_v+'
                  'feature_identity_recover): VFEZ0048 washer 71/71, VFEZ0049 70/71(유일 누락 WASHER_019=알려진 specular '
                  '볼트솟음, coverage 아님). 즉 detection coverage 는 해소됨. 잔여 진짜 레버=σ/repeatability(q_tab_threshold '
                  'single-view σ0.061) + specular 맹목(WASHER_019), detection 아님. q_w2prod 와 연계'),
    _n('ltdd_verdict_source_obs', 'progressive', 'field_dc375_128_deploy', m=10, base=10,
       nr=True, nc=True,
       comment='2026-06-16 ooptdd(LTDD) 정식 RED→GREEN(airo_trace/assert_trace 실 oo 라운드트립): BPC 서빙 '
               'verdict-source 4-event 관측화. bpc.measure_lot.applied(진짜)/fallthrough(canonical degrade=GICP '
               'double-fault 전제)/synthetic_placeholder(가짜="검사되는게 없냐" silent-PASS 근원)/merge.gicp_fallback_bpc'
               '(collapse 위험). 현장 oo 1-query로 진짜vs가짜 verdict-source 판별 → 도돌이표 불안에 관측 답. '
               'commit 8549900/52aa68d/b22783f/fdcd664 develop. 정본도구=prism_core/testing/airo_trace.py.',
       limitation='C5 log-free zone: washer_h mm 정밀수치는 L3 비대상(golden+71washer 회귀가 옳은 tier). verdict-source '
                  'contract는 4 event로 완결(RecipeV2/legacy per-path 추가=source 필드 중복=over-instrument STOP). '
                  '현장 첫 PLC 사이클 event 실관측은 배포 대기'),

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
    dict(name='q_dc375_spec128', status='CLOSED',
         body='feature spec 123 A110(washer80 phantom9, outer 없음) → 정본 128 DC375(big10+washer71+plate33+outer14) 정정·빌드',
         closed_by=['field_dc375_128_deploy']),
    dict(name='q_tab_threshold', status='OPEN',
         body='TAB_BOLT 0.5 공차 spec 근거(Mobis/EO 도면 또는 CMM) 확정 + single-view σ0.061 P/T 63% UNACCEPTABLE 해소. '
              '★2026-06-16 분석: min_ng_views≥3 경로는 REFUTED — 71-washer×2lot 실측 coverage = 모든 washer good-view '
              '1~2개(mean 1.4, ≥3 view 보유 washer=0개)이므로 min_ng_views≥3 default 시 ~100% abstain(missing_is_defect→전건 NG). '
              'min_ng_views=2 도 1-view washer(다수) abstain. 즉 σ는 view-gate로 못 푼다(coverage-limited). 남은 viable 2경로: '
              '①per-feature 공차 재도출 ✅코드 배선 LANDED(prismv2 develop 9473b1c): TabBoltStepPolicy.washer_h_tols_mm '
              '(fid→tol map) + _apply_tab_bolt_policy resolve + parser. seed 매핑=washer_h_sigma_per_feature.json '
              '(71feat {nominal_mm,sigma_lot_mm,tol_dyn_mm})→config washer_h_nominals_mm/washer_h_tols_mm. ⚠nuance: '
              'tol_dyn=max(0.5,5.15σ)는 capability FLOOR — 대부분 0.5(σ작아 floor), σ높은 washer만 widen(false-NG 방지, '
              'tighten 아님). 남은=json→Mongo bpc_thresholds seed(ops, 프로덕션 DB write). ②coverage 개선(overlap=q_tab_coverage)→σ↓. '
              '0.5 절대값은 도면/CMM 대기',
         closed_by=None),
    dict(name='q_tab_coverage', status='OPEN',
         body='TAB_BOLT washer detection coverage — "36/71"은 STALE. E_v in-plane refine 이미 배선(apply_lot_corrections L469)→실측 70-71/71(2026-06-16 measure_lot 전체경로 재현). 잔여=①σ/repeatability(single-view σ0.061, q_tab_threshold 연계) ②specular 맹목(WASHER_019 류, 3D blind→RGB-only 필요). detection 갭은 닫힘, σ+specular 가 진짜 OPEN',
         closed_by=None),
    dict(name='q_washer_tail_origin', status='CLOSED',
         body='TAB_BOLT washer_h 반복정밀도 꼬리(ring band [5.5,7.5] p90-p10 1.26mm)의 정체 — 센서노이즈 vs '
              '헥사 볼트헤드 side-wall 기하 오염. 판정: 후자(꼬리의 96.9%=r<6.2 side-wall), ROI inner 5.5→6.2 교정',
         closed_by=['washer_roi_clean']),
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
