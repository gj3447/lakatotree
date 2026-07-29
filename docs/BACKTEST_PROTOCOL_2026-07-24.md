# BACKTEST PROTOCOL — LakatoTree 진보판정기 효능 백테스트

> 상태: **IMPLEMENTED / UNTESTED** (측정 전).
> 2026-07-29 통계 감사에서 기존 초안의 표본수·비열등성·specificity·Cohen's d 결함을 측정 전에 교정했다.
> confirmatory corpus, 외부 시간 앵커, 측정 결과는 아직 없다. 기존 C3·dogfood는 development-only다.

## 0. 주장 범위

같은 봉인 사례에서 LakatoTree의 **진보 판정 커널**이 두 내부 기준선보다 외부 지상진리를 더 정확히
분류하는지 검정한다. 1차 표본은 progressive/nonprogressive가 같은 수인 외부 sealed holdout이다.

- `naive`: 주 지표 개선만 보면 진보
- `popper_like`: 측정 전 등록된 주 지표 개선만 보면 진보
- `lakatotree`: 실제 `lakatos.verdict.judge.judge()`가 측정 전 등록, 주 지표 개선, 독립 novel
  corroboration을 모두 요구

이 백테스트가 성공해도 다음은 증명하지 않는다.

- 연구 생산성이나 발견률 향상
- 미래 연구에서의 인과효과
- branch-level Popper/Bayes/Laudan stack 또는 eureka 전체의 효능
- HSWM 효능

stack과 eureka는 개별 사례를 한 번에 분류하는 단일 production composer가 없고, 프로그램 역사·문제수지 등
추가 입력을 요구한다. 임의의 기본값으로 합성하면 새 실험 장치를 발명하는 것이므로 1차 arm에서 제외한다.

## 1. 사전등록 가설

- **H1 (conjunctive accuracy superiority)**:
  `error_lakatotree < error_naive` **AND** `error_lakatotree < error_popper_like`.
- 각 비교는 같은 외부 holdout 사례의 paired correctness로 검정한다. nonprogressive에서 LakatoTree만
  맞히면 favorable, progressive에서 기준선만 맞히면 reverse discordance다.
- 두 비교 중 하나라도 실패하면 H1은 지지되지 않는다. 유리한 비교만 골라 보고하지 않는다.
- FPR만 1차 검정하지 않는다. 세 규칙은 `lakatotree ⊆ popper_like ⊆ naive` 포함관계라
  nonprogressive 사례에서 reverse FPR discordance가 구조상 불가능해 우위가 장치에 내장되기 때문이다.
- null·음성·검정력 부족 결과도 같은 result contract로 출판한다.

## 2. 세 장치와 입력 격리

| 장치 | 판정 | 구현 권위 |
|---|---|---|
| `naive` | noise band를 넘는 주 지표 개선 | 실제 `judge()`의 primary-improvement 계산 |
| `popper_like` | 측정 전 등록 + 주 지표 개선 | 내부 단층 기준선. 외부 POPPER 제품 효능 주장 아님 |
| `lakatotree` | 측정 전 등록 + 주 지표 개선 + 독립 novel corroboration | 실제 `judge(..., require_independent_source=True)` |

모든 장치는 동일한 `device_input`만 받는다. 다음 필드는 adapter 입력에서 구조적으로 제거한다.

- `ground_truth`
- `ground_truth_evidence`
- `adjudicator_ids`
- `source_class`

`case_package_sha256`은 development에서는 canonical inline 입력도 허용하지만 confirmatory에서는 반드시
manifest 내부 상대경로의 strict JSON package bytes를 봉인하고 그 내용이 실제 `device_input`과 같아야 한다.

## 3. 코퍼스와 노출 규칙

### 3.1 confirmatory에서 금지

- 기존 `examples/c3_effectiveness_corpus.py` 12건
- 프로젝트 dogfood와 문서에 이름·정답이 노출된 사례
- 개발 중 adapter 또는 threshold 수정에 사용한 사례
- 결과를 본 뒤 고른 사례

이들은 construct-validity/development 자료로만 남긴다.

