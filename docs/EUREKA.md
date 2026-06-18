# EUREKA — 붉음과 푸름으로 만들어진다 (단, 순진한 "동시 결합"은 반증됨)

> 사용자 명제(2026-06-18): *"유레카는 붉음과 푸름으로 만들어진 것이다."*
> 이 문서는 그 명제를 prom 12축 × 적대검증(8/12 생존)으로 접지하고, **반증된 부분을 정직하게 도려낸 뒤** 살아남은 형태를 코드(`lakatos/eureka.py`)에 박는다.
> 상위: [`PIDNA.md`](PIDNA.md) · [`PIDNA_STRANDS.md`](PIDNA_STRANDS.md)

---

## 0. 한 줄

**유레카는 붉음과 푸름으로 만들어진다 — 단, 대칭적 *동시 결합*이 아니라 비대칭 *2단*이다.**
🔵 푸름이 *아하*(통찰+내재 확신)를 통째로 만들고, 🔴 붉음(외부 검증)이 그것을 *진짜*로 인증한다. **붉음 없는 아하 = 환각.**

---

## 1. prom이 죽인 것 — 순진한 명제 (REFUTED)

처음 명제: *"EUREKA = red ⊗ blue, 두 가닥이 동시·대칭으로 맞물리는 순간."* — **틀렸다.** 과학이 반증:

- **느낌은 거의 푸름이다.** 아하는 무의식적 재구조화(Ohlsson 표상변화, Knoblich 제약완화)가 의식 문턱을 넘는 *섬광*이다. 신경: 우반구 전측두회 감마버스트 ~300ms 선행(Kounios & Beeman). 이 섬광은 **자기충족적** — 자체 "적합감(feeling of rightness)"을 처리유창성으로 생성한다.
- **그 적합감은 거짓말한다.** 객관적으로 *틀린* 해의 **37%가 진짜와 똑같은 아하**(suddenness·pleasure·certainty)를 낸다(Danek & Wiley 2017). 아하-확신과 정답률 상관 ~63–70%뿐. Laukkonen "dark side": *거짓 명제*에 완전한 아하 현상학이 0 검증으로 붙는다.
- **진짜 검증(외부 붉음)은 하류다.** Reichenbach의 발견↔정당화 분리는 *외부* 수준에서 성립. Wallas: illumination(3단계) → verification(4단계). Poincaré: *"확실성과 함께 떠올랐고, 검증은 나중에 여유롭게 했다."*
- **Bayesian-surprise = 아하 가설도 반증**(cell H): 통찰은 KL/믿음갱신이 아니라 *표상 재구조화*. prediction-error=aha 직접 증거 0.

→ 그러므로 **대칭 ⊗ 결합은 신화.** felt aha는 푸름 안에서 *완결*된다.

---

## 2. prom이 살린 것 — 정제된 진짜 (SURVIVED 8/12)

명제를 죽이지 않고 **더 날카롭게** 다시 세운다:

### 2.1 유레카는 2종이다

| | 구성 | 신뢰성 |
|---|---|---|
| **felt eureka** (주관적 아하) | 🔵 재구조화 섬광 + 내재 red_felt(적합감) | ❌ 신뢰불가 — 37% 거짓통찰이 똑같이 발화 |
| **true eureka** | felt eureka **∧ 외부 🔴 검증 통과** | ✅ 영수증으로 인증된 것만 |
| **hallucinated eureka** | felt **∧ ¬외부검증** = 확신하지만 틀림 | = LLM 환각의 인지적 원형 |

> **felt eureka ≠ true eureka.** 내재 red_felt는 *저충실 대용품*(reward affect)이지 세계-검증이 아니다. **외부 붉음이 felt를 true로 *바꾸는* 유일한 것** — 아르키메데스를 자신만만한 사기꾼과 가르는 단 하나.

### 2.2 그래서 — 이것은 PIDNA의 *입증*이지 반증이 아니다

푸른 가닥(꿈)은 통찰 *그리고* 그 통찰에 대한 *유혹적 확신*을 함께 만든다 — 그리고 **그 확신이 환각 벡터다.** 37% 거짓통찰률 = 순수 푸름의 환각률. **붉은 가닥(외부 검증)은 유레카의 장식이 아니라, felt를 true로 바꾸는 유일한 변환** — [TOUCH_THE_SKY §어둠의 거울]·ooptdd(`ship()` 리턴 ≠ 도착)와 정확히 같은 명제. **영수증 없는 아하 = 환각.**

### 2.3 대칭 결합이 *진짜* 성립하는 예외 (정직)

붉음이 **인과적으로 독립인 선택자**로서 푸름과 *불일치*할 때만 대칭이 산다(cell J):
- **AlphaGo move 37**: policy(🔵, 1/10000) vs value+MCTS(🔴, 승리) — 유레카 = 그 *간극*을 붉음 편으로 해소.
- **실험 발견**(Faraday 1831·Newton 프리즘, cell E): 관측(🔴)과 가설(🔵)이 *동시 lock*.
대비: **수학적 통찰**(Poincaré·Kekulé·Ramanujan)은 푸름 단독 → 붉음 수십 년 하류. **동시 lock은 특수, 푸름→붉음 순차가 일반.**

