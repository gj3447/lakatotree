#!/usr/bin/env python3
"""D3 스코어러 — MCP preflight(SYNCED_ROOTS) 가드가 서버의 **실제** 루트 게이트와 어긋난 수.

## 무엇을 재나
`lakatos/mcp_server.py:_preflight_paths()` 는 제출 경로가 "서버가 읽을 수 없는 곳"이면
경고한다. 그 경고가 근사하려는 참 술어는 서버가 실제로 거는 **루트 게이트**인데,
서버에는 게이트가 **둘** 있고 필드마다 다르다:

  게이트 A  script / novel_script / result_path
            server/contexts/tree/judgement_service.py:isolate_script_file
            허용 = longinus.ROOT(repo) + tempfile.gettempdir() + replay_cache_root()
                   + LAKATOS_SCRIPT_ROOTS
  게이트 B  record_derivation 의 output / inputs (lineage source)
            server/file_hashing.py:_within_raw_root  — 허용 = LAKATOS_RAW_ROOT

`_preflight_paths` 는 이 둘을 **하나의 SYNCED_ROOTS 로** 근사한다. 그래서 표본은
(경로, 필드) 쌍이고 오라클은 그 필드에 서버가 실제로 거는 게이트다.

오라클 설정값은 **살아 있는 서버 프로세스**(/proc/<uvicorn :55170>/environ)에서 읽는다.
이 오라클은 e4f2712 수정과 독립이다 — 수정은 클라이언트 상수만 건드렸다.

metric = |{(p,f) ∈ SAMPLE : preflight_warns(p) ≠ 서버_게이트가_막음(p,f)}|
       = false_warning(경고했는데 서버는 통과시킴) + missed_warning(무경고인데 서버가 막음)

**양방향이라 화이트리스트로 못 속인다** — 전부 허용하면 false_warning 은 0 이 되지만
게이트 밖 표본에서 missed_warning 이 올라간다(공허 게이트 '한쪽만 보는 가드' 회피).

## 값앵커 (손질하면 터진다)
 · PRE  SYNCED_ROOTS = `git show e4f2712^` AST 추출 ↔ 내장 리터럴 대조
 · POST SYNCED_ROOTS = 작업트리 mcp_server.py AST 추출 ↔ 내장 리터럴 대조
 · e4f2712 가 추가한 루트가 정확히 2개인지 대조
 · 게이트 A 는 production 코드를 import 할 수 없어(fastapi 의존) **미러**한다 →
   원본 `_allowed_script_roots` / `isolate_script_file` / `longinus.ROOT` 의
   소스 sha256 을 핀. 서버 코드가 바뀌면 미러가 낡았다는 뜻이라 FAIL-LOUD.
 · 게이트 B 는 production `server/file_hashing.py` 를 그대로 import 해서 쓴다.

## replay 4층 처방 ([[lakatotree-replay-sandbox-rlimit]])
 L3 numpy import 전에 BLAS THREADS=1 (본 스코어러는 stdlib 전용이라 무해하지만 계약 준수)
 L1 인터프리터 재실행 shim — `_LKT_REEXEC` 가드로 무한루프 방지
 L2 result 파일 쓰기는 best-effort(try/except OSError). 채점 정본 채널 = stdout `metric=` 한 줄
 L4 전 경로 절대경로 — 서버가 스크립트를 artifact 디렉터리로 복사해 실행한다

사용: python d3_preflight_synced_roots_scorer_20260729.py [result.json]
출력: stdout 한 줄 `metric=<disagreement count>`
"""
from __future__ import annotations

import os
import sys

# ── L3: numpy import 전에 BLAS 스레드 고정 (반드시 최상단) ──────────────────
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

