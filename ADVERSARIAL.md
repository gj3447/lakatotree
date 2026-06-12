# 적대 검증 이력 (나생문 critic)

## Round 1 (2026-06-12) — REJECT → 수정 → 통과
독립 critic agent 가 8 findings (3 BLOCKER). 전부 실행으로 재현됨. 수정:

| ID | 심각도 | 문제 | 수정 |
|---|---|---|---|
| F-FG-1 | BLOCKER | 판결 어휘 수동 덮어쓰기 + test_result re-roll 가능 (스크립트-판결 독트린 우회) | verdict 엔드포인트 ADMIN_VERDICTS 화이트리스트(403), test_result verdict_source='scripted' 시 재채점 409 |
| F-FG-2 | BLOCKER | 음수 noise_band → worse-is-progressive, NaN → 침묵 rejected | Prediction.__post_init__ noise_band≥0/유한 검증, judge measured 유한 검증, pydantic Field(ge=0) |
| F-FG-3 | BLOCKER | parent 사이클 → 무한루프 DoS (공개 API 로 생성가능) | path 워크/degen_depth/chain 워크 전부 visited-set 가드 |
| F-FG-4 | DEBT | 라우든 규칙③ 사실상 dead, former_canonical 미반영 | hits 에 former_canonical 추가 (규칙③ per-branch 귀속은 후속) |
| F-FG-5 | DEBT | CANONICAL demote+promote 2-세션 레이스 | 단일 Cypher 트랜잭션화 |
| F-FG-6 | DEBT | 대시보드 stored XSS | html.escape 전 입력 필드 |
| F-FG-8 | NITPICK | GET /metrics 부작용 INSERT | ?snapshot=1 opt-in |

회귀 테스트 6 추가 (test_judge: 음수밴드/NaN/worse-never-progressive, test_metrics: 사이클). 20/20 green.

## 잔여 (정직 — 후속 노드 frontier)
- F-FG-2 깊은 버전: novel_prediction 이 텍스트 존재만 검사(미입증). 구조화+채점은 별도 노드.
- F-FG-4: 라우든 규칙③ per-branch 질문 귀속(RAISES_QUESTION→windowed balance) 미배선.
- F-FG-6/7: 인증 레이어 부재(LAN 노출), .env 전체 주입 — 배포 시 토큰+최소권한.
