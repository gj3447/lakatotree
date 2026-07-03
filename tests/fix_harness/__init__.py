"""FIX HARNESS — RED negative-oracle receipts for the 2026-06-27 audit findings.
Each test reproduces one confirmed defect against real code and is xfail(strict) until the
fix lands (then xpass trips strict, forcing removal of the marker). Run the RED demo with:
  bash scripts/fix_harness.sh   # or: pytest tests/fix_harness -rx --runxfail
"""
