"""Dogfood — DATUM(GD&T Datum Reference Frame, 3-2-1)을 3D 형상 검출 트리의 가지로 모델링.

3D 형상 검출 통합 프로그램의 DATUM 가지. BPC 줄기의 **`aruco_metric` 마디에서 피어난다** —
ArUco 마커-Kabsch(BPC/SX3i)·markerless surface-match(LX3) 와 나란한 *세 번째 정합 프레임*:
마커 없이 CAD GD&T datum 으로 프레임을 잡는다. 동기 = 마커 self-consistency 의 precision≠accuracy
벽(+LX3RT color 깨짐)을 GD&T DRF 로 우회 — 편차가 곧 도면-적합 *독립검증*.

★정직성: 측정 없는 conjecture 를 progressive 로 박는 것은 자기채점=가짜green 이므로 금지.
2026-06-24 첫 구동: D2~D4 는 합성 ground-truth 로 instrument-valid(PARTIAL), D1 은 실 CAD 추출
(PARTIAL, 직교 triple 0 = 음의결과), D5(실부품)는 OPEN frontier. progressive 0개(정직).

정본 사양: /data/kjra/PROJECT/3D/DATUM/PROGRAMME.md
실행: python -m examples.datum_programme   (서버/DB 불필요 — 순수 엔진)
"""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics
from examples.bpc_icp_programme import _n, NODES as BPC_NODES, FRONTIER as BPC_FRONTIER
from examples._evidence import load_record, is_grounded, summarize
from examples.record_judge import judge_record

# 이 가지가 BPC 줄기의 어느 마디에서 피어나는가 = 정합 프레임 결정점.
BLOOM_AT = 'aruco_metric'

# D3(exposes_hidden_error) 의 *실데이터* grounded 레코드 — 2026-06-24 synthetic→real.
# 엔진이 _evidence 계약(verdict 금지·사전등록·grounded)으로 수용/거부한다(자기채점 차단).
DATUM_EVID = '/data/kjra/PROJECT/3D/DATUM/evidence'
REAL_RECORDS = [
    f'{DATUM_EVID}/gdt_datum_designation_a110_20260624.json',  # 도면 datum A/B/C 전사(3출처 일치)
    f'{DATUM_EVID}/bestfit_vs_datum_real_lx3_20260624.json',   # LX3 실 lot: 부등식 + 은폐폭
    f'{DATUM_EVID}/verdict_flip_hunt_bpc_20260624.json',       # BPC 실 lot: verdict-flip 사냥
    f'{DATUM_EVID}/d5_real_part_drf_lx3_20260624.json',        # D5: 실 2-캡처 도면-datum repro σ(n=2 낙관)
    f'{DATUM_EVID}/d5_realdata_bush_repeatability_20260624.json',  # D5 실 n=10 raw-zdf bush σ 0.30mm(band FAIL)
    # bears_on q_real_part_drf 합류(LX3 ArUco): id-collision=wrong-dict/frame artifact 교정(Occam)
    '/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_aruco_idcollision_correction_20260624.json',
    # LX3 Occam 종합(precision/accuracy 갈라): 붕괴=3버그 증상, precision 풀림·accuracy OPEN
    '/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_occam_precision_recovered_20260624.json',
    '/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_occam_accuracy_open_20260624.json',
]


def ground_real_records(paths=REAL_RECORDS):
    """실 evidence 레코드를 엔진 계약으로 검증 + **엔진 판결 커널(judge_record)로 verdict 생성**.
    손-설정 0: 숫자 사전등록(value_leq/value_geq) 있으면 엔진이 verdict 생성, 없으면 ABSTAIN(정직)."""
    out = []
    for p in paths:
        try:
            rec = load_record(p)
        except FileNotFoundError:
            out.append(dict(path=p, status='OPEN(파일 부재)', engine_verdict='OPEN'))
            continue
        s = summarize(rec)
        jr = judge_record(p)                          # 엔진 판결 — verdict 생성 or ABSTAIN
        if jr['status'] == 'judged':
            v = jr['verdict']
            ev = getattr(v, 'verdict', None) or (v.get('verdict') if isinstance(v, dict) else str(v))
        else:
            ev = jr['status'].upper()                 # ABSTAIN(숫자baseline 부재) / INVALID
        out.append(dict(path=p, status='GROUNDED' if is_grounded(rec) else f'REJECTED {s["errors"]}',
                        conjecture=rec.get('conjecture'), branch=rec.get('branch'),
                        metric=s['metric'], measured=s['measured'], unit=s['unit'],
                        engine_verdict=ev,
                        findings=[f.get('body') for f in s['findings']]))
    return out

