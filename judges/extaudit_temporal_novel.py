#!/usr/bin/env python3
"""EXTAUDIT S7 novel 채점기 — VAL L3 이 유효한 양끝 증인일 때만 열리고 아니면 안 열리는가 (in-process).

독립 결과(주 메트릭=테스트 가드와 별개 인과): 실제 Ed25519 증인으로 양끝 앵커를 발행/검증해
has_valid_temporal_witness 를 구동하고, 그 결과를 verdict_assurance 의 temporal_witness 로 흘려
L3 개방을 확인한다. 동시에 백데이트/무증인은 L3 를 안 여는지(과잉 개방 방지).

metric = 1 ⇔ (유효 증인→L3) ∧ (백데이트→L2) ∧ (무증인→L2) 셋 다 / 0 ⇔ 아니면 / -1 ⇔ 예외.
stdout `metric=<int>` + exit 0. in-process(라이브 sidecar persistence 는 S7b) — 순수 커널 e2e.
"""
import sys

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[1].as_posix())
from lakatos.temporal import build_temporal_anchor, has_valid_temporal_witness   # noqa: E402
from lakatos.verdicts import verdict_assurance                                    # noqa: E402
from lakatos.write_cert import did_key_encode, ed25519_public_key                 # noqa: E402

_W = bytes([210]) * 32
WDID = did_key_encode(ed25519_public_key(_W))


def _val(tw):
    row = dict(verdict="progressive", verdict_source="scripted", current_receipt_sha="r1",
               measurement_grade="server_regenerated", replay_status="verified",
               assurance_tier_resolved="anchored", attested_by_did=WDID, engine_rule_sha="e1")
    return verdict_assurance(row, tree_attestors=[WDID], engine_rule_floor=frozenset({"e1"}),
                             temporal_witness=tw)["val"]


def probe() -> int:
    try:
        pa = build_temporal_anchor(_W, "predsha", "2026-07-23T02:00:00+00:00", WDID)
        va = build_temporal_anchor(_W, "vsha", "2026-07-23T02:00:05+00:00", WDID)
        va_back = build_temporal_anchor(_W, "vsha", "2026-07-23T01:59:00+00:00", WDID)
        valid = has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha",
                                           verdict_receipt_sha="vsha", witness_allowlist=[WDID])
        backdated = has_valid_temporal_witness(pa, va_back, pred_receipt_sha="predsha",
                                               verdict_receipt_sha="vsha", witness_allowlist=[WDID])
        no_witness = has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha",
                                                verdict_receipt_sha="vsha", witness_allowlist=[])
        ok = (valid and _val(valid) == 3
              and not backdated and _val(backdated) == 2
              and not no_witness and _val(no_witness) == 2)
        return 1 if ok else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
