#!/usr/bin/env bash
# FIX HARNESS runner — RED negative-oracle receipts for the 2026-06-27 audit findings.
#
# Each receipt in tests/fix_harness/ reproduces ONE confirmed defect against the REAL code
# path and is marked xfail(strict). Two ways to look at it:
#
#   * suite-green view (default `pytest tests/`): the receipts report `xfailed`, so the main
#     suite stays green while the bugs are still open.
#   * RED demo (this script, `--runxfail`): the xfail markers are ignored, every receipt runs
#     for real, and the open bugs surface as actual FAILUREs — that is the "receipt" the bug exists.
#
# As each fix lands, its receipt flips to XPASS; strict=True then turns XPASS into a hard
# failure, forcing you to delete the now-obsolete xfail marker (ratchet — no silent re-RED).
#
# Usage:
#   bash scripts/fix_harness.sh            # RED demo (expects failures = open bugs)
#   bash scripts/fix_harness.sh -k oo      # filter
#   LAKATOS_IT=1 bash scripts/fix_harness.sh   # also runs the #16/#17 real-Neo4j receipt
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
echo "### FIX HARNESS — RED board (--runxfail: a FAIL here = the bug is still open) ###"
exec "$PY" -m pytest tests/fix_harness -rA --runxfail -p no:randomly -q "$@"
