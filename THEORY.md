# 라카토트리 이론 기반 (THEORY)

> prometheus 12-cell 리서치(과학철학/형식 신념수정/실험추적/탐색의사결정)의 합성.
> 정본 출처: Lakatos *MSRP* (1970), Laudan *Progress and its Problems* (1977),
> Bayesian confirmation theory, AGM belief revision (Alchourrón–Gärdenfors–Makinson 1985),
> W3C PROV-O, Multi-armed bandit (UCB1), Value of Information (Howard 1966).
> ※ 12 웹-리서치 셀은 rate-limit 으로 실패 — 본 이론맵은 정본 명명 출처 기반 합성. 웹 재검증은 frontier.

## 1. 엄격도 스택 (3층, 경쟁 아닌 스택)

| 층 | 이론 | 라카토트리 역할 | 모듈 |
|---|---|---|---|
| **포퍼** (최강) | 반증주의 + Lakatos: 진보=사전등록 novel 적중, 퇴행=사후 땜빵 | 이산 판결 엔진 (4판결), 기각 보존 | `judge.py` |
| **베이즈** (중) | Bayesian confirmation: 신뢰도=판결 시퀀스 사후확률, BF=P(E|진보)/P(E|퇴행) | 자산가중 — 강한 가지는 반례 하나로 안 죽음 | `bayes.py` |
| **라우든** (최약·실용) | 문제해결 효과성 = 해결−미해결 문제 | "언제 퇴행이냐" 명문 폐기 3규칙 | `laudan.py` |

## 2. 보강 4층 (서버 강화 — "너무 얇다" 해소)

| 층 | 이론 | 역할 | 모듈 |
|---|---|---|---|
| 신념개정 | AGM (contraction/revision, epistemic entrenchment) | hard_core 개정 형식화, CANONICAL demote=revision | (P1) |
| 출처추적 | W3C PROV-O (Entity/Activity/Agent) | "LLM 점수 금지·스크립트 채점"을 검증가능 계보로 | `prov.py` |
| 탐색배분 | bandit UCB1 + VoI (Howard 1966) | frontier 질문 우선순위 = 신뢰도+미탐색보너스, 기대진보/비용 | `explore.py` |
| 메타-종료 | Lakatos 프로그램 소멸 + regret | 수확/발산/소멸 3-상태 판정 | (P1) |

## 3. 정량 지표 (계산식)

- 진보율 = 100×(m_root−m_canonical)/m_root (동일 scope 정본경로)
- 가지 신뢰도 = odds/(1+odds), odds = prior/(1−prior)×Π BF; BF=exp(ln(base)×w), w=max(min(|Δ|/noise,4)/4, 0.3)
- 문제수지 = closed−opened / PSR = closed/path_nodes
- 퇴행깊이 = 가지 연속 NONPROGRESSIVE 최대 (≥3 경보) / 기각률 = rejected/all (건강 0.2~0.5)
- **VoI(q) ≈ E[Δ진보|q closed] × 1/cost(q)** / **UCB(q) = credence(q) + c·√(ln N/n_q)**
- Bayes 폐기 = credence<0.1 (라우든 이산 3규칙과 OR)

## 4. 이론적 gaps (정직 — 미해결/논쟁)

1. **novel 채점 미해결**: progressive 가 텍스트 존재만으로 partial 차등 → 구조적 corroboration 구현 필요 (본 버전 착수)
2. prior 주관성: BF_BASE={6,1.5,0.3} 보정 근거 없음 — Bayesian "problem of the priors"
3. **층간 통약불가**: 포퍼=rejected/베이즈=생존/라우든=양호 충돌 시 메타규칙 부재. 현재 OR=가장 관대한 층 지배 (Feyerabend 다원주의 미해결)
4. 라우든 규칙③ dead: problem_balance_windowed 항상 0 (per-branch 질문귀속 미배선)
5. AGM entrenchment 순서 유일해 없음 (credence? 문제수지? 연결도?)
6. bandit reward 순환: reward=progressive 적중이 novel 채점(gap1)에 의존 → 채점 신뢰성 선결
7. 단일 트리 한계: 진정한 패러다임 전환(Kuhn) 정량모델 부재
8. 통계 표본 미반영: 점추정 비교만, 다중비교 보정 없음 (false-progressive 율)

## 5. 우선순위 (이 버전 = v4 구현 대상)

P0: 구조적 corroboration(gap1) + PROV-O 계보 + 스크립트 sha256 무결성
P1: VoI/UCB directions + AGM hardcore 개정 + lifecycle 종료판정
P2: 경쟁 가지 리더보드 + 인증층
