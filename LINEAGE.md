# 데이터 계보 — 버퍼는 임시, 완성본은 root data 서 재생성

> 문제: 데이터가 바뀐다. root data → 버퍼/캐시 → 완성본. 중간 버퍼를 써도
> 완성본이 나오면 root data 서 전 파이프라인으로 다시 만들 수 있어야 하고, 데이터가 바뀌면 감지돼야.

## 모델 (lakatos/lineage.py)
- **source**: root artifact — derivation 없는 raw 입력, 재생성 안 함
- **intermediate(버퍼)**: 캐시/관측/전처리 산출물 — 코드+params 로 source 서 파생, 삭제/재생성 가능
- **final(완성본)**: 모델/리포트/판결 입력 — 버퍼서 파생
- **Derivation**: 출력 ← f(입력[path,sha], 생산코드[path,sha], params). 모든 sha 기록

## 기능
| 질문 | 함수/엔드포인트 |
|---|---|
| 이 완성본은 어느 root data 서 왔나 | `roots` / `GET /api/lineage/{art}` → roots |
| root data 서 어떻게 재생성하나 | `rebuild_plan` → topo 순서 (버퍼 먼저, 완성본 끝) |
| 정말 재현 가능한가(끊긴 링크 없나) | `is_reproducible` / reproducible+gaps |
| 데이터가 바뀌었나 | `stale_inputs` / `?stale=true` → 기록 sha vs 현 디스크 sha |

## 저장 (3중)
- KG: `(:DataArtifact)-[:DERIVED_FROM]->(:DataArtifact)` = W3C PROV wasDerivedFrom
- PG: `lineage` 테이블 = append-only sha 원장 (이력)
- 디스크: 실제 sha256 (Longinus content hashing 동형)

## 사용
```bash
lakatos lineage-record <out> --sha <s> --producer <p.py> --input <root>:<sha> --kind final
lakatos lineage <완성본>            # root 추적 + 재빌드 플랜 + 재현가능?
lakatos lineage <완성본> --stale    # 데이터 바뀜 감지
```

## 프로젝트 예시 (consumer_b)
consumer_b에서는 root artifact 가 ZDF lot 이다. 예: perview_fixedr_joint_v22 → roots=[VFEZ0060],
reproducible=True, rebuild_plan=[_rimobs, perview_v22], stale 감지(기록 sha≠현재 → 재생성 필요) 작동.

## 스크립트도 이력 (생산 코드 수정 추적)
스크립트도 중간에 수정된다. append-only 기록에서 `producer_sha` 가 바뀌면 새 버전.
- `script_history(derivs, producer)` → [{sha, first_seen, outputs}] 시간순
- `GET /api/lineage-script/{producer}` / `lakatos script-history <p.py>`
- 어느 코드 버전이 어느 데이터를 만들었나 = 완전 재현의 마지막 조각

## 프로젝트 온톨로지 — LakatoTree(틀) ⊃ 프로젝트(인스턴스)
- **LakatoTree** = 추상 형상/틀/프레임워크 (domain-agnostic, 순수이성구조체)
- **프로젝트** = 그 안의 구체 인스턴스. root 데이터·목표·파이프라인·연구나무를 가짐
  - **consumer_b**: root=ZDF, 목표=sub-1mm 검사 PASS/FAIL, tree=LakatosTree_BPC_20View
  - 타 프로젝트 = 타 root 데이터와 타 목표
- KG: `(:LegionCommander LakatoTree)-[:INSTANTIATED_AS]->(:LakatoProject)-[:HAS_RESEARCH_TREE]->(:LakatosTree)`
