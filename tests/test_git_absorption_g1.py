"""git-흡수 G1 landed guards — examples/git_absorption_20260702_programme.py 가 scan 하는 이중가드.

G1 = git 의 내용주소 불변 저장 + first-write-wins 발행(odb/source-loose.c:614-621, object-file.c:408-472)을
라카토트리 verdict 에 이식. 두 축:

  guard_defect(개선축)     : test_add_node_cannot_overwrite_scripted_verdict
        — scripted verdict 가 노드-쓰기로 덮이지 않는다(S3 봉합). ✅ 착륙(writer first-write-wins 가드).
  guard_mechanism(novel축) : test_current_verdict_is_fold_over_receipt_chain
        — 현재 verdict 가 불변 :VerdictReceipt 체인의 fold 로 재유도된다(내용주소 메커니즘). ⏳ 미착륙.

두 축이 *독립*이라 judge() 가 판별한다: defect닫힘 ∧ mechanism부재 → **partial**(우회만 막고 git-메커니즘 없음 =
ad-hoc 천장; 정직). mechanism 착륙 시 progressive. 현재 이 파일은 defect guard 만 green → 프로그램이 G1 을
partial 로 채점(가짜 progressive 아님 — 이중가드 판별력이 실제로 무는 증거).

# KG: LakatosTree_GitAbsorption_20260702 / G1_immutable_verdict_receipts
"""
from __future__ import annotations



from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.schemas import TestResultIn as Result
from server.contexts.tree.writer import TreeKgWriter


class _FakeKg:
    """writer op 를 받아 Neo4j MERGE...SET 의 verdict-preservation CASE 를 충실히 모델(revert 민감)."""

    def __init__(self, seed: dict[str, dict]):
        self.store = {k: dict(v) for k, v in seed.items()}
        self.last_ops: list = []

    def _guarded(self, query: str, params: dict) -> bool:
        return ("CASE WHEN coalesce(e.verdict_source" in query) and isinstance(params.get("forceful"), list)

    def __call__(self, ops):
        self.last_ops = ops
        out = []
        for query, params in ops:
            if "MERGE (e:LakatosNode" in query and "e.verdict" in query:
                rows = params.get("rows") or [params]
                guarded = self._guarded(query, params)
                forceful = params.get("forceful") or []
                for row in rows:
                    tag = row.get("tag", params.get("tag"))
                    node = self.store.setdefault(f"{params.get('tree')}/{tag}", {})
                    if not (guarded and node.get("verdict_source") in forceful):
                        node["verdict"] = row.get("verdict")
            out.append([{"t": params.get("tree")}])
        return out


# ── guard_defect (개선축, 음성 오라클) — 착륙 ──────────────────────────────────────────────
def test_add_node_cannot_overwrite_scripted_verdict():
    """scripted 'rejected' 노드를 같은 tag 로 add_node(기본 'proof')해도 verdict/verdict_source 보존(S3 봉합)."""
    kg = _FakeKg({"T/seam": {"verdict": "rejected", "verdict_source": "scripted", "node_state": "REFUTED"}})
    TreeKgWriter(kg_tx=kg).add_node("T", NodeIn(tag="seam"), [])
    stored = kg.store["T/seam"]
    assert stored["verdict"] == "rejected", f"scripted verdict 가 '{stored['verdict']}' 로 덮임 (S3)"
    assert stored.get("verdict_source") == "scripted", "verdict_source 오염 (S3)"


def test_upsert_nodes_also_preserves_scripted_verdict():
    """bulk 경로(upsert_nodes)도 동일 가드 — add_node 만 막고 bulk 로 새는 비대칭 방지."""
    kg = _FakeKg({"T/seam": {"verdict": "progressive", "verdict_source": "scripted", "node_state": "CANDIDATE"}})
    TreeKgWriter(kg_tx=kg).upsert_nodes("T", [NodeIn(tag="seam", verdict="proof")])
    assert kg.store["T/seam"]["verdict"] == "progressive", "bulk 경로가 scripted verdict 를 덮음 (S3 비대칭 누수)"