# ── DATUM 가지 노드 — 2026-06-24 첫 구동: 계측기 검증(synthetic) + 실 CAD 추출 ──
# progressive 0개(CANONICAL 미획득=정직). 측정으로 자란 마디 = D1~D4 partial 4개.
BLOOM_NODES = [
    _n('datum_prob', 'canonical_stage', BLOOM_AT, algo='problem',
       comment='DATUM = 마커없이 CAD GD&T datum(3-2-1 Reference Frame)으로 3D 데이터 정합 → 편차=GD&T-적합 '
               '독립검증. BPC aruco_metric(정합 프레임 결정점)에서 피어남 — 마커-Kabsch·markerless 와 나란한 '
               '3번째 프레임. 2026-06-24 첫 구동: 계측기 합성검증 + 실 CAD 추출(미측정 → PARTIAL).',
       limitation='D5(실부품 DRF)는 OPEN frontier. datum 지정 A/B/C 는 GD&T 도면 의존. 퇴행교훈은 BPC 상속.'),

    # ── D1: CAD datum 면 추출 — 실 STEP PARTIAL (추출 ✅ / 자동 triple 음) ──
    _n('cad_datum_extract', 'partial', 'datum_prob', nr=True, nc=False, q=['q_cad_datum_triple'],
       comment='CAD(STEP) datum 면 추출(scripts/cad_datum.py, pythonocc). LX3 STEP → 평면면 3572 raw '
               '→ 1862 병합(96s) ✅. evidence/d1_lx3_datum_candidates_20260624.json.',
       limitation='직교 3-2-1 triple = 0 — 상위 40개 큰 평면이 전부 ±Y 법선(평판형 weldment). 면적 휴리스틱 '
                  'datum 자동선택 반증 → hard core "datum 지정은 도면 GD&T 가 정한다" 실증. GD&T 폴더 datum '
                  '지정 들어와야 CONFIRMED.'),

    # ── D1b: 도면 GD&T datum 지정 전사 — 실 PPAP 도면 PARTIAL (q_cad_datum_triple 의 답) ──
    _n('gdt_datum_designation', 'partial', 'cad_datum_extract', nr=True, nc=False,
       q=['q_gdt_datum_designation'],
       comment='A110 *내부 설계의도* datum 전사(scripts/gdt_datum_designation.py): [A] RR_BODY_LH_BUSH(0,0,0) · '
               '[B] RR_BODY_RH_BUSH(0,805,0) · [C] FRT_BODY_LH_BUSH(-921,-144,140), GD&T ⊕⌀1.5|A|B|C. '
               '좌표=설계 outline + 그 Matplotlib 렌더 placeholder PDF(같은 저자/mtime, 독립 아님)=좌표 독립출처 ≈1; '
               'asme_datum LX3_DATUM_FRAME=라벨/DOF corrob(좌표 0). → D1 hard core "datum=도면이 정함" *내부* 실현. '
               'evidence/gdt_datum_designation_a110_20260624.json. 소급: LX3 Δ 가 이미 이 3 bush 사용.',
       limitation='전사(측정 아님). ⚠️외부 OEM/고객 도면 PENDING → 외부확정 아님(내부 설계의도만). '
                  'BPC 적용 GATED: 3 body bush 가 183-피처 report 에 부재 → true-datum BPC flip 은 datum-bush 측정(D5) 필요.'),

    # ── D2: 3-2-1 DRF instrument 강체 복원 — synthetic PASS ──
    _n('drf_instrument', 'partial', 'datum_prob', m=0.0, base=1e-6, nr=True, nc=False,
       mn='datum_drf_recovery_maxdev',  # synthetic 강체복원 max_dev(무차원·거리 아님) — 자체 family
       q=['q_drf_recovers'],
       comment='3-2-1 DRF 구성기(scripts/datum_frame.py: build_drf/transform_between/deviate_in_drf). '
               '사전등록 band: 임의 강체 200회 비-datum max_dev < 1e-6mm. 실측 max_dev=0.0 ✅(순수 기하).',
       limitation='합성 GT 일 뿐 — 실측 datum 면 입력(D5)은 미연결.'),

    # ── D3: DRF 노출 vs best-fit 은폐 ⭐ — synthetic PASS + 음의결과 보존 ──
    _n('exposes_hidden_error', 'partial', 'drf_instrument', nr=True, nc=False, q=['q_drf_vs_bestfit'],
       comment='hard core 실증(test_datum_frame T3): datum 무오차+비-datum 홀 1개 δ=0.30 주입. DRF 가 δ '
               '전부 노출(누설0), best-fit 은 21~62% 흡수(기하의존, 피처 적을수록↑)+무오차 홀 누설=은폐. '
               '재사전등록 불변부등식 4개 충족 ✅. evidence/d2_drf_synth_20260624.json. '
               '+2026-06-24 synthetic→REAL grounding(엔진 _evidence GROUNDED): LX3 실 lot 부등식 *방향* '
               '확증(best-fit RMS 13.46≤datum 20.41; 단 datum bush raw dev 25~42mm=조대-Z regime·비-datum n=1라 '
               'magnitude는 정합 artifact, 250µm와 비교불가) + BPC forward-flip 2건 중 WASHER_015(0.086 over)=marginal·'
               'WASHER_047(0.044 over)=MR60노이즈 내부, +역flip 1건(BIG_09 datum가 best-fit NG 0.966→0.782 구제, '
               '비보수성과 모순)·all-bush 변종 0 → 정직=최대 1 marginal flip(proxy datum·CMM부재).',
       limitation='음의결과 보존: 최초 magnitude band "best-fit<0.6·δ" 가 5피처서 0.2377 흡수로 REFUTED — '
                  '흡수분율 기하의존이라 magnitude 사전등록이 틀림 → 불변부등식으로 sharpening(credence 보정 1건). '
                  'REAL grounding caveat: BPC datum=내 선택(도면 A/B/C 아님, q_gdt_datum_designation OPEN), '
                  'flip Δ 0.09~0.17mm 가 MR60 노이즈 0.08mm 근처, trueness CMM부재 UNVERIFIED → partial 유지(progressive 아님).'),

    # ── D4: datum 면 노이즈 안정성 — synthetic PASS ──
    _n('noise_stability', 'partial', 'drf_instrument', m=0.0214, base=0.05, nr=True, nc=False,
       mn='datum_frame_sigma_mm',  # datum-frame 위치 σ(mm, band 0.05) — real_part_drf 와 같은 구성 = 한 family
       q=['q_drf_noise'],
       comment='datum 면 다점 LS 적합 평균화 이득(test_datum_frame T4). 사전등록: σ_pt=0.05mm 300회 → '
               '원점 σ_o<0.05mm·tilt p95<0.5°. 실측 σ_o=0.021mm ✅, tilt p95=0.033° ✅.',
       limitation='합성 GT. 실 datum 면 평탄도/segment 품질은 D5 에서.'),

    # ── D5: 실부품 DRF 재현성 — 실 2-캡처 PARTIAL (도면 datum, σ 부분측정) ──
    _n('real_part_drf', 'partial', 'drf_instrument', m=0.0485, base=0.05, nr=True, nc=False,
       mn='datum_frame_sigma_mm',  # datum-frame 재현 σ_p95(mm, band 0.05) — noise_stability 와 동일 구성 family
       q=['q_real_part_drf'],
       comment='실 2-캡처(GROUND_TRUTH trial_1·2) 도면 datum[A][B][C] DRF repro σ '
               '(scripts/d5_real_part_drf.py). datum σ_p95=0.0485mm < band 0.05 → PASS(경계). '
               'best-fit σ_p95=0.037 < datum 0.0485 → datum-target *점* anchoring 이 3 노이즈 점의 '
               'frame 노이즈 전파로 σ 키움 = 일방 datum-*면*(다점 평균)으로 가야 하는 동기. '
               '합성 linearity self-test 통과(ratio 2.06). evidence/d5_real_part_drf_lx3_20260624.json. '
               '⚠️+2026-06-24 실 n=10 갱신(d5_realdata_bush_repeatability, LX3 팀 측정 grounding): raw-zdf '
               'bush-center repeatability 3D σ=0.30mm >> 0.05 band = FAIL → **n=2 σ 0.0485(PASS)는 낙관**. '
               '정확도도 abc_refuted(386mm, 턴테이블 단일축 물리한계). σ·accuracy 둘 다 현 데이터 band 미달.',
       limitation='A110 datum=bush *점*(3-2-1 target)이라 datum_surface_extractor(평면)는 다른 용도(평면-datum 부품). '
                  'bush 다점평균=circle/cylinder-fit(lx3_bush_touchsky 존재, 재구현無). 실 n=10 σ 0.30 band-fail+accuracy '
                  'refuted → q_real_part_drf OPEN, **close=물리 재촬영(정면 multi-pose)이지 코드 아님**. DATUM≡LX3 '
                  'q_lx3_aruco_accuracy(bush 물리문제 합류). trueness CMM 부재 UNVERIFIED. 음의결과 보존(plan §5).'),

    # ── 기각: best-fit 을 DRF 로 착각 (이 가지가 정립) ──
    _n('bestfit_as_drf', 'rejected', 'datum_prob',
       comment='대칭 best-fit(전 피처 or datum 중심점 Kabsch)을 DRF 로 사용 = cad_metrology.align_and_deviate '
               '기존 경로. D3 가 이를 반증: 잔차 민주분산이 진짜 위치오차를 흡수·은폐(21~62%)하고 무오차 피처로 '
               '누설. datum 순서(A→B→C)·DOF 위계 없음.',
       limitation='GD&T 적합 측정의 기준으로 부적격. DRF(3-2-1)로 대체.'),
]

