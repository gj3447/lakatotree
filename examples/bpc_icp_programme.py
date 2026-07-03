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

from lakatos.quant.metrics import tree_metrics, branch_inputs
from lakatos.programme.stack import evaluate_stack
from lakatos.programme.lifecycle import lifecycle_state
from lakatos.programme.leaderboard import Competitor, leaderboard as build_leaderboard
from lakatos.verdict.certify import gate_check, certify_claim, next_actions
from lakatos.quant.fertility import predictive_fertility
from lakatos.programme.authoring import node

# `_n`(노드 빌더) 정본은 lakatos.programme.authoring.node 로 승격(2026-07-03, 공개 저작 API) —
# 하위호환 별칭 유지: 다른 프로그램들이 `from examples.bpc_icp_programme import _n` 로 계속 쓴다.
_n = node


# ── BPC/ICP 프로그램 트리 (실제 연구사) ──────────────────────────────────────
NODES = [
    # 정본 경로(progressive → CANONICAL)
    _n('prob_statement', 'canonical_stage', None,
       comment='20 BPC 뷰 metric 정합 → DC375 검사 sub-1mm', algo='problem'),
    _n('aruco_metric', 'progressive', 'prob_statement', m=1.60, base=12.0, mn='bpc_seam_selfconsistency_mm',
       nr=True, nc=True, q=['q_markerless_reuse', 'q_aruco_rgb_buffer_confound'],
       comment='ArUco shared-marker Kabsch+BA — 21뷰 1 connected component',
       limitation='격자이웃≠마커공유, dup-ID 가짜다리 주의. 검출 RGB원천=prismv2 자작 read_rgb(SDK無 역공학) → '
                  'q_aruco_rgb_buffer_confound **변별완료 CLOSED**(파서버퍼=SNR프레임 오선택, reader fix 로 부활).'),
    _n('frozen_calib_reuse', 'progressive', 'aruco_metric', m=1.026, base=1.60, mn='bpc_seam_selfconsistency_mm',
       nr=True, nc=True, q=['q_crosslot'],
       comment='board calib 동결→markerless lot 직접 T_view_to_world 재사용(0040→0049 1.384→1.026)',
       limitation='seam=self-consistency, accuracy vs CAD 미검증'),
    _n('v8_pipeline', 'CANONICAL', 'frozen_calib_reuse', m=0.90, base=1.026, mn='bpc_seam_selfconsistency_mm',
       nr=True, nc=True, q=['q_dc375_tol', 'q_outer004', 'q_washer_step', 'q_external_trueness'],
       comment='v8: ZDF stride3 srgb+frozen calib+colfix+v7보정, mesh-exact QC, cross-lot 4.05mm',
       limitation='interior 0.90mm CMM 미검증(precision≠accuracy). ⚠가지→줄기 전파(2026-06-24): v8 QC 는 대칭 '
                  'best-fit(cad_metrology.align_and_deviate) 위에서 편차를 잰다 — DATUM 가지 D3(exposes_hidden_error/'
                  'bestfit_as_drf rejected)가 그 best-fit 이 진짜 위치오차를 21~62% 흡수·은폐(비보수)하고 무오차 피처로 '
                  '누설함을 실 lot 으로 실증. 즉 0.90mm 는 precision 이고, accuracy 추정엔 best-fit 비보수 bias 가 섞여 '
                  '있다 — trueness 엔 GD&T datum-locked DRF + 외부 traceable(q_external_trueness) 필요.'),
    _n('prismv2_frozen_wiring', 'progressive', 'v8_pipeline', m=0.90, base=0.90, mn='bpc_seam_selfconsistency_mm',
       nr=True, nc=True, q=['q_recipev2_gicp_risk'],
       comment='2026-06-16 prismv2 production 배선 관통(Longinus + hitech-expert). v8 frozen-per-view 접근의 실 '
               'materialization = measure_lot Branch0: bpc_inspector_registration._run_measure_lot:334 → '
               'transform_camera_to_cad(frozen T_view_to_world + colfix + v8 + E_v apply_lot_corrections:469) → '
               'per-view feature 검출 → cross-view median fusion, ICP 0회. 즉 사용자 우려 "global view 정합/feature '
               '감지 문제" = GICP free multi-view ICP(prism_core/domain/multiview_icp.merge_views, small_gicp VGICP) '
               'collapse(평판 rank-deficiency: 법선≈+Z→XY/yaw null space yaw고유값 1.4e-4, drift 90-98% null 방향; '
               '+ 주기 포켓 18mm 격자 aliasing 19 local-min STACK→2353mm 부품 876mm 수축). Branch0는 global merged '
               'cloud 자체를 안 만들어 구조적 우회. 실측 washer 71/71 검출 확증.',
       limitation='GICP collapse 노출=GATED/LATENT(정상 현장 0). 현장 5-RPC(CaptureView×N→acc.views[vid] 채움→FinalizeCycle)는 '
                  'Branch0 기동 + _should_concat_by_transform(stage_merge.py) 게이트가 camera_transform real이면 concat(frozen). '
                  'Branch0 verdict는 merge cloud와 독립. 노출=이중fault(FS2 unwired→silent GICP ∧ Branch0 fail→RecipeV2 GICP cloud). '
                  'grpc single-shot(acc.views={})은 legacy RunInspection. per-view SYSTEMATIC residual(partial-arc 0.5-1.3mm '
                  'class-dep)은 E_v multi-lot solve로 흡수(sub-mm, collapse 아님). '
                  '회피=register_concat(frozen concat, ICP無) 강제 또는 FinalizeCycle 경로 Branch0 보장'),
    _n('placement_pose_robust', 'progressive', 'v8_pipeline', m=0.90, base=0.90, mn='bpc_placement_pose_mm',
       nr=True, nc=True,
       comment='E2E placement/pose 강건성 (29_E2E_PLACEMENT_POSE_ROBUSTNESS.md, run_new_lot v12.2 oracle '
               'bit-identical, 사전등록 채점). ★사용자 질문 답: 부품/디멘션이 "왓다갓다" 해도 washer_h 등 '
               'RELATIVE 측정류는 datum-invariant라 강건. 실측: washer_h re-center 0.033mm; 상대측정'
               '(washer_h/boss_h/r_eff) p95 0.060-0.103mm @ 1.4mm+0.15° placement 섭동 & σ0.1mm per-view pose '
               'jitter(실측 lot-sd 0.02-0.065의 2-5배 가혹); **verdict flip 0**. 부품 z=z-net per-lot selfsolve '
               '0.026-0.063. 부품 XY+회전=reanchor SE(2) P_l(prismv2 test_estimate_part_placement_recovers_se2 '
               '0.01°/0.05mm 회복): 2-5mm/0.5° native ROBUST · 10-20mm RESCUED(rec≤0.05) · 1-3° MARGINAL(flip1) · '
               '5°+ BREAK(한계=3°와5° 사이, seg inlier 끝단 절단). prismv2 fe653fa→2c1c4c1(reanchor)→b652c1a.',
       limitation='절대 center 위치만 σ0.1+ pose jitter서 0.26-0.31mm(1뷰 feature yaw 레버) — 운영 스케일(lot-sd '
                  '0.02-0.065)선 0.05-0.15mm 사실상 강건. per-view free XY selfsolve=REJECTED(계통 부분호 편향 교락 '
                  '0.26→0.73 악화). 즉 측정값은 강건, 절대 위치만 1뷰 feature서 상속 — washer_h(상대) 0.04mm급 정밀도는 '
                  '왓다갓다에 불변.'),

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

    # ── 2026-06-24 궤도: SEG→SEM 라벨 partition A-D 검증 (생산 라벨링 무결성) ──
    _n('seg_sem_partition', 'progressive', 'v8_pipeline', nr=True, nc=True, q=['q_seg_sem_canonical'],
       comment='instance seg(COCO overlap) → 1-of-N semantic partition A-D 검증(scripts/seg2sem_partition_remap.py 등). '
               'CAD-geom 으로 메커니즘 CONFIRMED: C1 whole(BPC) footprint 가 part feature 168/168 포함(dual-membership '
               '38205px), C2 argmax remap 후 multi-membership 37824→0px, C3-a 2D CC instance==CAD count 5/5클래스(delta0), '
               'z-layer 19 CAD vs 1 2D CC=다층 2D 불가(천장). evidence/seg_overlap_iou_matrix_20260624.json + '
               'seg_vs_sem_zlayer_separability_20260624.json (적대검증 confirmed, 무커밋).',
       limitation='★C1 canonical hand-label = 2026-06-24 CONFIRMED(diamondperl coco_v3 rsync): 실 라벨 28img·424 feature inst, '
                  'feature 픽셀 99.66% dual-membership·median containment 1.0 (v6 3dtruth 99.67%·458inst 동일) → CAD-geom 아닌 '
                  '실 라벨러 데이터서 overlap 실재 확증. evidence/seg_vs_sem_C1_canonical_handlabel_20260624.json. '
                  '★C3-a v3 모델 instance recovery = 2026-06-24 CONFIRMED(diamondperl bpc_seg_v3 best.pt, bead_trt ultralytics, '
                  '42 eval img CPU): feature instance pred/GT 1.02×(CUP43→46·EXT74→73·OUTER44→44·PLATE89→93·TAB207→210) → '
                  '모델이 라벨 인스턴스 회수 + semantic partition 이 인스턴스 보존. evidence/seg_vs_sem_C3a_model_cc_recovery_20260624.json. '
                  '남은 BLOCKED: C3-c 3D-fusion 비퇴행 회귀(96/128 p50 2.2mm)=production 3D fusion 파이프라인+zdf 필요(무거움·fleet 영역). '
                  '★날짜형상 함정(DATE_SHAPE_MAP_20260624.md): PLATE_HOLE Y 06-17 전후 다름 → 교차날짜 trueness/3D-fusion 은 그룹화 필수. '
                  'precision≠accuracy 잔존(2D 라벨 무결성 ≠ 3D 측정정확도).'),

    # ── 2026-06-24: frozen_calib_reuse domain 한계 실증 (cross-era calib mismatch) ──
    _n('calib_geometry_mismatch', 'degenerating', 'frozen_calib_reuse', m=8.0, base=1.026, scope='registration',
       nr=True, nc=False, q=['q_calib_geometry_gate'],
       comment='frozen_calib_reuse domain 한계 실증: VFEZ0040(group-A) calib을 PLATE_HOLE 변경 後 group-B(VFQZ 06-17)에 '
               '하드코딩 적용(run_new_lot:42, 날짜/형상 게이트 0) → 정합 어긋남, 같은 컵 boss_h 캡처간 8mm 출렁(BIG_04 −35mm), '
               'peel/탭볼트 verdict 출렁=reproducibility 위반(사용자 catch). VFEZ(matched) σ≤0.15 대비 명백. '
               'CALIB_GEOMETRY_MISMATCH_PROM_20260624.md.',
       limitation='검출 알고리즘은 무결(VFEZ 안정)—문제는 calib 입력. ★fix RESOLVED(group_b_calib_resolve, 2026-06-25): '
                  'group-B 보드 calib을 **기존 데이터(VFQZ0016~0024 board lot)** 로 재솔브 성공(재촬영 0). §7 "VFQZ markerless→재촬영 '
                  '필요"는 VFQZ0040 단일표본 일반화 오류였음(보드는 0016~0024에 있었음). 임시 게이트(calib_era_binding/'
                  'CALIB_GEOMETRY_GATE_PATCH)는 systemic fix로 유지. group-B 철회분은 group-B calib 재측정으로 복구 중.'),

    # ── 2026-06-24: group-B 해법 = markerless camera-spec 측정 (사용자 "보드말고 카메라스펙", 검증됨) ──
    _n('markerless_camera_spec_measure', 'progressive', 'v8_pipeline', m=0.028, base=0.90,
       scope='measurement', mn='bpc_markerless_camera_spec_z_mm',
       nr=True, nc=True, q=['q_calib_geometry_gate'],
       comment='calib-era 우회 해법(사용자 지시 "보드 재촬영 말고 카메라스펙"): measure_washer_markerless.py = Hough 홀검출 '
               '+ organized cloud pixel→3D per-frame LOCAL 측정(ArUco/calib/CAD-align 0). VFQZ0010(group-B)서 검증: 21뷰 '
               'washer 229검출 radius med 4.48mm·flush med 0.01mm(=탭볼트 안착 결함신호). calib 없어 era 무관·부품형상 무관 '
               '→ group-A/B 균일측정. 교시 why_markerless 검증 PLATE z 0.028mm/r 0.004mm·BIG z0.116. '
               'evidence/markerless_camera_spec_VFQZ0010_20260624.md.',
       limitation='per-frame LOCAL = global feature-ID 매핑 없음(결함 스크리닝엔 충분, reproducible·era문제0). cup peel은 '
                  'markerless_register.py(boss-constellation→CAD boss Kabsch)로. global 정밀 metrology 필요시에만 보드 calib. '
                  '★한계 실측(markerless_ng_label_feasibility): 전 필드 lot이 pose당 1프레임=frame기아 → feature당 <6뷰 '
                  '→ markerless 정밀집계 UNCONFIRMED + positive control(VFEZ0040 peel) 미검출. NG/normal 정밀라벨은 이 경로 단독 불가 '
                  '→ group_b_calib_resolve(ArUco)가 실효 경로.'),

    # ── 2026-06-25: group-B ArUco calib을 기존 보드 lot으로 재솔브 (실효 fix, 재촬영 0) ──
    _n('group_b_calib_resolve', 'progressive', 'calib_geometry_mismatch', m=0.266, base=8.0,
       scope='registration', mn='group_b_marker_resid_rms_mm',
       nr=True, nc=False, q=['q_calib_geometry_gate'],
       comment='calib_geometry_mismatch fix: group-B(06-17 PLATE_HOLE 변경 後) calib을 **기존 데이터**로 재솔브. '
               '몽타주 시각스캔서 VFQZ0013에 마커 발견→재검: VFQZ0016~0024 = 보드 20/21뷰·~99 distinct ArUco ids(완전 보드). '
               'hitech_aruco_puzzle_assemble VFQZ0016 → placed 20/20, marker rms 0.266mm·seam 1.001mm (VFEZ0040 0.42mm보다 우수). '
               'C3 메커니즘 CONFIRMED: 이 calib으로 VFQZ0010 측정 시 wrong-calib의 BIG_04 −35.43mm garbage가 −5.22mm sane peel로 '
               '복원, boss_h 전부 −7.1~+4.5 정상범위. 재촬영·markerless 둘 다 불필요(사용자 "재촬영 안 함" 옳았음). '
               'evidence/c3_groupB_calib_solved_20260625.md.',
       limitation='base calib(seam 1.0mm, zwarp/zconst 미적용) — gross NG(peel −5~−7·결손)엔 충분, <1mm 정밀안착엔 z-chain(215/216/219) '
                  '추가 필요. σ(재현성)·onset·per-lot NG/normal = 67 VFQZ+5 VFRZ 시간순 batch 진행 중(gbbatch).'),
]

