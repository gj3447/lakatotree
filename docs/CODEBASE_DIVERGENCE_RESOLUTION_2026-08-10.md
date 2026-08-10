# 라카토트리 코드베이스 분기 정리 — 2026-08-10

> 상태: `MEASURED / BACKED_UP / MERGE_DEFERRED`
> 이 문서는 실측 기록이며, 병합 자체는 수행하지 않았다(테스트가 필요한 실작업).

## 0. 세 갈래였다

"두 코드베이스(36 vs 50 도구)" 로 알고 있었으나 실제로는 셋이다.

| 위치 | HEAD | 날짜 | MCP 도구 | 성격 |
|---|---|---|---|---|
| CT301 `/opt/lakatotree` | `7d946d0` | 2026-08-10 | — | **런타임 정본** (서버) |
| `~/CD/lakatotree-mcp` | `6e4ccdd` | 2026-07-29 | **50** | dev-01 harness의 rsync 미러 = **MCP 클라이언트 정본** |
| `~/CD/lakatotree` | `e7767d4` | 2026-08-10 | 36 | 뒤처진 feature 브랜치 체크아웃 |

`~/CD/lakatotree`의 36도구는 "축소판"이 아니라 **오래된 것**이다.
`origin/master` 대비 **530 커밋 뒤처지고 100 앞선** 상태였다.

## 1. 무엇이 정본인가

- **런타임**: CT301 `7d946d0`. Phase 8 적재도 여기에 들어갔다.
- **클라이언트**: 50도구 harness. 현 런타임과 **종단간 검증 완료** —
  `tools/list` 50개 응답, `get_tree`로 `LakatosTree_CPTTemporalFoldedSUSY_20260809`
  실제 조회 성공(응답 417KB).
- `~/CD/.mcp.json`의 `lakatotree` 항목은 `~/CD/lakatotree-mcp/`를 가리킨다.

즉 **일상 사용에는 문제가 없다.** 분기는 "어느 것을 쓸지"가 아니라
"뒤처진 체크아웃의 100 커밋을 어떻게 할지"의 문제다.

## 2. 조치 — 유실 위험 제거

`~/CD/lakatotree`의 세 브랜치를 전부 GitHub `gj3447/lakatotree`로 대피시켰다.
`master`는 원격보다 뒤처져 있어 **force하지 않고 날짜 붙은 backup 브랜치**로 밀었다.

| 로컬 브랜치 | 원격 |
|---|---|
| `feat/ice-orca-dragon-programme` | 동명 브랜치 (신규) |
| `master` (530 behind) | `backup/mac-master-20260810` |
| `feat/longinus-cli-internal-mcp` | `backup/mac-longinus-cli-20260810` |

검증: 세 브랜치 모두 `git log --branches --not --remotes` = **0**.
추가로 저장소 전체 `git bundle --all`이 MinIO
`symposium-archive/repo-bundles-2026-08-10/lakatotree-all-20260810.bundle`
(sha256 `2ed2aa9f…` 대조 일치)에 있다.

부수 수정: `remote.origin.fetch`가 `master`만 가져오도록 제한돼 있어 push 후에도
추적 ref가 안 생기고 미푸시 카운트가 틀리게 나왔다. `+refs/heads/*:refs/remotes/origin/*`
로 바로잡았다.

## 3. 미룬 것 — 병합

`~/CD/lakatotree`의 100 커밋을 `origin/master`(530 앞섬)에 합치는 일은
rebase/merge 충돌 해소 + 테스트가 필요한 실작업이라 이번에 하지 않았다.
지금은 **양쪽 다 원격에 안전하게 있으므로 급하지 않다.**

병합할 때 확인할 것:
1. 100 커밋 중 실제로 살릴 것이 무엇인지 — 상당수가 연구·증거 산출물이고
   런타임 코드 변경은 적을 수 있다.
2. `lakatos/mcp_server.py`는 **병합 대상이 아니다.** 50도구 harness 쪽이
   이미 앞서 있으므로, 36도구 판을 master에 되돌려 넣으면 퇴행이다.
3. 병합 후 반드시 현 런타임 대비 `tools/list` + 실제 tool call로 재검증한다.

## 관련

- `LOST_TOOLS_RECOVERY_SPEC_2026-08-10.md` — 14개 도구 인터페이스 레퍼런스
  (당초 "소실 복구용"이었으나 전제가 틀렸음이 밝혀져 레퍼런스로 재분류)
- `~/CD/lakatotree-mcp/RUNTIME_MIRROR_README.md` — 편집 금지 미러 규약
- SYMPOSIUM `FINDINGS/git-directory-loss-2026-08-10/RESOLUTION.md`
