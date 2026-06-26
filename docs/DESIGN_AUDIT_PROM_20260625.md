# LakatoTree 설계감사 PROM 도시에 (2026-06-25)

> 知선행(行 전에 不知를 먼저 훔친다). 설계감사 13건(H1~H4, M1~M9)을 *제대로* 풀기 위한 사전 정찰.
> 짝 문서: 감사=[[lakatotree-design-audit]], 피드백 하네스=`examples/design_audit_20260625_programme.py`.
> 산출: 8테마 정찰(GIT/ 실염탐) → 도시에. PROM 워크플로 wz4gg77u1 / wf_b810ebf7-126.

## 헤드라인

먼저 훔칠 불 3개: (1) p333/crates/ltdd "제출값=주장·재유도값=판관" 독트린 + bhgman longinus_sha256_daemon "서버가 sourcePath에서 sha 재계산→대조→drift" — H3·H2·M1·M6의 척추, (2) omd CONCURRENCY.md/core.py "단일 임계구역 + fence + 멱등" — M5 TOCTOU 완본, (3) lakatotree 자체 안의 정답 패턴들(register_prediction의 단일-statement WHERE 가드, fertility.py의 novel_confirmed 게이트, judge.py의 dead PredictionLocked) — 외부 도입 0으로 H3·M3·M5·M6 절반은 같은 repo 안에서 닫힌다. 외부 신규 fetch는 TweetyProject(AGM oracle)뿐 사실상 필수.

---

# LakatoTree 설계결함 13건 → PROM 도시에 (아키텍트용)

> 원칙: **무작정 가지 마라.** 13건 중 다수는 LakatoTree repo *안에* 이미 정답 패턴이 있고(`register_prediction` 단일-statement 가드, `fertility.py`의 `novel_confirmed` 게이트, `judge.py`의 dead `PredictionLocked`), PI 워크스페이스(p333/ltdd, bhgman, omd)에 완성된 레퍼런스가 있다. 외부에서 *새로* 가져와야 하는 건 TweetyProject(AGM oracle) 한 종이 사실상 전부. 모든 fix는 "client 제출값=주장, 서버 재유도값=판관" 하나의 척추로 수렴한다.

> 정찰 검증 메모(샘플로 직접 확인): `metrics.py:71` 라벨-only 카운트 / `fertility.py`의 `novel_confirmed` 게이트 / `longinus.py`의 `{s}\s*[:=]` ==오인 정규식 + def-한줄 sha / `ci.yml` formal job의 bare `lake build` + "sorry=0" 거짓주석 — 전부 코드로 실재 확인. TweetyProject는 GIT/에 **없음**(fetch 필요).

---

## T1 — 영수증 위조불가 · 내용주소화 · 시간순서 (H3, M6)

**▸ local에서 훔칠 것**
- `p333/crates/ltdd/src/lib.rs:1-23` — "a function returning ok is a *claim*; the store is the judge" + Inconclusive(⊥ vs ?) 3값. H3 에러처리의 척추: sha 재계산이 OSError면 422가 아니라 **판정유보**(infra blip≠위조).
- `bhgman_tool/.../longinus_sha256_daemon.py` — "sourcePath에서 sha256 재계산→stored 대조→drift event"의 **PI-내부 완본**. 경로해결 체인(_BIN_DIR→_REPO_ROOT)도 judge_script 안전 join에 그대로.
- `lakatotree/lakatos/verdict/judge.py:16-17,93-95` — `PredictionLocked`/`check_registration`이 *이미 정의됐으나 dead*(server 호출 0). M6 최소판 = 이 dead code를 submit 경로에 **연결만** 하면 됨.
- `lakatotree/lakatos/harness.py:108-121` — sha 계산 코드(`hashlib.sha256(open(judge_script))`)가 client(harness)에 있음. **이 코드를 서버로 이동**하면 H3 핵심 해결.
- `bhgman_tool/.../skill-build-attestation.py` — in-toto Statement/v1 + SLSA Provenance v1 envelope 형태(subject.digest.sha256, merkle_root). 재유도 sha를 표준 어테스테이션으로 직렬화.
- `GIT/kythe/.../kzip.go:227-294` — content-addressed store canonical(`filePath(digest)`, 해시로 동일성 검증). judge_script를 경로 아닌 digest로 저장→파일 교체 공격 차단.

**▸ 외부에서 가져올 것** (fetch_queue 참조)
- in-toto/SLSA(bhgman이 부분채택, 스펙은 미반입), Sigstore Rekor + Trillian/CT(RFC 6962), RFC 3161 TSA — append-only Merkle log inclusion order / 서명 타임스탬프로 M6의 "먼저임"을 제3자 검증가능하게 (강화 단계).

**▸ 기반지식**
- second-preimage vs transport integrity: 현재 `judgement_service.py:231`은 client값끼리 비교 = sha가 전송무결성조차 아님(자기 자신과 비교).
- trusted timestamping & append-only log: `pred_registered_at`은 서버가 쓴 ISO 문자열일 뿐, 같은 서버가 측정시각도 씀 → 한 권위의 self-report라 재정렬 가능.
- generator≠verifier(oracle problem, Weyuker 1982; ltdd 독트린).

**▸ fix 경로**
- H3: `submit_test_result`에서 `r.script_sha`를 **신뢰하지 말고** r.script 파일을 project_root 기준 안전 join해 서버가 `sha256(content)` 재계산. line 231의 `pr['psha'] != r.script_sha`(client vs client)를 `server_sha != pred_script_sha_server_recomputed`(server vs server)로 교체. `register_prediction`도 그 시점 서버가 sha 재계산해 저장. prov.py:17과 in-toto subject도 server_sha로.
- M6: dead `PredictionLocked` 연결 → register는 `judged_at IS NULL AND pred_registered_at IS NULL`일 때만 SET(immutable). 강화: pred 해시에 RFC 3161 TST / Rekor inclusion. 정당한 수정은 amendment(새 노드)로만.