### 3.2 confirmatory 구성

- 외부 사례: progressive/nonprogressive **동수**, 장치 출력과 arm을 보지 않은 독립 판정자 2인 이상이
  1차 출처로 ground truth 동결. 이 층만 1차 superiority 표본이다.
- sealed synthetic sabotage: 전체의 **25% 이상**, 전부 ground-truth nonprogressive. 제작 정의·난이도·
  오염 유형을 결과 전에 봉인하고 별도 stress stratum으로 보고한다. 1차 효과량에는 섞지 않는다.
- 각 사례는 고유 `sampling_unit_id`, `component_id`, `source_entity_ids`, package SHA, measurement/novel
  source SHA를 가진다. 외부 1차 표본에서는 이 값들이 종류를 가로질러 pairwise nonoverlap이어야 하며
  pilot과도 source/component가 겹치면 안 된다.
- 외부 N은 §6의 두 superiority + sensitivity 3중 exact joint-power plan을 실제 제안 N에서 직접 통과해야 한다.

사례 ID는 유일해야 하고 duplicate JSON key, NaN, Infinity는 로더가 거부한다. confirmatory 외부 package
경로는 manifest 디렉터리 안의 상대경로만 허용한다. ID만 바꾼 복제 사례는 pseudoreplication으로 거부한다.

## 4. 지표

### 4.1 1차 — 외부 holdout paired error

- 장치별 `error = incorrect / external_holdout`과 accuracy를 보고한다. 외부 holdout은 class-balanced이다.
- 비교 효과는 `error_lakatotree - error_control`이다. **음수면 LakatoTree 우위**다.
- paired risk difference의 Bonferroni-adjusted 97.5% 구간은 Newcombe (1998) paired method 10으로 계산한다.
- discordant pair 수와 exact McNemar p-value를 항상 함께 보고한다.
- matched odds ratio는 `LakatoTree-only correct / control-only correct` 방향과 exact conditional CI로 보고한다.

### 4.2 오류 형태와 sabotage stress

- 외부 holdout의 FPR과 sensitivity/TPR을 장치별 Wilson 구간과 함께 보고한다.
- synthetic sabotage는 별도 FPR stress 결과로만 보고하며 H1 분모에 넣지 않는다.

### 4.3 보수성 방지 gate

구초안에서 “specificity”라고 부른 값은 실제로 **true-progressive sensitivity/TPR**였다. 명칭을 교정한다.

- `sensitivity_lakatotree = correctly_progressive / ground_truth_progressive`
- Wilson 95% lower bound가 사전등록 `min_sensitivity_wilson_lb` 이상이어야 한다.
- 미달이면 “탐지력 있는 보수성”이 아니라 `NOT_SUPPORTED`다.

paired binary 결과에 Cohen's d를 적용하지 않는다.

## 5. 블라인딩

ground-truth 판정자는 장치 실행 전에 사례를 판정하고, 장치 라벨·출력을 보지 않는다.
`device_outputs_seen=false`, curator DID, rubric SHA, raw-label SHA, consensus rule, 최종 ground-truth assignment
SHA를 machine-readable attestation에 봉인하고 모든 curator가 Ed25519 서명한다. 같은 curator들은
holdout prior-exposure attestation과 사례별 prediction-before-measurement ordering attestation도 서명한다.
장치는 자동 함수이므로
사후 인간이 장치 출력을 다시 라벨링하지 않는다. 분석기는 ground truth를 사용하지만 adapter 함수에는 전달하지
않는다. 이 구조는 arm-guess 설문보다 직접적인 label-leakage 차단이다.

## 6. 통계·검정력 계획

- familywise alpha: `0.05`
- 두 superiority 비교: Bonferroni `pairwise_alpha = 0.025`
- exact two-sided McNemar, 방향은 LakatoTree 우위여야 함
- accuracy-discordant pair에서 LakatoTree-only correct일 조건부 확률 사전 가정: `0.80`
- 전체 3중 결합 목표 power: `0.80`
- 필수 gate 3개(naive 비교, popper_like 비교, sensitivity)의 의존성을 가정하지 않는 union-bound 설계:
  각 component power `≥ 1-(1-.8)/3 = 14/15 ≈ .933333`
