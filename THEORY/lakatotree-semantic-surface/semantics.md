# Semantics Axis

Prometheus conclusion: semantic density becomes real when the shared language is
executable. The repo already has executable tests and Longinus-bound owners; the
gap was that a unit did not say which actor/reason makes the owner responsible.

Patch decision: every `SemanticUnit` now carries `change_actor`.

This follows the BDD/executable-spec idea without introducing Gherkin or a new
test framework.