# ── L4: 절대경로 고정. __file__ 상대경로 금지 ──────────────────────────────
LKT_REPO = "/data/kjra/PROJECT/PI/lakatotree"
MCP_SERVER_PY = LKT_REPO + "/lakatos/mcp_server.py"
FILE_HASHING_PY = LKT_REPO + "/server/file_hashing.py"
REPLAY_ARTIFACTS_PY = LKT_REPO + "/lakatos/replay_artifacts.py"
JUDGEMENT_SERVICE_PY = LKT_REPO + "/server/contexts/tree/judgement_service.py"
LONGINUS_PY = LKT_REPO + "/lakatos/longinus.py"
FIX_COMMIT = "e4f27123aa5f67b3ce267f807d27fbbf6e213bf3"
TARGET_PY = "/data/kjra/miniconda3/envs/cad3d/bin/python"

# ── L1: 인터프리터 재실행 shim ─────────────────────────────────────────────
# stdlib 만 쓰지만 세 조건(정본 env / 서버 python / 재배치)에서 **같은 인터프리터**로
# 수렴시켜야 값이 비트 동일해진다. 대상이 없으면 그대로 진행(FAIL-LOUD 아님).
if os.environ.get("_LKT_REEXEC") != "1" and os.path.exists(TARGET_PY):
    if os.path.realpath(sys.executable) != os.path.realpath(TARGET_PY):
        os.environ["_LKT_REEXEC"] = "1"
        _self = os.path.abspath(__file__)
        os.execv(TARGET_PY, [TARGET_PY, _self] + sys.argv[1:])

import ast
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════
# 값앵커 ①  SYNCED_ROOTS 두 버전
# ══════════════════════════════════════════════════════════════════════════
_MAC_SYMPOSIUM = tuple(
    f"/Users/lagyeongjun/CD/SYMPOSIUM/{d}" for d in (
        "PI", "HSWM", "THEORY", "FINDINGS", "METAHUMOTONIC", "MATH", "PAPERS",
        "BIZ_IDEA", "GAMES", "GAME_IDEA", "GROK", "FEEDBACK", "docs", "bin",
        "kg", "methodology-resolver", "REPRODUCTION", "ONTOLOGY",
        "mcp-server-symposium", "GIT", "_archive", "SKILLS"))

ANCHOR_PRE = ("/opt/lakatotree", "/Users/lagyeongjun/CD/spacegirl_tool") + _MAC_SYMPOSIUM
ANCHOR_POST = ("/opt/lakatotree", "/data/kjra/PROJECT",
               "/data/kjra/.local/state/lakatotree",
               "/Users/lagyeongjun/CD/spacegirl_tool") + _MAC_SYMPOSIUM
ANCHOR_ADDED = ("/data/kjra/PROJECT", "/data/kjra/.local/state/lakatotree")

# ══════════════════════════════════════════════════════════════════════════
# 값앵커 ②  게이트 A 미러가 베끼고 있는 production 소스의 sha256
#   (fastapi 의존 때문에 import 불가 → 미러. 원본이 바뀌면 미러가 낡은 것이므로 FAIL-LOUD)
# ══════════════════════════════════════════════════════════════════════════
PINNED_SOURCE_SHA = {
    (JUDGEMENT_SERVICE_PY, "func", "_allowed_script_roots"):
        "19fe5e8f3bdb0baa2fa646499c1e5943d24a2ca55a118d1a7633b96344fb8c63",
    (JUDGEMENT_SERVICE_PY, "func", "isolate_script_file"):
        "b4b6490bc56e76e435d5402e4f1d4984d1e7236744d545dd922f90a14a84cadc",
    (LONGINUS_PY, "line", "ROOT ="):
        "368e0b19b5c2054e768091e0f4a14f5009340b92571f3e578aca9185f278b094",
}

