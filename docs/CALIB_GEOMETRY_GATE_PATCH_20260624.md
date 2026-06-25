# CALIB_GEOMETRY_GATE_PATCH — 형상-era calib 바인딩 게이트 (2026-06-24)

**상태: ACTIVE (systemic fix, 유지)** · 발원 PROM: `CALIB_GEOMETRY_MISMATCH_PROM_20260624`
바인딩: `docs/bpc_prismv2_longinus_manifest.json` → `capture_datasets.calib_era_binding`
연구노드: `examples/bpc_icp_programme.py` → `calib_geometry_mismatch`(degenerating 진단) · `q_calib_geometry_gate`(OPEN)

---

## 1. 문제 (degenerating 진단, 사용자 catch)

`frozen_calib_reuse`(board calib 동결 → markerless lot 직접 `T_view_to_world` 재사용)는
**같은 형상 era 안에서만** 유효하다. PLATE_HOLE 형상이 바뀐 뒤의 lot 에 이전 era 의 동결 calib 을
적용하면 정합이 어긋나 **silent garbage** 가 나온다.

실증(grounded):
- group-A calib `VFEZ0040_puzzle_calibration_v4_zwarp_zconst.json`(2026-06-05) 을
  PLATE_HOLE Y 변경 後 group-B(`VFQZ`, 2026-06-17)에 하드코딩 적용 (`run_new_lot:42`, **날짜/형상 게이트 0개**).
- 결과: 같은 컵 `boss_h` 가 캡처간 −35~+4mm 출렁 (BIG_04 `[4.36, 4.50, −35.43, 4.39, −35.37]`, **σ≈18.6mm**),
  peel/탭볼트 verdict 가 캡처마다 깜빡 = **reproducibility 위반**.
- 대조: matched era(VFEZ) 에서는 `boss_h σ ≤ 0.15mm` 안정.

핵심: **검출 알고리즘은 무결**(VFEZ 에서 안정) — 결함은 *calib 입력*이 형상 era 와 어긋난 것.

---

## 2. 형상 era 정의

| | group-A | group-B |
|---|---|---|
| geometry | PLATE_HOLE 변경 **前** | PLATE_HOLE Y 변경 **後** |
| dates | 2026-06-04 VFDZ · 06-05 VFEZ · 06-08 VFHZ · 06-10..16 MASTER | 2026-06-17 VFQZ · 06-18 VFRZ |
| board | VFEZ0025-0048 ArUco DICT_4X4_250 (positive control VFEZ0040 4~7마커/뷰) | (생산은 markerless) 보드는 VFQZ0016~0024 lot 에 존재 |
| calib | `VFEZ0040_puzzle_calibration_v4_zwarp_zconst.json` | `group_b_calib_resolve`(2026-06-25, 기존데이터 재솔브 — [[GROUP_B_CALIB_BOARD_RECAPTURE_SPEC_20260624]] 참조) |
| status | valid (σ≤0.15mm) | base calib resolved (재촬영0); 정밀 z-chain·per-lot σ batch 진행 |

`other`: 2026-06-22 LX3RT 는 **다른 부품**(LX3 서브프레임) — BPC calib 과 무관(혼입 금지).

---

## 3. 게이트 규칙 (the patch)

```
REJECT (측정거부) IF  lot.capture_date > 2026-06-16  AND  calib.era == group-A
```

= 형상 era 가 바뀐 뒤(>2026-06-16)의 lot 에 group-A 동결 calib 을 적용하려는 시도를 **측정 전에 차단**한다.
원인 버그는 `run_new_lot:42` 가 calib 을 무조건 하드코딩 재사용하며 **날짜/형상 바인딩 검사가 0개**였던 것.

**패치가 추가해야 하는 것:** calib 적용 직전에 `(lot.geometry_era, calib.geometry_era)` 일치 검사.
불일치 → 측정 abort + era-mismatch 진단 메시지(어느 calib 가 어느 era 인지). 무음 진행 금지.

### 대안 측정 경로 (게이트에 걸렸을 때)
- **ArUco SOLVER_PKG 경로**: era-lock(같은 era 의 보드 calib 필요). group-B 는 `group_b_calib_resolve` 가 확보.
- **markerless camera-spec 경로** (`markerless_camera_spec_measure`, 검증됨): calib 없이 organized-cloud
  pixel→3D per-frame LOCAL 측정 → era 무관·부품형상 무관, group-A/B 균일. gross NG 스크리닝에 충분.

---

## 4. Acceptance / kill

- **G1 (게이트 발동)**: group-A calib 을 capture_date>2026-06-16 lot 에 적용 시도 → 측정거부 + 진단. (무음 garbage 0)
- **G2 (정상 통과)**: matched era(같은 형상)에서는 게이트가 막지 않는다 (VFEZ↔group-A 정상 측정).
- **G3 (재현성 회복)**: era-correct calib 으로 측정 시 `boss_h σ` 가 matched 수준으로 회복 (group-B: σ≤0.21mm 확인됨).
- **kill**: matched era 에서도 σ≫0.15mm 면 원인이 calib-era 가 아니라 검출기/캡처 → 이 게이트로 해결 불가(별도 진단).

---

## 5. Longinus do / don't

- ✅ calib 메타데이터에 `geometry_era` + `valid_date_range` 를 명시적으로 박는다(바인딩이 single source).
- ✅ era 불일치는 **측정거부**로 표면화한다 — "그냥 돌려서 숫자 나오면 OK" 금지.
- ❌ "예전 calib 재사용하면 빠르니까"로 형상 era 게이트를 우회하지 않는다(이 사고의 직접 원인).
- ❌ LX3RT 등 **다른 부품** 데이터를 BPC calib era 판정에 혼입하지 않는다.

---

## 6. 바인딩 (provenance)
- manifest: `capture_datasets.calib_era_binding.gate_rule`
- evidence: `c3_groupB_calib_solved_20260625.md` (게이트 후 group-B 정상 측정 복원 실증)
- 후속: [[GROUP_B_CALIB_BOARD_RECAPTURE_SPEC_20260624]] (원래 fix 안 + 2026-06-25 supersede)
