"""FIX-HARNESS #22 (P3 robustness): CLI lineage-record / manifest-verify IndexError on no-colon input.

Finding id: #22
Locations:
  - lakatos/cli.py:394  (lineage-record)  inputs = [[p.rsplit(':',1)[0], p.rsplit(':',1)[1]] for p in a.input]
  - lakatos/cli.py:399  (manifest-verify) current_shas = {p.rsplit(':',1)[0]: p.rsplit(':',1)[1] for p in a.current_sha}
  MCP variants guard with "if ':' in p": lakatos/mcp_server.py:417-418, :430-431 — surfaces diverge.

Bug:
  Both CLI handlers do `p.rsplit(':',1)[1]` WITHOUT checking that ':' is present in the
  item. Passing `--input foo` (or `--current-sha foo`) with no colon makes rsplit return a
  single-element list, so the `[1]` index raises an unhandled IndexError and dumps a
  traceback to the user — a crash, not a diagnosis. The MCP server guards the same parse
  with `if ':' in p`, so the two surfaces disagree on identical input.

Fix:
  Validate ':' per item and `sys.exit(...)` with a clear "path:sha" message, mirroring the
  key=value handling at cli.py:301-302 (`if '=' not in item: sys.exit(...)`). The contract
  is a CLEAN SystemExit with a helpful message — never a raw IndexError.

xfail(strict) until fixed: today these tests raise IndexError (the bug). The negative
oracle below pins the CORRECT post-fix behavior (SystemExit + helpful message), so it FAILS
now (IndexError != SystemExit) and will PASS once the validation lands; strict trips then.

Hermetic: the malformed-input parse happens at cli.py:394/:399 BEFORE any server `call()`
or file read, so no server/Neo4j is needed to exercise the real crash.
"""
import pytest

from lakatos.cli import main


# [FIXED 2026-06-27] #22 — green regression (lakatos/cli.py:394 validates ':' → clean sys.exit)
def test_lineage_record_no_colon_input_exits_cleanly():
    # 실제 CLI 진입점(main(argv))을 호출 — '--input foo' 는 콜론이 없어 path:sha 분해 불가.
    # 올바른 사후 동작: 깔끔한 SystemExit(도움말 메시지). 현재 동작: IndexError(버그).
    with pytest.raises(SystemExit) as ei:
        main(["lineage-record", "art://out", "--sha", "abc123", "--input", "foo"])
    # SystemExit 의 메시지는 비어있지 않고 잘못된 항목('foo')이나 'path:sha' 형식을 안내해야 함.
    msg = str(ei.value.code)
    assert msg, "SystemExit 은 도움이 되는 메시지를 담아야 함(빈 코드 금지)"
    assert ("foo" in msg) or ("path:sha" in msg) or (":" in msg), (
        "메시지는 콜론 형식(path:sha) 또는 위반 항목을 안내해야 함"
    )


# [FIXED 2026-06-27] #22 — green regression (lakatos/cli.py:399 validates ':' → clean sys.exit)
def test_manifest_verify_no_colon_current_sha_exits_cleanly():
    # '--current-sha foo' 도 동일 결함 — 콜론 분해 전 검증이 없어 IndexError. manifest 파일은
    # 라인 399 크래시 이후(라인 401)에서야 읽히므로 존재하지 않아도 됨(파싱 단계에서 막혀야 정상).
    with pytest.raises(SystemExit) as ei:
        main(["manifest-verify", "/nonexistent/manifest.json", "--current-sha", "foo"])
    msg = str(ei.value.code)
    assert msg, "SystemExit 은 도움이 되는 메시지를 담아야 함(빈 코드 금지)"
    assert ("foo" in msg) or ("path:sha" in msg) or (":" in msg), (
        "메시지는 콜론 형식(path:sha) 또는 위반 항목을 안내해야 함"
    )
