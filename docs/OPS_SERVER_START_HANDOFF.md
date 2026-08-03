# LakatoTree 서버 기동 — 인프라 핸드오프 (2026-08-02 갱신)

> 목적: `:55170` 서버를 띄워 `lakatos.cli`와 HTTP/MCP의 정식 검증 경로를 사용한다.
> 이 문서는 특정 호스트, VPN, 고정 IP를 배포 정본으로 삼지 않는다. 두 launcher 모두
> 저장소 위치나 자격증명을 추정하지 않으며, 현재 배포의 사용자 소유 `0600` canonical env가
> 모든 target을 명시해야 한다. 과거 2026-06-20 토폴로지 관측은 현재 운영 지시가 아니다.

## 배치 위치와 요구사항

서버 프로세스는 canonical env에 적힌 Neo4j와 MongoDB에 직접 연결할 수 있는 호스트에서만
기동한다. Critique/history 경로를 열려면 같은 env의 PostgreSQL target과 검증된 storage
predeploy receipt도 필요하다. MCP가 별도 네트워크 경로로 DB에 닿는다는 사실은 서버 자체의
직접 연결성을 증명하지 않는다.

| 의존성 | 필요 | 비고 |
|---|---|---|
| **Neo4j** (graph SoT) | ✅ 필수 | canonical env의 `NEO4J_URI`, `NEO4J_DATABASE`, runtime credential로 직접 도달 가능해야 함 |
| **Mongo** (artifacts) | ✅ 필수 | canonical env의 `LAKATOS_MONGO_URI`로 직접 도달 가능해야 함 |
| **PostgreSQL** (append-only history) | △ 기능별 | 없어도 core Neo4j/Mongo 조회·일반 비원장 동작은 기동. 단 verdict·prediction·test·cycle·critique·AGM 등 모든 원장 기반 mutation은 exact storage audit와 writer lease가 green이 되기 전 **mutation 전에 503**으로 닫힘. 런타임 PG 단절은 이미 원자적으로 생성된 KG outbox가 보존 |
| Python deps (uvicorn/fastapi/neo4j/psycopg2/cryptography) | ✅ | 배포 환경에서 `python -m pip install -e ".[server]"` 또는 predeploy 전용 `.[storage]` 설치 |

## 기동 절차 (predeploy 먼저, 서버 시작은 마지막)

원장 기반 writer를 열 배포에서는 실행 중인 서버에 나중에 `export`해도 아무 효과가 없다. 모든
storage pin을 정식 env 파일에 먼저 영속화하고, predeploy 영수증까지 추가한 뒤 서버를 시작하거나
재시작한다. 아래의 live-fence verifier는 저장소가 제공하는 echo 예제가 아니라, 실제 writer lease를
소유하고 exact readback하는 별도 운영 authority여야 한다.

