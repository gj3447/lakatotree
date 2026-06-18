# PIDNA 두 가닥 — 이론적 기반 · 독립 속성 · Longinus 바인딩 · 하네스 매핑

> PIDNA는 **이중나선(double helix)** 이다 — DNA처럼 *두* 가닥. 🔴붉은 가닥 ⊗ 🔵푸른 가닥.
> 본 문서는 두 가닥이 *무엇*인지(이론), *왜 독립*인지(직교 속성), *어디에 실재*하는지(Longinus), 그리고 *표준 용어로 무엇*인지(하네스 매핑)를 못 박는다.
> 상위: [`PIDNA.md`](PIDNA.md) · 시(詩): [`../TOUCH_THE_SKY.md`](../TOUCH_THE_SKY.md)

---

## 0. 한 줄 정의

**🔴 = 검증(justification/selection)** — 무엇이 *참으로 일어났는지* 결정론적으로 판정한다.
**🔵 = 추측(discovery/variation)** — 무엇이 *일어날 수 있는지* 생성한다.
두 가닥은 **독립**이어야 하고(§2), 매 칸(rung)에서 **염기쌍 [예측↔검증]** 으로 짝지어야 한다(§3). 독립 없으면 순환(자기채점=환각), 짝지음 없으면 헛것(증명 없는 꿈·셀 것 없는 기계).

---

## 1. 이론적 기반 — 두 가닥은 어디서 왔나

두 가닥은 우리가 발명한 게 아니라, 과학철학·인식론·공학이 **반복해서 같은 자리에서 발견한 이분법**이다. 정본 출처:

| 전통 | 🔵 푸른 가닥 (추측) | 🔴 붉은 가닥 (검증) |
|---|---|---|
| **Reichenbach 1938** (인식론 정본) | context of **discovery** (발견의 맥락) | context of **justification** (정당화의 맥락) |
| **Popper 1934/63** | bold **conjecture** (대담한 추측) | severe test / **refutation** (가혹한 시험·반증) |
| **Peirce** (추론양식) | **abduction** (가설생성, ampliative) | **deduction+induction** (시험, 진리보존) |
| **Campbell 1960 (BVSR)** | **blind variation** (맹목적 변이) | **selective retention** (선택적 보존) |
| **GAN (Goodfellow 2014)** | **Generator** G | **Discriminator** D |
| **Predictor–corrector** (수치해석) | **predictor** (예측자) | **corrector** (교정자) |
| **MCMC (Metropolis–Hastings)** | **proposal** kernel (제안) | **accept/reject** ratio (수락판정) |
| **본 워크스페이스 5무기** | 하네스/Design = **G** · 프로메테우스(불 훔침) | 나생문(羅生門)=D · ooptdd 영수증 · Longinus |

> 핵심: 이 일곱 전통이 *독립적으로* 같은 두 극을 짚었다는 것 자체가, 이분법이 임의 은유가 아니라 **인식의 구조적 사실**임을 시사한다(다중 독립 확증 = consilience).

---

## 2. 독립 속성 — 두 가닥은 *어떤 축에서* 직교하는가

두 가닥은 아래 **직교 축**들에서 서로 환원 불가능하다. 각 축은 한 가닥을 다른 가닥으로 *접을 수 없게* 만든다.

| # | 직교 축 (property) | 🔵 푸른 극 | 🔴 붉은 극 |
|---|---|---|---|
| P1 | 인식 맥락 (Reichenbach) | 발견 | 정당화 |
| P2 | 진화 작용 (Campbell BVSR) | 변이(생성) | 선택(보존) |
| P3 | 추론 양식 (Peirce) | abduction (ampliative) | deduction/induction (truth-preserving) |
| P4 | 시간 화살 | 전향적 — *일어날* 것을 예언 | 후향적 — *일어난* 것을 판정 |
| P5 | 내용 관계 (Popper) | content-**increasing** (초과경험내용) | content-**checking** (eliminative) |
| P6 | 결정성 | 확률적·생성적 (sampling) | 결정론적·재현가능 (script) |
| P7 | 접지/권위 | 내부 — 모델·prior (agent belief) | 외부 — 현실 영수증 (world-grounded) |
| P8 | 최적화 표적 | recall·도달 (coverage, sensitivity) | precision·건전성 (soundness, specificity) |
| P9 | 통계 오류 통제 | Type II↓ (miss 줄임, power) | Type I↓ (false positive 막음, α) |
| P10 | 막는 실패 모드 | 맹목·불모(아무 예언 없음) | 환각·과대주장(못 속이게) |

### 2.1 ★ 왜 *독립*이 핵심인가 — 비순환성 정리

> **한 가닥은 자기 출력을 스스로 검증할 수 없다 — 그러면 검증이 피검증 대상에 오염된다(순환).**

