// Programme sync depends on one global identity for each semantic anchor.
// Inspect and reconcile duplicates before applying this migration.
CREATE CONSTRAINT lkt_semantic_anchor_name_unique IF NOT EXISTS
FOR (a:SemanticAnchor) REQUIRE a.name IS UNIQUE;
