"""Vendored subset of ooptdd-loop (private repo gj3447/ooptdd-loop) — *only* the
positive-TDD loop runner needed to re-verify the design-audit receipts (ooptdd_receipts/run_all.py)
in clean-clone CI *without* a private-repo secret. base ``ooptdd`` lives in _vendor/ooptdd.

subset = {spec, runner, tools, selector_gates, longinus, oo_rca, log_mcp, rules, report}.
상위 패키지의 golden/local_capture/mcp_server/cli/kg 등은 런너 폐포 밖이라 *미포함*(minimal init).
갱신은 upstream 에서 재-vendor. 모듈 간은 relative import, base 는 `from ooptdd...`(같은 _vendor path).
"""
