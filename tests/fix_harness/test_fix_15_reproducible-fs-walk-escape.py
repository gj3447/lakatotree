"""FIX-HARNESS #15 (P2 security) — unbounded / arbitrary-path filesystem walk via
agent-controlled lineage 'source' paths (DoS + content read).

Finding id: 15
Locations:
  - server/file_hashing.py:18  (path_sha → imported into server.app as _path_sha)
      os.walk()/hash a path with NO allowlist / base-dir confinement.
  - server/app.py:414-416  (_reproducible_for_node)
      for every derivation 'output' declared with kind='source' (agent-controlled, linked
      to a node's result_path) the server calls _path_sha(src) and walks+hashes it.

The bug:
  A derivation whose `output` is an absolute path OUTSIDE any legitimate artifact/raw
  root (e.g. '/', '/proc', a huge mount, or — here — a tmp dir we control) can be
  declared with kind='source' and wired to a node's result_path. When the server
  evaluates reproducibility (_reproducible_for_node, reachable from set_verdict /
  certificate / claim_standing), it recursively walks+hashes that arbitrary path on
  the request thread → unauthenticated hang/DoS + content read of out-of-root files.
  There is no confinement: path_sha hashes whatever absolute path it is handed.

The exact fix:
  Confine source paths to a configured artifact/raw root: reject paths where
  os.path.realpath(src) does not start with the configured base (reject absolute /
  out-of-root paths) BEFORE any os.walk/open, and cap walk size/time. An out-of-root
  path must be REFUSED — never opened, never walked, never hashed.

Correct post-fix behavior encoded below:
  An out-of-root path handed to path_sha (and, end-to-end, to _reproducible_for_node)
  is rejected — its files are NEVER read/hashed. We assert the confinement decision by
  proving the marker file inside the out-of-root dir is never passed to file_sha. We
  deliberately use a tmp dir OUTSIDE the repo (NOT '/') so the test stays fast/safe.

xfail(strict) until fixed: today the path is walked+hashed (assertion fails = bug
present); once confinement lands the path is refused and the assertion passes →
strict xfail trips.
"""
from __future__ import annotations

import importlib
import os
import tempfile

import pytest

from server import file_hashing


def _make_out_of_root_dir() -> tuple[str, str]:
    """리포지토리/아티팩트 루트 밖이 *확실한* tmp 디렉토리를 만들고 마커 파일 1개를 넣는다.

    시스템 temp(/tmp/...) 는 repo 와 어떤 raw-root 와도 무관 → 어떤 합리적 confinement 에서도
    out-of-root. '/' 를 쓰지 않으므로 테스트는 빠르고 안전하다.
    """
    d = tempfile.mkdtemp(prefix="fixh15_out_of_root_")
    marker = os.path.join(d, "secret_outside_artifact_root.txt")
    with open(marker, "wb") as f:
        f.write(b"content the server must NOT be allowed to read/hash\n")
    return d, marker


def _spy_file_sha(monkeypatch) -> list[str]:
    """file_hashing.file_sha 호출 경로를 기록(원본은 그대로 위임). path_sha 가 디렉토리를
    walk 하면 내부 파일마다 file_sha(fp) 를 부르므로, 마커 경로의 출현 = '실제로 walk/hash 했다'."""
    seen: list[str] = []
    real = file_hashing.file_sha

    def _wrapped(path, *a, **k):
        seen.append(os.path.realpath(path))
        return real(path, *a, **k)

    monkeypatch.setattr(file_hashing, "file_sha", _wrapped)
    return seen


# [FIXED 2026-06-27] #15 — green regression (server/file_hashing.path_sha confines to raw_root(); LAKATOS_RAW_ROOT)
def test_path_sha_refuses_out_of_root_directory(monkeypatch):
    """직접(단위) — 실제 path_sha 를 out-of-root 디렉토리로 호출. 포스트-픽스 계약:
    confinement 결정으로 *거부* → 내부 마커 파일은 절대 읽히지/해시되지 않는다."""
    out_dir, marker = _make_out_of_root_dir()
    real_marker = os.path.realpath(marker)
    hashed = _spy_file_sha(monkeypatch)

    # 실제 코드 경로: server.file_hashing.path_sha (= app._path_sha)
    file_hashing.path_sha(out_dir)

    # 포스트-픽스: out-of-root 는 거부 → 마커는 한 번도 해시되지 않아야 한다(= walk 안 함).
    # 오늘(버그): path_sha 가 디렉토리를 walk 하며 마커를 해시 → 이 단언이 깨진다.
    assert real_marker not in hashed, (
        "out-of-root path was walked/hashed (DoS + content read): "
        f"{real_marker} read by server path_sha"
    )


# [FIXED 2026-06-27] #15 — green regression (path_sha refuses out-of-root source; _reproducible_for_node won't walk it)
def test_reproducible_for_node_does_not_walk_out_of_root_source(monkeypatch):
    """엔드투엔드(실제 호출 형태) — set_verdict/certificate 가 거치는 _reproducible_for_node.
    에이전트가 node.result_path 를 out-of-root 절대경로로, 그걸 kind='source' 계보로 자기선언.
    포스트-픽스: 서버는 그 경로를 *재계산하려고 walk 하지 않는다*(confinement 으로 거부)."""
    from lakatos.io.lineage import Derivation

    out_dir, marker = _make_out_of_root_dir()
    real_marker = os.path.realpath(marker)

    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    app = importlib.import_module("server.app")

    # 노드 result_path = 에이전트가 가리키는 out-of-root 경로. (kg/계보만 모킹; _path_sha 는 *실제*.)
    monkeypatch.setattr(app, "kg", lambda q, **p: [{"rp": out_dir}])
    monkeypatch.setattr(
        app,
        "_load_lineage",
        lambda: [
            Derivation(
                output=out_dir, output_sha="agent-declared-sha",
                producer="", producer_sha="", inputs=[], kind="source",
            )
        ],
    )

    hashed = _spy_file_sha(monkeypatch)

    # 실제 코드 경로 실행: roots ⊆ declared 통과 → 루프에서 _path_sha(out_dir) 호출.
    app._reproducible_for_node("tree", "n1")

    # 포스트-픽스: out-of-root source 는 거부 → 서버가 그 임의 경로를 walk/read 하지 않는다.
    # 오늘(버그): _path_sha(out_dir) 가 walk 하며 마커를 해시 → 단언 실패 = DoS/content-read 재현.
    assert real_marker not in hashed, (
        "server walked an agent-declared out-of-root source path while evaluating "
        f"reproducibility (DoS + content read): {real_marker}"
    )
