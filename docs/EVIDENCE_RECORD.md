# evidence-record 계약 (`lakato-evidence-record/v1`)

> 측정 하네스 → **grounded record(json)** → LakatoTree `source_record` grounding 의 표준 포맷.
> 로더/검증 = `lakatos.programme.evidence` (공개 저작 API; 구 `examples/_evidence.py` 는 back-compat shim).
> longinus-data-binding(데이터 provenance)을 *측정*으로 확장.
> 방법론 = `3D/THREE_D_RESEARCH_METHOD.md`.

## 불변식 (validate_record 강제)

1. **verdict 금지** — 레코드(및 measurement)는 판결을 담지 않는다. 판결은 엔진이 생성(자기채점 차단).
2. **grounded** — measurement 는 provenance.inputs(또는 data_manifest)로 출처가 명시돼야 한다.
3. **사전등록** — `preregistration.registered_before_measurement = true`(HARKing 차단).

## 스키마

```json
{
  "schema": "lakato-evidence-record/v1",
  "programme": "3d-shape-detection",
  "branch": "consumer_d | lx3 | bpc",
  "conjecture": "C1_xl250_marker_gsd",
  "node_tag": "consumer_d_c1_optics_feasibility",

  "preregistration": {
    "claim": "XL250 광학에서 20px 마커 룰이 물리적으로 성립하는가",
    "predicted": {"metric": "marker_min_mm_for_20px", "value": null, "unit": "mm"},
    "noise_band": 0.05,
    "direction": "lower",
    "kill_condition": "단일샷 정밀도 > C3 목표(100µm) → sub-0.1mm 단일샷 불가",
    "registered_before_measurement": true
  },

  "measurement": {
    "metric": "gsd_mm_per_px",
    "value": 0.5256,
    "unit": "mm/px",
    "scope": "optics_feasibility",
    "derived": { "marker_min_mm_for_20px": 10.51, "precision_um": 250, "c3_target_um": 100 }
  },

  "provenance": {
    "inputs": [
      {"name": "xl250_lensspec",
       "source": "consumer_a/consumer_a_core/config/zivid.py:LENS_CATALOG['XL250']",
       "fov_mm": [740.0, 740.0], "working_distance_mm": [1200.0, 2800.0], "precision_um": 250.0},
      {"name": "zdf_resolution_px", "source": "consumer_a/README.md (1408x1408 ZDF)", "value": 1408}
    ],
    "data_manifest": "SX3i_ICP_SPEC/docs/consumer_d_data_bindings.json",
    "data_count": 212,
    "grounded": true
  },

  "harness": {
    "script": "SX3i_ICP_SPEC/harness/measure_c1_marker_gsd.py",
    "git_commit": null,
    "env": "python3.10",
    "timestamp": "2026-06-23T00:00:00"
  },

  "gauge": null,

  "findings": [
    {"kind": "closes", "frontier": "q_xl250_gsd_satisfiable",
     "body": "20px 룰은 마커 ≥ 10.5mm 면 성립(GSD 0.526mm/px)"},
    {"kind": "opens", "frontier": "q_consumer_d_precision_floor",
     "body": "단일샷 정밀도 250µm > C3 목표 100µm — multi-view √N 평균 없이는 sub-0.1mm 불가"}
  ],

  "notes": "캡처 전 datasheet 기반 광학 타당성 — 실 마커검출 카운트는 별도 측정(212 zdf)."
}
```

## 필드

| 필드 | 필수 | 의미 |
|---|---|---|
| `schema` | ✓ | `lakato-evidence-record/v1` 고정 |
| `programme` / `branch` / `conjecture` | ✓ | 어느 프로그램·가지·주장에 대한 측정인가 |
| `node_tag` | | 엔진 노드 tag(있으면 직접 grounding) |
| `preregistration` | ✓ | 측정 전 박은 예측·noise band·반증조건 |
| `measurement` | ✓ | 실측 metric/value/unit/scope(+derived). **verdict 없음** |
| `provenance` | ✓ | inputs 출처 + data_manifest + grounded 플래그 |
| `harness` | ✓ | 재현용 script/git/env/timestamp |
| `gauge` | | MSA(R&R σ, AIAG P/T) — 있으면 기둥4 충족 |
| `findings` | | `closes`/`opens` frontier 제안(판결 programme 이 해석) |

## 판결측 사용 (programme)

```python
from lakatos.programme.evidence import load_record, summarize, is_grounded
rec = load_record(EVIDENCE_PATH)          # 파일 없으면 FileNotFoundError → frontier OPEN 유지
s = summarize(rec)                         # measured/predicted/grounded/findings/errors
if is_grounded(rec):
    # findings.closes → frontier CLOSED(closed_by=source_record), findings.opens → 새 OPEN
    ...
```
