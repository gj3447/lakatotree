#!/usr/bin/env python3
r"""replay 4층 처방 — **층별 넉아웃(knockout) 필요성 채점기**.

## 무엇을 재나

2026-07-29 에 LX3 하네스가 라카토트리에서 처음으로 `measurement_grade=server_regenerated`
(= assurance L2, replay_verified)를 받았다. 그 통과한 스코어러에 붙어 있던 것이 **4층 처방**이다:

  L1 인터프리터 재실행 shim   — 서버 sys.executable 에 numpy 가 없다
  L2 result read-only 관용     — 서버가 넘기는 result 스냅샷은 mode 0400 이다
  L3 numpy import 전 BLAS=1    — 샌드박스 RLIMIT_AS 2048MB 아래서 OpenBLAS 가 VmSize 를 터뜨린다
  L4 절대경로 고정             — 서버가 스크립트를 content-addressed 디렉터리로 **복사**해 실행한다

"처방을 지켰더니 통과했다"는 **각 층이 실제로 필요하다**는 뜻이 아니다. 넷 다 걸어놓고
한 번 통과한 것은 넷 중 하나만 진짜였어도 똑같이 보인다. 그래서 여기서는 **한 층씩 빼고**
배포 조건 그대로 재실행해, 몇 개 층이 실제로 계약을 깨뜨리는지를 센다.

    metric = replay_prescription_layers_proven_necessary  (0..4, 높을수록 처방이 실측으로 지탱됨)

## 배포 조건(모든 arm 공통 — 서버 실동작에서 확인한 값)

  · 인터프리터 = /data/kjra/PROJECT/PI/lakatotree/.venv/bin/python  (server/app.py `_safe_replay_argv`
    가 `[sys.executable, script, result]` 로 실행. 실측: 3.14.4, numpy 없음)
  · 스크립트는 원 위치가 아니라 복사본에서 실행 (lakatos/replay_artifacts.py `materialize_snapshot`,
    실측 `~/.local/state/lakatotree/replay-artifacts/v1/script/<sha>.py`, mode 0400)
  · result 스냅샷도 mode 0400 (같은 파일, kind='result')
  · RLIMIT_AS = 2048MB (server/app.py `_replay_rlimits`, LAKATOS_REPLAY_AS_MB **기본값**)
  · 채점 정본 채널 = stdout 의 `metric=` (lakatos/io/rebuild.py `_parse_metric`)

## ★지표 범위 단서 — 그냥 넘기면 과대주장이 된다

`~/.config/lakatotree/server.env` 는 2026-07-28 에 `LAKATOS_REPLAY_AS_MB=24576` 으로
**상향돼 있고**, 지금 도는 서버(pid 기동 2026-07-28 13:51)가 그 env 로 떠 있다. 즉 07-29 의
L2 통과는 2048MB 가 아니라 **24GiB 상한 아래에서** 일어났다 — L3 가 그 통과에 실제로
쓰였다는 보장이 없다. 그래서 지표는 **계약 기본값(2048MB)** 에서의 필요성으로 고정하고,
현 배포 상한(24576MB)에서의 L3 는 `diagnostics` 로 분리해 따로 보고한다(지표 불포함).
전자는 코드 상수라 어디서 돌려도 같고, 후자는 부모 hard 상한이 허용할 때만 측정된다.

## 자기반증 가드 (이게 없으면 넉아웃은 공허하다)

  G1 원본 sha 앵커  — 대상 스크립트가 영수증에 핀된 sha 가 아니면 즉시 실패
  G2 뮤테이션 적중  — 각 층 제거가 텍스트를 실제로 바꿨는지 치환 횟수로 확인(무음 no-op 금지)
  G3 뮤턴트 컴파일  — 모든 뮤턴트가 py_compile 을 통과해야 한다. 실패가 **문법이 아니라 환경**임을 보증
  G4 CONTROL 앵커   — 4층 다 켠 arm 이 배포 조건에서 정확히 0.1775 를 내야 한다. 아니면 채점 무효
  G5 SHAM 음성대조  — 무해한 주석 한 줄만 바꾼 뮤턴트는 **통과해야** 한다. 이게 깨지면 이 채점기는
                      "건드리면 무조건 깨진다"를 재는 공허한 장치이고, 넉아웃 4/4 는 의미가 없다

## 이 채점기 자신의 4층 준수

  L1 불필요(표준 라이브러리만 씀 — 서버 python 에서 그대로 돈다) · L2 준수(result 쓰기 best-effort)
  L3 불필요(numpy 를 import 하지 않는다) · L4 준수(`__file__` 을 한 번도 쓰지 않는다)

사용: python replay_layer_necessity_scorer_20260729.py [result.json]
출력: stdout 한 줄 `metric=<필요성이 실측된 층 수>`  (그 밖 진단은 전부 stderr)
"""
from __future__ import annotations

