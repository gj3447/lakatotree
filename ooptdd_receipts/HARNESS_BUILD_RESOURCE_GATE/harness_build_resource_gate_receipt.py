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
    BuildAdmissionPolicy,
    BuildExecutionPolicy,
    BuildExecutionSpec,
    BuildTerminalStatus,
    DEFAULT_BUILD_ADMISSION_POLICY,
    DEFAULT_BUILD_EXECUTION_POLICY,
    ResourceBuildConfigError,
    ResourceBuildOutcomeUnknown,
    environment_sha256,
    reserved_compute_wall_ms,
    split_stream_budget,
)
from lakatos.harness import BuildFailed, CycleSpec, LakatoHarness  # noqa: E402
from lakatos.io import local_build_execution as local_build_execution_module  # noqa: E402
from lakatos.io.local_build_execution import (  # noqa: E402
    BuildDeploymentPolicyPort,
    BuildInputManifestError,
    BuildTargetError,
    BuildTargetOutcomeUnknown,
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
    effect_type=DeadlineBoundSQLiteFencedBuildEffect,
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
        adapter=effect_type.adapter,
        adapter_version=effect_type.adapter_version,
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
    effect = effect_type(
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
_ENVIRONMENT_ALLOWLIST_MARKER = (
    "        if (admitted is None or key in admitted)\n"
)
_MANIFEST_JSON_LIMIT_MARKER = (
    '            with path.open("rb") as stream:\n'
    "                raw = stream.read(policy.maximum_manifest_json_bytes + 1)\n"
    "            if len(raw) > policy.maximum_manifest_json_bytes:\n"
)
_INPUT_FILE_LIMIT_MARKER = (
    "                    if before.st_size > self.maximum_input_file_bytes:\n"
)
_NONBLOCK_FILE_OPEN_MARKER = (
    "    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK\n"
)
_DEADLINE_VERIFIER_PORT_MARKER = (
    "        if self._requires_deadline_bound_verifier and not callable(\n"
)
_DEADLINE_BOUND_EFFECT_VERSION_MARKER = (
    "    adapter_version = DEADLINE_BOUND_LOCAL_BUILD_ADAPTER_VERSION\n"
)
_DEADLINE_BOUND_TARGET_FILENAME_MARKER = (
    "    target_database_filename = _DEADLINE_BOUND_BUILD_TARGET_DATABASE_FILENAME\n"
)
_SPLIT_STREAM_BUDGET_MARKER = (
    "    return ((total_bytes + 1) // 2, total_bytes // 2)\n"
)
_DEPLOYMENT_RESOLUTION_MARKER = (
    "        deployment_policy = resolve_policy(policy_name)\n"
)
_INJECTED_BUILD_SELECTION_MARKER = (
    "    if selected_build is None and spec.build_cmd:\n"
)
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
_HARNESS_RUN_FILES = _LOCAL_BUILD_FILES + ("harness.py", "harness_run.py")


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
    def verify_until(self, deadline_monotonic_ns): return self.verify()

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
closed = closed_build_environment(
    {"PATH": "/bin", "OPENAI_API_KEY": "secret"},
    allowed_keys=("OPENAI_API_KEY", "PATH"),
)
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


def _environment_allowlist_mutant_must_turn_red() -> None:
    probe = r'''
from lakatos.io.local_build_execution import closed_build_environment
closed = closed_build_environment({
    "PATH": "/bin",
    "UNDECLARED_BUILD_TUNING": "must-not-cross",
}, allowed_keys=("PATH",))
raise SystemExit(0 if "UNDECLARED_BUILD_TUNING" in closed else 7)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _ENVIRONMENT_ALLOWLIST_MARKER,
                "        if True\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-environment-allowlist-mutant-",
    )
    _require(
        result.returncode == 0,
        "environment-allowlist removal mutant stayed green: "
        + result.stderr[-500:],
    )


def _execution_policy_field_mutants_must_collide() -> None:
    cases = (
        (
            "shell",
            "/usr/bin/sh",
            '            "shell": self.shell,\n'
            '            "output_tail_bytes": self.output_tail_bytes,\n',
            '            "shell": "/bin/sh",\n'
            '            "output_tail_bytes": self.output_tail_bytes,\n',
        ),
        (
            "output_tail_bytes",
            32_768,
            '            "shell": self.shell,\n'
            '            "output_tail_bytes": self.output_tail_bytes,\n',
            '            "shell": self.shell,\n'
            '            "output_tail_bytes": 65536,\n',
        ),
        (
            "max_output_bytes",
            20_000_000,
            '            "output_tail_bytes": self.output_tail_bytes,\n'
            '            "max_output_bytes": self.max_output_bytes,\n'
            '            "process_cleanup_grace_ms": self.process_cleanup_grace_ms,\n',
            '            "output_tail_bytes": self.output_tail_bytes,\n'
            '            "max_output_bytes": 16777216,\n'
            '            "process_cleanup_grace_ms": self.process_cleanup_grace_ms,\n',
        ),
        (
            "process_cleanup_grace_ms",
            1_250,
            '            "max_output_bytes": self.max_output_bytes,\n'
            '            "process_cleanup_grace_ms": self.process_cleanup_grace_ms,\n'
            '            "stream_capture_strategy": self.stream_capture_strategy,\n',
            '            "max_output_bytes": self.max_output_bytes,\n'
            '            "process_cleanup_grace_ms": 1000,\n'
            '            "stream_capture_strategy": self.stream_capture_strategy,\n',
        ),
    )
    for field, changed_value, marker, replacement in cases:
        probe = f'''
from lakatos.build_execution import BuildExecutionPolicy, DEFAULT_BUILD_EXECUTION_POLICY
base = DEFAULT_BUILD_EXECUTION_POLICY
changed = BuildExecutionPolicy(**{{**base.to_dict(), {field!r}: {changed_value!r}}})
raise SystemExit(0 if base.policy_sha256 == changed.policy_sha256 else 7)
'''
        result = _run_isolated(
            files=("resource_coordination.py", "build_execution.py"),
            replacements={"build_execution.py": (marker, replacement)},
            probe=probe,
            prefix=f"lakatotree-build-policy-{field}-mutant-",
        )
        _require(
            result.returncode == 0,
            f"execution-policy {field} omission mutant stayed green: "
            + result.stderr[-500:],
        )


def _manifest_bound_mutants_must_turn_red() -> None:
    json_probe = r'''
import hashlib
import json
from pathlib import Path
from lakatos.build_execution import BuildAdmissionPolicy, DEFAULT_BUILD_ADMISSION_POLICY
from lakatos.io.local_build_execution import VerifiedBuildInputManifest

root = Path("source")
root.mkdir()
relative = "declared-input-with-a-long-name-to-cross-the-json-boundary.txt"
content = b"v1"
(root / relative).write_bytes(content)
manifest = root / "manifest.json"
raw = json.dumps({
    "schema_version": "lakatotree.build-input-manifest/v1",
    "files": [{"path": relative, "sha256": hashlib.sha256(content).hexdigest()}],
}).encode()
assert len(raw) > 128
manifest.write_bytes(raw)
policy = BuildAdmissionPolicy(**{
    **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
    "maximum_manifest_json_bytes": 128,
})
VerifiedBuildInputManifest.load(manifest, root=root, policy=policy)
raise SystemExit(0)
'''
    json_result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _MANIFEST_JSON_LIMIT_MARKER,
                '            with path.open("rb") as stream:\n'
                "                raw = stream.read()\n"
                "            if False:\n",
            )
        },
        probe=json_probe,
        prefix="lakatotree-build-manifest-json-mutant-",
    )
    _require(
        json_result.returncode == 0,
        "manifest JSON-bound removal mutant stayed green: "
        + json_result.stderr[-500:],
    )

    file_probe = r'''
import hashlib
import json
from pathlib import Path
from lakatos.build_execution import BuildAdmissionPolicy, DEFAULT_BUILD_ADMISSION_POLICY
from lakatos.io.local_build_execution import VerifiedBuildInputManifest

root = Path("source")
root.mkdir()
content = b"four"
(root / "input.txt").write_bytes(content)
manifest = root / "manifest.json"
manifest.write_text(json.dumps({
    "schema_version": "lakatotree.build-input-manifest/v1",
    "files": [{"path": "input.txt", "sha256": hashlib.sha256(content).hexdigest()}],
}))
policy = BuildAdmissionPolicy(**{
    **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
    "maximum_input_file_bytes": 3,
})
VerifiedBuildInputManifest.load(manifest, root=root, policy=policy)
raise SystemExit(0)
'''
    file_result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _INPUT_FILE_LIMIT_MARKER,
                "                    if False:\n",
            )
        },
        probe=file_probe,
        prefix="lakatotree-build-input-file-bound-mutant-",
    )
    _require(
        file_result.returncode == 0,
        "per-file-bound removal mutant stayed green: "
        + file_result.stderr[-500:],
    )


def _nonblocking_file_open_mutant_must_turn_red() -> None:
    probe = r'''
import subprocess
import sys

child = r"""
import hashlib
import os
from pathlib import Path
import time
from lakatos.io.local_build_execution import VerifiedBuildInputManifest

root = Path("fifo-input")
root.mkdir()
path = root / "input.txt"
path.write_bytes(b"regular")
expected = hashlib.sha256(path.read_bytes()).hexdigest()
verifier = VerifiedBuildInputManifest(
    root=root.resolve(),
    entries=(("input.txt", expected),),
    manifest_sha256=hashlib.sha256(b"manifest").hexdigest(),
    maximum_input_file_bytes=1024,
    maximum_input_bytes=1024,
)
path.unlink()
os.mkfifo(path)
verifier.verify_until(time.monotonic_ns() + 100_000_000)
"""
try:
    subprocess.run([sys.executable, "-c", child], timeout=1, check=False)
except subprocess.TimeoutExpired:
    raise SystemExit(0)
raise SystemExit(7)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _NONBLOCK_FILE_OPEN_MARKER,
                "    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-blocking-fifo-mutant-",
    )
    _require(
        result.returncode == 0,
        "blocking FIFO-open mutant did not strand verification: "
        + result.stderr[-500:],
    )


def _deadline_verifier_port_mutant_must_turn_red() -> None:
    probe = r'''
import hashlib
from pathlib import Path
from lakatos.build_execution import BuildExecutionSpec, environment_sha256
from lakatos.io.local_build_execution import DeadlineBoundSQLiteFencedBuildEffect

sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
class Isolation:
    adapter = "test.isolation"
    adapter_version = "1"
    policy_sha256 = sha("policy")
    denies_provider_network = True
    protects_resource_root = True
    @staticmethod
    def argv(spec): return (spec.shell, "-c", spec.command)
class PreflightOnly:
    manifest_sha256 = sha("inputs")
    def verify(self): return None

root = Path("deadline-port")
root.mkdir()
spec = BuildExecutionSpec(
    command="true", cwd=str(root.resolve()), shell="/bin/sh", timeout_seconds=1,
    environment_sha256=environment_sha256({"PATH": "/bin"}),
    input_manifest_sha256=PreflightOnly.manifest_sha256,
    isolation_adapter=Isolation.adapter, isolation_version=Isolation.adapter_version,
    isolation_policy_sha256=Isolation.policy_sha256,
    adapter=DeadlineBoundSQLiteFencedBuildEffect.adapter,
    adapter_version=DeadlineBoundSQLiteFencedBuildEffect.adapter_version,
)
DeadlineBoundSQLiteFencedBuildEffect(
    root / "target.sqlite3", spec=spec, environment={"PATH": "/bin"},
    isolation=Isolation(), input_verifier=PreflightOnly(),
    authentication_key=bytes(range(32)),
)
raise SystemExit(0)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _DEADLINE_VERIFIER_PORT_MARKER,
                "        if False and not callable(\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-deadline-verifier-mutant-",
    )
    _require(
        result.returncode == 0,
        "deadline-verifier port guard mutant stayed green: "
        + result.stderr[-500:],
    )


def _versioned_effect_boundary_mutant_must_turn_red() -> None:
    probe = r'''
from lakatos.io.local_build_execution import (
    DeadlineBoundSQLiteFencedBuildEffect,
    SQLiteFencedBuildEffect,
)
raise SystemExit(
    0
    if DeadlineBoundSQLiteFencedBuildEffect.adapter_version
    == SQLiteFencedBuildEffect.adapter_version
    else 7
)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _DEADLINE_BOUND_EFFECT_VERSION_MARKER,
                "    adapter_version = LOCAL_BUILD_ADAPTER_VERSION\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-effect-version-mutant-",
    )
    _require(
        result.returncode == 0,
        "deadline-bound effect identity mutant stayed green: "
        + result.stderr[-500:],
    )
    filename_probe = r'''
from lakatos.io.local_build_execution import (
    DeadlineBoundSQLiteFencedBuildEffect,
    SQLiteFencedBuildEffect,
)
raise SystemExit(
    0
    if DeadlineBoundSQLiteFencedBuildEffect.target_database_filename
    == SQLiteFencedBuildEffect.target_database_filename
    else 7
)
'''
    filename_result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _DEADLINE_BOUND_TARGET_FILENAME_MARKER,
                "    target_database_filename = _LEGACY_BUILD_TARGET_DATABASE_FILENAME\n",
            )
        },
        probe=filename_probe,
        prefix="lakatotree-build-target-filename-mutant-",
    )
    _require(
        filename_result.returncode == 0,
        "deadline-bound target filename mutant stayed green: "
        + filename_result.stderr[-500:],
    )