FRONTIER = [
    dict(name='q_markerless_reuse', status='CLOSED', body='markerless lot 에 board calib 재사용 되나',
         closed_by=['frozen_calib_reuse']),
    dict(name='q_crosslot', status='CLOSED', body='cross-lot per-view T 전이 <5mm',
         closed_by=['v8_pipeline']),
    dict(name='q_dc375_tol', status='OPEN', body='interior 0.90mm 가 DC375 공차 T0 에 충분한가', closed_by=None),
    dict(name='q_outer004', status='OPEN', body='OUTER_004 분기 — outer hole 검출 커버리지', closed_by=None),
    dict(name='q_washer_step', status='OPEN', body='washer step +0.83mm 진짜인가 artifact 인가', closed_by=None),
    dict(name='q_aruco_rgb_buffer_confound', status='CLOSED', closed_by=['reader_frame_provenance_fix'],
         body='ArUco 검출오염 confound(캡처설정 vs 파서버퍼) → **변별 완료: 파서버퍼**. crucial experiment ③(알려진 '
              'zdf 디코드 검증)이 결정적 결과로 수행됨 — read_rgb 가 색프레임을 byte-length 만으로 골라 SNR float32 맵'
              '(N×4B)을 진짜 색(N×16B) 대신 uint8 캐스트하던 frame-select 버그를 grounded 로 확정([[reader_frame_'
              'provenance_fix]]: _looks_like_snr_float 가드 + float-first 선택). **재촬영·Settings2D 변경 0으로** 디코드만 '
              '고쳐 마커가 부활(SX3i 34/40뷰, LX3 usable 8→61) = "캡처문제(Settings2D 누락)" 경쟁가설 결정적 반증'
              '(마커가 미캡처였다면 디코드 수정으로 부활 불가). 즉 오염원=파서가 잘못된 버퍼 추출. '
              '잔여(non-reopen): 공식 Zivid SDK byte-parity(①)는 SDK 부재로 미실행이나 부활 결과가 이미 confound 를 '
              '변별했으므로 닫힘. 디코드 미세 정합성(side/stride/PRGB·RB스왑)은 별개 finer 질문. '
              '2026-06-24 사용자 staleness 지적 수용, 발원 [[lx3-laptop-zivid-prismv2-conn]] read_rgb 역공학.'),
    dict(name='q_recipev2_gicp_risk', status='OPEN',
         body='GICP collapse 노출은 GATED/LATENT(정상 현장=노출0). 게이트=_should_concat_by_transform(stage_merge.py): views camera_transform real(FS2 dimconfig frozen pose)면 concat_by_transform(frozen,safe), all-identity(mock/FS2 unwired)면 legacy GICP merge_handles. 또 Branch0 verdict(per-view frozen)는 merge cloud와 독립이라 backend 무관. 노출=이중fault((a)FS2 unwired→silent GICP merge ∧ (b)Branch0 fail(bundle無)→RecipeV2가 GICP cloud로 verdict). 미티게이션 ✅LANDED(ooptdd RED→GREEN, prismv2 develop 8549900): concat→GICP silent fallback 시 BPC면 구조화 event merge.gicp_fallback_bpc 방출(stage_merge.py). LTDD: RED=airo_trace L3 oo 라운드트립 미방출 FAIL→GREEN=assert_trace oo 도착확인(C3 구조화). 동작불변·알람만',
         closed_by=None),
    dict(name='q_seg_sem_canonical', status='OPEN',
         body='SEG→SEM partition 이 정식 hand-label IoU·v3 모델 CC회수·3D-fusion 회귀에서도 검증되는가. '
              '★2026-06-24 4/4 디멘션 답함: C1(overlap 실재)=실 hand-label CONFIRMED(99.7% dual·median 1.0), '
              'C2(sem 제거)=CONFIRMED(argmax 37824→0px), C3-a(v3 모델 instance recovery)=CONFIRMED(1.02× GT, 42 eval), '
              'C3-c(3D-fusion 비퇴행)=구조적 CONFIRMED — production 측정=CAD-anchor+해석적마스크(seg 의존 제거 46facb4), '
              'run_new_lot smoke 128/128 CAD-anchor(dxy_nom p50~2.2mm) → seg→sem 라벨변경이 측정 소비경로에 없음. '
              'evidence/seg_vs_sem_{C1_canonical,C3a_model_cc_recovery,C3c_measurement_independence}_20260624. '
              'caveat(가짜green 금지): seg vs CAD-anchor 직접 A/B 측정은 미재구동(저번주 lot↔파이프라인 미 co-location), '
              '단 측정이 seg 미소비라 A/B 차=0 이 구조적 귀결. 전제: 날짜형상 그룹화(DATE_SHAPE_MAP). '
              '(read_rgb 버퍼버그와 별건 — BPC 는 다른 stride 이슈.)',
         closed_by=None),
    dict(name='q_calib_geometry_gate', status='OPEN', closed_by=None,
         body='형상 era별 calib 바인딩+게이트로 cross-era silent garbage 차단 + group-B 측정경로 확보. '
              '2026-06-24: ✅Longinus calib_era_binding·✅게이트패치 스펙. '
              '★해결: group-B는 **markerless camera-spec 측정(markerless_camera_spec_measure, 검증됨)**으로 calib 없이 측정 가능 '
              '→ 보드 재촬영 불필요(=사용자 지시). ArUco SOLVER_PKG 경로만 era-lock; markerless 경로는 group-A/B 균일. '
              '잔여: VFQZ/VFRZ 전 lot markerless 일괄 → NG/normal 라벨 → Longinus 등록(진행 가능).'),
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
