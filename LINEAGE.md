# 데이터 계보 — 버퍼는 임시, 완성본은 ZDF서 재생성

> 문제: 데이터가 바뀐다. consumer_b ZDF → 버퍼/캐시(_rimobs/perview) → 완성본. 중간 버퍼를 써도
> 완성본이 나오면 ZDF서 전 파이프라인으로 다시 만들 수 있어야 하고, 데이터가 바뀌면 감지돼야.

## 모델 (lakatos/lineage.py)
- **source**: ZDF — derivation 없는 root (raw 입력, 재생성 안 함)
- **intermediate(버퍼)**: _rimobs_*.npz 등 — 코드+params 로 source 서 파생, 삭제/재생성 가능
- **final(완성본)**: perview_*.json, 리포트 — 버퍼서 파생
- **Derivation**: 출력 ← f(입력[path,sha], 생산코드[path,sha], params). 모든 sha 기록

## 기능
| 질문 | 함수/엔드포인트 |
|---|---|
| 이 완성본은 어느 ZDF서 왔나 | `roots` / `GET /api/lineage/{art}` → roots |
| ZDF서 어떻게 재생성하나 | `rebuild_plan` → topo 순서 (버퍼 먼저, 완성본 끝) |
| 정말 재현 가능한가(끊긴 링크 없나) | `is_reproducible` / reproducible+gaps |
| 데이터가 바뀌었나 | `stale_inputs` / `?stale=true` → 기록 sha vs 현 디스크 sha |

## 저장 (3중)
- KG: `(:DataArtifact)-[:DERIVED_FROM]->(:DataArtifact)` = W3C PROV wasDerivedFrom
- PG: `lineage` 테이블 = append-only sha 원장 (이력)
- 디스크: 실제 sha256 (Longinus content hashing 동형)

## 사용
```bash
lakatos lineage-record <out> --sha <s> --producer <p.py> --input <zdf>:<sha> --kind final
lakatos lineage <완성본>            # ZDF 추적 + 재빌드 플랜 + 재현가능?
lakatos lineage <완성본> --stale    # 데이터 바뀜 감지
```

## 라이브 검증 (consumer_b)
perview_fixedr_joint_v22 → roots=[VFEZ0060], reproducible=True,
rebuild_plan=[_rimobs, perview_v22], stale 감지(기록 sha≠현재 → 재생성 필요) 작동.
