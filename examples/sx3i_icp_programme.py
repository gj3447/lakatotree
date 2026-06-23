"""Dogfood — SX3i(XL250 ArUco → 독립검증 sub-0.1mm)를 3D 형상 검출 트리의 가지로 모델링.

3D 형상 검출(3D-shape detection from 3D data) 통합 프로그램의 SX3i 가지.
BPC 줄기(examples/bpc_icp_programme)에서 **`v8_pipeline` 마디에 피어난다** — BPC v8 의
미완 step 6.1(precision≠accuracy 독립검증, interior 0.90mm CMM 미검증)을 XL250 에서
처음 닫으려는 *수직 심화* 가지(같은 ArUco 정합법, 정밀도만 sub-1mm→sub-0.1mm).

★정직성: 측정 없는 conjecture 를 progressive 로 박는 것은 자기채점=가짜green 이므로 금지.
2026-06-23 첫 실데이터 구동으로 C1/C1b 가 **partial**(측정으로 자란 마디, progressive 아님)
로 등록됐다 — 마커 실재·dict 는 확인됐으나 speckle 로 신뢰검출 미달이라 CONFIRMED 아님.
C2~C5 는 여전히 **OPEN frontier**(미측정). 공통 퇴행/기각 교훈은 BPC 줄기에서 상속(중복 등록 안 함).

정본 사양: /data/kjra/PROJECT/3D/SX3i_ICP_SPEC/PROGRAMME.md
실행: python -m examples.sx3i_icp_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics
from examples.bpc_icp_programme import _n, NODES as BPC_NODES, FRONTIER as BPC_FRONTIER

# 이 가지가 BPC 줄기의 어느 마디에서 피어나는가.
BLOOM_AT = 'v8_pipeline'

# ── SX3i 가지 노드 — 2026-06-23 첫 실데이터 구동: C1 측정 시작(PARTIAL) ──────────
# progressive 0개(CANONICAL 미획득=정직). 측정으로 자란 마디 = C1/C1b partial 2개.
BLOOM_NODES = [
    _n('sx3i_prob', 'canonical_stage', BLOOM_AT, algo='problem',
       comment='SX3i = Zivid3 XL250 lot(sx3i_20260615 ×212). XL250 ArUco 정합 → 독립검증 sub-0.1mm. '
               'BPC v8_pipeline 의 미완 step 6.1(precision≠accuracy) 을 XL250 에서 처음 닫는 수직심화 가지. '
               '2026-06-23 첫 실데이터 구동 — C1 측정 개시(미측정 → PARTIAL).',
       limitation='C2~C5 는 여전히 OPEN frontier(미측정). 정합법/퇴행교훈은 BPC 줄기 상속.'),

    # ── C1: XL250 ArUco 검출 — 실데이터 PARTIAL (마커 실재·dict ✅ / 신뢰검출 미달) ──
    _n('c1_marker_detect', 'partial', 'sx3i_prob', nr=True, nc=False, q=['q_xl250_gsd'],
       comment='212 zdf ArUco 검출(scripts/c1_marker_detect.py, prismv2 zdf_reader). zdf→aruco 경로 ✅, '
               'DICT_4X4_250 정답(id 110/120 = BPC marker 111 대역) ✅, 마커 물리실재 ✅ '
               '(evidence/c1_preliminary_20260623.md).',
       limitation='organized-intensity speckle → cv2.aruco 가 valid-but-wrong ID flip. 실측 211뷰 raw quad 520 '
                  '→ decode 70뷰/distinct ID 52종(노이즈 FP 양산), side_px median 신뢰 산출 불가. P1 부분/P2 미확정. '
                  'C1 은 하위가지 C1b 닫혀야 CONFIRMED.'),

    # ── C1b: denoise+geom+consistency 게이트 (C1 신뢰검출 하위문제) ──
    _n('c1b_consistency', 'partial', 'c1_marker_detect', nr=True, nc=False, q=['q_denoise_coverage'],
       comment='cross-view 마커맵 일관성 게이트 구축(scripts/marker_map.py) — 강체 거리불변 + intra-view '
               'uniqueness 로 노이즈 FP 학살. 합성 falsify 통과(scripts/test_marker_map.py: 진짜 4마커 채택, '
               'FP 3종 기각, 강체거리 0.77mm 복원). 3D 기하게이트(다리2)는 interior_plane_lift 로 기존재.',
       limitation='실 lot 적용(evidence/c1b_consistency_20260623): interior-gated 79개/52종, ≥2마커 뷰 9개, '
                  '공동관측 쌍이 전부 단1뷰 → min_pair_views=2 통과 쌍 0 → 채택 0(REFUTED). 게이트는 옳으나 '
                  '신호부족. denoise 프론트엔드(다리1)가 선결과제 — decode 반복 공동관측↑ 후 재적용.'),

    # ── C1b 다리1(denoise): salvage 가설 반증 → C1b 경로 degenerate ──
    _n('c1b_denoise', 'degenerating', 'c1_marker_detect',
       comment='denoise 프론트엔드 측정(scripts/c1b_denoise_eval.py + c1_salvage_denoise.py). triage 정본 '
               'bilateral(9,50,50)+CLAHE(3,16²)+EC0.4 가 이미 최적 denoise — 전 211뷰에서 ≥3뷰+side_mm안정 '
               '마커 = 172 단 1개, 최다반복 190(13뷰)은 노이즈 attractor(불안정)→탈락. '
               'evidence/c1b_denoise_20260623.md.',
       limitation='최적 2D denoise 로도 신뢰가능 반복 마커집합 不생성(172 1개=정합 불가). DICT_4X4_250 16비트 '
                  '+ speckle → valid-but-wrong flip 구조적. "재촬영 없이 살린다" denoise-salvage 반증. '
                  'C1 CONFIRM 경로(C1b)는 이 lot 에서 degenerate → 재촬영/markerless 분기.'),

    # ── 분기 A: 재촬영(root cause = Settings2D 누락) — C1 을 새 수단으로 푸는 신선한 시도 ──
    #    부모=c1_marker_detect (denoise 퇴행의 연속이 아니라 C1 검출문제의 대체 해법).
    _n('c1_rootcause_settings2d', 'partial', 'c1_marker_detect', nr=True, nc=False,
       q=['q_recapture_settings2d'],
       comment='C1 검출불가 근본원인 규명(capture_clean_2d3d.py): zdf 컬러가 3D 구조광 stripe 프레임에서 나옴 '
               '= capture 에 settings.color=Settings2D(flat-flash) 누락. 마커 부족/denoise 문제 아님. '
               'fix 스크립트 존재 + 사전등록 acceptance gate(scripts/recapture_gate.py, G1~G4) + 합성검정. '
               'evidence/recapture_spec_20260623.md.',
       limitation='gate 가 현 오염 lot 을 G1~G4 전부 FAIL 로 정확히 기각(변별력 검증). 재촬영(Settings2D + '
                  '마커≥22mm·DICT_5X5) 실행=하드웨어 대기(XL250 노트북). PASS 시 C1 CONFIRMED.'),

    # ── 분기 B: markerless C3 — 마커 우회 → 부모=sx3i_prob(가지 root). instrument 완성, 입력 블록 ──
    _n('c3_markerless_instrument', 'partial', 'sx3i_prob', nr=True, nc=False,
       q=['q_markerless_c3_inputs'],
       comment='C3(precision≠accuracy 독립게이트)를 마커 무관으로 치는 instrument 구축(scripts/markerless_c3.py: '
               'cross_view_coincidence + pairwise_spacing, 사전등록 band median≤0.10/p95≤0.15). 합성검정 통과 '
               '(진짜 CONFIRMED, 스케일오차 REFUTED). evidence/markerless_c3_20260623.md.',
       limitation='SX3i 즉시적용 불가: (i) 뷰 feature(hole/boss) 추출기 미존재, (ii) SX3i CAD nominal 은 '
                  '.igs BREP 추출 실패(STEP/mesh 필요). instrument ready, 입력 대기. A 성공 시 C3 에서 합류.'),
]

# ── SX3i frontier (Laudan open questions = PROGRAMME.md 의 C1~C5 계획) ────────
BLOOM_FRONTIER = [
    dict(name='q_xl250_gsd', status='OPEN', closed_by=None,
         body='C1: XL250 organized RGBA 에서 DICT_4X4_250 검출 & 마커 GSD ≥ 20px 룰 통과?'),
    dict(name='q_sx3i_assemble', status='OPEN', closed_by=None,
         body='C2: incremental puzzle 가 212뷰를 1 connected component, self-consistency p95 < 0.2mm?'),
    dict(name='q_independent_accuracy', status='OPEN', closed_by=None,
         body='C3⭐: feature-coincidence median ≤ 0.10mm — 마커 무관 독립 정밀게이트(BPC step 6.1 을 닫음).'),
    dict(name='q_raw_refine', status='OPEN', closed_by=None,
         body='C4: C2 puzzle INIT 위 raw-res ICP(geom+intensity) 로 overlap RMS sub-0.1mm?'),
    dict(name='q_crosscam', status='OPEN', closed_by=None,
         body='C5: XL250 ↔ MR60(zivid2Plus, BPC lot) cross-camera feature |Δ| < 0.15mm?'),
    # C1b denoise 질문 — 측정으로 부정 답(CLOSED by c1b_denoise): denoise 로는 못 살림.
    dict(name='q_denoise_coverage', status='CLOSED', closed_by='c1b_denoise',
         body='C1b: edge-preserving despeckle 로 decode 반복 공동관측↑? → 답 NO. bilateral+CLAHE 최적 '
              'denoise 로도 ≥3뷰 안정 마커 172 1개뿐(190 노이즈 attractor). salvage 반증.'),
    # 위 부정답이 연 두 분기전환 질문 (degenerate → 다른 가지; 배타 아님, C3 에서 합류).
    dict(name='q_recapture_settings2d', status='OPEN', closed_by=None,
         body='분기A: Settings2D(flat-flash) 재촬영(마커≥22mm·DICT_5X5)이 acceptance gate G1~G4 를 '
              'PASS 하는가? (근본원인=stripe-light color, recapture_gate.py 사전등록)'),
    dict(name='q_markerless_c3_inputs', status='OPEN', closed_by=None,
         body='분기B: 뷰 feature 추출기 + SX3i STEP nominal 이 마련되면 markerless C3 게이트가 '
              'feature-coincidence median ≤ 0.10mm 를 내는가? (instrument=markerless_c3.py ready)'),
]


def _line(c=''):
    print(c)


def run():
    """SX3i 가지를 BPC 줄기에 접붙여 통합 sub-tree 로 구동(가지 단독은 줄기 없이 무의미)."""
    nodes = BPC_NODES + BLOOM_NODES
    frontier = BPC_FRONTIER + BLOOM_FRONTIER
    m = tree_metrics(nodes, frontier)

    _line('═' * 72)
    _line('  SX3i 가지 — XL250 ArUco → 독립검증 sub-0.1mm (3D 형상 검출 / BPC 줄기 접붙임)')
    _line('═' * 72)
    _line(f"\n  피어나는 마디        : {BLOOM_AT} (BPC v8 의 step 6.1 = precision≠accuracy 갭)")
    _line(f"  통합 트리 정본       : {m['canonical']}  ← 여전히 BPC(SX3i 미측정이라 정본 미획득=정직)")
    sx3i_open = [q['name'] for q in BLOOM_FRONTIER if q['status'] == 'OPEN']
    _line(f"  SX3i open frontier   : {len(sx3i_open)}개  {sx3i_open}")
    _line(f"  핵심 정밀게이트      : q_independent_accuracy (C3⭐, median ≤ 0.10mm)")
    n_prog = sum(1 for nd in BLOOM_NODES if nd['verdict'] in ('progressive', 'CANONICAL'))
    partials = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'partial']
    degen = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'degenerating']
    _line(f"  진보 노드(SX3i)      : {n_prog}  ← CANONICAL 미획득=정직(정본 진보 아직 없음).")
    _line(f"  측정 마디(SX3i)      : partial {partials} + degenerating {degen}")
    _line(f"  C1 verdict           : PARTIAL (마커 실재·dict ✅ / speckle 신뢰검출 미달)")
    _line(f"  C1b 경로             : geom✅+consistency✅(합성), 그러나 denoise 다리1 반증 → degenerate")
    _line(f"  → 분기 A(재촬영)     : 근본원인=Settings2D 누락, acceptance gate 사전등록(현 lot FAIL 검증). 촬영대기")
    _line(f"  → 분기 B(markerless) : C3 instrument 구축+합성검정✅, SX3i feature/STEP 입력 대기 (A와 C3서 합류)")
    _line(f"  frontier 수지(통합)  : {m['laudan']['frontier_balance']}  (closed−open)")
    _line('\n' + '═' * 72)
    return dict(metrics=m, bloom_at=BLOOM_AT, open_frontier=sx3i_open,
                sx3i_progressive=n_prog, sx3i_partial=partials, sx3i_degenerating=degen,
                canonical=m['canonical'])


if __name__ == '__main__':
    run()
