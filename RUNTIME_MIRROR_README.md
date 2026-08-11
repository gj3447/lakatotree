# 런타임 미러 — 편집 금지

이 디렉터리는 **작업 사본이 아니라 MCP 런타임 미러**다.

- 정본: `dev-01:/root/CD/SYMPOSIUM/GIT/lakatotree_codex_harness_20260714` (HEAD `6e4ccdd`)
- 여기: Mac에서 `lakatotree` MCP를 띄우기 위한 소스 사본 (`.venv` 제외 20MB)
- 생성: 2026-08-10, `rsync -a --exclude=.venv --exclude=__pycache__`

수정은 **dev-01에서** 하고 여기로 다시 rsync한다. 여기서 편집하면 dev-01의
미푸시 커밋 7개와 갈라진다.

`~/CD/.mcp.json`의 `lakatotree` 항목이 이 경로를 가리킨다.
venv 재생성: `uv venv .venv && uv pip install "mcp<2" httpx`
(`mcp` 2.x는 `mcp.server.fastmcp`가 없어 실패한다.)
