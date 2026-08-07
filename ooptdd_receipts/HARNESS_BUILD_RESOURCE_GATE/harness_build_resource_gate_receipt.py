"""Hermetic OOPTDD receipt for the resource-gated harness build slice."""

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
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.build_execution import (  # noqa: E402
    BuildExecutionSpec,
    BuildTerminalStatus,
    ResourceBuildConfigError,
    ResourceBuildOutcomeUnknown,
    environment_sha256,
)
from lakatos.harness import BuildFailed, CycleSpec, LakatoHarness  # noqa: E402
from lakatos.io import local_build_execution as local_build_execution_module  # noqa: E402
from lakatos.io.local_build_execution import (  # noqa: E402
    BuildInputManifestError,
    BuildTargetError,
    BuildTargetOutcomeUnknown,
    ResourceGatedBuildRunner,
    SQLiteFencedBuildEffect,
    VerifiedBuildInputManifest,
    closed_build_environment,
    darwin_sandbox_argv,
    darwin_sandbox_profile,
    resource_root_metadata_violation,
    resource_root_path_violation,
)
from lakatos.io.resource_execution import (  # noqa: E402
    HMACPermitAuthenticator,
    ResourceExecutionGate,
)
from lakatos.io.resource_journal import (  # noqa: E402
    JournalNotInitialized,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (  # noqa: E402
    GrantStatus,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    StartGrant,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"harness build resource gate receipt red: {message}")


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


class _RollbackAfterDispatchClock:
    def __init__(self) -> None:
        self._calls = 0

    def now_utc(self) -> str:
        self._calls += 1
        if self._calls <= 2:
            return "2026-08-07T12:00:02Z"
        return "2026-08-07T11:59:59Z"


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.harness_build_resource_gate",
        "event": name,
    }


class _Clock:
    def now_utc(self) -> str:
        return "2026-08-07T12:00:04Z"


