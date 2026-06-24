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
    _n('lx3_aruco_turntable', 'progressive', 'lx3_prob', m=4.2, scope='detection',
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
    _n('lx3_aruco_dict4x4', 'progressive', 'lx3_aruco_turntable', m=61.0, base=8.0, scope='registration',
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
    _n('lx3_aruco_knownaxis_precision', 'progressive', 'lx3_aruco_dict4x4', m=0.99, base=513.4, scope='registration',
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
                  'self-cal 발산이 원인; id-collision 도 부차적=no-decluster 도 1.0mm·64id→59track). 다음 수=이 포즈로 part 점군 '
                  '정합→부시 거리 vs CAD nominal accuracy. (DeepArUco++ 사전학습=실코너 OOD near-constant 6px WORSE(팀 BPC verdict '
                  '도 WORSE)=재학습 필요; Blackwell GPU 는 torch cu128 정상=옛 cu117 garbage 경고 무효.)'),

    # ★2026-06-24 CAD-side 정확도 기준값(ruler) — STEP_REORIENT→LX3_LOCAL 변환 + 4부시 nominal (docs/10 미해결 #5)
    _n('lx3_cad_bush_nominal', 'progressive', 'lx3_aruco_knownaxis_precision', m=0.064, scope='cad_frame_map',
       direction='lower', nr=True, nc=True, q=['q_lx3_aruco_accuracy'],
       comment='정합 정확도의 *기준값(ruler)* 도출(CAD-only, 스캔 무관 — docs/10 미해결 항목 #5 STEP_REORIENT→LX3_LOCAL). '
               'STEP_REORIENT 4부시 + LX3_LOCAL 3부시(알려진 1:1 대응)로 Kabsch → **rigid 확정(resid 0.064mm·거리보존 0.000mm)**. '
               '미지였던 FRT_RH(LX3_LOCAL)=(-921,950,140) 도출. 정본 부시간 거리: RR쌍 805·RR-FRT 942.8·FRT쌍 1094mm. '
               '★독립 교차검증: 도출 FRT쌍 1094.0mm vs 측정 nominal 1093.3mm = **0.70mm 일치**(<±1.0mm tol). '
               'grounded record=evidence/lx3_bush_nominal_lx3local_20260624.json.',
       limitation='정확도 *기준값*(CAD nominal)이지 정확도 *측정* 아님 — q_lx3_aruco_accuracy 닫으려면 '
                  'lx3_aruco_knownaxis_precision 포즈로 정합한 스캔 부시를 이 기준에 대보아야(±1.0mm). 기준은 이제 준비됨(ruler ready).'),

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
    dict(name='q_lx3_full_surface_anchor', status='OPEN', closed_by=None,
         body='proper full-surface scan↔CAD anchor transform 을 자동으로 확보(markerless 자동경로 정본화)'),
    dict(name='q_lx3_turntable_runout', status='OPEN', closed_by=None,
         body='★사전등록(2026-06-24, prom blind-spot — ★공차 정정: LX3 는 ±1.0mm 이지 sub-0.1mm 아님. '
              'sub-0.1mm 는 SX3i C3 얘기고 SX3i 는 턴테이블도 아닌 ArUco-puzzle stitch → runout 무관, q_sx3i_precision_floor 로). '
              'LX3 맥락의 올바른 질문: LX3RT 턴테이블 물리축 runout 이 ±1mm 마진을 잡아먹는가? 정합 precision 0.99mm '
              '(≈±1mm 경계)에 *물리축 wobble* 이 lift-노이즈와 미분리로 섞여있을 수 있음(완벽 단일 3°/뷰 강체축 가정 미검증). '
              '측정: 동일각도 재방문 반복도 또는 known-3° 정합잔차의 각도-주기 성분으로 runout 분해. '
              '판정: runout 이 0.99mm 의 큰 몫이면 그걸 줄여 ±1mm 마진 확보; 작으면 lift/bush-fit 이 진짜 병목. '
              '(prom "runout>0.1mm→sub-0.1mm 불가"는 LX3 가 sub-0.1mm 가 아니라 직접 적용 안 됨 — ±1mm 마진 진단으로 격하). '
              '미측정=OPEN, 가짜green 금지.'),
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
