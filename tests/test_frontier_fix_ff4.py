"""FF4 guard (frontier-fix 2026-06-26, SECURITY): judge-script sha 재유도가 임의 절대파일을 읽지 않고
(ROOT/tempdir containment) 무제한 read 대신 streaming + size-cap 을 쓴다.

결함(deep-dive FF4): _recompute_script_sha 의 absolute 분기가 containment 없이 is_file() 만 보고
read_bytes() 전체를 메모리에 → script='/etc/passwd' 가 sha 오라클, 대용량 파일 RAM-exhaustion DoS
(LAKATOS_API_TOKEN 미설정 시 무인증 surface). relative traversal 거부와 *비대칭* 이었다.

두 가드 green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF4 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF4_script_sha_arbitrary_absolute_read
"""
from __future__ import annotations

import os
import tempfile

import server.file_hashing as fh
from server.contexts.tree.judgement_service import JudgementService


def _svc() -> JudgementService:
    return JudgementService(kg=lambda *a, **k: [], kg_tx=lambda *a, **k: [],
                            hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def test_absolute_script_path_outside_root_is_rejected():
    """음성 오라클: root/tempdir 밖 절대경로(시스템 파일)는 sha 재유도 거부 — 임의파일 읽기/sha 오라클 봉쇄."""
    svc = _svc()
    target = next((p for p in ("/etc/hostname", "/etc/passwd", "/etc/hosts") if os.path.exists(p)), None)
    assert target is not None, "테스트 환경에 시스템 파일 없음"
    sha, info = svc._recompute_script_sha(target)
    assert sha is None, f"out-of-root 절대경로가 해시됨(sha 오라클 잔존): {info}"
    assert info.get("reason") == "out_of_root", info


def test_script_sha_uses_streaming_capped_file_hash():
    """양성: 허용 루트(tempdir) 내 파일은 streaming file_sha 로 재유도 + size-cap 초과는 거부(무제한 read 아님)."""
    svc = _svc()
    # (1) 정상(작은) 파일 → 재유도 성공 + file_hashing.file_sha(streaming) 와 동일 해시
    with tempfile.NamedTemporaryFile("wb", suffix="_judge.py", delete=False) as f:
        f.write(b"print('measured: 0.4')\n")
        good = f.name
    try:
        sha, info = svc._recompute_script_sha(good)
        assert sha == fh.file_sha(good), info
        assert info.get("reason") == "file_content_sha", info
    finally:
        os.unlink(good)

    # (2) size-cap 초과 → 거부(전체를 메모리에 read 하지 않음 = RAM-DoS 차단)
    cap = svc._SCRIPT_MAX_BYTES
    with tempfile.NamedTemporaryFile("wb", suffix="_big.py", delete=False) as f:
        f.truncate(cap + 1)            # sparse: 디스크/메모리 안 채우고 크기만 cap 초과
        big = f.name
    try:
        sha2, info2 = svc._recompute_script_sha(big)
        assert sha2 is None and info2.get("reason") == "too_large", info2
    finally:
        os.unlink(big)


def test_command_like_oversized_script_is_rejected_without_oserror():
    """경로가 아닌 긴 명령 문자열은 ENAMETOOLONG 을 누출하지 않고 정직하게 미검증 처리한다."""
    command_like = "python -c '" + ("print(1);" * 64) + "'"

    sha, info = _svc()._recompute_script_sha(command_like)

    assert sha is None
    assert info.get("reason") in {"unresolvable", "not_a_file"}, info