import hashlib
import json
import os
import py_compile
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

# ── L4: 절대경로 고정. __file__ 은 쓰지 않는다 ──────────────────────────────
TARGET = "/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC/scripts/harness411_replay_scorer_20260729.py"
TARGET_SHA = "feb6ee34d176210ce28ddafa2103e451a5f5c0efae60671d9f9cae0b64dd5930"
SERVER_PY = "/data/kjra/PROJECT/PI/lakatotree/.venv/bin/python"

CONTRACT_AS_MB = 2048    # server/app.py `_replay_rlimits` 의 LAKATOS_REPLAY_AS_MB **기본값**(코드 상수)
LIVE_AS_MB = 24576       # 2026-07-28 운영자가 ~/.config/lakatotree/server.env 로 올린 **현 배포값**
AS_CAP_BYTES = CONTRACT_AS_MB * 1024 * 1024
ARM_TIMEOUT_S = 240
CONTROL_METRIC = 0.1775                # 봉인 영수증 regenerated_metric
BLAS_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")

# ── 층별 넉아웃 = 원본 텍스트 치환. (층, 설명, [(old, new, 기대 치환수)], 기대 실패지문) ──
L1_BLOCK = '''if os.environ.get("_LKT_REEXEC") != "1":
    try:
        import numpy  # noqa: F401
    except Exception:
        os.environ["_LKT_REEXEC"] = "1"
        _self = os.path.abspath(__file__)
        os.execv(TARGET_PY, [TARGET_PY, _self] + sys.argv[1:])
'''

L2_BLOCK = '''        try:
            Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        except OSError:
            pass
'''
L2_NEW = '''        Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
'''

L3_BLOCK = '''for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"
'''

L4_OLD = 'REPO = "/data/kjra/PROJECT/3DLAB/LX3_ICP_SPEC"\n'
L4_NEW = ('import pathlib as _pl  # noqa: E402\n'
          'REPO = str(_pl.Path(__file__).resolve().parents[1])\n')

KNOCKOUTS = [
    ("NO_L1_interpreter_shim",
     "인터프리터 재실행 shim 제거 — 서버 python 에 numpy 가 없다",
     [(L1_BLOCK, "", 1)],
     ("No module named", "ModuleNotFoundError")),
    ("NO_L2_readonly_result_tolerance",
     "result 쓰기 try/except 제거 — 서버 result 스냅샷은 mode 0400",
     [(L2_BLOCK, L2_NEW, 1)],
     ("PermissionError", "Errno 13", "Read-only")),
    ("NO_L3_blas_thread_pin",
     "numpy import 전 BLAS THREADS=1 제거 — RLIMIT_AS 2048MB",
     [(L3_BLOCK, "", 1)],
     ("MemoryError", "Unable to allocate", "Cannot allocate", "cannot allocate",
      "ImportError", "OpenBLAS", "libgomp", "Killed")),
    ("NO_L4_absolute_paths",
     "REPO 절대경로를 __file__ 상대로 — 서버는 복사본을 실행한다",
     [(L4_OLD, L4_NEW, 1)],
     ("FileNotFoundError", "로드 불가", "No such file")),
]

# ── G5 음성대조: 거동에 닿지 않는 주석 한 줄만 바꾼다. 이 arm 은 **통과해야** 한다 ──
SHAM_OLD = "    # ── 채점 정본 채널 = stdout 한 줄 ──────────────────────────────────────\n"
SHAM_NEW = "    # ── SHAM 음성대조: 주석만 바꾼 뮤턴트 (거동 불변이어야 한다) ──\n"


def _die(msg: str) -> None:
    print(f"FAIL-LOUD: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cap_settable(cap_bytes: int) -> bool:
    """요청한 상한을 자식에 **정확히** 걸 수 있나. 부모 hard 가 낮으면 못 건다(무음 강등 금지)."""
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    return hard == resource.RLIM_INFINITY or hard >= cap_bytes


def _limits_factory(cap_bytes: int):
    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (cap_bytes, cap_bytes))
    return _apply


def _child_env() -> dict:
    """BLAS 변수를 환경에서 **제거** — 스레드 고정의 유일한 출처가 스크립트 자신이 되게."""
    env = dict(os.environ)
    for v in (*BLAS_VARS, "_LKT_REEXEC"):
        env.pop(v, None)
    return env


def _stage(root: Path, name: str, source: str) -> Path:
    """서버 artifact 레이아웃을 흉내내 복사 — 원 위치가 아닌 곳에서 실행한다."""
    d = root / name / "replay-artifacts" / "v1" / "script"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_sha(source)}.py"
    p.write_text(source)
    p.chmod(0o400)
    return p


