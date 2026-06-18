# LakatoTree as an OS — the visual human-in-the-loop (roadmap / vision)

> Status: **vision, not built.** Captured so it does not evaporate (군단장의 "합류를 기록한다" 정신).
> 현재 상태 = 이미지를 프로젝트 폴더에 떨구고 IDE 파일브라우저로 본다 (crude). 아래는 *나중에* 필요한 방향.

---

## 1. 라카토트리 = 운영체제(OS), 입출력 = LLM 챗봇

라카토트리는 단순한 verdict 서버가 아니라 **연구 프로그램을 운영하는 OS**로 향한다.

- **커널** = verdict 엔진(judge/pnr/spine/promote) + 트리 상태(Neo4j/PG/Mongo).
- **셸(I/O)** = **LLM 기반 챗봇**. 사람이 자연어로 말하면, 챗봇이 그 의도를 *OS 콜*(트리 조작·조회·시각화)로 번역해 커널을 구동한다. = `mcp_server.py`/`cli.py` 가 이미 그 syscall 표면의 씨앗.
- **디스플레이** = **스트리밍 웹 화면**. 챗봇 옆에서 라카토트리 UI 가 실시간으로 트리를 그린다.

> 입력: 사람 말 → 챗봇 → OS 콜. 출력: 트리 상태 → 시각화 → 스트리밍 화면. 챗봇은 사람과 OS 사이의 양방향 통역.

## 2. 트리를 왔다갔다하는 GUI

지금처럼 "이미지 파일을 폴더에서 찾아보는" 방식이 아니라, **트리를 항해하는 GUI**:

- 노드(가지)를 따라 줌인/줌아웃, 분기·합류·가지치기를 한눈에.
- 노드 클릭 → 그 노드의 prediction/measurement/verdict/standing/계보(prov)·반례(pnr)를 패널로.
- 프론티어(살아있는 최전선)·퇴행 가지(잘린 물길)·정본 경로(본류)를 색으로 구분 (왜 나무인가 §군단장).
- shift_candidate·supersession 제안, standing 철회 같은 *안건*을 알림으로 surface (이번에 배선한 `proposal`/`standing_retraction` 이 그 데이터 소스).

## 3. 왜 시각화인가 — 사람은 시각 동물이다

**핵심 동기(consumer_b 실증)**: 수치적으로는 막 좋아 보여도, **시각화했을 때 개판인 경우가 있었다.**
숫자 게이트가 GREEN 이어도 사람 눈이 보면 명백히 틀린 것 — 이게 검증의 빈 구멍.

→ 사람의 검증은 본질적으로 **시각적**이다. verdict 가 영수증이라면, **시각화는 사람이 읽을 수 있는 형태의 영수증**이다. 라카토트리의 human-oracle 경계(409 / `requires_human_verdict` / argue standing)는 *이 시각 화면 위에서* 사람이 행사해야 제값을 한다. GUI 없이는 human 검증이 "폴더 뒤지기"로 퇴화한다.

→ 동시에 화면은 **피드백·방향 채널**이다: 사람이 보고 "이렇게 해봐" 를 챗봇에 말하면 = 양의 휴리스틱(다음 실험) 입력. 검증과 피드백이 같은 화면에서 돈다.

## 4. 사람도 꿈꾼다 — 푸른 가닥은 agent 만이 아니다

PIDNA 의 🔵 추측 가닥(꿈·예측·추상)은 **agent 전용이 아니다**. **사람도 푸른 가닥**이다 —
대담한 추측을 던지고, 시각 화면에서 직관으로 패턴을 보고, 다음 노선을 상상한다. 챗봇 UI 는
사람의 그 꿈을 트리의 OS 콜로 흘려보내는 통로다. (붉은 가닥엔 judge/test, 푸른 가닥엔 agent+**사람**.)

## 5. ★정정 — agent 도 검증한다 (붉음/푸름은 칼로 무 자르듯 나뉘지 않는다)

사용자 정정(2026-06-18): *"agent 가 검증을 아예 못하는 건 아니다. 너무 칼로 무 자르듯 딱 나누면 agent 역할이 너무 축소된다."* — 정당. PIDNA 의 "어느 가닥도 자기 자신은 검증 못 한다" 는 **이상화(idealization)**지 절대명제가 아니다.

정확한 진술:
- agent 는 **붉은 가닥의 도구를 실제로 돌린다** — judge/pytest/grep/sha/적대 sub-agent 리뷰. 즉 agent 는 검증을 *한다*. (이 세션 내내 그렇게 했다.)
- 금지되는 건 좁다: **자기 주장을 외부 영수증 없이 자기 채점으로 *최종 확정*하는 것.** 능력의 부재가 아니라 *최종 권위*의 문제.
- 따라서 agent 는 두 가닥에 **걸쳐 있다**. red⊗blue 분리는 "agent=무능한 푸름"이 아니라 "최종 수용엔 못-속이는 외부 영수증이 필요"라는 *receipt 규율*이다. 분리를 과하게 새기면 agent 의 실제 검증 기여(테스트·재현·적대검증)를 지운다.

> 결론: 분리는 **권위와 영수증**의 분리지, **능력과 사람/agent** 의 분리가 아니다. agent 는 검증을 돕고, 사람은 시각으로 최종 판단하며, 둘 다 꿈꾼다. UI/OS 는 이 셋(붉은 도구·푸른 꿈·시각 권위)이 한 화면에서 돌게 한다.

---

## 6. 이미 깔린 씨앗 (나중에 이어붙일 지점)

- syscall 표면: `mcp_server.py`(MCP 도구) · `cli.py` · `server/app.py`(REST). 챗봇은 이 위에 앉는다.
- 시각화할 데이터: `/api/tree/{name}/metrics`·`/directions`·`/heuristic`·`/paradigm`(+`proposal`)·`standing`·certificate, prov 계보, leaderboard.
- human-oracle 경계: 409 승격 게이트 · `requires_human_verdict` · argue standing · `supersession proposal`(이번 배선). GUI 가 이 안건들을 사람에게 띄우고 결정을 받는다.
- 현 dump-to-folder 이미지: `consumer_b/images/...` 식 → 나중에 스트리밍 캔버스로 대체.

> 이 문서는 belt(폐기 가능). hard core 는 변함없다: **나아감은 영수증으로만 참.** UI/OS 는 그 영수증을 *사람이 시각으로 읽고 행사*하게 만드는 표면일 뿐 — verdict 권위를 LLM 에게 넘기지 않는다.
