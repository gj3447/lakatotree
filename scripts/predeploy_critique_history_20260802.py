#!/usr/bin/env python3
"""Compatibility wrapper for the installable storage predeploy entrypoint."""

from server.storage_predeploy import main


if __name__ == "__main__":
    raise SystemExit(main())