```bash
cd <lakatotree>
install -d -m 700 ~/.config/lakatotree
touch ~/.config/lakatotree/server.env
chmod 600 ~/.config/lakatotree/server.env

# 기존 자격증명과 target 설정도 이 파일에 기록한다.
# NEO4J_URI / NEO4J_DATABASE / NEO4J_USER / NEO4J_PASSWORD
# LAKATOS_MONGO_URI
# LAKATOS_PG_HOST / PORT / USER / PASSWORD / DB
# LAKATOS_API_TOKEN=<operator-secret>   # 수동 reconcile은 open posture에서 거부됨

# migration authority는 이 runtime env 파일에 영속화하지 않는다. predeploy one-shot
# process에만 아래 여섯 값을 주입하며, 모든 runtime launcher는 발견 즉시 거부한다.
# LAKATOS_STORAGE_PG_MIGRATION_DSN=<single host + hostaddr + verify-full + SCRAM>
# LAKATOS_STORAGE_PG_MIGRATION_USER=<dedicated migrator, runtime과 달라야 함>
# LAKATOS_STORAGE_PG_MIGRATION_PASSWORD=<one-shot secret>
# LAKATOS_STORAGE_NEO4J_MIGRATION_URI=<bolt+s 또는 neo4j+s>
# LAKATOS_STORAGE_NEO4J_MIGRATION_USER=<dedicated migrator, runtime과 달라야 함>
# LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD=<one-shot secret>

# PostgreSQL bootstrap-owned large-object ACL은 앱 migration으로 바꿀 수 없다.
# exact target DB에 direct bootstrap-superuser 새 세션으로 먼저 실행한다.
# 비밀은 argv/runtime env/repository에 넣지 않고 보호된 operator auth를 사용한다.
psql -X --set=ON_ERROR_STOP=1 \
  --dbname lakatos \
  --file /absolute/path/postgresql_large_object_acl_v1.sql
# PG 16/17 전용이며 DB마다 적용한다. restore/initdb/major upgrade 뒤 재검증한다.
# managed PG가 이 direct authority를 제공하지 않으면 NOT_READY이며 owner로 우회하지 않는다.

# verifier는 /usr/bin/env shebang을 쓸 수 없다. 직접 절대 interpreter 또는 독립 실행파일만 허용한다.
lakatotree-storage-predeploy --inspect-verifier \
  --fence-verifier </absolute/path/to/live-fence-verifier>
# 출력의 sha256은 verifier 파일만의 hash가 아니라 직접 interpreter까지 묶은 execution identity다.

# 다음 세 값을 server.env에 먼저 기록한다.
# LAKATOS_STORAGE_ENVIRONMENT=<env>
# LAKATOS_STORAGE_FENCE_VERIFIER_SHA256=<inspect-verifier-output-sha256>
# LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX=<32-byte-raw-Ed25519-public-key-lowercase-hex>

set -a
. ~/.config/lakatotree/server.env
set +a
lakatotree-storage-predeploy --inspect-target
# 별도 drain authority가 위 target/operation과 listener_count=0, replica_count=0을 묶은
# writer-drain-v2.json을 발행한 뒤에만 다음 단계를 실행한다.
lakatotree-storage-predeploy --apply \
  --environment "$LAKATOS_STORAGE_ENVIRONMENT" \
  --drain-receipt </absolute/path/to/writer-drain-v2.json> \
  --fence-verifier </absolute/path/to/live-fence-verifier> \
  --fence-verifier-sha256 "$LAKATOS_STORAGE_FENCE_VERIFIER_SHA256" \
  --receipt-out </absolute/path/to/new-write-once-receipt.json>

# apply 출력의 receipt_file_sha256과 절대경로를 같은 server.env에 추가한다.
# LAKATOS_STORAGE_PREDEPLOY_RECEIPT=</absolute/path/to/new-write-once-receipt.json>
# LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256=<receipt_file_sha256>

# 별도 audit principal과 서로 다른 PG/Neo attestor key로 predeploy phase bundle을
# 만든다. 서버 시작 직전 같은 정책으로 startup phase bundle을 만들고, startup 요청은
# predeploy bundle의 raw-file SHA를 previous_phase_bundle로 묶어야 한다.
# lakatotree-storage-audit --request ... --request-sha256 ... \
#   --postgresql-signing-key ... --neo4j-signing-key ... --output ...
# 두 bundle의 pure verifier 결과가 ACCESS_PAIR_VERIFIED가 아니면 시작하지 않는다.

# runtime writer authority는 historical drain/fence authority와 다른 키와
# 다른 exact executable이어야 한다. signer private key는 server.env나 앱에 넣지 않는다.
# LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER=</absolute/path/to/runtime-authority>
# LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256=<execution-identity-sha256>
# LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX=<distinct-raw-Ed25519-public-key>

# 터미널 A 또는 service manager에서 새 프로세스가 다섯 pin을 모두 읽도록 시작/재시작한다.
# 이 명령은 foreground uvicorn으로 exec되므로 이 터미널은 서버에 계속 점유된다.
LAKATOS_ENV_FILE=~/.config/lakatotree/server.env bash server/run_internal.sh
```

서버 프로세스가 `/healthz`에 응답하면 **별도 터미널 B**에서 canonical env를 다시 읽고 후속
검증을 실행한다. pending intent가 있으면 `/readyz`는 의도적으로 503이므로, core liveness 확인 →
operator 인증 복구 → contract refresh → 최종 readiness 순서를 지킨다. 두 POST 응답은 모두
`ok=true`, 마지막 `/readyz`는 HTTP 200인지 확인한다.

