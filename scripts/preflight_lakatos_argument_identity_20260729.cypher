// Read-only blockers for migrate_lakatos_argument_identity_20260729.cypher.
// Every result table below must have zero rows. Any row means: stop; do not apply migration.

// Tree names form the namespace prefix and must be unique, non-empty single segments.
MATCH (t:LakatosTree)
WITH t.name AS tree, count(t) AS copies
WHERE tree IS NULL OR tree='' OR tree CONTAINS '/' OR copies <> 1
RETURN 'TREE_IDENTITY' AS blocker, tree, copies
ORDER BY tree;

// Each LakatoTree critique Argument must belong to exactly one tree and node, and its persisted
// id must be exactly <tree>/<one non-empty local segment>.
MATCH (t:LakatosTree)-[:HAS_NODE]->(e)-[:HAS_ARGUMENT]->(a:Argument)
WITH a, collect(DISTINCT t.name) AS trees,
     collect(DISTINCT elementId(e)) AS node_refs
WITH a, trees, node_refs,
     CASE WHEN size(trees)=1 AND a.id STARTS WITH trees[0]+'/'
          THEN substring(a.id, size(trees[0])+1) ELSE null END AS local_id
WHERE a.id IS NULL OR size(trees) <> 1 OR size(node_refs) <> 1
   OR local_id IS NULL OR local_id='' OR local_id CONTAINS '/'
RETURN 'ARGUMENT_SHAPE_OR_SCOPE' AS blocker, a.id AS argument_id,
       trees, node_refs, local_id
ORDER BY argument_id;

// Distinct nodes sharing one full id would make the uniqueness constraint fail.
MATCH (:LakatosTree)-[:HAS_NODE]->()-[:HAS_ARGUMENT]->(a:Argument)
WITH a.id AS argument_id, count(DISTINCT a) AS copies
WHERE argument_id IS NULL OR copies > 1
RETURN 'ARGUMENT_ID_DUPLICATE' AS blocker, argument_id, copies
ORDER BY argument_id;