def _readonly_result(root: Path, name: str) -> Path:
    p = root / name / "result.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"snapshot": "server-owned read-only copy"}')
    p.chmod(0o444)
    return p


def _run_arm(script: Path, result: Path, cap_bytes: int = AS_CAP_BYTES) -> dict:
    try:
        p = subprocess.run([SERVER_PY, str(script), str(result)],
                           capture_output=True, text=True, timeout=ARM_TIMEOUT_S,
                           env=_child_env(), preexec_fn=_limits_factory(cap_bytes))
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, err, code = "", "TimeoutExpired", 124
    metric = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("metric="):
            try:
                metric = float(line.split("=", 1)[1])
            except ValueError:
                metric = None
    return {"exit_code": code, "metric": metric,
            "stderr_tail": (err or "")[-400:], "stdout_len": len(out)}


def main() -> int:
    src_path = Path(TARGET)
    if not src_path.is_file():
        _die(f"대상 스크립트 없음 {TARGET}")
    source = src_path.read_text()
    # G1 — 영수증에 핀된 sha 가 아니면 이 넉아웃 집합은 정의되지 않는다
    got = _sha(source)
    if got != TARGET_SHA:
        _die(f"대상 sha 불일치 {got} != {TARGET_SHA}")
    if not Path(SERVER_PY).is_file():
        _die(f"서버 인터프리터 없음 {SERVER_PY}")
    if not _cap_settable(AS_CAP_BYTES):     # 무음 강등 금지 — 계약 상한을 못 걸면 채점 무효
        _die(f"RLIMIT_AS 를 {CONTRACT_AS_MB}MB 로 걸 수 없다(부모 hard 가 더 낮다)")

    arms: list[dict] = []
    diagnostics: list[dict] = []
    l3_mutant: str | None = None
    with tempfile.TemporaryDirectory(prefix="replay-knockout-") as tmp:
        root = Path(tmp)

        # ── CONTROL: 4층 전부 켠 채 배포 조건 그대로 ──────────────────────
        ctl_script = _stage(root, "control", source)
        ctl_result = _readonly_result(root, "control")
        ctl = _run_arm(ctl_script, ctl_result)
        ctl.update(arm="CONTROL", layer=None, mutated=False, compiles=True,
                   desc="4층 전부 적용 — 배포 조건(서버 python + 복사본 + read-only result + RLIMIT_AS 2048MB)")
        arms.append(ctl)

        # G4 — CONTROL 이 봉인값을 못 내면 채점 자체가 무효다
        if ctl["exit_code"] != 0 or ctl["metric"] is None or abs(ctl["metric"] - CONTROL_METRIC) > 1e-9:
            print(json.dumps({"arms": arms}, ensure_ascii=False, indent=1), file=sys.stderr)
            _die(f"CONTROL 앵커 실패 exit={ctl['exit_code']} metric={ctl['metric']} != {CONTROL_METRIC}")

        # ── 층별 넉아웃 ───────────────────────────────────────────────────
        for name, desc, edits, signature in KNOCKOUTS:
            mutant = source
            for old, new, want in edits:
                hit = mutant.count(old)
                if hit != want:                       # G2 — 무음 no-op 뮤테이션 금지
                    _die(f"{name}: 치환 대상 {hit}회 발견, {want}회 기대")
                mutant = mutant.replace(old, new)
            if mutant == source:
                _die(f"{name}: 뮤테이션이 텍스트를 바꾸지 못했다")
            if name.startswith("NO_L3"):
                l3_mutant = mutant
            script = _stage(root, name, mutant)
            compiles = True
            try:                                      # G3 — 실패가 문법 탓이 아님을 보증
                py_compile.compile(str(script), cfile=str(root / name / "chk.pyc"),
                                   doraise=True)
            except py_compile.PyCompileError as exc:
                compiles = False
                _die(f"{name}: 뮤턴트가 컴파일되지 않는다 — 넉아웃 무효 ({exc})")
            res = _run_arm(script, _readonly_result(root, name))
            broke = (res["exit_code"] != 0 or res["metric"] is None
                     or abs(res["metric"] - CONTROL_METRIC) > 1e-9)
            blob = (res["stderr_tail"] or "")
            res.update(arm=name, layer=name.split("_")[1], desc=desc, mutated=True,
                       compiles=compiles, mutant_sha256=_sha(mutant),
                       contract_broken=broke,
                       signature_expected=list(signature),
                       signature_match=any(s in blob for s in signature))
            arms.append(res)

        # ── 진단 arm: L3 를 **현 배포 상한(24576MB)** 에서 다시 — 지표에는 넣지 않는다 ──
        #    2026-07-28 운영자가 기본 2048MB 를 24576MB 로 올렸다. 그러면 OpenBLAS 의 VmSize 가
        #    들어가므로 L3 는 *현 서버에서는* 놀고 있을 수 있다. 그건 처방의 이식성 문제지
        #    계약 기본값에서의 필요성 문제가 아니라, 지표에서 분리해 따로 보고한다.
        live_cap = LIVE_AS_MB * 1024 * 1024
        diag = {"arm": "NO_L3_blas_thread_pin@LIVE_CAP", "as_mb": LIVE_AS_MB,
                "excluded_from_metric": True,
                "why": "운영자 override(~/.config/lakatotree/server.env, 2026-07-28)"}
        if l3_mutant is None:
            diag["measurable"] = False
            diag["reason"] = "L3 뮤턴트 부재"
        elif not _cap_settable(live_cap):
            diag["measurable"] = False
            diag["reason"] = f"부모 RLIMIT_AS hard 가 {LIVE_AS_MB}MB 미만 — 이 실행에서는 못 잰다"
        else:
            d_script = _stage(root, "diag_l3_live", l3_mutant)
            d_res = _run_arm(d_script, _readonly_result(root, "diag_l3_live"), cap_bytes=live_cap)
            d_broke = (d_res["exit_code"] != 0 or d_res["metric"] is None
                       or abs(d_res["metric"] - CONTROL_METRIC) > 1e-9)
            diag.update(measurable=True, contract_broken=d_broke, **d_res)
        diagnostics.append(diag)

        # ── G5 SHAM 음성대조 ──────────────────────────────────────────────
        if source.count(SHAM_OLD) != 1:
            _die("SHAM: 음성대조 치환 대상이 정확히 1회가 아니다")
        sham_src = source.replace(SHAM_OLD, SHAM_NEW)
        sham_script = _stage(root, "SHAM_comment_only", sham_src)
        py_compile.compile(str(sham_script), cfile=str(root / "SHAM_comment_only" / "chk.pyc"),
                           doraise=True)
        sham = _run_arm(sham_script, _readonly_result(root, "SHAM_comment_only"))
        sham_broke = (sham["exit_code"] != 0 or sham["metric"] is None
                      or abs(sham["metric"] - CONTROL_METRIC) > 1e-9)
        sham.update(arm="SHAM_comment_only", layer=None, mutated=True, compiles=True,
                    mutant_sha256=_sha(sham_src), contract_broken=sham_broke,
                    desc="음성대조 — 주석 한 줄만 치환. 통과해야 정상",
                    negative_control=True)
        arms.append(sham)
        if sham_broke:
            print(json.dumps({"arms": arms}, ensure_ascii=False, indent=1), file=sys.stderr)
            _die("SHAM 음성대조가 깨졌다 — 이 채점기는 '건드리면 깨진다'를 재는 공허한 장치다")

    necessary = [a for a in arms
                 if a.get("contract_broken") and not a.get("negative_control")]
    value = float(len(necessary))
    payload = {
        "scorer": "replay_layer_necessity_20260729",
        "metric_name": "replay_prescription_layers_proven_necessary",
        "metric": value,
        "of_layers": len(KNOCKOUTS),
        "target_script": TARGET,
        "target_sha256": TARGET_SHA,
        "metric_scope": (f"계약 기본 sandbox(RLIMIT_AS {CONTRACT_AS_MB}MB). "
                         f"현 서버는 {LIVE_AS_MB}MB 로 상향돼 있어 L3 는 diagnostics 로 분리 보고."),
        "deploy_conditions": {
            "interpreter": SERVER_PY,
            "rlimit_as_mb": CONTRACT_AS_MB,
            "rlimit_as_bytes": AS_CAP_BYTES,
            "script_relocated": True,
            "result_mode": "0444",
            "blas_env_stripped": list(BLAS_VARS),
        },
        "control_metric": arms[0]["metric"],
        "negative_control_passed": True,   # G5 — 여기 오면 SHAM 은 통과한 것(아니면 위에서 죽었다)
        "layers_necessary": [a["arm"] for a in necessary],
        "layers_not_necessary": [a["arm"] for a in arms
                                 if a.get("mutated") and not a.get("negative_control")
                                 and not a.get("contract_broken")],
        "signature_mismatches": [a["arm"] for a in arms
                                 if a.get("mutated") and not a.get("negative_control")
                                 and a.get("contract_broken") and not a.get("signature_match")],
        "arms": arms,
        "diagnostics": diagnostics,
    }

    # ── L2: result 경로는 read-only 일 수 있다 → best-effort ──────────────
    if len(sys.argv) > 1:
        try:
            Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        except OSError:
            pass

    # 진단은 전부 stderr — stdout 의 첫 metric= 이 정본이어야 한다(_parse_metric 은 첫 매치를 쓴다)
    print(json.dumps(payload, ensure_ascii=False, indent=1), file=sys.stderr)
    print(f"metric={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
