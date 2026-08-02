// PRECONDITION: target-bound writer drain was revalidated immediately before this statement.
// Community-compatible uniqueness rejects duplicate non-null ids. Neo4j uniqueness
// deliberately ignores a missing property; the exhaustive pre/postflight therefore
// rejects every missing/null id and no supported writer creates one.
CREATE CONSTRAINT lkt_outbox_id_unique IF NOT EXISTS
FOR (n:OutboxEntry) REQUIRE n.id IS UNIQUE;

// Stable critique retries address the same Argument by tree/local id.  This
// schema-level guard is the second line behind the tree-scoped CAS lock.
CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS
FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE;

// Cross-store writer election is fenced again inside every critique Neo4j
// transaction.  A uniqueness constraint is mandatory: two same-name lease
// nodes would let two different owner tokens each match a valid-looking row.
CREATE CONSTRAINT lkt_runtime_writer_lease_name_unique IF NOT EXISTS
FOR (n:RuntimeWriterLease) REQUIRE n.name IS UNIQUE;

MERGE (lease:RuntimeWriterLease {name:'critique-history-writer-v1'})
ON CREATE SET lease.generation=0;
