# BACKTEST PROTOCOL — 엔진 효과성 후향 블라인드 백테스트 (사전등록 정본)

> 상태: **사전등록 설계 정본** (측정 착수 전). corpus 동결 후 해시를 §10에 기록.
> 계승: `docs/C3_EFFECTIVENESS_PROTOCOL.md` (superseded — 골격만 계승, n=9 검정력 설계는 폐기).
> 결정 근거: `SYMPOSIUM/THEORY/lakatotree/DECISION_PROM16_4ITEMS_2026-07-24.md` D1.
> 발주: PROM 16 §C 권고 (n=9/팔 = 40pp 차이에서 검정력 26% → 무정보 설계).

## 0. 한 줄

**LakatoTree(사전등록+novel 게이트+3층 스택)가 naive(self-report)와 POPPER-류(외부 자동판정기)보다
*거짓 진보(false progressive)*를 더 적게 찍는가** — 같은 코퍼스·같은 입력에 페어드로 돌려 McNemar로 잰다.
엔진은 appraise 하지 generate 하지 않는다. 판정 특이도를 재지 발견율을 재지 않는다(C3 §0 범위 계승).

## 1. 가설 (사전등록)

- **H1**: `FPR_lakatotree < FPR_naive` AND `FPR_lakatotree ≤ FPR_popper_like`
  (1차 지표 = false-progressive rate: 지상진리상 퇴행/날조인데 progressive 판정한 비율).
- **H0**: FPR 차이 없음.
- **반증 조건(구체)**: 코퍼스 N≥20 확보 후 McNemar exact (양측 α=0.05)에서 naive 대비 우위 불성립,
  또는 자체 특이도 하한(§4) 미달이면 H1 기각.
- **null 결과도 정직하게 출판** (C3 §1 계승 — "honest gap").

## 2. 장치 (페어드 3-장치 — 동일 사례·동일 증거 투입)

| 장치 | 판정 방식 | 역할 |
|---|---|---|
| **A. naive** | 개선 감지만 = "measured 가 baseline 보다 나으면 progressive" (사전등록·novelty 무시) | confabulation baseline (C3 조건 B 계승) |
| **B. popper_like** | 사전등록 예측 충족 여부만 (novel/구조 게이트 없는 단층 판정기) | 외부 대조 — POPPER(ICML 2025) 류의 최소 기능형 |
| **C. lakatotree** | 정본 파이프라인: judge(사전등록 novel 게이트) → stack(Popper/Bayes/Laudan, quorum 2) → eureka(측정-red) | 피험체 |

세 장치 모두 **동일한 사례 패키지**(예측·측정값·증거)를 받는다. 패키지에는 장치 식별자가 없다(§5 블라인드).
판정 실행은 스크립트로, 판정자(사람)는 출력의 장치 라벨을 모른다.

## 3. 코퍼스 (N=20~30, 3원천 혼합)

| 원천 | 수 | 내용 | 지상진리 |
|---|---|---|---|
| 프로젝트 dogfood | 6 | 기존 ground-truth 보유 예제 (euler, bpc_inspection, consumer3d 등) | 이미 검증된 정본 |
| 외부 사례 | 8~14 | 공개 재현성 사건·역사적 프로그램 (Sakana CUDA, METR o3 행동, SWE-bench 리크류 + C3 역사 사례 중 선별) | 2인+ 독립 판정자가 outcome-blind로 합의 동결 |
| 합성 날조 | 6~10 | sabotage 주입: metric은 개선됐으나 ① novel 부재(ad-hoc) ② 측정 오염 ③ 사전등록 후 변경 ④ 선택적 보고 | 제작 시 정의 (날조 유형이 곧 지상진리) |

선정 규칙: **결과를 알기 전에** 선정 기준을 동결한다. 외부 사례의 포함/제외는 판정 결과가 아니라
출처 신뢰도(1차 소스 존재)로만 결정. 합성 날조는 코퍼스의 최소 25% — 이것이 없으면 분자(FP)가 0이 된다
(METR/SHADE-Arena 교훈: 날조 탐지율엔 주입 날조가 필요).

## 4. 지표 (전부 기존 엔진 primitive — dogfood, 순환성 차단 규칙 준수)

- **1차 — FPR(false-progressive rate)**: 지상진리 퇴행/날조 사례 중 progressive 판정 비율, 장치별.
- **2차 — 특이도(specificity) 하한 규칙**: 민감도만으로 이기는 것을 막기 위해, 장치 C의
  true-progressive 재현율이 사전등록 하한(초기값 0.70, Wilson 하한 기준) 미달이면 "탐지력 있는 보수성"이
  아니라 "무판정"으로 기록하고 H1 주장을 철회한다.
- **3차 — 보정**: 등록 credence vs 실현의 Brier/log (calibrate.py). 해당 장치만.
- **부록 A — 층 실효 (D2 연계)**: 같은 실행에서 leave-one-layer-out replay — stack 3층(popper/bayes/laudan)을
  한 층씩 빼고 판결 flip 관측 (`lakatos/programme/flip.py` 의 반사실적 피벗 정의 그대로). contested 코퍼스에서도
  flip=0 인 층은 reporting-only 강등 후보로 표기(그때 결정, 지금 아님).