**▸ 무작정 함정**
- H3을 "서버가 client sha를 더 꼼꼼히 검증"으로 고치면 비교 대상이 여전히 client 통제값 → generator==verifier 동어반복 그대로(line 231은 이미 client끼리 비교 중이라 "검증 추가"한 듯 보이지만 연극).
- M6을 "pred_registered_at < judged_at 비교 추가"로 고치면 같은 서버가 두 시각을 다 써 위조시각끼리 비교가 됨. register를 단순 once-only로 막으면 정당한 amendment와 HARKing을 구분 못 함 → OSF식 frozen+amendment 패턴 필요.

---

## T2 — 코드↔심볼 바인딩 (CPG/code-KG로 judge_script 심볼 실존·정합) (H3)

**▸ local에서 훔칠 것**
- `bhgman_tool/engine/longinus_drift_audit/scip_adapter.py` — SCIP moniker 파싱 + sigil(`#`type `.`term `().`method) kind 분류의 **이미 작동하는 어댑터**. lakatotree `longinus.py`가 만들어야 할 심볼ID의 레퍼런스 구현. **재사용 가능**.
- `bhgman_tool/.../tree_sitter_adapter.py` — graceful-import(미설치 시 스텁) 패턴. cross-lang(Lean 채점) 토대.
- `GIT/scip/scip.proto:148-282` — Symbol 문법(AST-ancestry 경로의 모든 노드마다 descriptor). 정규식 첫매칭이 못 가진 스코프-정확 식별의 표준 정의.
- `GIT/codepropertygraph/.../Method.scala` — HASH "over function contents"(본문 전체 해시) + AST_PARENT_FULL_NAME. **`longinus.py`의 def-한-줄 sha를 심볼 본문 전체 sha로 교체**하는 산업표준 근거.
- `GIT/kythe/.../storage.proto` VName 5-튜플 — 위치-독립 심볼 식별.
- `GIT/semantic/semantic-scope-graph/`(Haskell, 알고리즘만 차용), `GIT/atom`(reachability 심화).

**▸ 외부에서 가져올 것**
- Python stdlib `ast`(의존성 0, 이미 멀티버전) — `_resolve` 정규식을 NodeVisitor+스코프 스택으로 교체하면 `==` 오인이 원천 소멸(ast가 Compare로 구분). 신규 fetch 불필요.

**▸ 기반지식**
- Scope Graphs(Néron-Visser ESOP15): 정규식 첫매칭은 lexical 스코프를 모른다 → 동명 메서드·중첩 def에 엉뚱한 심볼 바인딩.
- CPG 4축(FULL_NAME+SIGNATURE+AST_PARENT+HASH본문전체).
- 안정 심볼ID 위치-독립(SCIP descriptor/Kythe VName).
- producer≠attestor(in-toto): client가 sha 계산·제출하면 self-report.

**▸ fix 경로** (3단계)
1. `longinus.py` 정규식 resolver를 `ast` 기반 SymbolResolver로 교체(qualified name 키, `get_source_segment`로 본문 전체 sha).
2. `submit_test_result`에서 서버가 judge_script 심볼 본문 sha 재계산, client 불일치 시 422.
3. `register_prediction`의 `pred_script_sha`도 서버 재계산값으로(PredictionIn에 script_path 추가) → line 231-232 비교가 server vs server.

**▸ 무작정 함정**
- ast 없이 정규식 유지한 채 sha만 서버계산하면 *엉뚱한 심볼*의 진짜 sha = 완벽한 거짓 영수증.
- sha를 def 한 줄에만 걸면 본문 통째 변경에 무드리프트(CPG contents-hash 필요).
- 심볼ID를 줄번호/경로로 잡으면 정상 리팩토링마다 drift 폭주 → 팀이 감사를 꺼버림.
- 사전등록 sha도 client값이면 등록·제출 둘 다 client라 영원히 동어반복.

---

## T3 — 재현가능 측정 · lineage · 외부 readback 계약(producer≠measurer) (M1, M4, M9)

**▸ local에서 훔칠 것**
- `lakatotree/lakatos/io/rebuild.py:66-67` — **수술 대상**: `regen=_parse_metric(last_out)`이 마지막 step stdout에서 metric을 긁음 = measurer==producer. 골격(버퍼 무시/topo 재실행/cid trace)은 보존하고 독립 measurer step을 끼움.
- `lakatotree/lakatos/io/lineage.py` — by-construction 재현 골격(Derivation/manifest/gap/stale/env_drift) 이미 존재. **`kind='measurement'` Derivation 한 줄 추가**로 측정을 lineage 일급 노드화.
- `lakatotree/lakatos/io/adapters.py:58-130` — OpenLineage 직렬화 이미 있음(단 eventType=COMPLETE만, metric facet 0). measurer를 별개 RunEvent(job.name='measure:<artifact>')로.
- `lakatotree/lakatos/io/oo_verify.py:27-29` — **M9 자백이 주석에 그대로**: "opener 주입해 같은 프로세스 응답 대조(영수증 연극). 외부 백엔드로 positive 왕복 고정할 것."
- `lakatotree/_vendor/ooptdd/backends/conformance.py` — `assert_backend_conforms`는 ship→독립query→compare 진짜 왕복(drop=True면 RED). **이미 부분적으로 M9를 푼 자산** → MarquezBackend로 확장만.
- `lakatotree/server/contexts/tree/writer.py:223-241` — **M4 결정적 증거**: `upsert_questions`가 `(node)-[:RAISES_QUESTION]->(q)`를 절대 안 씀(write=0, read=3). laudan은 읽기만 함 → 라이브에서 opened 항상 0. **writer를 추가**.
- `lakatotree/lakatos/quant/laudan.py` — opened/closed 귀속 모델 **이미 옳음**. 절대 건드리지 말 것(M4는 계산층 아닌 **공급(writer)층** 문제).
- `omd/CONCURRENCY.md` — fence/epoch로 measurer actor 독립성 형식화(M9 자기응답 차단).

**▸ 외부에서 가져올 것**
- OpenLineage spec 1-0-5(run lifecycle START/RUNNING/COMPLETE, ParentRunFacet, dataQuality/outputStatistics facet) — 엔진이 이미 Marquez ship 중, **신규 의존 0**, 표준 facet만 채우면 됨.
- DVC(metrics:/plots: 분리), reproducible-builds/reprotest(변주 재실행), Pact(consumer-driven contract, actor 분리 broker), Bazel/Nix(hermetic, undeclared input=실패), `GIT/graphiti/edges.py`(bi-temporal valid_at/invalid_at).

