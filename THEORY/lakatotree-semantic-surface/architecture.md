# Architecture Axis

Prometheus conclusion: this is an architecture decision, not only a test tweak.

Decision:

The semantic surface is a critical subset of `docs/meaning_units.json`, focused
on cross-cutting methodology boundaries that must not drift. It does not replace
the broader meaning registry.

Consequence:

New high-level claims should either enter `docs/semantic_surface.json` with an
owner, actor, tests, docs, and source refs, or remain only in the broader
`meaning_units.json` registry as covered/gap material.

