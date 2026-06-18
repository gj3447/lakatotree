"""층별 verdict-flip 지표 — 각 rigor 층(Popper/Bayes/Laudan)이 stack 메타규칙의
최종 결정을 실제로 *바꾼* 횟수. THEORY §1 의 3층 스택이 장식이 아니라 load-bearing 임을
데이터로 증명한다(외부 리뷰 B-3: "상당수 층이 실제로 판결을 바꾸는 일이 얼마나 되는지 의심").

정의 — 반사실적 피벗(counterfactual pivotality): 한 가지(leaf)의 `StackVerdict` 에서
층 L 의 표를 빼고 `stack_verdict` 를 재계산했을 때 `decision` 이 달라지면, L 이 그 가지의
판결을 '뒤집었다'(pivotal). 이것이 "층이 판결을 바꿨다"의 정직한 조작적 정의다:
기존 자료구조(`StackVerdict.votes` + 정족수 규칙)만으로 계산되고, 새 저장소도 LLM 도 필요없다.
단순한 '소수 의견(vote != decision)' 휴리스틱은 정족수 2 하에서 과대계상한다 —
소수 dissent 는 피벗이 아니다(이상의 바다에서 포퍼 단독 abandon 은 결정을 바꾸지 못한다).

스코프: 트리의 모든 가지 leaf(정본경로 + 분기) 각각에 대해 `branch_inputs` →
`evaluate_stack` 로 하나의 `StackVerdict` 를 얻고(서버 `/stack` 과 동형), 층별 피벗을 집계한다.

# KG: span_lakatotree_layer_flips / THEORY §1 stack
"""
from lakatos.quant.metrics import branch_inputs
from lakatos.programme.stack import evaluate_stack, stack_verdict, StackVerdict

LAYERS = ('popper', 'bayes', 'laudan')


def vote_pivotal(sv: StackVerdict, layer: str) -> bool:
    """층 `layer` 의 표를 빼고 메타규칙을 재계산 → `decision` 이 바뀌면 그 층이 이 가지를 뒤집었다.

    그 층이 애초에 투표하지 않았으면(표가 votes 에 없으면) 피벗 불가 → False.
    정족수는 메타규칙 상수이므로 표를 빼도 `sv.quorum` 을 그대로 쓴다(상대 정족수 아님).
    """
    remaining = [v for v in sv.votes if v.layer != layer]
    if len(remaining) == len(sv.votes):       # 그 층이 표를 안 냄 — 반사실 자체가 없음
        return False
    return stack_verdict(remaining, quorum=sv.quorum).decision != sv.decision


def _leaves(nodes: list) -> list:
    """부모로 지목되지 않은 노드 = 가지 leaf (단일 parent + 다중 parents 모두 반영).
    `metrics.tree_metrics` 의 leaves 계산과 동형."""
    parents = set()
    for r in nodes:
        if r.get('parent'):
            parents.add(r['parent'])
        for p in (r.get('parents') or []):
            parents.add(p)
    return [r['tag'] for r in nodes if r['tag'] not in parents]


def layer_flips(nodes: list, frontier: list) -> dict:
    """각 가지의 stack 판결에서 층별 피벗(판결 뒤집기) 횟수를 집계.

    반환: {
      'branches_evaluated': int,                         # 평가된 가지 수(분모 — 정직)
      'popper'/'bayes'/'laudan': {'flips': int, 'branches': [leaf, ...]},  # 어느 가지서 뒤집었나(감사가능)
      'note': str,                                        # 조작적 정의 1줄
    }
    평가 불가한 가지(leaf 누락 등 KeyError)는 건너뛴다 — 지표가 대시보드를 깨뜨리지 않게.
    """
    out = {layer: {'flips': 0, 'branches': []} for layer in LAYERS}
    evaluated = 0
    for leaf in _leaves(nodes):
        try:
            bi = branch_inputs(nodes, frontier, leaf=leaf)
        except KeyError:
            continue
        sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                            bi['prediction_hits'], bi['problem_balance_windowed'])
        evaluated += 1
        for layer in LAYERS:
            if vote_pivotal(sv, layer):
                out[layer]['flips'] += 1
                out[layer]['branches'].append(leaf)
    out['branches_evaluated'] = evaluated
    out['note'] = ('층이 stack 판결을 뒤집은 가지 수 — 그 층의 표를 빼면 decision 이 달라지는 경우만 '
                   '(반사실적 피벗). 소수 dissent ≠ flip. 0 이면 그 층은 이 트리에서 결정을 바꾸지 않았다.')
    return out
