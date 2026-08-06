"""Replay portability gate: strict tiers accept only repo-relative artifact identities."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from lakatos.io.reconcile import validate_history_record
from lakatos.io.replay import ProducerReplayVerdict
import server.contexts.tree.judgement_service as judgement_module
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result
from server.file_hashing import file_sha


class PortableKg:
    """Fresh submit double with observable mutation and preregistration boundaries."""

    def __init__(self, *, tier: str | None, psha: str | None):
        self.tier = tier
        self.psha = psha
        self.tx_ops: list[list[tuple[str, dict]]] = []

    def __call__(self, query: str, **_params):
        if "pred_metric AS m" in query:
            return [{
                "m": "seam", "d": "lower", "b": 10.0, "nb": 0.0,
                "scale": "ratio", "novel": "", "vsrc": None,
                "nmet": None, "ndir": None, "nthr": None, "psha": self.psha,
                "pred_registered_at": "2026-08-06", "node_state": "PREDICTED",
                "judged_at": None, "existing_metric_value": None,
                "existing_result_path": "", "existing_verdict": None,
                "existing_lstat": None, "prev_receipt_sha": None,
                "closes": None, "n_opened": 0, "hard_core": "",
                "require_novel_anchor": False, "assurance_tier": self.tier,
                "attestor_dids": None, "research_layout": None,
                "layout_owner_did": None, "layout_sig": None,
                "witness_dids": None,
            }]
        return []

    def tx(self, ops):
        self.tx_ops.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


@pytest.fixture
def portable_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    script = artifacts / "score.py"
    result = artifacts / "result.json"
    script.write_text("def score():\n    return 1.0\n", encoding="utf-8")
    result.write_text('{"metric":1.0}\n', encoding="utf-8")
    monkeypatch.setattr(judgement_module.longinus, "ROOT", root)
    monkeypatch.setenv(
        "LAKATOS_REPLAY_CACHE_ROOT", str(tmp_path / "server-replay-cache")
    )
    return root, script, result


def _service(kg: PortableKg, histories: list, producer_calls: list) -> JudgementService:
    def producer(*args):
        producer_calls.append(args)
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    return JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=lambda *args, **kwargs: histories.append((args, kwargs)),
        foundation=lambda _name: None,
        reproducible_for_node=lambda *_args: None,
        producer_replay_submit=producer,
    )


def _submit(
    portable_repo,
    *,
    tier: str | None = "receipted",
    script_path: str = "artifacts/score.py",
    result_path: str = "artifacts/result.json",
    script_sha: str | None = None,
    prereg_sha: str | None | object = ...,
):
    _root, script, _result = portable_repo
    actual_sha = file_sha(str(script))
    if script_sha is None:
        script_sha = actual_sha
    if prereg_sha is ...:
        prereg_sha = actual_sha
    kg = PortableKg(tier=tier, psha=prereg_sha)
    histories: list = []
    producer_calls: list = []
    request = Result(
        metric_value=1.0,
        script=script_path,
        result_path=result_path,
        script_sha=script_sha,
    )
    service = _service(kg, histories, producer_calls)
    return service, request, kg, histories, producer_calls


@pytest.mark.parametrize("tier", ["receipted", "anchored"])
@pytest.mark.parametrize(
    "case",
    [
        "absolute_script",
        "absolute_result",
        "script_traversal",
        "result_traversal",
        "symlink_escape",
        "file_symbol",
    ],
)
def test_strict_tiers_reject_nonportable_artifact_paths(
    portable_repo, tmp_path, tier, case
):
    root, script, result = portable_repo
    outside_script = tmp_path / "outside.py"
    outside_result = tmp_path / "outside.json"
    outside_script.write_text("print(1.0)\n", encoding="utf-8")
    outside_result.write_text('{"metric":1.0}\n', encoding="utf-8")
    script_path = "artifacts/score.py"
    result_path = "artifacts/result.json"
    script_sha = file_sha(str(script))

    if case == "absolute_script":
        script_path = str(script)
    elif case == "absolute_result":
        result_path = str(result)
    elif case == "script_traversal":
        script_path = "../outside.py"
        script_sha = file_sha(str(outside_script))
    elif case == "result_traversal":
        result_path = "../outside.json"
    elif case == "symlink_escape":
        link = root / "artifacts" / "escape.py"
        link.symlink_to(outside_script)
        script_path = "artifacts/escape.py"
        script_sha = file_sha(str(link))
    elif case == "file_symbol":
        script_path = "artifacts/score.py::score"

    service, request, kg, histories, producer_calls = _submit(
        portable_repo,
        tier=tier,
        script_path=script_path,
        result_path=result_path,
        script_sha=script_sha,
        prereg_sha=script_sha,
    )
    with pytest.raises(HTTPException) as exc:
        service.submit_test_result("T", "seam", request)
    assert exc.value.status_code == 422
    assert "portable" in str(exc.value.detail).lower()
    assert producer_calls == [] and kg.tx_ops == [] and histories == []


@pytest.mark.parametrize(
    "client_sha",
    [None, "a" * 63, "A" * 64, "0" * 64],
)
def test_strict_artifact_submit_requires_exact_lowercase_client_sha(
    portable_repo, client_sha
):
    _root, script, _result = portable_repo
    actual = file_sha(str(script))
    service, request, kg, histories, producer_calls = _submit(
        portable_repo,
        script_sha=client_sha,
        prereg_sha=actual,
    )
    if client_sha is None:
        request.script_sha = None
    with pytest.raises(HTTPException) as exc:
        service.submit_test_result("T", "seam", request)
    assert exc.value.status_code == 422
    expected_detail = "불일치" if client_sha == "0" * 64 else "lowercase sha256"
    assert expected_detail in str(exc.value.detail)
    assert producer_calls == [] and kg.tx_ops == [] and histories == []


@pytest.mark.parametrize(
    "prereg_sha",
    [None, "a" * 63, "A" * 64, "0" * 64],
)
def test_strict_artifact_submit_requires_exact_lowercase_preregistered_sha(
    portable_repo, prereg_sha
):
    service, request, kg, histories, producer_calls = _submit(
        portable_repo,
        prereg_sha=prereg_sha,
    )
    with pytest.raises(HTTPException) as exc:
        service.submit_test_result("T", "seam", request)
    assert exc.value.status_code == 409
    expected_detail = "불일치" if prereg_sha == "0" * 64 else "lowercase sha256"
    assert expected_detail in str(exc.value.detail)
    assert producer_calls == [] and kg.tx_ops == [] and histories == []


@pytest.mark.parametrize("tier", ["receipted", "anchored"])
def test_strict_portable_artifacts_execute_once_and_preserve_raw_request_identity(
    portable_repo, tier
):
    service, request, kg, histories, producer_calls = _submit(
        portable_repo, tier=tier
    )
    out = service.submit_test_result("T", "seam", request)
    params = kg.tx_ops[0][0][1]
    expected_request_json = validate_history_record(
        "T",
        "test_result",
        "seam",
        {
            "tree": "T",
            "tag": "seam",
            "request": request.model_dump(),
            "cycle_claim": None,
            "cycle_request": None,
        },
        "ob-test-result-preflight",
    )
    assert params["submit_request_sha256"] == hashlib.sha256(
        expected_request_json.encode("utf-8")
    ).hexdigest()
    assert len(producer_calls) == 1 and len(kg.tx_ops) == 1
    assert len(histories) == 1 and out["replay_authoritative"] is True


@pytest.mark.parametrize("tier", [None, "notebook"])
def test_permissive_tiers_keep_absolute_temp_artifact_compatibility(
    portable_repo, tier
):
    _root, script, result = portable_repo
    service, request, kg, histories, producer_calls = _submit(
        portable_repo,
        tier=tier,
        script_path=str(script),
        result_path=str(result),
    )
    out = service.submit_test_result("T", "seam", request)
    assert len(producer_calls) == 1 and len(kg.tx_ops) == 1
    assert len(histories) == 1 and out["replay_authoritative"] is True


def test_strict_resultless_submit_does_not_invent_an_artifact_requirement(
    portable_repo,
):
    _root, script, _result = portable_repo
    service, request, kg, histories, producer_calls = _submit(
        portable_repo,
        tier="anchored",
        script_path=str(script),
        result_path="",
        script_sha=None,
        prereg_sha=None,
    )
    request.script_sha = None
    out = service.submit_test_result("T", "seam", request)
    assert producer_calls == [] and len(kg.tx_ops) == 1 and len(histories) == 1
    assert out["replay_authoritative"] is False


def test_portable_resolver_rejects_nul_without_pathlib_crash(portable_repo):
    resolved, normalized, info = judgement_module.isolate_portable_replay_file(
        "artifacts/score.py\x00", judgement_module.SCRIPT_MAX_BYTES
    )
    assert resolved is None and normalized == ""
    assert info["reason"] == "nul_byte"


def test_strict_capture_rejects_parent_symlink_swap_after_containment_check(
    portable_repo, tmp_path, monkeypatch
):
    """Containment and source-open must be one fd-anchored operation."""
    root, script, _result = portable_repo
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "score.py").write_bytes(script.read_bytes())
    (attacker / "result.json").write_text(
        '{"metric":999.0,"source":"outside"}\n', encoding="utf-8"
    )
    original = judgement_module.isolate_portable_replay_file
    calls = 0

    def swap_after_both_checks(file_str, max_bytes):
        nonlocal calls
        resolved = original(file_str, max_bytes)
        calls += 1
        if calls == 2:
            (root / "artifacts").rename(root / "artifacts-safe")
            (root / "artifacts").symlink_to(attacker, target_is_directory=True)
        return resolved

    monkeypatch.setattr(
        judgement_module, "isolate_portable_replay_file", swap_after_both_checks
    )
    service, request, kg, histories, producer_calls = _submit(portable_repo)
    with pytest.raises(HTTPException) as exc:
        service.submit_test_result("T", "seam", request)
    assert exc.value.status_code == 422
    assert producer_calls == [] and kg.tx_ops == [] and histories == []


def test_strict_snapshot_uses_captured_bytes_after_source_swap(
    portable_repo, tmp_path, monkeypatch
):
    """Once both fd reads finish, later source-path swaps cannot alter replay bytes."""
    root, script, _result = portable_repo
    attacker = tmp_path / "attacker-after-capture"
    attacker.mkdir()
    (attacker / "score.py").write_bytes(script.read_bytes())
    (attacker / "result.json").write_text(
        '{"metric":999.0,"source":"outside"}\n', encoding="utf-8"
    )
    original = judgement_module.replay_artifact_mod.read_portable_repo_file
    calls = 0

    def swap_after_both_captures(**kwargs):
        nonlocal calls
        captured = original(**kwargs)
        calls += 1
        if calls == 2:
            (root / "artifacts").rename(root / "artifacts-safe")
            (root / "artifacts").symlink_to(attacker, target_is_directory=True)
        return captured

    monkeypatch.setattr(
        judgement_module.replay_artifact_mod,
        "read_portable_repo_file",
        swap_after_both_captures,
    )
    actual_sha = file_sha(str(script))
    kg = PortableKg(tier="receipted", psha=actual_sha)
    histories: list = []
    replayed_results: list[str] = []

    def producer(_script_path, result_path, _recorded):
        replayed_results.append(Path(result_path).read_text(encoding="utf-8"))
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    service = JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=lambda *args, **kwargs: histories.append((args, kwargs)),
        foundation=lambda _name: None,
        reproducible_for_node=lambda *_args: None,
        producer_replay_submit=producer,
    )
    out = service.submit_test_result(
        "T",
        "seam",
        Result(
            metric_value=1.0,
            script="artifacts/score.py",
            result_path="artifacts/result.json",
            script_sha=actual_sha,
        ),
    )
    assert replayed_results == ['{"metric":1.0}\n']
    assert len(kg.tx_ops) == 1 and len(histories) == 1
    assert out["replay_authoritative"] is True


def test_portable_capture_normalizes_close_failure_and_attempts_every_fd(
    portable_repo, monkeypatch
):
    root, _script, _result = portable_repo
    artifact_module = judgement_module.replay_artifact_mod
    real_close = artifact_module.os.close
    close_attempts: list[int] = []

    def fail_first_close_after_closing(fd):
        real_close(fd)
        close_attempts.append(fd)
        if len(close_attempts) == 1:
            raise OSError("injected close failure")

    monkeypatch.setattr(artifact_module.os, "close", fail_first_close_after_closing)
    with pytest.raises(artifact_module.ReplayArtifactError, match="fd close failed"):
        artifact_module.read_portable_repo_file(
            repo_root=root,
            relative_path="artifacts/score.py",
            max_bytes=judgement_module.SCRIPT_MAX_BYTES,
        )
    assert len(close_attempts) == 3
