# C3 — 엔진 효과성 실험 프로토콜 (falsifiable)

> 외부 리뷰 B-5: *"euler/HALCON 도그푸딩은 신호일 뿐, 엔진으로 검증한 연구가 미검증 연구보다 낫다는 증거는 없다."*
> 이 문서는 그 주장을 **반증 가능한 사전등록 실험**으로 만든다. 측정은 corpus 확보 후(Phase 0) — 지금은 *설계 정본*.
> C2(`tests/test_layer_flip_audit.py`)가 이미 입증: 현 dogfood 6개는 층 대립을 0회 자극 = **corpus 가 얕다**. C3 는 그 위에서 출발한다.
>
> 정본 = 이 문서 + KG `ExperimentProtocol:C3_Effectiveness_20260621` (재배맨). seed = `seed-lakatotree-c3-effectiveness-experiment-20260620`.

## 0. 한 줄
엔진(judge 사전등록 게이트 + stack 3층 + eureka 측정-red)으로 *appraise* 한 연구 프로그램이, 같은 프로그램을
**LLM 자기보고**로 appraise 한 것보다 **ground-truth 일치·보정(calibration)·환각률**에서 우월한가 — Wilson 하한과
proper scoring 으로 **사전등록**해 측정한다. **엔진은 appraise 하지 자 generate 하지 않는다** — 이 실험은 *판정 정확도/보정*을
재지, 발견율을 재지 않는다(범위 정직).

## 1. 가설 (사전등록)
- **H1**: `accuracy_engine_LB > accuracy_selfreport_LB` AND `brier_engine + δ_b ≤ brier_selfreport`
  (엔진이 ground-truth 일치 Wilson 하한에서 더 높고, Brier 보정오차에서 δ_b 이상 낮다).
- **H0**(영가설): 두 조건 간 차이 없음.
- **반증 조건 (pre-registered, 구체)**: ≥9 resolved 프로그램(아래 표본근거)에서 BH-FDR 보정 후
  `accuracy_engine_LB ≤ accuracy_selfreport_LB` *또는* `brier_engine > brier_selfreport − δ_b` 이면 **H1 기각**.
  **null 결과도 정직하게 출판한다**(프로젝트 honesty 원칙 — "honest gap").

## 2. 조건 (within-programme, 같은 입력·다른 appraisal)
| 조건 | appraisal 방식 | 비고 |
|---|---|---|
| **A. engine** | `judge`(사전등록 novel gate) → `dialectical_verdict` → `stack`(Popper/Bayes/Laudan, quorum 2) → `eureka`(측정-red: 확증+substantial BF+순문제폐쇄) | 정본 파이프라인 |
| **B. self-report (control)** | LLM 이 사전등록·외부측정 없이 직접 verdict 선언(confabulation baseline) | 엔진이 이기도록 설계된 그 대상 |
| **C. ablation (선택)** | engine 에서 한 층 제거 — `flip.layer_flips` 로 어느 층이 결정 바꾸는지 | 어느 층이 효과의 원천인지(B-3 연계) |

조건 A/B 는 **동일 프로그램·동일 증거**에 적용(입력 통제). 라벨러는 ground-truth 에 **blind**.

## 3. Corpus (Phase 0 = 게이팅 의존)
정확도 측정엔 **ground-truth(어느 추측이 실제로 살아남았나)가 알려진** 프로그램이 필요. 출처 3종:
1. **역사적 과학 사례**(Lakatos 원전, 승자 기지): Euler 다면체(χ=2 반례→lemma), Lorentz vs Einstein, Copernicus vs Ptolemy 등 — `grounding.SOURCES` 에 이미 인용.
2. **프로젝트 dogfood ground-truth**: `examples/bpc_inspection_groundtruth.py`(정답 lot verdict 보유), HALCON/consumer_b 정합(검증된 정본).
3. **prospective 사전등록**: 현 self-dev 트리의 OPEN frontier 질문에 예측 등록 → 해소 대기(gold standard, 느림).

