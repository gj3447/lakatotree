"""EUREKA detector — distinguish a FELT aha from a TRUE (externally-confirmed) one.

The cognitive science is blunt (see ``docs/EUREKA.md``; prom cycle eureka-red-blue,
2026-06-18, 12 axes, 8 surviving adversarial verification). The felt "aha" is mostly
🔵 BLUE — representational restructuring crossing the conscious threshold — plus an
INTRINSIC "feeling of rightness" that is a LOW-FIDELITY proxy, NOT verification.
~37% of objectively WRONG solutions produce a phenomenologically identical aha
(Danek & Wiley 2017; Laukkonen et al. "dark side of Eureka" 2019). Therefore:

    felt eureka  ≠  true eureka.
    A felt eureka with no external receipt is a hallucination.

This module makes that distinction executable. It is a **downstream pipeline detector**
(Reichenbach: discovery → justification), NOT a symmetric "red⊗blue bond": the engine's
gates are decoupled and 🔴 red is an *asymmetric* filter — it gates/demotes, never
originates content. What red contributes is the only thing that separates Archimedes
from a confident crank: external confirmation.

    🔵 blue (discovery)     a NOVEL prediction was registered (the flash)     → felt
    🔴 red  (justification) confirmed + survives the gates                    → true
    hallucinated = felt ∧ ¬true   (the false aha; the 37%)

Longinus: composes lakatos/ real symbols — ``bayes.bayes_factor`` (evidential weight),
``laudan.problem_balance`` (closed−opened), ``promote.promotion_gate`` (fail-closed).
The true-eureka *rate* mirrors ``fertility.predictive_fertility`` (confirmed/registered).
"""
from __future__ import annotations

from dataclasses import dataclass

from lakatos.quant.bayes import bayes_factor
from lakatos.quant.laudan import problem_balance
# NOTE(아키텍처 감사 2026-06-26, finding D3/eureka): verdict.promote 를 *주입*으로 받는다(아래 classify).
# 전엔 module-level import 라 quant.metrics → eureka → verdict.promote 상향 체인이 생겨 .importlinter 에
# carve-out(ignore_imports) 1줄로만 green 이었다 — 게다가 그 게이트는 모든 프로덕션 경로가 require_promotion=
# False 라 *dead weight* 였다. import 를 제거하면 eureka 는 순수 측정 코어(quant 만 의존)가 되고 계약은
# 예외-제로가 된다. promotion 이 필요한 호출자(현재 test_eureka 뿐)만 promotion_gate 를 주입한다.

# Jeffreys 'substantial' evidence band (10**0.5). Below this a confirmation is marginal —
# a felt aha riding weak evidence is not a true eureka.
BF_SUBSTANTIAL = 3.162


def eureka_verdict(verdict: str) -> str:
    """Map the Lakatos-unverified metric verdict onto Eureka's orthogonal discovery axis.

    The abandon-stack reads ``progressive_unverified`` as neutral BF=1.0. Eureka still
    evaluates the independently confirmed novelty/problem-closure gates, so it reads the
    same metric result as ``progressive``. ``classify`` owns this normalization so every public
    measurement caller receives the same semantics; promotion still sees the raw verdict.
    """
    return "progressive" if verdict == "progressive_unverified" else verdict


@dataclass(frozen=True)
class EurekaVerdict:
    felt: bool          # 🔵 the flash: a novel prediction was made (aha-prone, unreliable)
    true: bool          # 🔴 survives external red: confirmed + every gate passes
    hallucinated: bool  # felt ∧ ¬true ∧ ledger-assessable — the false aha (the ~37%)
    bf: float
    balance: int
    reasons: tuple = ()  # which external-red gate(s) vetoed it (why it is not true)
    inconclusive: bool = False  # felt but the Laudan axis has NO data (no problem ledger):
    #   neither true nor hallucinated — excluded from the true/hallucination rate denominator
    #   (audit 2026-07-12 finding B).