```bash
set -a
. ~/.config/lakatotree/server.env
set +a
curl -fsS http://127.0.0.1:55170/healthz
curl -fsS -X POST \
  -H "Authorization: Bearer $LAKATOS_API_TOKEN" \
  http://127.0.0.1:55170/api/ops/reconcile-outbox
curl -fsS -X POST \
  -H "Authorization: Bearer $LAKATOS_API_TOKEN" \
  http://127.0.0.1:55170/api/ops/critique-history-contract
curl -fsS http://127.0.0.1:55170/readyz
curl -fsS http://127.0.0.1:55170/api/ops/runtime-authority-snapshot
```

이 경로는 fresh database 생성과 legacy upgrade를 같은 migration/readback으로 처리한다. drain
영수증은 실제 PostgreSQL/Neo4j target, 설치 artifact, migration content에 묶이며 적용 경계마다
재검증된다. fence verifier는 stdin의 nonce/target/operation/lease challenge를 실제 writer-lease
authority에서 exact readback하고, 같은 nonce와 짧은 유효기간을 가진
`lakatotree-writer-fence-verification/v2` JSON만 stdout으로 반환해야 한다. authority는 요청을
그대로 서명하는 oracle이 아니라 현재 lease/target/operation/drain/writer 상태를 독립 검증해야 한다.
서명 메시지는 ASCII schema 문자열 + NUL + key-sorted compact UTF-8 JSON body이며 signature는 제외한다.
서명과 raw public key는 lowercase hex, receipt fingerprint는 raw 32-byte public key의 SHA-256이다.
v1 fence 및 v3 predeploy receipt fallback은 없고, key rotation은 기존 receipt를 무효화하므로 predeploy를
다시 실행한다. private key는 verifier/server env/repository가 아니라 외부 authority/HSM에만 둔다. 적용 결과 파일은
read-only로 봉인되며 서버는 별도 배포 설정에 핀한 raw-file SHA, 현재 artifact, migration,
PostgreSQL cluster/database, Neo4j database identity를 모두 다시 맞춘 뒤에만 critique를 연다.
v5 receipt의 `neo4j.payload_normalization`은 outbox의
`id/tree/op/node_tag/payload` 투영을 변경 전후 재스캔해 domain-separated SHA-256과 행 수,
CAS 갱신 수로 봉인한다. 무변경 실행도 두 번 스캔한다. 이 값은 해당 receipt에 묶인 상태 증명이지
독립 감사 원장은 아니다. Neo4j 변경 뒤 receipt 발행 전에 프로세스가 죽으면 재실행은 최종 정본의
무변경 상태를 증명하지만, 첫 시도의 역사적 delta까지 복구하지는 못한다. 해시는 기밀화 수단도 아니다.
verifier는 실행 때 private one-use copy로 옮겨지므로 원래 경로 옆의 상대 파일에 의존하면 안 된다.
script라면 직접 shebang interpreter도 execution identity에 포함되고, PATH/PYTHONPATH 등은 정리된다.
실제 production drain/canary authority가 준비되지 않았으면 이 절차를 production-ready로 간주하지 않는다.
coordinator는 이제 runtime과 다른 strict migration profile만 받아들이고 runtime launcher는 모든
migration authority 변수를 거부한다. 별도 signed storage-audit surface는 선언된 NOLOGIN owner/SET-only
migrator 정책, runtime/audit 분리, Neo4j custom-role projection을 서명된 관찰에 묶고 audit actor의
read-only 상태를 검증한다. 이 단계만으로 non-audit 역할의 least-privilege 적합성을 승인하지 않으며,
계정·TLS 인증서·Enterprise 라이선스도 만들지 않는다. 실제 production PG 역할과 CA, Neo4j Enterprise
custom role, 서로 다른 audit principal/attestor가 배치되어 predeploy/startup bundle을 발행하기 전에는
apply/기동을 승인하면 안 된다.
Community Neo4j의 RBAC 부재를 성공으로 간주해서도 안 된다.
Neo4j strict audit은 concrete application DB와 감사된 2026.03~2026.06 Enterprise 의미만
허용한다. PUBLIC 기본 권한을 먼저 revoke하고 runtime/migrator는 app DB ACCESS만, audit은
app DB와 system DB ACCESS 및 exact mutable SHOW/procedure 권한만 가진다. undeclared active
admin/break-glass role도 실패다. system authorization scan은 writer `lastCommittedTxn` 앞뒤가
같아야 하지만, 이것을 PG+Neo 전체의 원자적 snapshot으로 해석하면 안 된다. 현재 Enterprise
실환경 vocabulary 영수증이 없으므로 이 단계는 계속 NOT_READY다.
예외는 명시 선언한 development profile 하나뿐이다. policy/request의
`environment=development`면 PG host로 loopback 대신 literal IP 하나(예: LAN IP)를 허용하고,
live 서버가 실제 Community(2026.01~2026.06)일 때만 RBAC 검사 대신 Community 전용 fact set
(`community_semantics=true`, `rbac_available=false`, native-only auth, 세 principal 존재,
system authority 안정성, exact `read_query_count`)을 서명·검증한다. 이 경우도 audit principal의
read-only는 주장하지 않으며, 결과는 `ACCESS_PAIR_VERIFIED`지만 `deployment_status`가
`DEVELOPMENT_ONLY`, `production_ready`는 항상 false로 모든 서명 산출물에 정직하게 기록된다.
runtime writer authority challenge도 같은 선언 환경을 그대로 물려받아 서명·검증되며(정책·
receipt·challenge 환경이 정확히 일치하지 않으면 fail-closed), development snapshot 역시
`DEVELOPMENT_ONLY`로만 표기된다. 유효기간도 환경별이다: production은 access attestation
5분·snapshot 수명 최대 300초 그대로이고, development만 access pair 6시간(21600초)·
snapshot 수명 최대 1시간(3600초, 관측 후 30초 신선도와 commit margin은 동일)을 허용한다.
홈 운영은 bundle 재수집 없이 몇 분 간격의 주기적
`POST /api/ops/critique-history-contract`(예: systemd timer)로 runtime proof만 갱신하면
bundle 유효기간 내내 ledger가 열려 있고, 6시간 창의 갱신은 bundle 재수집 + env 재핀 +
재시작으로 한다. production policy는 지금과 동일하게 Enterprise 의미만 허용하고,
DEVELOPMENT_ONLY pair/snapshot은 production approval/L3 경로 어디에서도 승인 근거가
되지 않는다.
서명은 두 datastore key 아래 네 개의 domain-separated signature이며, verifier는 stateless다.
predeploy/startup nonce 재사용은 거부하지만 동일한 유효 pair의 만료 전 재검증은 막지 않는다.
그 다음 앱은 별도 runtime authority에 fresh nonce challenge를 보내 current boot, full Git 또는
wheel RECORD artifact, operation/target, access evidence, singleton worker, PG backend와 Neo4j
lease token digest/generation을 함께 서명받는다. 이 proof의 scope는 critique-history ledger뿐이며
generic mutation이나 배포 승인을 뜻하지 않는다. PostgreSQL ledger transaction은 advisory lock을
가진 동일 세션에서 실행된다. snapshot 만료·lease/boot drift·명시적 invalidation 시 원장 write와
readback endpoint가 즉시 fail-closed한다. read-only collector나 GET endpoint는 proof를 갱신하지 않는다.
런타임 snapshot은 최대 5분의 짧은 운영 창만 허용한다. 자동 갱신 루프는 없으며 만료 후에는 인증된
`POST /api/ops/critique-history-contract`를 다시 실행해 외부 authority의 새 snapshot을 받아야 한다.
런타임 launcher는 migration 및 readiness-audit credential 환경변수 유입을 거부하며,
`NEO4J_DATABASE`를 명시적으로 요구한다.

