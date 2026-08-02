"""Bounded canonical-JSON CLI for the standalone two-ended verifier."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sys

if __package__ in {None, ""}:  # ``-I`` removes the script directory from sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:  # Installed entry point and isolated direct execution.
    from .artifact import temporal_artifact_sha256
    from .jcs import jcs
    from .temporal_sidecar import (
        BATCH_REPORT_SCHEMA,
        MAX_INPUT_BYTES,
        TemporalSidecarError,
        verify_batch_bytes,
    )
else:  # pragma: no cover - exercised by subprocess integration tests
    from artifact import temporal_artifact_sha256
    from jcs import jcs
    from temporal_sidecar import (
        BATCH_REPORT_SCHEMA,
        MAX_INPUT_BYTES,
        TemporalSidecarError,
        verify_batch_bytes,
    )


def _python_sha256() -> str:
    return hashlib.sha256(Path(sys.executable).resolve(strict=True).read_bytes()).hexdigest()


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    input_sha = hashlib.sha256(raw).hexdigest()
    try:
        artifact_sha = temporal_artifact_sha256(Path(__file__).resolve().parent)
        python_sha = _python_sha256()
        report = verify_batch_bytes(
            raw,
            actual_verifier_artifact_sha256=artifact_sha,
            actual_verifier_python_sha256=python_sha,
            evaluated_at=datetime.now(timezone.utc),
        )
        report = {**report, "input_sha256": input_sha}
        code = 0 if report["status"] == "VERIFIED" else 1
    except (TemporalSidecarError, OSError, ValueError) as exc:
        report = {
            "schema_version": BATCH_REPORT_SCHEMA,
            "status": "ERROR",
            "input_sha256": input_sha,
            "reason_code": str(exc),
        }
        code = 2
    sys.stdout.buffer.write(jcs(report) + b"\n")
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":  # pragma: no cover - CLI path
    raise SystemExit(main())
