"""fix_harness-local pytest config.

Registers the `integration` marker so the LAKATOS_IT-gated #16/#17 receipt does not
emit PytestUnknownMarkWarning when fix_harness is run in isolation (tests/integration
registers the same marker in its own conftest for the integration tier).
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: real-backend (Neo4j/PG) tier — skipped unless LAKATOS_IT=1",
    )