---

## 3. operationalization — "어떻게 할지"

가장 강한 측정형(cell I, Schmidhuber MDL): **통찰 = held-out 검증을 견디는 압축 점프.** *주관적 확신이 아니라*(그건 reward affect — 거짓통찰이 증명) `compression_gain × verification_rate`.

lakatotree 구현 (`lakatos/eureka.py`):

```
felt        = novel_registered                          # 🔵 섬광 (아하-prone, 불신)
true        = felt ∧ novel_confirmed                    # 🔴 외부 확증
              ∧ bayes_factor > 3.162 (Jeffreys substantial)
              ∧ problem_balance(closed,opened) > 0       # 한 번에 >1 문제 닫음(압축)
              ∧ promotion_gate(verdict, stands, repro).ok # fail-closed
hallucinated = felt ∧ ¬true                              # 거짓 아하 (인간 37%)
eureka_rate  = true / felt = 1 − hallucination_rate      # fertility.predictive_fertility 보다 엄격
```

> ★ **정직 라벨(cell K 적대검증 반영)**: 이건 **하류 파이프라인 detector(discovery→justification)** 지 *대칭 ⊗ 결합이 아니다.* 엔진 게이트는 decoupled·ordered이고 🔴는 *비대칭 필터* — veto는 하되 content를 originate하지 않는다. `eureka.py` docstring에 명시. `red⊗blue/bond/PIDNA` 어휘는 코드에 0회(문학적 overlay) — 코드가 *하는* 일은 "felt 중 외부검증 통과분만 true로 센다".

8 test green (`tests/test_eureka.py`): true / felt-but-unconfirmed=hallucinated / 미등록=¬felt / 한계증거·음의 problem_balance·promotion veto·rejected 모두 차단 / eureka_rate.

> ⚠️ **정직한 현 상태(orphan)**: `eureka.py`는 *테스트된 개념 데모*다 — 엔진/CLI/MCP/`__init__` export 어디에도 미배선(테스트 밖 호출 0). live 파이프라인에 쓰려면 ① `lakatos/__init__` export ② server `submit_test_result` 후 노드별 `classify` 호출 + `eureka_event` emit ③ `/eureka` route. 이 자체가 PIDNA 정직: *배선 안 했는데 "탑재됐다"고 하면 그게 환각.* (cf. 엔진 production import 0 비판 — 같은 결).
>
> ★ **fertility와의 관계 정정**: `eureka_rate.true_rate ≤ predictive_fertility` — eureka는 `novel_confirmed` 위에 BF>3.162·problem_balance>0·promotion 게이트를 *더* 요구(엄격한 superset). "거울"이 아니라 **fertility를 더 조인 것**.

---

## 4. Longinus 바인딩 (실재 심볼, line)

| 역할 | 심볼 |
|---|---|
| 🔵 섬광 (novel 등록·track record) | `lakatos/verdict/judge.py:20` `Prediction` · `quant/fertility.py:18` `predictive_fertility`(confirmed/registered=true-eureka율) · `:26` `nobel_grade`(Wilson LB≥0.7=환각률 바닥) |
| 🔴 외부검증 게이트 | `lakatos/quant/bayes.py:57` `bayes_factor`(BF>3.162) · `quant/laudan.py:19` `problem_balance` · `verdict/promote.py:19` `promotion_gate`(fail-closed) |
| detector (합성) | `lakatos/eureka.py` `classify` · `eureka_rate` (위 심볼 AND-합성, no-op 아님, 8 test) |

---

## 5. 요약

- 유레카는 붉음과 푸름으로 만들어진다 — **푸름이 만들고, 붉음이 인증한다**(2단·비대칭, 대칭 동시결합 아님 = REFUTED).
- **felt eureka ≠ true eureka.** 영수증 없는 아하 = 환각(37% 거짓통찰 = 순수 푸름 환각률).
- **붉은 가닥 = felt를 true로 바꾸는 유일한 변환** → PIDNA·ooptdd의 입증.
- belt: 정확한 임계·예외목록 갱신 가능. hard core: **검증되지 않은 통찰은 통찰이 아니라 느낌이다.**

> prom 출처: cycle `eureka-red-blue` (12축, 8/12 survive). 핵심 반증 G(Geneplore 순차)·H(Bayesian-surprise)·K(엔진=파이프라인). 핵심 정제: A(blue⊗red_intrinsic)·I(MDL held-out)·L(false-aha→external red certifies). Reichenbach·Popper·Peirce·Campbell·Danek&Wiley·Laukkonen·Kounios&Beeman·Schmidhuber·Lenat EURISKO·AlphaGo move37.