**▸ 기반지식**
- OpenLineage RunEvent 생명주기·facet: 모르면 M1을 "metric 어딘가 또 쓰자"로 오해.
- **재현≠반복**: nondeterminism source(시각/경로/env순서)를 *바꿔서* 두 번 돌려도 같아야 재현. 한 번 같음은 반복.
- Pact actor 분리: M9는 "외부 켜기"가 아니라 "기대 적는 자≠확인하는 자".
- bi-temporal(valid time vs transaction time): 질문 열림/닫힘은 시간 사건.

**▸ fix 경로**
- M1: `kind='measurement'` Derivation 추가 + RebuildExecutor가 완성본 파일만 input으로 받는 별개 측정 step 실행 + reprotest식 변주 2회 재실행(cwd/env순서) + adapters에 measurer 별개 RunEvent.
- M4: writer에 `link_raised_questions` 추가(`MERGE (e)-[:RAISES_QUESTION]->(qn)`) + graphiti bi-temporal(valid_at/invalid_at). **laudan.py 불가침**.
- M9: conformance 패턴을 MarquezBackend(POST 후 독립 GET)로 확장 + Pact식 measurer actor_id 독립성 + CI hermetic 항상 ON + drop류 음성 케이스(RED 이빨).

**▸ 무작정 함정**
- M1을 "한 번 재실행해 같으면 rebuildable"로 고치면 같은 env에서 같은 echo 또 뱉어 통과(동어반복의 정교화).
- M4를 NodeIn questions 길이로 in-memory 계산하면 라이브 KG의 엣지는 여전히 0(이중장부). 반드시 writer가 KG에 materialize. laudan 손대면 회귀.
- M9 게이트만 ON으로 바꾸고 같은 프로세스가 ship/verify하면 영수증 연극 그대로.

---

## T4 — AGM 신념개정 · 하드코어 보호 형식화 (H1, H4)

**▸ local에서 훔칠 것**
- `lakatotree/lakatos/programme/agm.py`(161줄) — **H4 수정의 70%가 이미 여기**: `contraction()`/`revision()`/`_dependents_closure`/`entrenchment_key`/`HardCoreProtected` 게이트. `demote_canonical`만 이 인프라를 안 씀. `demote_canonical`을 `revision(base,new,contradicts=[old],allow_hard_core=...)`로 재작성하면 Levi identity가 돌고 게이트 자동 상속.
- `lakatotree/.../judgement_service.py:250-260` — **H1 chokepoint**: `bool(r.lakatos_excess)` 등 client bool을 LakatosEvidence에 직삽입. 여기서 서버 재유도로 교체.
- `lakatotree/lakatos/programme/heuristic.py:81` `negative_heuristic` — hard_core vs belt를 **집합연산**으로 이미 가름. bool→결정 치환의 국소 형식기(TweetyProject 없이도 가능).
- `lakatotree/lakatos/verdict/pnr.py:166-219` — H1 bool이 PnR 변증법 경로로도 새는 **두 번째 우회로**.
- `lakatotree/server/app.py:614-659,577-611` — `demote_canonical` 호출이 `allow_hard_core`를 안 넘김(게이트 밖). `_persist_revision`이 removed→former_canonical auto-rejudge하는 원자 tx 이미 존재(진짜 contraction이 removed 채우면 영속 공짜).
- `GIT/graphiti/edges.py:271-277` + `edge_operations.py:325-543` — bi-temporal **belief 무효화 데이터모델**(invalid_at/expired_at, 반증 흔적 보존). ★단 graphiti의 **판정자는 LLM** → 데이터모델만 훔치고 판정은 negative_heuristic 결정론으로(self-report→LLM-report 함정).

**▸ 외부에서 가져올 것**
- **TweetyProject**(GIT/ 미반입, fetch 필수) — KernelContraction/Levi operator + AGM postulate(success/inclusion/vacuity/recovery) 검사를 **reference oracle**로. 손으로 적은 revision()의 공준 준수를 property test로 검증.
- AGM 1985 + Hansson base-revision, Lakatos MSRP/Zahar use-novelty, Gärdenfors entrenchment EE1-EE5(dominance).

**▸ 기반지식**
- AGM 3연산 + Levi identity(revision = contract(¬A) THEN expand(A)): 모르면 demote를 "credence 깎기"로 오인.
- base revision vs theory revision: agm.py가 정직하게 base 계열 → recovery 비성립이 정당(버그 아님).
- Lakatos 초과경험내용 판정기준 = judge()의 독립 sha novel 확증 ∧ net problem closure.
- entrenchment EE2 dominance(hard_core>belt).

**▸ fix 경로**
- H1: schemas의 lakatos_* client bool 제거(extra='forbid'→422). LakatosEvidence를 서버 도출: `hard_core_preserved = (touched_beliefs ∩ tree.hard_core == ∅)`(negative_heuristic), `excess_empirical_content = (judge() Verdict.novel ∧ 독립 sha ∧ net closure>0)`. pnr.py:198/284도 같은 도출값으로(변증법 우회 봉쇄).
- H4: `demote_canonical(...,allow_hard_core=False)` → hard_core면 게이트, `revision(contradicts=[old])`로 진짜 Levi. app.py:642에 allow_hard_core 전파. 선택: contraction을 graphiti invalid_at로 영속.

**▸ 무작정 함정**
- H1을 "서버가 재유도"한다며 또 다른 자의적 휴리스틱(노드 수 증가=초과내용)을 박으면 self-report를 pseudo-formal로 세탁만. 반드시 judge()가 이미 영수증화한 독립 sha novel에서 유도.
- H4에서 Levi 모르면 demote를 destructive remove로 구현 → 라카토스 "기각 가지 보존" 위반 + base recovery 비성립을 버그로 오인. allow_hard_core 미전파 시 hard_core가 조용히 강등.
- graphiti LLM 판정 그대로 베끼면 동일 함정 재추락.

---

## T5 — 독립 평가자 · 인간증명 위조불가 · 직무분리(SoD) (H1, H2, M8)

