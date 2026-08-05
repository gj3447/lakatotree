#!/usr/bin/env python3
"""D3b 스코어러 — MCP preflight 가 서버의 **실제** 루트 게이트와 어긋난 수 (역할 인식판).

D3(d3_preflight_synced_roots_scorer_20260729.py)의 후계. 같은 지표, 같은 오라클,
바뀐 건 측정 대상 구조다.

## 왜 후계가 필요했나
D3 는 `SYNCED_ROOTS` 를 **리터럴 튜플**로 가정하고 AST 로 뽑아 exec 한다. 07-29 의
역할분리 리팩터가 그 줄을 `SYNCED_ROOTS = _server_roots('result')` 로 바꾼 순간
D3 는 NameError 로 FAIL-LOUD 하며 죽었다. 죽는 쪽이 조용히 통과하는 쪽보다 낫지만,
결과적으로 **그날 이후 이 지표는 한 번도 측정되지 않았다**. 그 사이 2026-08-05 에
`_server_env()` 가 자기 env 하나만 차 있어도 /proc 조회를 건너뛰어 LAKATOS_RAW_ROOT
를 영영 못 배우는 회귀가 실사용에서 드러났다(거짓경고). 계기가 꺼져 있어서 회귀가
보이지 않았다 — 스코어러를 되살리는 것이 수정의 일부다.

## 무엇을 재나
metric = |{(경로,역할) ∈ SAMPLE : preflight 가 경고 ≠ 서버 게이트가 실제로 막음}|
       = false_warning(경고했는데 서버는 통과) + missed_warning(무경고인데 서버가 막음)

**양방향이라 화이트리스트로 못 속인다** — 전부 허용하면 false_warning 은 0 이 되지만
게이트 밖 표본에서 missed_warning 이 올라간다.

## 오라클 (수정과 독립)
 게이트 A  script  = longinus.ROOT(repo) + gettempdir + replay_cache + LAKATOS_SCRIPT_ROOTS
                     (server/contexts/tree/judgement_service.py:isolate_script_file)
 게이트 B  result  = LAKATOS_RAW_ROOT (server/file_hashing.py:_within_raw_root, production import)
설정값은 **살아 있는 uvicorn :55170 프로세스의 /proc environ** 에서 읽는다. 클라이언트
설정이 아니다 — 그게 이 지표가 재려는 바로 그 어긋남이니까.

## PRE 채널
`git show <PRE_COMMIT>:lakatos/mcp_server.py` 를 임시파일로 적재해 **실제 옛 코드**를
돌린다. 미러 재구현이 아니다(미러는 드리프트한다). git 이 없으면 FAIL-LOUD.

## 실행 조건
클라이언트 env 를 실배포와 동일하게 세팅한 뒤 측정한다 — .claude.json 이 MCP 클라이언트에
LAKATOS_SCRIPT_ROOTS 만 좁게 주는 그 상태가 회귀의 트리거이기 때문이다.

사용: python d3b_preflight_role_roots_scorer_20260805.py [result.json]
출력: stdout 한 줄 `metric=<disagreement count>`
"""
from __future__ import annotations

import os
import sys

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

LKT_REPO = "/data/kjra/PROJECT/PI/lakatotree"
MCP_SERVER_PY = LKT_REPO + "/lakatos/mcp_server.py"
FILE_HASHING_PY = LKT_REPO + "/server/file_hashing.py"
REPLAY_ARTIFACTS_PY = LKT_REPO + "/lakatos/replay_artifacts.py"
PRE_COMMIT = "3202fce"          # _server_env 부분-env 단락 회귀가 살아 있던 마지막 커밋

# 실배포 클라이언트 조건 — .claude.json 의 lakatotree MCP env 그대로.
# 이 한 줄이 회귀의 트리거다: 값이 차 있으면 옛 코드가 /proc 을 안 본다.
DEPLOYED_CLIENT_ENV = {"LAKATOS_SCRIPT_ROOTS": "/data/kjra/PROJECT/3DLAB"}

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

