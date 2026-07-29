#!/usr/bin/env python3
"""Development compatibility wrapper for :mod:`lakatos.backtest_cli`.

Confirmatory locks name ``python -m lakatos.backtest_cli run`` as the canonical
execution surface; this repository wrapper is intentionally not authoritative.
"""
from lakatos.backtest_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
