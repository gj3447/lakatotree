# 라카토트리 하네스 — 모든 계·행위자를 한 사이클로 엮기

> 프로메테우스가 상계(read-only 인터넷)서 불을 훔쳐 하계(read-write KG/코드/bash/git)에 내리고,
> 인간+agent 가 비판하는 한 연구 사이클. `lakatos/harness.py` (포트-어댑터, 헥사고날).

## 한 사이클이 엮는 것 (LakatoHarness.run_cycle)

```
① 상계 read (read-only)   인터넷 정보 fetch → TrustRank/EigenTrust 신뢰가중 (read_internet 포트)
② 하계 write              agent 가 노드 생성 + 구조적 예측 사전등록 + 채점 sha256 (http 포트)
③ 하계 execute (게이트)   build_cmd: 빌드/TDD/실행파일 — exit≠0 면 BuildFailed 로 중단(ground truth)
④ 하계 measure            judge_cmd: 'metric=<수>' 순수 파싱 (LLM 점수 금지)
⑤ 하계 write → 판결       test_result 제출 → judge(인터넷 source_trust 베이즈 결합) → progressive/...
⑥ 인간+agent critique     의문/반박 등재 → standing(Dung grounded extension)
⑦ 이력관리                git_sha — 코드 버전 관통
```

## 권한 경계 (상계/하계 = read/write)
- **상계(read-only)**: 인터넷 — agent(WebFetch)가 미리 read 해 `internet_sources=[(url, trust)]` 로 주입.
  하네스는 신뢰가중만 결합(권한 경계 존중 — 하네스가 직접 웹에 쓰지 않음).
- **하계(read-write)**: bash 실행·KG/DB·git — 하네스가 직접 write/execute. 검증 가능 = ground truth.

## 행위자 분업
- **인간 + agent** = 질문/코멘트/평가/의문 (critique, Dung attack). standing=False → 막지 못한 의문.
- **순수 agent** = 코드빌딩(build_cmd) + 채점(judge_cmd) + 반박(코드/증명으로 의문 격파).

## 실행
```bash
python -m lakatos.harness_run <spec.json>   # 실 HTTP/bash/git 포트
# 또는 테스트: pytest tests/test_harness.py (mock 포트, 4 케이스)
```
spec.json = CycleSpec 필드(tree/tag/parent/metric/baseline/build_cmd/judge_cmd/internet_sources/human_critiques).

## 검증 (라이브 E2E)
v7_harness 사이클: 상계 read(신뢰0.9) + 하계 build(exit0, 66 TDD) + metric 66 + progressive(novel) +
인간의문→agent반박→standing True + git 2c216b0. test_harness 4/4 + build-fail 게이트 + 신뢰전파 검증.

## ARG-1..5 요구사항 무결성 하네스

`ooptdd_receipts/ARGUMENT_INTEGRITY/harness.json`은 L_IDE 검증 인스턴스다. 기존 메모리
receipt의 빠른 응답계약 검사와 별도로, 실제 `EvidenceClaimService.add_critique`를 일회용
Neo4j+PostgreSQL에 연결해 dangling target, immutable id, exact retry, tree-scoped race,
ON CREATE claim 소유권을 독립 DB readback으로 확인한다.

```bash
python ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py \
  --artifact-dir /tmp/argument-integrity-harness
```

성공은 현재 코드 ARG-1..5 GREEN → 역사 revision의 ARG-1..4 exact non-infrastructure RED →
현재 source archive에서 `ON CREATE` claim assignment만 제거한 ARG-5 `AssertionError` RED →
현재 코드 restored ARG-1..5 GREEN의 네 단계를 모두 요구한다. 고정 SHA의
`judges/arg5_targeted_negative_oracle.py`가 phase/hash/mutation binding을 다시 채점해 gap=0이어야
최종 receipt가 complete다. Git-locked preregistration은 이 CI 측정을 구속하지만 LakatoTree 서버
등록이나 과학적 verdict 권위는 주장하지 않는다. Docker/testcontainers가 없거나 음성 오라클
revision을 읽을 수 없으면 exit 2로 fail-closed하며, 비밀번호·URI·전체 환경변수는 receipt에
기록하지 않는다. CI의
`argument-integrity-harness` job은 이 절차를 allow-failure 없이 실행하고 결과 bundle을 업로드한다.
