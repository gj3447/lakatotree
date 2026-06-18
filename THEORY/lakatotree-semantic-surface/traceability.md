# Traceability Axis

Prometheus conclusion: semantic units should be traceable both forward and back.

Forward path:

`meaning_id -> owner_sourceId -> tests/docs`

Backward path:

`Longinus binding / repo source / KG finding -> semantic unit`

Patch decision: every semantic unit now carries `source_refs`, using three
prefixes:

- `repo:` local artifact evidence.
- `kg:` KG finding or anchor evidence.
- `external:` upper-world source evidence.