per-receipt Gate 4를 쓰는 배포는 C1 source closure와 Python, 외부 time-observation
authority executable 및 DID의 7개 pin을 시작 전에 전부 설정한다. C1은 private copy를
`-I -S -B`로 실행하고 자체 UTC 시각으로 만료를 판정한다. authority는 앱과 같은 키·프로세스가
아니라 별도 운영 주체/HSM 또는 보호된 서비스가 소유해야 한다. repository 테스트의 deterministic
script/key는 이 운영 독립성을 증명하지 않으며 production env에 복사하면 안 된다. 설정이 없거나
부분적이면 permanent read는 Gate 3 L2에 머무른다; receipt chain L0로 오판하지 않는다.

모든 live evidence가 모인 뒤에도 자동 승인하지 않는다. 별도 운영자는 canonical live review와
approval policy를 독립 채널에 pin하고, 앱이 보유하지 않는 approver key로 정확한 review receipt를
발행한다. `lakatotree-production-approval-verify`는 그 세 파일과 raw SHA를 오프라인 검증할 뿐이며
`APPROVED_NOT_APPLIED`를 배포·재시작·`/readyz`로 전달하지 않는다. 실제 receipt가 없으면 결과는
계속 `NOT_READY`다.
런처와 `/readyz`는 schema를 쓰거나 append-only ledger 전체를 매 probe마다 스캔하지 않는다.
`/healthz`는 core liveness, `/readyz`는 PG와 캐시된 exact storage authority까지 요구하는 traffic readiness다.
캐시는 프로세스 로컬이므로 `run.sh`/`run_internal.sh`는 현재 `UVICORN_WORKERS=1`만
허용한다. 스토리지 복구 후에는 단일 워커의 명시적 contract refresh를 실행하거나
모든 단일-워커 인스턴스를 재시작한다. 공유 signed audit generation 없이 multi-worker로
늘리면 `/readyz`와 원장 mutation authority가 worker별로 갈리므로 launcher가 fail-closed한다.