이것이 PIDNA가 *반드시 이중*나선인 이유다. 단일 가닥의 자기검증 = "내가 만든 답을 내가 채점" = [TOUCH_THE_SKY §어둠의 거울]의 자기보고 연극 = 환각. **두 가닥이 독립일 때만 한쪽이 다른 쪽을 비순환적으로 판정**할 수 있다. 독립성은 미학이 아니라 **검증의 건전성을 위한 형식적 필요조건**이다.

이 독립 요구는 공학에 이미 표준으로 존재한다:
- **oracle independence** — 테스트 오라클은 SUT와 같은 가정에서 유도되면 안 된다(tautology). (P3/P7)
- **train/test 분리·data leakage 금지** — 검증셋은 학습셋과 독립이어야 한다(overfit=자기확증). (P7/P8)
- **separation of powers / "don't mark your own homework"** — 생성자와 심판자의 권한 분리. (P10)
- **GAN**: G와 D는 *별개* 네트워크에 *대립* 목적함수. (P2/P10)

### 2.2 ★ 독립은 두 스케일에서 같은 원리다

prom(`OQ_PIDNA_TreeBranching`)의 분기 트리거 = **"검증경로의 독립"**. 즉:
- **rung 스케일**(한 칸): 🔴⊥🔵 독립이라야 비순환 검증이 선다.
- **branch 스케일**(트리 분기): 두 하위질문의 검증경로가 독립이 되면 가지가 갈라진다.
**독립(independence)이 PIDNA의 load-bearing 개념** — 한 칸을 세우는 것도, 가지를 가르는 것도 독립이다.

---

## 3. Longinus 바인딩 — 각 속성은 *어느 실재 심볼*에 꽂히나

> Longinus 규율: 환각 금지. 아래는 모두 `lakatos/` 실재 심볼(grep 확인, line 포함). 표면이 drift하면 sha256 baseline이 잡는다.
> 검증 도구: `python -c "import lakatos.<mod>"` + `grep -n`.

### 3.1 🔴 붉은 가닥 (검증/선택) — ReferenceSites

| 속성 | KG 개념 | 실재 심볼 (sourceId:line) | must_emit/역할 |
|---|---|---|---|
| 결정론 판정 (P3/P6) | `judge` 오라클 | `lakatos/verdict/judge.py:77` `judge()` · `:64` `Verdict` | 사전등록 예측 대비 스크립트 채점 |
| 사전등록 잠금 (P7) | registration gate | `lakatos/verdict/judge.py:72` `check_registration()` · `:15` `PredictionLocked` | 채점 후 예측 변경 금지(영수증 위조 방지) |
| 증거 가중·선택 (P2/P5) | Bayes 선택 | `lakatos/quant/bayes.py:57` `bayes_factor()` · `:69` `branch_credence()` | 판결 시퀀스→credence (선택적 보존) |
| 퇴행 가지치기 (P2/P8) | Laudan 폐기 | `lakatos/quant/laudan.py:75` `should_abandon()` · `:93` `should_abandon_sprt()` | degenerate 가지 영구 erase |
| 예측 정직성 채점 (P10) | proper scoring | `lakatos/quant/calibrate.py:14` `brier_score()` · `:32` `calibration_error()` | 🔵의 자기확신을 외부 기준으로 처벌 |
| 판결 권위 단일화 (rung) | spine | `lakatos/verdict/spine.py:44` `reconcile_verdict()` · `:67` `dialectical_verdict()` | 메트릭(🔴)+질적(🔵 P&R) 단일 판결 |
| 적대적 정당화 (P10) | Dung AF | `lakatos/verdict/argue.py:20` `grounded_extension()` · `:34` `verdict_stands()` | 판결이 반박 공격을 견디나 |
| 하드코어 보호 (P5) | 음의 휴리스틱 | `lakatos/programme/heuristic.py:81` `negative_heuristic()` · `lakatos/programme/agm.py:29` `HardCoreProtected` | modus tollens를 core에 못 겨눔 |
| 층간 정족수 (P9) | stack | `lakatos/programme/stack.py:48` `popper_vote()` · `:82` `stack_verdict()` | 3층 독립 투표 2/3 정족 |

### 3.2 🔵 푸른 가닥 (추측/변이) — ReferenceSites

