# lakatotree — 에이전트 작업 규율

이 repo 는 **여러 Claude 세션이 같은 워크트리를 동시에** 만진다(실증: 2026-07-02 G6/G7·G10 병렬).
기본 개발 스택은 3층: **OMD(조율) × ooptdd/LTDD(측정) × judge(진보 판정)** — 아래는 그 채택 규율.

## 1. 병렬 세션 규율 (OMD — 편집 전 필수)

1. **편집 시작 전** OMD lease: `mcp__omd__declare(task, writes=[...])` → `claim` → **HELD 확인**.
   다른 세션의 untracked/미커밋 파일이 내 write-set 과 겹치면 **손 떼고 분리 태스크로 전환**.
2. claim 직후 **페이스 선언**: `heartbeat(agent, ttl=3600)` — 인터랙티브 세션의 per-agent 생존창.
   미선언이면 기계 물방울 기본(agent_ttl 90s)이라 verb 간 침묵 중 RETIRED 된다(F2, 실전 재현됨).
2b. lease-only 흐름(start/connect 미경유)을 닫을 땐 `cancel(task, reason)` — PENDING 잔류 방지(F4).
3. **커밋은 반드시 pathspec**: `git add <내파일들> && git commit -- <내파일들>`.
   맨 `git commit` 은 남이 스테이징한 파일까지 인덱스 전체를 쓸어담는다(사고 전례 0691263).
4. 전체회귀 판정 시 남의 in-flight RED 파일은 `--ignore=<파일>` 후 판정하고, 내 커밋에 절대 포함 금지.
5. 종료 시 `release`. (lease-only 사용(start/connect 미경유) 시 태스크가 PENDING 잔류 — 알려진 한계.)
6. 커밋하면 **곧바로 push** (공유 브랜치 규율).

## 2. 방법론 (RED-first 이중가드 + ooptdd 영수증 + judge 채점)

- 슬라이스마다 가드 먼저(RED 확인) → 구현 → green. 이중가드: guard_defect(음성 오라클, 결함 죽음)
  + guard_mechanism(양성 오라클, 메커니즘 실재). revert-민감하게(가드 떼면 RED).
- **엔진 거동 슬라이스는 ooptdd 영수증 동반**: `ooptdd_receipts/<ID>/{requirements.yaml, <id>_receipt.py}`.
  emit-adapter 는 *실코드*를 구동(재구현 금지)하고 **음성 오라클**(결함 주입 시 검출 = vacuous green 차단)을
  포함한다. `tests/test_ooptdd_receipts_all.py` 가 자동 발견·전수 실행 — 추가만 하면 CI 상주(등록 불요).
- 진보 주장은 `examples/*_programme.py` 하네스의 **judge() 채점으로만** (손입력 verdict 금지, no fake green).

## 3. 검증 게이트 (커밋 전)

```bash
.venv/bin/python -m pytest -q                    # 전체 0 회귀 (uv run 금지 — 이 repo 는 .venv 직접)
.venv/bin/python -m lakatos.longinus audit       # 코어 def-line 변경 시 docs/longinus_bindings.json 재베이스라인
```

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