**▸ local에서 훔칠 것**
- `lakatotree/lakatos/claim.py:124-144` — **M8 버그 현장**: `_resolved_doubt_ids`가 `payload['resolves']`만 보고 doubt를 닫음, resolver.actor와 doubt.actor를 **대조 안 함**(자문자답 허용). ResearchEvent.actor는 이미 KG에 적재됨(evidence_claim_service.py:159).
- `lakatotree/.../judgement_service.py:110-148` — **H2 주입점**: `has_human_verdict=bool(v.human_verdict)`. 이미 fetch 중인 args에 a.by/a.kind 추가 SELECT해 "∃ Argument(kind∈{human_attestation,evaluation} ∧ a.by≠author)"의 서버 MATCH 결과로 도출.
- `lakatotree/lakatos/verdict/argue.py:21-37` — Dung grounded_extension 이미 standing에 쓰임, 단 **actor-blind**. AF 넣기 전 actor pre-filter(resolve는 by≠doubt.by일 때만 유효 attack)로 자문자답 무력화. a.by는 이미 저장됨.
- `GIT/phoenix/.../models.py:1148-1166` — annotation을 1급 노드로: annotator_kind CheckConstraint(LLM/CODE/HUMAN) + user_id FK. H2의 client bool 대체 정본.
- `GIT/deepeval/.../arena_g_eval/utils.py:13-86` — blind grading(FAKE_NAMES 마스킹 + shuffle). H1의 self-preference 제거.
- `GIT/simple-evals/common.py:157`, `math_eval.py:29-55` — grader를 별개 생성자 인자로(우연한 self-grading 불가).
- `GIT/guardrails/.../validator_base.py:92-143` — 검증을 별도 pass로(on_fail=EXCEPTION).
- `bhgman_tool/symposium-skills/CODEOWNERS` — scope→authorized_actors SoD 선언.

**▸ 외부에서 가져올 것**
- in-toto Attestation(ITE-6, DSSE, functionary key SoD) — repo 미보유(fetch). Sigstore Rekor(append-only inclusion, stale 무효화). NIST RBAC SSD/DSD. GitHub branch-protection(self-approve 금지·dismiss-stale). Dung 1995 + value-based AF(PyArg).

**▸ 기반지식**
- LLM-as-judge self-preference bias(Zheng 2023, Panickssery 2024): 분리만으로 부족, **블라인딩 필수**.
- Dung AF의 actor-blindness(grounded_extension만으론 자문자답 못 막음).
- SoD Static(SSD)/Dynamic(DSD), two-person rule.
- 위조불가 증명 = signed attestation + transparency log + content-binding(subject digest).

**▸ fix 경로**
- H1: LakatosEvidence bool을 QualValidator.validate()→Pass/Fail 통과로만 True + grader_actor 별도 인자(==author면 422) + 저자 마스킹/순서 셔플 + 결과를 phoenix annotation 행으로 독립 기록.
- H2: `has_human_verdict` 삭제, 서버 MATCH 도출(권한 attestor registry 통과). 강화: DSSE 서명 payload(subject=노드 digest) + digest 일치 검증(stale-dismissal).
- M8: `_resolved_doubt_ids`에 `resolver.actor ≠ doubt.actor` 검사(같으면 self_resolved 경고+unresolved 유지) + AF self-attack 제외. NIST RBAC SSD로 역할 배타, 신원은 서명키 바인딩(Sybil 차단).

**▸ 무작정 함정**
- H2를 "KG에 human Argument 있나만 MATCH"로 때우면 self-attestation/권한없는 HUMAN 자처/attest 후 내용 변경(stale)/backdating 4구멍 잔존.
- H1을 "별도 grader 모델만 붙이면 독립"으로 믿으면 self-preference로 독립 평가 연극(블라인딩 누락).
- M8을 "actor != author if문" 한 줄로 막으면 Sybil 우회 + Dung AF actor-blind라 standing 여전.

---

## T6 — 동시성 원자성 (TOCTOU 제거) (M5)

**▸ local에서 훔칠 것**
- `omd/omd_server/store.py:200-224,286-295` — `tx()` BEGIN IMMEDIATE(읽고-검사-쓰기를 한 트랜잭션) + `next_fence()` 단일문 +1 + `cas_leader` CAS. **M5의 원형**.
- `omd/omd_server/core.py:858-972` — claim이 _conflicts(read)+grant(write)를 같은 `with self._cs()` 임계구역에. CONCURRENCY.md가 진단한 옛 TOCTOU를 **고친 후 코드**(단일 임계구역+fence 가드+멱등 3종).
- `omd/.../store.py:44-46` — UNIQUE INDEX 방어심층(코드 회귀해도 중복=IntegrityError).
- `omd/.../core.py:864` `_idem` — at-least-once 재시도 이중작용 차단(성공 종단만 캐시).
- `lakatotree/.../judgement_service.py:195-215` — **이미 정답 패턴**: `register_prediction`이 WHERE 가드+SET을 **한 Cypher statement**에 담아 Neo4j 단일-statement 원자성. submit을 이 형태로 리팩터하면 됨.
- `lakatotree/server/container.py:59-64` — `kg_tx`는 write끼리만 원자(ROB-1), 가드 read는 `self.kg`(별개 session, :218) → read/write 두 session = TOCTOU. set_verdict도 동일 약점.

**▸ 외부에서 가져올 것**
- Neo4j unique constraints + 단일-statement MERGE 원자성(제품 1급 보장, register_prediction이 이미 검증). Kleppmann DDIA Ch.8 fencing tokens(omd가 직접 인용). OCC/version-stamped CAS(Kung&Robinson 1981, etcd/DynamoDB). 신규 repo fetch 불필요(문서/책만).

**▸ 기반지식**
- Neo4j 단일-statement 원자성 vs 다중-session read/write 경계: "kg_tx가 트랜잭션이니 원자다"는 착각(가드 read가 밖이면 TOCTOU 그대로).
- TOCTOU check-then-act 비원자성(락 범위가 read 포함 안 하면 헛수고).
- fencing token + monotonic clock(Chandra-Toueg: 완벽한 실패감지 불가, write를 토큰 불일치로 거부).
- 멱등성 + at-least-once(MCP 재시도).
- 방어심층(가드+DB 제약 2층).