def _command(marker: Path, exit_code: int = 0) -> str:
    source = (
        "from pathlib import Path; "
        f"p=Path({str(marker)!r}); "
        "n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); print('ooptdd-build'); "
        f"raise SystemExit({exit_code})"
    )
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def _write_manifest(root: Path, *relative_paths: str) -> Path:
    path = root / "build-input-manifest.json"
    path.write_text(json.dumps({
        "schema_version": "lakatotree.build-input-manifest/v1",
        "files": [
            {
                "path": relative,
                "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            }
            for relative in sorted(relative_paths)
        ],
    }), encoding="utf-8")
    return path


def _runtime(
    root: Path,
    *,
    command: str,
    scope: str,
    effect_id: str,
    after_claim=None,
    after_terminal=None,
    input_verifier=None,
    utc_now=None,
    monotonic_ns=None,
    gate_clock=None,
    timeout_seconds: int = 10,
    target_timeout_seconds: float = 10.0,
    output_tail_bytes: int = 65_536,
    max_output_bytes: int = 16_777_216,
):
    child_environment = {"PATH": os.environ.get("PATH", "")}
    isolation = _TestIsolation()
    selected_input_verifier = input_verifier or _StaticInputVerifier(
        _sha(f"inputs:{scope}")
    )
    input_manifest_sha256 = selected_input_verifier.manifest_sha256
    spec = BuildExecutionSpec(
        command=command,
        cwd=str(root.resolve()),
        shell="/bin/sh",
        timeout_seconds=timeout_seconds,
        environment_sha256=environment_sha256(child_environment),
        input_manifest_sha256=input_manifest_sha256,
        isolation_adapter=isolation.adapter,
        isolation_version=isolation.adapter_version,
        isolation_policy_sha256=isolation.policy_sha256,
        output_tail_bytes=output_tail_bytes,
        max_output_bytes=max_output_bytes,
    )
    effect_options = {
        "utc_now": (
            utc_now if utc_now is not None else lambda: "2026-08-07T12:00:03Z"
        ),
    }
    if monotonic_ns is not None:
        effect_options["monotonic_ns"] = monotonic_ns
    effect = SQLiteFencedBuildEffect(
        root / "target.sqlite3",
        spec=spec,
        environment=child_environment,
        isolation=isolation,
        input_verifier=selected_input_verifier,
        authentication_key=bytes(range(64, 96)),
        failure_inject_after_claim=after_claim,
        failure_inject_after_terminal_commit=after_terminal,
        timeout_seconds=target_timeout_seconds,
        **effect_options,
    )
    fence = effect.allocate_fence(scope=scope, effect_id=effect_id)
    journal = SQLiteResourceJournal(
        root / "resource.sqlite3",
        trusted_anchor=SignedAppendOnlyFileAnchor(
            root / "anchor",
            signing_key=bytes(range(32)),
        ),
    )
    genesis = ResourceState.create(
        budget_id=f"budget:{_sha(scope)}",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(compute_wall_ms=60_000),
    )
    try:
        journal.load(scope)
    except JournalNotInitialized:
        journal.initialize(genesis)
    identity = _sha(effect_id)
    request = RequestGrant(
        command_id=f"request:{identity}",
        grant_id=f"grant:{identity}",
        fence_token=fence,
        observed_at="2026-08-07T12:00:00Z",
        expires_at="2026-08-07T12:10:00Z",
        estimate=ResourceEstimate(
            work_id=f"work:{identity}",
            attempt_id=f"attempt:{identity}",
            workload_sha256=spec.workload_sha256,
            adapter=effect.adapter,
            adapter_version=effect.adapter_version,
            upper_bound=ResourceVector(
                compute_wall_ms=timeout_seconds * 1000 + 1000
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
            issuer="ooptdd:harness-build",
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
    )


_BUILD_PORT_MARKER = "        raw = self._build(s.build_cmd)\n"
_ENVIRONMENT_HASH_MARKER = (
    '            "environment_sha256": self.environment_sha256,\n'
)
_ISOLATION_POLICY_MARKER = (
    '            "isolation_policy_sha256": self.isolation_policy_sha256,\n'
)
_AUTHENTICATE_BEFORE_DECODE_MARKER = '        target_mac = row["target_mac_sha256"]\n'
_OUTPUT_CAP_MARKER = "        admitted = chunk[:remaining_bytes]\n"
_SECRET_FILTER_MARKER = "        and not _is_sensitive_child_environment_key(key)\n"
_ROOT_CONTAINS_CWD_MARKER = (
    "    if cwd == prospective or cwd.is_relative_to(prospective):\n"
)
_ROOT_SYMLINK_MARKER = (
    "    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):\n"
)
_ROOT_OWNER_MARKER = "    if owner_uid != current_uid:\n"
_ROOT_MODE_MARKER = "    if stat.S_IMODE(mode) & 0o077:\n"
_LOCAL_BUILD_FILES = (
    "write_cert.py",
    "resource_coordination.py",
    "resource_kernel.py",
    "resource_execution.py",
    "build_execution.py",
    "io/__init__.py",
    "io/_resource_journal_contracts.py",
    "io/_resource_journal_codec.py",
    "io/_resource_anchor.py",
    "io/resource_execution.py",
    "io/resource_journal.py",
    "io/local_build_execution.py",
)


def _run_isolated(
    *,
    files: tuple[str, ...],
    replacements: dict[str, tuple[str, str]],
    probe: str,
    prefix: str,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=prefix) as raw:
        temp_root = Path(raw)
        package = temp_root / "lakatos"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        for name in files:
            source = (ROOT / "lakatos" / name).read_text(encoding="utf-8")
            if name in replacements:
                before, after = replacements[name]
                _require(source.count(before) == 1, f"mutation marker not unique: {name}")
                source = source.replace(before, after, 1)
            destination = package / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = raw
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-c", probe],
            cwd=raw,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )


def _build_port_mutant_must_expose_forbidden_effect() -> None:
    probe = r'''
from pathlib import Path
from lakatos.build_execution import ResourceBuildOutcomeUnknown
from lakatos.harness import CycleSpec, LakatoHarness

marker = Path("forbidden-marker")
def raw_bash(command):
    marker.write_text(command, encoding="utf-8")
    return "legacy bypass", 0
def denied_build(command):
    raise ResourceBuildOutcomeUnknown("resource authority refused")
harness = LakatoHarness(http=lambda *a, **k: {}, run_bash=raw_bash, run_build=denied_build)
try:
    harness._build_gate(CycleSpec(
        tree="T", tag="v1", parent="root", metric="m", baseline=0,
        build_cmd="forbidden-build",
    ))
except ResourceBuildOutcomeUnknown:
    pass
raise SystemExit(0 if marker.exists() else 9)
'''
    result = _run_isolated(
        files=("resource_coordination.py", "build_execution.py", "harness.py"),
        replacements={"harness.py": (_BUILD_PORT_MARKER, "        raw = self._bash(s.build_cmd)\n")},
        probe=probe,
        prefix="lakatotree-harness-build-port-mutant-",
    )
    _require(
        result.returncode == 0,
        "legacy-bash wiring mutant did not expose the forbidden effect: "
        + result.stderr[-500:],
    )


def _environment_binding_mutant_must_collide() -> None:
    probe = r'''
import hashlib
from lakatos.build_execution import BuildExecutionSpec, environment_sha256
sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
base = dict(
    command="make", cwd="/tmp", shell="/bin/sh", timeout_seconds=10,
    input_manifest_sha256=sha("inputs"),
    isolation_adapter="test.isolation", isolation_version="1",
    isolation_policy_sha256=sha("isolation-policy"),
)
one = BuildExecutionSpec(**base, environment_sha256=environment_sha256({"PATH": "/bin"}))
two = BuildExecutionSpec(**base, environment_sha256=environment_sha256({"PATH": "/usr/bin"}))
raise SystemExit(0 if one.workload_sha256 == two.workload_sha256 else 7)
'''
    result = _run_isolated(
        files=("resource_coordination.py", "build_execution.py"),
        replacements={
            "build_execution.py": (
                _ENVIRONMENT_HASH_MARKER,
                '            "environment_sha256": "0" * 64,\n',
            )
        },
        probe=probe,
        prefix="lakatotree-build-environment-mutant-",
    )
    _require(
        result.returncode == 0,
        "environment-binding mutant did not collide: " + result.stderr[-500:],
    )


def _isolation_policy_binding_mutant_must_collide() -> None:
    probe = r'''
import hashlib
from lakatos.build_execution import BuildExecutionSpec, environment_sha256
sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
base = dict(
    command="make", cwd="/tmp", shell="/bin/sh", timeout_seconds=10,
    environment_sha256=environment_sha256({"PATH": "/bin"}),
    input_manifest_sha256=sha("inputs"),
    isolation_adapter="test.isolation", isolation_version="1",
)
one = BuildExecutionSpec(**base, isolation_policy_sha256=sha("policy-one"))
two = BuildExecutionSpec(**base, isolation_policy_sha256=sha("policy-two"))
raise SystemExit(0 if one.workload_sha256 == two.workload_sha256 else 7)
'''
    result = _run_isolated(
        files=("resource_coordination.py", "build_execution.py"),
        replacements={
            "build_execution.py": (
                _ISOLATION_POLICY_MARKER,
                '            "isolation_policy_sha256": "0" * 64,\n',
            )
        },
        probe=probe,
        prefix="lakatotree-build-isolation-policy-mutant-",
    )
    _require(
        result.returncode == 0,
        "isolation-policy mutant did not collide: " + result.stderr[-500:],
    )


def _decode_before_authentication_mutant_must_turn_red() -> None:
    probe = r'''
import hashlib
from pathlib import Path
import sqlite3
from lakatos.build_execution import BuildExecutionSpec, environment_sha256
from lakatos.io.local_build_execution import BuildTargetError, SQLiteFencedBuildEffect

sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
class Isolation:
    adapter = "test.isolation"
    adapter_version = "1"
    policy_sha256 = sha("policy")
    denies_provider_network = True
    protects_resource_root = True
    @staticmethod
    def argv(spec): return (spec.shell, "-c", spec.command)
class Inputs:
    manifest_sha256 = sha("inputs")
    def verify(self): return None

root = Path("target-auth")
root.mkdir()
spec = BuildExecutionSpec(
    command="true", cwd=str(root.resolve()), shell="/bin/sh", timeout_seconds=1,
    environment_sha256=environment_sha256({"PATH": "/bin"}),
    input_manifest_sha256=Inputs.manifest_sha256,
    isolation_adapter=Isolation.adapter, isolation_version=Isolation.adapter_version,
    isolation_policy_sha256=Isolation.policy_sha256,
)
effect = SQLiteFencedBuildEffect(
    root / "target.sqlite3", spec=spec, environment={"PATH": "/bin"},
    isolation=Isolation(), input_verifier=Inputs(), authentication_key=bytes(range(32)),
)
fence = effect.allocate_fence(scope="scope", effect_id="effect")
with sqlite3.connect(root / "target.sqlite3") as connection:
    connection.execute(
        "INSERT INTO build_effects "
        "(effect_id, scope, workload_sha256, intent_sha256, fence_token, status, "
        "result_blob, result_sha256, receipt_blob, receipt_sha256, target_mac_sha256) "
        "VALUES (?, ?, ?, ?, ?, 'TERMINAL', ?, ?, ?, ?, ?)",
        ("effect", "scope", spec.workload_sha256, sha("intent"), fence,
         sqlite3.Binary(b"{}"), "0" * 64, sqlite3.Binary(b"{}"), "0" * 64, "0" * 64),
    )
try:
    effect.load_terminal_result(effect_id="effect", workload_sha256=spec.workload_sha256)
except BuildTargetError as exc:
    raise SystemExit(0 if "authentication failed" not in str(exc) else 8)
raise SystemExit(9)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _AUTHENTICATE_BEFORE_DECODE_MARKER,
                "        self._decode_result(row, result_blob)\n"
                + _AUTHENTICATE_BEFORE_DECODE_MARKER,
            )
        },
        probe=probe,
        prefix="lakatotree-build-auth-order-mutant-",
    )
    _require(
        result.returncode == 0,
        "decode-before-authentication mutant was not exposed: " + result.stderr[-500:],
    )


def _output_cap_mutant_must_turn_red() -> None:
    probe = r'''
from lakatos.io.local_build_execution import _BoundedStreamEvidence
evidence = _BoundedStreamEvidence(tail_bytes=8)
evidence.append(b"abcdefgh", remaining_bytes=4)
raise SystemExit(0 if evidence.byte_count > 4 else 7)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _OUTPUT_CAP_MARKER,
                "        admitted = chunk\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-output-cap-mutant-",
    )
    _require(
        result.returncode == 0,
        "output-cap removal mutant stayed green: " + result.stderr[-500:],
    )


def _closed_environment_mutant_must_turn_red() -> None:
    probe = r'''
from lakatos.io.local_build_execution import closed_build_environment
closed = closed_build_environment({"PATH": "/bin", "OPENAI_API_KEY": "secret"})
raise SystemExit(0 if "OPENAI_API_KEY" in closed else 7)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _SECRET_FILTER_MARKER,
                "        and True\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-environment-secret-mutant-",
    )
    _require(
        result.returncode == 0,
        "credential-filter removal mutant stayed green: " + result.stderr[-500:],
    )


def _resource_root_mutants_must_turn_red() -> None:
    cases = (
        (
            _ROOT_CONTAINS_CWD_MARKER,
            "    if False:\n",
            r'''
from pathlib import Path
from lakatos.io.local_build_execution import resource_root_path_violation
violation = resource_root_path_violation(
    prospective=Path("/work"), cwd=Path("/work/source"), home=Path("/home/user"),
)
raise SystemExit(0 if violation is None else 7)
''',
            "contains-cwd",
        ),
        (
            _ROOT_SYMLINK_MARKER,
            "    if False:\n",
            r'''
import stat
from lakatos.io.local_build_execution import resource_root_metadata_violation
violation = resource_root_metadata_violation(
    mode=stat.S_IFLNK | 0o700, owner_uid=501, current_uid=501,
)
raise SystemExit(0 if violation is None else 7)
''',
            "symlink",
        ),
        (
            _ROOT_OWNER_MARKER,
            "    if False:\n",
            r'''
import stat
from lakatos.io.local_build_execution import resource_root_metadata_violation
violation = resource_root_metadata_violation(
    mode=stat.S_IFDIR | 0o700, owner_uid=502, current_uid=501,
)
raise SystemExit(0 if violation is None else 7)
''',
            "owner",
        ),
        (
            _ROOT_MODE_MARKER,
            "    if False:\n",
            r'''
import stat
from lakatos.io.local_build_execution import resource_root_metadata_violation
violation = resource_root_metadata_violation(
    mode=stat.S_IFDIR | 0o755, owner_uid=501, current_uid=501,
)
raise SystemExit(0 if violation is None else 7)
''',
            "mode",
        ),
    )
    for marker, replacement, probe, label in cases:
        result = _run_isolated(
            files=_LOCAL_BUILD_FILES,
            replacements={
                "io/local_build_execution.py": (marker, replacement),
            },
            probe=probe,
            prefix=f"lakatotree-build-root-{label}-mutant-",
        )
        _require(
            result.returncode == 0,
            f"resource-root {label} mutant stayed green: " + result.stderr[-500:],
        )


def verify(backend, cid):
    with tempfile.TemporaryDirectory(prefix="lakatotree-harness-build-ooptdd-") as raw:
        root = Path(raw)

        success_root = root / "success"
        success_root.mkdir()
        success_marker = success_root / "marker"
        success_command = _command(success_marker)
        runner, journal = _runtime(
            success_root,
            command=success_command,
            scope="harness-build:ooptdd-success",
            effect_id="effect:ooptdd-success",
        )
        run = runner(success_command)
        restarted, restarted_journal = _runtime(
            success_root,
            command=success_command,
            scope="harness-build:ooptdd-success",
            effect_id="effect:ooptdd-success",
        )
        replay = restarted(success_command)
        _require(run == replay, "terminal build replay changed evidence")
        _require(success_marker.read_text() == "1", "terminal replay relaunched build")
        grant = journal.load("harness-build:ooptdd-success").state.grant(
            f"grant:{_sha('effect:ooptdd-success')}"
        )
        _require(grant.status is GrantStatus.SETTLED, "build did not settle")
        _require(
            restarted_journal.load("harness-build:ooptdd-success").state.revision == 3,
            "terminal replay advanced resource journal",
        )
        backend.ship([_event(cid, "gated_build_runs_once_and_settles")])

        response_root = root / "response-loss"
        response_root.mkdir()
        response_marker = response_root / "marker"
        losses = {"count": 0}

        def lose_once(_result):
            losses["count"] += 1
            if losses["count"] == 1:
                raise ConnectionError("lost after terminal commit")

        response_command = _command(response_marker)
        response_runner, response_journal = _runtime(
            response_root,
            command=response_command,
            scope="harness-build:ooptdd-response-loss",
            effect_id="effect:ooptdd-response-loss",
            after_terminal=lose_once,
        )
        response_run = response_runner(response_command)
        _require(response_run.returncode == 0, "response-loss recovery lost result")
        _require(response_marker.read_text() == "1", "response loss repeated subprocess")
        _require(
            response_journal.load("harness-build:ooptdd-response-loss")
            .state.grant(f"grant:{_sha('effect:ooptdd-response-loss')}")
            .status is GrantStatus.SETTLED,
            "response-loss recovery did not settle",
        )
        backend.ship([_event(cid, "terminal_response_loss_recovers_without_redispatch")])

        claim_root = root / "claim-crash"
        claim_root.mkdir()
        claim_marker = claim_root / "marker"

        def crash_after_claim(_effect_id):
            raise RuntimeError("crash after claim")

        claim_command = _command(claim_marker)
        claim_runner, claim_journal = _runtime(
            claim_root,
            command=claim_command,
            scope="harness-build:ooptdd-claim-crash",
            effect_id="effect:ooptdd-claim-crash",
            after_claim=crash_after_claim,
        )
        try:
            claim_runner(claim_command)
        except ResourceBuildOutcomeUnknown:
            pass
        else:
            raise RuntimeError("post-claim crash did not stay unknown")
        restarted_claim, _ = _runtime(
            claim_root,
            command=claim_command,
            scope="harness-build:ooptdd-claim-crash",
            effect_id="effect:ooptdd-claim-crash",
        )
        try:
            restarted_claim(claim_command)
        except ResourceBuildOutcomeUnknown:
            pass
        else:
            raise RuntimeError("restart relaunched a nonterminal claim")
        _require(not claim_marker.exists(), "ambiguous claim launched subprocess")
        _require(
            claim_journal.load("harness-build:ooptdd-claim-crash")
            .state.grant(f"grant:{_sha('effect:ooptdd-claim-crash')}")
            .status is GrantStatus.RECONCILIATION_REQUIRED,
            "ambiguous claim did not hold reservation",
        )
        backend.ship([_event(cid, "nonterminal_claim_stays_unknown_without_redispatch")])

        failure_root = root / "nonzero"
        failure_root.mkdir()
        failure_marker = failure_root / "marker"
        failure_command = _command(failure_marker, 7)
        failure_runner, failure_journal = _runtime(
            failure_root,
            command=failure_command,
            scope="harness-build:ooptdd-nonzero",
            effect_id="effect:ooptdd-nonzero",
        )
        raw_bash_calls: list[str] = []
        harness = LakatoHarness(
            http=lambda method, path, body=None: (
                {"verdict": "progressive"}
                if path.endswith("/test_result")
                else {"stands": True}
                if path.endswith("/standing")
                else {"ok": True}
            ),
            run_bash=lambda command: (raw_bash_calls.append(command) or ("metric=1", 0)),
            run_build=failure_runner,
        )
        try:
            harness.run_cycle(CycleSpec(
                tree="T",
                tag="v1",
                parent="root",
                metric="tests",
                baseline=0,
                build_cmd=failure_command,
                judge_cmd="judge",
            ))
        except BuildFailed:
            pass
        else:
            raise RuntimeError("nonzero resource build did not reach BuildFailed")
        _require(raw_bash_calls == [], "judge ran after nonzero build")
        _require(
            failure_journal.load("harness-build:ooptdd-nonzero")
            .state.grant(f"grant:{_sha('effect:ooptdd-nonzero')}")
            .status is GrantStatus.SETTLED,
            "nonzero build was not settled before BuildFailed",
        )
        backend.ship([_event(cid, "nonzero_build_settles_then_fails_scientifically")])

        base = dict(
            command="make",
            cwd=str(root.resolve()),
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
            {**base, "cwd": str(success_root.resolve())},
            {**base, "environment_sha256": environment_sha256({"PATH": "/usr/bin"})},
            {**base, "timeout_seconds": 11},
            {**base, "input_manifest_sha256": _sha("inputs-v2")},
            {**base, "shell": "/usr/bin/sh"},
            {**base, "isolation_adapter": "test.other-isolation"},
            {**base, "isolation_version": "2"},
            {**base, "isolation_policy_sha256": _sha("other-policy")},
            {**base, "output_tail_bytes": 32_768},
            {**base, "max_output_bytes": 32_000_000},
        )
        _require(
            all(
                BuildExecutionSpec(**variant).workload_sha256
                != original.workload_sha256
                for variant in variants
            ),
            "declared execution input failed to change workload identity",
        )
        backend.ship([_event(cid, "workload_identity_binds_execution_inputs")])

        manifest_root = root / "verified-input"
        manifest_root.mkdir()
        input_path = manifest_root / "input.txt"
        input_path.write_text("v1", encoding="utf-8")
        verifier = VerifiedBuildInputManifest.load(
            _write_manifest(manifest_root, "input.txt"),
            root=manifest_root,
        )
        manifest_marker = manifest_root / "marker"
        manifest_command = _command(manifest_marker)
        manifest_runner, _ = _runtime(
            manifest_root,
            command=manifest_command,
            scope="harness-build:ooptdd-verified-input",
            effect_id="effect:ooptdd-verified-input",
            input_verifier=verifier,
        )
        manifest_runner(manifest_command)
        input_path.write_text("v2", encoding="utf-8")
        try:
            manifest_runner(manifest_command)
        except ResourceBuildConfigError:
            pass
        else:
            raise RuntimeError("changed declared input replayed stale terminal evidence")
        _require(manifest_marker.read_text() == "1", "input change relaunched build")
        alias_manifest = manifest_root / "alias-manifest.json"
        alias_manifest.write_text(json.dumps({
            "schema_version": "lakatotree.build-input-manifest/v1",
            "files": [{
                "path": "a//b",
                "sha256": _sha("irrelevant-before-file-read"),
            }],
        }), encoding="utf-8")
        try:
            VerifiedBuildInputManifest.load(alias_manifest, root=manifest_root)
        except BuildInputManifestError:
            pass
        else:
            raise RuntimeError("noncanonical manifest alias was accepted")
        backend.ship([_event(cid, "verified_input_change_blocks_stale_replay")])

        auth_root = root / "target-auth"
        auth_root.mkdir()
        auth_marker = auth_root / "marker"
        auth_command = _command(auth_marker)
        auth_runner, _ = _runtime(
            auth_root,
            command=auth_command,
            scope="harness-build:ooptdd-target-auth",
            effect_id="effect:ooptdd-target-auth",
        )
        auth_runner(auth_command)
        with sqlite3.connect(auth_root / "target.sqlite3") as connection:
            connection.execute(
                "UPDATE build_effects SET result_blob = ? WHERE effect_id = ?",
                (sqlite3.Binary(b"{}"), "effect:ooptdd-target-auth"),
            )
        restarted_auth, _ = _runtime(
            auth_root,
            command=auth_command,
            scope="harness-build:ooptdd-target-auth",
            effect_id="effect:ooptdd-target-auth",
        )
        try:
            restarted_auth(auth_command)
        except BuildTargetError as exc:
            _require(
                "authentication failed" in str(exc),
                "forged raw bytes crossed the decode boundary before authentication",
            )
        else:
            raise RuntimeError("target authentication accepted forged terminal evidence")
        _require(auth_marker.read_text() == "1", "target forgery relaunched build")
        oversized = 8 * 1024 * 1024 + 1
        with sqlite3.connect(auth_root / "target.sqlite3") as connection:
            connection.execute(
                "UPDATE build_effects SET result_blob = zeroblob(?) WHERE effect_id = ?",
                (oversized, "effect:ooptdd-target-auth"),
            )
        bounded_row = restarted_auth._effect._load_row("effect:ooptdd-target-auth")
        _require(
            bounded_row["result_blob_length"] == oversized
            and bounded_row["result_blob"] is None,
            "oversized target blob crossed the bounded SQLite readback query",
        )
        try:
            restarted_auth(auth_command)
        except BuildTargetError as exc:
            _require(
                "exceeds the readback limit" in str(exc),
                "oversized target blob did not fail at the length boundary",
            )
        else:
            raise RuntimeError("oversized target blob was accepted")
        _decode_before_authentication_mutant_must_turn_red()
        backend.ship([_event(cid, "target_authentication_rejects_forged_terminal")])

        corrupt_root = root / "target-corrupt"
        corrupt_root.mkdir()
        (corrupt_root / "target.sqlite3").write_bytes(b"not a SQLite database")
        try:
            _runtime(
                corrupt_root,
                command="true",
                scope="harness-build:ooptdd-target-corrupt",
                effect_id="effect:ooptdd-target-corrupt",
            )
        except BuildTargetError as exc:
            _require(
                not isinstance(exc, BuildTargetOutcomeUnknown),
                "corrupt target was misclassified as transient",
            )
        else:
            raise RuntimeError("corrupt target escaped the typed permanent boundary")

        locked_root = root / "target-locked"
        locked_root.mkdir()
        locked_runner, _ = _runtime(
            locked_root,
            command="true",
            scope="harness-build:ooptdd-target-locked",
            effect_id="effect:ooptdd-target-locked",
            target_timeout_seconds=0.01,
        )
        blocker = sqlite3.connect(
            locked_root / "target.sqlite3",
            isolation_level=None,
        )
        blocker.execute("BEGIN EXCLUSIVE")
        try:
            try:
                locked_runner._effect.allocate_fence(
                    scope="harness-build:ooptdd-target-locked-other",
                    effect_id="effect:ooptdd-target-locked-other",
                )
            except BuildTargetOutcomeUnknown:
                pass
            else:
                raise RuntimeError("locked target escaped the transient boundary")
        finally:
            blocker.rollback()
            blocker.close()
        sqlite_constant_names = (
            "SQLITE_BUSY",
            "SQLITE_LOCKED",
            "SQLITE_READONLY",
            "SQLITE_INTERRUPT",
            "SQLITE_IOERR",
            "SQLITE_FULL",
            "SQLITE_CANTOPEN",
            "SQLITE_PROTOCOL",
        )
        saved_sqlite_constants = {
            name: getattr(local_build_execution_module.sqlite3, name)
            for name in sqlite_constant_names
            if hasattr(local_build_execution_module.sqlite3, name)
        }
        try:
            for name in saved_sqlite_constants:
                delattr(local_build_execution_module.sqlite3, name)
            translated = (
                local_build_execution_module._translated_target_sqlite_error(
                    sqlite3.OperationalError("database is locked")
                )
            )
        finally:
            for name, value in saved_sqlite_constants.items():
                setattr(local_build_execution_module.sqlite3, name, value)
        _require(
            isinstance(translated, BuildTargetOutcomeUnknown),
            "Python 3.10 SQLite surface escaped transient translation",
        )
        backend.ship([_event(cid, "target_sqlite_failures_are_typed")])

        group_root = root / "process-group"
        group_root.mkdir()
        delayed_marker = group_root / "delayed-marker"
        child = (
            "import time; from pathlib import Path; time.sleep(0.4); "
            f"Path({str(delayed_marker)!r}).write_text('escaped')"
        )
        leader = (
            "import subprocess, sys; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "print('leader-exit')"
        )
        group_command = f"{shlex.quote(sys.executable)} -c {shlex.quote(leader)}"
        group_runner, _ = _runtime(
            group_root,
            command=group_command,
            scope="harness-build:ooptdd-process-group",
            effect_id="effect:ooptdd-process-group",
        )
        group_run = group_runner(group_command)
        time.sleep(0.6)
        _require(group_run.returncode == 0, "process-group leader did not exit")
        _require(not delayed_marker.exists(), "background descendant escaped settlement")
        backend.ship([_event(cid, "ordinary_background_descendant_is_closed")])

        rollback_root = root / "clock-rollback"
        rollback_root.mkdir()
        rollback_marker = rollback_root / "marker"
        rollback_command = _command(rollback_marker)
        utc_values = iter(("2026-08-07T12:00:03Z", "2026-08-07T11:59:58Z"))
        monotonic_values = iter((1_000_000_000, 2_250_000_000))
        rollback_runner, rollback_journal = _runtime(
            rollback_root,
            command=rollback_command,
            scope="harness-build:ooptdd-clock-rollback",
            effect_id="effect:ooptdd-clock-rollback",
            utc_now=lambda: next(utc_values),
            monotonic_ns=lambda: next(monotonic_values),
            gate_clock=_RollbackAfterDispatchClock(),
        )
        rollback_runner(rollback_command)
        rollback_grant = rollback_journal.load(
            "harness-build:ooptdd-clock-rollback"
        ).state.grant(f"grant:{_sha('effect:ooptdd-clock-rollback')}")
        _require(
            rollback_grant.status is GrantStatus.SETTLED,
            "clock rollback stranded terminal use",
        )
        _require(
            rollback_grant.measured_at == "2026-08-07T12:00:04.250000Z",
            "clock rollback escaped the monotonic completion floor",
        )
        backend.ship([_event(cid, "clock_rollback_preserves_terminal_settlement")])

        unsafe_root = root / "unsafe-isolation"
        unsafe_root.mkdir()

        class _UnsafeIsolation(_TestIsolation):
            denies_provider_network = False

        unsafe = _UnsafeIsolation()
        unsafe_environment = {"PATH": os.environ.get("PATH", "")}
        unsafe_spec = BuildExecutionSpec(
            command="true",
            cwd=str(unsafe_root.resolve()),
            shell="/bin/sh",
            timeout_seconds=1,
            environment_sha256=environment_sha256(unsafe_environment),
            input_manifest_sha256=_sha("unsafe-inputs"),
            isolation_adapter=unsafe.adapter,
            isolation_version=unsafe.adapter_version,
            isolation_policy_sha256=unsafe.policy_sha256,
        )
        try:
            SQLiteFencedBuildEffect(
                unsafe_root / "target.sqlite3",
                spec=unsafe_spec,
                environment=unsafe_environment,
                isolation=unsafe,
                input_verifier=_StaticInputVerifier(
                    unsafe_spec.input_manifest_sha256
                ),
                authentication_key=bytes(range(64, 96)),
            )
        except ValueError:
            pass
        else:
            raise RuntimeError("provider-capable isolation reached the target adapter")
        backend.ship([_event(cid, "provider_denial_capability_is_required")])

        policy_root = root / "resource authority"
        profile = darwin_sandbox_profile(policy_root)
        policy_spec = BuildExecutionSpec(
            command="make test",
            cwd=str(root.resolve()),
            shell="/bin/sh",
            timeout_seconds=3,
            environment_sha256=environment_sha256({"PATH": "/bin"}),
            input_manifest_sha256=_sha("policy-inputs"),
            isolation_adapter="test",
            isolation_version="1",
            isolation_policy_sha256=_sha("policy"),
        )
        root_literal = json.dumps(str(policy_root.resolve()), ensure_ascii=False)
        expected_profile = "\n".join((
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            f"(deny file-read* (subpath {root_literal}))",
            f"(deny file-write* (subpath {root_literal}))",
        ))
        _require(profile == expected_profile, "Darwin sandbox profile drifted")
        _require(
            darwin_sandbox_argv(profile, policy_spec) == (
                "/usr/bin/sandbox-exec",
                "-p",
                profile,
                "/bin/sh",
                "-c",
                "make test",
            ),
            "Darwin sandbox argv drifted",
        )
        backend.ship([_event(cid, "darwin_sandbox_policy_is_exact")])

        closed = closed_build_environment({
            "PATH": "/bin",
            "GIT_AUTHOR_NAME": "Lakato Builder",
            "OPENAI_API_KEY": "secret",
            "SERVICE_AUTH_TOKEN": "secret",
            "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "1000",
        })
        _require(
            closed == {"PATH": "/bin", "GIT_AUTHOR_NAME": "Lakato Builder"},
            "closed build environment retained authority or credential material",
        )
        _closed_environment_mutant_must_turn_red()
        backend.ship([_event(cid, "closed_environment_secret_filter_is_load_bearing")])

        _require(
            resource_root_path_violation(
                prospective=Path("/work"),
                cwd=Path("/work/source"),
                home=Path("/home/user"),
            ) is not None,
            "resource authority root was allowed to contain the working tree",
        )
        root_mode = stat.S_IFDIR | 0o700
        _require(
            resource_root_metadata_violation(
                mode=root_mode,
                owner_uid=501,
                current_uid=501,
            ) is None,
            "owner-private directory facts were rejected",
        )
        for mode, owner in (
            (stat.S_IFLNK | 0o700, 501),
            (stat.S_IFDIR | 0o700, 502),
            (stat.S_IFDIR | 0o755, 501),
        ):
            _require(
                resource_root_metadata_violation(
                    mode=mode,
                    owner_uid=owner,
                    current_uid=501,
                ) is not None,
                "unsafe resource authority metadata was accepted",
            )
        _resource_root_mutants_must_turn_red()
        backend.ship([_event(cid, "resource_root_policy_is_load_bearing")])

        output_root = root / "output-limit"
        output_root.mkdir()
        output_source = "import sys; sys.stdout.write('x' * 8192); sys.stdout.flush()"
        output_command = (
            f"{shlex.quote(sys.executable)} -c {shlex.quote(output_source)}"
        )
        output_runner, output_journal = _runtime(
            output_root,
            command=output_command,
            scope="harness-build:ooptdd-output-limit",
            effect_id="effect:ooptdd-output-limit",
            output_tail_bytes=1024,
            max_output_bytes=4096,
        )
        output_run = output_runner(output_command)
        with sqlite3.connect(output_root / "target.sqlite3") as connection:
            result_blob = connection.execute(
                "SELECT result_blob FROM build_effects WHERE effect_id = ?",
                ("effect:ooptdd-output-limit",),
            ).fetchone()[0]
        terminal = json.loads(bytes(result_blob).decode("utf-8"))
        _require(output_run.returncode == 125, "output limit lost its typed exit code")
        _require(
            terminal["status"] == BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED.value,
            "output overflow was not terminalized",
        )
        _require(
            terminal["stdout_bytes"] + terminal["stderr_bytes"] == 4096,
            "output evidence exceeded or underfilled its hard bound",
        )
        _require(
            output_journal.load("harness-build:ooptdd-output-limit")
            .state.grant(f"grant:{_sha('effect:ooptdd-output-limit')}")
            .status is GrantStatus.SETTLED,
            "output overflow did not settle measured usage",
        )
        _output_cap_mutant_must_turn_red()
        backend.ship([_event(cid, "bounded_output_overflow_settles_terminally")])

        invalid_root = root / "invalid-output"
        invalid_root.mkdir()
        invalid_source = (
            "import sys; sys.stdout.buffer.write(b'\\xff' * 400000); "
            "sys.stdout.flush()"
        )
        invalid_command = (
            f"{shlex.quote(sys.executable)} -c {shlex.quote(invalid_source)}"
        )
        invalid_runner, invalid_journal = _runtime(
            invalid_root,
            command=invalid_command,
            scope="harness-build:ooptdd-invalid-output",
            effect_id="effect:ooptdd-invalid-output",
            output_tail_bytes=400_000,
            max_output_bytes=500_000,
        )
        invalid_run = invalid_runner(invalid_command)
        _require(invalid_run.returncode == 0, "invalid UTF-8 changed process status")
        _require(
            len(invalid_run.output.encode("utf-8")) <= 400_000,
            "replacement decoding expanded persisted evidence past its byte cap",
        )
        _require(
            invalid_journal.load("harness-build:ooptdd-invalid-output")
            .state.grant(f"grant:{_sha('effect:ooptdd-invalid-output')}")
            .status is GrantStatus.SETTLED,
            "invalid UTF-8 stranded a terminal claim",
        )
        backend.ship([_event(cid, "invalid_utf8_tail_remains_bounded_and_terminal")])

        cleanup_root = root / "stream-cleanup"
        cleanup_root.mkdir()
        cleanup_source = "import time; print('ready', flush=True); time.sleep(10)"
        cleanup_command = (
            f"{shlex.quote(sys.executable)} -c {shlex.quote(cleanup_source)}"
        )
        cleanup_runner, _ = _runtime(
            cleanup_root,
            command=cleanup_command,
            scope="harness-build:ooptdd-stream-cleanup",
            effect_id="effect:ooptdd-stream-cleanup",
        )
        real_popen = subprocess.Popen
        real_read = os.read
        observed = {"spawned": False, "wait_calls": 0, "process": None}

        def recording_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            real_wait = process.wait

            def recording_wait(*wait_args, **wait_kwargs):
                observed["wait_calls"] += 1
                return real_wait(*wait_args, **wait_kwargs)

            process.wait = recording_wait
            observed["process"] = process
            observed["spawned"] = True
            return process

        def fail_stream_read(fd, size):
            if not observed["spawned"]:
                return real_read(fd, size)
            raise OSError("injected stream read failure")

        local_build_execution_module.subprocess.Popen = recording_popen
        local_build_execution_module.os.read = fail_stream_read
        try:
            try:
                cleanup_runner(cleanup_command)
            except ResourceBuildOutcomeUnknown:
                pass
            else:
                raise RuntimeError("stream read failure did not remain outcome-unknown")
        finally:
            local_build_execution_module.subprocess.Popen = real_popen
            local_build_execution_module.os.read = real_read
        _require(observed["wait_calls"] >= 1, "exceptional cleanup never waited")
        _require(
            observed["process"] is not None
            and observed["process"].returncode is not None,
            "exceptional cleanup did not reap the subprocess leader",
        )
        backend.ship([_event(cid, "exceptional_stream_cleanup_reaps_leader")])

    _build_port_mutant_must_expose_forbidden_effect()
    backend.ship([_event(cid, "harness_build_port_wiring_load_bearing")])
    _environment_binding_mutant_must_collide()
    backend.ship([_event(cid, "workload_environment_binding_load_bearing")])
    _isolation_policy_binding_mutant_must_collide()
    backend.ship([_event(cid, "workload_isolation_policy_binding_load_bearing")])