# (절대경로, 역할, 존재강제)
SAMPLE = (
    # ── 역할 script ─────────────────────────────────────────────────────────
    (MCP_SERVER_PY, "script", True),                                    # repo 안
    ("/data/kjra/PROJECT/3DLAB", "script", True),                       # 클라이언트도 아는 루트
    ("/data/kjra/PROJECT/PI/lakatotree/server/file_hashing.py", "script", True),
    ("/tmp", "script", True),                                           # gettempdir
    ("/data/kjra/PROJECT/SQCEDIT", "script", True),                     # RAW 안 · SCRIPT 밖
    ("/etc/passwd", "script", True),                                    # 진짜 밖
    ("/var/log", "script", True),                                       # 진짜 밖
    ("/data/kjra/hswm-f1-r8-0701da8", "script", True),                  # PROJECT 밖
    # ── 역할 result ─────────────────────────────────────────────────────────
    ("/data/kjra/PROJECT/3DLAB", "result", True),
    ("/data/kjra/PROJECT/SQCEDIT", "result", True),                     # ★RAW 안인데 옛 코드는 경고
    (MCP_SERVER_PY, "result", True),                                    # ★RAW 안인데 옛 코드는 경고
    ("/data/kjra/PROJECT/PI", "result", True),                          # ★같은 사유
    ("/etc/passwd", "result", True),
    ("/var/log", "result", True),
    ("/data/kjra/hswm-f1-r8-0701da8", "result", True),                  # PROJECT 밖 — 진짜 경고 대상
)


def _fail(msg: str) -> int:
    print(f"FAIL-LOUD: {msg}", file=sys.stderr)
    return 1


def load_module(path: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"FAIL-LOUD: 로드 불가 {path}")
    m = importlib.util.module_from_spec(spec)
    sys.modules[alias] = m
    spec.loader.exec_module(m)
    return m


def server_env() -> tuple[dict, str]:
    """살아 있는 uvicorn :55170 의 environ. 못 찾으면 채점하지 않는다."""
    for pid in sorted(os.listdir("/proc"), key=lambda s: (not s.isdigit(), s)):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace")
            if "uvicorn" not in cmd or "55170" not in cmd:
                continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = dict(kv.split("=", 1) for kv in
                           f.read().decode("utf-8", "replace").split("\0") if "=" in kv)
        except OSError:
            continue
        if env.get("LAKATOS_RAW_ROOT"):
            return env, f"proc:{pid}"
    raise SystemExit("FAIL-LOUD: 살아 있는 서버의 LAKATOS_RAW_ROOT 를 못 찾았다 — "
                     "오라클 없이 채점하지 않는다")