무토큰 기동은 loopback만 허용한다. 외부 주소/hostname은 `LAKATOS_API_TOKEN`이 없으면 preflight에서
종료하며, `--host`/`--fd`/`--uds`와 `UVICORN_FD`/`UVICORN_UDS`로 listener 정책을 우회할 수 없다.
원격 CLI의 `LAKATOTREE_URL`에는 실제 서버의 승인된 주소를 쓴다. 외부 bind에는 API token이
필수이며 방화벽/TLS/ingress 정책은 이 launcher 밖의 배포 책임이다.

`server/run.sh`는 canonical env 파일이 반드시 존재해야 하는 운영 경로다.
`server/run_internal.sh`는 같은 파일이 있으면 동일하게 검증해 사용하고, 파일이 없을 때만
호출자가 명시적으로 주입한 현재 환경을 허용하는 내부/테스트 경로다. 둘 다 고정 IP, 다른
checkout의 `.env`, Claude 설정, 특정 컨테이너 이름을 읽지 않는다.

## 기동 확인

```bash
curl -fsS http://127.0.0.1:55170/readyz            # full readiness 200 기대
curl -fsS http://127.0.0.1:55170/api/tree/LakatosTree_VerdictProvenanceGate_20260620 | python3 -m json.tool | head
```

서버가 뜨면 CLI 풀 엔진 가용:
```bash
export LAKATOTREE_URL=http://127.0.0.1:55170
python -m lakatos.cli metrics     LakatosTree_VerdictProvenanceGate_20260620   # Bayes/Laudan/fertility/FDR
python -m lakatos.cli certificate LakatosTree_VerdictProvenanceGate_20260620 asymmetric_ceiling
python -m lakatos.cli leaderboard LakatosTree_VerdictProvenanceGate_20260620,LakatosTree_OOPTDD_20260616
python -m lakatos.cli stack       LakatosTree_VerdictProvenanceGate_20260620   # Popper/Bayes/Laudan 투표
```

## 서버 없이 가능한 범위

별도 승인된 Neo4j/MCP 읽기 경로가 있다면 조회와 수동 감사에는 사용할 수 있다. 하지만 그 경로는
LakatoTree 서비스의 mutation, receipt mint, PostgreSQL history projection, writer fencing을 대체하지
않는다. 서버 없이 수행한 ad-hoc Cypher write를 정식 엔진 판정으로 간주하지 않는다.

## 정식 게이트와 남은 production blocker

일반 `add_node`/bulk writer는 `_reject_scored`를 통해 scored/scripted/engine verdict 직접 주입을
거부한다. 예측은 `register_prediction`, 측정은 `submit_test_result`, 판정 변경은 `set_verdict`의
receipt/history 경로를 사용한다. 운영자가 ad-hoc Cypher로 이 경계를 우회하면 정식 판정이 아니다.

현재 storage predeploy와 runtime fence가 코드 경계를 강화했어도 production 승인 요건은 아직
완료되지 않았다. 별도 drain/canary authority, PostgreSQL owner/migrator/runtime 최소권한 분리,
Neo4j Enterprise custom-role 분리, 실제 actor/owner/ACL receipt 및 startup exact readback을 외부
배포에서 구현하고 검증해야 한다. 또한 writer token은 receipt/history 핵심 mutation을 직렬화하지만
모든 generic tree/programme mutation을 전역 standby read-only로 만드는 권위는 아니다.
