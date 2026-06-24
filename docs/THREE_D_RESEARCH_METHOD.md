# 3D 형상 검출 연구 — 어떻게 해야 "잘했다고 소문나는가"

> 통합 프로그램 **「3D 형상 검출(3D-shape detection from 3D data)」** 의 방법론 정본.
> BPC(줄기)·SX3i·LX3(가지)가 공유. 엔진=`lakatotree`, 통합루트=`examples/three_d_detection.py`.

## 0. 한 줄 요약

> **연구를 "코드 짜고 돌리기"가 아니라 「측정 → grounded 레코드 → 엔진 판결」 루프를 닫는 일로 재정의하라.**
> 그러면 소문은 "결과가 좋다"가 아니라 **"저 팀은 한계를 datasheet 로 먼저 못박고, 실패를 숨기지 않고, 누구나 재현한다"** 로 난다 — 그게 metrology 신뢰의 본질이다.

prismv2(측정 기계) → 얇은 하네스(grounded record) → LakatoTree(판결). 측정 기계가 자기 출력을
자기가 판결하면 = 자기채점. 그래서 세 역할을 분리한다. 사람은 판결하지 않는다 — **나무를 본다.**

## 1. 소문나는 3D 연구의 5 기둥

각 기둥은 LakatoTree 5-gate 인증으로 수렴한다(preregistered/reproducible/stands/calibrated/grounded).

| # | 기둥 | 무엇 | 반례(이것 없으면 신뢰 0) | 우리 증거 |
|---|---|---|---|---|
| 1 | **사전등록** | 예측·noise band·반증조건을 *측정 전*에 박는다 | 결과 보고 가설 만들기(HARKing), verdict 손입력 | 엔진이 강제. SX3i C3 noise band 측정 전 고정 |
| 2 | **독립검증** | self-consistency ≠ accuracy. 외부 기준(CMM/cross-cam/feature-coincidence) | "정합에 쓴 마커끼리 잘 맞으니 정확하다"(허수) | SX3i C3⭐, LX3 GROUND_TRUTH |
| 3 | **재현 provenance** | 데이터 sha256 + script git + env → 누구나 재실행, 같은 verdict | "내 노트북에선 됐다", 데이터 출처 불명 | longinus-data-binding(212 zdf), evidence-record |
| 4 | **게이지 능력(MSA)** | R&R σ, AIAG P/T — 측정계가 공차를 분해하나 | 측정 산포가 공차보다 큰데 PASS/FAIL 함 | LX3 σ=37µm, P/T 22% 🟢ACCEPTABLE |
| 5 | **음의 결과 보존** | 실패 가지를 나무에 남긴다 — *왜 안 되는지*가 자산 | degenerating/rejected 삭제 → 같은 실수 반복 | free-ICP collapse, 6-DOF 악화, CPD 흡수 |

## 2. 운영 루프 (매 실험 1바퀴)

```
[1] 사전등록   PROGRAMME.md 에 conjecture + 예측값 + noise band + 반증조건을 측정 전 기입
                  → frontier OPEN 질문으로 등록 (q_*)
[2] 측정       prismv2(또는 도메인 모듈/합성)를 얇은 하네스로 호출
                  → SX3i_ICP_SPEC/evidence/<record>.json (grounded record, verdict 없음)
[3] 판결       LakatoTree 가 record 를 source_record 로 grounding → verdict 를 *생성*
                  → progressive / degenerating / rejected (손입력 0)
[4] 갱신       frontier 닫힘/열림, 5-gate 상태 갱신, 나무 재렌더
[5] 확인(사람)  대시보드에서 나무를 본다 → 다음 frontier 선택 (판결 안 함, 방향만)
```

**규율**: [2]의 하네스는 버리는 코드가 아니다 — `evidence/` 에 재현가능 레코드를 남긴다.
[3]에서 측정 없이 progressive 박으면 가짜green(금지). 미측정 conjecture 는 OPEN frontier 로만.