# ══════════════════════════════════════════════════════════════════════════
# 표본 — (절대경로, 필드, 존재강제)
#   필드 'script'      → 게이트 A (script/novel_script/result_path 가 같은 게이트다)
#   필드 'derivation'  → 게이트 B (record_derivation output/inputs)
# 이 머신에서 실제로 라카토트리에 넣거나 넣을 법한 경로만 쓴다.
# ══════════════════════════════════════════════════════════════════════════
SAMPLE = (
    # ── 게이트 A: 오늘 실제로 submit_result 의 script/result_path 로 준 종류 ──
    ("/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC/scripts/harness411_replay_scorer_20260729.py", "script", True),
    ("/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC/tests/test_longinus_20260729_recompute.py", "script", True),
    ("/data/kjra/PROJECT/PI/lakatotree/lakatos/mcp_server.py", "script", True),
    ("/data/kjra/.local/state/lakatotree/replay-artifacts/v1/script", "script", True),
    ("/tmp", "script", True),                       # gettempdir — 서버는 허용한다
    ("/data/kjra/PROJECT/LX3_RAW", "script", True),  # raw root 안이지만 SCRIPT_ROOTS 밖
    ("/etc/passwd", "script", True),                 # 진짜 밖
    ("/var/log", "script", True),                    # 진짜 밖
    # ── 게이트 B: record_derivation 의 source/output 종류 ────────────────────
    ("/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC/evidence/T_03full_to_step_cad_20260518.json", "derivation", True),
    ("/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC/evidence/README.md", "derivation", True),
    ("/data/kjra/PROJECT/PI/lakatotree/server/file_hashing.py", "derivation", True),
    ("/data/kjra/PROJECT/LX3_RAW", "derivation", True),
    ("/data/kjra/.local/state/lakatotree/replay-artifacts/v1/result", "derivation", True),
    ("/tmp", "derivation", True),
    ("/etc/passwd", "derivation", True),
    ("/var/log", "derivation", True),
)


def _fail(msg: str) -> int:
    print(f"FAIL-LOUD: {msg}", file=sys.stderr)
    return 1


# ══════════════════════════════════════════════════════════════════════════
# SYNCED_ROOTS 추출 — AST 로 대입문만 격리 실행 (mcp/httpx import 불필요)
# ══════════════════════════════════════════════════════════════════════════
def extract_synced_roots(src: str, origin: str) -> tuple:
    tree = ast.parse(src, filename=origin)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SYNCED_ROOTS" for t in node.targets):
            mod = ast.Module(body=[node], type_ignores=[])
            # genexp 는 자기 스코프를 가지므로 globals/locals 를 같은 dict 로.
            # builtins 는 tuple 하나만 노출(임의코드 실행 표면 최소화).
            ns: dict = {"__builtins__": {"tuple": tuple}}
            exec(compile(mod, origin, "exec"), ns, ns)  # noqa: S102
            val = ns.get("SYNCED_ROOTS")
            if not isinstance(val, tuple) or not val:
                raise SystemExit(f"FAIL-LOUD: {origin} SYNCED_ROOTS 가 비었거나 튜플이 아니다")
            return val
    raise SystemExit(f"FAIL-LOUD: {origin} 에 SYNCED_ROOTS 대입문이 없다")


def preflight_warns(p: str, roots: tuple) -> bool:
    """mcp_server._preflight_paths 의 판정 술어와 동일 (절대경로 + 루트 prefix)."""
    return isinstance(p, str) and p.startswith("/") and not p.startswith(roots)


# ══════════════════════════════════════════════════════════════════════════
# 값앵커 검사기
# ══════════════════════════════════════════════════════════════════════════
def check_pinned_sources() -> list[str]:
    bad = []
    for (path, kind, key), want in PINNED_SOURCE_SHA.items():
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            bad.append(f"{path}: 읽기 실패 {e}")
            continue
        got = None
        if kind == "func":
            for n in ast.walk(ast.parse(src, filename=path)):
                if isinstance(n, ast.FunctionDef) and n.name == key:
                    seg = ast.get_source_segment(src, n)
                    if seg is not None:
                        got = hashlib.sha256(seg.encode()).hexdigest()
                    break
        else:
            for line in src.splitlines():
                if line.startswith(key):
                    got = hashlib.sha256(line.encode()).hexdigest()
                    break
        if got != want:
            bad.append(f"{path}::{key} sha {got} != pinned {want}")
    return bad


