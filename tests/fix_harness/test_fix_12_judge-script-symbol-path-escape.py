"""FIX-HARNESS #12 (P2 security): judge-script SHA 재유도의 'file::symbol' 분기가 FF4 경로격리를
우회한다 — 무인증 임의 .py 읽기 오라클 + RAM-DoS.

finding id: #12
locations:
  - server/contexts/tree/judgement_service.py:171-179 ('::' 분기 — file_part 를 격리/size-cap 없이
    longinus.symbol_body_sha 로 직행)
  - 대칭 PLAIN 분기 :180-206 은 FF4 로 _allowed_script_roots() containment + _SCRIPT_MAX_BYTES stat
    체크가 걸려있음 (대조군이 이를 입증).
  - lakatos/longinus.py:28-46(_resolve), :105-124(symbol_body_sha): _resolve 가 `root / file` 를 하는데
    file 이 절대경로면 `ROOT / "/abs/path"` == "/abs/path" 라 root 가 무시됨(격리 부재).

bug: PLAIN form '/dev/shm/.../secret.py' 는 out_of_root 로 거부되지만, 'file::SYMBOL' form
  '/dev/shm/.../secret.py::API_KEY' 는 격리/size-cap 어느 것도 거치지 않고 실제 본문 sha 를 반환한다.
  → 무인증 호출자(LAKATOS_API_TOKEN 미설정)가 허용 루트 밖 임의 .py 의 내용/존재를 sha 로 탐침,
  대용량 파일로 RAM-exhaustion DoS 가능.

fix: judgement_service.py 의 '::' 분기에서 longinus 호출 *전에* PLAIN 분기와 동일하게 file_part 를
  resolve+격리(out_of_root 거부, is_file(), _SCRIPT_MAX_BYTES 강제)하거나, longinus._resolve 가
  절대/'..' 경로를 거부하고 root/file 를 root 하위로 confine(resolve()+parents 체크)하도록 한다.

xfail(strict) until fixed: post-fix 계약(SYMBOL form 도 out_of_root 거부 = sha None)을 인코딩하므로
  오늘은 sha 가 반환되어 FAIL(=버그 존재), 수정 착륙 시 PASS → strict xfail 이 trips.
"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from server.contexts.tree.judgement_service import JudgementService, _allowed_script_roots


def _svc() -> JudgementService:
    return JudgementService(kg=lambda *a, **k: [], kg_tx=lambda *a, **k: [],
                            hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


@pytest.fixture
def secret_outside_roots(monkeypatch):
    """허용 루트(ROOT + OS tempdir + env) 밖의 실제 .py 파일을 만든다.
    tempdir(/tmp)은 _allowed_script_roots() 에 포함되므로 사용 불가 → /dev/shm 사용."""
    monkeypatch.delenv("LAKATOS_SCRIPT_ROOTS", raising=False)  # env 로 /dev/shm 이 허용되지 않게
    base = Path("/dev/shm")
    if not (base.exists() and os.access(base, os.W_OK)):
        pytest.skip("/dev/shm 미존재/비쓰기 — out-of-root 실파일 생성 불가")
    d = base / f"poc_lkt_{uuid.uuid4().hex}"
    d.mkdir()
    secret = d / "secret.py"
    secret.write_text('API_KEY = "s3cr3t-value"\n', encoding="utf-8")
    # 방어: 이 경로가 정말 허용 루트 밖인지 사전 확정(대조군이 의미 있도록)
    resolved = secret.resolve()
    assert not any(r == resolved or r in resolved.parents for r in _allowed_script_roots()), \
        "전제 위반: secret 이 허용 루트 안에 있음 — 격리 우회를 검증할 수 없음"
    try:
        yield secret
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_plain_out_of_root_absolute_is_rejected(secret_outside_roots):
    """대조군(이미 green): PLAIN 절대경로 form 은 FF4 격리로 out_of_root 거부 — sha 오라클 없음."""
    svc = _svc()
    sha, info = svc._recompute_script_sha(str(secret_outside_roots))
    assert sha is None, f"PLAIN 분기가 out-of-root 파일을 해시함: {info}"
    assert info.get("reason") == "out_of_root", info


# [FIXED 2026-06-27] #12 — green regression (judgement_service._isolate_script_file shared by both branches)
def test_symbol_form_out_of_root_must_also_be_rejected(secret_outside_roots):
    """음성 오라클(post-fix 계약): 'file::SYMBOL' form 도 PLAIN 과 *대칭*으로 out-of-root 거부해야 한다.

    오늘(버그): '::' 분기가 file_part 를 longinus.symbol_body_sha 로 직행 → 격리 없이 실제 본문 sha 반환.
    수정 후: sha is None (격리/거부). 따라서 이 단언은 오늘 FAIL(sha 반환) → xfail(strict).
    """
    svc = _svc()
    symbol_script = f"{secret_outside_roots}::API_KEY"
    sha, info = svc._recompute_script_sha(symbol_script)
    # 핵심 계약: 허용 루트 밖 파일은 SYMBOL form 으로도 내용/존재를 누설하면 안 된다(sha None).
    assert sha is None, (
        f"'::' 분기가 허용 루트 밖 파일을 해시함(격리 우회, 임의파일 sha 오라클 잔존): "
        f"sha={sha!r} info={info!r}"
    )
