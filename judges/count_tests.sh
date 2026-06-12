#!/usr/bin/env bash
cd "$(dirname "$0")/.."
N=$(python -m pytest tests/ -q 2>&1 | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+")
echo "metric=$N"
