# ADR: KG 미러 sync 는 동일-DB 스키마 통일 문제다 (2026-07-03, 후속 PROM R11)

## 맥락
git-흡수 G4 는 receive-pack 격리(quarantine-then-migrate)를 이식해 `scripts/sync_lakatos_programme_to_kg.py`
의 미러 무결성을 행별 content-sha 재유도로 강화했다. 남은 질문: **엔진 DB → 공유 KG projection** 의 방향과 범위.

## 결정
1. **엔진 DB == 공유 consumer KG 는 동일 DB다**(라이브 실측: `:55170` 서버의 NEO4J_URI 와 kg-neo4j 가 같은
   bolt/그래프를 가리킴 — git-흡수 캠페인 내내 확인). 따라서 'engine→KG projection' 은 별도 DB 복제가 아니라
   **스키마 통일 문제**로 축소된다. 이 단일-DB 가정을 명시 의존성으로 이 ADR 에 못박는다(가정이 깨지면 =
   별도 replica 도입 시 = 이 sync 설계 전면 재검토).

2. **미러는 판결 권위가 없다 — notebook tier 스탬프.** `sync` 가 쓰는 `:LakatosNode` 미러 행은 손큐레이션
   프로그램 모듈에서 온다(서버 원장 receipt 가 아님). 그래서 `_node_row` 는 `assurance_tier='notebook'` 을
   무조건 스탬프한다(`_MIRROR_TIER_ALLOWED = {notebook}`). 모듈이 `verdict_source` 를 손으로 FORCEFUL 로
   실어도 `engine_scored` 는 파생(진위는 KG 가 판정)이고 tier 는 notebook 이라 소급 CANONICAL/anchored 위장이
   구조적으로 불가하다.

3. **명명 프리픽스 레지스트리**(`NAME_REGISTRY`) — 허브명 → 정본 노드 프리픽스 고정 매핑. 미등록 허브에
   `resolve_prefix` 는 `NamingRegistryError`(fail-loud). 한계비용 0 으로 KG 이름공간 드리프트(같은 프로그램이
   두 프리픽스로 갈라짐)를 봉합.

4. **무권한 staging prototype 폐기**(2026-08-02 안전성 재심). 과거
   `build_staging_cypher`/`build_migrate_cypher`는 실제 verifier·tree lock·receipt와 결합되지
   않았고 live properties 전체를 덮을 수 있었다. 세 호환 함수는 이제 호출 즉시 fail-closed 한다.
   유일한 mutation authority는 namespace, exact constraints, tree lock, protected-node guard,
   operation identity와 durable receipt를 한 트랜잭션에 묶는 `do_apply`다.

## 보류 (user GO 대기)
- **exporter 방향 반전**(엔진 DB → 허브, 현행 모듈 → KG 의 역): 허브 13개 3-way 처분표(재주행/notebook 강등/
  은퇴) 확정 후로 DEFER — 일부 허브는 진행중 프로그램 등록처라 은퇴 불가(설계결정 선행).
- **268행 content_sha 백필 `--apply`**: KG write 이므로 user GO 게이트. 별도 staging 경로를
  부활시키지 말고 현재 guarded `do_apply` 계약 안에서만 수행할 것.

## 상태
ACCEPTED, amended 2026-08-02 (prototype 폐기 + guarded direct apply 단일 권위;
백필·방향반전은 GO 대기). 가드: `tests/fix_harness/test_r11_sync_20260703.py`.
