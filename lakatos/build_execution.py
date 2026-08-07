"""Pure contracts for a resource-accounted local subprocess build.

The values in this module bind every declared execution input before the I/O
shell can reserve resources or launch a process.  They read no clock,
environment, filesystem, journal, database, or subprocess.  The local adapter
is intentionally scoped to provider-free build/TDD commands: token usage is
therefore zero by contract, not guessed from arbitrary model traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import PurePath
import re
from typing import Mapping

from lakatos.resource_coordination import ResourceUsage, ResourceVector


BUILD_EXECUTION_SCHEMA_VERSION = "lakatotree.build-execution/v2"
_LEGACY_BUILD_EXECUTION_SCHEMA_VERSION = "lakatotree.build-execution/v1"
LOCAL_BUILD_ADAPTER = "lakatotree.local-subprocess-build"
LOCAL_BUILD_ADAPTER_VERSION = "1"
DEADLINE_BOUND_LOCAL_BUILD_ADAPTER_VERSION = "2"
_WORKLOAD_DOMAIN = b"lakatotree-local-build-workload\x00v2\n"
_EVIDENCE_DOMAIN = b"lakatotree-local-build-evidence\x00v1\n"
_MEASUREMENT_DOMAIN = b"lakatotree-local-build-measurement\x00v1\n"
_ENVIRONMENT_DOMAIN = b"lakatotree-local-build-environment\x00v1\n"
_EXECUTION_POLICY_DOMAIN = b"lakatotree-build-execution-policy\x00v1\n"
_ADMISSION_POLICY_DOMAIN = b"lakatotree-build-admission-policy\x00v1\n"
SPLIT_STREAM_CAPTURE_STRATEGY = "stdout-ceil-stderr-floor-no-borrow/v1"
HARDENED_BUILD_ENVIRONMENT_ALLOWLIST = (
    "ARCHFLAGS",
    "CC",
    "CFLAGS",
    "CI",
    "CMAKE_BUILD_PARALLEL_LEVEL",
    "CMAKE_PREFIX_PATH",
    "CONDA_PREFIX",
    "CPPFLAGS",
    "CXX",
    "CXXFLAGS",
    "FORCE_COLOR",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_NAME",
    "GOFLAGS",
    "GOMODCACHE",
    "GOPATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LDFLAGS",
    "MACOSX_DEPLOYMENT_TARGET",
    "MAKEFLAGS",
    "NODE_PATH",
    "NO_COLOR",
    "PATH",
    "PKG_CONFIG_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "RUSTFLAGS",
    "SDKROOT",
    "TERM",
    "TMPDIR",
    "VIRTUAL_ENV",
)
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a canonical lowercase SHA-256")


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ValueError(f"{label} must be printable, non-empty, and <= 256 chars")


def _require_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc


def environment_sha256(environment: Mapping[str, str]) -> str:
    """Hash the selected child environment without persisting plaintext values."""

    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a string mapping")
    canonical: dict[str, str] = {}
    for key, value in environment.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
        ):
            raise ValueError("environment keys must be non-empty strings without '=' or NUL")
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("environment values must be strings without NUL")
        canonical[key] = value
    return _sha256_bytes(_ENVIRONMENT_DOMAIN + _canonical_bytes(canonical))


def _bounded_integer(
    value: int,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{label} must be between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class BuildExecutionPolicy:
    """Immutable physical subprocess policy whose identity is workload-bound.

    Only values that can change subprocess evidence belong here.  Admission,
    persistence, manifest, and scheduling knobs live in ``BuildAdmissionPolicy``
    so tuning a TTL or SQLite wait cannot manufacture a new physical effect id.
    """

    shell: str = "/bin/sh"
    output_tail_bytes: int = 65_536
    max_output_bytes: int = 16_777_216
    process_cleanup_grace_ms: int = 1_000
    stream_capture_strategy: str = SPLIT_STREAM_CAPTURE_STRATEGY

    def __post_init__(self) -> None:
        if not isinstance(self.shell, str) or not PurePath(self.shell).is_absolute():
            raise ValueError("shell must be an absolute path")
        if "\0" in self.shell:
            raise ValueError("shell cannot contain NUL")
        _bounded_integer(
            self.output_tail_bytes,
            "output_tail_bytes",
            minimum=1,
            maximum=1_048_576,
        )
        _bounded_integer(
            self.max_output_bytes,
            "max_output_bytes",
            minimum=1,
            maximum=1_073_741_824,
        )
        if self.output_tail_bytes > self.max_output_bytes:
            raise ValueError("output_tail_bytes cannot exceed max_output_bytes")
        _bounded_integer(
            self.process_cleanup_grace_ms,
            "process_cleanup_grace_ms",
            minimum=1,
            maximum=60_000,
        )
        if self.stream_capture_strategy != SPLIT_STREAM_CAPTURE_STRATEGY:
            raise ValueError("unsupported stream_capture_strategy")

    def to_dict(self) -> dict:
        return {
            "shell": self.shell,
            "output_tail_bytes": self.output_tail_bytes,
            "max_output_bytes": self.max_output_bytes,
            "process_cleanup_grace_ms": self.process_cleanup_grace_ms,
            "stream_capture_strategy": self.stream_capture_strategy,
        }

    @property
    def policy_sha256(self) -> str:
        return _sha256_bytes(
            _EXECUTION_POLICY_DOMAIN + _canonical_bytes(self.to_dict())
        )

    def reserved_compute_wall_ms(self, timeout_seconds: int) -> int:
        _bounded_integer(
            timeout_seconds,
            "timeout_seconds",
            minimum=1,
            maximum=604_800,
        )
        return timeout_seconds * 1_000 + self.process_cleanup_grace_ms

    def make_spec(
        self,
        *,
        command: str,
        cwd: str,
        timeout_seconds: int,
        environment_sha256: str,
        input_manifest_sha256: str,
        isolation_adapter: str,
        isolation_version: str,
        isolation_policy_sha256: str,
        adapter: str = LOCAL_BUILD_ADAPTER,
        adapter_version: str = LOCAL_BUILD_ADAPTER_VERSION,
    ) -> "BuildExecutionSpec":
        """Construct the only physical spec shape admitted by this policy."""

        return BuildExecutionSpec(
            command=command,
            cwd=cwd,
            shell=self.shell,
            timeout_seconds=timeout_seconds,
            environment_sha256=environment_sha256,
            input_manifest_sha256=input_manifest_sha256,
            isolation_adapter=isolation_adapter,
            isolation_version=isolation_version,
            isolation_policy_sha256=isolation_policy_sha256,
            adapter=adapter,
            adapter_version=adapter_version,
            execution_policy_sha256=self.policy_sha256,
            process_cleanup_grace_ms=self.process_cleanup_grace_ms,
            stream_capture_strategy=self.stream_capture_strategy,
            output_tail_bytes=self.output_tail_bytes,
            max_output_bytes=self.max_output_bytes,
        )


@dataclass(frozen=True, slots=True)
class BuildAdmissionPolicy:
    """Operational and input-shaping limits applied before effect admission.

    TTL and persistence tuning stay outside physical workload identity. Manifest
    and environment selection constrain inputs; the selected manifest and child
    environment cross ``BuildExecutionSpec`` through their content hashes.
    """

    maximum_timeout_seconds: int = 86_400
    minimum_grant_ttl_seconds: int = 300
    grant_ttl_slack_seconds: int = 60
    target_sqlite_timeout_ms: int = 10_000
    permit_ttl_seconds: int = 30
    environment_allowlist: tuple[str, ...] | None = None
    maximum_manifest_json_bytes: int = 8_388_608
    maximum_manifest_entries: int = 50_000
    maximum_input_file_bytes: int = 1_073_741_824
    maximum_input_bytes: int = 4_294_967_296

    def __post_init__(self) -> None:
        _bounded_integer(
            self.maximum_timeout_seconds,
            "maximum_timeout_seconds",
            minimum=1,
            maximum=604_800,
        )
        _bounded_integer(
            self.minimum_grant_ttl_seconds,
            "minimum_grant_ttl_seconds",
            minimum=1,
            maximum=1_209_600,
        )
        _bounded_integer(
            self.grant_ttl_slack_seconds,
            "grant_ttl_slack_seconds",
            minimum=0,
            maximum=604_800,
        )
        _bounded_integer(
            self.target_sqlite_timeout_ms,
            "target_sqlite_timeout_ms",
            minimum=1,
            maximum=300_000,
        )
        _bounded_integer(
            self.permit_ttl_seconds,
            "permit_ttl_seconds",
            minimum=1,
            maximum=300,
        )
        allowlist = self.environment_allowlist
        if allowlist is not None:
            if not isinstance(allowlist, tuple):
                raise ValueError("environment_allowlist must be a tuple or None")
            for key in allowlist:
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or "\0" in key
                ):
                    raise ValueError("environment_allowlist contains an invalid key")
            if tuple(sorted(set(allowlist))) != allowlist:
                raise ValueError("environment_allowlist must be sorted and unique")
        _bounded_integer(
            self.maximum_manifest_json_bytes,
            "maximum_manifest_json_bytes",
            minimum=128,
            maximum=67_108_864,
        )
        _bounded_integer(
            self.maximum_manifest_entries,
            "maximum_manifest_entries",
            minimum=1,
            maximum=1_000_000,
        )
        _bounded_integer(
            self.maximum_input_file_bytes,
            "maximum_input_file_bytes",
            minimum=1,
            maximum=1_099_511_627_776,
        )
        _bounded_integer(
            self.maximum_input_bytes,
            "maximum_input_bytes",
            minimum=1,
            maximum=17_592_186_044_416,
        )

    def to_dict(self) -> dict:
        return {
            "maximum_timeout_seconds": self.maximum_timeout_seconds,
            "minimum_grant_ttl_seconds": self.minimum_grant_ttl_seconds,
            "grant_ttl_slack_seconds": self.grant_ttl_slack_seconds,
            "target_sqlite_timeout_ms": self.target_sqlite_timeout_ms,
            "permit_ttl_seconds": self.permit_ttl_seconds,
            "environment_allowlist": self.environment_allowlist,
            "maximum_manifest_json_bytes": self.maximum_manifest_json_bytes,
            "maximum_manifest_entries": self.maximum_manifest_entries,
            "maximum_input_file_bytes": self.maximum_input_file_bytes,
            "maximum_input_bytes": self.maximum_input_bytes,
        }

    @property
    def policy_sha256(self) -> str:
        return _sha256_bytes(
            _ADMISSION_POLICY_DOMAIN + _canonical_bytes(self.to_dict())
        )

    def validate_timeout(self, timeout_seconds: int) -> int:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= self.maximum_timeout_seconds
        ):
            raise ValueError(
                "timeout_seconds must be positive and no greater than "
                f"maximum_timeout_seconds={self.maximum_timeout_seconds}"
            )
        return timeout_seconds

    def grant_ttl_seconds(
        self,
        timeout_seconds: int,
        *,
        cleanup_grace_ms: int,
    ) -> int:
        timeout = self.validate_timeout(timeout_seconds)
        _bounded_integer(
            cleanup_grace_ms,
            "cleanup_grace_ms",
            minimum=1,
            maximum=60_000,
        )
        cleanup_seconds = (cleanup_grace_ms + 999) // 1_000
        return max(
            self.minimum_grant_ttl_seconds,
            timeout + cleanup_seconds + self.grant_ttl_slack_seconds,
        )


DEFAULT_BUILD_EXECUTION_POLICY = BuildExecutionPolicy()
DEFAULT_BUILD_ADMISSION_POLICY = BuildAdmissionPolicy()


@dataclass(frozen=True, slots=True)
class BuildExecutionSpec:
    """Closed execution input for one provider-free shell build attempt."""

    command: str
    cwd: str
    shell: str
    timeout_seconds: int
    environment_sha256: str
    input_manifest_sha256: str
    isolation_adapter: str
    isolation_version: str
    isolation_policy_sha256: str
    execution_policy_sha256: str = DEFAULT_BUILD_EXECUTION_POLICY.policy_sha256
    process_cleanup_grace_ms: int = (
        DEFAULT_BUILD_EXECUTION_POLICY.process_cleanup_grace_ms
    )
    stream_capture_strategy: str = (
        DEFAULT_BUILD_EXECUTION_POLICY.stream_capture_strategy
    )
    output_tail_bytes: int = DEFAULT_BUILD_EXECUTION_POLICY.output_tail_bytes
    max_output_bytes: int = DEFAULT_BUILD_EXECUTION_POLICY.max_output_bytes
    provider_calls: str = "forbidden"
    schema_version: str = BUILD_EXECUTION_SCHEMA_VERSION
    adapter: str = LOCAL_BUILD_ADAPTER
    adapter_version: str = LOCAL_BUILD_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUILD_EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported build execution schema")
        if not isinstance(self.command, str) or not self.command or "\0" in self.command:
            raise ValueError("command must be a non-empty string without NUL")
        if len(self.command.encode("utf-8")) > 1_048_576:
            raise ValueError("command exceeds the 1 MiB build contract limit")
        for label, value in (("cwd", self.cwd), ("shell", self.shell)):
            if not isinstance(value, str) or not PurePath(value).is_absolute():
                raise ValueError(f"{label} must be an absolute path")
            if "\0" in value:
                raise ValueError(f"{label} cannot contain NUL")
        _bounded_integer(
            self.timeout_seconds,
            "timeout_seconds",
            minimum=1,
            maximum=604_800,
        )
        if (
            isinstance(self.output_tail_bytes, bool)
            or not isinstance(self.output_tail_bytes, int)
            or not 1 <= self.output_tail_bytes <= 1_048_576
        ):
            raise ValueError("output_tail_bytes must be between 1 and 1048576")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 1 <= self.max_output_bytes <= 1_073_741_824
        ):
            raise ValueError("max_output_bytes must be between 1 and 1073741824")
        if self.output_tail_bytes > self.max_output_bytes:
            raise ValueError("output_tail_bytes cannot exceed max_output_bytes")
        _require_sha256(self.environment_sha256, "environment_sha256")
        _require_sha256(self.input_manifest_sha256, "input_manifest_sha256")
        _require_identifier(self.isolation_adapter, "isolation_adapter")
        _require_identifier(self.isolation_version, "isolation_version")
        _require_sha256(self.isolation_policy_sha256, "isolation_policy_sha256")
        _require_sha256(self.execution_policy_sha256, "execution_policy_sha256")
        _bounded_integer(
            self.process_cleanup_grace_ms,
            "process_cleanup_grace_ms",
            minimum=1,
            maximum=60_000,
        )
        if self.stream_capture_strategy != SPLIT_STREAM_CAPTURE_STRATEGY:
            raise ValueError("unsupported stream_capture_strategy")
        _require_identifier(self.adapter, "adapter")
        _require_identifier(self.adapter_version, "adapter_version")
        if self.provider_calls != "forbidden":
            raise ValueError(
                "the v1 local build adapter only meters provider-free subprocesses"
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "command": self.command,
            "cwd": self.cwd,
            "shell": self.shell,
            "timeout_seconds": self.timeout_seconds,
            "environment_sha256": self.environment_sha256,
            "input_manifest_sha256": self.input_manifest_sha256,
            "isolation_adapter": self.isolation_adapter,
            "isolation_version": self.isolation_version,
            "isolation_policy_sha256": self.isolation_policy_sha256,
            "execution_policy_sha256": self.execution_policy_sha256,
            "process_cleanup_grace_ms": self.process_cleanup_grace_ms,
            "stream_capture_strategy": self.stream_capture_strategy,
            "output_tail_bytes": self.output_tail_bytes,
            "max_output_bytes": self.max_output_bytes,
            "provider_calls": self.provider_calls,
        }

    @property
    def workload_sha256(self) -> str:
        return _sha256_bytes(_WORKLOAD_DOMAIN + _canonical_bytes(self.to_dict()))


def reserved_compute_wall_ms(spec: BuildExecutionSpec) -> int:
    """Return the exact compute reservation bound carried by ``spec``."""

    if not isinstance(spec, BuildExecutionSpec):
        raise TypeError("reserved compute requires a BuildExecutionSpec")
    return (
        spec.timeout_seconds * 1_000
        + spec.process_cleanup_grace_ms
    )


def split_stream_budget(total_bytes: int) -> tuple[int, int]:
    """Deterministically split a no-borrow byte budget across stdout/stderr."""

    _bounded_integer(
        total_bytes,
        "total_bytes",
        minimum=0,
        maximum=1_073_741_824,
    )
    return ((total_bytes + 1) // 2, total_bytes // 2)


class BuildTerminalStatus(str, Enum):
    EXITED = "EXITED"
    TIMED_OUT = "TIMED_OUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    SPAWN_FAILED = "SPAWN_FAILED"
    INPUT_REJECTED = "INPUT_REJECTED"


@dataclass(frozen=True, slots=True)
class BuildExecutionResult:
    """Durable terminal subprocess evidence, independent of scientific success."""

    effect_id: str
    workload_sha256: str
    intent_sha256: str
    fence_token: int
    status: BuildTerminalStatus
    returncode: int | None
    started_at: str
    completed_at: str
    elapsed_monotonic_ns: int
    compute_wall_ms: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    output_tail: str
    schema_version: str = BUILD_EXECUTION_SCHEMA_VERSION
    measurement_method: str = "subprocess.monotonic_elapsed.ceil_ms/v1"

    def __post_init__(self) -> None:
        if self.schema_version not in {
            BUILD_EXECUTION_SCHEMA_VERSION,
            _LEGACY_BUILD_EXECUTION_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported build execution result schema")
        _require_identifier(self.effect_id, "effect_id")
        _require_sha256(self.workload_sha256, "workload_sha256")
        _require_sha256(self.intent_sha256, "intent_sha256")
        if (
            isinstance(self.fence_token, bool)
            or not isinstance(self.fence_token, int)
            or self.fence_token < 1
        ):
            raise ValueError("fence_token must be an integer >= 1")
        if not isinstance(self.status, BuildTerminalStatus):
            raise ValueError("status must be a BuildTerminalStatus")
        if (
            self.schema_version == _LEGACY_BUILD_EXECUTION_SCHEMA_VERSION
            and self.status is BuildTerminalStatus.INPUT_REJECTED
        ):
            raise ValueError("INPUT_REJECTED is available only in the v2 schema")
        if self.status in {
            BuildTerminalStatus.TIMED_OUT,
            BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED,
        }:
            if self.returncode is not None:
                raise ValueError(
                    "forced-stop result cannot claim a process return code"
                )
        elif isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise ValueError("exited/spawn-failed result requires an integer return code")
        started = _require_utc(self.started_at, "started_at")
        completed = _require_utc(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at cannot precede started_at")
        if (
            isinstance(self.elapsed_monotonic_ns, bool)
            or not isinstance(self.elapsed_monotonic_ns, int)
            or self.elapsed_monotonic_ns < 0
        ):
            raise ValueError("elapsed_monotonic_ns must be an integer >= 0")
        expected_ms = (self.elapsed_monotonic_ns + 999_999) // 1_000_000
        if self.compute_wall_ms != expected_ms:
            raise ValueError("compute_wall_ms must be monotonic elapsed time rounded up")
        for label, value in (
            ("stdout_bytes", self.stdout_bytes),
            ("stderr_bytes", self.stderr_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be an integer >= 0")
        _require_sha256(self.stdout_sha256, "stdout_sha256")
        _require_sha256(self.stderr_sha256, "stderr_sha256")
        if not isinstance(self.output_tail, str):
            raise ValueError("output_tail must be text")
        if len(self.output_tail.encode("utf-8")) > 1_048_576:
            raise ValueError("output_tail exceeds the v1 1 MiB evidence limit")
        _require_identifier(self.measurement_method, "measurement_method")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "fence_token": self.fence_token,
            "status": self.status.value,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_monotonic_ns": self.elapsed_monotonic_ns,
            "compute_wall_ms": self.compute_wall_ms,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "output_tail": self.output_tail,
            "measurement_method": self.measurement_method,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "BuildExecutionResult":
        expected = {
            "schema_version",
            "effect_id",
            "workload_sha256",
            "intent_sha256",
            "fence_token",
            "status",
            "returncode",
            "started_at",
            "completed_at",
            "elapsed_monotonic_ns",
            "compute_wall_ms",
            "stdout_sha256",
            "stderr_sha256",
            "stdout_bytes",
            "stderr_bytes",
            "output_tail",
            "measurement_method",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("build result fields diverged from the closed v1 schema")
        return cls(
            **{**value, "status": BuildTerminalStatus(value["status"])}
        )

    @property
    def evidence_sha256(self) -> str:
        return _sha256_bytes(_EVIDENCE_DOMAIN + _canonical_bytes(self.to_dict()))

    @property
    def usage(self) -> ResourceUsage:
        actual = ResourceVector(compute_wall_ms=self.compute_wall_ms)
        measurement = {
            "schema_version": self.schema_version,
            "measurement_method": self.measurement_method,
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "elapsed_monotonic_ns": self.elapsed_monotonic_ns,
            "actual": actual.to_dict(),
            "evidence_sha256": self.evidence_sha256,
        }
        return ResourceUsage(
            actual=actual,
            measured_at=self.completed_at,
            measurement_sha256=_sha256_bytes(
                _MEASUREMENT_DOMAIN + _canonical_bytes(measurement)
            ),
            evidence_sha256=self.evidence_sha256,
        )


@dataclass(frozen=True, slots=True)
class BuildRun:
    """Legacy-compatible build result plus operation-scoped resource evidence."""

    output: str
    returncode: int
    timed_out: bool
    effect_id: str
    workload_sha256: str
    intent_sha256: str
    dispatch_receipt_sha256: str
    evidence_sha256: str
    measurement_sha256: str
    settlement_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.output, str):
            raise ValueError("output must be text")
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise ValueError("returncode must be an integer")
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be boolean")
        _require_identifier(self.effect_id, "effect_id")
        for label, value in (
            ("workload_sha256", self.workload_sha256),
            ("intent_sha256", self.intent_sha256),
            ("dispatch_receipt_sha256", self.dispatch_receipt_sha256),
            ("evidence_sha256", self.evidence_sha256),
            ("measurement_sha256", self.measurement_sha256),
            ("settlement_receipt_sha256", self.settlement_receipt_sha256),
        ):
            _require_sha256(value, label)

    @property
    def resource_provenance(self) -> dict[str, str]:
        return {
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "dispatch_receipt_sha256": self.dispatch_receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "measurement_sha256": self.measurement_sha256,
            "settlement_receipt_sha256": self.settlement_receipt_sha256,
        }


class ResourceBuildError(RuntimeError):
    """Base class for typed failures at the resource-gated build boundary."""


class ResourceBuildConfigError(ResourceBuildError):
    """The opt-in build resource composition is incomplete or inconsistent."""


class ResourceBuildOutcomeUnknown(ResourceBuildError):
    """A durable claim exists but target completion cannot be proven."""


class ResourceBuildOverrun(ResourceBuildError):
    """Measured build use exceeded its reservation and froze the budget."""


__all__ = [
    "BUILD_EXECUTION_SCHEMA_VERSION",
    "BuildAdmissionPolicy",
    "BuildExecutionPolicy",
    "BuildExecutionResult",
    "BuildExecutionSpec",
    "BuildRun",
    "BuildTerminalStatus",
    "DEFAULT_BUILD_ADMISSION_POLICY",
    "DEFAULT_BUILD_EXECUTION_POLICY",
    "DEADLINE_BOUND_LOCAL_BUILD_ADAPTER_VERSION",
    "HARDENED_BUILD_ENVIRONMENT_ALLOWLIST",
    "LOCAL_BUILD_ADAPTER",
    "LOCAL_BUILD_ADAPTER_VERSION",
    "ResourceBuildConfigError",
    "ResourceBuildError",
    "ResourceBuildOutcomeUnknown",
    "ResourceBuildOverrun",
    "SPLIT_STREAM_CAPTURE_STRATEGY",
    "environment_sha256",
    "reserved_compute_wall_ms",
    "split_stream_budget",
]
