"""verdict-provenance gate (bhgman_tool OQ1) — Lakatos 연구 프로그램 도그푸드.

★요점(euler 예제와 동일 규율): 노드는 verdict 를 *손입력하지 않는다*. 각 노드는 사전등록
Prediction + NovelTarget 만 들고, `run()` 이 **실제 bhgman_tool pytest receipt**(subprocess —
독립 측정, self-report 아님)에서 measured/novel_measured 를 *파생*해 `judge()` 가 verdict 를
*생성*한다. LakatoTree 의 하드코어("receipt only, self-report 거부")를 그 자신으로 도그푸드.

이 프로그램 자체가 그 원리의 사례다: bhgman 의 verdict-provenance gate 는 "위조/자기보고
verdict 로는 비가역 realize 불가"를 강제한다 = LakatoTree 의 `Rung.derived` 와 동형.

하드코어: **realize 는 authentic·unforgeable verdict 없이는 불가** (forge/self-report 거부).
보호대: HMAC 서명 · cycle/artifact 바인딩 · 1회용 ledger · selection 서명 · 비대칭 키.

문제이동(problemshift) 매핑 — 각 노드의 novel = red-team 이 *발견한* 위협을 닫음(lemma-incorporation):
  · hard_core            추측 확립(root, 채점 대상 아님)
  · hardened_symmetric   red-team 3렌즈(forge/keyless/replay)가 초안 우회 → 하드닝으로 봉쇄
  · persistent_ledger    [novel] 프로세스 재시작 후 replay → KG-backed ledger 로 봉쇄
  · selection_signing    [novel] verdictStatus 직접 위조(2nd trust point) → 노드 서명으로 봉쇄
  · asymmetric_ceiling   [novel] env-read in-process forger(대칭 HMAC 천장) → Ed25519 public-only 로 봉쇄

measured = 해당 위협 테스트의 *실패 수*(receipt 파생, 0=전부 green=봉쇄). baseline = 그 위협의
잠재 공격면(테스트 수; 게이트 부재 시 전부 뚫림). novel_measured = 그 라운드의 guard 테스트 통과(1.0).

# KG: adr-legion-runtime-shape-review-2026-06-20 (bhgman) / span_lakatotree_verdict_gate_dogfood
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_BHGMAN = "<WORKSPACE>/PROJECT/PI/bhgman_tool"
_GATE_TESTS = (
    "engine/legion/tests/test_verdict_gate.py "
    "engine/mcp_server/tests/test_hades_realize.py "
    "engine/mcp_server/tests/test_legion_tools.py "
    "engine/legion/tests/test_gated_run.py"
)


def receipt() -> dict[str, bool]:
    """외부 측정 = bhgman_tool 게이트 pytest 를 그 자신의 uv 로 실행(독립 venv·독립 프로젝트).

    Return {test_nodeid_tail: passed?}. self-report 아님 — judge 의 채점 입력이 되는 receipt."""
    cmd = (
        f"cd {_BHGMAN} && uv run --extra dev pytest {_GATE_TESTS} "
        f"-v --no-header -p no:cacheprovider 2>&1"
    )
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        # 테스트 *함수명*만 추출(클래스 접두사/파라미터 제거). 같은 함수의 파라미터는 AND 집계.
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


def _select(rc: dict[str, bool], needles: tuple[str, ...]) -> tuple[int, int]:
    """(공격면 total, 실패 수) — needle 부분일치 테스트 집합."""
    hit = [ok for name, ok in rc.items() if any(n in name for n in needles)]
    return len(hit), sum(1 for ok in hit if not ok)


def _guard(rc: dict[str, bool], name: str) -> float:
    """guard 테스트(그 라운드가 닫은 novel 위협)의 독립 측정 = 통과면 1.0."""
    return 1.0 if rc.get(name, False) else 0.0


@dataclass(frozen=True)
class GateNode:
    tag: str
    parent: str | None
    story: str
    threat_needles: tuple[str, ...] = ()
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_test: str = ""
    hard_core_preserved: bool = True


NODES: tuple[GateNode, ...] = (
    GateNode(
        tag="hard_core", parent=None,
        story="추측: realize 는 authentic·unforgeable verdict 없이는 불가 (self-report/forge 거부)",
    ),
    GateNode(
        tag="hardened_symmetric", parent="hard_core",
        story="red-team 3렌즈(forge/keyless/replay)가 초안 우회 → 하드닝으로 봉쇄(HMAC+positive PASS"
              "+freshness+artifact 바인딩+약키 hard-refuse)",
        threat_needles=("forged", "tampered", "foreign_key", "unsigned", "empty_verdict",
                        "weak_key", "from_env_dev_default", "from_env_empty", "from_env_absent",
                        "oracle_not_pass", "oracle_missing", "ensemble_reject", "cross_artifact",
                        "cycle_mismatch", "artifact_mismatch"),
        # 잠재 공격면 대비 *열린* 우회 수가 0(noise 0) 미만으로 떨어져야 improved
        prediction=Prediction(metric_name="open_bypass", direction="lower",
                              baseline_value=15.0, noise_band=0.0,
                              novel_prediction="keyless/public-default 키 fail-open 봉쇄",
                              closes_question="q-forge-keyless-replay"),
        novel_target=NovelTarget(metric_name="keyless_failopen_closed", direction="higher",
                                 threshold=1.0),
        guard_test="test_from_env_dev_default_refused",
    ),
    GateNode(
        tag="persistent_ledger", parent="hardened_symmetric",
        story="[novel] 프로세스 재시작 후 replay(in-memory ledger 의 구멍) → KG-backed :RealizedVerdict 로 봉쇄",
        threat_needles=("ledger", "consumed", "persists", "replay_refused_across_restart"),
        prediction=Prediction(metric_name="open_bypass", direction="lower",
                              baseline_value=5.0, noise_band=0.0,
                              novel_prediction="재시작-후 replay 봉쇄(영속 ledger)",
                              closes_question="q-restart-replay"),
        novel_target=NovelTarget(metric_name="restart_replay_closed", direction="higher",
                                 threshold=1.0),
        guard_test="test_gate_with_kg_ledger_replay_refused_across_restart",
    ),
    GateNode(
        tag="selection_signing", parent="hardened_symmetric",
        story="[novel] verdictStatus='ACCEPTED' 직접 위조(2nd trust point) → selection-node HMAC 서명으로 봉쇄",
        threat_needles=("selection", "require_signed_selection", "acceptedstatus"),
        prediction=Prediction(metric_name="open_bypass", direction="lower",
                              baseline_value=6.0, noise_band=0.0,
                              novel_prediction="selection 노드 직접 위조 봉쇄",
                              closes_question="q-selection-forgery"),
        novel_target=NovelTarget(metric_name="selection_forgery_closed", direction="higher",
                                 threshold=1.0),
        guard_test="test_forged_acceptedstatus_unsigned_refused",
    ),
    GateNode(
        tag="asymmetric_ceiling", parent="hardened_symmetric",
        story="[novel] env-read in-process forger(대칭 HMAC 구조적 천장) → Ed25519 consumer public-only 로 봉쇄",
        threat_needles=("asymmetric", "public_only", "ceiling", "foreign_keypair"),
        prediction=Prediction(metric_name="open_bypass", direction="lower",
                              baseline_value=7.0, noise_band=0.0,
                              novel_prediction="consumer 가 public-only → sign 불가(env-read forger 봉쇄)",
                              closes_question="q-symmetric-hmac-ceiling"),
        novel_target=NovelTarget(metric_name="inprocess_forger_closed", direction="higher",
                                 threshold=1.0),
        guard_test="test_public_only_cannot_sign_closes_ceiling",
    ),
)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — 각 노드 verdict 를 judge() 가 *생성*. measured 는 receipt 파생, 손입력 0."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES:
        if n.prediction is None:
            out.append(dict(tag=n.tag, verdict="canonical_stage", metric_verdict=None,
                            open_bypass=None, attack_surface=None, novel=None))
            continue
        surface, failures = _select(rc, n.threat_needles)
        novel_measured = _guard(rc, n.guard_test) if n.novel_target else None
        v = judge(n.prediction, float(failures), n.novel_target, novel_measured)
        out.append(dict(
            tag=n.tag,
            verdict=v.verdict,            # ★judge 생성 — 손입력 아님
            metric_verdict=v.verdict,
            improved=v.improved, novel=v.novel,
            open_bypass=failures,         # 실제 실패(열린 우회) 수 — receipt 파생
            attack_surface=surface,       # 그 위협을 지키는 테스트 수
            novel_guard=n.guard_test,
            reason=v.reason,
        ))
    return out


if __name__ == "__main__":
    rc = receipt()
    passed = sum(1 for ok in rc.values() if ok)
    print(f"receipt: {passed}/{len(rc)} gate tests PASSED (bhgman_tool uv, 독립 측정)\n")
    for r in run(rc):
        sfx = (f"open_bypass={r['open_bypass']}/{r['attack_surface']}  novel={r.get('novel')}"
               if r["open_bypass"] is not None else "(root)")
        print(f"{r['tag']:20} → {r['verdict']:14} {sfx}")
