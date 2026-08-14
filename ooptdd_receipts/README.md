# ooptdd_receipts — 동결된 ooptdd-loop LTS 영수증 코퍼스

LakatoTree 설계감사(2026-06-25, [docs/DESIGN_AUDIT_PROM_20260625.md](../docs/DESIGN_AUDIT_PROM_20260625.md)
+ `examples/design_audit_20260625_programme.py` dogfood)에서 닫은 **13건**(H1~H4, M1~M9)을
**ooptdd-loop 정식 영수증**으로 박제한 데서 시작했다. 이 디렉터리는 현재 역사 증거의 LTS
감사 코퍼스이며, 일반 제품 변경의 완료 조건이나 새 영수증의 기본 목적지가 아니다.

엔진 자체 dogfood(LTDD/PROM, `examples/design_audit_20260625_programme.py` → 13/13 progressive)와
**이중 검증**: 여기 영수증은 pytest pass 가 아니라 **ooptdd 방법론** 기준이다 —
- **R02 (positive trace arrival)**: requirement 는 기대 구조화 이벤트가 correlation id 로 *도착*해야 green.
- **R10 (Longinus ReferenceSite)**: 각 requirement 의 `must_emit` 이벤트가 emit site(`verify` 심볼)에 bound.
- **R14 (done = green + bound + rules)**.

## 구조

```
ooptdd_receipts/
  run_all.py            # 감사 엔트리 — 모든 */requirements.yaml 자동발견, 하나라도 RED 면 exit 1
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
# → 발견된 전체가 green 이면 exit 0
```

개별 finding 만:

```bash
cd ooptdd_receipts/H3 && ooptdd-loop run requirements.yaml   # root: "." = 이 디렉토리
```

> 참고: `memory` 백엔드는 per-run ephemeral 이라 사후 `ooptdd-loop verify <cid>` 단독 호출은
> `absent` 를 반환한다(영수증 결함 아님). 권위는 `run`/`run_all.py` 출력이다.

## 감사 배선

이 코퍼스는 일반 push/PR 제품 게이트에서 제외된다. 주간 또는 수동
`.github/workflows/frozen-evidence-audit.yml`이 checkout 안에서 재현 가능한 경계를 전수 검사한다.
외부 HSWM/SYMPOSIUM 원본과의 결속은 별도 cross-repository 감사 대상이며, 이 워크플로가 그
권위를 검증했다고 주장하지 않는다.

일부 동결 spec 주석에는 역사적 runner 이름인 `test_ooptdd_receipts_all(.py)`가 남아 있다.
현재 후계 runner는 `tests/frozen_ooptdd_receipts_all.py`다. spec 바이트에 결속된 기존 영수증을
단순 문구 정리로 재발행하지 않기 위해 해당 주석은 의도적으로 보존한다.