def classify(node: dict, *, bf_substantial: float = BF_SUBSTANTIAL,
             require_promotion: bool = True, promotion_gate=None) -> EurekaVerdict:
    """Classify a research node as felt / true / hallucinated eureka.

    Node keys (all optional, conservative defaults): ``novel_registered``,
    ``novel_confirmed``, ``verdict``, ``delta``, ``noise_band``, ``source_trust``,
    ``closed``, ``opened``, ``stands``, ``reproducible``.

    A node is *felt* iff a novel prediction was registered (the blue flash). It is *true*
    iff it is also externally confirmed AND clears every red gate; otherwise the felt aha
    is *hallucinated* and ``reasons`` names every veto.

    ``require_promotion=False`` drops the promotion gate (``stands``/``reproducible``) from
    the verdict. Those live in the *standing* layer, not on a tree node — so a tree-level
    eureka scan asserts only the *measurement* gates (confirmed + substantial BF + net
    problem closure) and leaves promotion-standing to the layer that owns it, rather than
    hallucinating a veto from a field the node never carried. See :func:`eureka_over_tree`.

    ``require_promotion=True`` (default) additionally applies the promotion gate, which must
    be supplied via the ``promotion_gate`` parameter (dependency injection) — eureka itself
    stays a measurement core that does *not* import ``verdict.promote`` (finding D3/eureka),
    so the ``.importlinter`` layers contract holds with zero exceptions. All production tree
    paths call with ``require_promotion=False`` and need no injection.
    """
    felt = bool(node.get("novel_registered"))  # 🔵 blue flash — does NOT imply correctness
    if not felt:
        return EurekaVerdict(False, False, False, bf=1.0, balance=0,
                             reasons=("no_novel_prediction",))

    # 🔴 external-red gates — each may veto, none may originate (asymmetric filter)
    reasons: list[str] = []
    if not node.get("novel_confirmed"):
        reasons.append("novel_unconfirmed")  # the decisive false-aha signature
    raw_verdict = node.get("verdict", "")
    bf = bayes_factor(eureka_verdict(raw_verdict), node.get("delta", 0.0),
                      node.get("noise_band"), node.get("source_trust", 1.0))
    if bf <= bf_substantial:
        reasons.append(f"bf_marginal:{bf:.3f}<={bf_substantial}")
    closed_n, opened_n = int(node.get("closed", 0)), int(node.get("opened", 0))
    balance = problem_balance(closed_n, opened_n)
    ledger_absent = (closed_n == 0 and opened_n == 0)
    # audit 2026-07-12 finding B: only a PRESENT, net-negative ledger (closed<opened =
    # excuses breeding problems) vetoes true-eureka. An ABSENT ledger (0,0) leaves the
    # Laudan axis UNASSESSABLE → the node abstains (inconclusive below), it is NOT branded a
    # hallucination. Was `<= 0`, which conflated absent-ledger AND break-even with genuine
    # net-negative, pinning hallucination_rate=1.0 on ledger-less live trees.
    if not ledger_absent and balance < 0:
        reasons.append(f"problem_balance:{balance}<0")
    if require_promotion:
        if promotion_gate is None:
            raise ValueError(
                "require_promotion=True requires an injected promotion_gate (DI: eureka 는 verdict.promote 를 "
                "import 하지 않는 측정 코어 — finding D3/eureka). 프로덕션 트리 경로는 require_promotion=False "
                "라 이 분기를 타지 않는다; promotion 이 필요한 호출자가 lakatos.verdict.promote.promotion_gate 를 주입할 것.")
        ok, gate_reasons = promotion_gate(scripted_verdict=raw_verdict,
                                          stands=bool(node.get("stands", False)),
                                          reproducible=node.get("reproducible"))
        if not ok:
            reasons.extend(gate_reasons)

    inconclusive = ledger_absent and not reasons   # would be true, but the Laudan axis has no data
    true = (not reasons) and not inconclusive
    return EurekaVerdict(felt=True, true=true,
                         hallucinated=(not true and not inconclusive),
                         bf=bf, balance=balance, reasons=tuple(reasons),
                         inconclusive=inconclusive)


def closed_count(value) -> int:
    """'닫는 질문 수'의 단일 정본(R7, G5 단일 프로젝터 장르) — str(질문명)=1·빈str=0, list=원소수,
    int=그대로, None=0. 봉합한 버그: len(pred_closes)가 질문명 *글자수*(len('q_lx3_enabler')=13)를
    닫은 질문 수로 계산해 problem_balance 를 거짓 부양했다. judgement seam(1 if closes else 0)과 동형."""
    if value is None:
        return 0
    if isinstance(value, str):
        return 1 if value.strip() else 0
    if isinstance(value, (list, tuple, set)):
        return len([v for v in value if v])
    return int(value)


def _node_to_eureka_input(node: dict) -> dict:
    """Assemble the eureka input dict from a *real* lakatotree tree node (server
    ``repository``/``read_models`` shape). Derivations match the engine, not invented:

    * ``delta = metric_value − pred_baseline``  (exactly ``judge.judge``'s effect)
    * ``noise_band = pred_noise_band``
    * ``closed = |pred_closes|`` (questions this prediction closes),
      ``opened = |questions|`` (questions the node raises) → per-node problem balance
    * ``verdict`` / ``novel_registered`` / ``novel_confirmed`` / ``source_trust`` — direct

    ``stands``/``reproducible`` are deliberately absent — they belong to the standing layer
    (see :func:`eureka_over_tree`, which runs with ``require_promotion=False``).
    """
    mv, base = node.get("metric_value"), node.get("pred_baseline")
    delta = (float(mv) - float(base)) if mv is not None and base is not None else 0.0
    return {
        "novel_registered": node.get("novel_registered"),
        "novel_confirmed": node.get("novel_confirmed"),
        "verdict": node.get("verdict", ""),
        "delta": delta,
        "noise_band": node.get("pred_noise_band"),
        "source_trust": node.get("source_trust", 1.0),
        "closed": closed_count(node.get("pred_closes")),   # R7: 글자수 버그 봉합(str 질문명=1)
        "opened": len(node.get("questions") or []),
    }


