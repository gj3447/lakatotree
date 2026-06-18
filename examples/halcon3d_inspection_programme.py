"""HALCON 기반 3D 검사 — 인터넷 리서치를 라카토스 연구 프로그램으로 *녹인* 도그푸드.

사용자 사양: "그 3d 분석 할콘 기반으로 분석 다른 인터넷 내용을 라카토트리에 녹여줘."

상계(read-only) reader 가 *실제로* WebSearch/WebFetch 한 HALCON 3D 분석 연구(``tests/fixtures/
halcon3d_internet_research.json`` — 12 레코드, 94 실 출처)를 두 층으로 트리에 녹인다:

  (1) import 층  — ``research_import.import_research_records`` 가 각 레코드의 *인터넷 증거*를 G-Web
                   게이트(scan_injection → web_gate → 분해신뢰 → ResearchEvent(INTERNET))로 적재.
  (2) 프로그램 층 — 레코드에서 *grounded 수치*(prediction/measured)만 뽑아 judge-채점 노드로. ★노드는
                   verdict 를 손입력하지 않는다(euler 도그푸드 규약). ``run()`` 이 judge → pnr →
                   dialectical_verdict 로 verdict 를 *생성*한다.

드러나는 라카토스 구조(전부 fixture 수치, 각 노드에 레코드 id 주석):
  protagonist P1 = HALCON 결정론 CAD-모델 매칭 (hard core: rigid CAD + 기하 voting + frozen 캘리브 →
                   학습데이터 없이 bounded·결정론 pose).
    · ppf_surface_match       PPF recall 0.77 > 0.70 (B) — 하드코어 확증(partial)
    · free_multiview_gicp     free 6-DOF GICP 가 0.93→2.78 mm 붕괴 (G/K rival) — *전역 반례*(rejected),
                              음의 휴리스틱이 금지하는 수
    · frozen_multiview_calib  frozen 변환(죄있는 보조정리 통합) + *미지 lot* 0.887 mm·seam 31/31 새
                              사실 예측·적중 (G/K) — lemma-incorporation → progressive(P&R 성숙)
    · aruco_backbone          ArUco frozen backbone seam 1.026 mm·RMS 0.27 mm (H/L) — 보호대(partial)
    · sheet_of_light          sheet-of-light RMS < 0.1 mm·±7 µm (D) — 측정 modality 확장(partial)
  rival P2 = 딥러닝 RGB-D 6D pose (다른 hard core: 학습 dense feature → 빠르고 고recall, 학습데이터·GPU·
             도메인시프트 비용).
    · densefusion_rival       DenseFusion ADD-S(2cm) 95.30% YCB (I) — *다른 프로그램*(P1 핵 미보존)

★정직: 두 프로그램은 서로를 반증하지 않는다 — regime 교차(YCB 텍스처 → DL, 산업 금속·무학습 → HALCON;
BOP'22 PPF 0.77 vs MegaPose 0.65)에서 각자 progressive. Lakatos 의 "경쟁 연구 프로그램" 정본 사례.
관련 스팬: world_gates G-Web import + verdict spine(judge/pnr/spine). euler_polyhedron_programme 자매.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from lakatos.engine import ResearchFrame, ResearchProject
from lakatos.research_import import import_research_records
from lakatos.verdict.judge import NovelTarget, Prediction, judge
from lakatos.verdict.pnr import (
    CounterexampleType,
    ProofGeneratedConcept,
    Response,
    appraise_response,
)
from lakatos.verdict.spine import dialectical_verdict

_FIXTURE = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "halcon3d_internet_research.json"


@dataclass(frozen=True)
class HalconNode:
    """프로그램의 한 노드. ★verdict 필드 없음 — 엔진이 런타임에 생성.

    수치는 전부 fixture 레코드에서 grounded (source_record = 레코드 id). 손입력 verdict 금지.
    """

    tag: str
    parent: str | None
    story: str
    source_record: str                          # fixture 레코드 id (수치 출처 추적)
    prediction: Prediction | None = None        # 사전등록(없으면 admin root = 프로그램 핵 확립)
    measured: float | None = None               # 실측(데이터 — verdict 아님)
    novel_target: NovelTarget | None = None     # 새 사실 예측(progressive 조건)
    novel_measured: float | None = None
    response: Response | None = None            # 반례 대응(없으면 변증법 미적용)
    excess_content: bool = False
    in_heuristic_spirit: bool | None = None
    proof_generated_concept: ProofGeneratedConcept | None = None
    counterexample_type: CounterexampleType | None = None
    hard_core_preserved: bool = True            # False = P1 핵 이탈(다른 프로그램 = 라이벌)


# 증명-생성 개념 — free-merge 붕괴 반례서 *탄생한* 제약(frozen 변환의 정체)
_FROZEN_TRANSFORM = ProofGeneratedConcept(
    name="frozen per-view rigid transform (translation-only merge)",
    born_from_counterexample="free_multiview_gicp (2353→876 mm footprint 붕괴, seam ×3.0)",
    incorporated_lemma="평면+주기 부품의 multiview merge 는 per-view 회전을 *고정*해야 한다 — free "
                       "6-DOF 는 rank-deficient null-space 로 붕괴(숨은 보조정리: 강체 frozen pose)",
)

NODES: tuple[HalconNode, ...] = (
    # ── P1 root: HALCON 결정론 CAD-모델 매칭 프로그램 핵 (admin root) ────────────
    HalconNode(
        tag="halcon_cad_programme", parent=None, source_record="A",
        story="HALCON 결정론 CAD-모델 매칭: rigid CAD + 기하 voting(PPF) + frozen 캘리브 → 학습데이터 "
              "없이 bounded·결정론 6DoF pose. ADD < 10% 부품지름 (find_surface_model).",
        # prediction None → 핵 확립(채점 대상 아님)
    ),
    # ── 하드코어 확증: PPF recall 0.77 > 0.70 (record B) ─────────────────────────
    HalconNode(
        tag="ppf_surface_match", parent="halcon_cad_programme", source_record="B",
        story="PPF surface matching 산업 bin-picking recall 0.77(>0.70 예측, metric=BOP bin-picking). "
              "F1 0.784(record A). ★cherry-pick 금지: 같은 record B 가 *LineMOD automotive* 에선 rigid "
              "surface matching 0.46 recall(훨씬 낮음) — PPF 는 regime 의존(텍스처·도메인). 하드코어 확증이되 "
              "한쪽 수치만 고르지 않음(새 사실 없음 → partial).",
        prediction=Prediction(metric_name="ppf_recall_bop", direction="higher",
                              baseline_value=0.70, noise_band=0.02,
                              novel_prediction="", closes_question="q-ppf-baseline"),
        measured=0.77,             # record B: "PPF baseline 0.77 recall across bin-picking datasets"
                                   #   (자매 수치: 같은 record B "0.46 recall on Linemod automotive" = 약한 regime)
    ),
    # ── 전역 반례: free 6-DOF GICP 붕괴 (record K rival) ─────────────────────────
    #   verdict='rejected' 는 *metric judge* 가 낸다(예측 falsify=전역 반례). 음의 휴리스틱은 이 merge
    #   방법을 *채택 금지*하는 정책층이고, 그 반례에 대한 positive-heuristic 응답이 아래 frozen_multiview_calib.
    HalconNode(
        tag="free_multiview_gicp", parent="ppf_surface_match", source_record="K",
        story="순진한 free 6-DOF multiview GICP 가 평면+주기 부품 merge 에서 *붕괴*: seam 0.93→2.78 mm "
              "(×3.0), footprint 2353→876 mm, yaw 82.3° 비물리. 예측(merge error<1.0mm) 전역 반증(rejected).",
        prediction=Prediction(metric_name="seam_systematic_mm", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="", closes_question="q-multiview-merge"),
        measured=2.78,             # record K rival: "seam ×3.0 worse (0.93→2.78 mm)" (정확 인용)
        # 추측(merge 됨)은 깨는데 어느 단계가 틀렸는지 불명 → 숨은 보조정리(free 회전) 신호
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,
    ),
    # ── lemma-incorporation: frozen 변환 + 미지 lot 새 사실 예측·적중 (record G/K) ─
    HalconNode(
        tag="frozen_multiview_calib", parent="free_multiview_gicp", source_record="K",
        story="죄있는 보조정리(free 회전)를 제약으로 통합 = frozen per-view 변환(translation-only). 그리고 "
              "*never-before-seen* VFEZ0050 lot 의 interior median 0.887 mm + seam gate 31/31 PASS 를 "
              "새 사실로 예측·적중(in-sample VFEZ0040 0.954 mm 대비 degrade 없음). 증명-생성 개념 탄생 → 성숙.",
        # ★source_record='K'(인터넷-import된 twin): 동일 0.887mm·31/31 수치를 든 record G 는 confidence=HIGH
        #   이나 인터넷 출처 0(순수 로컬)→ web_gate 가 import 거부(runtime rejected=['G']). K(arxiv/github/bop)
        #   가 같은 OOS 수치를 *인터넷 출처로* corroborate → 프로그램 노드는 provenance 있는 twin K 를 cite.
        #   (로컬-grounded 측정 vs 인터넷-provenance import 의 정직한 분리.)
        prediction=Prediction(metric_name="interior_median_mm", direction="lower",
                              baseline_value=0.90, noise_band=0.0,
                              novel_prediction="frozen 캘리브가 미지 lot 으로 일반화(out-of-sample transfer)",
                              closes_question="q-multiview-merge"),
        measured=0.887,            # record K: "interior 0.887 mm (VFEZ0050 OOS) ... seam gate 31/31 PASS"
        # 독립 초과내용: interior residual(mm) 과 *다른* 측정 = seam systematic gate 통과율(31/31=1.0)
        novel_target=NovelTarget(metric_name="oos_seam_gate_pass_ratio", direction="higher",
                                 threshold=1.0),
        novel_measured=1.0,        # record K: "seam systematic gate 31/31 PASS" = 31/31 = 1.0
        response=Response.PROOFS_AND_REFUTATIONS,
        excess_content=True, in_heuristic_spirit=True,
        proof_generated_concept=_FROZEN_TRANSFORM,
        counterexample_type=CounterexampleType.GLOBAL_NOT_LOCAL,
        hard_core_preserved=True,
    ),
    # ── 보호대: ArUco frozen backbone (record H/L) ──────────────────────────────
    HalconNode(
        tag="aruco_backbone", parent="frozen_multiview_calib", source_record="H",
        story="ArUco+frozen-backbone: marker RMS 0.27 mm/edge post-Kabsch(20-view ZDF)가 record H 예측 "
              "'XY-translation error < 0.5 mm' 을 만족. seam 1.026 mm median·ChArUco reproj 0.28–0.37 px "
              "(record H/L). 보조가설 보강(improved, 새 사실 없음 → partial).",
        # ★baseline·measured 둘 다 record H grounded(felt 금지): 예측=H "XY-translation error < 0.5 mm",
        #   measured=H "marker RMS 0.27 mm/edge post-Kabsch"(Kabsch 후 fiducial 등록잔차 = XY 정확도 proxy).
        prediction=Prediction(metric_name="aruco_marker_rms_mm", direction="lower",
                              baseline_value=0.5, noise_band=0.0,
                              novel_prediction="", closes_question="q-fiducial-backbone"),
        measured=0.27,             # record H: "marker RMS 0.27 mm/edge post-Kabsch over 20-view ZDF"
    ),
    # ── 보호대(측정 modality 확장): sheet-of-light (record D) ────────────────────
    HalconNode(
        tag="sheet_of_light", parent="halcon_cad_programme", source_record="D",
        story="HALCON sheet-of-light(레이저 삼각측량) reconstruction RMS < 0.1 mm 예측. 결정론 프로그램의 "
              "*별도 측정 modality plausibility* (HALCON-native RMS 미공개 → Artec accuracy proxy, partial).",
        # ★metric 타입 정직(felt 금지): record D 는 HALCON-specific RMS 수치 *미공개* 명시 → 같은 record D 의
        #   가장 가까운 reconstruction-accuracy 수치(Artec 0.02 mm)를 proxy 로. ±7µm 은 repeatability(정밀도,
        #   다른 metric 타입)라 RMS 채점에 안 씀.
        prediction=Prediction(metric_name="sol_recon_accuracy_mm", direction="lower",
                              baseline_value=0.1, noise_band=0.0,
                              novel_prediction="", closes_question="q-active-3d"),
        measured=0.02,             # record D: "Artec Point industrial scanner: 0.02 mm accuracy"
    ),
    # ── 라이벌 프로그램 P2: 딥러닝 RGB-D 6D pose (P1 핵 미보존 = different programme) ─
    HalconNode(
        tag="densefusion_rival", parent="ppf_surface_match", source_record="I",
        story="DenseFusion(RGB-D 학습 dense fusion) ADD-S(2cm) 95.30% YCB-Video(CVPR2019), HALCON PPF "
              "~90% 대비 +3.5%·200x 빠름. ★*다른 hard core*(학습 feature ≠ CAD 결정론) → P1 안의 수가 "
              "아니라 라이벌 프로그램. 핵 미보존 → different_programme(퇴행 아님, 정체성 축).",
        prediction=Prediction(metric_name="ycb_add_s_pct", direction="higher",
                              baseline_value=90.0, noise_band=1.0,
                              novel_prediction="", closes_question="q-dl-rival"),
        measured=95.30,            # record I: "ADD-S (2cm) = 95.30%" YCB-Video
        # ★response 는 _appraise_core 진입 트리거일 뿐 — hard_core_preserved=False 가 SURRENDER 외 모든
        #   response 를 'different_programme' 로 덮어쓴다(pnr.py short-circuit, 검증됨). 즉 EXCEPTION_BARRING 은
        #   inert placeholder 지 "DenseFusion 이 도메인 축소한다"는 주장 아님. run() 이 None response 는
        #   appraise 안 하므로 non-None·non-SURRENDER 가 *구조적으로* 필요할 뿐.
        response=Response.EXCEPTION_BARRING,
        excess_content=False, in_heuristic_spirit=False,
        hard_core_preserved=False,             # 학습 feature = P1(CAD 결정론) 핵 이탈 → different_programme 판정
    ),
)


def run() -> list[dict]:
    """프로그램을 엔진에 태운다 — 각 노드 verdict 를 judge/pnr/변증법이 *생성*(손입력 0)."""
    out: list[dict] = []
    for n in NODES:
        if n.prediction is None:
            out.append(dict(tag=n.tag, source_record=n.source_record, metric_verdict=None,
                            pnr_verdict=None, dialectic_status="root", verdict="canonical_stage",
                            reasons=()))
            continue
        mv = judge(n.prediction, n.measured, n.novel_target, n.novel_measured)
        appraisal = None
        if n.response is not None:
            appraisal = appraise_response(
                n.response, excess_content=n.excess_content, novel_corroborated=mv.novel,
                in_heuristic_spirit=n.in_heuristic_spirit,
                hard_core_preserved=n.hard_core_preserved,
                proof_generated_concept=n.proof_generated_concept,
                counterexample_type=n.counterexample_type)
        final = dialectical_verdict(mv.verdict, appraisal, lakatos_result=None)
        out.append(dict(
            tag=n.tag, source_record=n.source_record,
            metric_verdict=mv.verdict, novel=mv.novel,
            pnr_verdict=(appraisal.verdict if appraisal else None),
            dialectic_status=final["status"], verdict=final["verdict"],
            reasons=tuple(final.get("reasons", ())),
        ))
    return out


def dissolve_internet_evidence() -> tuple[ResearchFrame, dict]:
    """import 층 — 12 레코드의 *인터넷 증거*를 G-Web 게이트로 같은 트리에 녹인다.

    프로그램 노드 tag 와 레코드 id 를 잇는다(tag_of=레코드 _id). 반환 (frame, import 보고 dict).
    """
    research = json.loads(_FIXTURE.read_text())
    frame = ResearchFrame(ResearchProject(
        name="halcon-3d-inspection",
        goal="HALCON 결정론 CAD-모델 매칭으로 차부품 6DoF 검사 — 딥러닝 라이벌과 경쟁",
    ))
    report = import_research_records(
        frame, research["records"], retrieved_at=research["_provenance"]["retrieved_at"],
        tag_of=lambda r: r["_id"])
    return frame, {
        "imported": report.n_imported, "rejected": [r["tag"] for r in report.rejected],
        "n_internet_events": report.n_events, "n_sources": report.n_sources,
    }


def rival_regime_crossover() -> dict:
    """라이벌 P1(HALCON) vs P2(딥러닝)의 *정직한 regime 교차* — 누가 어디서 이기나(fixture grounded).

    어느 프로그램도 반증되지 않는다. 각자 다른 regime 에서 progressive(Lakatos 경쟁 프로그램).
    ★정직: P2(딥러닝)는 이 트리에서 *단일 라이벌 sketch 노드*(densefusion_rival)로만 들어와 있고 in-tree
    적대검증을 거치지 않았다 — 'neither_refuted' 는 "둘 다 끝까지 몰아봤다"가 아니라 "현재 증거로 한쪽
    일방승리 없음"이다. HALCON 타이밍도 0.9s/scene(record J)~10–100s/full-cycle(record I)로 폭이 넓어
    결정론 regime 우위는 *속도*가 아니라 *무학습·결정론*에 있다.
    """
    return {
        "ycb_textured_objects": {"winner": "P2_deep_learning",
            "evidence": "DenseFusion ADD-S 95.30% vs HALCON PPF ~90% (record I)"},
        "bop2022_industrial_metal": {"winner": "P1_halcon_ppf",
            "evidence": "BOP'22 recall PPF 0.77 vs MegaPose 0.65 / CosyPose 0.63 (record B)"},
        "no_training_data_deterministic": {"winner": "P1_halcon_ppf",
            "evidence": "HALCON: CAD-model, no training, 결정론 (record J); P2 는 100k+ 합성샘플·GPU·"
                        "도메인시프트 비용 (record A/I). ★우위는 결정론·무학습이지 속도 아님(아래 참조)."},
        "speed_realtime": {"winner": "P2_deep_learning",
            "evidence": "DenseFusion <1s vs HALCON PPF 10–100s/full-cycle (record I; cf. 0.9s/scene record J)"},
        "verdict": "neither_refuted — 경쟁 프로그램, regime 별 progressive (Lakatos). P2=단일 sketch 노드(미完 적대검증).",
    }


if __name__ == "__main__":
    print("=== 프로그램 층 (verdict = 엔진 생성, 손입력 0) ===")
    for r in run():
        print(f"  {r['tag']:24} [{r['source_record']}]  metric={str(r.get('metric_verdict')):>11}  "
              f"pnr={str(r.get('pnr_verdict')):>18}  → {r['verdict']}")
    print("\n=== import 층 (인터넷 증거 G-Web 게이트 통과) ===")
    _frame, rep = dissolve_internet_evidence()
    print(f"  imported={rep['imported']}  rejected={rep['rejected']}  "
          f"internet_events={rep['n_internet_events']}  sources={rep['n_sources']}")
    print("\n=== 라이벌 regime 교차 (정직: 누구도 반증 안 됨) ===")
    for regime, d in rival_regime_crossover().items():
        if regime == "verdict":
            print(f"  → {d}")
        else:
            print(f"  {regime:34} winner={d['winner']}")
