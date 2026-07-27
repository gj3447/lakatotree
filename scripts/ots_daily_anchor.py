#!/usr/bin/env python3
"""ots_daily_anchor — 영수증 체인 root 의 OpenTimestamps 일일 앵커링 (PROM 16 Phase 1, L2).

급소: 409 락은 DB 날부 순서만 보장 — 결과를 먼저 보고 '예측'을 나중에 등록해도(백데이트)
막을 수 없다. L2 = 매일 KG 의 전체 VerdictReceipt sha 집합을 하나의 root 다이제스트로 묶어
비트코인 블록체인에 외부 타임스탬프를 박는다. 이후 "이 영수증은 어제 있었다"는 주장은
어제의 앵커와 모순되어 *과거 시점 위조(백데이트)* 가 봉쇄된다.

★증명 범위 경계(2026-07-28 정정): 앵커가 증명하는 것은 존재-이전(existence-before-T)뿐이다.
등록자가 T1 에 결과를 몰랐다는 것(outcome ignorance)은 증명하지 않는다 — 결정론적 측정은
T0(<T1) 사적 사전실행으로 결과를 알고 나서 '예측'을 정직하게 앵커할 수 있다. 그 층은
별도 메커니즘(randomness beacon 등, seed-lktadv-outcome-ignorance-basis-20260728)의 몫.

설계 결정:
  - **stdlib only** (q_signer_key_substrate: 서명/증인 경로 외부의존 0). OTS 캘린더 API 는
    순수 HTTPS POST/GET 이라 외부 패키지 없이 구현. opentimestamps-client 는 *검증*에만 필요
    (`ots verify`), 일일 앵커링 자체에는 불필요.
  - **root = 전체 receipt_sha 집합의 sha256** (canonical JSON lines 정렬). 어느 receipt 하나라도
    소급 변경/삭제되면 root 가 달라져 직전 앵커와 모순. 체인 링크(prev_receipt_sha)와 독립적으로
    "이 집합이 이 날짜에 존재"를 증명한다(백데이트 방어의 핵).
  - **캘린더 2-풀 정족** (a.pool + b.pool) — 풀 하나가 죽거나 악의적이어도 다른 쪽이 독립 증인.
    풀별 독립 .ots 파일 (하나의 타임스탬프에 병합하지 않음 — 독립 검증이 더 강한 정족).
  - **pending → confirmed 2단** (EXTAUDIT S8 OTS 강화): stamp 직후는 캘린더 서명(pending)뿐,
    비트코인 블록 확정(수 시간) 후 GET /timestamp/{digest} 로 upgrade. 일일 실행이 어제의
    pending 을 자동 upgrade 한다(outbox+크론 패턴).
  - 앵커는 봉인 sha 밖 **사이드카** (docs/data/ots_anchors/) — KG 를 건드리지 않아 순환 회피,
    기존 receipt/verdict 에 소급 강등 0.

★정직 경계(temporal.py 와 동일): 솔로 box 에서 이 앵커가 증명하는 것은 "이 다이제스트가 이
시점에 존재했다"뿐 — 다이제스트의 *내용*이 올바르다는 것은 증명하지 않는다(쓰레기를 앵커하면
쓰레기가 타임스탬프된다). 내용의 정합은 replay(L3)와 fsck 의 몫.

사용:
  python scripts/ots_daily_anchor.py              # 오늘 root 계산→stamp + 어제 pending upgrade
  python scripts/ots_daily_anchor.py --digest-only # 네트워크 없이 root 만 계산(테스트/점검)
  python scripts/ots_daily_anchor.py --upgrade-all # 모든 pending 재시도

크론(미설치 — 설치는 사용자 결정):
  17 3 * * * cd <repo> && .venv/bin/python scripts/ots_daily_anchor.py >> docs/data/ots_anchors/cron.log 2>&1
launchd 는 bin/com.symposium.longinus-sha256-daemon.plist 패턴 참조.

환경변수:
  LAKATOS_ANCHOR_NEO4J_URI / _USER / _PASSWORD — KG 접속 (기본 bolt://localhost:7687, neo4j, neo4jpassword)
  LAKATOS_ANCHOR_CYPHER_SHELL — cypher-shell 경로 오버라이드
  LAKATOS_ANCHOR_OUTBOX — outbox 디렉토리 (기본 <repo>/docs/data/ots_anchors)
  LAKATOS_ANCHOR_CALENDARS — 캘린더 풀 CSV (기본 a.pool,b.pool.opentimestamps.org)
# KG: q-extaudit-temporal-witness-20260722 / PROM16 Phase1-L2
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# .ots 파일 포맷 (opentimestamps-client opentimestamps/core/detached.py 정합):
#   HEADER_MAGIC(31B) + varuint(MAJOR_VERSION=1) + file_hash_op tag(OpSHA256=0x08)
#   + digest(32B) + timestamp.serialize()
# 캘린더 POST /digest 응답 바디가 곧 serialized Timestamp 라 그대로 이어붙인다.
# ※2026-07-28 수리: 초판(24B magic·op 태그 누락)은 표준 `ots` 클라이언트가 파싱 거부하는
#   파일을 만들었다 — finding_c15adc24d551e4fe. 정본 상수로 교정, 구 사이드카는 --reassemble.
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
OTS_VERSION = 1
OP_SHA256_TAG = 0x08

_DOMAIN = b"lakatotree-daily-receipt-root/v1\n"
_DEFAULT_CALENDARS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org")
_CYPHER = ("MATCH (r:VerdictReceipt) WHERE r.receipt_sha IS NOT NULL AND r.receipt_sha <> '' "
           "RETURN r.receipt_sha AS sha ORDER BY sha")

# OTS 캘린더가 받는 digest 크기(sha256). 서버는 임의 바이트도 받지만 표준은 32B.
_DIGEST_LEN = 32


def compute_receipt_root(cypher_shell: str, uri: str, user: str, password: str) -> dict:
    """KG 의 전체 VerdictReceipt sha 집합 → canonical root 다이제스트.

    반환 {root_digest(hex), receipt_count, computed_at}. cypher-shell 실패는 RuntimeError(fail-loud
    — 조용한 빈 집합 앵커는 "없었다"는 거짓 증명을 찍을 수 있어 허용하지 않는다)."""
    proc = subprocess.run(
        [cypher_shell, "-a", uri, "-u", user, "-p", password, "--format", "plain", _CYPHER],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"cypher-shell 실패(rc={proc.returncode}): {proc.stderr.strip()[:300]}")
    shas = []
    for line in proc.stdout.splitlines():
        line = line.strip().strip('"')
        if line and line != "sha":
            shas.append(line)
    shas = sorted(set(shas))
    body = "".join(f"{s}\n" for s in shas)
    root = hashlib.sha256(_DOMAIN + body.encode("utf-8")).hexdigest()
    return {"root_digest": root, "receipt_count": len(shas),
            "computed_at": datetime.now(timezone.utc).isoformat()}


def assemble_ots_file(digest_bytes: bytes, calendar_timestamp_bytes: bytes) -> bytes:
    """DetachedTimestampFile.serialize() 정합 조립 — 표준 클라이언트가 파싱하는 포맷.
    (검증 자체는 여전히 외부 `ots verify` 의 몫 — 여기는 포맷 정합만 책임진다.)"""
    if len(digest_bytes) != _DIGEST_LEN:
        raise ValueError(f"digest 는 {_DIGEST_LEN}B 여야: {len(digest_bytes)}B")
    return (OTS_MAGIC + bytes([OTS_VERSION]) + bytes([OP_SHA256_TAG])
            + digest_bytes + calendar_timestamp_bytes)


# ── serialized Timestamp 최소 파서 (opentimestamps core/timestamp.py 문법 정합) ─────────
# 목적 2가지만: ① pending attestation 지점의 commitment(msg) 계산 — upgrade 질의는 원 digest 가
# 아니라 이 값으로 해야 한다(캘린더는 nonce-append+sha256 후 값으로 인덱싱; 원 digest 질의는 404)
# ② 확정 판정 = BitcoinBlockHeaderAttestation 태그 실재(바이트 diff 휴리스틱은 거짓 확정 가능).

_ATT_PENDING = bytes.fromhex("83dfe30d2ef90c8e")   # PendingAttestation.TAG
_ATT_BITCOIN = bytes.fromhex("0588960d73d71901")   # BitcoinBlockHeaderAttestation.TAG


def _read_varuint(buf: bytes, pos: int) -> tuple:
    value, shift = 0, 0
    while True:
        b = buf[pos]; pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7


def _read_varbytes(buf: bytes, pos: int, max_len: int) -> tuple:
    n, pos = _read_varuint(buf, pos)
    if n > max_len:
        raise ValueError(f"varbytes {n}B > 상한 {max_len}B")
    return buf[pos:pos + n], pos + n


def _apply_op(tag: int, msg: bytes, operand: bytes | None = None) -> bytes:
    if tag == 0x08:
        return hashlib.sha256(msg).digest()
    if tag == 0x02:
        return hashlib.sha1(msg).digest()
    if tag == 0x03:
        return hashlib.new("ripemd160", msg).digest()   # OpenSSL 구성따라 부재 가능 — fail-loud
    if tag == 0xF0:
        return msg + operand
    if tag == 0xF1:
        return operand + msg
    if tag == 0xF2:
        return msg[::-1]
    if tag == 0xF3:
        return msg.hex().encode()
    raise ValueError(f"미지원 op 태그 0x{tag:02x}")


def _parse_entry(buf: bytes, pos: int, tag: int, msg: bytes, atts: list) -> int:
    if tag == 0x00:                                  # attestation: TAG(8B) + varbytes payload
        start = pos - 1                              # 0x00 바이트 포함 (splice 단위)
        att_tag = buf[pos:pos + 8]; pos += 8
        payload, pos = _read_varbytes(buf, pos, 8192)
        atts.append({"msg": msg, "tag": att_tag, "payload": payload, "span": (start, pos)})
        return pos
    if tag in (0xF0, 0xF1):                          # binary op: varbytes operand
        operand, pos = _read_varbytes(buf, pos, 4096)
        return _parse_ts(buf, pos, _apply_op(tag, msg, operand), atts)
    return _parse_ts(buf, pos, _apply_op(tag, msg), atts)


def _parse_ts(buf: bytes, pos: int, msg: bytes, atts: list) -> int:
    while True:
        tag = buf[pos]; pos += 1
        if tag == 0xFF:                              # fork: 엔트리 하나 소화 후 계속
            inner = buf[pos]; pos += 1
            pos = _parse_entry(buf, pos, inner, msg, atts)
            continue
        return _parse_entry(buf, pos, tag, msg, atts)


def parse_attestations(ts_bytes: bytes, initial_msg: bytes) -> list:
    """serialized Timestamp 전체를 걷어 attestation 목록 반환.
    각 항목 {msg(그 지점 commitment), tag(8B), payload, span(원본 바이트 구간)}."""
    atts: list = []
    end = _parse_ts(ts_bytes, 0, initial_msg, atts)
    if end != len(ts_bytes):
        raise ValueError(f"timestamp 파싱 잔여 {len(ts_bytes) - end}B — 포맷 불일치")
    return atts


def bitcoin_block_height(payload: bytes) -> int:
    return _read_varuint(payload, 0)[0]


def stamp_with_calendar(calendar_base: str, digest_bytes: bytes, timeout: int = 60) -> bytes:
    """POST /digest → serialized Timestamp (pending attestation). 실패는 RuntimeError."""
    req = urllib.request.Request(f"{calendar_base}/digest", data=digest_bytes, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        raise RuntimeError(f"{calendar_base} 가 빈 attestation 반환")
    return body


def fetch_upgraded_timestamp(calendar_base: str, commitment_hex: str, timeout: int = 60) -> bytes:
    """GET /timestamp/{commitment} — 비트코인 확정 후면 블록 attestation 포함 serialized Timestamp.

    ※commitment = pending attestation 지점의 msg(캘린더가 nonce-append+sha256 적용 후 값).
    원 root digest 로 질의하면 404 (2026-07-28 실측·수리, finding_c15adc24d551e4fe)."""
    with urllib.request.urlopen(f"{calendar_base}/timestamp/{commitment_hex}", timeout=timeout) as resp:
        body = resp.read()
    if not body:
        raise RuntimeError(f"{calendar_base} 가 빈 timestamp 반환")
    return body


def _entry_path(outbox: Path, date_utc: str) -> Path:
    return outbox / f"{date_utc}.json"


def _write_ots_sidecar(outbox: Path, date_utc: str, pool_name: str, ots_bytes: bytes) -> str:
    fname = f"{date_utc}.{pool_name}.ots"
    (outbox / fname).write_bytes(ots_bytes)
    return fname


def _pool_name(calendar_base: str) -> str:
    # https://a.pool.opentimestamps.org → a.pool
    host = calendar_base.split("://", 1)[-1].split("/")[0]
    return host.split(".opentimestamps.org")[0] or host.replace(".", "_")


def run_daily(*, cypher_shell: str, uri: str, user: str, password: str,
              outbox: Path, calendars: tuple, digest_only: bool = False) -> dict:
    """오늘 root 계산→(선택)stamp + 기존 pending upgrade. 반환 = outbox 엔트리 dict."""
    outbox.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    root = compute_receipt_root(cypher_shell, uri, user, password)
    entry = {"date": today, **root, "calendars": {}, "status": "digest_only" if digest_only else "pending"}

    if not digest_only:
        digest_bytes = bytes.fromhex(root["root_digest"])
        ok = 0
        for cal in calendars:
            pool = _pool_name(cal)
            try:
                ts_bytes = stamp_with_calendar(cal, digest_bytes)
            except Exception as exc:  # 풀 하나 실패가 다른 풀을 막지 않는다 (정족 정신)
                entry["calendars"][pool] = {"status": "error", "error": str(exc)[:300]}
                continue
            ots_bytes = assemble_ots_file(digest_bytes, ts_bytes)
            fname = _write_ots_sidecar(outbox, today, pool, ots_bytes)
            entry["calendars"][pool] = {"status": "pending", "ots_file": fname,
                                        "attestation_b64": base64.b64encode(ts_bytes).decode()}
            ok += 1
        entry["status"] = "pending" if ok else "stamp_failed"
        _entry_path(outbox, today).write_text(json.dumps(entry, indent=1, ensure_ascii=False))

    upgraded = upgrade_pending(outbox=outbox, calendars=calendars)
    entry["upgraded_this_run"] = upgraded
    if not digest_only:
        _entry_path(outbox, today).write_text(json.dumps(entry, indent=1, ensure_ascii=False))
    return entry


def _splice_upgrade(old_ts: bytes, att: dict, response: bytes) -> bytes | None:
    """pending attestation 엔트리(span)를 upgrade 응답(그 지점 msg 기준 serialized Timestamp)으로
    바이트 치환. 안전 조건: 엔트리가 노드의 유일/최종 엔트리(직전 바이트가 0xff 아님 + tail).
    조건 밖(멀티 엔트리 fork)이면 None — splice 없이 응답만 보존한다(거짓 파일 조립 금지)."""
    start, end = att["span"]
    if end != len(old_ts) or (start > 0 and old_ts[start - 1] == 0xFF):
        return None
    return old_ts[:start] + response


def upgrade_pending(*, outbox: Path, calendars: tuple) -> list:
    """pending 엔트리를 비트코인 확정분으로 upgrade. 반환 = 확정된 (date, pool) 목록.

    확정 판정 = upgrade 응답 파싱에서 BitcoinBlockHeaderAttestation 태그 실재 (2026-07-28 수리:
    바이트-diff 휴리스틱은 pending 갱신 응답도 '확정'으로 오판 — 거짓 확정 가능이라 폐기).
    질의 키 = pending attestation 지점 commitment (원 digest 아님)."""
    confirmed = []
    if not outbox.is_dir():
        return confirmed
    for path in sorted(outbox.glob("*.json")):
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if entry.get("status") not in ("pending", "partial_confirmed"):
            continue
        digest = entry.get("root_digest", "")
        digest_bytes = bytes.fromhex(digest)
        any_success = False
        for pool, info in entry.get("calendars", {}).items():
            if info.get("status") != "pending":
                continue
            cal = next((c for c in calendars if _pool_name(c) == pool), None)
            if cal is None:
                continue
            old_ts = base64.b64decode(info.get("attestation_b64", ""))
            try:
                atts = parse_attestations(old_ts, digest_bytes)
            except (ValueError, IndexError) as exc:
                info["upgrade_error"] = f"attestation 파싱 실패: {exc}"[:200]
                continue
            pendings = [a for a in atts if a["tag"] == _ATT_PENDING]
            if not pendings:
                info["upgrade_error"] = "pending attestation 부재"
                continue
            for att in pendings:
                commitment_hex = att["msg"].hex()
                try:
                    resp = fetch_upgraded_timestamp(cal, commitment_hex)
                except Exception:
                    continue                          # 아직 미확정(404 등) — 다음 실행 재시도
                try:
                    resp_atts = parse_attestations(resp, att["msg"])
                except (ValueError, IndexError):
                    continue                          # 파싱 불가 응답은 확정 증거 아님
                btc = [a for a in resp_atts if a["tag"] == _ATT_BITCOIN]
                if not btc:
                    continue                          # pending 갱신일 뿐 — 확정 아님 (핵심 수리)
                spliced = _splice_upgrade(old_ts, att, resp)
                upgraded_ts = spliced if spliced is not None else old_ts
                ots_bytes = assemble_ots_file(digest_bytes, upgraded_ts)
                fname = _write_ots_sidecar(outbox, entry["date"], pool, ots_bytes)
                info.update({"status": "confirmed", "ots_file": fname,
                             "attestation_b64": base64.b64encode(upgraded_ts).decode(),
                             "bitcoin_block_height": bitcoin_block_height(btc[0]["payload"]),
                             "commitment": commitment_hex,
                             "confirmed_at": datetime.now(timezone.utc).isoformat()})
                if spliced is None:
                    info["upgrade_response_b64"] = base64.b64encode(resp).decode()
                    info["splice"] = "skipped-multi-entry"
                confirmed.append((entry["date"], pool))
                any_success = True
                break
        cal_states = {p: i.get("status") for p, i in entry.get("calendars", {}).items()}
        if cal_states and all(s == "confirmed" for s in cal_states.values()):
            entry["status"] = "confirmed"
        elif any_success or any(s == "confirmed" for s in cal_states.values()):
            entry["status"] = "partial_confirmed"
        path.write_text(json.dumps(entry, indent=1, ensure_ascii=False))
    return confirmed


def reassemble_sidecars(*, outbox: Path) -> list:
    """구판(24B magic·op 태그 누락) .ots 사이드카를 보존된 attestation_b64 로 정본 포맷 재조립.
    앵커 자체(캘린더 서명 시각)는 불변 — 파일 포맷만 소급 회수. 반환 = 재조립된 파일명 목록."""
    fixed = []
    if not outbox.is_dir():
        return fixed
    for path in sorted(outbox.glob("*.json")):
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        digest = entry.get("root_digest", "")
        if not digest:
            continue
        for pool, info in entry.get("calendars", {}).items():
            b64 = info.get("attestation_b64", "")
            fname = info.get("ots_file", "")
            if not b64 or not fname:
                continue
            ots_bytes = assemble_ots_file(bytes.fromhex(digest), base64.b64decode(b64))
            existing = outbox / fname
            if existing.is_file() and existing.read_bytes() == ots_bytes:
                continue
            existing.write_bytes(ots_bytes)
            fixed.append(fname)
    return fixed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="영수증 체인 root OTS 일일 앵커링")
    ap.add_argument("--digest-only", action="store_true", help="네트워크 없이 root 만 계산")
    ap.add_argument("--upgrade-all", action="store_true", help="stamp 없이 pending upgrade 만")
    ap.add_argument("--reassemble", action="store_true",
                    help="구판 포맷 .ots 사이드카를 정본 포맷으로 재조립(네트워크 불요)")
    args = ap.parse_args(argv)

    uri = os.environ.get("LAKATOS_ANCHOR_NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("LAKATOS_ANCHOR_NEO4J_USER", "neo4j")
    password = os.environ.get("LAKATOS_ANCHOR_NEO4J_PASSWORD", "neo4jpassword")
    cypher_shell = os.environ.get("LAKATOS_ANCHOR_CYPHER_SHELL", "cypher-shell")
    outbox = Path(os.environ.get("LAKATOS_ANCHOR_OUTBOX", ROOT / "docs" / "data" / "ots_anchors"))
    cal_csv = os.environ.get("LAKATOS_ANCHOR_CALENDARS", "")
    calendars = tuple(c.strip() for c in cal_csv.split(",") if c.strip()) or _DEFAULT_CALENDARS

    if args.reassemble:
        fixed = reassemble_sidecars(outbox=outbox)
        print(json.dumps({"reassembled": fixed}, ensure_ascii=False))
        return 0

    if args.upgrade_all:
        confirmed = upgrade_pending(outbox=outbox, calendars=calendars)
        print(json.dumps({"upgraded": confirmed}, ensure_ascii=False))
        return 0

    try:
        entry = run_daily(cypher_shell=cypher_shell, uri=uri, user=user, password=password,
                          outbox=outbox, calendars=calendars, digest_only=args.digest_only)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"date": entry["date"], "root_digest": entry["root_digest"],
                      "receipt_count": entry["receipt_count"], "status": entry["status"],
                      "upgraded": entry.get("upgraded_this_run", [])}, ensure_ascii=False))
    return 0 if entry["status"] in ("pending", "digest_only", "confirmed") else 1


if __name__ == "__main__":
    sys.exit(main())