# ── DATUM frontier (Laudan open/closed questions) ────────────────────────────
BLOOM_FRONTIER = [
    dict(name='q_cad_datum_triple', status='CLOSED', closed_by=['cad_datum_extract'],
         body='D1: CAD 형상(면적)만으로 직교 3-2-1 triple 자동선택? → 답 NO. 평판형 weldment 는 상위 40면이 '
              '전부 평행(±Y). datum 지정은 도면 GD&T 가 정해야 함(hard core 실증).'),
    dict(name='q_drf_recovers', status='CLOSED', closed_by=['drf_instrument'],
         body='D2: 3-2-1 DRF 가 임의 강체로 옮긴 datum 으로 원 프레임 복원? → 답 YES. max_dev 0.0 (synthetic).'),
    dict(name='q_drf_vs_bestfit', status='CLOSED', closed_by=['exposes_hidden_error'],
         body='D3⭐: DRF 가 best-fit 보다 위치오차에 충실? → 답 YES. DRF 전부 노출·누설0, best-fit 21~62% 은폐 '
              '(기하의존)+누설. 불변 4충족. (synthetic) +REAL(2026-06-24): LX3 부등식 *방향* 확증(RMS 13.46≤20.41; '
              'magnitude는 조대-Z·n=1 정합artifact, 비교불가) + BPC 최대 1 marginal flip(WASHER_015 0.086 over; '
              'WASHER_047 노이즈내부; 역flip 1·all-bush 0). 도면 datum proxy·CMM 미정→magnitude UNVERIFIED.'),
    dict(name='q_drf_noise', status='CLOSED', closed_by=['noise_stability'],
         body='D4: datum 면 다점적합이 단일점보다 안정? → 답 YES. 원점 σ 0.021mm<0.05, tilt p95 0.033°<0.5°.'),
    dict(name='q_gdt_datum_designation', status='CLOSED', closed_by=['gdt_datum_designation'],
         body='도면 GD&T 가 datum A/B/C 지정? → 답 YES(*내부* 설계의도 전사). A110: [A] RR_BODY_LH_BUSH(0,0,0) · '
              '[B] RR_BODY_RH_BUSH(0,805,0) · [C] FRT_BODY_LH_BUSH(-921,-144,140), ⊕⌀1.5|A|B|C. 좌표 출처=설계 outline'
              '+그 렌더 placeholder PDF(1저자, 독립 아님), asme_datum=라벨 corrob(좌표0). ⚠️외부 OEM 도면 PENDING. '
              'CAD 형상 자동선택은 q_cad_datum_triple 로 부정 → 도면이 정함(hard core 내부 실현).'),
    dict(name='q_real_part_drf', status='OPEN', closed_by=None,
         body='D5🔬: 실 zdf 에서 datum 면(점군)+피처 추출 → DRF 정합 cross-capture σ<0.05mm, datum 면 평탄도 '
              'rms<0.1mm? **부분측정(real_part_drf partial)**: 실 2-캡처 도면-datum DRF σ_p95=0.0485<0.05 '
              'PASS(경계, n=2 약추정)·best-fit 0.037<datum 0.0485(점 anchoring 노이즈전파). **OPEN 유지** — '
              'datum-면 평탄도 미측정 + n=2 + 일방 tangent-plane DRF 미구현. 잔여입력=raw-zdf datum-면 추출기'
              '(=SX3i 분기B feature 추출기 공유). 닫히면 SX3i C3⭐ 와 합류.'),
]


