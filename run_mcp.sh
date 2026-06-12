#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python -m lakatos.mcp_server
