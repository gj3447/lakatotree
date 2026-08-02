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

원장 기반 writer를 열 배포에서는 실행 중인 서버에 나중에 `export`해도 아무 효과가 없다. 다섯 개의
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
v4 receipt의 `neo4j.payload_normalization`은 outbox의
`id/tree/op/node_tag/payload` 투영을 변경 전후 재스캔해 domain-separated SHA-256과 행 수,
CAS 갱신 수로 봉인한다. 무변경 실행도 두 번 스캔한다. 이 값은 해당 receipt에 묶인 상태 증명이지
독립 감사 원장은 아니다. Neo4j 변경 뒤 receipt 발행 전에 프로세스가 죽으면 재실행은 최종 정본의
무변경 상태를 증명하지만, 첫 시도의 역사적 delta까지 복구하지는 못한다. 해시는 기밀화 수단도 아니다.
verifier는 실행 때 private one-use copy로 옮겨지므로 원래 경로 옆의 상대 파일에 의존하면 안 된다.
script라면 직접 shebang interpreter도 execution identity에 포함되고, PATH/PYTHONPATH 등은 정리된다.
실제 production drain/canary authority가 준비되지 않았으면 이 절차를 production-ready로 간주하지 않는다.
또한 현재 coordinator는 migration과 runtime DB principal을 아직 분리하지 않는다. 따라서 production에서는
다음 access-contract가 구현·검증되기 전까지 apply/기동을 승인하면 안 된다: PostgreSQL NOLOGIN owner +
별도 migrator/runtime, runtime table `SELECT/INSERT`와 sequence `SELECT/USAGE`만 허용, Neo4j Enterprise
custom role로 runtime graph write와 migrator constraint-create를 분리, 양 저장소의 실제 actor/owner/ACL을
receipt와 startup readback에 결합. Community Neo4j의 RBAC 부재를 성공으로 간주해서도 안 된다.
런타임 launcher는 migration credential 환경변수 유입을 거부하며, `NEO4J_DATABASE`를 명시적으로 요구한다.
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