**▸ fix 경로**
- 가드 read를 write의 WHERE로 흡수: 최종 verdict write Cypher에 `WHERE (e.verdict_source IS NULL OR <>'scripted')` + RETURN, kg_tx 첫 op로, rows 비면 tx 안에서 예외→409. script_sha 가드(H3)도 같은 트랜잭션으로. submit_result MCP에 request_id 멱등(JudgementReceipt MERGE). Neo4j unique constraint / JudgementLock 방어심층. set_verdict도 같은 수술.

**▸ 무작정 함정**
- write만 kg_tx로 감싸고 가드 read를 self.kg에 남기면 두 동시 submit이 둘 다 통과 → verdict 이중 덮어쓰기·bandit 보상 이중계상인데 단일-스레드 테스트는 green(가짜 green).
- fencing/멱등 빼면 정상 MCP 재시도를 409로 깨거나 GC-pause ABA로 옛 submit이 덮어씀.
- DB 제약 빼면 후속 PR이 WHERE 빠뜨려도 회귀가드 없음.

---

## T7 — 형식 CI 위생(sorry=0 실강제) + fail-loud 오케스트레이션 (M7, M2)

**▸ local에서 훔칠 것**
- `lakatotree/.github/workflows/ci.yml:84-97` — **현장**: formal job이 bare `lake build` + "ground-truth gate: sorry=0" 거짓주석(line 96). sorry는 warning이라 exit 0 → 침투해도 green.
- `lakatotree/formal/Pidna.lean` — `Rung.derived` 타입불변식(자기채점 불가)이 sorry 한 줄로 위조됨 → sorry=0은 타입안전성의 **전제**. 핵심 정리 7개가 axiom allow-list 게이트 대상.
- `lakatotree/lakatos/harness.py:63-148` — **M2 현장**: `_build_gate`만 fail-loud(`raise BuildFailed`), `_submit_and_judge`(145-148)는 응답 dict 무검사 반환 → 채점거부(404/422/409)에도 `verdict=None`인데 exit 0+stands=True. `self._http`가 status를 버리는 게 근본원인.
- `bhgman_tool/.github/workflows/{ci.yml,lean-build.yml}` — **반면교사**: olean 개수/컴파일 성공을 sorry=0으로 착각하는 안티패턴 2사례. (시드가 "bhgman lean에 답 있다" 했으나 실제론 같은 결함 공유 → 음의 자산.)
- `GIT/langgraph/.../pregel/_retry.py:631-661` + `errors.py:50-67` — fail-loud 전파 canonical: GraphBubbleUp은 절대 retry/삼킴 없이 raise, "panics the run instead of silent tear-down" 주석, raise가 default. exc.add_note로 사이클/노드 추적.

**▸ 외부에서 가져올 것**
- mathlib4 CI(`lake build --iofail`, `LEAN_ABORT_ON_PANIC=1`, nolints.json allow-list) — sorry/axiom exit-code 강제의 사실상 유일한 대규모 reference. Lean `set_option warningAsError true`(외부의존 없는 Pidna에 전역 적용 안전), `#print axioms`/sorryAx allow-list(propext/Classical.choice/Quot.sound). Temporal/Saga(영수증 일관성 심화).

**▸ 기반지식**
- Lean sorry 의미론: sorry=warning, sorryAx는 타입체커 통과, lake build는 warning에 exit 0. "lake build green=sorry 없음"은 거짓 등식.
- axiom allow-list 감사(import 깊은 곳 sorry/주입 axiom).
- fail-loud vs fail-silent: raise가 default, 삼킴은 명시 정책일 때만. control-flow 신호와 진짜 실패를 타입으로 구분.
- verdict=None과 HTTP status 구분(200인데 verdict=None인 partial-write).

**▸ fix 경로**
- M7: Pidna.lean에 `set_option warningAsError true`(또는 lakefile leanOptions) → sorry→error→exit≠0. + 핵심 정리 7개에 `#print axioms` allow-list step(sorryAx 발견 시 exit 1). bhgman은 의존 warning 노이즈 때문에 `--iofail` 또는 axiom 게이트만.
- M2: ScoringRefused 예외 신설 + self._http가 (status, body) 반환하게 시그니처 변경(근본원인). 4xx/5xx면 raise, 200이라도 verdict=None이면 raise. run_cycle을 langgraph 패턴(raise default).

**▸ 무작정 함정**
- "lake build green이니 sorry 없다" 믿고 그대로 두거나, build step만 다시 추가해 여전히 exit 0.
- warningAsError를 의존 많은 프로젝트(bhgman apt_functor)에 전역 적용하면 무관한 deprecation warning에 빌드가 죽어 게이트를 도로 끔(mathlib가 --iofail로 우회하는 이유).
- warningAsError만 켜고 #print axioms 빼면 import 깊은 sorry/주입 axiom 놓침.
- self._http가 status 버리는 근본원인 못 보고 _submit_and_judge에만 try/except 덧대면 status 소실로 4xx 못 잡고 partial-write도 못 막음. 무차별 raise/except는 정상 사이클까지 죽이거나 도로 삼킴.

---

## T8 — 퇴행 탐지 · bandit 보상 무결성 · 사전등록 (M3, M6 방법론 측면)

