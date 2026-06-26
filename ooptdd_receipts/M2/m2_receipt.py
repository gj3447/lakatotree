"""OOPTDD emit-adapter — LakatoTree 설계감사 M2(채점거부 fail-loud)를 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진(lakatos/harness.py)이 아니라 이 adapter 의 verify 본문에만 등장한다.
verify 가 실제 lakatos.harness.LakatoHarness.run_cycle 을 *구동*(재구현 금지)하고, 관측한 사실을
구조화 이벤트로 ship 한다. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

음성 오라클(no-fake-green): M2 결함이 살아있었다면(서버 채점거부를 조용히 삼켜 verdict=None 인데
exit 0+stands=True 로 green) 음성 케이스(scoring_refused_on_reject)는 *틀린다* — ScoringRefused 가
안 올라오므로 pytest.raises 가 실패하고, 이벤트가 ship 되지 않아 게이트가 미충족이 된다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.harness import LakatoHarness, CycleSpec, ScoringRefused   # noqa: E402  (실제 엔진 import — 재구현 아님)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M2", "event": name, **attrs}


# test_design_audit_m2._harness 와 동일한 mock 하네스 (test_result POST 응답만 주입).
def _harness(test_result_resp):
    calls = []

    def run_bash(cmd):
        calls.append(("bash", cmd))
        if "build" in cmd or "pytest" in cmd:
            return ("... 49 passed", 0)              # 하계: TDD/빌드 green
        return ("metric=49", 0)                      # 하계: 채점 스크립트

    def http(method, path, body=None):
        calls.append((method, path))
        if path.endswith("/prediction"):
            return {"ok": True}
        if path.endswith("/test_result"):
            return test_result_resp                  # ← 채점거부/verdict 없음/정상 주입
        if path.endswith("/standing"):
            return {"stands": True, "grounded_extension": ["verdict:x"]}
        return {"ok": True}

    def git_sha():
        return "abc1234"

    return LakatoHarness(http=http, run_bash=run_bash, read_internet=None, git_sha=git_sha)


_SPEC = CycleSpec(tree="T", tag="v7", parent="v6", metric="tests", baseline=34,
                  direction="higher", build_cmd="pytest tests/ -q",
                  judge_cmd="python judges/count.py", judge_script="judges/count.py")


def verify(backend, cid):
    """M2 채점게이트 구동 — 실제 LakatoHarness.run_cycle 을 mock 포트로 돌려 두 경계를 증언.

    (음성 오라클) 서버가 채점을 거부(error 키)하거나 verdict 가 None 이면 run_cycle 이 ScoringRefused
    를 raise 해 가짜 green 을 차단한다 → scoring_refused_on_reject.
    (양성 대조) 정상 verdict 응답이면 run_cycle 이 그 verdict 를 담은 prov 를 정상 반환한다 →
    green_cycle_ok.
    """
    # ── (1) 음성 오라클: 채점거부(error)·verdict 부재·verdict=None 세 경계 모두 ScoringRefused.
    #        결함이 살아있었다면(조용히 삼킴) raise 가 안 올라와 이 블록이 실패 → 이벤트 미ship → 게이트 적색.
    refused = []

    # ① 채점거부: harness_run._http 가 HTTPError(422)를 {'error': code, ...} dict 로 반환.
    h1 = _harness({"error": 422, "detail": "admissibility 위반: novel 독립측정 없음"})
    try:
        h1.run_cycle(_SPEC)
        raise AssertionError("결함 회귀: error=422 채점거부를 삼켜 green 으로 끝남(ScoringRefused 미발생)")
    except ScoringRefused as e:
        refused.append(("error422", str(e)[:60]))

    # ② verdict 키 부재(200 이지만 채점 미성립).
    h2 = _harness({"ok": True, "novel": None, "delta": None})
    try:
        h2.run_cycle(_SPEC)
        raise AssertionError("결함 회귀: verdict 키 부재를 삼켜 green 으로 끝남")
    except ScoringRefused as e:
        refused.append(("verdict_absent", str(e)[:60]))

    # ③ verdict=None 명시 응답.
    h3 = _harness({"ok": True, "verdict": None})
    try:
        h3.run_cycle(_SPEC)
        raise AssertionError("결함 회귀: verdict=None 을 삼켜 green 으로 끝남")
    except ScoringRefused as e:
        refused.append(("verdict_none", str(e)[:60]))

    assert len(refused) == 3, refused
    backend.ship([_ev(cid, "scoring_refused_on_reject",
                      cases=[c for c, _ in refused], n_refused=len(refused))])

    # ── (2) 양성 대조: 정상 verdict 응답이면 run_cycle 이 ScoringRefused 없이 verdict 를 반환.
    #        ScoringRefused 가 *모든* 채점을 거부하는 게 아님(거짓 양성 아님)을 증언 — fail-loud 의 비대칭이
    #        오직 거부/미성립에만 작동함을 양성 대조로 닫는다.
    h_ok = _harness({"ok": True, "verdict": "progressive", "novel": False, "delta": 15})
    prov = h_ok.run_cycle(_SPEC)
    assert prov.get("verdict") == "progressive", prov
    assert prov.get("standing", {}).get("stands") is True, prov
    assert "scoring_refused" not in prov, prov   # 정상 경로엔 거부 기록 없음
    backend.ship([_ev(cid, "green_cycle_ok",
                      verdict=prov["verdict"], stands=prov["standing"]["stands"],
                      git_sha=prov.get("git_sha"))])
