# ooptdd Tier-1 external-store benchmark — PASS

> External-store arrival evidence over the five fixed T1 scenarios against one compose OpenObserve (v0.14.7) endpoint, with seeded repetitions and Wilson intervals. Not a claim about other backends, other versions, or a production trace distribution.

## ooptdd gate — 🟢 GREEN

- **cid**: `ooptdd-tier1-arrival-v0-seed20260723`
- **backend**: `tier1-external-store`

| check | result | detail |
|---|---|---|
| `T1-loss-drop` | ✅ pass | {"got": 1.0, "want": 1.0} |
| `T1-loss-401` | ✅ pass | {"got": 1.0, "want": 1.0} |
| `T1-lag` | ✅ pass | {"got": 1.0, "want": 1.0} |
| `T1-outage` | ⏭ inconclusive | {"got": 1.0, "want": 1.0} |
| `T1-restore` | ✅ pass | {"got": 1.0, "want": 1.0} |

Re-verify independently: `ooptdd verify ooptdd-tier1-arrival-v0-seed20260723 --backend <your-backend>`
