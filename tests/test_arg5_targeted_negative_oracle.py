"""Synthetic contract tests for the preregistered ARG-5 bundle judge."""
from __future__ import annotations

import hashlib
import json

from judges import arg5_targeted_negative_oracle as oracle


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _phase(name, tests, *, status, accepted=True, detail="AssertionError: ownership"):
    return {
        "phase": name,
        "accepted": accepted,
        "observed": "GREEN" if status == "passed" else "RED",
        "source_sha256": "b" * 64 if "targeted" in name else "a" * 64,
        "junit": {
            "cases": [
                {"name": test, "status": status, "detail": None if status == "passed" else detail}
                for test in tests
            ]
        },
    }


def _bundle(tmp_path, *, targeted_detail="AssertionError: ownership"):
    phases = {
        "positive.json": _phase("positive", oracle.ALL_TESTS, status="passed"),
        "negative_historical.json": _phase(
            "negative_historical_arg_1_4", oracle.HISTORICAL_TESTS, status="failed"
        ),
        "negative_arg5_claim.json": _phase(
            "negative_targeted_arg_5_claim",
            (oracle.TARGET_TEST,),
            status="failed",
            detail=targeted_detail,
        ),
        "restored_positive.json": _phase(
            "restored_positive", oracle.ALL_TESTS, status="passed"
        ),
    }
    for filename, value in phases.items():
        _write_json(tmp_path / filename, value)
    mutation = {
        "mutation_id": "arg5-remove-on-create-claim",
        "replacements": 1,
        "marker_removed": True,
        "source_before_sha256": "a" * 64,
        "source_after_sha256": "b" * 64,
    }
    _write_json(tmp_path / "arg5_claim_mutation.json", mutation)
    sequence = []
    for phase, filename in oracle.PHASE_FILES:
        sequence.append(
            {
                "phase": phase,
                "path": filename,
                "sha256": hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest(),
            }
        )
    receipt = {
        "complete": True,
        "canonical_worktree_mutated": False,
        "bindings": {
            "service_sha256": "a" * 64,
            "targeted_judge_sha256": hashlib.sha256(
                oracle.Path(oracle.__file__).resolve().read_bytes()
            ).hexdigest(),
        },
        "sequence": sequence,
    }
    _write_json(tmp_path / "receipt.json", receipt)


def test_preregistered_judge_accepts_exact_semantic_red_sequence(tmp_path):
    _bundle(tmp_path)

    result = oracle.judge(tmp_path)

    assert result["metric"] == 0
    assert result["status"] == "PASS"


def test_preregistered_judge_rejects_pool_failure_as_nonsemantic(tmp_path):
    _bundle(tmp_path, targeted_detail="psycopg2.pool.PoolError: pool exhausted")

    result = oracle.judge(tmp_path)

    assert result["metric"] > 0
    assert "targeted_failure_not_assertion" in result["failures"]
    assert f"targeted_infra_failure:{oracle.TARGET_TEST}" in result["failures"]