def eureka_over_tree(nodes: list) -> dict:
    """Run the eureka scan over real tree nodes — the *measurement-grade* eureka.

    Each node's inputs are assembled by :func:`_node_to_eureka_input` from fields the node
    actually carries; ``classify`` runs with ``require_promotion=False`` because standing is
    not a node field. So a *true* here means: a novel prediction that was confirmed, with
    substantial Bayes evidence, that closed more questions than it opened — i.e. the node
    *measured* a real discovery (felt aha that survived measurement red). Promotion-standing
    is a separate, higher gate. Returns the same shape as :func:`eureka_rate` plus
    ``measurement_grade=True`` so a caller never mistakes it for the full (promotion) verdict.
    """
    inputs = [_node_to_eureka_input(n) for n in nodes]
    verdicts = [classify(i, require_promotion=False) for i in inputs]
    felt = sum(1 for v in verdicts if v.felt)
    true = sum(1 for v in verdicts if v.true)
    hallucinated = sum(1 for v in verdicts if v.hallucinated)
    # audit 2026-07-12 finding B (supersedes R7 "헤드라인 불변" — that only *disclosed* the
    # artifact): a felt node whose problem ledger is absent (closed==0∧opened==0) is now an
    # INCONCLUSIVE abstain, not a hallucination. true_rate/hallucination_rate are computed over
    # ASSESSABLE nodes (felt − inconclusive) — the ones whose Laudan axis actually has data —
    # so a ledger-less live tree no longer pins hallucination_rate to 1.0. (OmdEngine 7/7 genre:
    # confirmed+substantial-BF but no declared pred_closes → inconclusive, honestly unmeasured.)
    inconclusive = sum(1 for v in verdicts if v.inconclusive)
    assessable = felt - inconclusive
    return {
        "felt": felt, "true": true, "hallucinated": hallucinated,
        "inconclusive": inconclusive, "assessable": assessable,
        "true_rate": round(true / assessable, 3) if assessable else 0.0,
        "hallucination_rate": round(hallucinated / assessable, 3) if assessable else 0.0,
        "problem_ledger_absent": inconclusive,
        "hallucinated_reason_split": {"problem_ledger_absent": inconclusive,
                                      "measurement_failed": hallucinated},
        "measurement_grade": True,
    }


def eureka_rate(nodes: list, *, promotion_gate=None) -> dict:
    """True-eureka rate over a node set = true / felt = 1 − hallucination rate.

    The headline reliability metric: of all felt ahas, how many survived external red?
    This is the engine's measured analogue of the ~37% human false-insight rate — and the
    whole point of the 🔴 strand is to drive ``hallucination_rate`` toward zero.

    ※정직 한계(적대 재검증 R2 2026-06-21): classify(n) 를 *호출자 dict 그대로* 채점하므로 self-report 한
    delta/noise_band/closed/opened 를 신뢰한다(BF·문제수지 red 게이트를 그 값으로 통과). 신뢰 불가 입력엔
    eureka_over_tree(metric_value/pred_baseline 에서 *재유도*하는 measurement-grade 경로)를 쓸 것 — 현재
    eureka_rate 는 untrusted entrypoint 에 미연결(잠재 비대칭; 헤드라인 집계는 over_tree 가 받침).

    promotion 게이트를 쓰는 full 경로이므로(require_promotion 기본 True) 호출자가 ``promotion_gate`` 를
    주입한다(eureka 는 verdict.promote 를 import 안 하는 측정 코어, D3/eureka). 미주입 시 felt 노드에서
    classify 가 명시적으로 raise — 측정-grade 집계가 필요하면 :func:`eureka_over_tree` 를 쓸 것.
    """
    verdicts = [classify(n, promotion_gate=promotion_gate) for n in nodes]
    felt = sum(1 for v in verdicts if v.felt)
    true = sum(1 for v in verdicts if v.true)
    hallucinated = sum(1 for v in verdicts if v.hallucinated)
    inconclusive = sum(1 for v in verdicts if v.inconclusive)   # audit 2026-07-12 finding B
    assessable = felt - inconclusive
    return {
        "felt": felt, "true": true, "hallucinated": hallucinated,
        "inconclusive": inconclusive, "assessable": assessable,
        "true_rate": round(true / assessable, 3) if assessable else 0.0,
        "hallucination_rate": round(hallucinated / assessable, 3) if assessable else 0.0,
    }
