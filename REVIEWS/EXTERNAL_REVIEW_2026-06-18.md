# 외부 리뷰 — LakatoTree (2026-06-18)

> 리뷰어: 외부 평가자 (Claude, 사용자 의뢰). 방법: README/THEORY/LINEAGE/ADVERSARIAL 정독 +
> **실제 빌드·테스트 실행으로 간판 검증**(receipts, not claims — 이 프로젝트 자신의 독트린을 리뷰에 적용).
> 결론 한 줄: **아키텍처/개념은 강하고 Lean 간판은 진짜다. 단 "tests green"은 clean clone에서 재현되지 않는다 — 의존성 명세 결함.**

---

## A. 실측 검증 (receipts)

리뷰 환경: Python 3.14.4 / fresh `uv venv` / `pip install -r requirements.txt` / Lean `elan` 신규 설치.

| 간판 (claim) | 실측 결과 | 평결 |
|---|---|---|
| `cd formal && lake build` → error=0, sorry=0, 12 theorems | `Build completed successfully` · `sorry` 택틱 0개(정적+빌드 경고 0) · `theorem` 12개 정확 | ✅ **참** |
| `python -m pytest tests/ -q` 통과 | **clean clone에서 수집조차 실패** — `httpx`, `mcp` 미설치로 8개 모듈 collection error | ❌ **거짓 (재현 불가)** |
| (위 deps 수동 보강 후 재실행) | **755 passed, 7 failed, 1 skipped** | ⚠️ **부분** |
| 코어 엔진/판결 로직(judge·bayes·laudan·engine·metrics·certify·pnr) | 전부 green (156/156, 버전 무관) | ✅ **참** |

### A-1. `requirements.txt` 결함 (BLOCKER, 재현성)
- `httpx`, `mcp` 두 런타임 의존성이 **누락**. `mcp_server.py`/`fastapi.testclient`가 import하므로 clean clone에서 8개 테스트 모듈이 **수집 단계에서 사망**.
- 버전 핀이 **0개**(완전 비고정). 이게 아래 A-2의 직접 원인.
- → "receipts, not claims"를 표방하는 repo에서 **테스트 green 자체가 재현 불가능한 claim**이 되어 있음. 이것이 이번 리뷰 최대 아이러니.

### A-2. 7개 실패는 로직 버그 아님 — 버전 커플링 (DEBT)
- 실패 7건 전부 `test_server_architecture.py` / `test_make_it_real.py` / `test_adapters.py`의 **인트로스펙션 테스트**.
- 원인: 최신 FastAPI(0.137)/Starlette(1.3)에서 `app.include_router()`가 하위 라우트를 `app.routes`에 **평탄화하지 않고** `_IncludedRouter` 래퍼로 감싼다. 테스트는 옛 FastAPI의 평탄화 동작(`route.path`/`route.endpoint.__module__` 직접 순회)을 가정 → `owners.keys()`가 빈 집합.
- **런타임 라우팅은 정상.** 즉 엔진 결함이 아니라 **테스트가 미고정 라이브러리 내부구조에 결합**돼 있어 깨진 것.
- 권고: ① `requirements.txt`에 `httpx`, `mcp` 추가 + 상한 핀(`fastapi<0.137` 또는 introspection을 `app.routes` 평탄화 대신 공개 API로 재작성) ② CI를 clean 컨테이너에서 돌려 이 클래스의 드리프트를 사전 차단(현재 `test_readme_longinus.py`가 모듈맵 드리프트는 막지만 **deps/런타임 드리프트는 못 막음**).

---

## B. 개념 리뷰 (5 findings)

### B-1. "machine-checked"의 범위 — 모델 ⊂ 구현 (정직성 톤)
Lean 증명은 Python이 아니라 **손으로 쓴 모델**(`formal/Pidna.lean`)을 검증한다. README가 "not an auto-extraction of the Python"으로 정직하게 인정한 부분이지만, 이게 사실상 "formal foundation" 셀링포인트의 한계 전부다. 모델↔구현 간극이 버그가 사는 곳. **"machine-checked theory"는 참(검증함), "verified engine"은 거짓** — 그런데 README 상단 톤은 후자처럼 읽힌다.
→ 권고: Lean 범위 한계를 README **첫 문단**으로 끌어올릴 것.

