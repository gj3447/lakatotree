# LakatoTree 서버 기동 — 인프라 핸드오프 (2026-06-20)

> 목적: `:55170` 서버를 띄워 `lakatos.cli`(metrics/certificate/directions/stack/lifecycle/
> leaderboard/trust)와 MCP `add_node`/`register_prediction` 정식 게이트 경로를 쓸 수 있게 한다.
> CLI 는 서버 위 얇은 층(`lakatos/cli.py:1` "서버 API(:55170) 위의 얇은 조작층")이라 **서버가
> 전제**다. kg-neo4j MCP(Cypher)만으로도 대부분 조회/계산은 되지만, 풀 엔진은 서버 경유.

## 왜 이 박스(`<WORKSPACE>` = consumer/consumer_a)에선 못 띄우나

서버 코어는 **Neo4j(graph SoT)** 에 붙어야 하고, 그건 dgx 의 `bolt://100.64.0.3:7687` 이다
(`server/run_internal.sh:5`). 이 호스트는 **tailscale 미설치 → 100.64.0.3 도달 불가**
(`ping 100.64.0.3` 100% loss). kg-neo4j **MCP** 는 동작하지만 그건 *MCP 호스트*가 Neo4j 에
접근하는 것이지 이 박스가 직접 bolt 로 닿는 게 아니다. 그래서 서버는 **tailscale 로 dgx 에
닿는 호스트(설계상 macmini)** 에서 띄운다.

## 어디서 띄우나 — 요구사항

| 의존성 | 필요 | 비고 |
|---|---|---|
| **Neo4j** (graph SoT) | ✅ 필수 | `bolt://100.64.0.3:7687` (dgx). 도달 가능한 호스트에서만 기동 |
| **Mongo** (artifacts) | ✅ 필수 | `mongodb://…@100.64.0.3:27017` (dgx) |
| **PostgreSQL** (append-only history) | ⬜ 선택 | 내부망 미가동 시 **lazy degrade** — history append만 best-effort, core Neo4j ops 정상 (`run_internal.sh` 주석) |
| Python deps (uvicorn/fastapi/neo4j) | ✅ | `lakatotree/.venv` 에 이미 있음(확인됨) |

## 기동 절차 (정식 경로 = `run_internal.sh`)

tailscale 로 dgx 에 닿는 호스트의 `lakatotree/` 에서:

```bash
cd <lakatotree>
bash server/run_internal.sh          # → uv run uvicorn --app-dir server app:app --host 127.0.0.1 --port 55170
```

`run_internal.sh` 가 박아둔 기본 creds (다르면 export 로 오버라이드):
```bash
export NEO4J_URI="bolt://100.64.0.3:7687"   NEO4J_USER="neo4j"   NEO4J_PASSWORD="<dgx neo4j pw>"
export LAKATOS_MONGO_URI="mongodb://mongo:<pw>@100.64.0.3:27017/?authSource=admin"
# PG 쓸 거면(선택): LAKATOS_PG_HOST/PORT/USER/PASSWORD/DB (없으면 history degrade)
```

> ⚠️ `server/run.sh`(run_internal 아님)는 **다른 셋업용**이다 — `<WORKSPACE>/vision3d_test/.env`
> 를 source 하고 `~/.claude/settings.json['env']['NEO4J_*']` + 로컬 docker 컨테이너 `postgresql`
> (포트 55100)를 가정한다. 이 환경엔 그 .env 도, 그 컨테이너 이름(여긴 `pg-host`)도 없으니
> **run.sh 말고 run_internal.sh 를 써라.**

## 기동 확인

```bash
curl -s http://127.0.0.1:55170/api/health           # 200 기대
curl -s http://127.0.0.1:55170/api/tree/LakatosTree_VerdictProvenanceGate_20260620 | python3 -m json.tool | head
```

서버가 뜨면 CLI 풀 엔진 가용:
```bash
export LAKATOTREE_URL=http://127.0.0.1:55170
python -m lakatos.cli metrics     LakatosTree_VerdictProvenanceGate_20260620   # Bayes/Laudan/fertility/FDR
python -m lakatos.cli certificate LakatosTree_VerdictProvenanceGate_20260620 asymmetric_ceiling
python -m lakatos.cli leaderboard LakatosTree_VerdictProvenanceGate_20260620,LakatosTree_OOPTDD_20260616
python -m lakatos.cli stack       LakatosTree_VerdictProvenanceGate_20260620   # Popper/Bayes/Laudan 투표
```

## 서버 없이 지금 가능한 것 (kg-neo4j MCP / Cypher)

서버를 못 띄우는 동안에도 **데이터는 전부 consumer Neo4j 에 있으므로** MCP Cypher 로:
- leaderboard(progress_rate 비교) · genealogy(BRANCHED_FROM/DERIVED_FROM) · frontier · provenance audit(`verdict_source`) — 실증됨.
- 풀 metrics 의 Bayes credence / Laudan PSR / multiplicity FDR 는 Cypher 로 *근사* 계산 가능(작업 b).

## 정식 게이트(self-report 차단) 주의

서버 `POST /api/tree/{}/node` 의 `add_node` 는 `e.verdict=$verdict` 를 **judge() 게이트 없이**
자유문자열로 쓴다(`server/contexts/tree/writer.py:59-63`, 2026-06-20 자체 적대감사 TODO). 즉 서버를
띄워도 verdict 직접 주입이 가능하므로, **verdict 는 반드시 `examples/*_programme.py` 의 judge()
산출값으로 넣고 `verdict_source` 에 `executed-not-asserted` 출처를 박을 것** (VerdictProvenanceGate
트리는 이미 그렇게 등록됨). writer 의 SCRIPTED_VERDICTS 게이트가 닫히기 전까진 이 규율로 우회 방지.
```
