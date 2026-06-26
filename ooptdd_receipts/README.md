# ooptdd_receipts — 설계감사 13건의 ooptdd-loop 영수증

LakatoTree 설계감사(2026-06-25, [docs/DESIGN_AUDIT_PROM_20260625.md](../docs/DESIGN_AUDIT_PROM_20260625.md)
+ `examples/design_audit_20260625_programme.py` dogfood)에서 닫은 **13건**(H1~H4, M1~M9)을
**ooptdd-loop 정식 영수증**으로 박제한다.

엔진 자체 dogfood(LTDD/PROM, `examples/design_audit_20260625_programme.py` → 13/13 progressive)와
**이중 검증**: 여기 영수증은 pytest pass 가 아니라 **ooptdd 방법론** 기준이다 —
- **R02 (positive trace arrival)**: requirement 는 기대 구조화 이벤트가 correlation id 로 *도착*해야 green.
- **R10 (Longinus ReferenceSite)**: 각 requirement 의 `must_emit` 이벤트가 emit site(`verify` 심볼)에 bound.
- **R14 (done = green + bound + rules)**.

## 구조

```
ooptdd_receipts/
  run_all.py            # CI 엔트리 — 13개 spec 일괄 run, 하나라도 RED 면 exit 1
  <F>/<f>_receipt.py    # emit-adapter: 실제 고쳐진 lakatos/server 코드를 in-process 구동 + 구조화 이벤트 ship
  <F>/requirements.yaml # ooptdd spec: gate(이벤트 count) + longinus(must_emit → verify)
```

각 adapter 의 `verify(backend, cid)` 는 **실모듈을 import 해 구동**(재구현 금지)하고, **음성 오라클**
(그 finding 의 결함을 주입하면 RED 가 되는 케이스)을 포함한다. 예:
- H3 — `longinus.symbol_body_sha` 가 심볼 본문에서 sha 재유도; 부재 심볼은 None(거짓 영수증 거부).
- M3 — `CONFIRMED_NOVEL_PROGRESS=PROGRESS_VERDICTS` 로 결함 복원 시 leaf 가 거짓 생존 → RED.
- M5 — CAS claim 0행(동시 submit) → 409; 가드 cypher 부재 시 RED.
- (전체 매핑은 각 `requirements.yaml` 의 description 참조.)

규율: **이벤트 리터럴은 adapter 에만** — 엔진 코드(`lakatos/`, `server/`)는 불변(ooptdd object-design 규칙).

## 실행

`ooptdd_loop` + (server.* finding 용) `fastapi` 가 있는 env 가 필요하다. 가장 쉬운 길은
이웃 `ooptdd-loop` 저장소의 venv:

```bash
# repo 루트(lakatotree/)에서
<WORKSPACE>/PROJECT/PI/ooptdd-loop/.venv/bin/python ooptdd_receipts/run_all.py
# → 13/13 green 이면 exit 0
```

개별 finding 만:

```bash
cd ooptdd_receipts/H3 && ooptdd-loop run requirements.yaml   # root: "." = 이 디렉토리
```

> 참고: `memory` 백엔드는 per-run ephemeral 이라 사후 `ooptdd-loop verify <cid>` 단독 호출은
> `absent` 를 반환한다(영수증 결함 아님). 권위는 `run`/`run_all.py` 출력이다.

## CI 배선(권장)

lakatotree CI 에 다음 잡을 추가하면 13 영수증이 상시 재검증된다(엔진 코드가 회귀해 결함이 돌아오면
해당 음성 오라클이 RED → 잡 실패):

```yaml
  ooptdd-receipts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |   # ooptdd-loop 체크아웃 + 설치(ooptdd_loop + fastapi)
          pip install -e ../ooptdd-loop fastapi
          python ooptdd_receipts/run_all.py
```
