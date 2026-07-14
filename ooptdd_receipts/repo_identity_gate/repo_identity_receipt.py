"""OOPTDD receipt for the exact LakatoTree repository identity gate.

The adapter drives :mod:`server.version` against real temporary git repositories.
Its negative oracle ablates only the exact-root predicate and demonstrates that the
old parent-SHA theft immediately returns, so the receipt cannot be vacuously green.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

_LKT = Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

import server.version as version  # noqa: E402


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _init_repo(root: Path, *, marked: bool) -> str:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "receipt@example.invalid")
    _git(root, "config", "user.name", "Repo Identity Receipt")
    if marked:
        (root / "pyproject.toml").write_text(
            '[project]\nname = "lakatotree"\nversion = "0"\n', encoding="utf-8",
        )
        (root / "lakatos").mkdir()
        (root / "lakatos" / "__init__.py").write_text("", encoding="utf-8")
    else:
        (root / "README.md").write_text("# enclosing repository\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture")
    return _git(root, "rev-parse", "--short", "HEAD")


def _event(cid: str, name: str, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "server.version.repository_identity",
        "event": name,
        **attrs,
    }


def verify(backend, cid):
    with tempfile.TemporaryDirectory(prefix="lakatotree-repo-identity-") as tmp:
        tmp_root = Path(tmp)

        exact_repo = tmp_root / "lakatotree"
        exact_sha = _init_repo(exact_repo, marked=True)
        observed = version._git_head_sha(str(exact_repo))
        assert observed == exact_sha
        backend.ship([_event(cid, "exact_identity_accepted", sha=observed)])

        parent = tmp_root / "symposium"
        parent_sha = _init_repo(parent, marked=False)
        snapshot = parent / "GIT" / "delltower_import" / "lakatotree"
        snapshot.mkdir(parents=True)
        (snapshot / "pyproject.toml").write_text(
            '[project]\nname = "lakatotree"\nversion = "0"\n', encoding="utf-8",
        )
        (snapshot / "lakatos").mkdir()

        rejected = version._git_head_sha(str(snapshot))
        assert rejected == "unknown"
        backend.ship([_event(cid, "parent_identity_rejected", parent_sha=parent_sha)])

        old_boot = version.BOOT_GIT_SHA
        old_disk = version.disk_head_sha
        try:
            version.BOOT_GIT_SHA = "unknown"
            version.disk_head_sha = lambda: "unknown"
            status = version.served_version()
        finally:
            version.BOOT_GIT_SHA = old_boot
            version.disk_head_sha = old_disk
        assert status["identity_verified"] is False and status["stale"] is None
        backend.ship([_event(cid, "unknown_identity_abstains", stale=status["stale"])])

        exact_guard = version._exact_lakatotree_git_root
        try:
            version._exact_lakatotree_git_root = lambda _root: True
            stolen = version._git_head_sha(str(snapshot))
        finally:
            version._exact_lakatotree_git_root = exact_guard
        assert stolen == parent_sha, "guard ablation must reproduce the historical defect"
        assert version._git_head_sha(str(snapshot)) == "unknown"
        backend.ship([_event(cid, "identity_guard_ablation_detected", stolen_sha=stolen)])