## 3. 사람의 역할 — "가끔 확인"은 무엇을 보는가

판결은 엔진이 한다(자기채점 차단). 사람은 **나무를 보고 방향을 잡는다.** 대시보드(`§5`)에서:

1. **본류(canonical)가 진보 중인가** — improvement_pct ↑ 면 건강. 정체면 frontier 전환 신호.
2. **frontier 가 닫히는가** — closed−open 수지(laudan). open 만 쌓이면 측정이 안 따라오는 것.
3. **퇴행 가지가 폐기 합의됐는가** — 최대 퇴행깊이 ≥3 경보. (6-DOF 가지가 그 예.)
4. **5-gate 미통과가 뭔가** — reproducible/calibrated 가 흔한 미통과. manifest·credence 이력 보강 대상.

> 사람이 보는 화면 = `examples/three_d_detection.html` (정적, 서버 불필요). 색=본류/퇴행/살아있는 가지.

## 4. 지금 우리 나무의 정직한 상태 (2026-06-23)

- **BPC** = 줄기. CANONICAL=`v8_pipeline`(sub-1mm). 미해소 = interior 0.90mm **CMM 미검증**(step 6.1) → 기둥2 미완.
- **SX3i** = `v8_pipeline` 에서 수직 개화. 설계완료·실행대기. **첫 grounded 증거**(C1 광학 타당성):
  - GSD = 740mm FOV / 1408px = **0.526 mm/px** (zivid.py LensSpec, 실측)
  - 20px 룰 → ArUco 마커 **≥ 10.5mm** 필요 (grounded 조건)
  - ⚠️ **XL250 단일샷 정밀도 250µm > C3 목표 100µm (2.5배)** — capture_qc "0.1mm washer XY 불가" 와 일치.
    → sub-0.1mm 는 **multi-view 평균(√N)** 없이는 물리적으로 불가. 캡처 전에 datasheet 로 못박은 음의 사전판정.
- **LX3** = `aruco_metric` 에서 개화. 초기 markerless 가정 → **2026-06-22 MIP_36H12 ArUco + 턴테이블(LX3RT) 피벗**(과거 "마커 不在" 정정). GROUND_TRUTH σ 37µm(기둥4 충족) + ArUco 검출 119/121뷰(보정 nlm+2×, 연결성분 115)로 정합 enabler 확보. markerless 자동경로 ceiling 은 음의분기 보존. ⚠️정합 *정확도* sub-mm 는 미측정(OPEN, 검출≠정확도).

## 5. 도구 지도

| 일 | 도구 |
|---|---|
| 사전등록 | 각 repo `PROGRAMME.md` (BPC=README+26_EXPERIMENT_TREE, SX3i/LX3=PROGRAMME.md) |
| 측정 하네스 | `SX3i_ICP_SPEC/harness/*.py` → `evidence/*.json` (계약=`lakatotree/docs/EVIDENCE_RECORD.md`) |
| 판결 엔진 | `lakatotree/examples/{three_d_detection,bpc_icp,sx3i_icp,lx3_icp}_programme.py` |
| 나무 보기 | `python -m examples.three_d_dashboard` → `three_d_detection.html` (브라우저로 열기) |
| 회귀 가드 | `lakatotree/tests/test_*_icp.py`, `test_three_d_detection.py` (pytest) |

## 6. 다음 한 걸음

C3(독립 정밀게이트)가 관문이다. 그런데 §4 가 보여주듯 **C3 전에 물리 한계를 먼저 닫아야** 한다:
multi-view 평균으로 250µm 단일샷 정밀도를 100µm 아래로 끌어내릴 수 있는가(√N, N≈212)?
이 질문(`q_sx3i_precision_floor`)을 사전등록하고, 212 zdf 로 feature-coincidence 분산을 측정해 닫는다.
**C3 검증 없이 C4 refine 얹으면 헛디딤(BPC 반복실수 패턴).**
