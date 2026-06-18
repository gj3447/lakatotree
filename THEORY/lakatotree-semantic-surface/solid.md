# SOLID Axis

Prometheus conclusion: SRP must be interpreted as responsibility and reason to
change, not as file count or class count.

Patch decision: keep one primary `owner_sourceId` per semantic unit, but add
`change_actor` so the owner uniqueness rule has a reason. This blocks both
failure modes:

- prose-only meaning with no accountable code owner;
- artificial code splitting that exists only to satisfy a LOC intuition.

DIP corollary: the validator remains pure over JSON and a Longinus manifest. It
does not call FastAPI, Cypher, or live KG.