**▸ local에서 훔칠 것**
- `lakatotree/lakatos/quant/metrics.py:71` — **M3 진앙**: `prediction_hits=sum(1 for r in chain if r['verdict'] in PROGRESS_VERDICTS)` (라벨만, `novel_confirmed` 안 봄). 직접 확인됨.
- `lakatotree/lakatos/quant/fertility.py:22` — **이미 올바른 정답 패턴**: `confirmed = sum(... novel_registered and novel_confirmed)` + Wilson 하한. **이 패턴을 prediction_hits로 승격**하면 비대칭 구조소멸. 직접 확인됨.
- `lakatotree/lakatos/verdicts.py:65-70` — PROGRESS_VERDICTS(progressive_conditional·former_canonical 포함=미확증). `force_of(149)` 3치 술어(COUNTS/INCONCLUSIVE/SELF_REPORT). 새 분류축은 여기서만(SSOT).
- `lakatotree/lakatos/programme/heuristic.py:38-48,215` — `realized_reward` Laplace (hits+1)/(attempts+2)=Beta(1,1). hits를 confirmed로, attempts를 registered로.
- `lakatotree/lakatos/quant/laudan.py:166-181` — 규칙② `prediction_hits==0`이 미확증 라벨로 무력화 → degenerating 생존. 인자명을 confirmed_prediction_hits로(시그니처 변경=호출처 전수 강제).
- `lakatotree/.../judgement_service.py:195-217` — M6: register_prediction이 미채점이면 pred_* 무제한 재SET, pred_registered_at은 write-only(submit이 읽지도 비교도 안 함).
- `GIT/deepeval/.../dag/nodes.py` — VerdictNode 라벨→점수 단락차단 게이트.
- `GIT/graphiti/edges.py` — bi-temporal valid_at/invalid_at/created_at 3-timestamp(M6 사후예측 형식).

**▸ 외부에서 가져올 것**
- multi-armed bandit 정전(Lattimore&Szepesvári: reward는 environment-realized, self-report 아님). Registered Reports/preregistration(Nosek 2018, Zahar use-novelty). Laudan 1977(solved=검증된 해결). 신규 repo fetch 불필요(책/논문).

**▸ 기반지식**
- use-novelty(Zahar/Worrall) vs temporal-novelty(Popper): 시각 비교만으론 use-novelty(데이터에 맞춰 빚었는가) 못 막음. judge.py는 이미 novel_sha distinct로 use-novelty 검사.
- Beta-Bernoulli posterior 무결성: success가 confirmed일 때만 regret bound 성립.
- SPRT(Wald) 정초: LLR은 확증 증거에서만 누적.
- bi-temporal(transaction-time 동결 + valid-time 비교).
- Laplace prior(분자+1/분모+2): cold-start 방지, 게이트는 hits 정의에만.

**▸ fix 경로**
- M3: verdicts.py에 직교축(force_of=='COUNTS' ∧ novel_confirmed). metrics.py:71을 `fertility.predictive_fertility(chain)['confirmed']`로 교체. heuristic realized_reward를 confirmed_hits/registered로. laudan 인자명 confirmed_prediction_hits로(전수 수정).
- M6: register_prediction에 `AND e.pred_registered_at IS NULL` 가드(재SET 금지) + submit이 measured_at 받아 `measured_at >= pred_registered_at` 아니면 422 + judge.py novel_sha distinct와 결합(temporal+use 동시강제).

**▸ 무작정 함정**
- "미확증을 안 세면 되겠지"로 metrics.py:71만 라벨 화이트리스트 변경하면 'progressive' 라벨이 영수증 없이 self-report되는 H1 경로로 오염 잔존 + fertility와 SSOT 갈림(drift). 정답은 force_of=='COUNTS' ∧ novel_confirmed 게이트.
- M6을 단일 시각 비교로만 막으면 use-novelty 놓침 + register 무제한 재SET 안 막으면 등록시각 매번 갱신해 비교 무력화.
- Beta(1,1) prior 자리(분자+1/분모+2)를 confirmed 변경하며 같이 손대면 cold-start 붕괴(새 가지 영원히 explore 배제).


---

# 부록 A — finding별 1순위 염탐 + 훔칠 것 + 기반지식

