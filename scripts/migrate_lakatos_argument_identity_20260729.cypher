// V5 argument identity migration. First run preflight_lakatos_argument_identity_20260729.cypher
// and verify that every result table has zero rows. Then take a backup and run this file with
// cypher-shell --fail-fast. This is additive and preserves every legacy id and relationship.
MATCH (t:LakatosTree)-[:HAS_NODE]->()-[:HAS_ARGUMENT]->(a:Argument)
WITH DISTINCT t, a, substring(a.id, size(t.name)+1) AS local_id
SET a:LakatosArgument, a.tree_name=t.name, a.local_id=local_id,
    a.identity_migrated_at=coalesce(a.identity_migrated_at, datetime()),
    a.identity_migration=coalesce(
      a.identity_migration, 'lakatos-argument-identity-20260729');

CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS
FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE;