- accuracy component는 `D ~ Binomial(N_external, r_floor)`로 discordant 수를 혼합한 exact power를 계산한다.
  `ceil(required_discordant/r)` 근사는 금지한다.
- `r_floor`는 development pilot 두 contrast의 observed rate가 아니라 각 Wilson 95% lower bound 중 최솟값이며,
  contrast의 `total_pairs`는 `total_pilot_cases`와 같아야 한다. 모든 pilot case의 고유 sampling unit,
  component, nonempty source 목록을 machine receipt로 재계산하고 confirmatory holdout과 비중복을 검사한다.
- sensitivity component는 true-sensitivity alternative `0.90`에서 Wilson lower `≥0.70` 통과 확률을 exact 계산한다.
- 관측 discordant gate도 component target을 쓴다: 최소 **34쌍**
  (`34 → .9379729218`, `33 → .8932131493`). 단순 유의성 최저 7:0은 power 설계가 아니다.
- 제안된 실제 class-balanced N에서 세 component와 union-bound joint lower bound를 모두 재계산해 통과해야 한다.

## 7. 판정 상태

- `SUPPORTED`: 외부 holdout 두 accuracy 비교 모두 방향·exact p·discordant-power gate 통과 + sensitivity gate 통과
- `NOT_SUPPORTED`: sensitivity 미달, 우위 방향 실패, 또는 충분한 정보에서 superiority 불성립
- `INCONCLUSIVE_UNDERPOWERED`: 방향은 유리하나 discordant pair가 사전 power 수에 미달
- `INVALID`: schema, label isolation, source SHA, sample plan 등 구조 위반
- `INVALID_TEMPORAL_ANCHOR`: 2-of-N 외부 witness 서명·target SHA·exact readback 중 하나라도 불일치
- `INVALID_MEASUREMENT_LOCK`: 코드·protocol·환경·case package 중 하나라도 lock 이후 변경

`NOT_SUPPORTED`와 `INCONCLUSIVE_UNDERPOWERED`를 합치지 않는다.

## 8. 측정 순서

1. **Development only**: adapter·분석기·power calculator를 기존 노출 자료로 검증한다.
2. **Corpus curation**: 독립 판정자가 sealed holdout을 만들고 manifest를 동결한다.
3. **Code/environment freeze**: manifest, protocol, schema, `judge.py`, `grounding.py`, `backtest.py`,
   `measurement_lock.py`, `temporal.py`, `write_cert.py`, `envfp.py`, CLI, case/provenance package와 코드가 직접 계산한 환경
   fingerprint를 portable logical-path `MeasurementLock`에 묶는다. 빈/축소 dep set은 거부한다.
4. **Temporal anchor**: premeasurement lock SHA(그 안에 raw manifest SHA 포함)를 producer·curator와
   역할이 분리된 Ed25519 witness allow-list의 **2-of-N 이상**이 서명하고 exact readback sidecar를 기록한다.
5. **One-shot run**: runner가 lock, allow-list SHA, 서명 정족수, exact readback을 검증한 뒤 실행한다.
6. **Producer receipt**: result SHA를 같은 input `lock_key`에 추가하되
   `producer_generated / replay_status=pending / claim_eligible=false`로만 발행한다. INVALID 결과에는
   receipt를 발행하지 않는다. 이 단계의 `SUPPORTED`는 분석 상태일 뿐 과학 주장 승격이 아니다.
7. **Independent replay**: producer·curator·witness와 다른 사전등록 replayer DID가
   `lock_key + result SHA + result status + replay environment SHA + 양 actor DID`를 Ed25519 서명하고,
   byte-identical 재생까지 통과한 뒤에만 `externally_signed_replay / verified`로 승격한다.
   `SUPPORTED`만 `claim_eligible=true`; 음성·검정력 부족 결과는 `publication_eligible=true`이지만
   양성 효능 주장은 불가하다.

