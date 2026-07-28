#!/usr/bin/env python3
"""L3 read-path 라이브 프로브 — 현행 엔진 판정 노드가 *영구 읽기 표면*에서 L3 로 재도출되는지.

P3 수술(2026-07-28, finding_d286e6ed37a462c1) 후 잔여 실증: 기존 트리들의 L3 는 봉인 판관
sha 가 floor 밖(구 엔진)이라 정직 L2 캡 — *현행* 엔진으로 full chain(anchored tier + attestor
write-cert + k-of-N temporal witness + 서버 replay + MeasurementLock)을 새로 세우면 읽기
표면(get_tree/standing)이 L3 을 재도출해야 한다. submit 응답 L3(구 주장)과 읽기 L3(신규)을
같은 노드에서 대조하는 것이 본 프로브의 목적.

★정직 경계(temporal.py 준수): attestor/witness 키는 이 프로브가 생성(solo box) — 메커니즘
실증이지 시각·서명의 진짜 외부성 실증이 아니다. 외부성은 키 소유 구조가 결정한다.

실행(LXC301 컨테이너에서 — 서버와 동일 체크아웃이라 model_dump 바이트 동일):
  LAKATOS_API_TOKEN=... .venv/bin/python scripts/probe_l3_readpath_live.py
산출: ooptdd_receipts/l3_readpath_probe_20260728/probe_evidence.json
# KG: plan-lktadv-p3-val-l3-readpath-20260728
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'unused-client-side')

from lakatos.temporal import build_temporal_anchor, spec_digest                    # noqa: E402
from lakatos.write_cert import build_write_cert, keygen, operation_payload_sha256  # noqa: E402
from server.contexts.tree.schemas import PredictionIn, TestResultIn                # noqa: E402

BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")
TOKEN = os.environ.get("LAKATOS_API_TOKEN", "")
RUN = os.environ.get("PROBE_RUN", "")
TREE = "LakatoTree_L3ReadProbe_20260728" + (f"_{RUN}" if RUN else "")
JUDGE_SCRIPT = "judges/engine_unify_vocab.py"   # 결정론 metric=0, 서버 체크아웃 실재
OUT = ROOT / "ooptdd_receipts" / "l3_readpath_probe_20260728" / "probe_evidence.json"
_ENVELOPE_KEYS = ("write_cert", "temporal_anchor", "temporal_anchors")


def _post(path: str, payload: dict) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:400]}


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    a_sec, a_did = keygen()      # attestor (submit write-cert 서명자)
    w1_sec, w1_did = keygen()    # temporal witness 2-of-2
    w2_sec, w2_did = keygen()
    now = datetime.now(timezone.utc).isoformat()
    evidence: dict = {"probe": "L3 read-path live (P3 수술 실증)", "tree": TREE, "server": BASE,
                      "generated_at": now, "attestor_did": a_did,
                      "witness_dids": [w1_did, w2_did],
                      "honesty_boundary": "solo box 키 자기생성 — 메커니즘 실증(외부성은 키 소유 구조 몫)",
                      "steps": []}

    def step(name, ok, **detail):
        evidence["steps"].append({"name": name, "ok": bool(ok), **detail})
        if not ok:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"FAIL at {name}: {detail}")
            raise SystemExit(1)

    # 1. anchored 트리 + attestor + 증인 2-of-2
    st, body = _post(f"/api/tree/{TREE}", {
        "title": "L3 read-path probe — 현행 엔진 full-chain 읽기 재도출 (P3 2026-07-28)",
        "hard_core": "LakatosGate + critique + replayability",
        "frontier_rule": "probe 종료 시 archive",
        "assurance_tier": "anchored", "attestor_dids": [a_did],
        "witness_dids": [w1_did, w2_did], "witness_threshold": 2,
    })
    step("tree_create_anchored", st in (200, 201), status=st, body=str(body)[:200])

    st, body = _post(f"/api/tree/{TREE}/node",
                     {"tag": "l3", "author": "l3-read-probe", "comment": "P3 read-path 실증 노드"})
    step("node_create", st in (200, 201), status=st)

    # 2. 예측 등록 (layout 미선언 → cert 불요) + 2-of-2 temporal anchor (T1=now ≤ T2)
    pred = PredictionIn(metric_name="probe_l3_roundtrip", direction="lower",
                        baseline_value=1.0, noise_band=0.0, scale_type="ratio")
    sd = {k: v for k, v in pred.model_dump().items() if k not in _ENVELOPE_KEYS}
    anchors = [build_temporal_anchor(bytes.fromhex(sec), spec_digest(sd), now, did)
               for sec, did in ((w1_sec, w1_did), (w2_sec, w2_did))]
    pred_payload = pred.model_dump(mode="json")
    pred_payload["temporal_anchors"] = anchors
    st, body = _post(f"/api/tree/{TREE}/node/l3/prediction", pred_payload)
    step("prediction_registered", st == 200 and body.get("pred_anchor_verified") is True,
         status=st, pred_anchor_verified=body.get("pred_anchor_verified"),
         quorum=body.get("pred_anchor_quorum"), body=str(body)[:200])
    pred_rsha = body.get("pred_receipt_sha")
    step("pred_receipt_minted", bool(pred_rsha), pred_receipt_sha=pred_rsha)

    # 3. 판정 제출 — attestor write-cert(v4 artifact binding) + 서버 replay(metric=0 결정론).
    #    result_path 는 서버 체크아웃의 커밋된 파일(SelfDev v20+ 관례 — replay 가 사본 봉인 후
    #    실행·재해시로 불변 검증). 빈 result_path 는 unsealed_result 로 replay 불가(r1 실측).
    RESULT_PATH = "CITATION.cff"
    script_sha = hashlib.sha256((ROOT / JUDGE_SCRIPT).read_bytes()).hexdigest()
    result_sha = hashlib.sha256((ROOT / RESULT_PATH).read_bytes()).hexdigest()
    result = TestResultIn(metric_value=0.0, script=JUDGE_SCRIPT, script_sha=script_sha,
                          result_path=RESULT_PATH)
    cert = build_write_cert(bytes.fromhex(a_sec), {
        "tree": TREE, "tag": "l3", "prev_receipt_sha": pred_rsha,
        "metric_value": 0.0, "script_sha": script_sha,
        "verb": "submit_test_result", "command_version": "v4",
        "operation_payload_sha256": operation_payload_sha256(
            "submit_test_result", result.model_dump(exclude={"write_cert"})),
        "result_sha256": result_sha,
    })
    submit_payload = result.model_dump(mode="json")
    submit_payload["write_cert"] = cert
    st, body = _post(f"/api/tree/{TREE}/node/l3/test_result", submit_payload)
    resp_assur = body.get("assurance") or {}
    step("submit_ok", st == 200, status=st, verdict=body.get("verdict"), body=str(body)[:300])
    step("submit_response_l3", resp_assur.get("val") == 3,
         assurance=resp_assur, verdict_display=body.get("verdict_display"))

    # 4. ★영구 읽기 표면 재도출 — P3 수술의 실증 본체
    td = _get(f"/api/tree/{TREE}")
    node = next((n for n in td.get("nodes", []) if n.get("tag") == "l3"), {})
    read_assur = node.get("assurance") or {}
    step("read_surface_get_tree_l3", read_assur.get("val") == 3,
         assurance=read_assur, verdict_display=node.get("verdict_display"),
         measurement_grade=node.get("measurement_grade"), replay=node.get("replay_status"))
    standing = _get(f"/api/tree/{TREE}/node/l3/standing")
    step("read_surface_standing_l3", (standing.get("assurance") or {}).get("val") == 3,
         assurance=standing.get("assurance"), verdict=standing.get("verdict"))

    evidence["result"] = "L3_ON_READ_SURFACES"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"result": evidence["result"],
                      "submit_l3": True, "get_tree_l3": True, "standing_l3": True,
                      "evidence": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
