// Gate-3 append-only temporal adjunct identities.  Neo4j uniqueness ignores a
// missing property, so predeploy and startup audits also reject every malformed,
// null, duplicated, orphaned, or multiply-bound temporal node.
CREATE CONSTRAINT lkt_prediction_temporal_commitment_sha_unique IF NOT EXISTS
FOR (n:PredictionTemporalCommitment) REQUIRE n.commitment_sha256 IS UNIQUE;

CREATE CONSTRAINT lkt_prediction_temporal_commitment_target_unique IF NOT EXISTS
FOR (n:PredictionTemporalCommitment)
REQUIRE (n.tree_incarnation_id, n.tree, n.tag,
         n.prediction_receipt_sha256) IS UNIQUE;

CREATE CONSTRAINT lkt_temporal_proof_sidecar_sha_unique IF NOT EXISTS
FOR (n:TemporalProofSidecar) REQUIRE n.sidecar_sha256 IS UNIQUE;

CREATE CONSTRAINT lkt_temporal_proof_sidecar_target_unique IF NOT EXISTS
FOR (n:TemporalProofSidecar)
REQUIRE (n.tree_incarnation_id, n.tree, n.tag,
         n.verdict_receipt_sha256) IS UNIQUE;
