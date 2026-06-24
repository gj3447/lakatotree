"""Dogfood — SX3i(XL250 ArUco → 독립검증 sub-0.1mm)를 3D 형상 검출 트리의 가지로 모델링.

3D 형상 검출(3D-shape detection from 3D data) 통합 프로그램의 SX3i 가지.
BPC 줄기(examples/bpc_icp_programme)에서 **`v8_pipeline` 마디에 피어난다** — BPC v8 의
미완 step 6.1(precision≠accuracy 독립검증, interior 0.90mm CMM 미검증)을 XL250 에서
처음 닫으려는 *수직 심화* 가지(같은 ArUco 정합법, 정밀도만 sub-1mm→sub-0.1mm).

★2026-06-24 misdiagnosis 정정(음의결과=교훈으로 보존):
  2026-06-23 의 C1 'speckle 검출취약' + C1b 'denoise-salvage 반증' + 분기A 'Settings2D 재촬영'
  결론은 전부 **misdiagnosis** 였다. 진짜 원인 = prismv2 zdf_reader.read_rgb 가 진짜 색(N*4
  float32 프레임)을 두고 N*4-byte SNR float 맵을 색으로 오선택해 보라쓰레기를 뱉던 리더 버그.
  고친 리더 + STRICT DICT_4X4_250(denoise 0) 재검출: 40뷰 중 34뷰 검출·총 331마커·평균 8.28/뷰·
  side_px median 90.6px(20px 룰 100% 통과)·cross-view 반복 ID 28종. 데이터는 항상 멀쩡했다.
  → C1 = progressive(재grounding). 사용자 원 가설("촬영 멀쩡, 디코드가 문제")이 옳았다.
  보존 교훈: 파일 sha256 은 맞아도 '파서가 어느 zstd 프레임을 RGBA로 뽑았나'를 검증 안 하면 GIGO —
  자기채점 차단도 GIGO 를 못 막는다. grounded record = evidence/c1_marker_detect_refixed_20260624.json.

★정직성: C1 검출은 grounded progressive 지만 **CONFIRMED 아님** — 전 212뷰 lot-경계 확정 미완.
  C2~C5 + precision_floor 는 여전히 **OPEN frontier**(미측정). 퇴행/기각 교훈은 BPC 줄기 상속.

정본 사양: /data/kjra/PROJECT/3D/SX3i_ICP_SPEC/PROGRAMME.md
실행: python -m examples.sx3i_icp_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics
from examples.bpc_icp_programme import _n, NODES as BPC_NODES, FRONTIER as BPC_FRONTIER

# 이 가지가 BPC 줄기의 어느 마디에서 피어나는가.
BLOOM_AT = 'v8_pipeline'

# ── SX3i 가지 노드 (2026-06-24 리더fix 후 재배선) ─────────────────────────────
BLOOM_NODES = [
    _n('sx3i_prob', 'canonical_stage', BLOOM_AT, algo='problem',
       comment='SX3i = Zivid3 XL250 lot(sx3i_20260615 ×212). XL250 ArUco 정합 → 독립검증 sub-0.1mm. '
               'BPC v8_pipeline 의 미완 step 6.1(precision≠accuracy) 을 XL250 에서 처음 닫는 수직심화 가지. '
               '2026-06-24 리더버그 정정 후 C1 검출 grounded.',
       limitation='C2~C5 + precision_floor 는 여전히 OPEN frontier(미측정). 정합법/퇴행교훈은 BPC 줄기 상속.'),

    # ── C1: XL250 ArUco 검출 — 재grounding PROGRESSIVE (리더fix 후 깨끗이 검출) ──
    _n('c1_marker_detect', 'progressive', 'sx3i_prob', m=8.28, scope='detection',
       nr=True, nc=True, q=['q_xl250_gsd'],
       comment='고친 zdf_reader(float RGBA 색) + STRICT DICT_4X4_250(denoise 0) 재검출: 40뷰 중 34뷰·'
               '총 331마커·평균 8.28/뷰·max 21·side_px median 90.6px(20px 룰 100% 통과)·cross-view 반복 ID 28종. '
               '마커 물리실재·DICT 정답 확인. grounded record=evidence/c1_marker_detect_refixed_20260624.json.',
       limitation='CONFIRMED 아님: 전 212뷰 lot-경계 인지 확정 미완(40뷰 샘플·다중-lot 혼재 6/40 무마커=딴 장면). '
                  'progressive 근거. C2(assembly)부터 다음.'),

    # ── 리더 프레임-오선택 버그 규명+수정 = 이번 라운드의 진짜 진보 ──
    _n('reader_frame_provenance_fix', 'progressive', 'c1_marker_detect', nr=True, nc=True,
       comment='근본원인 규명+수정(novel, confirmed): prismv2 zdf_reader.read_rgb 의 _read_native_rgba 가 '
               '바이트길이로만 색 프레임을 골라 N*4-byte SNR(float32) 맵을 색으로 오선택→uint8 캐스팅(보라쓰레기). '
               'fix=float-색-우선(8+N*16) + SNR-가드 + read_snr 노출, uint8 contract/back-compat 보존(15 테스트 GREEN). '
               '6가지로 SNR 정체 증명(ch3==float32>>24 100% 등).',
       limitation='BPC 는 다른 stride 버그(N*16 색프레임 부재, side불일치 moiré) — 이 패치로 안 고쳐짐(별건).'),

    # ── 폐기 가지(보존=교훈): speckle/denoise/재촬영 가설 — 전부 리더버그의 그림자 ──
    _n('misdiag_reader_frame', 'rejected', 'c1_marker_detect',
       comment='2026-06-23 의 가설들 — (a) "organized speckle 로 검출취약", (b) "denoise-salvage 불가"(c1b), '
               '(c) "Settings2D 누락→재촬영 필요"(분기A) — 전부 REJECTED. 실제론 read_rgb 가 SNR 프레임을 '
               '색으로 오선택했을 뿐, 데이터·캡처는 멀쩡. 고친 색프레임에선 STRICT 기본파라미터로 검출됨.',
       limitation='보존 교훈(기둥5): 물리적으로 그럴듯한 서사(structured-light speckle)가 잘못된 바이트 위에 '
                  '얹히면 검증을 늦춘다. 자기채점 차단도 GIGO 를 못 막음 — grounded 게이트에 디코드-프레임 '
                  '검증을 추가하라. 보존된 자산: consistency 게이트·recapture_gate 사전등록 골격·합성검정.'),

    # ── 분기 B: markerless C3 instrument — 리더버그와 독립, 그대로 유지 ──
    _n('c3_markerless_instrument', 'partial', 'sx3i_prob', nr=True, nc=False,
       q=['q_markerless_c3_inputs'],
       comment='C3(precision≠accuracy 독립게이트)를 마커 무관으로 치는 instrument 구축(scripts/markerless_c3.py: '
               'cross_view_coincidence + pairwise_spacing, 사전등록 band median≤0.10/p95≤0.15). 합성검정 통과 '
               '(진짜 CONFIRMED, 스케일오차 REFUTED). evidence/markerless_c3_20260623.md.',
       limitation='instrument ready. 입력은 2026-06-24 분기B 궤도서 마련: (i) per-view hole 추출기 '
                  'scripts/view_feature_extract.py(self-test 0.284mm), (ii) IGS scan-mesh nominal '
                  'CAD/sx3i_cad_nominal.json(홀9, scripts/cad_nominal_mesh.py). 실데이터 결과=c3_markerless_real.'),

    # ── 분기B 실데이터 시도(2026-06-24 궤도) — 입력 마련됐으나 markerless 정합 미성립(보존 음의분기) ──
    _n('c3_markerless_real', 'degenerating', 'c3_markerless_instrument', m=13.18, base=0.10,
       scope='registration', nr=True, nc=False, q=['q_markerless_c3_inputs'],
       comment='분기B 실데이터(2026-06-24): 마련된 입력(view_feature_extract + IGS scan-mesh nominal)으로 5뷰 '
               'markerless 정합 시도→실패. 1/5뷰만 CAD정합(허위 10.18mm RMS), 0/15 뷰쌍 ≥3홀 합동삼각형 공유'
               '(min 삼각오차 14.6mm), pairwise view-vs-scanCAD median 13.18mm(C3 band 0.10 의 130배). '
               'C3 instrument 합성검정은 OK(진짜 CONFIRMED/스케일 REFUTED)이나 실데이터 共검출 홀 부족 + scan-noise '
               'nominal 로 공통프레임 미성립. evidence/markerless_c3_real_20260624.json(적대검증 confirmed).',
       limitation='markerless-홀 경로=보존 음의분기 — 정합 미성립이지 trueness 측정 아님(13mm 는 대응불량 산물). '
                  '★1차 경로는 리더fix 로 부활한 마커(c1_marker_detect progressive)→C2 assembly→C3. '
                  'CAD nominal 도 scan재구성=precision≠accuracy(GD&T truth 아님, 정밀 trueness 엔 STEP/CMM 필요).'),

    # ── C3 물리관문 측정(2026-06-24): 마커-coincidence path 도 sub-0.1mm 11× 미달 → 사전등록 예측 REFUTE ──
    # ★verdict='rejected' = 엔진 judge_record 판결과 정렬(손입력 'degenerating' 과대였음; 예측 falsify=rejected).
    _n('sx3i_precision_floor_marker', 'rejected', 'sx3i_prob', m=1.076, base=0.10,
       scope='registration', nr=True, nc=False, q=['q_sx3i_precision_floor'],
       comment='q_sx3i_precision_floor 측정(scripts/c3pre_precision_floor.py): SX3i=삼각대 자유이동(기하구속0, 정합 '
               '100% ArUco DICT_4X4_250). held-out 마커 코너 독립정밀도(공유≥4 중 1개 빼고 Kabsch→빼낸 코너 |Δ|): '
               '181 뷰쌍·6188 코너 → median **1.076mm**·p95 242mm·min 0.029mm·<0.1mm 비율 0.2%. '
               '사전등록 예측(median ≤0.10mm) **REFUTE**(11× 초과). 즉 삼각대+XL250+마커정합으로 sub-0.1mm 물리 불가.',
       limitation='병목=삼각대 자유이동 registration(기하구속 0, pairwise Kabsch) + XL250 250µm 카메라 floor + lift 노이즈. '
                  'markerless 경로(c3_markerless_real 13mm)도 동반 미달 → 두 경로 모두 sub-0.1mm refute. '
                  '카메라(MR60 80µm)/근접WD/고정지그/CMM 재고 근거. ⚠️caveat: pairwise Kabsch(global bundle-adjust 미시도)·'
                  'crude median lift — 개선여지 있으나 10× gap+기하구속0 은 강한 음의신호. grounded record='
                  'evidence/c3pre_precision_floor_20260624.json.'),
]

# ── SX3i frontier (Laudan open/closed) ───────────────────────────────────────
BLOOM_FRONTIER = [
    # C1 — 측정으로 닫힘(grounded): 검출 OK + side_px median 90.6 ≥ 20.
    dict(name='q_xl250_gsd', status='CLOSED', closed_by='c1_marker_detect',
         body='C1: XL250 색에서 DICT_4X4_250 검출 & 마커 GSD ≥ 20px 룰 통과? → 답 YES(grounded). '
              '고친 리더+STRICT: 34/40뷰 검출, side_px median 90.6px(20px 의 4.5배), 100% ≥20px.'),
    # speckle/denoise/재촬영 — 리더버그가 만든 허위질문들, 정정으로 해소(CLOSED=교훈보존).
    dict(name='q_reader_frame_misdiagnosis', status='CLOSED', closed_by='reader_frame_provenance_fix',
         body='2026-06-23 의 speckle/denoise-salvage/Settings2D-재촬영 질문(옛 q_denoise_coverage·'
              'q_recapture_settings2d)은 read_rgb 의 SNR-프레임 오선택 버그가 만든 허위질문이었다 — '
              '리더 고침+재검출로 해소. 데이터 멀쩡, 재촬영 불필요. (음의결과=교훈으로 보존)'),
    dict(name='q_sx3i_assemble', status='OPEN', closed_by=None,
         body='C2: incremental puzzle 가 212뷰를 1 connected component, self-consistency p95 < 0.2mm?'),
    dict(name='q_independent_accuracy', status='OPEN', closed_by=None,
         body='C3⭐: feature-coincidence median ≤ 0.10mm — 마커 무관 독립 정밀게이트(BPC step 6.1 을 닫음).'),
    dict(name='q_raw_refine', status='OPEN', closed_by=None,
         body='C4: C2 puzzle INIT 위 raw-res ICP(geom+intensity) 로 overlap RMS sub-0.1mm?'),
    dict(name='q_crosscam', status='OPEN', closed_by=None,
         body='C5: XL250 ↔ MR60(zivid2Plus, BPC lot) cross-camera feature |Δ| < 0.15mm?'),
    # ── C3 앞 물리 관문 — 사전등록(2026-06-24, 측정 전. 리더버그와 무관하게 선결) ──
    dict(name='q_sx3i_precision_floor', status='OPEN', closed_by=None,
         body='C3 物理관문(사전등록 2026-06-24, 미측정=OPEN): XL250 단일샷 정밀도 250µm(zivid.py '
              'LensSpec precision_um, capture_qc "0.1mm washer XY 불가")가 C3 목표 100µm 의 2.5배 — '
              'multi-view 평균으로 floor 를 목표 아래로 끌어내릴 수 있는가? '
              '★사전등록 예측: (a) per-view feature(hole/boss) 중심 반복도 σ_view(다점 fit 이라 단일점 250µm '
              '보다 이미 우수), (b) N 중첩뷰 융합 → σ_fused ≈ σ_view/√N_eff 로 축소, (c) 중첩뷰쌍 '
              'feature-coincidence median |Δcenter| ≤ 0.10mm·p95 ≤ 0.15mm(C3 band, 측정 전 고정). '
              'noise_band 0.05, direction=lower. '
              '★반증(kill): 융합 median > 0.10mm 또는 σ_fused 가 √N 으로 안 줄면 → "XL250 단일카메라 '
              'sub-0.1mm 불가" 확정 → cross-camera(C5, MR60 precision 80µm) 또는 고밀도 재촬영으로 분기. '
              '측정수단: 분기B instrument(markerless_c3.py, cross_view_coincidence)로 212 zdf 에서 직접 — '
              '마커 문제 없음(C1 검출 grounded). 입력=뷰 feature 추출기(분기B 선결과제와 공유). '
              'C3 검증 없이 C4 refine 얹으면 헛디딤(BPC 반복실수). 이 관문이 C3⭐의 물리 전제다.'),
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

    sx3i_open = [q['name'] for q in BLOOM_FRONTIER if q['status'] == 'OPEN']
    sx3i_closed = [q['name'] for q in BLOOM_FRONTIER if q['status'] == 'CLOSED']
    n_prog = sum(1 for nd in BLOOM_NODES if nd['verdict'] in ('progressive', 'CANONICAL'))
    prog = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'progressive']
    partials = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'partial']
    rejected = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'rejected']

    _line('═' * 72)
    _line('  SX3i 가지 — XL250 ArUco → 독립검증 sub-0.1mm (3D 형상 검출 / BPC 줄기 접붙임)')
    _line('═' * 72)
    _line(f"\n  피어나는 마디        : {BLOOM_AT} (BPC v8 의 step 6.1 = precision≠accuracy 갭)")
    _line(f"  통합 트리 정본       : {m['canonical']}  ← 여전히 BPC(SX3i CONFIRMED 아님=정직)")
    _line(f"  진보 노드(SX3i)      : {n_prog}  {prog}  (C1 검출 grounded + 리더fix)")
    _line(f"  C1 verdict           : PROGRESSIVE — 34/40뷰·331마커·side_px 90.6px(20px 100%). CONFIRMED은 전212뷰 후.")
    _line(f"  ★2026-06-24 정정     : speckle/denoise/재촬영 = read_rgb SNR-프레임 오선택 버그의 그림자(REJECTED). 데이터 멀쩡.")
    _line(f"  폐기(교훈보존)       : {rejected}")
    _line(f"  분기 B(markerless)   : {partials} — C3 instrument ready, SX3i feature/STEP 입력 대기")
    _line(f"  SX3i closed frontier : {sx3i_closed}")
    _line(f"  SX3i open frontier   : {len(sx3i_open)}개  {sx3i_open}")
    _line(f"  핵심 정밀게이트      : q_independent_accuracy (C3⭐) ← 물리전제 q_sx3i_precision_floor 먼저")
    _line(f"  frontier 수지(통합)  : {m['laudan']['frontier_balance']}  (closed−open)")
    _line('\n' + '═' * 72)
    return dict(metrics=m, bloom_at=BLOOM_AT, open_frontier=sx3i_open, closed_frontier=sx3i_closed,
                sx3i_progressive=n_prog, sx3i_progressive_tags=prog,
                sx3i_partial=partials, sx3i_rejected=rejected, canonical=m['canonical'])


if __name__ == '__main__':
    run()