### B-2. confabulation을 제거한 게 아니라 경계로 밀어냄
채점은 결정론적이지만 입력(무엇이 "novel 예측"인지, "외부 측정", `noise_band` 값, corroboration 인정 기준)은 여전히 에이전트/사람이 **프레이밍**한다. `gap1`을 "닫힘"이라 했으나 `ADVERSARIAL.md`는 여전히 "예측 텍스트 채점은 frontier"라 인정. **garbage in → 결정론적 garbage out.** 판결 단계는 잠갔으나 프레이밍·측정 단계로 confabulation 재진입 가능.

### B-3. 과적층(over-engineering) 위험
Popper+Bayes+Laudan+AGM+Dung AF+bandit+VoI+PROV-O+EigenTrust+다중비교보정+Kuhn — 바닥은 "예측을 측정과 대조해 점수낸다"인데 학설을 11겹 쌓음. 상당수 층이 실제로 **판결을 뒤집은 횟수**가 의심스럽고, tier 표기 자체가 "유도된 듯 보이는 정책 상수"가 많음을 드러냄.
→ 권고: **각 층이 실제로 판결을 바꾼 사례 카운트를 지표로 노출**(층의 load-bearing 여부를 데이터로 증명 — 이 프로젝트 정신과 일치).

### B-4. 시·신화 레이어가 신호를 가림
"touch the sky", 비행기맨, poem 커밋, "ascending double-helix", Longinus, 나생문 critic — 매력적이나 리뷰어가 load-bearing 엔지니어링과 로망스를 분리하는 데 품이 든다. 외부 평가자에겐 인플레이션으로 읽힐 수 있음.

### B-5. 효능 증거 부재
euler/HALCON-3D 도그푸딩은 좋은 신호지만 "이 엔진을 통과한 연구가 안 통과한 것보다 실제로 낫다"는 증거는 아직 없음. 단기 증명이 어려운 종류라 당분간 신념의 영역.

---

## C. 강점 (균형)
- **핵심 통찰이 정확**: conjecture/verification 역할분리 + `Rung.derived : verdict = judge …`로 자기보고 판결을 **타입상 거주불가**로 만든 것은 Goodhart 회피의 정공법.
- **지적 정직성**: gap 표, tier 표기, "Scope, honestly", 자기 가설(meta-spiral) 자기반증·가지치기.
- **드리프트 가드**: import-linter 레이어 강제 + 모듈맵 테스트 검증.

## D. 평결
**아키텍처 A− / "검증된 진리 엔진" 서사 B−.** 최대 자산은 Lean이 아니라 "누구도 자기 출력을 채점 못 한다"는 구조적 불변식. 가장 시급한 실무 결함은 **B-1의 톤**이 아니라 **A-1(requirements 미명세 → 테스트 green 재현 불가)** — 정직성 브랜드를 직접 훼손하므로 우선 수정 권고.

### 액션 아이템
- [x] (P0) `requirements.txt`에 `httpx`, `mcp`, `lxml`, `rdflib` 추가 — **이 커밋에서 수정**
- [x] (P0) 의존성 버전 핀(`==`) — **이 커밋에서 수정**. clean venv + `pip install -r requirements.txt`만으로 762 passed 재현 확인
- [x] (P1) `test_server_architecture` + `test_make_it_real` 인트로스펙션을 `_IncludedRouter` 평탄화 헬퍼로 버전-비결합화 — **이 커밋에서 수정** (7→0 fail)
- [ ] (P1) clean-container CI로 deps/런타임 드리프트 차단 — *미착수(인프라)*
- [ ] (P2) README 첫 문단에 Lean 범위 한계 명시 (B-1) — *문서 톤, 저자 판단 영역*
- [ ] (P2) 각 rigor 층의 "판결 뒤집은 횟수" 지표 노출 (B-3) — *기능 추가, 별도 작업*

### 수정 후 실측 (2026-06-18, this branch)
| 항목 | before | after |
|---|---|---|
| clean clone `pip install -r requirements.txt` | 8 collection errors | ✅ 성공 |
| `pytest tests/ -q` | 755 passed / 7 failed | ✅ **762 passed / 0 failed / 1 skipped** |
| `cd formal && lake build` | (변경 없음) | ✅ success, sorry=0 |