| # | 1순위(local 우선) | 훔칠 메커니즘 | 기반지식 |
|---|---|---|---|
| **H1** | local: lakatotree/server/contexts/tree/judgement_service.py:250-260 (client bool→LakatosEvidence 직삽입 chokepoint) + lakatos/programme/heuristic.py:81 negative_heuristic | negative_heuristic의 집합연산(touched∩hard_core)으로 hard_core_preserved를 도출값화; excess_empirical_content는 judge() Verdict.novel(독립 sha)∧net closure에서 유도; grader를 simple-evals처럼 별도 인자로 분리하고 deepeval arena_g_eval식 저자 마스킹+shuffle로 self-preference 제거; guardrails Validator(별도 pass, on_fail=EXCEPTION) | LLM-judge self-preference bias(Zheng 2023/Panickssery 2024) — 분리만으로 부족, 블라인딩 필수; generator≠verifier |
| **H2** | local: lakatotree/server/contexts/tree/judgement_service.py:110-148 (has_human_verdict=bool(v.human_verdict)) + GIT/phoenix/src/phoenix/db/models.py:1148-1166 (annotator_kind CheckConstraint+user_id FK) | 이미 fetch 중인 args에 a.by/a.kind 추가 SELECT해 '∃ Argument(kind∈{human_attestation,evaluation} ∧ a.by≠author ∧ 권한 통과)' 서버 MATCH로 도출; phoenix annotation 1급 노드 모델(LLM/CODE/HUMAN DB-제약+신원 FK); in-toto DSSE 서명 payload(subject=노드 digest)로 stale/backdating 차단 | 위조불가 증명 = signed attestation + transparency log(Rekor) + content-binding(subject digest); SoD self-approve 금지 |
| **H3** | local: lakatotree/lakatos/longinus.py:27-38 (정규식 _resolve, ==오인+def한줄sha) + bhgman_tool/.../longinus_sha256_daemon.py (서버 재계산→대조→drift 완본) | longinus 정규식을 Python ast SymbolResolver로 교체(get_source_segment로 본문 전체 sha, CPG contents-hash); judge_script sha를 서버가 r.script 내용에서 재계산(harness.py:111 로직 이동); line 231 client-vs-client를 server-vs-server로; scip_adapter.py 재사용으로 스코프-안정 심볼ID | second-preimage vs transport integrity; scope graph 이름해석; CPG 4축(HASH=본문 전체); producer≠attestor |
| **H4** | local: lakatotree/lakatos/programme/agm.py (revision/contraction/HardCoreProtected 게이트 이미 존재; demote_canonical만 안 씀) + server/app.py:642 (allow_hard_core 미전파) | demote_canonical을 revision(contradicts=[old],allow_hard_core)로 재작성→Levi identity 작동+게이트 자동상속; app.py:642에 allow_hard_core 전파; _persist_revision의 removed→former_canonical auto-rejudge 원자 tx는 그대로(영속 공짜); graphiti invalid_at 데이터모델만 차용(LLM 판정 제외) | AGM Levi identity(contract THEN expand); base revision recovery 비성립 정당(Hansson); TweetyProject oracle로 공준 검증 |
| **M1** | local: lakatotree/lakatos/io/rebuild.py:66-67 (_parse_metric(last_out)=measurer==producer) + io/lineage.py (Derivation/manifest 골격) + io/adapters.py:58-130 (OpenLineage) | kind='measurement' Derivation 추가; 마지막 step stdout 대신 완성본 파일만 input으로 받는 별개 측정 step; reprotest식 변주 2회 재실행(cwd/env순서); adapters에 measurer 별개 RunEvent(job.name='measure:<artifact>', ParentRunFacet, dataQuality facet에 metric) | 재현≠반복(reproducible-builds 변주 검증); OpenLineage run lifecycle+facet; Bazel/Nix hermetic(undeclared input=실패) |
| **M2** | local: lakatotree/lakatos/harness.py:63-148 (_build_gate만 fail-loud, _submit_and_judge:145-148 응답 무검사) + GIT/langgraph/.../pregel/_retry.py:631-661 | self._http가 (status,body) 반환하게 시그니처 변경(근본원인=status 소실); 4xx/5xx면 ScoringRefused raise, 200이라도 verdict=None이면 raise; langgraph GraphBubbleUp 'raise가 default, 삼킴은 명시 정책' + silent tear-down 금지 + exc.add_note 추적 | fail-loud vs fail-silent 기본값 역전; verdict=None과 HTTP status 둘 다 가드(partial-write); control-flow 신호와 실패를 타입 구분 |
| **M3** | local: lakatotree/lakatos/quant/metrics.py:71 (라벨만 카운트, 검증됨) + lakatos/quant/fertility.py:22 (이미 올바른 novel_confirmed 게이트, 검증됨) | fertility의 confirmed 패턴을 prediction_hits로 승격(metrics가 predictive_fertility(chain)['confirmed'] 호출); verdicts.py에 force_of=='COUNTS'∧novel_confirmed 직교축; realized_reward를 confirmed/registered로; should_abandon 인자명 confirmed_prediction_hits로(전수 강제); deepeval VerdictNode 라벨→점수 단락차단 | Beta-Bernoulli reward 무결성(success=confirmed일 때만 regret bound); SPRT는 확증 증거에서만; Laplace prior(+1/+2) 자리 보존(cold-start) |
| **M4** | local: lakatotree/server/contexts/tree/writer.py:223-241 (RAISES_QUESTION write=0, read=3) + lakatos/quant/laudan.py (계산층 이미 옳음, 불가침) | writer에 link_raised_questions 추가(MERGE (e)-[:RAISES_QUESTION]->(qn)); graphiti bi-temporal(valid_at/invalid_at)로 질문 열림/닫힘을 시간 사건화; close_question이 invalid_at SET. laudan.py는 절대 손대지 않음(공급층 문제) | M4는 계산층 아닌 KG 공급(writer)층 결함; bi-temporal valid time vs transaction time(status 불린보다 시점쿼리) |
| **M5** | local: omd/omd_server/core.py:858-972 (단일 _cs 임계구역+fence+멱등, 고친 후 코드) + lakatotree/server/contexts/tree/judgement_service.py:195-215 (register_prediction의 정답 단일-statement 가드) | 가드 read를 write의 WHERE로 흡수(register_prediction 형태 답습); kg_tx 첫 op로 WHERE+RETURN, rows 비면 tx 안 예외→409; submit_result MCP에 request_id 멱등(JudgementReceipt MERGE); Neo4j unique constraint/JudgementLock 방어심층; set_verdict도 같은 수술 | Neo4j 단일-statement 원자성 vs 다중-session read/write 경계; TOCTOU check-then-act; fencing token(Kleppmann); at-least-once 멱등; 방어심층 2층 |
| **M6** | local: lakatotree/server/contexts/tree/judgement_service.py:195-215 (무제한 재SET, pred_registered_at write-only) + lakatos/verdict/judge.py:93-95 (dead PredictionLocked/check_registration) | dead PredictionLocked를 submit 경로에 연결; register는 judged_at IS NULL AND pred_registered_at IS NULL일 때만 SET(immutable); submit이 measured_at 받아 measured_at>=pred_registered_at 아니면 422; judge.py novel_sha distinct(use-novelty)와 결합; 강화는 RFC 3161 TST/Rekor inclusion. graphiti valid_at vs created_at 분리 | use-novelty(Zahar) vs temporal-novelty(Popper) — 시각 비교만으론 HARKing 못 막음; OSF frozen+amendment; trusted timestamping(self-report 시각으론 먼저임 증명 불가) |
| **M7** | local: lakatotree/.github/workflows/ci.yml:84-97 (bare lake build+거짓 sorry=0 주석, 검증됨) + formal/Pidna.lean (Rung.derived 타입불변식=sorry 한 줄로 위조) | Pidna.lean에 set_option warningAsError true(외부의존 없어 전역 안전)→sorry→error→exit≠0; 핵심 정리 7개에 #print axioms allow-list step(propext/Classical.choice/Quot.sound 외=exit 1); mathlib4 --iofail/LEAN_ABORT_ON_PANIC; bhgman lean job은 반면교사 | Lean sorry=warning, sorryAx 타입체커 통과, lake build warning에 exit 0; axiom allow-list 감사; warningAsError 전역 적용 함정(의존 warning 노이즈) |
| **M8** | local: lakatotree/lakatos/claim.py:124-144 (_resolved_doubt_ids가 actor 미대조) + lakatos/verdict/argue.py:21-37 (grounded_extension actor-blind) | _resolved_doubt_ids에 resolver.actor≠doubt.actor 검사(같으면 self_resolved 경고+unresolved 유지); AF 구성 전 self-attack 제외(by≠doubt.by일 때만 유효 attack); a.by/ev.actor는 이미 KG 적재됨; NIST RBAC SSD 역할 배타+신원 서명키 바인딩(Sybil 차단) | Dung AF actor-blindness(grounded_extension만으론 자문자답 못 막음); SoD Static/Dynamic; 단발 if문은 Sybil로 우회 |