# ══════════════════════════════════════════════════════════════════════════
# 오라클 설정값 — 살아 있는 서버 프로세스의 env
# ══════════════════════════════════════════════════════════════════════════
SERVER_ENV_KEYS = ("LAKATOS_RAW_ROOT", "LAKATOS_SCRIPT_ROOTS",
                   "LAKATOS_REPLAY_CACHE_ROOT", "TMPDIR")


def server_env() -> tuple[dict, str]:
    """(env subset, 채널). /proc 에서 uvicorn :55170 을 찾아 그 environ 을 읽는다."""
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
            return {k: env[k] for k in SERVER_ENV_KEYS if k in env}, f"proc:{pid}"
    # replay 는 서버의 자식 프로세스라 env 를 상속한다 — 2차 채널
    if os.environ.get("LAKATOS_RAW_ROOT"):
        return ({k: os.environ[k] for k in SERVER_ENV_KEYS if k in os.environ},
                "inherited_env")
    raise SystemExit("FAIL-LOUD: 살아 있는 서버의 LAKATOS_RAW_ROOT 를 못 찾았다 — "
                     "오라클 없이 채점하지 않는다")


def load_module(path: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"FAIL-LOUD: 로드 불가 {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    # ── 값앵커 ②: 게이트 A 미러가 베끼는 production 소스가 그대로인가 ────────
    drift = check_pinned_sources()
    if drift:
        return _fail("서버 소스가 핀된 sha 와 다르다(미러가 낡음): " + " | ".join(drift))

    # ── 값앵커 ①: POST SYNCED_ROOTS ────────────────────────────────────────
    with open(MCP_SERVER_PY, "r", encoding="utf-8") as f:
        post = extract_synced_roots(f.read(), MCP_SERVER_PY)
    if tuple(post) != ANCHOR_POST:
        return _fail(f"POST SYNCED_ROOTS 불일치.\n  live ={post}\n  anchor={ANCHOR_POST}")

    # ── 값앵커 ①: PRE SYNCED_ROOTS (git show, 있으면 대조) ──────────────────
    pre_channel = "embedded_anchor"
    try:
        out = subprocess.run(
            ["git", "-C", LKT_REPO, "show", f"{FIX_COMMIT}^:lakatos/mcp_server.py"],
            capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            pre_git = extract_synced_roots(out.stdout.decode("utf-8"), "git:pre")
            if tuple(pre_git) != ANCHOR_PRE:
                return _fail(f"PRE SYNCED_ROOTS 불일치.\n  git ={pre_git}\n  anchor={ANCHOR_PRE}")
            pre_channel = "git_show_verified"
    except (OSError, subprocess.SubprocessError):
        pass
    pre = ANCHOR_PRE

    added = tuple(r for r in post if r not in pre)
    if added != ANCHOR_ADDED:
        return _fail(f"e4f2712 가 추가한 루트가 예상과 다르다: {added}")

    # ── 오라클 배선 ────────────────────────────────────────────────────────
    senv, env_channel = server_env()
    for k, v in senv.items():
        os.environ[k] = v

    # 게이트 B = production 코드 그대로
    FH = load_module(FILE_HASHING_PY, "lkt_file_hashing")
    if os.path.realpath(FH.raw_root()) != os.path.realpath(senv["LAKATOS_RAW_ROOT"]):
        return _fail("raw_root 주입 실패")

    # 게이트 A = 미러(핀된 원본과 1:1). replay_cache_root 는 production import.
    RA = load_module(REPLAY_ARTIFACTS_PY, "lkt_replay_artifacts")

    def allowed_script_roots() -> list[Path]:
        roots = [Path(LKT_REPO).resolve(),                  # longinus.ROOT
                 Path(tempfile.gettempdir()).resolve(),
                 RA.replay_cache_root()]
        for part in os.environ.get("LAKATOS_SCRIPT_ROOTS", "").split(os.pathsep):
            part = part.strip()
            if part:
                try:
                    roots.append(Path(part).resolve())
                except OSError:
                    pass
        return roots

    SCRIPT_ROOTS = allowed_script_roots()

    def blocked_by_gate(p: str, field: str) -> bool:
        """서버가 이 (경로, 필드) 를 **루트 때문에** 막는가."""
        if field == "derivation":
            return not FH._within_raw_root(p)
        resolved = Path(p).resolve()
        return not any(r == resolved or r in resolved.parents for r in SCRIPT_ROOTS)

    # ── 오라클 sanity — 자명한 케이스를 못 가르면 채점 무효 ──────────────────
    sanity = [
        (not blocked_by_gate(MCP_SERVER_PY, "script"), "repo script 가 막히면 안 된다"),
        (blocked_by_gate("/etc/passwd", "script"), "/etc/passwd script 는 막혀야 한다"),
        (not blocked_by_gate("/tmp/x.py", "script"), "gettempdir script 는 허용돼야 한다"),
        (not blocked_by_gate(MCP_SERVER_PY, "derivation"), "raw root 안 source 는 허용"),
        (blocked_by_gate("/etc/passwd", "derivation"), "/etc/passwd source 는 막혀야 한다"),
        (blocked_by_gate("/tmp/x.json", "derivation"), "/tmp source 는 raw root 밖"),
    ]
    for ok, why in sanity:
        if not ok:
            return _fail(f"오라클 sanity 실패 — {why}")

    # ── 표본 존재 확인 ────────────────────────────────────────────────────
    missing = sorted({p for p, _f, req in SAMPLE if req and not os.path.exists(p)})
    if missing:
        return _fail(f"존재를 강제한 표본 경로가 없다: {missing}")

    # ── 채점 ──────────────────────────────────────────────────────────────
    def evaluate(roots: tuple) -> dict:
        false_warn, missed_warn, agree = [], [], []
        for p, field, _req in SAMPLE:
            warns = preflight_warns(p, roots)
            blocked = blocked_by_gate(p, field)
            item = f"{p} [{field}]"
            if warns and not blocked:
                false_warn.append(item)
            elif (not warns) and blocked:
                missed_warn.append(item)
            else:
                agree.append(item)
        return {"false_warning": false_warn, "missed_warning": missed_warn,
                "agree_n": len(agree),
                "disagreements": len(false_warn) + len(missed_warn)}

    pre_r, post_r = evaluate(pre), evaluate(post)
    baseline, value = pre_r["disagreements"], post_r["disagreements"]

    payload = {
        "seq": "D3", "replay_scorer": True,
        "metric": value,
        "metric_name": "preflight_vs_server_gate_disagreements",
        "baseline_pre_fix": baseline,
        "direction": "lower",
        "sample_n": len(SAMPLE),
        "fix_commit": FIX_COMMIT,
        "added_roots": list(added),
        "pre_channel": pre_channel,
        "oracle": {
            "env_channel": env_channel,
            "server_env": senv,
            "gate_A": "judgement_service.isolate_script_file (mirrored, source-sha pinned)",
            "gate_A_roots": [str(r) for r in SCRIPT_ROOTS],
            "gate_B": "server/file_hashing._within_raw_root (production import)",
            "gate_B_root": FH.raw_root(),
        },
        "pre": pre_r,
        "post": post_r,
        "note": ("양방향 지표 — false_warning 만 보면 화이트리스트로 0 을 만들 수 있다. "
                 "missed_warning 을 같이 세서 그 길을 막았다."),
    }

    # ── L2: result 경로는 read-only 일 수 있다 → best-effort ────────────────
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    for line in (
        f"baseline(pre)={baseline}  metric(post)={value}  sample_n={len(SAMPLE)}",
        f"  pre : false_warning={len(pre_r['false_warning'])} "
        f"missed_warning={len(pre_r['missed_warning'])}",
        f"  post: false_warning={len(post_r['false_warning'])} "
        f"missed_warning={len(post_r['missed_warning'])}",
        f"  post.false_warning  {post_r['false_warning']}",
        f"  post.missed_warning {post_r['missed_warning']}",
        f"  pre_channel={pre_channel} env_channel={env_channel}",
    ):
        print(line, file=sys.stderr)

    # ── 채점 정본 채널 = stdout 한 줄 ──────────────────────────────────────
    print(f"metric={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
