"""EXTAUDIT S5 — Laudan 폐기신호 서버 배선 + override 기록 (급소 #7).

적대감사 2026-07-22: laudan.should_abandon(폐기 3규칙)은 server/ 호출 0건의 죽은 신호였다 —
Laudan 후보 4건이 켜진 트리가 다음날 Phase B 로 진격해도 어떤 기록도 남지 않았다(hard core 불사).
라카토스 철학상 자동 차단은 논쟁적(연구자의 방어 권리)이므로 처방은 하네스 진단 그대로:
*신호를 서버 표면에 올리고, 무시하고 계속하는 결정을 지울 수 없게 기록한다* (AGM
programme_shift_candidate 패턴의 abandon 판).

배선: mutations.add_node — 부모 가지에 should_abandon 이 발화하면
  · 응답에 abandon_signal(사유 동봉) + policy_warnings 에 ABANDON_SIGNAL_IGNORED
  · hist 에 'abandon_override' 영속 이력 (침묵 진격 불가)
차단 없음 — 확장은 자유이되 red light 위를 지나갔다는 사실이 남는다.
입력은 metrics.branch_inputs 재사용(규칙①②③ 전부 실입력 — ③도 frontier 로 라이브).
# KG: q-extaudit-hardcore-immortality-20260722 / crit-extaudit 감사
"""
from types import SimpleNamespace

from server.contexts.tree.mutations import TreeMutationService
from server.contexts.tree.schemas import NodeIn


class _Writer:
    def add_node(self, name, node, parent_edges):
        self.added = (name, node.tag)


class _Hist:
    def __init__(self):
        self.events = []

    def __call__(self, name, kind, tag, payload):
        self.events.append((kind, tag, payload))


def _mut():
    m = object.__new__(TreeMutationService)
    m.writer = _Writer()
    m.validator = SimpleNamespace(validate_node_create_result=lambda n, td, node: SimpleNamespace(
        parent_edges=[], policy_findings=[]))
    m.hist = _Hist()
    return m


def _n(tag, parent, verdict, **kw):
    base = dict(tag=tag, parent=parent, parents=[parent] if parent else [], verdict=verdict,
                metric_value=None, pred_baseline=None, pred_noise_band=None, verdict_source='scripted')
    base.update(kw)
    return base


def _tree(nodes):
    return {'nodes': nodes, 'frontier': []}


# ── 발화: 연속 비진보 3 가지에 노드를 더 얹으면 신호+기록 ─────────────────────────────────
def test_add_node_on_degenerating_branch_records_override():
    m = _mut()
    td = _tree([_n('r', None, 'proof'),
                _n('a', 'r', 'rejected'), _n('b', 'a', 'rejected'), _n('c', 'b', 'rejected')])
    out = m.add_node('T', NodeIn(tag='d', parent='c'), td)
    assert 'abandon_signal' in out, out
    assert out['abandon_signal']['fired'] is True
    assert '연속 비진보' in out['abandon_signal']['reason']
    assert 'ABANDON_SIGNAL_IGNORED' in out.get('policy_warnings', []), out
    kinds = [k for k, _t, _p in m.hist.events]
    assert 'abandon_override' in kinds, kinds   # 영속 이력 — 침묵 진격 불가


# ── 무발화: 건강한 가지는 신호 없음 (과잉 경보 방지 이중가드) ─────────────────────────────
def test_add_node_on_healthy_branch_is_silent():
    m = _mut()
    td = _tree([_n('r', None, 'proof'),
                _n('a', 'r', 'progressive', novel_confirmed=True),
                _n('b', 'a', 'partial')])
    out = m.add_node('T', NodeIn(tag='c', parent='b'), td)
    assert 'abandon_signal' not in out, out
    assert 'ABANDON_SIGNAL_IGNORED' not in out.get('policy_warnings', [])
    assert 'abandon_override' not in [k for k, _t, _p in m.hist.events]


# ── 루트/미지 부모: 신호 계산 불가 = 조용히 통과 (fail-open — 차단 도구 아님) ─────────────
def test_add_root_or_unknown_parent_no_crash():
    m = _mut()
    out = m.add_node('T', NodeIn(tag='root2'), _tree([]))
    assert out['ok'] is True and 'abandon_signal' not in out
    m2 = _mut()
    out2 = m2.add_node('T', NodeIn(tag='x', parent='ghost'), _tree([_n('r', None, 'proof')]))
    assert out2['ok'] is True and 'abandon_signal' not in out2