| 속성 | KG 개념 | 실재 심볼 (sourceId:line) | must_emit/역할 |
|---|---|---|---|
| 다음 실험 생성 (P1/P2) | 양의 휴리스틱 | `lakatos/programme/heuristic.py:124` `generate_moves()` · `verdict/pnr.py:84` `PositiveHeuristic` | ABANDON/PUSH/PROBE/PRIORITIZE 수(move) *생성* |
| 탐색 방향 (P4/P8) | VoI·UCB | `lakatos/programme/explore.py:23` `voi()` · `:16` `ucb_score()` · `:32` `rank_questions()` | 어느 가지를 찌를지(변이 우선순위) |
| 기대 진보이득 (P5) | progress gain | `lakatos/programme/heuristic.py:51` `expected_progress_gain()` | 초과경험내용 예상치(분자) |
| 예측 자체 (P4) | 사전등록 예측 | `lakatos/verdict/judge.py:20` `Prediction` · `:42` `NovelTarget` | 🔵가 던지는 conjecture (🔴가 판정) |
| 발견적 개념 생성 (P5) | P&R | `lakatos/verdict/pnr.py:106` `ProofGeneratedConcept` · `:84` `PositiveHeuristic` | 증명-반박서 새 개념 산출 |
| 예측력 track record (P8) | fertility | `lakatos/quant/fertility.py:18` `predictive_fertility()` · `:26` `nobel_grade()` | novel 예측 적중 이력(변이의 열매) |
| 연구 프레임 (P7) | engine | `lakatos/engine.py:96` `ResearchProject` · `:69` `Realm` | 추측이 사는 sparse 프레임 |

### 3.3 ⊗ 염기쌍 — 두 가닥이 *만나는* 심볼 (rung bond)

| 역할 | 실재 심볼 | 비고 |
|---|---|---|
| 🔴+🔵 단일 판결 결합 | `lakatos/verdict/spine.py:67` `dialectical_verdict()` · `:103` `synthesize_promotion()` | 메트릭+P&R = 한 칸 |
| 판결→다음 추측 전달 | `lakatos/quant/bayes.py:69` `branch_credence()` → `programme/heuristic.py:225` `appraise_and_plan()` | 🔴 출력이 🔵 입력으로 (회전) |
| 학습 보정(상호) | `lakatos/programme/heuristic.py:38` `realized_reward()` (🔴 실측) → `:51` `expected_progress_gain(learned_reward=)` (🔵 보정) | 상호 감시의 코드화 |

> ⚠️ Longinus 깊이 게이트: 위 심볼은 모두 *작동하는* 함수/클래스다(no-op·NotImplementedError 아님). drift 시 `scripts/`의 baseline 감사로 재검증.

---

## 4. 표준 하네스 엔지니어링 용어 매핑

두 가닥을 업계 표준어로 번역하면 — PIDNA는 **generate-and-test 패러다임의 인식론적 일반형**이다.

| 표준 패러다임 | 🔵 푸른 가닥 = | 🔴 붉은 가닥 = | 짝지음(rung) |
|---|---|---|---|
| **Property-based testing** | input **generator** (Hypothesis 등) | **property / oracle** | generate→check |
| **Test harness 일반** | test **driver** / data generator | **test oracle** / assertion | drive→assert |
| **GAN** | Generator G | Discriminator D | adversarial game |
| **Predictor–corrector** | predictor step | corrector step | predict→correct |
| **MCMC (Metropolis–Hastings)** | proposal distribution | acceptance ratio | propose→accept |
| **Runtime verification** | (system under monitoring) model | **monitor** (LTL3) | run→monitor |
| **제어이론** | feedforward **model/plan** | feedback **controller/observer** | plan→feedback |
| **강화학습** | **policy** / exploration | **value/reward** signal | act→reward |
| **CI/CD** | feature **build** | **acceptance gate** | build→gate |
| **통계 가설검정** | alternative hypothesis / estimator | null-test, **α-control** | estimate→test |
| **본 워크스페이스** | 하네스 Design=G · 프로메테우스 · `heuristic.generate_moves` | 나생문(D) · **ooptdd**(영수증) · Longinus · `judge.judge` | `spine.dialectical_verdict` |

### 4.1 독립성의 하네스 표준어

§2.1의 비순환 요구 = 다음 표준 규율들의 *동일한* 원리:
- **the oracle problem** — 오라클이 SUT와 독립이어야 함
- **train/validation/test split · no data leakage** — 검증 독립
- **separation of concerns / least privilege** — 생성·심판 권한 분리
- **adversarial separation** (GAN G≠D) — 대립 목적함수

> 즉, "🔴⊥🔵 독립"은 신비가 아니라 **테스트 오라클 독립성 + 홀드아웃 검증 + 권한 분리**의 인식론적 통합 이름이다. PIDNA는 그 셋이 *같은 것*임을 말한다.

---

## 5. 요약 (hard core 표기)

- **PIDNA = 이중나선**: 🔴검증 가닥 ⊗ 🔵추측 가닥, 둘은 §2의 10개 직교 축에서 **독립**, 매 칸 **[예측↔검증]** 으로 짝지음.
- **독립 = 비순환성의 필요조건**(hard core). 표준어로 = 오라클 독립·홀드아웃·권한분리.
- 이론 기반 = Reichenbach·Popper·Peirce·Campbell·GAN·predictor-corrector·MCMC의 *수렴*.
- 모든 속성은 §3에서 `lakatos/` 실재 심볼에 Longinus 바인딩(환각 아님, line 명시).
- belt: 정확한 축 개수(10)·매핑 세부는 갱신 가능. hard core: **독립 두 가닥 없이는 비순환 검증도, 상승도 없다.**
