"""Judge Proprioception — 판관을 content-address 하라 (통시적 자기정체성).

deep-think 2026-07-08 (workflow wf_cf7ca993-336, 30 agent, 확정 12 / 반증 2) 의 PROM 등재 하네스.
KG 거울: LakatosTree_JudgeProprioception_20260708  (부모 계보: LakatosTree_ManifestoGap_20260702).

────────────────────────────────────────────────────────────────────────────
테제(hard core): 엔진은 '재유도가 판관, 캐시 불신' 을 자기 외 *모든* 연구프로그램에 강제하나 —
  ① 영수증(RECEIPT_FIELDS)이 판관 정체성(engine_rule_sha)을 봉인하지 않고
  ② 어떤 읽기 경로도 stored receipt_sha 를 content 로부터 재유도(recompute)해 검증하지 않는다.
  ⇒ content-addressing 은 mint-time 의식이지 verification 계약이 아니다. 엔진에겐 통시적 self 가 없다.
  다섯 서브시스템 딥싱크가 서로 다른 곳에서 이 한 점으로 수렴 → 이것이 캠페인.

★규율(no fake green): stale 엔진(:55170 = 1845b4e, disk 보다 30커밋 뒤)에 progressive 제출 금지.
  이 하네스는 in-process(disk 코드)로 돌아 stale 서버를 우회하고, 예측을 *잠그되* 채점하지 않는다.
  각 fix 노드는 RED-first: guard_mechanism(양성오라클)이 disk 실측 0 → 전부 pending.
  대신 anomaly 를 *실행 데모*로 재현(주장 아님) — 예측이 겨누는 결함이 지금 살아있음을 증명한다.
  fix 가 착륙하면 같은 하네스 재실행 시 실측이 1 로 flip → MECHANISM DETECTED 배너(revert-sensitive).

이중가드 4-칸(측정주권 programme 규약과 동형):
  둘다닫힘→progressive · defect만→partial · mech만→equivalent · 둘다미착륙→pending
────────────────────────────────────────────────────────────────────────────
쓰임:  .venv/bin/python examples/judge_proprioception_20260708_programme.py
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from lakatos import verdicts as V                    # RECEIPT_FIELDS, fold_receipt_chain, receipt_content_sha
from lakatos.verdict.judge import Prediction, judge  # 엔진 판결 커널 (verdict 손입력 금지 — 전부 judge() 생성)

_TREE = "LakatosTree_JudgeProprioception_20260708"


def _read(rel: str) -> str:
    try:
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# ── 실행 데모: 결함이 *지금* 살아있음을 재현한다 (주장이 아니라 running proof) ─────────

_GENESIS = {
    "tree": _TREE, "tag": "demo", "target_id": "demo",
    "verdict": "progressive", "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
    "novel_confirmed": True, "lakatos_status": "progressive", "judged_at": "2026-07-08T00:00:00+00:00",
    "judge_script_sha": "0" * 64, "measurement_grade": "client_asserted",
}


def _mk_receipt(fields: dict, prev_sha) -> dict:
    f = dict(fields, prev_receipt_sha=prev_sha)
    return {**f, "receipt_sha": V.receipt_content_sha(f)}


def demo_tamper_invisible() -> dict:
    """실 영수증 체인을 만들고 head verdict 를 in-place 변조(receipt_sha 는 그대로) →
    fold_receipt_chain 이 변조된 verdict 를 예외 없이 반환. stored sha 를 dict key 로 신뢰(verdicts.py:292),
    content 로부터 재유도하지 않음 ⇒ 원장우회/in-place 위조가 fold 에 불가시.
    (jp3 이 겨누는 결함의 running proof.)"""
    genesis = _mk_receipt(_GENESIS, None)
    head = _mk_receipt(dict(_GENESIS, tag="head"), genesis["receipt_sha"])
    chain = [genesis, head]

    honest = V.fold_receipt_chain(chain, head["receipt_sha"])
    stored_sha = head["receipt_sha"]

    head["verdict"] = "CANONICAL"                      # 변조: verdict 뒤집되 sha 는 손대지 않음
    tampered = V.fold_receipt_chain(chain, stored_sha)  # 예외 없이 변조값 반환?
    recomputed = V.receipt_content_sha(head)            # 변조 후 content 로부터 재유도한 sha

    return {
        "honest_verdict": honest["verdict"],
        "tampered_verdict": tampered["verdict"],
        "tamper_invisible": tampered["verdict"] == "CANONICAL" and tampered.get("from_receipt"),
        "stored_sha_now_wrong": recomputed != stored_sha,   # stored 는 이제 content 와 불일치, 그러나 fold 는 확인 안 함
    }


def demo_engine_anonymous() -> dict:
    """RECEIPT_FIELDS 에 판관(엔진 규칙) 정체성 필드가 없음 ⇒ 원장은 '어느 판관이 찍었나'를 답 못 함.
    (jp1 이 겨누는 결함의 running proof.)"""
    has_engine_id = any("engine" in f for f in V.RECEIPT_FIELDS)
    return {"receipt_fields": len(V.RECEIPT_FIELDS), "binds_engine_identity": has_engine_id,
            "anonymous": not has_engine_id}


# ── fix 노드: RED-first 이중가드 (disk 실측 → judge() 엔진판결, 손입력 0) ──────────────

@dataclass(frozen=True)
class FixNode:
    tag: str
    altitude: str
    metric: str           # 개선축(defect-closed) 구조 metric — disk 에서 실측
    question: str         # 닫는 frontier 질문
    summary: str
    measure: Callable[[], float]   # 현재 disk 상태 실측(0=미착륙, 1=착륙)


def _m_engine_sha() -> float:
    return 1.0 if any("engine" in f for f in V.RECEIPT_FIELDS) else 0.0


def _m_fsck_recompute() -> float:
    # fsck 가 receipt_content_sha 를 read-time 에 재계산해 대조하는 checker 를 가졌는가
    return 1.0 if "receipt_content_sha" in _read("server/contexts/audit/fsck.py") else 0.0


def _m_write_gated_on_stale() -> float:
    src = _read("server/contexts/tree/writer.py") + _read("server/contexts/tree/judgement_service.py")
    return 1.0 if ("served_version" in src or "boot_git_sha" in src) else 0.0


def _m_attested_self_sign_rejected() -> float:
    # certify 층이 self-authorized attestation 을 owned 에서 배제(선언 allow-list 요구)하는가
    src = _read("lakatos/verdict/certify.py") + _read("server/contexts/tree/judgement_service.py")
    return 1.0 if "authored" in src else 0.0


def _m_served_full_seam() -> float:
    # 단일 disk 표면이 engine 정체성 봉인 + measurement 게이트를 동시에 가지는가 (4-way split 해소 proxy)
    certify = _read("lakatos/verdict/certify.py")
    return 1.0 if (_m_engine_sha() and "measurement_owned" in certify) else 0.0


NODES = [
    FixNode("jp1-engine-rule-sha", "strategic", "receipt_binds_engine_rule_sha", "q_judge_identity",
            "engine_rule_sha 를 RECEIPT_FIELDS+인증서에 바인딩 · v1→v2(legacy carve-out) · stale CANONICAL 자동강등",
            _m_engine_sha),
    FixNode("jp2-ref-reconcile", "tactical", "served_commit_has_full_seam", "q_served_seam",
            "acme/master(bf09c64+117cb6d) forward-merge → 통짜 커밋 존재+served (rank1 hard precondition)",
            _m_served_full_seam),
    FixNode("jp3-fsck-recompute", "structural", "fsck_recompute_reject_checkers", "q_tamper_evidence",
            "fsck read-time recompute-and-reject: receipt_sha==recompute(content) 불일치 시 ERROR (fold 아님)",
            _m_fsck_recompute),
    FixNode("jp4-ca-fail-closed", "structural", "forceful_write_gated_on_stale", "q_ca_authority",
            "served_version().stale+capability self-check 를 FORCEFUL write 에 배선 → 거부 or provisional_stale_engine",
            _m_write_gated_on_stale),
    FixNode("jp5-attested-self-sign", "tactical", "self_signed_attested_rejected", "q_attestation_authority",
            "empty-attestor fallback allowlist=[signer_did] → 자기인가 거부(grade 'authored'≠'attested')",
            _m_attested_self_sign_rejected),
]


def judge_node(n: FixNode) -> dict:
    """disk 실측 → 엔진 판결(judge()). 손입력 verdict 없음. mechanism_closed = 실측이 baseline(0) 초과."""
    measured = float(n.measure())
    pred = Prediction(metric_name=n.metric, direction="higher", baseline_value=0.0, noise_band=0.0)
    v = judge(pred, measured)
    mechanism_closed = measured >= 1.0
    status = "MECHANISM DETECTED → submit progressive" if mechanism_closed else "pending (RED-first — anomaly live)"
    return {"tag": n.tag, "altitude": n.altitude, "metric": n.metric, "measured": measured,
            "verdict": v.verdict, "improved": v.improved, "mechanism_closed": mechanism_closed,
            "status": status, "closes": n.question}


def main() -> int:
    print(f"═══ Judge Proprioception PROM 하네스 — {_TREE} ═══\n")

    print("── 실행 데모(결함 running proof) ──")
    tam = demo_tamper_invisible()
    print(f"  [tamper]  honest={tam['honest_verdict']} → 변조후 fold={tam['tampered_verdict']}  "
          f"invisible={tam['tamper_invisible']}  stored_sha_now_wrong={tam['stored_sha_now_wrong']}")
    anon = demo_engine_anonymous()
    print(f"  [anon]    RECEIPT_FIELDS={anon['receipt_fields']}  binds_engine_identity={anon['binds_engine_identity']}  "
          f"anonymous={anon['anonymous']}")
    anomalies_live = int(tam["tamper_invisible"]) + int(tam["stored_sha_now_wrong"]) + int(anon["anonymous"])
    print(f"  → anomalies reproduced live: {anomalies_live}/3\n")

    print("── fix 노드 이중가드(RED-first; disk 실측 → judge()) ──")
    rows = [judge_node(n) for n in NODES]
    progressive = 0
    for r in rows:
        flag = "✓" if r["mechanism_closed"] else "·"
        if r["mechanism_closed"]:
            progressive += 1
        print(f"  [{flag}] {r['tag']:22s} {r['altitude']:10s} {r['metric']:32s} "
              f"measured={r['measured']:.0f} verdict={r['verdict']:14s} {r['status']}")

    print(f"\n── 요약 ── progressive={progressive}/{len(rows)}  pending={len(rows) - progressive}  "
          f"anomalies_live={anomalies_live}/3")
    if progressive == 0 and anomalies_live == 3:
        print("  ⇒ 정직 상태: 예측 5 잠금, 채점 0(no fake green). 결함 3/3 실행 재현. fix 착륙 시 실측이 flip.")
    elif progressive > 0:
        print("  ⇒ ★ fix 감지 — 해당 노드를 (비-stale 서버에서) judge()-채점·submit_result 로 progressive 등재하라.")
    elif anomalies_live < 3:
        print("  ⇒ ★ anomaly 일부 소멸 — 결함이 이미 닫혔을 수 있다. 재검토 후 예측 재조준.")
    # 하네스는 상태 리포트(pre-registration) — CI 게이트 아님. 항상 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
