"""write-cert canonical blob — 독립 재구현 (심화 D3, substrate-B).

엔진 write_cert.canonical_cert_blob 과 *바이트 동일*(엔진-CI 골든이 대조). c1verify 가 lakatos import
없이 write-cert 서명을 재검증하기 위한 최소 재구현: 고정 명령 필드셋 + 버전드 헤더 + JCS.
# KG: q-extaudit-role-separation-20260722 (심화 D3)
"""
from __future__ import annotations

import json

CERT_HEADER = b"lakatos-write-cert\x00v1\n"
COMMAND_FIELDS = ("tree", "tag", "prev_receipt_sha", "metric_value", "script_sha", "verb")


class CertShapeError(ValueError):
    pass


def _jcs(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def canonical_cert_blob(command: dict, issued_at: str) -> bytes:
    """서명 대상 = 헤더 + JCS({command(고정 필드셋), issued_at}). 미지 필드 = 서명 범위 불명 = 에러."""
    if not isinstance(command, dict):
        raise CertShapeError("command 비객체")
    unknown = set(command) - set(COMMAND_FIELDS)
    if unknown:
        raise CertShapeError(f"command 미지 필드 {sorted(unknown)} (서명 범위 밖)")
    body = {k: command.get(k) for k in COMMAND_FIELDS}
    return CERT_HEADER + _jcs({"command": body, "issued_at": issued_at})