- **부록 B — 상수 민감도 (D4 연계)**: 대표 정책 상수(abandon_credence, stack_quorum, credibility_*_trust,
  bf_progressive)를 ±1단계 흔들어 판결 flip 관측. flip 유발 상수는 문헌 근거 승격 후보로 표기.

## 5. 블라인딩 (Soderberg 함정 차단)

- 전 장치 동일 패키징: 영수증 포맷·필드 순서·산출물 수를 맞춘다 (영수증 노출 시 팔 추측 가능 → 누수).
- 판정 후 판정자에게 **팔 추측 질문**("방금 본 출력이 어느 장치 것 같았는가")을 묻고 추측률을 보고한다.
  추측률이 우연 수준을 유의하게 넘으면 블라인드 실패로 기록하고 해당 판정자 분은 민감도 분석에서 제외.

## 6. 통계 계획 (사전등록, 데이터 보기 전 동결)

- 1차 비교: 장치별 FPR — **McNemar exact** (페어드 이진: 같은 사례에서 C는 옳고 A/B는 틀린 불일치 쌍).
- 신뢰구간: Wilson 95% (grounding.wilson_lower_bound 재사용).
- 다중성: 장치 쌍 2개(C vs A, C vs B) — Bonferroni α=0.025 (quant.multiplicity 재사용).
- 검정력 근거: N=20~30 코퍼스에 날조 6~10이면 FP 기회가 충분하고, 페어드 McNemar는 불일치 쌍 기반이라
  독립 n=9×2 설계(검정력 26%)보다 같은 N에서 우월. 부족 시 판정은 "검정력 부족"으로 정직 보고.
- 효과크기: 차이를 cohen_d_grade 밴드로 해석, raw 숫자 단독 인용 금지.

## 7. 타당도 위협 (C3 §6 계승 + 추가)

1. **순환성(치명)**: 지상진리는 외부(독립 인간 합의/날조 제작 정의)다. 엔진 출력을 지상진리로 쓰는 사례는 즉시 제외.
2. **선택 편향**: 사례 선정은 결과를 알기 전. 역사 사례는 승자 기지 편향을 명시.
3. **날조 현실성**: 합성 날조가 너무 쉬우면(FP 탐지가 자명) 민감도 부풀림 — 날조별 탐지율을 개별 보고하고
   "자명 등급"을 분리 집계한다.
4. **백테스트 ≠ 전향**: 이 설계는 "과거 날조를 탐지하는가"만 증명한다. 미래 연구를 낫게 한다는 주장은
   별도 전향 무작위 배정 실험(Phase 4)의 몫이며, 이 문서 어디에도 그 주장을 쓰지 않는다.
5. **판정자 표본**: 독립 판정자 2인은 외부 인간이 이상적이나, 현실 대안(다른 모델 계열 + 사람 1인)을 쓸 경우
   그 한계를 결과에 병기한다.

## 8. 단계

- **B0 — 코퍼스 구축·동결** (게이팅): 3원천 수집 + 지상진리 합의 + `corpus_manifest.json` (sha 포함) 커밋.
  이것 없이 측정 불가.
- **B1 — 장치 어댑터 구현**: naive/popper_like 는 엔진 primitive 의 *얇은 래퍼*로(판정 로직 신규 작성 금지 —
  장치 B는 judge 의 novelty 게이트만 끈 형태가 아니라 독립 단층 규칙으로, 순환성 방지).
- **B2 — 블라인드 실행**: 패키징 → 장치별 실행 → 판정자 outcome-blind 라벨링 → 팔 추측 질문.
- **B3 — 분석·보고**: §6 계획대로. null이면 null대로. 부록 A/B 결과를 같은 보고서에 동봉.

## 9. 결정 규칙

- H1 지지(1차 통과 + 특이도 하한 통과) → 효과크기와 함께 보고, Phase 4(전향 실험) 승급 검토.
- H1 반증 → "엔진 효과 미입증"을 README 톤 하향과 함께 정직 기록.
- 검정력 부족(불일치 쌍 부족) → 무정보로 보고, 코퍼스 확충 외 결론 없음.
- **어느 쪽이든 null은 실패가 아니라 결과다** (C3 §8 계승).

## 10. 동결 기록 (측정 착수 시 채움)

- corpus_manifest.json sha256: (미기록)
- 지상진리 판정자: (미기록) / 합의 일시: (미기록)
- 분석 스크립트 sha256: (미기록)
- 사전등록 시각: (미기록 — OTS 앵커 대상, PROM 16 L2)

---

*이 프로토콜은 C3 의 골격(사전등록·순환성 차단·null 출판·임계 동결)을 계승하고, 검정력 설계를
페어드 McNemar + 합성 날조 코퍼스로 교체한 것이다. 측정 착수 = B0 코퍼스 동결 후.*
