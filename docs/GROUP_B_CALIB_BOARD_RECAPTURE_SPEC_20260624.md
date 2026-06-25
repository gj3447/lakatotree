# GROUP_B_CALIB_BOARD_RECAPTURE_SPEC — group-B calib 확보 사양 (2026-06-24)

**상태: ★SUPERSEDED (2026-06-25) — 재촬영 불필요로 판명.** 기록 보존용 문서.
발원 PROM: `CALIB_GEOMETRY_MISMATCH_PROM_20260624` · 게이트: [[CALIB_GEOMETRY_GATE_PATCH_20260624]]
연구노드: `examples/bpc_icp_programme.py` → `group_b_calib_resolve`(progressive)

> 이 문서는 매니페스트 `calib_era_binding.fix` 가 가리키던 forward-pointer 다. 원래 가정한 "현장 보드
> 1회 재촬영" 안을 **기록으로 남기되**, 2026-06-25 에 그 가정이 틀렸고 재촬영 없이 해결됐음을 명시한다.
> 측정 결과를 새로 만들지 않는다 — 이미 기록된 사실만 정리한다.

---

## 1. 원래 가정 (2026-06-24)

group-B(PLATE_HOLE 변경 後, VFQZ 06-17~)는 **생산이 markerless** 라 board calib 이 없다고 판단
(`VFQZ0040` 단일 표본에서 ArUco 마커 0개 실측). 따라서 era-correct calib 을 얻으려면:

> **원안:** 현장에서 ArUco 보드를 group-B 형상 위에 1회 재촬영 → puzzle calib 체인 재솔브.

이 원안이 매니페스트 `fix` 가 가리킨 본 문서의 본래 내용이었다.

### 원안 recapture 절차 (실행되지 않음 — 기록용)
1. group-B 형상(PLATE_HOLE Y 변경 後)에 DICT_4X4_250 puzzle 보드를 올려 1회 캡처(≥20뷰, 뷰당 ≥4마커).
2. `hitech_aruco_puzzle_assemble` 로 board calib 재솔브(target: marker rms ≤ group-A 수준).
3. 새 calib 에 `geometry_era=group-B`, `valid_date_range` 메타 박기([[CALIB_GEOMETRY_GATE_PATCH_20260624]] G1 충족).
4. group-B lot 재측정 → `boss_h σ` 가 matched 수준으로 회복되는지 검증.

---

## 2. ★2026-06-25 SUPERSEDED — 재촬영 불필요 (grounded)

원안의 전제("group-B 보드 없음")가 **VFQZ0040 단일표본 일반화 오류**였다. 몽타주 시각스캔에서
`VFQZ0013` 에 마커가 발견 → 재검 결과 **`VFQZ0016~0024` lot 에 완전한 보드가 이미 존재**(20/21뷰·~99 distinct ArUco ids).

→ **기존 데이터만으로 calib 재솔브, 재촬영 0:**
- `hitech_aruco_puzzle_assemble VFQZ0016` → placed 20/20, **marker rms 0.266mm · seam 1.001mm**
  (group-A `VFEZ0040` 0.42mm 보다 오히려 우수).
- 이 calib 으로 `VFQZ0010` 측정 시: wrong-calib 의 `BIG_04 −35.43mm` garbage 가 **−5.22mm sane peel** 로 복원,
  `boss_h` 전부 −7.1~+4.5 정상범위, 안정 컵 **σ ≤ 0.21mm**.
- evidence: `c3_groupB_calib_solved_20260625.md`

결론: **재촬영·markerless 둘 다 불필요**했다 (사용자 "재촬영 안 함" 판단이 옳았음).

---

## 3. 현재 상태

- **게이트는 유지**: 형상-era 바인딩 게이트([[CALIB_GEOMETRY_GATE_PATCH_20260624]])는 systemic fix 로 그대로 둔다
  (재촬영이 불필요했던 것과 별개로, cross-era silent garbage 차단은 영구 필요).
- **group-B calib = resolved (base)**: seam 1.0mm·zwarp/zconst 미적용 base calib. **gross NG**(peel −5~−7·결손)엔 충분.
  `<1mm` 정밀 안착엔 z-chain(215/216/219) 추가 필요.
- **진행 중**: group-B 철회분 재측정 — 67 VFQZ + 5 VFRZ 시간순 batch(gbbatch), per-lot σ·onset·NG/normal 라벨.
- **대안 경로**: calib-free `markerless_camera_spec_measure`(검증됨) 로도 group-A/B 균일 측정 가능(결함 스크리닝).

---

## 4. 교훈 (Longinus)
- ❌ 단일 표본(`VFQZ0040` 마커 0개)에서 lot 집합 전체("group-B 보드 없음")로 일반화 금지 — 본 사고의 잘못된 전제.
- ✅ "없다"는 결론 전에 인접 lot(0016~0024)을 전수 확인 → 기존 데이터로 해결 가능한지 먼저 본다(재촬영은 최후수단).
- ✅ 원안이 틀렸어도 문서를 지우지 않고 **supersede 로 표면화**한다(왜 틀렸는지 기록 = 재발 방지).
