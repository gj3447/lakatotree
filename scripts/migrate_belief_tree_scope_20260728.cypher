// V1 state-isolation migration: materialize a tree-owned Belief for every legacy/global link.
// Non-destructive: legacy nodes and HAS_BELIEF edges remain as provenance; SUPERSEDED_BY records the replacement.
MATCH (t:LakatosTree)-[:HAS_BELIEF]->(legacy:Belief)
WHERE legacy.tree IS NULL OR legacy.tree <> t.name
WITH t, legacy
MERGE (scoped:Belief {tree:t.name, belief_id:legacy.belief_id})
ON CREATE SET scoped += properties(legacy)
SET scoped.tree=t.name, scoped.belief_id=legacy.belief_id,
    scoped.scope_migrated_at=datetime(), scoped.scope_migration='belief-tree-scope-20260728'
MERGE (t)-[:HAS_BELIEF]->(scoped)
MERGE (legacy)-[:SUPERSEDED_BY]->(scoped);

CREATE CONSTRAINT lkt_belief_tree_id_key IF NOT EXISTS
FOR (n:Belief) REQUIRE (n.tree, n.belief_id) IS UNIQUE;
