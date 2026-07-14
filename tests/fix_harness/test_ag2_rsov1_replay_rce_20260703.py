"""AG2/R-SOV-1 가드 — replay exec 경로의 RCE 봉합 (측정주권 PROM, 2026-07-03).

배경(정찰 wf_48a54c6b, 코드 실측): replay 실행 경로가 submit 이 쓰는 FF4 격리를 우회했다 —
`replay_command` 는 `f'python {judge_script} {result_path}'` 문자열을 만들고(둘 다 client 가 KG 에
넣은 값), `_replay_run` 은 shlex.split 후 그대로 subprocess 실행했다. 세 벡터가 열려 있었다:
① 스크립트 인자 격리 부재(_isolate_script_file 미경유) → 임의 절대경로/traversal 실행,
② `judge_script='-c'` → `python -c <result_path>` argv 인젝션(임의 코드), result_path flag 위장,
③ setrlimit 부재 → fork/mem/disk-DoS 가 timeout 만으론 안 막힘.
LAKATOS_REPLAY_EXEC 은 기본 OFF(dead path)라 지금 실피해는 없으나, GO1(exec 기본-ON)의 **절대
선행조건**이다. 봉합: server/app.py `_safe_replay_argv`(python 계열만·스크립트=허용루트 실존파일·
result_path flag 거부) + `_apply_replay_rlimits`(CPU/AS/FSIZE/CORE 유한 상한;
Darwin은 이미 매핑된 대형 공유 주소공간을 실측한 뒤 허용 growth를 더한다).

  guard_defect    = test_rce_vectors_are_rejected            (음성: 4벡터 실행 시 side-effect 없음·거부)
  guard_mechanism = test_honest_replay_runs_under_finite_rlimits (양성: 정직 스크립트 실행 + 자식 rlimit 유한)

노드의 novel_script = 이 파일 — mechanism 실재해야 progressive, revert-민감(격리/rlimit 떼면 RED).
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag2_rsov1_replay_rce
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _app():
    import importlib
    return importlib.import_module("server.app")


def test_rce_vectors_are_rejected():
    """음성 오라클: 4 RCE 벡터가 (a) side-effect 를 못 내고 (b) replay_error:unsafe_command 로 거부된다.
    revert-민감: _safe_replay_argv 의 격리를 떼면 sentinel 이 생겨 RED."""
    app = _app()
    tmp = tempfile.mkdtemp(prefix="ag2_")
    sentinel = os.path.join(tmp, "PWNED")
    real = os.path.join(tempfile.gettempdir(), "ag2_real_scorer.py")
    with open(real, "w") as f:
        f.write("print('metric=1.0')\n")

    # ① judge_script='-c' argv 인젝션: python -c <result_path> 로 임의 코드
    out1, code1 = app._replay_run(f"python -c import os;open('{sentinel}','w').write('x')")
    # ② result_path 를 python flag 로 위장(-c...)
    out2, code2 = app._replay_run(f"python {real} -cimport os;open('{sentinel}','w').write('y')")
    # ③ 허용 루트 밖 절대경로 스크립트
    out3, code3 = app._replay_run("python /etc/passwd")
    # ④ 비-python 실행파일
    out4, code4 = app._replay_run(f"/bin/sh -c touch\\ {sentinel}")

    assert not os.path.exists(sentinel), "RCE 벡터가 실행돼 side-effect 발생(격리 우회)"
    for out, code in ((out1, code1), (out2, code2), (out3, code3), (out4, code4)):
        assert code != 0 and out.startswith("replay_error:unsafe_command"), (out, code)


def test_honest_replay_runs_under_finite_rlimits():
    """양성 오라클: 허용 루트 내 실존 스크립트는 여전히 실행되고(하드닝이 정직 경로를 안 깬다),
    자식 프로세스는 유한 rlimit(memory/FSIZE/CPU) 하에서 돈다. revert-민감: preexec_fn 을 떼면
    자식이 RLIM_INFINITY 를 보고 아래 단언이 RED."""
    app = _app()
    probe = os.path.join(tempfile.gettempdir(), "ag2_rlimit_probe.py")
    with open(probe, "w") as f:
        f.write(
            "import resource\n"
            "memory, _ = resource.getrlimit(resource.RLIMIT_AS)\n"
            "fs, _ = resource.getrlimit(resource.RLIMIT_FSIZE)\n"
            "cpu, _ = resource.getrlimit(resource.RLIMIT_CPU)\n"
            "inf = resource.RLIM_INFINITY\n"
            "bounded = memory != inf and fs != inf and cpu != inf\n"
            "print('metric=%d' % (1 if bounded else 0))\n")
    out, code = app._replay_run(f"python {probe} ignored_arg")
    assert code == 0, (out, code)
    assert "metric=1" in out, f"자식이 유한 rlimit 을 못 봄(rlimit 미적용): {out!r}"

    # 하드닝이 정상 재현확인을 유지하는지 — 게이트 ON + 일치 → verified True (기존 계약 보존).
    def _node(mv, js, rp="ignored"):
        return {"judge_script": js, "metric_value": mv, "result_path": rp}
    scorer = os.path.join(tempfile.gettempdir(), "ag2_scorer.py")
    with open(scorer, "w") as f:
        f.write("print('metric=0.50')\n")
    import importlib
    monkey = importlib.import_module("_pytest.monkeypatch").MonkeyPatch()
    try:
        monkey.setenv("LAKATOS_REPLAY_EXEC", "1")
        monkey.setattr(app, "kg", lambda q, **p: [_node(0.50, scorer)], raising=False)
        assert app._producer_replay_for_node("t", "n") is True
        monkey.setattr(app, "kg", lambda q, **p: [_node(0.99, scorer)], raising=False)
        assert app._producer_replay_for_node("t", "n") is False   # 위조는 여전히 적발
    finally:
        monkey.undo()


# 이중 가드 export
guard_defect = "test_rce_vectors_are_rejected"
guard_mechanism = "test_honest_replay_runs_under_finite_rlimits"