# 부록 B — fetch_queue (아직 GIT/에 없어 새로 가져올 것, 우선순위)

1. TweetyProject (github.com/TweetyProjectTeam/TweetyProject) — H4 AGM oracle, GIT/에 부재 확인, 손으로 적은 revision()의 success/inclusion/vacuity 공준 검증용 reference. 사실상 유일한 진짜-신규 fetch 필수항
2. in-toto attestation spec + Python ref impl (github.com/in-toto/attestation, in-toto/in-toto) — H2/H3 DSSE 봉투·functionary key SoD. bhgman skill-build-attestation.py가 형태만 부분채택, 스펙/구현은 미반입
3. Sigstore Rekor + Trillian (github.com/sigstore/rekor, google/trillian) + RFC 6962(CT) — M6/H2 append-only Merkle transparency log, inclusion proof로 사후위조 차단 (강화 단계)
4. RFC 3161 TSP / RFC 5816 — M6 신뢰 타임스탬프 토큰(OpenSSL ts로도 가능, 별도 repo 불요지만 사양 확보)
5. OpenLineage spec 1-0-5 문서 (openlineage.io/spec) — M1 run lifecycle+facet 카탈로그. 엔진이 이미 Marquez ship 중이라 의존 0, 사양 문서만
6. reprotest (salsa.debian.org/reproducible-builds/reprotest) — M1 변주 검증(변주 set: cwd/TMPDIR/env순서/locale). 도구 또는 variation set 개념만
7. DVC pipeline 사양 (dvc.org, dvc.yaml metrics:/plots:) — M1 metric을 outs와 분리된 1급 시민으로. adapters.py가 이미 근사 export 중
8. Pact (github.com/pact-foundation) — M9 consumer-driven contract broker actor 분리 모델 (개념 차용, 직접 의존은 선택)
9. TweetyProject 의존 외 나머지 표준문서(AGM 1985 JSL, Gärdenfors 1988, Lakatos MSRP 1970, Zahar 1973, Lattimore&Szepesvári 2020, Nosek 2018 PNAS, Laudan 1977, Kleppmann DDIA Ch.8, Wald 1945) — 코드 아닌 문헌, 학습용

# 부록 C — sequencing (의존성 고려 학습/구현 순서)

1. 0. 척추 먼저: p333/crates/ltdd/src/lib.rs 정독으로 '제출값=주장, 재유도값=판관' + Inconclusive 3값을 모든 finding의 공통 원칙으로 체화. 이게 H3·H2·M1·M2·M6·M9를 한 사상으로 묶는다.
2. 1. T1(H3 영수증 재유도)을 T2(심볼 바인딩)보다 *먼저*가 아니라 *함께* 풀되, 의존 순서는 T2의 ast/CPG contents-hash 지식이 T1의 '무엇을 sha할 것인가'(=심볼 본문 전체)를 정의하므로 T2 심볼바인딩 지식을 T1 내용주소보다 먼저 확보해야 H3가 '엉뚱한 심볼의 진짜 sha=거짓 영수증' 함정을 피한다. → T2 ast/scip_adapter → T1 서버 재계산 순.
3. 2. T6(M5 TOCTOU)은 register_prediction의 단일-statement 가드 패턴을 손에 익히는 게 T1의 H3 서버측 sha 가드와 같은 Cypher 트랜잭션에 들어가므로, T6를 T1 H3 server-side 구현 직전에 학습(둘이 같은 write 트랜잭션을 공유). omd/CONCURRENCY.md→core.py→store.py 순.
4. 3. M6은 H3(서버 재유도)와 M5(원자 가드)에 의존: pred_registered_at을 immutable·서명 타임스탬프로 만들려면 먼저 서버가 값을 재유도(H3)하고 register WHERE를 원자화(M5)해야 한다. → H3·M5 후 M6(T1+T8 결합).
5. 4. T8(M3 bandit/퇴행)은 H1(질적 self-report)과 같은 오염원(라벨=self-report) 공유 → H1의 'force_of==COUNTS ∧ novel_confirmed' 게이트 개념을 먼저 세우고 M3 prediction_hits를 fertility 패턴으로 통일. T8 M3는 fertility.py가 이미 정답이라 비교적 독립적이나, H1 게이트 어휘 정립 후가 깔끔.
6. 5. T4(H1·H4 AGM)는 TweetyProject fetch(fetch_queue #1)를 기다림. fetch 전이라도 agm.py·negative_heuristic·judge.py로 H1 bool→결정 치환과 H4 demote→revision 재작성은 착수 가능(코드 70% 존재). TweetyProject는 property-test oracle로 *검증 단계*에 합류. 따라서 T4 구현은 fetch와 병렬, 검증만 fetch 의존.
7. 6. T5(H1·H2·M8 독립평가자)는 H1(질적 grader)을 T4의 negative_heuristic 도출과, H2를 T1의 attestation과 공유. M8(claim.py actor 대조 + argue.py self-attack 제외)은 비교적 독립이라 조기 착수 가능. in-toto/Rekor(fetch_queue #2,#3)는 H2 강화 단계에만 필요.
8. 7. T3(M1·M4·M9)는 OpenLineage 사양(fetch_queue #5)과 reprotest(#6) 학습 후. M4(writer RAISES_QUESTION)는 사양 의존 없이 즉시 가능하고 laudan 불가침 원칙만 지키면 됨 → M4 먼저, M1/M9는 사양 학습 후.
9. 8. T7(M7·M2)는 가장 독립적: M7은 Lean warningAsError/#print axioms로 즉시(mathlib4 사양 참고), M2는 harness self._http 시그니처 변경+langgraph 패턴으로 즉시. 단 M2의 ScoringRefused는 T6/T1의 409/422 응답과 일관돼야 하므로 그 응답 계약 확정 후가 좋다. → 마지막 단계 또는 병렬.
10. 9. 전 구간 RED-first: 각 테마의 trap_if_skipped가 곧 음성 테스트 명세(위조 sha 통과·동시 submit 이중채점·sorry green·미확증 progress·자문자답 resolved 등). 구현 전 이 실패 테스트를 먼저 깨라.
