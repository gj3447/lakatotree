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
  - ★(2026-06-22 ArUco-턴테이블, LX3RT MIP_36H12) 검출 classic 101/121 → 보정(nlm+2× upscale) 119/121뷰,
    최대 연결성분 115/121(DeepArUco++ 보강중) = 막혀있던 "ArUco init data" enabler 확보(progressive).
    단 정합 *정확도* sub-mm 미측정(OPEN) — 검출커버리지 ≠ 정확도(가짜green 금지).
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
    _n('lx3_groundtruth_oracle', 'progressive', 'lx3_prob', m=0.0368, base=None, scope='measurement',
       nr=True, nc=True, q=['q_lx3_full_surface_anchor'],
       comment='GROUND_TRUTH self-verify: R&R σ=36.8µm, AIAG MSA P/T 22.08% 🟢ACCEPTABLE(±1.0mm). '
               '12측정 11 OK+1 NG. BPC-grade σ 도달 — production GROUND_TRUTH 는 이미 sub-mm.',
       limitation='oracle/수동 anchor 기준 — 자동 정합 경로 아님(lx3_auto_path_ceiling 참조). precision≠accuracy.'),
    _n('lx3_cylinder_fit', 'progressive', 'lx3_groundtruth_oracle', m=0.39, base=None, scope='measurement',
       nr=True, nc=False, q=['q_lx3_gauge_boundary'],
       comment='hole 중심=cylinder fit. mean pos dev 0.39mm part-wide sub-mm. '
               '5-gate: G1 rigid / G2 hole-align / G3 local-min audit / G4 signed-dist / G5 noise-floor.',
       limitation='B_LH 0.999→1.067mm tol-경계 flip = gauge 위태(σ shift 시 verdict 뒤집힘).'),

    # ★2026-06-22 ArUco-턴테이블 정합 가지 — markerless 천장의 "ArUco data missing" enabler 를 닫음
    _n('lx3_aruco_turntable', 'progressive', 'lx3_prob', m=None, scope='registration',
       nr=True, nc=True, q=['q_lx3_enabler'],
       comment='ArUco-턴테이블 정합 경로(LX3RT_20260622, MIP_36H12). 막혀있던 "ArUco init data missing"'
               '(lx3_auto_path_ceiling) enabler 를 닫음: 마커 검출 classic 101/121뷰 → 보정(nlm denoise '
               '+ 2× upscale) 119/121뷰, 최대 연결성분 115/121(멀티뷰 정합그래프 연결). DeepArUco++(MIP_36H12 '
               '학습) 어려운 뷰 보강중. novel=턴테이블 fiducial 이 연결된 멀티뷰 정합그래프 산출(confirmed).',
       limitation='검출 커버리지/그래프 연결만 grounded. 정합 *정확도* sub-mm(±1.0mm)는 미측정=OPEN '
                  '(q_lx3_aruco_accuracy). 검출≠정확도. ⚠️DeepArUco GPU=타워 Blackwell(sm_120)↔CUDA11.7 '
                  '비호환(torch cu117 garbage) → CPU+다운스케일로만 신뢰. '
                  '★2026-06-23 known-3° 단일축 턴테이블 LSQ 정합 시도=FAILED(grounded, lx3_turntable_register_'
                  '20260623.json): 134 robust-3D center/80 id 중 ≥2뷰 32 id이나 24개가 3D span>1.4m '
                  '(=1.3m 회전체에 단일 물리마커로 불가능) → MIP_36H12 id-collision/오검출, 같은 id가 같은 '
                  '물리마커 아님. id-collision gate 후 8 마커/14 view-pair(<30 임계)로 starved, LM 해는 '
                  'degenerate(축 95m밖·precision 1193mm 발산=신뢰 0, accuracy로 보고 금지). 병목=검출/대응'
                  '(solver 튜닝 아님): 멀티뷰 id 대응이 도장된 캐스팅에서 비신뢰 → geometry-gated id matching '
                  '(RANSAC) 또는 마커-무관 부시 fallback 필요.'),

    # 퇴행 가지(보존) — BPC 줄기 hard-core 재확인 + markerless 자동경로 한계
    _n('lx3_identity_basin', 'degenerating', 'lx3_prob', m=4.35, base=None,
       comment='markerless multi-view ICP 28 pair rmse 4.35-5.77mm cluster = identity-init basin. '
               '"진짜 R&R 아님" — BPC free-ICP collapse(평판 rank-deficiency) 교훈을 LX3 형상에서 재확인.',
       limitation='마커/anchor 없는 free ICP 는 이 형상에서도 collapse. → ArUco-턴테이블 fiducial 이 그 해법.'),
    _n('lx3_auto_path_ceiling', 'degenerating', 'lx3_cylinder_fit', m=25.0, base=0.39,
       comment='markerless 자동 정합 경로 ceiling: production pipeline 4/6 valid, pos_dev 25-42mm(voxel5 '
               'sparse). proper full-surface scan↔CAD anchor transform 부재 → software-only 천장.',
       limitation='HALCON SurfaceMatch = license blocked. (ArUco init = data missing 절은 2026-06-22 해소: '
                  'LX3RT 턴테이블 MIP_36H12 데이터 확보 → lx3_aruco_turntable.) markerless 천장 기록으로 보존.'),
]

# ── LX3 frontier (Laudan open/closed) ────────────────────────────────────────
BLOOM_FRONTIER = [
    dict(name='q_lx3_msa', status='CLOSED', closed_by=['lx3_groundtruth_oracle'],
         body='GROUND_TRUTH R&R 이 AIAG MSA(±1.0mm) ACCEPTABLE 인가 → 22.08% 🟢'),
    dict(name='q_lx3_enabler', status='CLOSED', closed_by=['lx3_aruco_turntable'],
         body='정합 enabler: HALCON SurfaceMatch license OR ArUco init data — 둘 중 하나 확보. '
              '→ 2026-06-22 ArUco init data 확보(LX3RT MIP_36H12 턴테이블, 검출 119/121뷰·연결성분 115).'),
    dict(name='q_lx3_aruco_accuracy', status='OPEN', closed_by=None,
         body='ArUco-턴테이블 정합이 sub-mm(±1.0mm) 정확도를 다는가. **OPEN 유지** — 2026-06-23 grounded '
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
              '턴테이블모델(기지 3°단일축, -90°정면)→부시 vs CAD nominal accuracy.'),
    dict(name='q_lx3_full_surface_anchor', status='OPEN', closed_by=None,
         body='proper full-surface scan↔CAD anchor transform 을 자동으로 확보(markerless 자동경로 정본화)'),
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
    _line(f"  LX3 진보 노드        : {lx3_prog}  (R&R σ 37µm + ArUco-턴테이블 enabler 확보)")
    _line(f"  LX3 퇴행 노드        : {lx3_degen}  ← markerless identity-basin = BPC collapse 교훈 재확인")
    _line(f"  frontier 수지(통합)  : {m['laudan']['frontier_balance']}  (closed−open)")
    _line('\n' + '═' * 72)
    return dict(metrics=m, bloom_at=BLOOM_AT, lx3_progressive=lx3_prog,
                lx3_degenerating=lx3_degen, canonical=m['canonical'])


if __name__ == '__main__':
    run()