# ── guard_mechanism (novel축, 양성 오라클) — 착륙: 내용주소 :VerdictReceipt 체인 + fold ──────────
class _ReceiptKg:
    """submit_test_result 를 실제로 구동하는 stateful KG 더블 — #M5 op 의 receipt MERGE·포인터 전진을 충실 적용,
    load_receipt_chain 의 read 를 store 에서 응답. git odb(MERGE {sha} ON CREATE)+reflog(prev 체인) 의미론 모델."""

    def __init__(self, pred: dict):
        self.pred = pred
        self.node = {'verdict': 'proof', 'verdict_source': None, 'current_receipt_sha': None}
        self.receipts: list[dict] = []
        self.captured: list = []

    def __call__(self, query, **p):   # kg() reads
        if 'pred_metric AS m' in query:
            return [dict(self.pred, prev_receipt_sha=self.node['current_receipt_sha'])]
        if 'current_receipt_sha AS head' in query:
            return [{'head': self.node['current_receipt_sha'], 'cache_verdict': self.node['verdict'],
                     'cache_source': self.node['verdict_source']}]
        if 'HAS_RECEIPT' in query:
            return [dict(r) for r in self.receipts]
        return []

    def tx(self, ops):   # kg_tx() write — #M5 op 를 충실 적용(receipt 발행 + 포인터 전진)
        self.captured.append(ops)
        q0, params = ops[0]
        if 'MERGE (rec:VerdictReceipt' in q0:
            self.node['verdict'] = params['v']
            self.node['verdict_source'] = 'scripted'
            self.node['current_receipt_sha'] = params['rsha']
            self.receipts.append({'receipt_sha': params['rsha'], 'prev_receipt_sha': params['prev_rsha'],
                                  'verdict': params['v'], 'verdict_source': 'scripted'})
        return [[{'claimed': params.get('tag')}] for _ in ops]


def _receipt_svc():
    # cross-metric novel(nmet≠m) + improved + novel_measured=1.0 → judge() progressive(FF1 default-off 경로).
    pred = {'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': 'novel claim',
            'vsrc': None, 'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0, 'psha': None, 'closes': 'q-x',
            'n_opened': 0, 'pred_registered_at': '2026-07-02', 'node_state': 'PREDICTED',
            'judged_at': None, 'existing_metric_value': None, 'hard_core': '', 'require_novel_anchor': False}
    kg = _ReceiptKg(pred)
    svc = JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    return svc, kg


def test_current_verdict_is_fold_over_receipt_chain():
    """노드의 현재 verdict 는 불변 :VerdictReceipt 체인의 fold 로 *재유도*되고 e.verdict 캐시와 일치한다.

    실 submit_test_result 경로가 #M5 CAS 같은 tx 에서 receipt 를 발행하고 current_receipt_sha 포인터를 전진시킴을
    확인 + verify_verdict_chain 이 체인 fold(재유도)==캐시임을 단언. 캐시 손상 시 재유도가 검출(rebuild_verify 판)."""
    svc, kg = _receipt_svc()
    out = svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    assert out['verdict'] == 'progressive_unverified', out

    # (1) receipt 발행 + 포인터 전진(git first-write-wins): 체인에 receipt 1개, 노드 포인터=그 sha.
    assert len(kg.receipts) == 1, kg.receipts
    assert kg.node['current_receipt_sha'] == kg.receipts[0]['receipt_sha']
    assert kg.receipts[0]['verdict'] == 'progressive_unverified'

    # (2) rebuild_verify: 체인 fold 재유도 == e.verdict 캐시(재유도가 판관, 캐시 신뢰 아님).
    v = svc.verify_verdict_chain('T', 'seam')
    assert v['ok'] and v['from_receipt'] and v['rederived'] == 'progressive_unverified', v

    # (3) 캐시 변조 검출: e.verdict 캐시를 손상시키면 재유도(체인 head)와 불일치 → ok=False.
    kg.node['verdict'] = 'rejected'   # 누군가 캐시만 덮음(체인은 불변)
    v2 = svc.verify_verdict_chain('T', 'seam')
    assert v2['ok'] is False and v2['rederived'] == 'progressive_unverified', v2   # 체인이 진실을 보존, 변조 검출


def test_receipt_sha_is_content_addressed_and_deterministic():
    """receipt_sha 는 내용주소 — 같은 내용은 같은 sha(멱등), 한 필드만 달라도 다른 sha(git odb name==content)."""
    from lakatos.verdicts import receipt_content_sha
    base = dict(tree='T', tag='n', target_id='q-x', verdict='progressive', verdict_source='scripted',
                metric_name='seam', metric_value=1.0, novel_confirmed=True, lakatos_status='progressive',
                judged_at='2026-07-02T00:00:00Z', judge_script_sha='abc', prev_receipt_sha=None)
    assert receipt_content_sha(base) == receipt_content_sha(dict(base)), '멱등 실패'
    assert receipt_content_sha(base) != receipt_content_sha(dict(base, verdict='rejected')), '내용 변화 sha 불변(충돌)'
    assert receipt_content_sha(base) != receipt_content_sha(dict(base, prev_receipt_sha='deadbeef')), 'prev 변화 sha 불변'
