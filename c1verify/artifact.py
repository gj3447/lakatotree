"""Content identity for the standalone two-ended temporal verifier artifact."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import sys

if __package__:  # Installed package and isolated direct execution.
    from .jcs import jcs
else:  # pragma: no cover - exercised by subprocess integration tests
    from jcs import jcs


TEMPORAL_ARTIFACT_SCHEMA = "lakatotree-c1-temporal-verifier-artifact/v1"
TEMPORAL_ARTIFACT_DOMAIN = b"lakatotree-c1-temporal-verifier-artifact/v1\0"
TEMPORAL_ARTIFACT_FILES = (
    "_ed25519.py",
    "artifact.py",
    "jcs.py",
    "receipts.py",
    "temporal_cli.py",
    "temporal_sidecar.py",
)
_LOCAL_MODULES = frozenset(
    Path(name).stem for name in TEMPORAL_ARTIFACT_FILES
)
_ALLOWED_IMPORTS = frozenset(sys.stdlib_module_names) | {"__future__"} | _LOCAL_MODULES


def _validate_import_closure(raw: bytes, *, relative: str) -> None:
    try:
        tree = ast.parse(raw, filename=relative)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"temporal verifier source is invalid: {relative}") from exc
    for node in ast.walk(tree):
        names: tuple[str, ...] = ()
        if isinstance(node, ast.Import):
            names = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (node.module or "",)
        for name in names:
            root = name.split(".", 1)[0]
            if root and root not in _ALLOWED_IMPORTS:
                raise ValueError(
                    f"temporal verifier import escapes pinned closure: {relative}:{root}"
                )


def temporal_artifact_manifest(root: Path | None = None) -> dict:
    base = (root or Path(__file__).resolve().parent).resolve()
    files = []
    for relative in TEMPORAL_ARTIFACT_FILES:
        raw = (base / relative).read_bytes()
        _validate_import_closure(raw, relative=relative)
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    return {
        "schema_version": TEMPORAL_ARTIFACT_SCHEMA,
        "files": files,
    }


def temporal_artifact_sha256(root: Path | None = None) -> str:
    return hashlib.sha256(
        TEMPORAL_ARTIFACT_DOMAIN + jcs(temporal_artifact_manifest(root))
    ).hexdigest()


__all__ = [
    "TEMPORAL_ARTIFACT_FILES",
    "TEMPORAL_ARTIFACT_SCHEMA",
    "temporal_artifact_manifest",
    "temporal_artifact_sha256",
]
