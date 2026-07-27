"""ots_daily_anchor 단위 테스트 — 네트워크·KG 없이 순수 로직만 (L2 앵커링, PROM16 Phase1).

실 캘린더 왕복은 라이브 프로브(scripts/probe_temporal_witness_live.py 패턴)의 몫이고,
여기서는 ① root 다이제스트 결정론 ② .ots 조립 포맷 ③ pending→confirmed upgrade 상태기계
④ 캘린더 부분 실패 정족 을 고정한다.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ots_daily_anchor as oda  # noqa: E402


class _Resp:
    def __init__(self, body: bytes):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ots_magic_matches_reference_client():
    """정본 opentimestamps DetachedTimestampFile.HEADER_MAGIC (31B, 8B suffix 포함).
    구판 24B magic 은 표준 `ots` 클라이언트가 파싱을 거부했다 (finding_c15adc24d551e4fe)."""
    assert oda.OTS_MAGIC == (b"\x00OpenTimestamps\x00\x00Proof\x00"
                            b"\xbf\x89\xe2\xe8\x84\xe8\x92\x94")
    assert len(oda.OTS_MAGIC) == 31


def test_assemble_ots_file_format():
    digest = bytes.fromhex("ab" * 32)
    ts = b"\x00\xffserialized-timestamp"
    out = oda.assemble_ots_file(digest, ts)
    assert out.startswith(oda.OTS_MAGIC)
    assert out[len(oda.OTS_MAGIC)] == oda.OTS_VERSION          # varuint(1) == 0x01
    assert out[len(oda.OTS_MAGIC) + 1] == oda.OP_SHA256_TAG    # file_hash_op 태그 필수
    assert out[len(oda.OTS_MAGIC) + 2: len(oda.OTS_MAGIC) + 34] == digest
    assert out.endswith(ts)
    with pytest.raises(ValueError):
        oda.assemble_ots_file(b"\x00" * 16, ts)   # 32B 아닌 digest 는 거부


# ── serialized Timestamp 파서 — 합성 캘린더 응답으로 문법·commitment 고정 ────────────

def _varbytes(b: bytes) -> bytes:
    assert len(b) < 0x80
    return bytes([len(b)]) + b


def _pending_chain(digest: bytes, nonce: bytes, url: bytes = b"https://cal.example"):
    """실 캘린더 stamp 응답 형태: OpAppend(nonce) → OpSHA256 → PendingAttestation(url).
    반환 (ts_bytes, commitment)."""
    import hashlib
    commitment = hashlib.sha256(digest + nonce).digest()
    ts = (b"\xf0" + _varbytes(nonce)          # OpAppend + operand
          + b"\x08"                            # OpSHA256
          + b"\x00" + oda._ATT_PENDING + _varbytes(_varbytes(url)))
    return ts, commitment


def _bitcoin_leaf(height: int = 810000) -> bytes:
    """upgrade 응답 형태: 그 지점 msg 기준 BitcoinBlockHeaderAttestation 단일 엔트리."""
    payload = bytearray()
    v = height
    while True:
        b = v & 0x7F
        v >>= 7
        payload.append(b | (0x80 if v else 0))
        if not v:
            break
    return b"\x00" + oda._ATT_BITCOIN + _varbytes(bytes(payload))


def test_parse_attestations_commitment_and_tags():
    digest = bytes.fromhex("ab" * 32)
    nonce = bytes.fromhex("0748eee53a9a2e57")
    ts, commitment = _pending_chain(digest, nonce)
    atts = oda.parse_attestations(ts, digest)
    assert len(atts) == 1
    assert atts[0]["tag"] == oda._ATT_PENDING
    assert atts[0]["msg"] == commitment, "commitment = sha256(digest+nonce) — 원 digest 아님"
    # 잔여 바이트가 있으면 fail-loud
    with pytest.raises(ValueError):
        oda.parse_attestations(ts + b"\x00", digest)


def test_varuint_roundtrip_multibyte():
    buf = b"\x90\xb8\x31"          # varuint(810000) = 0x90 0xb8 0x31
    val, pos = oda._read_varuint(buf, 0)
    assert (val, pos) == (810000, 3)
    assert oda.bitcoin_block_height(buf) == 810000


def test_compute_receipt_root_deterministic_and_sorted(monkeypatch):
    calls = []

    class P:
        returncode = 0
        stderr = ""
        stdout = 'sha\n"bb%064d"\n"aa%064d"\n"bb%064d"\n' % (1, 2, 1)  # 중복+역순

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return P()

    monkeypatch.setattr(oda.subprocess, "run", fake_run)
    r1 = oda.compute_receipt_root("cypher-shell", "bolt://x", "u", "p")
    r2 = oda.compute_receipt_root("cypher-shell", "bolt://x", "u", "p")
    assert r1["root_digest"] == r2["root_digest"], "같은 집합은 같은 root (결정론)"
    assert r1["receipt_count"] == 2, "중복 제거 후 계수"
    assert calls[0][:4] == ["cypher-shell", "-a", "bolt://x", "-u"]


def test_compute_receipt_root_fails_loud_on_cypher_error(monkeypatch):
    class P:
        returncode = 3
        stderr = "connection refused"
        stdout = ""

    monkeypatch.setattr(oda.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(RuntimeError, match="cypher-shell"):
        oda.compute_receipt_root("cypher-shell", "bolt://x", "u", "p")


def _fake_stamp(urls_bodies):
    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        for base, body in urls_bodies.items():
            if url.startswith(base):
                return _Resp(body)
        raise OSError(f"unknown calendar {url}")
    return fake_urlopen


def test_run_daily_stamps_two_pools_and_writes_outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(oda, "compute_receipt_root",
                        lambda *a, **k: {"root_digest": "cd" * 32, "receipt_count": 7,
                                         "computed_at": "2026-07-24T00:00:00+00:00"})
    monkeypatch.setattr(oda.urllib.request, "urlopen",
                        _fake_stamp({"https://a.pool.opentimestamps.org": b"ts-a",
                                     "https://b.pool.opentimestamps.org": b"ts-b"}))
    entry = oda.run_daily(cypher_shell="x", uri="u", user="n", password="p",
                          outbox=tmp_path, calendars=oda._DEFAULT_CALENDARS)
    assert entry["status"] == "pending"
    assert set(entry["calendars"]) == {"a.pool", "b.pool"}
    # .ots 사이드카가 포맷대로 쓰였다
    ots_a = (tmp_path / entry["calendars"]["a.pool"]["ots_file"]).read_bytes()
    assert ots_a.startswith(oda.OTS_MAGIC) and ots_a.endswith(b"ts-a")
    on_disk = json.loads((tmp_path / f"{entry['date']}.json").read_text())
    assert on_disk["root_digest"] == "cd" * 32


def test_run_daily_partial_pool_failure_still_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(oda, "compute_receipt_root",
                        lambda *a, **k: {"root_digest": "cd" * 32, "receipt_count": 1,
                                         "computed_at": "t"})
    monkeypatch.setattr(oda.urllib.request, "urlopen",
                        _fake_stamp({"https://a.pool.opentimestamps.org": b"ts-a"}))
    entry = oda.run_daily(cypher_shell="x", uri="u", user="n", password="p",
                          outbox=tmp_path, calendars=oda._DEFAULT_CALENDARS)
    assert entry["status"] == "pending", "1/2 풀 성공이면 pending (정족은 독립 파일이라 손실 없음)"
    assert entry["calendars"]["b.pool"]["status"] == "error"


def _pending_entry(tmp_path, digest_hex: str, ts_bytes: bytes):
    entry = {"date": "2026-07-23", "root_digest": digest_hex, "receipt_count": 3,
             "status": "pending",
             "calendars": {"a.pool": {"status": "pending", "ots_file": "x.ots",
                                      "attestation_b64": base64.b64encode(ts_bytes).decode()}}}
    (tmp_path / "2026-07-23.json").write_text(json.dumps(entry))
    return entry


def test_upgrade_queries_commitment_and_confirms_on_bitcoin_attestation(tmp_path, monkeypatch):
    digest_hex = "ef" * 32
    digest = bytes.fromhex(digest_hex)
    ts, commitment = _pending_chain(digest, b"\x01\x02\x03\x04\x05\x06\x07\x08")
    _pending_entry(tmp_path, digest_hex, ts)
    btc_resp = _bitcoin_leaf(810000)
    urls = {"https://a.pool.opentimestamps.org/timestamp/" + commitment.hex(): btc_resp}
    monkeypatch.setattr(oda.urllib.request, "urlopen", _fake_stamp(urls))
    confirmed = oda.upgrade_pending(outbox=tmp_path, calendars=("https://a.pool.opentimestamps.org",))
    assert confirmed == [("2026-07-23", "a.pool")]
    after = json.loads((tmp_path / "2026-07-23.json").read_text())
    info = after["calendars"]["a.pool"]
    assert after["status"] == "confirmed" and info["status"] == "confirmed"
    assert info["commitment"] == commitment.hex(), "질의 키 = commitment (원 digest 였다면 404)"
    assert info["bitcoin_block_height"] == 810000
    # spliced .ots: pending 엔트리가 비트코인 attestation 으로 치환된 정본 파일
    ots = (tmp_path / info["ots_file"]).read_bytes()
    assert ots.startswith(oda.OTS_MAGIC) and oda._ATT_BITCOIN in ots
    spliced_ts = base64.b64decode(info["attestation_b64"])
    atts = oda.parse_attestations(spliced_ts, digest)
    assert [a["tag"] for a in atts] == [oda._ATT_BITCOIN], "splice 후 파서 재검증 통과"


def test_upgrade_not_confirmed_by_mere_byte_change(tmp_path, monkeypatch):
    """음성 오라클(구판 결함 재발 방지): 바이트가 달라져도 비트코인 attestation 이 없으면
    (pending 갱신 응답) 확정 선언 금지 — 구판 바이트-diff 휴리스틱은 여기서 거짓 확정을 찍었다."""
    digest_hex = "ef" * 32
    digest = bytes.fromhex(digest_hex)
    ts, commitment = _pending_chain(digest, b"\x01\x02\x03\x04\x05\x06\x07\x08")
    _pending_entry(tmp_path, digest_hex, ts)
    still_pending = b"\x00" + oda._ATT_PENDING + _varbytes(_varbytes(b"https://other.example"))
    urls = {"https://a.pool.opentimestamps.org/timestamp/" + commitment.hex(): still_pending}
    monkeypatch.setattr(oda.urllib.request, "urlopen", _fake_stamp(urls))
    confirmed = oda.upgrade_pending(outbox=tmp_path, calendars=("https://a.pool.opentimestamps.org",))
    assert confirmed == [], "바이트 변화 != 확정 — attestation 태그만이 증거"
    after = json.loads((tmp_path / "2026-07-23.json").read_text())
    assert after["status"] == "pending"


def test_upgrade_stays_pending_on_404(tmp_path, monkeypatch):
    digest_hex = "ef" * 32
    ts, _ = _pending_chain(bytes.fromhex(digest_hex), b"\x01\x02\x03\x04\x05\x06\x07\x08")
    _pending_entry(tmp_path, digest_hex, ts)
    monkeypatch.setattr(oda.urllib.request, "urlopen", _fake_stamp({}))   # 전부 미지 URL → OSError
    confirmed = oda.upgrade_pending(outbox=tmp_path, calendars=("https://a.pool.opentimestamps.org",))
    assert confirmed == []
    after = json.loads((tmp_path / "2026-07-23.json").read_text())
    assert after["status"] == "pending"


def test_reassemble_sidecars_recovers_old_format(tmp_path):
    """구판(24B magic) 사이드카를 attestation_b64 보존분으로 정본 포맷 재조립 — 소급 회수."""
    digest_hex = "ef" * 32
    ts, _ = _pending_chain(bytes.fromhex(digest_hex), b"\x01\x02\x03\x04\x05\x06\x07\x08")
    entry = _pending_entry(tmp_path, digest_hex, ts)
    old_format = b"\x00OpenTimestamps\x00\x00Proof\x00\x00" + b"\x01" + bytes.fromhex(digest_hex) + ts
    (tmp_path / "x.ots").write_bytes(old_format)
    fixed = oda.reassemble_sidecars(outbox=tmp_path)
    assert fixed == ["x.ots"]
    new_bytes = (tmp_path / "x.ots").read_bytes()
    assert new_bytes.startswith(oda.OTS_MAGIC)
    assert new_bytes[len(oda.OTS_MAGIC) + 1] == oda.OP_SHA256_TAG
    assert oda.reassemble_sidecars(outbox=tmp_path) == [], "멱등 — 이미 정본이면 무변경"
    del entry


def test_pool_name_parsing():
    assert oda._pool_name("https://a.pool.opentimestamps.org") == "a.pool"
    assert oda._pool_name("https://b.pool.opentimestamps.org") == "b.pool"
