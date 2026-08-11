# lakatotree-ts — Repository Contract

TypeScript+함수형 재개발 라카토트리. 기존 Python 엔진(`~/CD/lakatotree`)은 레퍼런스 오라클이며
이 저장소의 수정 대상이 아니다. 효능 지위: **PROPOSED / 무측정** — 이 저장소를 "검증된 방법"으로
인용하지 않는다. 상태 어휘: HYPOTHESIS / PROPOSED / MEASURED / FALSIFIED / ACCEPTED —
산문 동의·import 성공·모델 판정으로 승격 금지, MEASURED는 명령+픽스처+환경+영수증 필요.

## Commands

```
pnpm check    # typecheck + lint + arch  — 수시, 초 단위
pnpm verify   # check + unit + property  — DONE 의 유일한 정의
node src/entrypoints/mcp.ts   # MCP stdio 게이트웨이 (env: LAKATOS_STORE_URL·LAKATOS_API_TOKEN·LAKATOS_TS_*_CAP)
```

커밋 게이트: `pnpm verify && git commit`(exit code 직접 연결) — 커밋 시점 트리가 verify 시점과
같아야 한다 (dirty-tree verify ≠ 커밋 검증, 사고 2건 실측 2026-08-11).

## Definition of Done

1. `pnpm verify` GREEN (로컬과 CI는 같은 명령).
2. 시나리오 단위 작업: "Scenario X를 GREEN으로" — 구현+배선+테스트+게이트가 한 패치.
3. 테스트·타입 규칙·스키마·린트 규칙을 약화시키지 않았다 (완화는 별도 승인).
4. 자연어 보고는 증거가 아니다 — 종료 코드와 테스트 출력이 증거다.
5. 최종 diff 리뷰 후 보고.

## Architecture (의존은 아래로만)

```
src/contracts/     wire 스키마(Zod)·타입. contracts 외 import 금지.
src/domain/        순수 함수만. Effect·Promise·IO·Date·random·throw·zod 런타임 전부 금지.
                   결정 = Decision 값 반환(오류는 값), 상태 전이 = 이벤트 소싱 reduce.
src/application/   유스케이스 오케스트레이션 — gateway(51도구 유계 파이프라인)·assemblers(body 조립 셈 이식).
src/adapters/      storehttp(:55170 프록시) 구현. PG 이벤트 스토어·콘텐츠 주소 증거 스토어 (미구현).
src/entrypoints/   런타임 실행이 허용되는 유일한 곳 (+ tests) — mcp.ts stdio 게이트웨이.
```

- 도메인 시각은 이벤트 데이터로만 들어온다 (ambient clock 금지).
- **회계 이중 평면**: AI 토큰 원장(TokenLedger)과 컴퓨팅 원장(ComputeLedger)은 타입·이벤트·리듀서가
  분리된 별도 평면이다. 한 평면의 이벤트가 다른 평면 상태를 건드리면 결함이다 (property 게이트).
- 판정(verdict)은 결정론 순수 함수다. LLM 점수 금지.

## Coding Rules

- `any` 금지, unchecked cast 금지, non-null assertion 금지.
- 예상 가능한 실패에 throw 금지 — `_tag` 판별합 오류 값 반환. 오류 reason 은 닫힌 어휘.
- 커스텀 DSL 금지 — 같은 패턴 실제 3회 반복 후에만 얇은 공통 함수 추출.
- 돈·토큰·시간은 정수(cents/개/ms). float 금지.
- 한 개념 한 표현 — 같은 값의 중복 표현을 만들지 않는다.

## Workflow

가까운 테스트 읽기 → 의도 서술 → 최소 정합 변경 → 대상 테스트+`pnpm check` → `pnpm verify` →
실행한 명령 보고. 자율 실행은 예산(호출·토큰·wall-time) 선언 후 시작 (CONTRACT §5 B1~B5 상속:
같은 게이트 3연속 같은 이유 RED면 정지, 대기는 폴링이 아니라 스케줄+알림).

## 오라클 경계

Python 엔진과의 동등성(conformance)은 아직 **주장하지 않는다** — v0 도메인은 자체 계약이 정본이고,
오라클 파리티는 어댑터·동결 코퍼스가 생긴 뒤 별도 게이트로 승격한다 (flrh M6 패턴).
