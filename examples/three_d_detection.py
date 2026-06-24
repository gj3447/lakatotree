"""3D 형상 검출 (3D-shape detection from 3D data) — BPC·SX3i·LX3 통합 연구 프로그램.

세 ICP_SPEC repo(BPC_ICP_SPEC / SX3i_ICP_SPEC / LX3_ICP_SPEC)는 부품만 다를 뿐
**하나의 연구 프로그램**이다: "멀티뷰 3D 데이터로 부품 형상을 공차 이하로 검출한다."
따라서 세 개의 분리된 트리가 아니라 **한 그루의 나무** — BPC 가 검증된 줄기(trunk),
SX3i 와 LX3 는 그 줄기의 특정 마디에서 피어난(bloom) 가지다.

    ROOT  prob_statement (BPC)
      └─ aruco_metric ─────────────────────────────┐ 정합 프레임 결정점
          ├─ frozen_calib_reuse → v8_pipeline(CANONICAL, sub-1mm)
          │     └─◆ SX3i 가지: v8 의 미완 step 6.1(precision≠accuracy)을
          │            XL250 에서 sub-0.1mm 로 닫음 (같은 ArUco 정합, 정밀 심화)
          └─◆ LX3 가지: 초기 markerless(CAD surface-match) → 2026-06-22 MIP_36H12 ArUco
                 + 턴테이블(LX3RT) 피벗. markerless 자동경로 ceiling 은 음의분기로 보존
      + [degenerating: free_multiview_icp, pv6dof×3] ← 공통 실패교훈(LX3 가 재확인)
      + [rejected: non_rigid_cpd, dup_id_90lock]      ← 공통 실패교훈(SX3i 가 상속)

실행: python -m examples.three_d_detection
"""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics
from examples.bpc_icp_programme import NODES as BPC_NODES, FRONTIER as BPC_FRONTIER
from examples import sx3i_icp_programme as sx3i
from examples import lx3_icp_programme as lx3
from examples import datum_programme as datum

TITLE = '3D 형상 검출 (3D-shape detection from 3D data)'

# Hard core — 세 부품이 공유하는 반증불가 프로그램 정체성(BPC 가 발견, SX3i 상속, LX3 재확인).
HARD_CORE = [
    '1) 멀티뷰 3D 데이터를 공통 metric frame 으로 정합해야 형상 검출이 가능하다.',
    '2) free multi-view ICP 는 평판·주기·대칭 형상에서 collapse 한다 (rank-deficiency + aliasing).',
    '3) precision ≠ accuracy — 정합 self-consistency 는 정확도 증거가 아니다(독립검증 필요).',
]

# ── 나무 전체를 가로지르는 frontier — hard-core #3(precision≠accuracy)의 유일한 닫는 노드 ──
# 2026-06-24 사용자 적대검증: 트리 전체에 외부 trueness(traceable) 독립검증 노드가 0개였다.
# v8 0.90mm·SX3i C3·LX3 Kabsch·DATUM DRF 는 전부 precision(자기일관성) 또는 scan-재구성 CAD(GD&T truth 아님)
# 만 측정 — 외부 traceable 표준 대비 accuracy 는 어느 가지도 닫지 못함. 이게 모든 가지의 천장.
# 이 frontier 를 *명시적으로 OPEN* 으로 사전등록 = 가짜진보 은폐 금지(엔진이 빚을 보이게 한다).
TREE_FRONTIER = [
    dict(name='q_external_trueness', status='OPEN', closed_by=None,
         body='★hard-core #3(precision≠accuracy)의 유일 닫는 노드 — 나무 전체 공통 천장(2026-06-24 사전등록). '
              '현 모든 "정밀" 성취는 외부 trueness 미검증이다: v8 interior 0.90mm(=self-consistency, CMM無), '
              'SX3i C3 feature-coincidence(=정합 자기일관성), LX3 Kabsch 0.064mm/known-axis 0.99mm(=재투영 잔차), '
              'DATUM DRF(=CAD nominal 대비, 그 CAD 도 STEP 공칭이지 측정된 truth 아님). 어느 것도 traceable 표준'
              '(CMM·CT·calibrated artifact)에 대조 안 됨. 사전등록 닫힘조건(측정 전 고정): 동일 부품을 traceable '
              'CMM/CT 로 측정해 GD&T 피처별 |scan_dim − CMM_dim| 산출, 공차 band 내(예: ≤0.10mm·k=2 불확도 포함)면 '
              'CLOSED. 그 전까지 hard-core #3 은 나무 전체에서 OPEN — 모든 가지 verdict 는 "정밀도까지"로 읽어야 한다. '
              '비고: best-fit 비보수성(D3 21~62% 은폐)은 이 천장을 더 낮춤 → DRF-locked 측정이 전제.'),
]