def _stream_split_mutant_must_turn_red() -> None:
    probe = r'''
from lakatos.build_execution import split_stream_budget
raise SystemExit(0 if split_stream_budget(5) == (5, 5) else 7)
'''
    result = _run_isolated(
        files=("resource_coordination.py", "build_execution.py"),
        replacements={
            "build_execution.py": (
                _SPLIT_STREAM_BUDGET_MARKER,
                "    return (total_bytes, total_bytes)\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-stream-split-mutant-",
    )
    _require(
        result.returncode == 0,
        "shared-per-stream output budget mutant stayed green: "
        + result.stderr[-500:],
    )


def _deployment_resolution_mutant_must_turn_red() -> None:
    probe = r'''
import hashlib
import json
from pathlib import Path
import lakatos.io.local_build_execution as module
from lakatos.build_execution import (
    DEFAULT_BUILD_ADMISSION_POLICY, DEFAULT_BUILD_EXECUTION_POLICY,
)

class Isolation:
    adapter = "test.portable-isolation"
    adapter_version = "1"
    policy_sha256 = hashlib.sha256(b"portable").hexdigest()
    denies_provider_network = True
    protects_resource_root = True
    @staticmethod
    def argv(spec): return (spec.shell, "-c", spec.command)

class Policy:
    name = "darwin-sandbox-exec/v1"
    execution_policy = DEFAULT_BUILD_EXECUTION_POLICY
    admission_policy = DEFAULT_BUILD_ADMISSION_POLICY
    @staticmethod
    def create_isolation(_root): return Isolation()

class Resolver:
    @staticmethod
    def resolve(_name): return Policy()

source = Path("source")
source.mkdir()
content = b"v1"
(source / "input.txt").write_bytes(content)
manifest = source / "manifest.json"
manifest.write_text(json.dumps({
    "schema_version": "lakatotree.build-input-manifest/v1",
    "files": [{"path": "input.txt", "sha256": hashlib.sha256(content).hexdigest()}],
}))
environment = {
    "PATH": "/bin",
    "LAKATOTREE_RESOURCE_BUILD_DIR": str(Path("resource").resolve()),
    "LAKATOTREE_RESOURCE_BUILD_POLICY": Policy.name,
    "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
    "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
    "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
    "LAKATOTREE_BUILD_INPUT_MANIFEST": str(manifest.resolve()),
}
original = module.DarwinSandboxExecIsolation
def forbidden_darwin(*_args, **_kwargs):
    raise RuntimeError("injected resolver was bypassed")
try:
    module.DarwinSandboxExecIsolation = forbidden_darwin
    old = Path.cwd()
    try:
        import os
        os.chdir(source)
        module.resource_gated_build_runner_from_environment(
            tree="T", tag="v1", command="true", timeout_seconds=1,
            environment=environment, deployment_policy_resolver=Resolver(),
        )
    finally:
        os.chdir(old)
except RuntimeError as exc:
    raise SystemExit(0 if "bypassed" in str(exc) else 8)
finally:
    module.DarwinSandboxExecIsolation = original
raise SystemExit(7)
'''
    result = _run_isolated(
        files=_LOCAL_BUILD_FILES,
        replacements={
            "io/local_build_execution.py": (
                _DEPLOYMENT_RESOLUTION_MARKER,
                "        deployment_policy = DarwinBuildDeploymentPolicy()\n",
            )
        },
        probe=probe,
        prefix="lakatotree-build-deployment-resolution-mutant-",
    )
    _require(
        result.returncode == 0,
        "Darwin-construction mutant did not bypass the injected resolver: "
        + result.stderr[-500:],
    )


def _injected_build_selection_mutant_must_turn_red() -> None:
    probe = r'''
import json
from pathlib import Path
from lakatos import harness_run

spec = Path("spec.json")
spec.write_text(json.dumps({
    "tree": "T", "tag": "v1", "parent": "root", "metric": "m",
    "baseline": 0, "build_cmd": "make", "judge_cmd": "echo metric=1",
}))
def http(_method, path, _body=None):
    if path.endswith("/test_result"):
        return {"verdict": "progressive", "novel": None, "delta": 1}
    if path.endswith("/standing"):
        return {"stands": True}
    return {"ok": True}
def forbidden_factory(**_kwargs):
    raise RuntimeError("explicit run_build was ignored")
harness_run._http = http
harness_run._bash = lambda _command: ("metric=1", 0)
harness_run._git_sha = lambda: "abc123"
harness_run.resource_gated_build_runner_from_environment = forbidden_factory
try:
    harness_run.main(spec, run_build=lambda _command: ("build-ok", 0))
except RuntimeError as exc:
    raise SystemExit(0 if "ignored" in str(exc) else 8)
raise SystemExit(7)
'''
    result = _run_isolated(
        files=_HARNESS_RUN_FILES,
        replacements={
            "harness_run.py": (
                _INJECTED_BUILD_SELECTION_MARKER,
                "    if spec.build_cmd:\n",
            )
        },
        probe=probe,
        prefix="lakatotree-harness-run-build-selection-mutant-",
    )
    _require(
        result.returncode == 0,
        "explicit run_build override mutant stayed green: "
        + result.stderr[-500:],
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
            {**base, "execution_policy_sha256": _sha("other-execution-policy")},
            {**base, "process_cleanup_grace_ms": 750},
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

        base_policy = DEFAULT_BUILD_EXECUTION_POLICY
        bounded_policy = BuildExecutionPolicy(**{
            **base_policy.to_dict(),
            "process_cleanup_grace_ms": (
                base_policy.process_cleanup_grace_ms + 250
            ),
        })
        policy_arguments = dict(
            command="make",
            cwd=str(root.resolve()),
            timeout_seconds=7,
            environment_sha256=environment_sha256({"PATH": "/bin"}),
            input_manifest_sha256=_sha("policy-inputs"),
            isolation_adapter=_TestIsolation.adapter,
            isolation_version=_TestIsolation.adapter_version,
            isolation_policy_sha256=_TestIsolation.policy_sha256,
        )
        base_policy_spec = base_policy.make_spec(**policy_arguments)
        bounded_policy_spec = bounded_policy.make_spec(**policy_arguments)
        _require(
            base_policy_spec.workload_sha256
            != bounded_policy_spec.workload_sha256,
            "execution policy did not change workload identity",
        )
        _require(
            reserved_compute_wall_ms(base_policy_spec)
            == base_policy.reserved_compute_wall_ms(7),
            "execution policy and scheduler reservation diverged",
        )
        _execution_policy_field_mutants_must_collide()
        backend.ship([_event(cid, "execution_policy_is_identity_bound")])

        base_admission = DEFAULT_BUILD_ADMISSION_POLICY
        tuned_admission = BuildAdmissionPolicy(**{
            **base_admission.to_dict(),
            "target_sqlite_timeout_ms": base_admission.target_sqlite_timeout_ms + 1,
        })
        _require(
            tuned_admission.policy_sha256 != base_admission.policy_sha256,
            "admission policy tuning was not independently identified",
        )
        _require(
            base_admission.to_dict().keys().isdisjoint(base_policy.to_dict()),
            "physical and admission policy ownership overlapped",
        )
        _require(
            base_policy.make_spec(**policy_arguments).workload_sha256
            == base_policy_spec.workload_sha256,
            "non-input admission tuning changed physical workload identity",
        )
        inherited_environment = {
            "PATH": "/bin",
            "ORDINARY_BUILD_FLAG": "enabled",
        }
        default_environment = closed_build_environment(inherited_environment)
        allowlisted_environment = closed_build_environment(
            inherited_environment,
            allowed_keys=("PATH",),
        )
        default_environment_spec = base_policy.make_spec(**{
            **policy_arguments,
            "environment_sha256": environment_sha256(default_environment),
        })
        allowlisted_environment_spec = base_policy.make_spec(**{
            **policy_arguments,
            "environment_sha256": environment_sha256(allowlisted_environment),
        })
        _require(
            default_environment_spec.workload_sha256
            != allowlisted_environment_spec.workload_sha256,
            "input-shaping environment selection escaped workload identity",
        )
        backend.ship([_event(
            cid,
            "operational_admission_and_environment_identity_are_separate",
        )])

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

        bounded_root = root / "bounded-input"
        bounded_root.mkdir()
        (bounded_root / "a.txt").write_text("aaaa", encoding="utf-8")
        (bounded_root / "b.txt").write_text("bbbb", encoding="utf-8")
        bounded_manifest = _write_manifest(bounded_root, "a.txt", "b.txt")
        one_entry_policy = BuildAdmissionPolicy(**{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_manifest_entries": 1,
        })
        try:
            VerifiedBuildInputManifest.load(
                bounded_manifest,
                root=bounded_root,
                policy=one_entry_policy,
            )
        except BuildInputManifestError as exc:
            _require("entry limit" in str(exc), "entry bound lost its typed reason")
        else:
            raise RuntimeError("manifest entry bound was not enforced")
        three_byte_file_policy = BuildAdmissionPolicy(**{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_input_file_bytes": 3,
        })
        try:
            VerifiedBuildInputManifest.load(
                bounded_manifest,
                root=bounded_root,
                policy=three_byte_file_policy,
            )
        except BuildInputManifestError as exc:
            _require(
                "per-file byte limit" in str(exc),
                "per-file bound lost its typed reason",
            )
        else:
            raise RuntimeError("manifest per-file byte bound was not enforced")
        six_byte_policy = BuildAdmissionPolicy(**{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_input_bytes": 6,
        })
        try:
            VerifiedBuildInputManifest.load(
                bounded_manifest,
                root=bounded_root,
                policy=six_byte_policy,
            )
        except BuildInputManifestError as exc:
            _require(
                "declared byte limit" in str(exc),
                "input byte bound lost its typed reason",
            )
        else:
            raise RuntimeError("manifest input byte bound was not enforced")
        compatibility_environment = {
            "PATH": "/bin",
            "GIT_AUTHOR_NAME": "Lakato Builder",
            "UNDECLARED_BUILD_TUNING": "legacy-compatible",
        }
        _require(
            closed_build_environment(compatibility_environment)
            == compatibility_environment,
            "default environment policy broke legacy ordinary variables",
        )
        _require(
            closed_build_environment(
                compatibility_environment,
                allowed_keys=("GIT_AUTHOR_NAME", "PATH"),
            ) == {
                "PATH": "/bin",
                "GIT_AUTHOR_NAME": "Lakato Builder",
            },
            "explicit environment allowlist admitted an undeclared key",
        )
        oversized_manifest = bounded_root / "oversized-manifest.json"
        oversized_manifest.write_bytes(b" " * 129)
        tiny_json_policy = BuildAdmissionPolicy(**{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "maximum_manifest_json_bytes": 128,
        })
        try:
            VerifiedBuildInputManifest.load(
                oversized_manifest,
                root=bounded_root,
                policy=tiny_json_policy,
            )
        except BuildInputManifestError as exc:
            _require("JSON byte limit" in str(exc), "JSON bound lost its typed reason")
        else:
            raise RuntimeError("manifest JSON byte bound was not enforced")
        _manifest_bound_mutants_must_turn_red()
        _environment_allowlist_mutant_must_turn_red()
        backend.ship([_event(cid, "bounded_manifest_and_allowlisted_environment")])

        descriptor_root = root / "descriptor-input"
        descriptor_root.mkdir()
        descriptor_path = descriptor_root / "input.txt"
        descriptor_path.write_bytes(b"abcd")
        descriptor_verifier = VerifiedBuildInputManifest.load(
            _write_manifest(descriptor_root, "input.txt"),
            root=descriptor_root,
        )
        real_read = local_build_execution_module.os.read
        read_calls = {"count": 0}

        def growing_read(descriptor, size):
            read_calls["count"] += 1
            if read_calls["count"] == 2:
                return b"x"
            return real_read(descriptor, size)

        local_build_execution_module.os.read = growing_read
        try:
            try:
                descriptor_verifier.verify()
            except BuildInputManifestError as exc:
                _require("grew while reading" in str(exc), "growth lost typed reason")
            else:
                raise RuntimeError("descriptor growth was accepted")
        finally:
            local_build_execution_module.os.read = real_read
        _require(read_calls["count"] == 2, "descriptor verifier skipped EOF probe")
        def failed_read(_descriptor, _size):
            raise OSError("injected descriptor failure")

        local_build_execution_module.os.read = failed_read
        try:
            try:
                descriptor_verifier.verify()
            except BuildInputManifestError as exc:
                _require(
                    "could not be read safely" in str(exc),
                    "descriptor I/O failure escaped its typed boundary",
                )
            else:
                raise RuntimeError("descriptor I/O failure was accepted")
        finally:
            local_build_execution_module.os.read = real_read
        observed_open_flags = []
        real_open = local_build_execution_module.os.open

        def recording_open(path, flags, *args, **kwargs):
            if path == "input.txt":
                observed_open_flags.append(flags)
            return real_open(path, flags, *args, **kwargs)

        local_build_execution_module.os.open = recording_open
        try:
            descriptor_verifier.verify_until(time.monotonic_ns() + 1_000_000_000)
        finally:
            local_build_execution_module.os.open = real_open
        _require(
            observed_open_flags
            and observed_open_flags[-1] & os.O_NONBLOCK,
            "final input descriptor open can block on a FIFO race",
        )
        _nonblocking_file_open_mutant_must_turn_red()
        backend.ship([_event(cid, "descriptor_snapshot_rejects_input_growth")])

        portable_source = root / "portable-source"
        portable_source.mkdir()
        (portable_source / "input.txt").write_text("v1", encoding="utf-8")
        portable_manifest = _write_manifest(portable_source, "input.txt")
        portable_policy = BuildExecutionPolicy(**{
            **DEFAULT_BUILD_EXECUTION_POLICY.to_dict(),
            "process_cleanup_grace_ms": 250,
        })
        portable_admission_policy = BuildAdmissionPolicy(**{
            **DEFAULT_BUILD_ADMISSION_POLICY.to_dict(),
            "environment_allowlist": ("PATH",),
        })

        class PortableDeploymentPolicy:
            name = "ooptdd-portable/v1"
            execution_policy = portable_policy
            admission_policy = portable_admission_policy

            def __init__(self):
                self.calls = 0

            def create_isolation(self, _protected_root):
                self.calls += 1
                return _TestIsolation()

        class PortableResolver:
            def __init__(self, selected):
                self.selected = selected
                self.names = []

            def resolve(self, name):
                self.names.append(name)
                return self.selected

        selected_policy = PortableDeploymentPolicy()
        portable_resolver = PortableResolver(selected_policy)
        portable_resource_root = root / "portable-resource"
        portable_environment = {
            "PATH": os.environ.get("PATH", ""),
            "LAKATOTREE_RESOURCE_BUILD_DIR": str(portable_resource_root),
            "LAKATOTREE_RESOURCE_BUILD_POLICY": selected_policy.name,
            "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX": bytes(range(32)).hex(),
            "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX": bytes(range(32, 64)).hex(),
            "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS": "20000",
            "LAKATOTREE_BUILD_INPUT_MANIFEST": str(portable_manifest),
        }
        original_cwd = Path.cwd()
        original_darwin = local_build_execution_module.DarwinSandboxExecIsolation

        def forbidden_darwin(*_args, **_kwargs):
            raise RuntimeError("injected deployment policy was bypassed")

        try:
            os.chdir(portable_source)
            local_build_execution_module.DarwinSandboxExecIsolation = forbidden_darwin
            portable_runner = resource_gated_build_runner_from_environment(
                tree="OOPTDD-T",
                tag="v1",
                command="true",
                timeout_seconds=1,
                environment=portable_environment,
                deployment_policy_resolver=portable_resolver,
            )
        finally:
            local_build_execution_module.DarwinSandboxExecIsolation = original_darwin
            os.chdir(original_cwd)
        _require(
            isinstance(selected_policy, BuildDeploymentPolicyPort),
            "injected deployment policy did not satisfy its structural port",
        )
        _require(portable_runner is not None, "portable policy did not compose")
        _require(
            portable_resolver.names == [selected_policy.name]
            and selected_policy.calls == 1,
            "composition did not route through the selected policy",
        )
        _require(
            portable_runner._request.estimate.upper_bound.compute_wall_ms == 1_250,
            "injected cleanup grace did not reach scheduling",
        )
        unknown_root = root / "unknown-policy-must-not-exist"
        try:
            resource_gated_build_runner_from_environment(
                tree="OOPTDD-T",
                tag="unknown",
                command="true",
                timeout_seconds=1,
                environment={
                    "LAKATOTREE_RESOURCE_BUILD_DIR": str(unknown_root),
                    "LAKATOTREE_RESOURCE_BUILD_POLICY": "unknown/v99",
                },
            )
        except ResourceBuildConfigError as exc:
            _require(
                "unknown resource build policy" in str(exc),
                "unknown selector lost its typed reason",
            )
        else:
            raise RuntimeError("unknown deployment policy was accepted")
        _require(
            not unknown_root.exists(),
            "unknown deployment policy caused a filesystem side effect",
        )
        _deployment_resolution_mutant_must_turn_red()
        backend.ship([_event(cid, "deployment_policy_is_injected_and_preflighted")])

        class PreflightOnlyVerifier:
            manifest_sha256 = _sha("preflight-only")

            def verify(self):
                return None

        deadline_port_root = root / "deadline-verifier-port"
        deadline_port_root.mkdir()
        try:
            _runtime(
                deadline_port_root,
                command="true",
                scope="harness-build:ooptdd-deadline-port",
                effect_id="effect:ooptdd-deadline-port",
                input_verifier=PreflightOnlyVerifier(),
            )
        except ValueError as exc:
            _require(
                "deadline-aware verify_until" in str(exc),
                "deadline verifier refusal lost its typed reason",
            )
        else:
            raise RuntimeError("preflight-only verifier crossed the durable effect port")
        _require(
            not (deadline_port_root / "target.sqlite3").exists(),
            "invalid verifier caused durable target I/O",
        )
        _deadline_verifier_port_mutant_must_turn_red()
        backend.ship([_event(cid, "deadline_aware_verifier_port_is_required")])

        class VerifyOnlyInputVerifier:
            manifest_sha256 = _sha("legacy-inputs")

            def __init__(self):
                self.calls = 0

            def verify(self):
                self.calls += 1

        legacy_root = root / "legacy-verifier-effect"
        legacy_root.mkdir()
        legacy_marker = legacy_root / "marker"
        legacy_command = _command(legacy_marker)
        legacy_verifier = VerifyOnlyInputVerifier()
        legacy_runner, _legacy_journal = _runtime(
            legacy_root,
            command=legacy_command,
            scope="harness-build:ooptdd-legacy-port",
            effect_id="effect:ooptdd-legacy-port",
            input_verifier=legacy_verifier,
            effect_type=SQLiteFencedBuildEffect,
        )
        legacy_result = legacy_runner(legacy_command)
        _require(legacy_result.returncode == 0, "legacy verifier effect did not run")
        _require(legacy_verifier.calls == 3, "legacy verifier call contract drifted")
        _require(
            isinstance(portable_runner._effect, DeadlineBoundSQLiteFencedBuildEffect),
            "production factory did not select the deadline-bound effect",
        )
        _require(
            SQLiteFencedBuildEffect.adapter_version
            != DeadlineBoundSQLiteFencedBuildEffect.adapter_version,
            "legacy evidence can collide with deadline-bound effect identity",
        )
        _require(
            SQLiteFencedBuildEffect.target_database_filename
            != DeadlineBoundSQLiteFencedBuildEffect.target_database_filename,
            "legacy and deadline-bound target stores share a filename",
        )
        upgrade_root = root / "versioned-target-upgrade"
        upgrade_root.mkdir(mode=0o700)
        upgrade_root.chmod(0o700)
        upgrade_environment = {"PATH": os.environ.get("PATH", "")}
        upgrade_isolation = _TestIsolation()
        legacy_spec = BuildExecutionSpec(
            command="true",
            cwd=str(portable_source.resolve()),
            shell="/bin/sh",
            timeout_seconds=1,
            environment_sha256=environment_sha256(upgrade_environment),
            input_manifest_sha256=_sha("upgrade-legacy-inputs"),
            isolation_adapter=upgrade_isolation.adapter,
            isolation_version=upgrade_isolation.adapter_version,
            isolation_policy_sha256=upgrade_isolation.policy_sha256,
            adapter=SQLiteFencedBuildEffect.adapter,
            adapter_version=SQLiteFencedBuildEffect.adapter_version,
        )
        legacy_target_path = (
            upgrade_root / SQLiteFencedBuildEffect.target_database_filename
        )
        legacy_target = SQLiteFencedBuildEffect(
            legacy_target_path,
            spec=legacy_spec,
            environment=upgrade_environment,
            isolation=upgrade_isolation,
            input_verifier=_StaticInputVerifier(legacy_spec.input_manifest_sha256),
            authentication_key=bytes(range(64, 96)),
        )
        legacy_target_bytes = legacy_target_path.read_bytes()
        upgrade_policy = PortableDeploymentPolicy()
        upgrade_resolver = PortableResolver(upgrade_policy)
        upgrade_factory_environment = {
            **portable_environment,
            "LAKATOTREE_RESOURCE_BUILD_DIR": str(upgrade_root),
        }
        try:
            os.chdir(portable_source)
            upgrade_runner = resource_gated_build_runner_from_environment(
                tree="OOPTDD-upgrade",
                tag="v2",
                command="true",
                timeout_seconds=1,
                environment=upgrade_factory_environment,
                deployment_policy_resolver=upgrade_resolver,
            )
        finally:
            os.chdir(original_cwd)
        deadline_target_path = (
            upgrade_root
            / DeadlineBoundSQLiteFencedBuildEffect.target_database_filename
        )
        _require(upgrade_runner is not None, "v1 target blocked v2 composition")
        _require(deadline_target_path.exists(), "v2 target store was not created")
        _require(
            legacy_target_path.read_bytes() == legacy_target_bytes,
            "v2 composition modified the v1 target store",
        )
        with legacy_target._scope_lock("upgrade-lock"):
            pass
        with upgrade_runner._effect._scope_lock("upgrade-lock"):
            pass
        lock_names = {path.name for path in upgrade_root.glob(".*.lock")}
        _require(
            any(legacy_target_path.name in name for name in lock_names)
            and any(deadline_target_path.name in name for name in lock_names),
            "v1 and v2 target lock namespaces collided",
        )
        _versioned_effect_boundary_mutant_must_turn_red()
        backend.ship([_event(
            cid,
            "versioned_effect_boundary_preserves_legacy_verifier_compatibility",
        )])

        class ChangesAfterClaim(_StaticInputVerifier):
            def __init__(self):
                super().__init__(_sha("postclaim-inputs"))
                self.calls = 0

            def verify(self):
                self.calls += 1
                if self.calls == 2:
                    raise BuildInputManifestError("declared input changed after claim")

        postclaim_root = root / "postclaim-input-refusal"
        postclaim_root.mkdir()
        postclaim_marker = postclaim_root / "must-not-run"
        postclaim_command = _command(postclaim_marker)
        postclaim_verifier = ChangesAfterClaim()
        postclaim_runner, postclaim_journal = _runtime(
            postclaim_root,
            command=postclaim_command,
            scope="harness-build:ooptdd-postclaim-refusal",
            effect_id="effect:ooptdd-postclaim-refusal",
            input_verifier=postclaim_verifier,
        )
        postclaim_run = postclaim_runner(postclaim_command)
        postclaim_result, _ = postclaim_runner._effect.load_terminal_result(
            effect_id="effect:ooptdd-postclaim-refusal",
            workload_sha256=postclaim_runner._start.workload_sha256,
        )
        _require(not postclaim_marker.exists(), "rejected input launched the build")
        _require(postclaim_run.returncode == 126, "input refusal lost its exit code")
        _require(
            postclaim_result.status is BuildTerminalStatus.INPUT_REJECTED,
            "post-claim input refusal was not terminalized",
        )
        _require(
            postclaim_journal.load("harness-build:ooptdd-postclaim-refusal")
            .state.grant(f"grant:{_sha('effect:ooptdd-postclaim-refusal')}")
            .status is GrantStatus.SETTLED,
            "post-claim input refusal stranded its resource grant",
        )
        _require(postclaim_verifier.calls == 2, "input verification count drifted")
        backend.ship([_event(cid, "postclaim_input_refusal_terminalizes")])

        class MutableMonotonicClock:
            now = 1_000_000_000

            def __call__(self):
                return self.now

        class SlowChangedInput(_StaticInputVerifier):
            def __init__(self, clock):
                super().__init__(_sha("metered-inputs"))
                self.clock = clock
                self.calls = 0

            def verify(self):
                self.calls += 1
                if self.calls == 2:
                    self.clock.now += 250_000_000
                    raise BuildInputManifestError("slow declared input change")

        metered_clock = MutableMonotonicClock()
        metered_verifier = SlowChangedInput(metered_clock)
        metered_root = root / "metered-input-refusal"
        metered_root.mkdir()
        metered_marker = metered_root / "must-not-run"
        metered_command = _command(metered_marker)
        metered_runner, _ = _runtime(
            metered_root,
            command=metered_command,
            scope="harness-build:ooptdd-metered-input-refusal",
            effect_id="effect:ooptdd-metered-input-refusal",
            input_verifier=metered_verifier,
            monotonic_ns=metered_clock,
        )
        metered_runner(metered_command)
        metered_result, _ = metered_runner._effect.load_terminal_result(
            effect_id="effect:ooptdd-metered-input-refusal",
            workload_sha256=metered_runner._start.workload_sha256,
        )
        _require(not metered_marker.exists(), "metered input refusal launched build")
        _require(
            metered_result.elapsed_monotonic_ns == 250_000_000
            and metered_result.compute_wall_ms == 250,
            "post-claim verification time escaped compute evidence",
        )
        backend.ship([_event(cid, "postclaim_verification_time_is_metered")])

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
        monotonic_values = iter((1_000_000_000, 1_000_000_000, 2_250_000_000))
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
            adapter=DeadlineBoundSQLiteFencedBuildEffect.adapter,
            adapter_version=DeadlineBoundSQLiteFencedBuildEffect.adapter_version,
        )
        try:
            DeadlineBoundSQLiteFencedBuildEffect(
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
            terminal["stdout_bytes"] == split_stream_budget(4096)[0]
            and terminal["stderr_bytes"] == 0,
            "stdout escaped its deterministic no-borrow stream quota",
        )
        _require(
            output_journal.load("harness-build:ooptdd-output-limit")
            .state.grant(f"grant:{_sha('effect:ooptdd-output-limit')}")
            .status is GrantStatus.SETTLED,
            "output overflow did not settle measured usage",
        )
        _output_cap_mutant_must_turn_red()
        backend.ship([_event(cid, "bounded_output_overflow_settles_terminally")])
        _require(
            split_stream_budget(5) == (3, 2),
            "odd output budget lost its deterministic split",
        )

        class RejectsAfterPreflight(_StaticInputVerifier):
            def __init__(self):
                super().__init__(_sha("synthetic-input-refusal"))
                self.calls = 0

            def verify(self):
                self.calls += 1
                if self.calls == 2:
                    raise BuildInputManifestError("changed")

        synthetic_refusal_root = root / "synthetic-input-refusal"
        synthetic_refusal_root.mkdir()
        synthetic_refusal_runner, _ = _runtime(
            synthetic_refusal_root,
            command="true",
            scope="harness-build:ooptdd-synthetic-refusal",
            effect_id="effect:ooptdd-synthetic-refusal",
            input_verifier=RejectsAfterPreflight(),
            output_tail_bytes=1,
            max_output_bytes=1,
        )
        synthetic_refusal_runner("true")
        synthetic_refusal, _ = (
            synthetic_refusal_runner._effect.load_terminal_result(
                effect_id="effect:ooptdd-synthetic-refusal",
                workload_sha256=synthetic_refusal_runner._start.workload_sha256,
            )
        )

        synthetic_spawn_root = root / "synthetic-spawn-failure"
        synthetic_spawn_root.mkdir()
        synthetic_spawn_runner, _ = _runtime(
            synthetic_spawn_root,
            command="true",
            scope="harness-build:ooptdd-synthetic-spawn",
            effect_id="effect:ooptdd-synthetic-spawn",
            output_tail_bytes=1,
            max_output_bytes=1,
        )
        real_popen = local_build_execution_module.subprocess.Popen

        def fail_spawn(*_args, **_kwargs):
            raise OSError("injected spawn failure")

        local_build_execution_module.subprocess.Popen = fail_spawn
        try:
            synthetic_spawn_runner("true")
        finally:
            local_build_execution_module.subprocess.Popen = real_popen
        synthetic_spawn, _ = synthetic_spawn_runner._effect.load_terminal_result(
            effect_id="effect:ooptdd-synthetic-spawn",
            workload_sha256=synthetic_spawn_runner._start.workload_sha256,
        )
        _require(
            synthetic_refusal.status is BuildTerminalStatus.INPUT_REJECTED
            and synthetic_spawn.status is BuildTerminalStatus.SPAWN_FAILED
            and synthetic_refusal.stderr_bytes == 0
            and synthetic_spawn.stderr_bytes == 0
            and synthetic_refusal.output_tail == ""
            and synthetic_spawn.output_tail == "",
            "synthetic stderr bypassed the split stream quota",
        )
        _stream_split_mutant_must_turn_red()
        backend.ship([_event(cid, "stream_capture_budget_is_deterministically_split")])

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
            max_output_bytes=800_000,
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
    _injected_build_selection_mutant_must_turn_red()
    backend.ship([_event(cid, "explicit_run_build_override_is_preserved")])