def _line(c=''):
    print(c)


def run():
    """DATUM 가지를 BPC 줄기에 접붙여 통합 sub-tree 로 구동."""
    nodes = BPC_NODES + BLOOM_NODES
    frontier = BPC_FRONTIER + BLOOM_FRONTIER
    m = tree_metrics(nodes, frontier)

    _line('═' * 72)
    _line('  DATUM 가지 — GD&T Datum Reference Frame(3-2-1) (3D 형상 검출 / BPC 줄기 접붙임)')
    _line('═' * 72)
    _line(f"\n  피어나는 마디        : {BLOOM_AT} (정합 프레임 결정점 — 마커·markerless 와 나란한 3번째)")
    _line(f"  통합 트리 정본       : {m['canonical']}  ← 여전히 BPC(DATUM 미측정이라 정본 미획득=정직)")
    datum_open = [q['name'] for q in BLOOM_FRONTIER if q['status'] == 'OPEN']
    datum_closed = [q['name'] for q in BLOOM_FRONTIER if q['status'] == 'CLOSED']
    _line(f"  DATUM closed frontier: {len(datum_closed)}개  {datum_closed}")
    _line(f"  DATUM open frontier  : {len(datum_open)}개  {datum_open}")
    _line(f"  핵심 실증게이트      : q_drf_vs_bestfit (D3⭐, best-fit 21~62% 은폐 — DRF 가 노출)")
    n_prog = sum(1 for nd in BLOOM_NODES if nd['verdict'] in ('progressive', 'CANONICAL'))
    partials = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'partial']
    rej = [nd['tag'] for nd in BLOOM_NODES if nd['verdict'] == 'rejected']
    _line(f"  진보 노드(DATUM)     : {n_prog}  ← CANONICAL 미획득=정직(정본 진보 아직 없음).")
    _line(f"  측정 마디(DATUM)     : partial {partials} + rejected {rej}")
    _line(f"  D1 CAD 추출          : 평면 1862 병합 ✅ / 직교 triple 0 → GD&T 도면 datum 필요(음)")
    _line(f"  D2~D4 instrument     : synthetic PASS (복원 max_dev 0.0 · 은폐 실증 · 노이즈 σ0.021mm)")
    _line(f"  → 관문 D5(실부품)    : zdf datum-면 추출기(SX3i 분기B 공유) + GD&T 도면 datum 대기")
    _line(f"  frontier 수지(통합)  : {m['laudan']['frontier_balance']}  (closed−open)")

    # ── 실데이터 grounding + 엔진 판결(judge_record) — 손-설정 0, 엔진이 verdict 생성 ──
    real = ground_real_records()
    _line('\n' + '─' * 72)
    _line('  실데이터 grounded 레코드 — 엔진 _evidence 검증 + judge_record 판결(verdict 손-설정 아님)')
    for r in real:
        _line(f"  [{r['status']}] {r.get('branch')}: {r['metric']}={r['measured']} {r.get('unit','')} "
              f"→ 엔진 verdict={r.get('engine_verdict')}")
        for fb in (r.get('findings') or []):
            _line(f"       · {fb}")
    n_grounded = sum(1 for r in real if r['status'] == 'GROUNDED')
    n_judged = sum(1 for r in real if r.get('engine_verdict') in ('progressive', 'partial', 'equivalent', 'rejected'))
    n_abstain = sum(1 for r in real if r.get('engine_verdict') == 'ABSTAIN')
    _line(f"  → 엔진 grounded {n_grounded}/{len(real)} · **엔진 판결 {n_judged} judged + {n_abstain} abstain**. "
          f"judged=숫자 사전등록(value_leq/geq) → 엔진 생성 verdict(전부 partial=정직). "
          f"abstain=전사/노이즈-count = 기계판결 불가(엔진이 손-verdict 거부, 루프 진짜갭 노출).")
    _line('\n' + '═' * 72)
    return dict(metrics=m, bloom_at=BLOOM_AT, open_frontier=datum_open, closed_frontier=datum_closed,
                datum_progressive=n_prog, datum_partial=partials, datum_rejected=rej,
                canonical=m['canonical'], real_records=real, n_grounded=n_grounded,
                n_judged=n_judged, n_abstain=n_abstain)


if __name__ == '__main__':
    run()
