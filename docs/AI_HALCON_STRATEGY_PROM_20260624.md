# 3D 형상검출 AI·HALCON 전략 — 프로메테우스(prom) × 우리 실측 교차종합 (2026-06-24)

> 출처: `bhgman-tool prom 5 "..."` (DGX vLLM Qwen3.6-35B, 5 서브에이전트, --local --no-web).
> 우리 실측(grounded recon)과 교차: HALCON `surface_match`123·`cylinder`297·`sphere`121·
> `fit_primitives_object_model_3d`6 실사용(단 LX3 SurfaceMatch **license 막힘**); neural 서비스=스켈레톤.

## 1. prom이 우리 원칙을 **확증** (잘 가고 있음)

- **precision ≠ accuracy, best-fit 금지, GD&T datum 보존** = prom 만장일치 = 우리 hard core 그대로.
- **DL은 측정에 쓰지 마라** — 최종 치수(직경/위치/GD&T)는 *결정론적 기하 fit*(LSQ/ICP/primitive)으로만.
  DL은 **세그멘테이션 + 6D pose INIT**(coarse, ICP collapse 방지)에만. → 우리 "metrology는 결정론" 그대로.
- **occlusion → multi-view fusion(bundle adjustment), 턴테이블 known-angle을 hard constraint로** = 우리가
  이미 하는 known 3°/뷰 정합 그대로.

## 2. **어디에 AI를 적용**하나 (Q1 답)

| 단계 | AI 적용? | 모델 | 비고 |
|---|---|---|---|
| 부시 bore **검출/세그멘테이션** | ✅ **여기** | **SAM2**(promptable seg), PointTransformer/Sonata | ★내 자동fit 3/4 실패를 직접 해결 — 4부시 robust 식별 |
| 6D pose **INIT** (coarse) | ✅ | FoundationPose / MegaPose / SAM-6D | ICP collapse·local-min 방지용 init만 |
| 멀티뷰 **정합 fine** | ❌ DL 아님 | HALCON ICP / 커스텀 datum-constrained ICP | 정확도 보존 |
| **치수 측정** | ❌ 절대 DL 아님 | LSQ cylinder/plane fit (HALCON `fit_primitives`) | GD&T datum |
| anomaly(결함) | ⚠️ 선택 | — | 치수와 분리 |

→ **즉 우리 다음 수 = 부시 bore SAM2 세그멘테이션**(4부시 robust 검출) → 기존 sub-mm 축으로 정합 → CAD ruler 대조.

## 3. HALCON 충분히 쓰나 (Q3 답)

- **잘 쓰는 중**: surface_match·cylinder·sphere primitive fit 다수 배선. 우리 메인 도구.
- **막힌 곳**: LX3 `SurfaceBasedMatching`(S-BASE) **license 블록**. prom 분기:
  - 합법 경로 = S-BASE 라이선스 확보 OR Open3D/PCL+커스텀 datum-ICP로 정합 이관(측정만 HALCON).
  - ⚠️ "workaround/우회"는 prom 일부가 *불법/비윤리*라 거부 — 라이선스 확보가 정도.
- **미활용**: `register_object_model_3d_pair`(multi-view fusion), deformable surface, photometric stereo. 검토 여지.

## 4. ⭐ 우리가 **못 보던 blind-spot** (Q4 — prom이 surface)

> ⚠️ **캡처·공차 정정(2026-06-24, 사용자 지적 2회):** 두 케이스 분리.
> **LX3** = **회전지그(rotating jig)** — 부품을 지그에 고정·3°씩 회전(턴테이블 아님; 정밀지그라 축 반복도 양호 →
> 정합 precision 이미 0.99mm). 공차 **±1.0mm**(sub-0.1mm 아님, GROUND_TRUTH σ 37µm 충족).
> **SX3i** = **삼각대 자유이동** — 카메라를 마구 옮겨가며 촬영. **기하 구속 0**, 정합이 **100% ArUco 마커**에만 의존
> (공유마커 puzzle stitch). 목표 **sub-0.1mm**(C3). → 회전축 자체가 없어 runout 무관; sub-0.1mm 는 *마커 정합품질 +
> 카메라 floor* 가 전부(가장 어려운 케이스).

1. **(SX3i) Zivid 구조광 sub-0.1mm *accuracy* 한계 — sub-0.1mm 의 진짜 blind-spot.** XL250 단일샷 250µm(이미 앎).
   prom: 대형 금속부품 structured-light 는 interferometric cal 없이 sub-0.1mm *accuracy* 도달 불확실(precision≠
   accuracy). SX3i 는 턴테이블 아닌 ArUco-puzzle → runout 無, 벽은 **카메라 floor 250µm + 멀티뷰 √N 평균**(=이미
   사전등록 `q_sx3i_precision_floor`). prom 이 그 kill-condition 강화: 평균해도 구조광 accuracy 천장 가능 →
   **목표 정직화**: SX3i ±0.1mm 가 XL250 으로 물리적으로 가능한가, 아니면 다른 카메라/방법 필요한가.
2. **(LX3) 턴테이블 runout — ±1mm 마진 질문(1순위 아님).** prom "runout>0.1mm→sub-0.1mm 불가"는 LX3 가
   sub-0.1mm 가 **아니라 직접 적용 안 됨.** LX3 올바른 질문: LX3RT 물리축 runout 이 ±1mm 마진을 갉아먹는가
   (정합 precision 0.99mm≈±1mm 경계). LX3 의 진짜 병목은 **bush-fit(4부시 robust 검출)** = SAM2 적용처(§2).
3. **흰면 약한 리턴 = multi-exposure HDR / projector intensity 최적화** 미시도(bore 림에 여전히 유효).
4. **DL 라벨 GT 전략 부재** — SAM2/PointMAE 학습 시 GT를 Sim2Real 합성으로 할지 CMM-검증 수동라벨로 할지.
5. **NIR/multi-spectral 분리**(흰면용) — Zivid 옵션 따라.

## 5. 다음 액션 (우선순위)

1. **(SX3i) q_sx3i_precision_floor 측정** — 멀티뷰 √N 평균이 XL250 250µm 를 100µm 아래로? = sub-0.1mm feasibility 판정(진짜 sub-0.1mm 질문). 안 되면 ±0.1mm 목표/카메라 재고. *(과거 §5-1 "LX3 runout 1순위"는 공차혼동 — 격하)*
   lift-노이즈*로 분해. runout>0.1mm면 sub-mm 불가 확정(목표 ±1mm로) — accuracy 벽의 근본 진단.
2. **부시 bore SAM2 세그멘테이션** — 내 자동fit 3/4 실패 해결, 4부시 robust 검출 → CAD ruler 대조로 accuracy 측정.
3. **HALCON S-BASE license 상태 확인** — 블록이 절대인가, 확보 가능한가 (LX3 markerless 경로 재개 여부).
4. **정확도 목표 정직화** — ±0.1mm physical feasibility 판정 후 spec 확정(과잉추구 금지).

## 정직성
prom은 *전략 reference*(외부 SOTA)지 측정 verdict가 아님 — LakatoTree엔 frontier 사전등록(runout 등)으로만
반영, 측정은 grounded record로. DL은 측정에 안 쓰는 게 prom·우리 공통 원칙(metrology 결정론 보존).