run-time에 새로 만든 lock만으로는 사전등록 시점을 증명하지 못한다. 현재 `gen_time`은 외부 TSA나
transparency log의 암호학적 시각 증명이 아니라 독립 witness가 서명한 **시각 진술**이다. 따라서 witness의
정직성·비담합과 out-of-band 기록 보존을 가정하며, 강한 존재-이전 증명에는 RFC 3161 TSA·OpenTimestamps·
append-only transparency log 같은 별도 권위가 필요하다. 이것도 사적 선행 실행으로 결과를 몰랐다는 사실까지
증명하지는 않는다. blind holdout·독립 corpus custody가 남은 사회적 신뢰 경계다. DID 서명은 서로 다른 키
제어를 증명하지만 서로 다른 인간·조직이 실제로 키를 보유한다는 사실까지 증명하지는 않으므로
witness/replayer/corpus custody의 실세계 독립성은 여전히 사회적 신뢰 경계다. 고유한
`sampling_unit_id`/`component_id`/`source_entity_ids` 문자열도 실제 연구 단위의 독립성을 스스로 증명하지
않으므로 외부 corpus audit가 필요하다.
정족수 sidecar가 없거나 위조되면 confirmatory 실행은 fail-close한다.

## 9. 구현·재현 명령

```bash
# 실제 제안 N의 3-gate joint power contract (floor는 pilot receipt에서 복사)
.venv/bin/python -m lakatos.backtest_cli joint-power \
  --external-cases <even-N> --discordance-rate-floor <pilot-wilson-floor>

# manifest 구조 + pre-lock 참조 artifact 의미/해시/서명 검증
.venv/bin/python -m lakatos.backtest_cli validate <manifest.json>

# 측정 전 input lock 생성 (코드가 환경 fingerprint를 직접 계산)
.venv/bin/python -m lakatos.backtest_cli lock <manifest.json> \
  --output <premeasurement-lock.json>

# exact readback 뒤 한 번만 실행
.venv/bin/python -m lakatos.backtest_cli run <manifest.json> \
  --lock <premeasurement-lock.json> \
  --output <result.json> --receipt-output <producer-receipt.json>

# 별도 actor/checkout에서 독립 replay
.venv/bin/python -m lakatos.backtest_cli replay <manifest.json> \
  --lock <premeasurement-lock.json> --producer-result <result.json> \
  --producer-receipt <producer-receipt.json> --replayer-did <did:key:...> \
  --replay-signature <ed25519-hex> --receipt-output <verified-receipt.json>
```

confirmatory의 권위 실행면은 lock에 포함된 `lakatos.backtest_cli` 모듈이며, 저장소 `scripts/` wrapper는
개발 편의용이다. 설치된 wheel에서는 같은 명령을 `lakatotree-backtest` entrypoint로 실행한다.
manifest/anchor schema와
machine protocol은 `lakatos/resources/` package data에 포함되며 lock은 checkout 절대경로가 아닌 논리 경로를 쓴다.
`validate` 시점에는 아직 생성되지 않은 temporal-anchor receipt를 검사하지 않는다. witness 서명·정족수·
exact readback 검증은 anchor 생성 뒤 `run --lock`에서만 수행된다.

## 10. confirmatory 동결 기록

아래는 독립 corpus가 준비되기 전까지 비워 둔다. 미기록 상태에서 측정 금지.

- corpus manifest raw SHA-256: **미기록**
- ground-truth 판정자/합의 시각 + curator-signed blind attestation: **미기록**
- curator-signed holdout prior-exposure attestation: **미기록**
- contrast별 pilot count/Wilson discordance floor와 case-level source/component nonoverlap receipt: **미기록**
- code commit + protocol/judge/analyzer SHA: **미기록**
- environment SHA: **미기록**
- premeasurement MeasurementLock SHA/key: **미기록**
- case별 prediction/measurement/curator-signed order receipt + 외부 witness exact readback: **미기록**
- producer/curator/replayer DID allow-list와 separation attestation: **미기록**

따라서 현재 과학 상태는 효능 양성도 음성도 아닌 **UNTESTED**다.