def main() -> int:
    senv, env_channel = server_env()

    # ── 오라클 배선. 서버 설정을 프로세스 env 로 주입한 뒤 production 코드를 쓴다 ──
    for k in ("LAKATOS_RAW_ROOT", "LAKATOS_SCRIPT_ROOTS", "LAKATOS_REPLAY_CACHE_ROOT"):
        if k in senv:
            os.environ[k] = senv[k]
    FH = load_module(FILE_HASHING_PY, "lkt_file_hashing")
    RA = load_module(REPLAY_ARTIFACTS_PY, "lkt_replay_artifacts")
    if os.path.realpath(FH.raw_root()) != os.path.realpath(senv["LAKATOS_RAW_ROOT"]):
        return _fail("raw_root 주입 실패")

    script_roots = [Path(LKT_REPO).resolve(), Path(tempfile.gettempdir()).resolve(),
                    RA.replay_cache_root()]
    for part in senv.get("LAKATOS_SCRIPT_ROOTS", "").split(os.pathsep):
        if part.strip():
            try:
                script_roots.append(Path(part.strip()).resolve())
            except OSError:
                pass

    def blocked_by_gate(p: str, role: str) -> bool:
        if role == "result":
            return not FH._within_raw_root(p)
        resolved = Path(p).resolve()
        return not any(r == resolved or r in resolved.parents for r in script_roots)

    sanity = [
        (not blocked_by_gate(MCP_SERVER_PY, "script"), "repo script 는 통과해야 한다"),
        (blocked_by_gate("/etc/passwd", "script"), "/etc/passwd script 는 막혀야 한다"),
        (not blocked_by_gate("/tmp/x.py", "script"), "gettempdir script 는 통과"),
        (not blocked_by_gate(MCP_SERVER_PY, "result"), "raw root 안 result 는 통과"),
        (blocked_by_gate("/etc/passwd", "result"), "/etc/passwd result 는 막혀야 한다"),
        (blocked_by_gate("/data/kjra/hswm-f1-r8-0701da8", "result"), "PROJECT 밖 result 는 막힘"),
    ]
    for ok, why in sanity:
        if not ok:
            return _fail(f"오라클 sanity 실패 — {why}")

    missing = sorted({p for p, _r, req in SAMPLE if req and not os.path.exists(p)})
    if missing:
        return _fail(f"존재를 강제한 표본 경로가 없다: {missing}")

    # ★오라클을 **여기서 확정**한다. file_hashing.raw_root() 는 호출 시점의 env 를
    # 읽으므로, 아래에서 클라이언트 조건을 복원하려고 LAKATOS_RAW_ROOT 를 지우면
    # 오라클이 조용히 무너진다. sanity 는 지우기 전에 돌아 통과하고 채점만 망가지는,
    # 정확히 이 스코어러가 잡으려는 종류의 false 다(2026-08-05 자기적발, metric 2→3
    # 으로 위장돼 나타났다).
    oracle = {(p, role): blocked_by_gate(p, role) for p, role, _req in SAMPLE}

    # ── 피측정: 클라이언트 env 는 실배포 조건으로 되돌린다 ─────────────────────
    for k in ("LAKATOS_RAW_ROOT", "LAKATOS_SCRIPT_ROOTS"):
        os.environ.pop(k, None)
    os.environ.update(DEPLOYED_CLIENT_ENV)

    def evaluate(mod) -> dict:
        mod._SERVER_ENV_CACHE = None                      # 캐시는 측정 간 격리
        false_warn, missed_warn, agree = [], [], []
        for p, role, _req in SAMPLE:
            warns = bool(mod._preflight_paths(p, role=role))
            blocked = oracle[(p, role)]
            item = f"{p} [{role}]"
            if warns and not blocked:
                false_warn.append(item)
            elif (not warns) and blocked:
                missed_warn.append(item)
            else:
                agree.append(item)
        return {"false_warning": false_warn, "missed_warning": missed_warn,
                "agree_n": len(agree),
                "learned_env": dict(mod._server_env()),
                "disagreements": len(false_warn) + len(missed_warn)}

    post_mod = load_module(MCP_SERVER_PY, "lkt_mcp_post")
    post_r = evaluate(post_mod)

    out = subprocess.run(["git", "-C", LKT_REPO, "show",
                          f"{PRE_COMMIT}:lakatos/mcp_server.py"],
                         capture_output=True, timeout=60)
    if out.returncode != 0 or not out.stdout:
        return _fail(f"PRE 코드({PRE_COMMIT})를 git 에서 못 꺼냈다 — 미러로 대체하지 않는다")
    with tempfile.NamedTemporaryFile("wb", suffix="_pre_mcp_server.py", delete=False) as f:
        f.write(out.stdout)
        pre_path = f.name
    try:
        pre_r = evaluate(load_module(pre_path, "lkt_mcp_pre"))
    finally:
        os.unlink(pre_path)

    baseline, value = pre_r["disagreements"], post_r["disagreements"]
    payload = {
        "seq": "D3b", "replay_scorer": True,
        "metric": value,
        "metric_name": "preflight_vs_server_gate_disagreements",
        "baseline_pre_fix": baseline,
        "direction": "lower",
        "sample_n": len(SAMPLE),
        "pre_commit": PRE_COMMIT,
        "deployed_client_env": DEPLOYED_CLIENT_ENV,
        "oracle": {
            "env_channel": env_channel,
            "server_env": {k: senv[k] for k in
                           ("LAKATOS_RAW_ROOT", "LAKATOS_SCRIPT_ROOTS") if k in senv},
            "gate_script_roots": [str(r) for r in script_roots],
            "gate_result_root": FH.raw_root(),
        },
        "pre": pre_r, "post": post_r,
        "note": ("양방향 지표 — false_warning 만 보면 화이트리스트로 0 을 만들 수 있다. "
                 "missed_warning 을 같이 세서 그 길을 막았다."),
    }

    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    for line in (
        f"baseline(pre {PRE_COMMIT})={baseline}  metric(post)={value}  sample_n={len(SAMPLE)}",
        f"  pre  env learned: {pre_r['learned_env']}",
        f"  post env learned: {post_r['learned_env']}",
        f"  pre : false_warning={len(pre_r['false_warning'])} missed_warning={len(pre_r['missed_warning'])}",
        f"  post: false_warning={len(post_r['false_warning'])} missed_warning={len(post_r['missed_warning'])}",
        f"  pre.false_warning   {pre_r['false_warning']}",
        f"  post.false_warning  {post_r['false_warning']}",
        f"  post.missed_warning {post_r['missed_warning']}",
        f"  env_channel={env_channel}",
    ):
        print(line, file=sys.stderr)

    print(f"metric={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