**표본 근거(thin-corpus 정면대응, C2)**: 프로젝트 자체 기준 `grounding.nobel_min_*` — Wilson 하한 ≥0.7 의 실효 통과선은 **9/9**.
따라서 조건당 **≥9 resolved 프로그램**이 없으면 "유의" 주장 금지(LB 가 임계 미달). N<9 면 *서술적 신호*로만 보고.

## 4. 결과 지표 (전부 기존 엔진 primitive — dogfood)
- **1차 — ground-truth 정확도**: appraisal 최종 verdict(CANONICAL/progressive 등)가 실제 살아남은 결론과 일치하는 비율. `grounding.wilson_lower_bound(k,n)` 로 소표본 과신 차단.
- **2차 — 보정(calibration)**: 등록 예측의 `pred_credence` vs 실현(0/1) 에 `calibrate.brier_score`/`log_score`/`calibration_error(ECE)`. 엔진이 더 잘 보정돼야(자기보고는 overconfident → log_score 강벌).
- **3차 — 환각률**: `eureka.eureka_rate` 의 `hallucination_rate`(felt∧¬true). 엔진이 self-report 대비 위양성(거짓 aha)을 낮춰야 — ~37% 인간 false-insight 기준선 대비.
- **다중비교**: 프로그램/지표가 여럿이면 `quant.multiplicity.false_progressive_screen`(BH-FDR + Bonferroni)로 family-level 위양성 차단.
- **효과크기**: 차이를 `grounding.cohen_d_grade` 밴드로 해석(raw 숫자 금지).

## 5. 통계 계획 (사전등록)
- 정확도: 조건별 Wilson 95% 하한 비교, δ_acc = (정책, 사전등록) 최소 의미차.
- 보정: Brier/log 차이 + bootstrap CI. ECE 10-bin(`grounding.ece_bins`).
- 보정 다중성: BH q=0.05(`grounding.fdr_q`).
- **분석 코드·임계·δ 를 데이터 보기 전 동결**(researcher DoF 차단) — 엔진의 사전등록 게이트로 자기적용(dogfood).

## 6. 타당도 위협 (Lakatos 정직 — 반드시 명시)
1. **순환성(치명)**: 엔진으로 엔진 성공지표를 채점하지 말 것. ground-truth 는 **외부**(역사적 해소/독립 인간)여야. eureka/judge 를 *성과 라벨*로 쓰면 무효.
2. **얕은 corpus(C2)**: N<9 면 Wilson LB 미달 → 주장 금지. 역사 사례는 유한·선택편향 위험.
3. **선택 편향**: 프로그램은 결과 알기 *전*에 선정(또는 역사 사례는 outcome-blind 라벨링).
4. **appraisal ≠ discovery**: 엔진은 판정만 — "더 나은 판정"이지 "더 나은 발견"이 아니다(범위 정직).
5. **self-report 조건 공정성**: control 도 같은 증거를 받아야(엔진에 유리한 정보비대칭 금지).

## 7. 단계 (corpus 없음 → 점진)
- **Phase 0 — corpus 구축**(게이팅): 역사 사례 ≥9 + dogfood ground-truth 정형화. *이게 선행 없으면 측정 불가.*
- **Phase 1 — 회고(blinded)**: 알려진-결과 사례에 engine vs self-report, outcome-blind 라벨러. 1차 영수증.
- **Phase 2 — 전향(prospective)**: open frontier 에 사전등록 → 해소 대기. gold standard(느림).

## 8. 결정 규칙
Phase 1 에서 H1 반증 조건 충족 → **"엔진 효과 미입증"을 정직 기록**(README 톤 하향). 충족 안 됨(=H1 지지) → 효과크기·LB 와 함께 보고, Phase 2 로 승급. **어느 쪽이든 null 은 실패가 아니라 결과다.**

---
*이 프로토콜은 엔진 primitive(judge/stack/eureka/calibrate/wilson/multiplicity/flip)로 자기 자신을 평가해 dogfood 하되, ground-truth 만은 외부에 둔다(순환성 차단). 측정 착수 = Phase 0 corpus 확보 후.*
