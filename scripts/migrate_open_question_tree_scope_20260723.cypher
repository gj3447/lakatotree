// 마이그레이션: OpenQuestion 트리-스코프 (2026-07-23)
// 배경: OpenQuestion MERGE 키가 {name} 전역이던 결함 수리(서버 writer/service/sync 전부 (tree,name)
// 복합키로 변경됨)에 따라, 기존 KG 의 OpenQuestion 노드에 tree 를 박고 제약을 교체한다.
// 실충돌 관측: judgment-ledger-repair-20260723 (HSWM 2트리 공유 노드, body 덮어씀).
//
// 실행 순서: 0(전수조사, 읽기) → 1 → 2 → 3(고아 귀속) → 4(제약 교체) → 5(검증).
// 주의: NODE KEY(Enterprise)가 아니라 복합 UNIQUE(Community)를 쓰므로 tree 없는 노드가
// 남아 있어도 4는 성공한다(제약 면제) — 무리하게 전원 마킹할 필요 없음. 실적용 교훈은 3번 주석.

// 0) 전수조사 — tree 미보유 질문과 공유(충돌) 질문 목록 (읽기 전용)
// MATCH (q:OpenQuestion) WHERE q.tree IS NULL
// OPTIONAL MATCH (t:LakatosTree)-[:HAS_FRONTIER]->(q)
// RETURN q.name AS qname, collect(DISTINCT t.name) AS trees, size(collect(DISTINCT t.name)) AS n_trees
// ORDER BY n_trees DESC;

// 1) 단일 트리 질문 — tree 박기 (PrismFinding:OpenQuestion 허브 질문 포함)
MATCH (t:LakatosTree)-[:HAS_FRONTIER]->(q:OpenQuestion)
WHERE q.tree IS NULL
WITH q, collect(DISTINCT t.name) AS trees
WHERE size(trees) = 1
SET q.tree = trees[0];

// 2) 공유 질문(충돌) — 트리별 복제 후 원본은 첫 트리 소유로
//    (복제본은 properties 전체 복사 → body/status/n_visits 보존, tree 만 각자)
MATCH (q:OpenQuestion) WHERE q.tree IS NULL
MATCH (t:LakatosTree)-[:HAS_FRONTIER]->(q)
WITH q, collect(DISTINCT t) AS attached WHERE size(attached) > 1
UNWIND attached[1..] AS t
CREATE (q2:OpenQuestion)
SET q2 = properties(q), q2.tree = t.name
CREATE (t)-[:HAS_FRONTIER]->(q2)
WITH DISTINCT q
MATCH (t:LakatosTree)-[r:HAS_FRONTIER]->(q)
WITH q, collect({t: t, r: r}) AS xs
SET q.tree = xs[0].t.name
FOREACH (x IN xs[1..] | DELETE x.r);

// 2b) RAISES_QUESTION 재연결 — raising 노드의 트리와 다른 사본을 가리키는 엣지를 맞는 사본으로
MATCH (t:LakatosTree)-[:HAS_NODE]->(e)-[r:RAISES_QUESTION]->(q:OpenQuestion)
WHERE q.tree IS NOT NULL AND q.tree <> t.name
MATCH (q2:OpenQuestion {name: q.name, tree: t.name})
CREATE (e)-[:RAISES_QUESTION]->(q2)
DELETE r;

// 3) 고아 처리 — ★교훈(2026-07-23 실적용): canonical KG 는 OpenQuestion 라벨을 여러 도메인이
//    공유한다(Game/Lesson/Physics/UpperOntology 등 — question/displayName/mh_eid 스키마).
//    이들에게 tree 를 박으면 외부 도메인 오염. 게다가 Community 복합 UNIQUE 는 tree 없는
//    노드를 그냥 제약에서 면제하므로 일괄 마킹 자체가 불필요하다.
//    따라서 고아는 두 갈래로만 처리:
//    (a) 진짜 lakatotree 고아 — RAISES_QUESTION 으로 연결된 부모 노드의 트리를 귀속:
MATCH (t:LakatosTree)-[:HAS_NODE]->(e:PrismExperiment)-[:RAISES_QUESTION]->(q:OpenQuestion)
WHERE q.tree IS NULL
SET q.tree = t.name;
//    (b) 그 외(tree 없는 외부 도메인/무연결 노드)는 *건드리지 않는다* — 복합 UNIQUE 가 면제.

// 4) 제약 교체 — name 전역 UNIQUE 폐기, (tree, name) 복합 UNIQUE 도입
//    (NODE KEY 는 Enterprise 전용 — Community 에서는 복합 UNIQUE; tree 존재는 writer 가 보장)
DROP CONSTRAINT lkt_open_question_name_unique IF EXISTS;
CREATE CONSTRAINT lkt_open_question_tree_name_key IF NOT EXISTS
FOR (n:OpenQuestion) REQUIRE (n.tree, n.name) IS UNIQUE;

// 5) 검증 (읽기 전용)
// MATCH (q:OpenQuestion) RETURN count(q) AS total, count(q.tree) AS with_tree;
// MATCH (q:OpenQuestion) WHERE q.tree IS NOT NULL
//   WITH q.tree AS t, q.name AS n, count(*) AS c WHERE c > 1 RETURN t, n, c;   // 0 건이어야 함
// SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties
//   WHERE 'OpenQuestion' IN labelsOrTypes RETURN name, properties;
