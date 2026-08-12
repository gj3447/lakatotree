# lakatotree — 에이전트 작업 규율

현재 재개발 레인은 `ts/`이고 현행 인덱스·로드맵은 `MAP.md` 하나다. `lakatos/`, `server/`, 루트
`tests/`의 Python 구현은 배포된 구현이자 비교 오라클로 보존한다. TS-only 변경은 `pnpm verify`,
Python 변경은 해당 Python 게이트, 언어 간 wire/spec 변경은 양쪽 게이트를 실행한다.

이 repo 는 SYMPOSIUM canonical `main`의 **단일 writer**가 순차적으로 변경한다.
기본 개발 스택은 2층: **ooptdd/LTDD(측정) × judge(진보 판정)** — 아래는 그 채택 규율.

## 1. 단일 writer 규율 (OMD RETIRED — 2026-07-26 사용자 승인)

1. OMD MCP, lease, heartbeat, coordination DB 쓰기와 자동 linked worktree/session branch는 금지한다.
   과거 OMD 코드·DB·테스트는 읽기 전용 연구 자료다.
2. root/parent 세션 하나만 canonical checkout의 writer token을 보유한다. 다른 세션과 subagent는
   read-only이며, writer가 끝나기 전 별도 쓰기 레인으로 분산하지 않는다.
3. **커밋은 반드시 pathspec**: `git add <내파일들> && git commit -- <내파일들>`.
   맨 `git commit` 은 남이 스테이징한 파일까지 인덱스 전체를 쓸어담는다(사고 전례 0691263).
4. 알려진 RED를 ignore/deselection/skip/xfail/path scoping/allow-failure로 숨겨 DONE을 만들지 않는다.
   다른 in-flight 변경이 적용 게이트를 깨면 완료를 선언하지 말고, 정확한 후보 커밋의 clean 격리 checkout에서
   적용되는 전체 게이트를 제외 없이 실행한다.
5. 파일을 바꾸는 작업은 소유한 diff를 scoped commit으로 닫기 전에는 완료가 아니다. 커밋하면 곧바로
   push하고 remote readback으로 같은 SHA를 확인한다.

## 2. 방법론 (행동 RED-first + 증거 비례)

- 의미 결함은 가장 작은 행동·fault fixture로 RED를 먼저 확인한 뒤 고친다. 별도 mechanism guard는
  실제 false-green을 추가로 구분할 때만 둔다. 소스 문자열·주석·내부 함수 위치를 제품 동작의 대리물로 검사하지 않는다.
- 해시는 릴리스·외부 영수증·동결 역사 증거처럼 저장소 밖으로 나가는 경계에만 쓴다. 내부 코드·문서·테스트
  사이의 결속은 실행 계약이나 의미 불변식으로 검증한다.
- 파생물은 재생성 명령과 단일 정본이 있을 때만 둔다. 손으로 맞춰야 하는 schema/manifest/golden/receipt 복제는
  만들지 않는다. 기존 `ooptdd_receipts/`는 레거시 회귀 corpus로 동결하며 새 변경의 기본 산출물이 아니다.
- blocking guard에는 보호하는 실제 실패, owner, retirement 조건이 있어야 한다. 새 guard를 넣을 때 겹치는
  source/hash/string guard를 하나 제거하거나, 제거할 것이 없다는 근거를 남긴다.
- 진보 주장은 `examples/*_programme.py` 하네스의 **judge() 채점으로만** (손입력 verdict 금지, no fake green).

## 3. 경로별 검증 게이트 (커밋 전)

```bash
pnpm verify                                      # TS 변경의 유일한 DONE 게이트

# 아래는 레거시 Python 경로를 실제로 변경한 경우에만 실행한다.
.venv/bin/python -m pytest -q
.venv/bin/python -m lakatos.longinus audit       # Python 코어 def-line 변경 시에만
```

게이트는 단순 경로명이 아니라 실제 dependency/contract closure로 선택한다. 알려진 RED를 경로
스코핑으로 숨겨 green으로 만들지 않는다.

## 4. 함정 (실전 비용 지불됨 — 반복 금지)

- `ruff --fix` 가 re-export 를 F401 오판 제거(테스트 파손) → 복구 시 `noqa: F401`.
- fake-heavy 경로(run_cycle 등)에 새 kg 쿼리를 넣으면 KG-less 테스트가 실 neo4j 를 친다 —
  파괴적 결정(삭제 등)의 조회는 fail-safe(불확실=안 지움).
- :55170 재시작: **`scripts/dev_server_restart.sh` 만 사용** — 정본 env(~/.config/lakatotree/server.env,
  0600) 없으면 기동 거부(무-creds 무음 degraded 사고 재발 방지), healthz 3/3 수렴 게이트 내장
  (version 200 ≠ 건강). 손 재시작(pkill -f 자기쉘 자살·environ 단일사본) 금지.
- 이벤트 리터럴은 emit-adapter 에만 — 엔진 코드에 절대 금지(ooptdd 규율).
- dev-box 자원 결합 테스트(형제 repo <WORKSPACE>/PROJECT/PI/omd·정본 env·3D workspace 절대경로)는
  hosted CI 에서 죽는다(PR#19 에서 9건 실측) — `pytestmark = pytest.mark.skipif(경로부재)` 관례
  (test_omd_engine_p* 참조)로 hermetic-skip, manifest 류는 *경로존재 단언만* 조건화(내용 불변식은 전역 실행).

## 5. 실행 예산 (2026-08-10 신설 · 2026-08-11 B5 축약 — 기계화 조항의 정본은 기계)

- **B1(예산 선언·초과=흡수 정지)·B3(무진전 3연속 정지)·B4(대기≠계산)·유계 출력의 정본은 기계다**:
  `ts/spec/run-budget.v0.json` + `ts/src/domain/{budget,streak,wait,bound,emission,run}.ts`
  (드리프트 = run-conform RED). MCP 경로는 ts 게이트웨이가 상주 강제(`ts/src/entrypoints/mcp.ts` —
  전 응답 ToolPage·실바이트 계량·캡은 env 전용). 산문 재서술 금지 — 조문 확인은 spec 을 읽는다.
- 주제가 바뀌거나 세션이 수 시간을 넘으면 새 세션을 연다 (긴 수명 = 턴마다 누적 히스토리 재전송, 품질 기여 0).
- 에이전트 자신의 green 보고는 주장이지 검증이 아니다 — 완료는 §3 게이트를 제3자(오케스트레이터/리뷰어)가
  재실행한 뒤에만 인정한다. verify 는 커밋 시점 트리와 같은 상태에서, exit code 직접 확인 (사고 2건 실측).
- 산문으로만 존재하는 강제 조항은 아직 강제되지 않은 조항이다 — 새 기계 게이트가 생기면 그 게이트가 정본이며 대응 산문은 지운다.
