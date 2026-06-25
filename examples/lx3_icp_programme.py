"""Dogfood — PRISM-LX3 서브프레임 검사를 3D 형상 검출 트리의 가지로 모델링.

3D 형상 검출(3D-shape detection from 3D data) 통합 프로그램의 LX3 가지.
BPC 줄기(examples/bpc_icp_programme)에서 **`aruco_metric` 마디에 피어난다**. 초기엔 자동차
서브프레임에 마커가 없다 가정해 *측면 분기*(CAD surface-match anchor + cylinder-fit)했으나,
**2026-06-22 피벗: 서브프레임에 MIP_36H12 ArUco 마커 부착 + 턴테이블 회전 촬영(LX3RT)** →
BPC 와 같은 fiducial 정합 계열로 복귀(과거 "마커 不在" 가정 폐기). markerless 분기는
음의 결과(자동경로 ceiling)로 보존한다.

★실측 가지(BPC 와 달리 측정 완료):
  - (2026-05-18) GROUND_TRUTH self-verify R&R σ=36.8µm, AIAG MSA P/T 22.08% 🟢ACCEPTABLE — BPC-grade σ(progressive).
  - (markerless 자동경로) ceiling: HALCON SurfaceMatch=license blocked, ArUco init=data missing(degenerating).
  - (markerless ICP) 28pair rmse 4.35-5.77mm = identity-init basin = BPC free-ICP collapse 재확인(degenerating).
  - ★(ArUco-턴테이블, LX3RT MIP_36H12) 검출 = 2026-06-24 grounded **progressive**. 정정 3겹: 옛 "119/121"의 COUNT 은
    buggy read_rgb 가 SNR 맵을 색으로 오선택한 노이즈였고 / 그 다음 "markers≈0 하드한계" 판정은 brightening 미적용 탓 /
    **진실**=고친 색프레임+gamma0.4+CLAHE+default 로 24뷰중 23뷰·≥3뷰반복 MIP_36H12 ID 10종·side_px 60px(육안확인).
    어두움=전처리로 풀리는 문제지 하드한계 아님. enabler CLOSED(검출). 단 정합 *정확도* sub-mm 는 OPEN(검출≠정확도).
  - ★(2026-06-23 grounded, q_lx3_aruco_accuracy OPEN 유지): 정합 LSQ=FAILED(id-collision로 8마커/14쌍 starved,
    LM degenerate·precision 1193mm 발산); 독립 부시-vs-CAD 정확도=측정됐으나 OVER_TOL(FRT거리 -2.34mm>±1.0mm,
    더구나 단일 정면station=ArUco 정합 우회). precision(반복도 0.19mm)≠accuracy. → 가짜green 금지, OPEN 정직.

정본 사양: /data/kjra/PROJECT/3D/LX3_ICP_SPEC/{README,PRODUCTION_REPORT}.md
실행: python -m examples.lx3_icp_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics
from examples.bpc_icp_programme import _n, NODES as BPC_NODES, FRONTIER as BPC_FRONTIER

# 이 가지가 BPC 줄기의 어느 마디에서 피어나는가. (ArUco 정합 결정점 — LX3 도 이제 fiducial 정합)
BLOOM_AT = 'aruco_metric'

# ── LX3 가지 노드 (실측) ─────────────────────────────────────────────────────
BLOOM_NODES = [
    _n('lx3_prob', 'canonical_stage', BLOOM_AT, algo='problem',
       comment='PRISM-LX3 자동차 서브프레임 hole 검사(tol ±1.0mm pos / ±2.0° perp, 18 feature: '
               '6 confirmed + 12 bolt placeholder). 초기 "마커 不在" 가정 → markerless CAD surface-match '
               'anchor + cylinder-fit 시도. 2026-06-22 피벗: MIP_36H12 ArUco 마커 부착 + 턴테이블 회전 '
               '촬영(LX3RT)으로 fiducial 정합 복귀.',
       limitation='"마커 不在"는 폐기된 초기가정 — 이제 ArUco-턴테이블이 1차 정합 enabler, '
                  'markerless(CAD anchor/HALCON SurfaceMatch)는 보존된 음의 분기.'),

    # 실측 정본 후보 가지 (oracle anchor 기준)
    _n('lx3_groundtruth_oracle', 'degenerating', 'lx3_prob', m=0.0368, base=None, scope='measurement',
       nr=True, nc=True, q=['q_lx3_full_surface_anchor'],
       comment='GROUND_TRUTH self-verify: R&R σ=36.8µm, AIAG MSA P/T 22.08% 🟢ACCEPTABLE(±1.0mm). '
               '12측정 11 OK+1 NG. BPC-grade σ 도달 — production GROUND_TRUTH 는 이미 sub-mm. '
               '★라이브엔진 reconcile(2026-06-24, LakatosTree_LX3_PLACEHOLDER): 원저자 라벨 progressive → '
               '엔진 judge 판정 **degenerating**. 이유=oracle/수동 anchor 는 자동 프로그램을 전진시키는 novel 예측이 '
               '아닌 베이스라인(anomaly 없음) → MSRP상 비진보. 측정 자체는 유효(σ ACCEPTABLE)이나 프로그램 진보는 아님.',
       limitation='oracle/수동 anchor 기준 — 자동 정합 경로 아님(lx3_auto_path_ceiling 참조). precision≠accuracy.'),
    _n('lx3_cylinder_fit', 'partial', 'lx3_groundtruth_oracle', m=0.39, base=None, scope='measurement',
       nr=True, nc=False, q=['q_lx3_gauge_boundary'],
       comment='hole 중심=cylinder fit. mean pos dev 0.39mm part-wide sub-mm. '
               '5-gate: G1 rigid / G2 hole-align / G3 local-min audit / G4 signed-dist / G5 noise-floor. '
               '★라이브엔진 reconcile(2026-06-24): 원저자 progressive → 엔진 **partial**. 이유=novel 미확인(nc=False)·'
               'excess empirical content 없음 → sub-mm 달성하나 초과내용 없는 부분진보.',
       limitation='B_LH 0.999→1.067mm tol-경계 flip = gauge 위태(σ shift 시 verdict 뒤집힘).'),

    # ★2026-06-24 grounded(검출) — ArUco-턴테이블 마커는 brightening 으로 실재·검출됨(progressive)
    # ★엔진 reconcile(2026-06-24, 엔진에 올라탐): 손입력 progressive → record_judge **partial**
    _n('lx3_aruco_turntable', 'partial', 'lx3_prob', m=4.2, scope='detection',
       nr=True, nc=True, q=['q_lx3_enabler'],
       comment='ArUco-턴테이블 정합 경로(LX3RT_20260622, MIP_36H12). 정정 이력: (1) 옛 "119/121 검출, id-collision"의 '
               'COUNT 은 buggy read_rgb(b09b2b2)가 SNR 맵을 색으로 오선택한 노이즈(무작위 ID→>1.4m span)였음. '
               '(2) 그 다음 "markers≈0 하드한계" 판정도 틀림 — brightening 미적용 탓. (3) **grounded 진실**(고친 색프레임 '
               '+ gamma0.4+CLAHE + default params): 24뷰 중 23뷰 검출·평균 4.2/뷰·**≥3뷰 반복 MIP_36H12 ID 10종**'
               '(8,28,31,76,109,123,159,173,197,248)·side_px median 60.5px, 오버레이 육안확인. 턴테이블 회전에 같은 ID 가 '
               '반복=실 마커(노이즈 아님). 어두운 씬(mean≈10/255)은 **전처리로 풀리는 문제지 하드한계 아님**(사용자 지적 정확). '
               'grounded record=evidence/lx3_aruco_detect_refixed_20260624.json.',
       limitation='검출만 grounded. 정합 *정확도* sub-mm(±1.0mm)는 미측정=OPEN(q_lx3_aruco_accuracy) — 옛 turntable LSQ 는 '
                  '리더 노이즈 위에서 돌아 FAILED 였으니 corrected 검출로 재실행 필요. 수율 modest(4/뷰)라 노출↑ 재촬영이 '
                  '강건성엔 도움되나 필수 아님. ⚠️relaxed params/equalize 는 FP 과증폭(100+/뷰) — default+gamma/CLAHE 만 신뢰.'),

    # ★2026-06-24 결정타 — dict 정정: 마커는 MIP_36H12 아니라 DICT_4X4_250 (lx3_aruco_turntable 의 dict 식별 정정)
    # ★엔진 reconcile(2026-06-24): 손입력 progressive → record_judge **partial**(dict4x4 record 부여 후 자동판결)
    _n('lx3_aruco_dict4x4', 'partial', 'lx3_aruco_turntable', m=61.0, base=8.0, scope='registration',
       mn='lx3_markers_usable_count',  # 마커 *개수*(higher) — 거리 metric 과 다른 family (이질 metric 분리)
       direction='higher', nr=True, nc=True, q=['q_lx3_aruco_accuracy'],
       comment='lx3_aruco_turntable 가 "마커 실재"는 맞췄으나 **dict 를 MIP_36H12 로 오식별**했다. 진짜 dict = '
               '**DICT_4X4_250**. 비트단위 증거(반박불가): v60 실 마커를 정사영 보정→6×6 샘플 시 테두리 전부 검정(4×4 ArUco '
               '요건)이고 내부 4×4 비트가 표준 DICT_4X4_250 id56 과 **완전 동일** [[0,1,1,0],[0,0,0,1],[0,0,1,0],[0,1,0,0]] '
               '(evidence/lx3_marker_dict4x4_proof_20260624.png 패널·6×6 MIP id109 와 시각적으로 명백히 다름). MIP 의 "반복 ID '
               '8,109,123,…"은 6×6 디코더가 4×4 마커를 체계적으로 오독한 것 → 바로 그래서 3D 상 >1m 흩어진 "id-collision". '
               'DICT_4X4_250 로는 cross-source Jaccard 0.81(=SX3i 정상대조군급)·121뷰 2195 안정검출. detect_lift_4x4.py(decoder '
               'color)→lx3_turntable_register: n_markers_usable 8→61, view-pair 제약 starved(<30)→43867, success False→True. '
               '정본 evidence/aruco_via_zivid_sdk_verdict_20260624.md (Zivid SDK 2.17.2 타워빌드, env zivid).',
       limitation='정밀도 미해결(q_lx3_aruco_accuracy OPEN, 가짜green 금지): precision_rmse 429mm·최선 단일마커 클러스터 18mm. '
                  '원인은 더 이상 dict/검출 아님 — ①DICT_4X4_250 도 id-collision(같은 id 가 부품 여러 물리위치, 특히 회전축 X '
                  '방향=un-rotate 불변) ②흰 마커면 Zivid 3D 리턴 약함(~18mm 중심노이즈). 다음 수=marker-free 축(turntable_full)으로 '
                  'un-rotate 후 per-id 공간클러스터(collision 분리)+코너 plane-fit 리프트. 3D-direct 밀집정합(CAD fitness0.72)이 '
                  '정밀도 더 견고 → corrected ArUco 는 init/검증용. 단 enabler(검출)는 재촬영 없이 기존 lot 에서 확보됨.'),

    # ★2026-06-24 독립검증 + 정밀도 grounded — corner 3D sub-mm 확정 + known-axis 정합 self-consistency 513mm→0.99mm
    # ★엔진 reconcile(2026-06-24): 손입력 progressive → record_judge **partial**(임계초과·novel 초과내용 없음)
    _n('lx3_aruco_knownaxis_precision', 'partial', 'lx3_aruco_dict4x4', m=0.99, base=513.4, scope='registration',
       mn='lx3_register_selfconsistency_rms_mm',  # 정합 자기일관성 RMS(mm, lower) — 자체 family
       direction='lower', nr=True, nc=True, q=['q_lx3_aruco_accuracy'],
       comment='타워 Zivid SDK 2.17.2(소스빌드 cp39/cp310, OpenCL nvidia.icd OK) 깨끗한 rgba+gamma0.45+DICT_4X4_250 독립 '
               '재현: 121뷰 2088검출·60 distinct id·17.3마커/뷰(≈dict4x4 의 18/뷰, 강한 교차확인). **코너 3D sub-mm 확정**: '
               '변 median 50.0mm·within-id σ 0.37mm(naive 5×5)~0.96mm(plane-raycast)·평면 residual 0.9mm·대각/변 1.417≈√2; '
               '서로 다른 3개 3D방법(49.77/49.685/49.78mm)+6에이전트 적대워크플로(verify-aruco-50mm) 수렴=단일버그 면역. '
               '**정밀도 grounded**: self-cal 6DOF(13m 발산) 대신 robust 단일축(SVD chord-null dir + lstsq (I-R)a=P\'-RP pt, '
               '턴테이블 3°/뷰)+per-id declustering → self-consistency RMS median **0.99mm**·p95 2.4mm(59 물리트랙·2017점 '
               '전부<5mm). 음성대조: 틀린축(수직)=64mm. prior 513mm(13m garbage 축)·429mm 대비 ~500×. '
               '정본 evidence/lx3_aruco_{50mm_independent_verify,register_precision_knownaxis}_20260624.json.',
       limitation='이것은 PRECISION(반복도)이지 ACCURACY 아님 — 부시(독립피처) vs CAD nominal ±1.0mm 미측정(q_lx3_aruco_accuracy '
                  'OPEN 유지). dict4x4 한계 "②흰면 3D약(~18mm)" 은 본 노드가 **반증**(코너3D=sub-mm; 18mm/429mm 는 흰면 아니라 '
                  'self-cal 발산이 원인; id-collision 도 부차적=no-decluster 도 1.0mm·64id→59track). '
                  '★accuracy ATTEMPT(2026-06-24, evidence/lx3_aruco_cad_register_accuracy_attempt): 신뢰축으로 121뷰 융합'
                  '(isolate_turntable_part)→CAD 형상정합 실행=lx3_registered_bush_accuracy 가 "registration_axis_available:false"로 '
                  '**실행조차 못했던 경로를 실행가능**하게 만듦(진보). 그러나 fused part 가 잔여 정적배경(perp 링 r700+축방향 spread, '
                  'motion-isolation 불완전 제거)으로 오염→CAD 정합 median 21mm·fitness 0.36=**±1mm 미달**, 부시 accuracy 미측정. '
                  '⇒accuracy 는 **여전히 OPEN**(가짜green 금지): 남은 병목=co-located 배경 잔여 제거+표면 커버리지+CAD 부시 1:1 매핑. '
                  '(DeepArUco++ 사전학습=실코너 OOD near-constant 6px WORSE(팀 BPC verdict 도 WORSE)=재학습 필요; '
                  'Blackwell GPU 는 torch cu128 정상=옛 cu117 garbage 경고 무효.)'),

    # ★2026-06-24 CAD-side 정확도 기준값(ruler) — STEP_REORIENT→LX3_LOCAL 변환 + 4부시 nominal (docs/10 미해결 #5)
    # ★엔진 reconcile(2026-06-24): 손입력 progressive → record_judge **partial**
    _n('lx3_cad_bush_nominal', 'partial', 'lx3_aruco_knownaxis_precision', m=0.064, scope='cad_frame_map',
       direction='lower', nr=True, nc=True, q=['q_lx3_aruco_accuracy'],
       comment='정합 정확도의 *기준값(ruler)* 도출(CAD-only, 스캔 무관 — docs/10 미해결 항목 #5 STEP_REORIENT→LX3_LOCAL). '
               'STEP_REORIENT 4부시 + LX3_LOCAL 3부시(알려진 1:1 대응)로 Kabsch → **rigid 확정(resid 0.064mm·거리보존 0.000mm)**. '
               '미지였던 FRT_RH(LX3_LOCAL)=(-921,950,140) 도출. 정본 부시간 거리: RR쌍 805·RR-FRT 942.8·FRT쌍 1094mm. '
               '★독립 교차검증: 도출 FRT쌍 1094.0mm vs 측정 nominal 1093.3mm = **0.70mm 일치**(<±1.0mm tol). '
               'grounded record=evidence/lx3_bush_nominal_lx3local_20260624.json.',
       limitation='정확도 *기준값*(CAD nominal)이지 정확도 *측정* 아님 — q_lx3_aruco_accuracy 닫으려면 '
                  'lx3_aruco_knownaxis_precision 포즈로 정합한 스캔 부시를 이 기준에 대보아야(±1.0mm). 기준은 이제 준비됨(ruler ready).'),

    # ★2026-06-24 사용자 입력 CMM workbook — 외부 기준값 확보. 단 매핑/scan-vs-CMM trueness 는 아직 OPEN.
    _n('lx3_cmm_reference_available', 'equivalent', 'lx3_cad_bush_nominal', m=5.0, base=5.0,
       scope='external_reference', mn='cmm_specimen_count', direction='higher',
       nr=True, nc=True, q=['q_lx3_cmm_mapping', 'q_lx3_external_trueness'],
       comment='LX3 CMM reference record 확보(input/lx3/260622 LX3 FRT SEMI MODULE 인덱스별.xlsx). workbook 은 '
               '스프레드시트 셀이 아니라 embedded report image 5장이라 수동 전사로 v1 record 화. provisional mapping: '
               'image1..5 → CMM id 127..131. CMM sample count 5/5 로 external-trueness 작업의 기준값은 준비됨. '
               'record_judge verdict=equivalent(기준값 확보 자체는 새 정확도 성취가 아니라 측정 전제 충족). '
               'CMM 자체 NG 후보: provisional 130 에서 B LH X dev +1.218mm, FRT BODY RH BUSH Z dev -1.067mm '
               '(inferred ±1.0mm gate 초과). grounded record=evidence/lx3_cmm_reference_20260624.json.',
       limitation='이 노드는 scan-vs-CMM trueness 를 닫지 않는다. prompt 의 촬영 순서(127 360도/121뷰, 이후 127~131 60뷰)와 '
                  '실 scan lot/index 를 먼저 reconciliation 해야 한다. 그 뒤 DRF-locked 또는 face-aware per-bush scan 치수를 '
                  'CMM 값과 feature/axis 별로 비교해야 q_lx3_external_trueness 를 닫을 수 있다.'),

    # ★2026-06-24 lot↔CMM 매핑 확정 — q_lx3_cmm_mapping 닫음 (view-count+시간순 = prompt 촬영계획 정합)
    # ★엔진 reconcile(2026-06-25): 손입력 progressive → record_judge **equivalent**. lot↔CMM 매핑은
    #   외부 trueness 측정의 *전제*(어느 scan 이 어느 CMM specimen 인지 확정)이지 새 정확도 성취가 아님
    #   → lx3_cmm_reference_available 와 같은 equivalent(측정 전제 충족). 자기채점 progressive 제거.
    _n('lx3_lot_cmm_mapping', 'equivalent', 'lx3_cmm_reference_available', m=5.0, base=0.0,
       scope='lot_cmm_reconciliation', mn='sessions_matched_to_cmm_id', direction='higher',
       nr=True, nc=True, q=['q_lx3_external_trueness'],
       comment='scan capture session 의 .zdf view-count + 디렉터리 시간순이 prompt 촬영계획과 **1:1 정합** → lot↔CMM 확정. '
               '153439=121뷰(lot 127 360°) · 160114/162343/164447/171253/173509=각 60뷰(lot 127/128/129/130/131) · '
               '153129=3뷰 setup. "121 + 5×60" 패턴이 prompt 와 정확히 일치. CMM 보고 frame = **3-2-1 datum(LX3_LOCAL)** '
               '= prompt 의 "321 좌표계"(FRT_LH(-921,-144,140)·RR_RH Y=805). CMM truth: 127·128·129·131 PASS(≤1.0mm), '
               '**130 NG(B_LH X +1.218·FRT_BODY_RH_BUSH Z -1.067mm)**. grounded record=evidence/lx3_lot_cmm_mapping_20260624.json.',
       limitation='lot 절대숫자(prompt "27? 인가 127")는 라벨 — scan-vs-CMM 엔 ordinal 1:1(1~5번째 60뷰↔CMM specimen, '
                  'view-count+시간으로 확정)이면 충분. q_lx3_external_trueness 는 여전히 OPEN: 확정 lot 별 scan bush 치수를 '
                  '같은 CMM specimen 과 feature/axis 대조해야 닫힘(현재 scan accuracy 21mm = 그 전 단계 part/jig 분할).'),

    # ★2026-06-25 ABCDE pair-only scan-vs-CMM sweep — *물리 LX3 부품*이 아니라 pair-only estimator 경로 판정.
    # ★엔진 record_judge **rejected**(손입력 0, lx3_engine_judged.py 와 동일 record): 사전등록 |scan−CMM|≤1.0mm·
    #   kill=>1.0mm 인데 5쌍 중 4 NG·max 2.687mm → 반증. (이전엔 손입력 모듈에 노드 자체가 누락 = 정본 미스왑)
    _n('lx3_pair_only_cmm_sweep', 'rejected', 'lx3_lot_cmm_mapping', m=2.687, base=1.0,
       scope='scan_vs_cmm_trueness', mn='max_abs_scan_minus_cmm_pair_distance_mm',
       direction='lower', nr=True, nc=True, q=['q_lx3_external_trueness'],
       comment='ABCDE(127→repeat→128 boundary→130 NG challenge→production-gate) pair-only sweep: 단일 정면 station '
               'FRT_LH–FRT_RH 쌍거리만으로 scan−CMM trueness 시도. 사전등록 예측 |scan−CMM|≤1.0mm·kill=>1.0mm. '
               '결과 pair residual(mm) 127 −1.513·128 −2.687·129 −0.833·130 −2.011·131 −2.118 → 5쌍 중 **4 NG**, '
               'max 2.687mm. 반복성은 있으나 CMM-true 아님 → pair-only estimator 경로는 promote 금지(음의 결과 보존). '
               'grounded record=evidence/lx3_abcde_scan_cmm_board_20260625.json.',
       limitation='full-XYZ·registration 없는 fixed-ROI pair-only 한계(quality_flags: partial_pair_only/no_full_xyz/'
                  'no_registration). q_lx3_external_trueness 는 여전히 OPEN — face-aware per-bush DRF-locked 치수를 '
                  'CMM feature/axis 별로 대조해야 닫힘. 본 노드는 그 전단계 estimator 의 음의 결과다.'),

    # 퇴행 가지(보존) — BPC 줄기 hard-core 재확인 + markerless 자동경로 한계
    _n('lx3_identity_basin', 'rejected', 'lx3_prob', m=4.35, base=None,
       comment='markerless multi-view ICP 28 pair rmse 4.35-5.77mm cluster = identity-init basin. '
               '"진짜 R&R 아님" — BPC free-ICP collapse(평판 rank-deficiency) 교훈을 LX3 형상에서 재확인. '
               '★라이브엔진 reconcile(2026-06-24): 원저자 degenerating → 엔진 **rejected**(sub-mm 예측이 4.35mm로 hard 미달=반증). 둘 다 비진보(NONPROGRESSIVE).',
       limitation='마커/anchor 없는 free ICP 는 이 형상에서도 collapse. → ArUco-턴테이블 fiducial 이 그 해법.'),
    _n('lx3_auto_path_ceiling', 'rejected', 'lx3_cylinder_fit', m=25.0, base=0.39,
       comment='markerless 자동 정합 경로 ceiling: production pipeline 4/6 valid, pos_dev 25-42mm(voxel5 '
               'sparse). proper full-surface scan↔CAD anchor transform 부재 → software-only 천장. '
               '★라이브엔진 reconcile(2026-06-24): 원저자 degenerating → 엔진 **rejected**(oracle 0.39mm 자동화 예측이 25mm로 미달=반증). 둘 다 비진보.',
       limitation='HALCON SurfaceMatch = license blocked. (ArUco init data 는 2026-06-24 grounded 확보 — 고친 색프레임 '
                  '+ brightening 으로 실 마커 검출, lx3_aruco_turntable progressive.) markerless 천장은 그 대안경로로 보존.'),
]

# ── LX3 frontier (Laudan open/closed) ────────────────────────────────────────
BLOOM_FRONTIER = [
    dict(name='q_lx3_msa', status='CLOSED', closed_by=['lx3_groundtruth_oracle'],
         body='GROUND_TRUTH R&R 이 AIAG MSA(±1.0mm) ACCEPTABLE 인가 → 22.08% 🟢'),
    dict(name='q_lx3_enabler', status='CLOSED', closed_by=['lx3_aruco_turntable'],
         body='정합 enabler: HALCON SurfaceMatch license OR ArUco init data — 둘 중 하나 확보. '
              '★2026-06-24 grounded: ArUco init data **확보(YES)** — 고친 색프레임 + brightening(gamma0.4+CLAHE)으로 '
              '실 마커 검출(23/24뷰, ≥3뷰 반복 ID, side_px 60px, 육안확인). 옛 "119/121"은 reader 노이즈였고 '
              '중간의 "markers≈0"도 brightening 미적용 탓이었음 — 마커는 실재. '
              '★★2026-06-24 dict 정정(lx3_aruco_dict4x4): dict 는 MIP_36H12 아니라 **DICT_4X4_250**(비트단위 증거 — '
              '실마커 4×4 비트가 표준 id56 과 완전동일). enabler(검출) CLOSED 는 유지되나(마커 실재 확정), 올바른 dict 로 '
              '재검출 시 121뷰 2195 안정검출·Jaccard 0.81. (정합 *정확도*는 별 frontier q_lx3_aruco_accuracy.)'),
    dict(name='q_lx3_aruco_accuracy', status='OPEN', closed_by=None,
         body='ArUco-턴테이블 정합이 sub-mm(±1.0mm) 정확도를 다는가. **OPEN 유지**. '
              '★★2026-06-24 결정타(lx3_aruco_dict4x4): 진짜 병목은 reader 도 노출도 아니라 **ArUco DICT** 였다. '
              '마커 = DICT_4X4_250(MIP_36H12 아님) — 비트단위 증거(실마커 4×4 비트가 표준 id56 과 완전동일, '
              'evidence/lx3_marker_dict4x4_proof_20260624.png). MIP 의 "반복 ID/id-collision"은 6×6 디코더가 4×4 마커를 '
              '오독한 것. 올바른 dict 로 재실행: detect_lift_4x4.py→lx3_turntable_register **success False→True, '
              'n_markers_usable 8→61, 제약 <30→43867**(검출/대응 병목 해소). 그러나 정확도는 아직 OPEN — '
              'precision_rmse 429mm(최선 단일마커 18mm): 잔존 원인은 dict 아님 = ①DICT_4X4_250 내부 id-collision(축 X 방향 '
              '동일 id 복수) ②흰 마커면 3D 리턴 약함(~18mm). CLOSE 조건=marker-free 축 un-rotate+collision 분리+코너 '
              'plane-fit 로 부시(독립피처) sub-mm. (이하 2026-06-23/이전 기록은 dict 오식별·오염입력 위에서 쓰임 — 보존·맥락용) '
              '— 2026-06-23 grounded '
              '측정 2건이 둘 다 닫지 못함: '
              '(1) 정합 자체 FAILED(lx3_turntable_register_20260623.json): known-3° 단일축 LSQ가 '
              'id-collision으로 starved(32 멀티뷰 id 중 24개 span>1.4m=오검출, 잔여 8마커/14쌍<30; LM '
              'degenerate, precision 1193mm 발산 → 신뢰 0, precision_rmse=null). 같은 ArUco id가 같은 '
              '물리마커가 아님 = 검출/대응 병목(solver 아님). 따라서 정합 precision조차 미확보. '
              '(2) 독립 정확도 측정(lx3_bush_accuracy_20260623.json, 기둥2 부시 vs CAD nominal): 측정됐으나 '
              '**OVER_TOL** — FRT_LH-FRT_RH 거리 1090.96mm vs nominal 1093.30mm = error -2.34mm(>±1.0mm). '
              '게다가 이 측정은 단일 정면(-90°)station을 시간평균한 것으로 **ArUco 정합을 우회**(검증한 것은 '
              '단일뷰 부시 거리 정확도이지 ArUco-턴테이블 정합 정확도가 아님). FRT 한 쌍만 측정가능(RR 부시 '
              '정면 occlusion). 반복도(precision) 0.19mm는 깨끗하나 precision≠accuracy. '
              'CLOSE 조건=마커 우회 아닌 ArUco-턴테이블 정합으로 부시(독립피처)가 sub-mm. 미달=OPEN. '
              '병목 체인: 검출 recall+id-collision(→geometry-gated RANSAC id matching/DeepArUco++)→robust lift→'
              '턴테이블모델(기지 3°단일축, -90°정면)→부시 vs CAD nominal accuracy. '
              '★★★2026-06-24 정밀도 sub-step CLOSED, accuracy OPEN 유지(lx3_aruco_knownaxis_precision): 잔존 병목이 '
              'dict/검출/흰면-3D 가 아니라 **self-cal 6DOF 축 옵티마이저 발산(→13m garbage 축, 513mm)** 임을 규명. '
              'robust 단일축(SVD chord+lstsq pt)+per-id declustering 으로 self-consistency RMS median **0.99mm**·p95 2.4mm'
              '(59 물리트랙, 음성대조 틀린축=64mm) = ~500× 개선. 코너3D 도 sub-mm 으로 독립확정(변 50.0mm·σ<1mm·3방법수렴=한계 '
              '"②흰면3D약" 반증). id-collision 은 이 lot 에선 부차적(no-decluster 도 1.0mm). 남은 CLOSE 조건=이 포즈로 part '
              '점군 정합→부시(독립피처) vs CAD nominal ±1.0mm accuracy(precision≠accuracy 견지).'),
    dict(name='q_lx3_cmm_mapping', status='CLOSED', closed_by=['lx3_lot_cmm_mapping'],
         body='★2026-06-24 CLOSED — lot↔CMM mapping 확정(lx3_lot_cmm_mapping). scan session 의 .zdf view-count + 시간순이 '
              'prompt 촬영계획과 1:1 정합: 153439=121뷰(127 360°)·160114/162343/164447/171253/173509=각 60뷰(127/128/129/130/131)·'
              '153129=3뷰 setup. "121 + 5×60" 패턴 일치 → ordinal 1:1 확정(절대 lot 숫자는 prompt 라벨). evidence record 고정='
              'evidence/lx3_lot_cmm_mapping_20260624.json. 이제 provisional 130 NG(B LH X +1.218·FRT BODY RH BUSH Z -1.067)는 '
              'session LX3RT_20260622_171253(lot 130)에 귀속 가능. (scan-vs-CMM 실제 대조는 q_lx3_external_trueness 로 — 별개.)'),
    dict(name='q_lx3_external_trueness', status='OPEN', closed_by=None,
         body='LX3 scan-vs-CMM external trueness. lx3_cmm_reference_available 로 CMM 기준값은 준비됐지만, 아직 scan 치수를 '
              'CMM feature/axis 와 대조하지 않았다. CLOSE 조건=확정된 lot mapping + face-aware/DRF-locked scan measurement 로 '
              'FRT/RR/B bush feature별 X/Y/Z 또는 distance deltas 를 CMM 값과 비교하고, 사전등록 gate(예: ±1.0mm 및 CMM '
              '불확도 포함)를 통과. 실패 시 accuracy 병목은 ArUco pose, face-aware bush extraction, CMM datum mapping 중 어디인지 '
              '분해한다.'),
    dict(name='q_lx3_part_jig_separation_non_circular', status='OPEN', closed_by=None,
         body='★2026-06-24 merge_part_vs_jig.png 해석 가드. output/images/lx3/merge_part_vs_jig.png 의 빨강/파랑 분리는 '
              '“rough CAD 정렬 후 nearest CAD surface distance <25mm = part(파랑), 그 외 = jig(빨강)”인 CAD-distance 분리다. '
              '시각적으로 잘 갈라져 보여도 검사 증거로는 순환논리 위험이 있다: part 를 CAD 에 가까운 점으로 정의하면 정렬오차와 '
              '실제 부품 변형/불량이 분류 단계에서 흡수될 수 있다. 따라서 이 이미지는 diagnostic visualization 으로만 인정하고 '
              'q_lx3_external_trueness 또는 q_lx3_aruco_accuracy 를 닫는 증거로 쓰지 않는다. CLOSE 조건=CAD distance 없이 '
              'per-view geometry 기반 largest connected component/DBSCAN 또는 motion/known-angle coherence 로 part body 를 먼저 '
              '분리하고, 그 결과를 face-aware bush extraction 및 CMM 대조에 투입해 같은 결론이 재현됨을 보이는 것.'),
    dict(name='q_lx3_full_surface_anchor', status='OPEN', closed_by=None,
         body='proper full-surface scan↔CAD anchor transform 을 자동으로 확보(markerless 자동경로 정본화)'),
    dict(name='q_lx3_jig_runout', status='OPEN', closed_by=None,
         body='★사전등록(2026-06-24, prom blind-spot — ★캡처/공차 정정: LX3 는 **회전지그(rotating jig)**, 턴테이블 아님. '
              '부품을 지그에 고정·3°씩 회전. 공차 ±1.0mm(sub-0.1mm 아님). [sub-0.1mm 는 SX3i C3 — SX3i 는 삼각대 자유이동 '
              'ArUco-puzzle 이라 회전축 자체가 없어 runout 무관, q_sx3i_precision_floor 로]. '
              'LX3 올바른 질문: 회전지그 축 반복도/wobble 이 ±1mm 마진을 갉아먹는가? 정합 precision 0.99mm(≈±1mm 경계)에 '
              '*지그 축 반복오차* 가 lift-노이즈와 미분리로 섞여있을 수 있음(완벽 단일 3°/뷰 강체축 가정 미검증). '
              '측정: 동일각도 재방문 반복도 또는 known-3° 정합잔차의 각도-주기 성분으로 분해. '
              '판정: 지그오차가 0.99mm 의 큰 몫이면 줄여 마진 확보; 작으면 lift/bush-fit 이 진짜 병목. '
              '(prom "runout>0.1mm→sub-0.1mm 불가"는 LX3 가 sub-0.1mm 가 아니라 직접 적용 안 됨 — ±1mm 마진 진단으로 격하. '
              '정밀 회전지그는 턴테이블보다 축 반복도가 좋아 작을 가능성). 미측정=OPEN, 가짜green 금지.'),
    dict(name='q_lx3_datum_bush_faces', status='OPEN', closed_by=None,
         body='★2026-06-24 사용자 도메인 정정(측정 기하의 근본) — LX3 body datum = **6 bush 홀**(gdt_datum_designation 의 '
              '3-2-1 A/B/C[RR_LH·RR_RH·FRT_LH]는 그 6점 패턴의 *부분집합*). 결정적 기하 = 이 bush 들이 **면-분리(face-split)**: '
              '[사용자 명시] 상/하 bush 는 **앞면(front)** 에서 측정(보어가 앞으로 열림), 중간 bush 2개는 보어가 **뒷면(back)** 에 '
              '있어 **뒷면에서 측정**해야 함. ⇒ 한 station/단일 회전축 한 자세로 6 bush 를 동시 측정 불가가 *물리적 사실*. '
              '이것이 두 기존 실패의 *근본원인*을 통합 설명: (1) d5_realdata_bush_repeatability "턴테이블 단일축 360° whole-merge '
              '무효(데이터 기하한계)"·σ 0.30mm band FAIL, (2) lx3_aruco_knownaxis_precision accuracy 21mm(co-located 배경 잔여 + '
              '부시 1:1 매핑 실패) — whole-part 융합이 *면-의존 가시성*을 무시했고, 보어축이 카메라와 ⊥인 각도에선 그 bush 의 '
              '3D 리턴이 약하다(흰 보어면 noise). CLOSE 전략 = **face-aware per-bush 추출**: bush 마다 그 보어가 카메라-facing 인 '
              '회전뷰만 선택(front bush=앞면 뷰각, back bush=뒷면 뷰각)→그 뷰에서 보어 중심/축 fit→기지 jig 각으로 공통(un-rotate) '
              '프레임에 배치→6-bush DRF(build_drf)→cross-capture σ<0.05mm + bush vs CAD nominal ±1.0mm(precision≠accuracy 견지). '
              '데이터[d5 close_path + 360MERGE 확인]: 기존 121뷰 raw zdf(LX3RT_20260622) 360° jig 회전이 양면 모두 포함 → '
              '재촬영 없이 face-aware 재추출 가능. ★과거 LX3 문서 교차확인(2026-06-24, 가짜green 아님=데이터 실증): '
              '6 feature = RR_BODY_LH/RH(rear, x≈371,z-145) · FRT_BODY_LH/RH(front, x≈-550,z-4) · '
              '**B_LH/RH(중간 x≈-42·y±829·z-225)** [production_inspect_20260518 per_feature 6개 + README "6 bush + 2 B-point", '
              'docs/10 "18 cyl=LX3 6 bush+LUCID 12"]. front/back 배정 = **데이터 실증**: 앞면 단일캡처 production_inspect 에서 '
              '**B_LH·B_RH=INVALID(plane_status=error·cylinder=empty·axis None)** = back-bore 라 앞면서 측정 불가 / RR·FRT=측정됨(NG); '
              '반면 수동 GROUND_TRUTH(면별 올바른 측정)는 6/6 OK → **중간 2(B_LH/RH)=뒷면 측정 필수, 4(RR/FRT)=앞면** 이 '
              '사용자 진술과 데이터로 수렴(360merge 평판 smear · B INVALID · 도메인 = 3중 grounding). '
              'q_lx3_aruco_accuracy·q_real_part_drf(DATUM D5)의 진짜 전제 = 이 face-aware 추출. ★계측기 구축+검증'
              '(2026-06-24, scripts/lx3_face_aware_bush.py): synthetic method-valid = **face-aware 6/6 회복·rmse 0.003mm'
              '(back B 2/2 포함) vs naive 단일-window 4/6(back 구조적 누락)** → 면-split insight 가 알고리즘 수준에서 정당화. '
              '실 zdf=**BLOCKED_DETECTION**(per-view bore 검출이 sparse/흰-보어 cloud 에서 막힘=데이터-bound지 method 아님; '
              '다음 레버=cylinder-wall RANSAC 또는 ArUco-pose 로 CAD nominal 위치 직접 ROI+면게이팅). '
              'evidence/lx3_face_aware_bush_validation_20260624.json. ★ArUco-pose 실데이터 시도(2026-06-24, "그거까지"): '
              'per-view 마커 pose **0.68mm median**(74뷰·p95 2.44)=**pose 병목 아님 확정**. 그러나 per-view-pose 머지(smear_solved=False '
              'ext 2255×1433×1811) + multi-view-consistency(≥20뷰 occupied voxel)도 ext **2048×504×1464mm**(part~1040)로 미분리 — '
              '회전지그가 part 와 *함께 회전*하니 consistency 로 안 갈림(static 배경은 제거되나 co-rotating jig 잔존). '
              '⇒ 4 경로(단일축머지·per-view검출·marker-pose머지·MVC) 모두 같은 벽=**part/jig 분할 + sparse/흰-보어 신호**(pose·알고리즘 아님 '
              '= 21mm 벽의 정밀 국소화). 다음 레버=CAD 앵커 part bbox crop 또는 jig 제거 재촬영. (CMM 부재 trueness UNVERIFIED).'),
    dict(name='q_lx3_gauge_boundary', status='OPEN', closed_by=None,
         body='B_LH tol-경계(0.999→1.067) gauge 위태 — 공차 class 재설계 필요한가'),
]


def _line(c=''):
    print(c)


def run():
    """LX3 가지를 BPC 줄기에 접붙여 통합 sub-tree 로 구동."""
    nodes = BPC_NODES + BLOOM_NODES
    frontier = BPC_FRONTIER + BLOOM_FRONTIER
    m = tree_metrics(nodes, frontier)

    lx3_prog = [n['tag'] for n in BLOOM_NODES if n['verdict'] == 'progressive']
    lx3_degen = [n['tag'] for n in BLOOM_NODES if n['verdict'] == 'degenerating']

    _line('═' * 72)
    _line('  LX3 가지 — 서브프레임 ArUco-턴테이블 + CAD-anchor 검사 (3D 형상 검출 / BPC 줄기 접붙임)')
    _line('═' * 72)
    _line(f"\n  피어나는 마디        : {BLOOM_AT} (초기 markerless 측면분기 → 2026-06-22 ArUco-턴테이블 피벗)")
    _line(f"  통합 트리 정본       : {m['canonical']}  (LX3 정합정확도 미측정 → 통합 정본은 BPC v8 유지, 정직)")
    _line(f"  LX3 진보 노드        : {lx3_prog}")
    _line("  ★2026-06-24 grounded : 옛 '119/121'은 reader SNR-노이즈였으나, 고친 색+brightening(gamma/CLAHE)으로 실 MIP_36H12")
    _line("                         마커 검출(23/24뷰·≥3뷰반복 10종·side_px 60px, 육안확인) → 어두움=전처리문제지 하드한계 아님.")
    _line("                         enabler CLOSED(검출). 정합 정확도는 q_lx3_aruco_accuracy OPEN(corrected 검출로 재측정).")
    _line("  ★★2026-06-24 dict정정 : 마커 dict = DICT_4X4_250 (MIP_36H12 오식별, 비트단위 증거). 올바른 dict 재실행 →")
    _line("                         turntable_register success False→True·usable 8→61·제약 <30→43867. 단 precision 429mm")
    _line("                         (id-collision+흰면 3D약) = 정확도 OPEN. lx3_aruco_dict4x4 (progressive).")
    _line("  ★★★2026-06-24 정밀도   : (lx3_aruco_knownaxis_precision) 독립검증=코너3D sub-mm(변 50.0mm·σ<1mm·3방법수렴, '흰면3D약' 반증).")
    _line("                         정밀도 병목=흰면 아니라 self-cal 6DOF 발산(13m축,513mm). robust 단일축+decluster → self-consistency")
    _line("                         RMS median 0.99mm(59트랙,틀린축대조 64mm)=~500×. accuracy(부시 vs CAD)는 q_lx3_aruco_accuracy OPEN.")
    _line(f"  LX3 퇴행 노드        : {lx3_degen}  ← markerless identity-basin = BPC collapse 교훈 재확인")
    _line(f"  frontier 수지(통합)  : {m['laudan']['frontier_balance']}  (closed−open)")
    _line('\n' + '═' * 72)
    return dict(metrics=m, bloom_at=BLOOM_AT, lx3_progressive=lx3_prog,
                lx3_degenerating=lx3_degen, canonical=m['canonical'])


if __name__ == '__main__':
    run()
