"""Resource-gated harness build: durable target fence, recovery, and settlement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import stat
import subprocess
import sys
import time

import pytest

from lakatos import harness_run
from lakatos.io import local_build_execution
from lakatos.build_execution import (
    BuildAdmissionPolicy,
    BuildExecutionPolicy,
    BuildExecutionResult,
    BuildExecutionSpec,
    BuildRun,
    BuildTerminalStatus,
    DEFAULT_BUILD_ADMISSION_POLICY,
    DEFAULT_BUILD_EXECUTION_POLICY,
    ResourceBuildConfigError,
    ResourceBuildOutcomeUnknown,
    environment_sha256,
    reserved_compute_wall_ms,
    split_stream_budget,
)
from lakatos.harness import BuildFailed, CycleSpec, LakatoHarness
from lakatos.io.local_build_execution import (
    BuildInputVerifierPort,
    BuildInputManifestError,
    BuildTargetError,
    BuildTargetOutcomeUnknown,
    BuildDeploymentPolicyPort,
    DeadlineBoundBuildInputVerifierPort,
    DeadlineBoundSQLiteFencedBuildEffect,
    ResourceGatedBuildRunner,
    SQLiteFencedBuildEffect,
    VerifiedBuildInputManifest,
    closed_build_environment,
    darwin_sandbox_argv,
    darwin_sandbox_profile,
    resource_root_metadata_violation,
    resource_root_path_violation,
    resource_gated_build_runner_from_environment,
)
from lakatos.io.resource_execution import HMACPermitAuthenticator, ResourceExecutionGate
from lakatos.io.resource_journal import (
    BudgetIdentityConflict,
    JournalSchemaMismatch,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
    TrustedAnchorUnavailable,
)
from lakatos.resource_coordination import (
    GrantStatus,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    StartGrant,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _TestIsolation:
    adapter = "test.provider-denied-isolation"
    adapter_version = "1"
    policy_sha256 = _sha("test-provider-denied-isolation-v1")
    denies_provider_network = True
    protects_resource_root = True

    @staticmethod
    def argv(spec):
        return (spec.shell, "-c", spec.command)


class _StaticInputVerifier:
    def __init__(self, manifest_sha256: str) -> None:
        self.manifest_sha256 = manifest_sha256

    def verify(self) -> None:
        return None

    def verify_until(self, _deadline_monotonic_ns: int) -> None:
        self.verify()


class _RollbackAfterDispatchClock:
    def __init__(self) -> None:
        self._calls = 0

    def now_utc(self) -> str:
        self._calls += 1
        if self._calls <= 2:
            return "2026-08-07T12:00:02Z"
        return "2026-08-07T11:59:59Z"


class _Clock:
    def __init__(self, now: str = "2026-08-07T12:00:04Z") -> None:
        self.now = now

    def now_utc(self) -> str:
        return self.now


def _command(marker: Path, *, exit_code: int = 0) -> str:
    source = (
        "from pathlib import Path; "
        f"p=Path({str(marker)!r}); "
        "n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); "
        "print('build-output'); "
        f"raise SystemExit({exit_code})"
    )
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def _write_manifest(root: Path, *relative_paths: str) -> Path:
    manifest = root / "build-input-manifest.json"
    files = []
    for relative in sorted(relative_paths):
        files.append({
            "path": relative,
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        })
    manifest.write_text(json.dumps({
        "schema_version": "lakatotree.build-input-manifest/v1",
        "files": files,
    }))
    return manifest


def _runtime(
    tmp_path: Path,
    *,
    command: str,
    effect_id: str = "effect:build:1",
    failure_after_claim=None,
    failure_after_terminal=None,
    input_verifier=None,
    authentication_key: bytes = bytes(range(64, 96)),
    utc_now=None,
    monotonic_ns=None,
    gate_clock=None,
    timeout_seconds: int = 10,
    target_timeout_seconds: float = 10.0,
    output_tail_bytes: int = 65_536,
    max_output_bytes: int = 16_777_216,
    effect_type=DeadlineBoundSQLiteFencedBuildEffect,
) -> tuple[
    ResourceGatedBuildRunner,
    SQLiteResourceJournal,
    DeadlineBoundSQLiteFencedBuildEffect | SQLiteFencedBuildEffect,
]:
    scope = "harness-build:test-tree"
    child_environment = {"PATH": os.environ.get("PATH", "")}
    isolation = _TestIsolation()
    selected_input_verifier = input_verifier or _StaticInputVerifier(
        _sha("source-tree-v1")
    )
    input_manifest_sha256 = selected_input_verifier.manifest_sha256
    spec = BuildExecutionSpec(
        command=command,
        cwd=str(tmp_path.resolve()),
        shell="/bin/sh",
        timeout_seconds=timeout_seconds,
        environment_sha256=environment_sha256(child_environment),
        input_manifest_sha256=input_manifest_sha256,
        isolation_adapter=isolation.adapter,
        isolation_version=isolation.adapter_version,
        isolation_policy_sha256=isolation.policy_sha256,
        adapter=effect_type.adapter,
        adapter_version=effect_type.adapter_version,
        output_tail_bytes=output_tail_bytes,
        max_output_bytes=max_output_bytes,
    )
    effect_options = {}
    effect_options["utc_now"] = (
        utc_now if utc_now is not None else lambda: "2026-08-07T12:00:03Z"
    )
    if monotonic_ns is not None:
        effect_options["monotonic_ns"] = monotonic_ns
    effect = effect_type(
        tmp_path / "build-target.sqlite3",
        spec=spec,
        environment=child_environment,
        isolation=isolation,
        input_verifier=selected_input_verifier,
        authentication_key=authentication_key,
        failure_inject_after_claim=failure_after_claim,
        failure_inject_after_terminal_commit=failure_after_terminal,
        timeout_seconds=target_timeout_seconds,
        **effect_options,
    )
    fence = effect.allocate_fence(scope=scope, effect_id=effect_id)
    journal = SQLiteResourceJournal(
        tmp_path / "resource.sqlite3",
        trusted_anchor=SignedAppendOnlyFileAnchor(
            tmp_path / "resource-anchor",
            signing_key=bytes(range(32)),
        ),
    )
    state = ResourceState.create(
        budget_id="budget:harness-build:test-tree",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(compute_wall_ms=30_000),
    )
    try:
        journal.initialize(state)
    except BudgetIdentityConflict:
        # Restart construction intentionally reopens the exact same durable state.
        snapshot = journal.load(scope)
        assert snapshot.state.budget == state.budget
    request = RequestGrant(
        command_id="request:" + effect_id,
        grant_id="grant:" + effect_id,
        fence_token=fence,
        observed_at="2026-08-07T12:00:00Z",
        expires_at="2026-08-07T12:10:00Z",
        estimate=ResourceEstimate(
            work_id="work:" + effect_id,
            attempt_id="attempt:" + effect_id,
            workload_sha256=spec.workload_sha256,
            adapter=effect.adapter,
            adapter_version=effect.adapter_version,
            upper_bound=ResourceVector(
                compute_wall_ms=reserved_compute_wall_ms(spec)
            ),
            valid_until="2026-08-07T12:10:00Z",
        ),
    )
    start = StartGrant(
        command_id=effect_id,
        grant_id=request.grant_id,
        fence_token=fence,
        workload_sha256=spec.workload_sha256,
        observed_at="2026-08-07T12:00:01Z",
    )
    gate = ResourceExecutionGate(
        scope=scope,
        journal=journal,
        effect=effect,
        clock=gate_clock or _Clock(),
        permit_authenticator=HMACPermitAuthenticator(
            signing_key=bytes(range(32, 64)),
            issuer="test:harness-build",
        ),
        settlement_effect=effect,
    )
    return (
        ResourceGatedBuildRunner(
            scope=scope,
            journal=journal,
            gate=gate,
            effect=effect,
            request=request,
            start=start,
        ),
        journal,
        effect,
    )


def test_gated_build_runs_once_and_settles_measured_compute(tmp_path):
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, journal, _effect = _runtime(tmp_path, command=command)

    result = runner(command)

    assert isinstance(result, BuildRun)
    assert result.returncode == 0
    assert "build-output" in result.output
    assert marker.read_text() == "1"
    grant = journal.load("harness-build:test-tree").state.grant("grant:effect:build:1")
    assert grant.status is GrantStatus.SETTLED
    assert grant.actual.compute_wall_ms >= 0
    assert grant.actual.llm_input_tokens == grant.actual.llm_output_tokens == 0
    assert result.resource_provenance["effect_id"] == "effect:build:1"
    assert result.resource_provenance["settlement_receipt_sha256"]

    # A new adapter/runner process view exact-readbacks the terminal result.
    restarted, restarted_journal, _ = _runtime(tmp_path, command=command)
    replay = restarted(command)
    assert replay == result
    assert marker.read_text() == "1"
    assert restarted_journal.load("harness-build:test-tree").state.revision == 3


def test_terminal_response_loss_recovers_without_redispatch(tmp_path):
    marker = tmp_path / "marker"
    trips = {"count": 0}

    def lose_response(_record):
        trips["count"] += 1
        if trips["count"] == 1:
            raise ConnectionError("response lost after terminal commit")

    command = _command(marker)
    runner, journal, _effect = _runtime(
        tmp_path,
        command=command,
        failure_after_terminal=lose_response,
    )

    result = runner(command)

    assert result.returncode == 0
    assert marker.read_text() == "1"
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_claim_crash_is_unknown_and_never_redispatched(tmp_path):
    marker = tmp_path / "marker"

    def crash(_effect_id):
        raise RuntimeError("crash after durable claim")

    command = _command(marker)
    runner, journal, _effect = _runtime(
        tmp_path,
        command=command,
        failure_after_claim=crash,
    )

    with pytest.raises(ResourceBuildOutcomeUnknown):
        runner(command)
    assert not marker.exists()
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.RECONCILIATION_REQUIRED

    restarted, _journal, _ = _runtime(tmp_path, command=command)
    with pytest.raises(ResourceBuildOutcomeUnknown):
        restarted(command)
    assert not marker.exists()


def test_nonzero_build_is_settled_before_existing_buildfailed_boundary(tmp_path):
    marker = tmp_path / "marker"
    command = _command(marker, exit_code=7)
    runner, journal, _effect = _runtime(tmp_path, command=command)
    calls: list[tuple[str, str]] = []

    def http(method, path, body=None):
        calls.append((method, path))
        if path.endswith("/test_result"):
            return {"verdict": "progressive"}
        if path.endswith("/standing"):
            return {"stands": True}
        return {"ok": True}

    raw_bash_calls: list[str] = []

    def raw_bash(cmd):
        raw_bash_calls.append(cmd)
        return "metric=1", 0

    harness = LakatoHarness(http=http, run_bash=raw_bash, run_build=runner)
    cycle = CycleSpec(
        tree="T",
        tag="v1",
        parent="root",
        metric="tests",
        baseline=0,
        build_cmd=command,
        judge_cmd="echo metric=1",
    )

    with pytest.raises(BuildFailed):
        harness.run_cycle(cycle)

    assert marker.read_text() == "1"
    assert raw_bash_calls == []
    assert not any(path.endswith("/test_result") for _method, path in calls)
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_build_port_is_distinct_from_legacy_judge_port():
    calls: list[tuple[str, str]] = []

    def build(cmd):
        calls.append(("build", cmd))
        return "built", 0

    def bash(cmd):
        calls.append(("judge", cmd))
        return "metric=2", 0

    harness = LakatoHarness(
        http=lambda method, path, body=None: (
            {"verdict": "progressive"}
            if path.endswith("/test_result")
            else {"stands": True}
            if path.endswith("/standing")
            else {"ok": True}
        ),
        run_bash=bash,
        run_build=build,
    )
    harness.run_cycle(CycleSpec(
        tree="T",
        tag="v1",
        parent="root",
        metric="tests",
        baseline=0,
        build_cmd="make",
        judge_cmd="judge",
    ))

    assert calls == [("build", "make"), ("judge", "judge")]


def test_workload_identity_binds_every_declared_execution_input(tmp_path):
    base = dict(
        command="make",
        cwd=str(tmp_path.resolve()),
        shell="/bin/sh",
        timeout_seconds=10,
        environment_sha256=environment_sha256({"PATH": "/bin"}),
        input_manifest_sha256=_sha("inputs-v1"),
        isolation_adapter=_TestIsolation.adapter,
        isolation_version=_TestIsolation.adapter_version,
        isolation_policy_sha256=_TestIsolation.policy_sha256,
    )
    original = BuildExecutionSpec(**base)

    variants = (
        {**base, "command": "make test"},
        {**base, "cwd": str(tmp_path.parent.resolve())},
        {**base, "environment_sha256": environment_sha256({"PATH": "/usr/bin"})},
        {**base, "timeout_seconds": 11},
        {**base, "input_manifest_sha256": _sha("inputs-v2")},
        {**base, "shell": "/usr/bin/sh"},
        {**base, "isolation_adapter": "test.other-isolation"},
        {**base, "isolation_version": "2"},
        {**base, "isolation_policy_sha256": _sha("other-policy")},
        {**base, "execution_policy_sha256": _sha("other-execution-policy")},
        {**base, "process_cleanup_grace_ms": 750},
        {**base, "output_tail_bytes": 32_768},
        {**base, "max_output_bytes": 32_000_000},
    )
    assert all(BuildExecutionSpec(**value).workload_sha256 != original.workload_sha256
               for value in variants)


def test_target_adapter_rejects_exact_live_schema_drift(tmp_path):
    command = _command(tmp_path / "marker")
    _runner, _journal, effect = _runtime(tmp_path, command=command)
    with sqlite3.connect(tmp_path / "build-target.sqlite3") as connection:
        connection.execute(
            "CREATE INDEX unexpected_build_status_index ON build_effects(status)"
        )

    with pytest.raises(BuildTargetError, match="live schema diverged"):
        DeadlineBoundSQLiteFencedBuildEffect(
            tmp_path / "build-target.sqlite3",
            spec=effect.spec,
            environment={"PATH": os.environ.get("PATH", "")},
            isolation=_TestIsolation(),
            input_verifier=_StaticInputVerifier(effect.spec.input_manifest_sha256),
            authentication_key=bytes(range(64, 96)),
        )


def test_corrupt_target_database_is_a_permanent_typed_failure(tmp_path):
    (tmp_path / "build-target.sqlite3").write_bytes(b"not a SQLite database")

    with pytest.raises(BuildTargetError, match="rejected durable state") as error:
        _runtime(tmp_path, command=_command(tmp_path / "marker"))

    assert not isinstance(error.value, BuildTargetOutcomeUnknown)


def test_locked_target_database_is_a_transient_outcome_unknown(tmp_path):
    command = _command(tmp_path / "marker")
    _runner, _journal, effect = _runtime(
        tmp_path,
        command=command,
        target_timeout_seconds=0.01,
    )
    blocker = sqlite3.connect(
        tmp_path / "build-target.sqlite3",
        isolation_level=None,
    )
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(BuildTargetOutcomeUnknown, match="SQLite unavailable"):
            effect.allocate_fence(
                scope="harness-build:locked-target",
                effect_id="effect:locked-target",
            )
    finally:
        blocker.rollback()
        blocker.close()


@pytest.mark.parametrize(
    "detail",
    (
        "database is locked",
        "attempt to write a readonly database",
        "interrupted",
        "disk I/O error",
        "database or disk is full",
        "unable to open database file",
        "locking protocol",
    ),
)
def test_sqlite_error_translation_does_not_require_python_311_constants(
    monkeypatch,
    detail,
):
    for name in (
        "SQLITE_BUSY",
        "SQLITE_LOCKED",
        "SQLITE_READONLY",
        "SQLITE_INTERRUPT",
        "SQLITE_IOERR",
        "SQLITE_FULL",
        "SQLITE_CANTOPEN",
        "SQLITE_PROTOCOL",
    ):
        monkeypatch.delattr(local_build_execution.sqlite3, name, raising=False)

    translated = local_build_execution._translated_target_sqlite_error(
        sqlite3.OperationalError(detail)
    )

    assert isinstance(translated, BuildTargetOutcomeUnknown)


def test_verified_manifest_blocks_stale_terminal_replay_after_input_change(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("v1")
    verifier = VerifiedBuildInputManifest.load(
        _write_manifest(tmp_path, "input.txt"),
        root=tmp_path,
    )
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, _journal, _effect = _runtime(
        tmp_path,
        command=command,
        input_verifier=verifier,
    )

    runner(command)
    input_path.write_text("v2")

    with pytest.raises(ResourceBuildConfigError, match="declared build input changed"):
        runner(command)
    assert marker.read_text() == "1"


def test_manifest_rejects_noncanonical_path_aliases(tmp_path):
    nested = tmp_path / "a"
    nested.mkdir()
    input_path = nested / "b"
    input_path.write_text("v1")
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()

    for alias in ("a//b", "a/./b"):
        manifest = tmp_path / f"manifest-{_sha(alias)}.json"
        manifest.write_text(json.dumps({
            "schema_version": "lakatotree.build-input-manifest/v1",
            "files": [{"path": alias, "sha256": digest}],
        }))
        with pytest.raises(BuildInputManifestError, match="normalized relative POSIX"):
            VerifiedBuildInputManifest.load(manifest, root=tmp_path)


def test_target_hmac_rejects_terminal_blob_forgery(tmp_path):
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, _journal, _effect = _runtime(tmp_path, command=command)
    runner(command)

    target = tmp_path / "build-target.sqlite3"
    with sqlite3.connect(target) as connection:
        raw = connection.execute(
            "SELECT result_blob FROM build_effects WHERE effect_id = ?",
            ("effect:build:1",),
        ).fetchone()[0]
        payload = json.loads(bytes(raw).decode("utf-8"))
        payload["output_tail"] = "forged-success"
        forged = BuildExecutionResult.from_dict(payload)
        forged_blob = json.dumps(
            forged.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        connection.execute(
            "UPDATE build_effects SET result_blob = ?, result_sha256 = ? "
            "WHERE effect_id = ?",
            (sqlite3.Binary(forged_blob), forged.evidence_sha256, "effect:build:1"),
        )

    restarted, _journal, _effect = _runtime(tmp_path, command=command)
    with pytest.raises(BuildTargetError, match="authentication failed"):
        restarted(command)
    assert marker.read_text() == "1"


def test_target_authenticates_raw_blob_before_schema_decode(tmp_path):
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, _journal, _effect = _runtime(tmp_path, command=command)
    runner(command)

    with sqlite3.connect(tmp_path / "build-target.sqlite3") as connection:
        connection.execute(
            "UPDATE build_effects SET result_blob = ? WHERE effect_id = ?",
            (sqlite3.Binary(b"{}"), "effect:build:1"),
        )

    restarted, _journal, _effect = _runtime(tmp_path, command=command)
    with pytest.raises(BuildTargetError, match="authentication failed"):
        restarted(command)
    assert marker.read_text() == "1"


def test_target_blob_query_bounds_bytes_before_python_materialization(tmp_path):
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, _journal, effect = _runtime(tmp_path, command=command)
    runner(command)

    oversized = 8 * 1024 * 1024 + 1
    with sqlite3.connect(tmp_path / "build-target.sqlite3") as connection:
        connection.execute(
            "UPDATE build_effects SET result_blob = zeroblob(?) WHERE effect_id = ?",
            (oversized, "effect:build:1"),
        )

    row = effect._load_row("effect:build:1")
    assert row is not None
    assert row["result_blob_length"] == oversized
    assert row["result_blob"] is None
    with pytest.raises(BuildTargetError, match="exceeds the readback limit"):
        effect.load_terminal_result(
            effect_id="effect:build:1",
            workload_sha256=effect.spec.workload_sha256,
        )


def test_output_limit_is_terminal_metered_and_settled(tmp_path):
    source = "import sys; sys.stdout.write('x' * 8192); sys.stdout.flush()"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        output_tail_bytes=1024,
        max_output_bytes=4096,
    )

    run = runner(command)
    terminal, _receipt = effect.load_terminal_result(
        effect_id="effect:build:1",
        workload_sha256=effect.spec.workload_sha256,
    )

    assert run.returncode == 125
    assert run.timed_out is False
    assert terminal.status is BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED
    assert terminal.returncode is None
    stdout_limit, _stderr_limit = split_stream_budget(4096)
    assert terminal.stdout_bytes == stdout_limit
    assert terminal.stderr_bytes == 0
    assert len(run.output.encode("utf-8")) <= 1024
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_split_stream_budget_is_odd_safe_and_interleaving_invariant():
    assert split_stream_budget(0) == (0, 0)
    assert split_stream_budget(1) == (1, 0)
    assert split_stream_budget(5) == (3, 2)

    def capture(order):
        limits = dict(zip(("stdout", "stderr"), split_stream_budget(5)))
        evidence = {
            name: local_build_execution._BoundedStreamEvidence(tail_bytes=limit)
            for name, limit in limits.items()
        }
        refused = []
        for name, chunk in order:
            stream = evidence[name]
            refused.append(stream.append(
                chunk,
                remaining_bytes=max(limits[name] - stream.byte_count, 0),
            ))
        return {
            name: (stream.sha256, stream.byte_count, stream.tail)
            for name, stream in evidence.items()
        }, tuple(refused)

    first, first_refused = capture((("stdout", b"abcd"), ("stderr", b"xyz")))
    second, second_refused = capture((("stderr", b"xyz"), ("stdout", b"abcd")))

    assert first == second
    assert first["stdout"][1:] == (3, b"abc")
    assert first["stderr"][1:] == (2, b"xy")
    assert first_refused == second_refused == (True, True)


def test_invalid_utf8_tail_stays_within_persisted_byte_contract(tmp_path):
    source = "import sys; sys.stdout.buffer.write(b'\\xff' * 400000); sys.stdout.flush()"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        output_tail_bytes=400_000,
        max_output_bytes=800_000,
    )

    run = runner(command)
    terminal, _receipt = effect.load_terminal_result(
        effect_id="effect:build:1",
        workload_sha256=effect.spec.workload_sha256,
    )

    assert run.returncode == 0
    assert terminal.status is BuildTerminalStatus.EXITED
    assert terminal.stdout_bytes == 400_000
    assert len(terminal.output_tail.encode("utf-8")) <= 400_000
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_stream_read_failure_kills_and_reaps_leader(tmp_path, monkeypatch):
    source = "import time; print('ready', flush=True); time.sleep(10)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"
    runner, _journal, _effect = _runtime(tmp_path, command=command)
    real_popen = subprocess.Popen
    real_read = os.read
    observed: dict[str, object] = {"wait_calls": 0, "spawned": False}

    def recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        real_wait = process.wait

        def recording_wait(*wait_args, **wait_kwargs):
            observed["wait_calls"] = int(observed["wait_calls"]) + 1
            return real_wait(*wait_args, **wait_kwargs)

        process.wait = recording_wait
        observed["process"] = process
        observed["spawned"] = True
        return process

    def unreadable_output(fd, size):
        if not observed["spawned"]:
            return real_read(fd, size)
        raise OSError("injected stream read failure")

    monkeypatch.setattr(local_build_execution.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(local_build_execution.os, "read", unreadable_output)

    with pytest.raises(ResourceBuildOutcomeUnknown):
        runner(command)

    process = observed["process"]
    assert isinstance(process, real_popen)
    assert observed["wait_calls"] >= 1
    assert process.returncode is not None


def test_timeout_kills_reaps_and_settles_as_typed_terminal(tmp_path):
    source = "import time; print('started', flush=True); time.sleep(10)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        timeout_seconds=1,
    )

    run = runner(command)
    terminal, _receipt = effect.load_terminal_result(
        effect_id="effect:build:1",
        workload_sha256=effect.spec.workload_sha256,
    )

    assert run.returncode == 124
    assert run.timed_out is True
    assert terminal.status is BuildTerminalStatus.TIMED_OUT
    assert terminal.returncode is None
    assert "started" in run.output
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_normal_background_descendant_is_killed_before_terminal_result(tmp_path):
    delayed_marker = tmp_path / "delayed-marker"
    child = (
        "import time; from pathlib import Path; time.sleep(0.4); "
        f"Path({str(delayed_marker)!r}).write_text('escaped')"
    )
    leader = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('leader-exit')"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(leader)}"
    runner, journal, _effect = _runtime(tmp_path, command=command)

    result = runner(command)
    time.sleep(0.6)

    assert result.returncode == 0
    assert "leader-exit" in result.output
    assert not delayed_marker.exists()
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED


def test_clock_rollback_still_terminalizes_and_settles_at_monotonic_floor(tmp_path):
    utc_values = iter(("2026-08-07T12:00:03Z", "2026-08-07T11:59:58Z"))
    monotonic_values = iter((1_000_000_000, 1_000_000_000, 2_250_000_000))
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        utc_now=lambda: next(utc_values),
        monotonic_ns=lambda: next(monotonic_values),
        gate_clock=_RollbackAfterDispatchClock(),
    )

    result = runner(command)
    terminal, _receipt = effect.load_terminal_result(
        effect_id="effect:build:1",
        workload_sha256=effect.spec.workload_sha256,
    )
    grant = journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    )

    assert result.returncode == 0
    assert terminal.completed_at == "2026-08-07T12:00:04.250000Z"
    assert grant.status is GrantStatus.SETTLED
    assert grant.measured_at == terminal.completed_at


def test_isolation_capabilities_are_mandatory_before_target_creation(tmp_path):
    class UnsafeIsolation(_TestIsolation):
        denies_provider_network = False

    isolation = UnsafeIsolation()
    spec = BuildExecutionSpec(
        command="true",
        cwd=str(tmp_path.resolve()),
        shell="/bin/sh",
        timeout_seconds=1,
        environment_sha256=environment_sha256({"PATH": "/bin"}),
        input_manifest_sha256=_sha("inputs"),
        isolation_adapter=isolation.adapter,
        isolation_version=isolation.adapter_version,
        isolation_policy_sha256=isolation.policy_sha256,
        adapter=DeadlineBoundSQLiteFencedBuildEffect.adapter,
        adapter_version=DeadlineBoundSQLiteFencedBuildEffect.adapter_version,
    )

    with pytest.raises(ValueError, match="deny provider network"):
        DeadlineBoundSQLiteFencedBuildEffect(
            tmp_path / "target.sqlite3",
            spec=spec,
            environment={"PATH": "/bin"},
            isolation=isolation,
            input_verifier=_StaticInputVerifier(spec.input_manifest_sha256),
            authentication_key=bytes(range(64, 96)),
        )


def test_darwin_sandbox_policy_and_argv_are_exact_cross_platform(tmp_path):
    protected_root = tmp_path / "resource authority"
    profile = darwin_sandbox_profile(protected_root)
    spec = BuildExecutionSpec(
        command="make test",
        cwd=str(tmp_path.resolve()),
        shell="/bin/sh",
        timeout_seconds=3,
        environment_sha256=environment_sha256({"PATH": "/bin"}),
        input_manifest_sha256=_sha("inputs"),
        isolation_adapter="test",
        isolation_version="1",
        isolation_policy_sha256=_sha("policy"),
    )
    root_literal = json.dumps(str(protected_root.resolve()), ensure_ascii=False)

    assert profile == "\n".join((
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        f"(deny file-read* (subpath {root_literal}))",
        f"(deny file-write* (subpath {root_literal}))",
    ))
    assert darwin_sandbox_argv(profile, spec) == (
        "/usr/bin/sandbox-exec",
        "-p",
        profile,
        "/bin/sh",
        "-c",
        "make test",
    )


def test_closed_environment_and_resource_root_policies_are_cross_platform(tmp_path):
    closed = closed_build_environment({
        "PATH": "/bin",
        "GIT_AUTHOR_NAME": "Lakato Builder",
        "OPENAI_API_KEY": "secret",
        "SERVICE_AUTH_TOKEN": "secret",
        "DATABASE_PASSWORD": "secret",
        "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "1000",
    })
    assert closed == {
        "PATH": "/bin",
        "GIT_AUTHOR_NAME": "Lakato Builder",
    }

    cwd = tmp_path / "source" / "tree"
    authority = tmp_path / "source"
    assert resource_root_path_violation(
        prospective=authority,
        cwd=cwd,
        home=tmp_path / "home",
    ) == "resource build directory cannot contain the build working tree"
    assert resource_root_path_violation(
        prospective=tmp_path / "authority",
        cwd=cwd,
        home=tmp_path / "home",
    ) is None

    directory = stat.S_IFDIR | 0o700
    assert resource_root_metadata_violation(
        mode=directory,
        owner_uid=501,
        current_uid=501,
    ) is None
    assert "real directory" in resource_root_metadata_violation(
        mode=stat.S_IFLNK | 0o700,
        owner_uid=501,
        current_uid=501,
    )
    assert "owned by the current user" in resource_root_metadata_violation(
        mode=directory,
        owner_uid=502,
        current_uid=501,
    )
    assert "group/other" in resource_root_metadata_violation(
        mode=stat.S_IFDIR | 0o755,
        owner_uid=501,
        current_uid=501,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="production isolation is macOS-only")
def test_environment_composition_reuses_retained_command_payloads(tmp_path, monkeypatch):
    input_path = tmp_path / "input.txt"
    input_path.write_text("v1")
    manifest = _write_manifest(tmp_path, "input.txt")
    monkeypatch.chdir(tmp_path)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LAKATOTREE_RESOURCE_BUILD_DIR": str(tmp_path / "resource-runtime"),
        "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
        "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
        "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
        "LAKATOTREE_BUILD_INPUT_MANIFEST": str(manifest),
    }
    first = resource_gated_build_runner_from_environment(
        tree="T",
        tag="v1",
        command="true",
        timeout_seconds=1,
        environment=environment,
    )
    assert first is not None
    assert stat.S_IMODE((tmp_path / "resource-runtime").stat().st_mode) == 0o700
    first("true")

    restarted = resource_gated_build_runner_from_environment(
        tree="T",
        tag="v1",
        command="true",
        timeout_seconds=1,
        environment=environment,
    )
    assert restarted is not None
    assert restarted._request == first._request
    assert restarted._start == first._start


@pytest.mark.skipif(sys.platform != "darwin", reason="production isolation is macOS-only")
def test_harness_run_opt_in_composes_gated_build_and_replays_terminal_result(
    tmp_path,
    monkeypatch,
    capsys,
):
    marker = tmp_path / "cli-marker"
    command = _command(marker)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "tree": "CLI-T",
        "tag": "v1",
        "parent": "root",
        "metric": "tests",
        "baseline": 0,
        "build_cmd": command,
        "judge_cmd": "judge",
    }))
    resource_root = tmp_path / "resource-runtime"
    manifest = _write_manifest(tmp_path, "spec.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAKATOTREE_RESOURCE_BUILD_DIR", str(resource_root))
    monkeypatch.setenv("LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX", bytes(range(32)).hex())
    monkeypatch.setenv("LAKATOTREE_RESOURCE_PERMIT_KEY_HEX", bytes(range(32, 64)).hex())
    monkeypatch.setenv("LAKATOTREE_RESOURCE_COMPUTE_CAP_MS", "700000")
    monkeypatch.setenv("LAKATOTREE_BUILD_INPUT_MANIFEST", str(manifest))
    monkeypatch.setattr(harness_run, "_bash", lambda cmd: ("metric=1", 0))
    monkeypatch.setattr(harness_run, "_git_sha", lambda: "abc1234")
    monkeypatch.setattr(harness_run, "_http", lambda method, path, body=None: (
        {"verdict": "progressive"}
        if path.endswith("/test_result")
        else {"stands": True}
        if path.endswith("/standing")
        else {"ok": True}
    ))

    harness_run.main(str(spec_path))
    first = json.loads(capsys.readouterr().out)
    harness_run.main(str(spec_path))
    second = json.loads(capsys.readouterr().out)

    assert marker.read_text() == "1"
    assert first["build"]["resource"] == second["build"]["resource"]
    assert first["build"]["resource"]["effect_id"].startswith("build:")
    assert (resource_root / "resource.sqlite3").is_file()
    assert (
        resource_root
        / DeadlineBoundSQLiteFencedBuildEffect.target_database_filename
    ).is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="production isolation is macOS-only")
def test_live_isolation_strips_provider_secret_and_denies_network_and_target_write(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.txt"
    input_path.write_text("v1")
    manifest = _write_manifest(tmp_path, "input.txt")
    resource_root = tmp_path / "resource-runtime"
    probe = (
        "import errno, os, socket; from pathlib import Path; "
        "print('secret=' + str('OPENAI_API_KEY' in os.environ)); "
        "print('author=' + os.environ.get('GIT_AUTHOR_NAME', 'missing')); "
        "s=socket.socket(); "
        "\ntry: s.connect(('127.0.0.1', 9)); print('network=allowed')"
        "\nexcept OSError as e: print('network_errno=' + str(e.errno)); "
        f"\ntry: Path({str(resource_root / 'forged')!r}).write_text('x'); print('root=allowed')"
        "\nexcept OSError as e: print('root_errno=' + str(e.errno))"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(probe)}"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "OPENAI_API_KEY": "must-not-reach-child",
        "GIT_AUTHOR_NAME": "Lakato Builder",
        "LAKATOTREE_RESOURCE_BUILD_DIR": str(resource_root),
        "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
        "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
        "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
        "LAKATOTREE_BUILD_INPUT_MANIFEST": str(manifest),
    }
    monkeypatch.chdir(tmp_path)
    runner = resource_gated_build_runner_from_environment(
        tree="isolation",
        tag="v1",
        command=command,
        timeout_seconds=2,
        environment=environment,
    )
    assert runner is not None

    result = runner(command)

    assert result.returncode == 0
    assert "secret=False" in result.output
    assert "author=Lakato Builder" in result.output
    assert f"network_errno={getattr(os, 'EPERM', 1)}" in result.output
    assert f"root_errno={getattr(os, 'EPERM', 1)}" in result.output
    assert not (resource_root / "forged").exists()


def test_harness_run_resource_opt_in_is_fail_closed_and_typed(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "tree": "CLI-T",
        "tag": "v1",
        "parent": "root",
        "metric": "tests",
        "baseline": 0,
        "build_cmd": "true",
    }))
    monkeypatch.setenv(
        "LAKATOTREE_RESOURCE_BUILD_DIR",
        str(tmp_path / "incomplete-resource-runtime"),
    )

    assert harness_run.run_typed(str(spec_path)) == 1
    terminal = json.loads(capsys.readouterr().err)
    assert terminal["status"] == "resource_build_config_error"
    assert terminal["class"] == "permanent"


def test_harness_run_maps_foreign_target_failure_to_typed_terminal(
    tmp_path,
    monkeypatch,
    capsys,
):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "tree": "CLI-T",
        "tag": "v1",
        "parent": "root",
        "metric": "tests",
        "baseline": 0,
        "build_cmd": "true",
    }))

    def reject_target(**_kwargs):
        raise BuildTargetError("foreign target metadata")

    monkeypatch.setattr(
        harness_run,
        "resource_gated_build_runner_from_environment",
        reject_target,
    )

    assert harness_run.run_typed(str(spec_path)) == 1
    terminal = json.loads(capsys.readouterr().err)
    assert terminal == {
        "status": "resource_build_target_error",
        "class": "permanent",
        "detail": "foreign target metadata",
    }


def test_target_outcome_unknown_is_a_transient_typed_terminal(monkeypatch, capsys):
    def unknown(_path):
        raise BuildTargetOutcomeUnknown("durable target claim is unresolved")

    monkeypatch.setattr(harness_run, "main", unknown)

    assert harness_run.run_typed("ignored.json") == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "resource_build_target_outcome_unknown",
        "class": "transient",
        "detail": "durable target claim is unresolved",
    }


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    (
        (JournalSchemaMismatch("foreign schema"), ResourceBuildConfigError),
        (TrustedAnchorUnavailable("anchor offline"), ResourceBuildOutcomeUnknown),
    ),
)
def test_runner_translates_journal_failures_at_service_boundary(
    tmp_path,
    monkeypatch,
    failure,
    expected_type,
):
    marker = tmp_path / "marker"
    command = _command(marker)
    runner, journal, _effect = _runtime(tmp_path, command=command)

    def fail_load(_scope):
        raise failure

    monkeypatch.setattr(journal, "load", fail_load)

    with pytest.raises(expected_type, match=str(failure)):
        runner(command)


def test_execution_policy_identity_and_reservation_have_one_source_of_truth(tmp_path):
    base = DEFAULT_BUILD_EXECUTION_POLICY
    changed = BuildExecutionPolicy(
        **{
            **base.to_dict(),
            "process_cleanup_grace_ms": base.process_cleanup_grace_ms + 250,
        }
    )
    isolation = _TestIsolation()

    def spec(policy: BuildExecutionPolicy) -> BuildExecutionSpec:
        return policy.make_spec(
            command="true",
            cwd=str(tmp_path.resolve()),
            timeout_seconds=7,
            environment_sha256=environment_sha256({"PATH": "/bin"}),
            input_manifest_sha256=_sha("inputs"),
            isolation_adapter=isolation.adapter,
            isolation_version=isolation.adapter_version,
            isolation_policy_sha256=isolation.policy_sha256,
        )

    original_spec = spec(base)
    changed_spec = spec(changed)

    assert changed.policy_sha256 != base.policy_sha256
    assert changed_spec.workload_sha256 != original_spec.workload_sha256
    physical_variants = (
        {**base.to_dict(), "shell": "/usr/bin/sh"},
        {**base.to_dict(), "output_tail_bytes": base.output_tail_bytes // 2},
        {**base.to_dict(), "max_output_bytes": base.max_output_bytes + 1},
        {
            **base.to_dict(),
            "process_cleanup_grace_ms": base.process_cleanup_grace_ms + 1,
        },
    )
    assert all(
        BuildExecutionPolicy(**variant).policy_sha256 != base.policy_sha256
        for variant in physical_variants
    )
    assert reserved_compute_wall_ms(changed_spec) == (
        7_000
        + changed.process_cleanup_grace_ms
    )
    admission = DEFAULT_BUILD_ADMISSION_POLICY
    with pytest.raises(ValueError, match="maximum_timeout_seconds"):
        admission.validate_timeout(admission.maximum_timeout_seconds + 1)

    operationally_tuned = BuildAdmissionPolicy(
        **{
            **admission.to_dict(),
            "target_sqlite_timeout_ms": admission.target_sqlite_timeout_ms + 1,
        }
    )
    assert operationally_tuned.policy_sha256 != admission.policy_sha256
    assert set(admission.to_dict()).isdisjoint(base.to_dict())
    assert spec(base).workload_sha256 == original_spec.workload_sha256

    inherited = {"PATH": "/bin", "ORDINARY_BUILD_FLAG": "enabled"}
    selected_default = closed_build_environment(inherited)
    selected_allowlist = closed_build_environment(
        inherited,
        allowed_keys=("PATH",),
    )

    def spec_for_environment(selected_environment):
        return base.make_spec(
            command="true",
            cwd=str(tmp_path.resolve()),
            timeout_seconds=7,
            environment_sha256=environment_sha256(selected_environment),
            input_manifest_sha256=_sha("inputs"),
            isolation_adapter=isolation.adapter,
            isolation_version=isolation.adapter_version,
            isolation_policy_sha256=isolation.policy_sha256,
        )

    default_environment_spec = spec_for_environment(selected_default)
    allowlisted_environment_spec = spec_for_environment(selected_allowlist)
    assert default_environment_spec.workload_sha256 != (
        allowlisted_environment_spec.workload_sha256
    )


def test_legacy_v1_result_rejects_v2_only_input_rejected_status():
    payload = {
        "schema_version": "lakatotree.build-execution/v1",
        "effect_id": "effect:v1",
        "workload_sha256": _sha("workload"),
        "intent_sha256": _sha("intent"),
        "fence_token": 1,
        "status": BuildTerminalStatus.INPUT_REJECTED.value,
        "returncode": 126,
        "started_at": "2026-08-07T12:00:00Z",
        "completed_at": "2026-08-07T12:00:00Z",
        "elapsed_monotonic_ns": 0,
        "compute_wall_ms": 0,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "output_tail": "",
        "measurement_method": "subprocess.monotonic_elapsed.ceil_ms/v1",
    }

    with pytest.raises(ValueError, match="only in the v2 schema"):
        BuildExecutionResult.from_dict(payload)


def test_injected_deployment_policy_drives_composition_without_darwin_hardcoding(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("v1")
    manifest = _write_manifest(source, "input.txt")
    resource_root = tmp_path / "resource"
    policy = BuildExecutionPolicy(
        **{
            **DEFAULT_BUILD_EXECUTION_POLICY.to_dict(),
            "shell": "/bin/sh",
            "output_tail_bytes": 4_096,
            "max_output_bytes": 32_768,
            "process_cleanup_grace_ms": 275,
        }
    )
    selected_admission_policy = BuildAdmissionPolicy(
        **{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "environment_allowlist": ("PATH",),
        }
    )

    class PortableDeploymentPolicy:
        name = "test-portable/v7"
        execution_policy = policy
        admission_policy = selected_admission_policy

        def __init__(self):
            self.calls = 0

        def create_isolation(self, protected_root):
            self.calls += 1
            return _TestIsolation()

    class Resolver:
        def __init__(self, selected):
            self.selected = selected
            self.names = []

        def resolve(self, name):
            self.names.append(name)
            return self.selected

    selected = PortableDeploymentPolicy()
    resolver = Resolver(selected)
    monkeypatch.chdir(source)
    monkeypatch.setattr(
        local_build_execution,
        "DarwinSandboxExecIsolation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("composition bypassed injected isolation policy")
        ),
    )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LAKATOTREE_RESOURCE_BUILD_DIR": str(resource_root),
        "LAKATOTREE_RESOURCE_BUILD_POLICY": selected.name,
        "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
        "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
        "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
        "LAKATOTREE_BUILD_INPUT_MANIFEST": str(manifest),
    }

    runner = resource_gated_build_runner_from_environment(
        tree="T",
        tag="v1",
        command="true",
        timeout_seconds=1,
        environment=environment,
        deployment_policy_resolver=resolver,
    )

    assert isinstance(selected, BuildDeploymentPolicyPort)
    assert runner is not None
    assert isinstance(runner._effect, DeadlineBoundSQLiteFencedBuildEffect)
    assert resolver.names == [selected.name]
    assert selected.calls == 1
    assert runner._effect.spec.execution_policy_sha256 == policy.policy_sha256
    assert runner._effect.spec.shell == policy.shell
    assert runner._effect.spec.output_tail_bytes == policy.output_tail_bytes
    assert runner._effect.spec.max_output_bytes == policy.max_output_bytes
    assert runner._effect.spec.process_cleanup_grace_ms == 275
    assert runner._request.estimate.upper_bound.compute_wall_ms == 1_275

    class InvalidIsolationPolicy(PortableDeploymentPolicy):
        name = "test-invalid-isolation/v1"

        def create_isolation(self, _protected_root):
            return object()

    invalid = InvalidIsolationPolicy()
    invalid_environment = {
        **environment,
        "LAKATOTREE_RESOURCE_BUILD_DIR": str(tmp_path / "invalid-resource"),
        "LAKATOTREE_RESOURCE_BUILD_POLICY": invalid.name,
    }
    with pytest.raises(ResourceBuildConfigError, match="invalid isolation port"):
        resource_gated_build_runner_from_environment(
            tree="T",
            tag="invalid",
            command="true",
            timeout_seconds=1,
            environment=invalid_environment,
            deployment_policy_resolver=Resolver(invalid),
        )


def test_unknown_enabled_policy_fails_before_filesystem_side_effects(tmp_path):
    resource_root = tmp_path / "must-not-exist"
    environment = {
        "LAKATOTREE_RESOURCE_BUILD_DIR": str(resource_root),
        "LAKATOTREE_RESOURCE_BUILD_POLICY": "unknown/v99",
    }

    with pytest.raises(ResourceBuildConfigError, match="unknown resource build policy"):
        resource_gated_build_runner_from_environment(
            tree="T",
            tag="v1",
            command="true",
            timeout_seconds=1,
            environment=environment,
        )

    assert not resource_root.exists()


def test_disabled_resource_mode_does_not_resolve_poisoned_policy():
    class Resolver:
        def resolve(self, name):
            raise AssertionError(f"disabled mode resolved policy {name}")

    assert resource_gated_build_runner_from_environment(
        tree="T",
        tag="v1",
        command="true",
        timeout_seconds=1,
        environment={"LAKATOTREE_RESOURCE_BUILD_POLICY": "poisoned/v1"},
        deployment_policy_resolver=Resolver(),
    ) is None


def test_closed_environment_is_allowlisted_and_policy_controlled():
    source = {
        "PATH": "/bin",
        "LANG": "C.UTF-8",
        "GIT_AUTHOR_NAME": "Lakato Builder",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "DOCKER_HOST": "unix:///tmp/docker.sock",
        "KUBECONFIG": "/tmp/kubeconfig",
        "HOME": "/secret-home",
        "FUTURE_PROVIDER_CREDENTIAL": "secret",
    }

    assert closed_build_environment(source) == {
        "PATH": "/bin",
        "LANG": "C.UTF-8",
        "GIT_AUTHOR_NAME": "Lakato Builder",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "DOCKER_HOST": "unix:///tmp/docker.sock",
        "KUBECONFIG": "/tmp/kubeconfig",
        "HOME": "/secret-home",
    }
    assert closed_build_environment(source, allowed_keys=("PATH", "LANG")) == {
        "PATH": "/bin",
        "LANG": "C.UTF-8",
    }
    with pytest.raises(ValueError, match="invalid key"):
        BuildAdmissionPolicy(environment_allowlist=("PATH", 7))  # type: ignore[arg-type]


def test_manifest_policy_bounds_json_entries_and_declared_bytes(tmp_path):
    (tmp_path / "a.txt").write_text("aaaa")
    (tmp_path / "b.txt").write_text("bbbb")
    manifest = _write_manifest(tmp_path, "a.txt", "b.txt")
    one_entry = BuildAdmissionPolicy(
        **{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_manifest_entries": 1,
        }
    )
    with pytest.raises(BuildInputManifestError, match="entry limit"):
        VerifiedBuildInputManifest.load(manifest, root=tmp_path, policy=one_entry)

    tiny_json = BuildAdmissionPolicy(
        **{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_manifest_json_bytes": 128,
        }
    )
    oversized_manifest = tmp_path / "oversized-manifest.json"
    oversized_manifest.write_bytes(b" " * 129)
    with pytest.raises(BuildInputManifestError, match="JSON byte limit"):
        VerifiedBuildInputManifest.load(
            oversized_manifest,
            root=tmp_path,
            policy=tiny_json,
        )

    three_bytes = BuildAdmissionPolicy(
        **{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_input_file_bytes": 3,
        }
    )
    with pytest.raises(BuildInputManifestError, match="per-file byte limit"):
        VerifiedBuildInputManifest.load(manifest, root=tmp_path, policy=three_bytes)

    six_bytes = BuildAdmissionPolicy(
        **{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_input_bytes": 6,
        }
    )
    with pytest.raises(BuildInputManifestError, match="declared byte limit"):
        VerifiedBuildInputManifest.load(manifest, root=tmp_path, policy=six_bytes)


def test_manifest_descriptor_verification_rejects_growth_and_wraps_io(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.txt"
    input_path.write_bytes(b"abcd")
    verifier = VerifiedBuildInputManifest.load(
        _write_manifest(tmp_path, "input.txt"),
        root=tmp_path,
    )
    real_read = local_build_execution.os.read
    read_sizes = []

    def growing_read(descriptor, size):
        read_sizes.append(size)
        if len(read_sizes) == 2:
            return b"x"
        return real_read(descriptor, size)

    monkeypatch.setattr(local_build_execution.os, "read", growing_read)
    with pytest.raises(BuildInputManifestError, match="grew while reading"):
        verifier.verify()
    assert read_sizes == [4, 1]

    def failed_read(_descriptor, _size):
        raise OSError("injected descriptor failure")

    monkeypatch.setattr(local_build_execution.os, "read", failed_read)
    with pytest.raises(BuildInputManifestError, match="could not be read safely"):
        verifier.verify()


def test_manifest_descriptor_walk_rejects_intermediate_symlink(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    input_path = actual / "input.txt"
    input_path.write_text("v1")
    (tmp_path / "alias").symlink_to(actual, target_is_directory=True)
    manifest = tmp_path / "symlink-manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "lakatotree.build-input-manifest/v1",
        "files": [{
            "path": "alias/input.txt",
            "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        }],
    }))

    with pytest.raises(BuildInputManifestError, match="could not be read safely"):
        VerifiedBuildInputManifest.load(manifest, root=tmp_path)


def test_manifest_final_descriptor_open_is_nonblocking(tmp_path, monkeypatch):
    input_path = tmp_path / "input.txt"
    input_path.write_text("stable")
    verifier = VerifiedBuildInputManifest.load(
        _write_manifest(tmp_path, "input.txt"),
        root=tmp_path,
    )
    real_open = local_build_execution.os.open
    observed_flags = []

    def recording_open(path, flags, *args, **kwargs):
        if path == "input.txt":
            observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(local_build_execution.os, "open", recording_open)
    verifier.verify_until(time.monotonic_ns() + 1_000_000_000)

    assert observed_flags
    assert observed_flags[-1] & os.O_NONBLOCK


def test_deadline_bound_effect_rejects_preflight_only_verifier_before_durable_io(
    tmp_path,
):
    class PreflightOnlyVerifier:
        manifest_sha256 = _sha("preflight-only")

        def verify(self):
            return None

    with pytest.raises(ValueError, match="deadline-aware verify_until"):
        _runtime(
            tmp_path,
            command="true",
            input_verifier=PreflightOnlyVerifier(),
        )

    assert not (tmp_path / "build-target.sqlite3").exists()


def test_legacy_effect_accepts_verify_only_input_verifier(tmp_path):
    class VerifyOnlyInputVerifier:
        manifest_sha256 = _sha("legacy-inputs")

        def __init__(self):
            self.calls = 0

        def verify(self):
            self.calls += 1

    verifier = VerifyOnlyInputVerifier()
    marker = tmp_path / "legacy-marker"
    runner, _journal, effect = _runtime(
        tmp_path,
        command=_command(marker),
        input_verifier=verifier,
        effect_type=SQLiteFencedBuildEffect,
    )

    assert runner(_command(marker)).returncode == 0
    assert marker.read_text() == "1"
    assert verifier.calls == 3  # service preflight plus legacy pre/post-claim checks
    assert effect.adapter_version != DeadlineBoundSQLiteFencedBuildEffect.adapter_version


def test_public_effect_boundary_versions_are_explicit_and_distinct(tmp_path):
    assert BuildInputVerifierPort in DeadlineBoundBuildInputVerifierPort.__mro__
    assert "BuildInputVerifierPort" in local_build_execution.__all__
    assert "DeadlineBoundBuildInputVerifierPort" in local_build_execution.__all__
    assert "SQLiteFencedBuildEffect" in local_build_execution.__all__
    assert "DeadlineBoundSQLiteFencedBuildEffect" in local_build_execution.__all__

    base = dict(
        command="true",
        cwd=str(tmp_path.resolve()),
        shell="/bin/sh",
        timeout_seconds=1,
        environment_sha256=environment_sha256({"PATH": "/bin"}),
        input_manifest_sha256=_sha("inputs"),
        isolation_adapter=_TestIsolation.adapter,
        isolation_version=_TestIsolation.adapter_version,
        isolation_policy_sha256=_TestIsolation.policy_sha256,
    )
    legacy = BuildExecutionSpec(
        **base,
        adapter=SQLiteFencedBuildEffect.adapter,
        adapter_version=SQLiteFencedBuildEffect.adapter_version,
    )
    deadline_bound = BuildExecutionSpec(
        **base,
        adapter=DeadlineBoundSQLiteFencedBuildEffect.adapter,
        adapter_version=DeadlineBoundSQLiteFencedBuildEffect.adapter_version,
    )

    assert legacy.workload_sha256 != deadline_bound.workload_sha256


def test_factory_upgrade_preserves_v1_target_and_uses_distinct_v2_store(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("v1")
    manifest = _write_manifest(source, "input.txt")
    resource_root = tmp_path / "resource"
    resource_root.mkdir(mode=0o700)
    resource_root.chmod(0o700)
    child_environment = {"PATH": os.environ.get("PATH", "")}
    isolation = _TestIsolation()
    legacy_spec = BuildExecutionSpec(
        command="true",
        cwd=str(source.resolve()),
        shell="/bin/sh",
        timeout_seconds=1,
        environment_sha256=environment_sha256(child_environment),
        input_manifest_sha256=_sha("legacy-inputs"),
        isolation_adapter=isolation.adapter,
        isolation_version=isolation.adapter_version,
        isolation_policy_sha256=isolation.policy_sha256,
        adapter=SQLiteFencedBuildEffect.adapter,
        adapter_version=SQLiteFencedBuildEffect.adapter_version,
    )
    legacy_path = resource_root / SQLiteFencedBuildEffect.target_database_filename
    legacy_effect = SQLiteFencedBuildEffect(
        legacy_path,
        spec=legacy_spec,
        environment=child_environment,
        isolation=isolation,
        input_verifier=_StaticInputVerifier(legacy_spec.input_manifest_sha256),
        authentication_key=bytes(range(64, 96)),
    )
    legacy_bytes = legacy_path.read_bytes()

    class PortableDeploymentPolicy:
        name = "test-upgrade/v1"
        execution_policy = DEFAULT_BUILD_EXECUTION_POLICY
        admission_policy = BuildAdmissionPolicy(environment_allowlist=("PATH",))

        @staticmethod
        def create_isolation(_protected_root):
            return _TestIsolation()

    class Resolver:
        @staticmethod
        def resolve(name):
            assert name == PortableDeploymentPolicy.name
            return PortableDeploymentPolicy()

    monkeypatch.chdir(source)
    runner = resource_gated_build_runner_from_environment(
        tree="upgrade",
        tag="v2",
        command="true",
        timeout_seconds=1,
        environment={
            **child_environment,
            "LAKATOTREE_RESOURCE_BUILD_DIR": str(resource_root),
            "LAKATOTREE_RESOURCE_BUILD_POLICY": PortableDeploymentPolicy.name,
            "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
            "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
            "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
            "LAKATOTREE_BUILD_INPUT_MANIFEST": str(manifest),
        },
        deployment_policy_resolver=Resolver(),
    )

    assert runner is not None
    assert isinstance(runner._effect, DeadlineBoundSQLiteFencedBuildEffect)
    deadline_path = (
        resource_root
        / DeadlineBoundSQLiteFencedBuildEffect.target_database_filename
    )
    assert deadline_path.exists()
    assert deadline_path != legacy_path
    assert legacy_path.read_bytes() == legacy_bytes

    with legacy_effect._scope_lock("upgrade-lock"):
        pass
    with runner._effect._scope_lock("upgrade-lock"):
        pass
    lock_names = {path.name for path in resource_root.glob(".*.lock")}
    assert any(legacy_path.name in name for name in lock_names)
    assert any(deadline_path.name in name for name in lock_names)


def test_post_claim_input_refusal_is_terminal_and_settled(tmp_path):
    class ChangesAfterClaim(_StaticInputVerifier):
        def __init__(self):
            super().__init__(_sha("inputs"))
            self.calls = 0

        def verify(self):
            self.calls += 1
            if self.calls == 2:
                raise BuildInputManifestError("declared build input changed: input.txt")

    marker = tmp_path / "must-not-run"
    command = _command(marker)
    verifier = ChangesAfterClaim()
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        input_verifier=verifier,
    )

    run = runner(command)
    result, _receipt = effect.load_terminal_result(
        effect_id=runner._start.command_id,
        workload_sha256=runner._start.workload_sha256,
    )
    grant = journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    )

    assert not marker.exists()
    assert run.returncode == 126
    assert result.status is BuildTerminalStatus.INPUT_REJECTED
    assert grant.status is GrantStatus.SETTLED
    assert verifier.calls == 2


def test_synthetic_terminal_stderr_obeys_split_stream_quota(tmp_path, monkeypatch):
    class RejectsAfterPreflight(_StaticInputVerifier):
        def __init__(self):
            super().__init__(_sha("synthetic-input-refusal"))
            self.calls = 0

        def verify(self):
            self.calls += 1
            if self.calls == 2:
                raise BuildInputManifestError("changed")

    refusal_root = tmp_path / "input-refusal"
    refusal_root.mkdir()
    refusal_runner, _journal, refusal_effect = _runtime(
        refusal_root,
        command="true",
        input_verifier=RejectsAfterPreflight(),
        output_tail_bytes=1,
        max_output_bytes=1,
    )
    refusal_runner("true")
    refusal, _ = refusal_effect.load_terminal_result(
        effect_id=refusal_runner._start.command_id,
        workload_sha256=refusal_runner._start.workload_sha256,
    )

    spawn_root = tmp_path / "spawn-failure"
    spawn_root.mkdir()
    spawn_runner, _journal, spawn_effect = _runtime(
        spawn_root,
        command="true",
        output_tail_bytes=1,
        max_output_bytes=1,
    )

    def fail_spawn(*_args, **_kwargs):
        raise OSError("injected spawn failure")

    monkeypatch.setattr(local_build_execution.subprocess, "Popen", fail_spawn)
    spawn_runner("true")
    spawn, _ = spawn_effect.load_terminal_result(
        effect_id=spawn_runner._start.command_id,
        workload_sha256=spawn_runner._start.workload_sha256,
    )

    assert refusal.status is BuildTerminalStatus.INPUT_REJECTED
    assert spawn.status is BuildTerminalStatus.SPAWN_FAILED
    assert refusal.stderr_bytes == spawn.stderr_bytes == 0
    assert refusal.output_tail == spawn.output_tail == ""


def test_post_claim_verification_time_is_metered_before_input_rejection(tmp_path):
    class MutableMonotonicClock:
        now = 1_000_000_000

        def __call__(self):
            return self.now

    class SlowChangedInput(_StaticInputVerifier):
        def __init__(self, clock):
            super().__init__(_sha("inputs"))
            self.clock = clock
            self.calls = 0

        def verify(self):
            self.calls += 1
            if self.calls == 2:
                self.clock.now += 250_000_000
                raise BuildInputManifestError("declared build input changed: input.txt")

    clock = MutableMonotonicClock()
    verifier = SlowChangedInput(clock)
    marker = tmp_path / "must-not-run"
    command = _command(marker)
    runner, journal, effect = _runtime(
        tmp_path,
        command=command,
        input_verifier=verifier,
        monotonic_ns=clock,
    )

    run = runner(command)
    result, _receipt = effect.load_terminal_result(
        effect_id=runner._start.command_id,
        workload_sha256=runner._start.workload_sha256,
    )

    assert not marker.exists()
    assert run.returncode == 126
    assert result.status is BuildTerminalStatus.INPUT_REJECTED
    assert result.elapsed_monotonic_ns == 250_000_000
    assert result.compute_wall_ms == 250
    assert journal.load("harness-build:test-tree").state.grant(
        "grant:effect:build:1"
    ).status is GrantStatus.SETTLED