# 한 그루의 나무: 줄기(BPC) + 세 개의 개화 가지(SX3i, LX3, DATUM) + 나무 전체 frontier.
UNIFIED_NODES = BPC_NODES + sx3i.BLOOM_NODES + lx3.BLOOM_NODES + datum.BLOOM_NODES
UNIFIED_FRONTIER = (BPC_FRONTIER + sx3i.BLOOM_FRONTIER + lx3.BLOOM_FRONTIER
                    + datum.BLOOM_FRONTIER + TREE_FRONTIER)


def _line(c=''):
    print(c)


def _roots(nodes):
    return [n['tag'] for n in nodes if not n.get('parent') and not n.get('parents')]


def run():
    m = tree_metrics(UNIFIED_NODES, UNIFIED_FRONTIER)
    roots = _roots(UNIFIED_NODES)

    _line('═' * 72)
    _line(f'  {TITLE}')
    _line('  BPC 줄기 + SX3i·LX3·DATUM 개화 가지 — 한 그루의 나무')
    _line('═' * 72)

    _line('\n[Hard core] 세 부품 공유 (반증불가)')
    for h in HARD_CORE:
        _line(f'  {h}')

    _line('\n[나무 구조]')
    _line(f"  단일 root            : {roots}  (연결된 한 그루 — 분리 트리 아님)")
    _line(f"  통합 정본(CANONICAL) : {m['canonical']}  (BPC v8 — 유일하게 공차이하 확증된 마디)")
    _line(f"  SX3i 개화 마디       : {sx3i.BLOOM_AT}  → step 6.1(precision≠accuracy) 을 sub-0.1mm 로")
    _line(f"  LX3  개화 마디       : {lx3.BLOOM_AT}  → markerless CAD-anchor 측면 분기")
    _line(f"  DATUM 개화 마디      : {datum.BLOOM_AT}  → 마커없이 CAD GD&T datum(3-2-1 DRF) 정합 (3번째 프레임)")

    _line('\n[가지별 상태 — 정직한 성숙도]')
    sx3i_open = [q for q in sx3i.BLOOM_FRONTIER if q['status'] == 'OPEN']
    sx3i_prog = [n['tag'] for n in sx3i.BLOOM_NODES if n['verdict'] in ('progressive', 'CANONICAL')]
    sx3i_partial = [n['tag'] for n in sx3i.BLOOM_NODES if n['verdict'] == 'partial']
    sx3i_degen = [n['tag'] for n in sx3i.BLOOM_NODES if n['verdict'] == 'degenerating']
    lx3_prog = [n['tag'] for n in lx3.BLOOM_NODES if n['verdict'] == 'progressive']
    lx3_degen = [n['tag'] for n in lx3.BLOOM_NODES if n['verdict'] == 'degenerating']
    _line(f"  BPC  : CANONICAL(v8 sub-1mm) — 줄기 확립. 미해소=interior CMM 미검증(step 6.1).")
    _line(f"  SX3i : 실측 — 진보 {len(sx3i_prog)}, partial {sx3i_partial}, degenerating {sx3i_degen}. "
          f"C1=PARTIAL, C1b denoise-salvage 반증 → 재촬영/markerless 분기(open frontier {len(sx3i_open)}).")
    _line(f"  LX3  : 실측 — progressive {lx3_prog} (R&R σ 37µm), "
          f"degenerating {lx3_degen} (auto-path ceiling + collapse 재확인).")
    datum_open = [q for q in datum.BLOOM_FRONTIER if q['status'] == 'OPEN']
    datum_partial = [n['tag'] for n in datum.BLOOM_NODES if n['verdict'] == 'partial']
    datum_rej = [n['tag'] for n in datum.BLOOM_NODES if n['verdict'] == 'rejected']
    _line(f"  DATUM: 계측기 검증(synthetic) — partial {datum_partial}, rejected {datum_rej}. "
          f"D2~D4 DRF instrument PASS·D3⭐ best-fit 21~62% 은폐 실증, D5 실부품 OPEN(frontier {len(datum_open)}).")

    _line('\n[통합 지표]')
    _line(f"  frontier 수지        : {m['laudan']['frontier_balance']}  (closed {m['frontier']['closed']} − open {m['frontier']['open']})")
    _line(f"  최대 퇴행깊이        : {m['max_degeneration_depth']}  (≥3 경보 — 공통 6-DOF 교훈)")
    _line(f"  정본경로 신뢰도      : {m['bayes']['canonical_credence']}")
    _line(f"  경보                 : {m.get('alerts')}")

    _line('\n' + '═' * 72)
    return dict(title=TITLE, hard_core=HARD_CORE, roots=roots,
                canonical=m['canonical'], metrics=m,
                sx3i_progressive=sx3i_prog, sx3i_partial=sx3i_partial,
                blooms={'sx3i': sx3i.BLOOM_AT, 'lx3': lx3.BLOOM_AT})


if __name__ == '__main__':
    run()
