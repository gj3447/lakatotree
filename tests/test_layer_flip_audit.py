"""C2: layer-flip 감사 — 11개 '철학층'이 load-bearing 인가를 데이터로 정직하게 답한다.

외부 리뷰 B-3(과잉설계 의심: "상당수 층이 실제로 판결을 바꾸는 일이 얼마나 되나"). 이 감사는 세 가지를
정직하게 고정한다:
  (1) SCOPE — flip 은 *stack 투표 3층*(Popper/Bayes/Laudan)만 측정한다. 나머지 8개 '층'은 stack
      voter 가 아니므로 flip *대상이 아니다*(out-of-flip-scope by construction). 이걸 명시해 "11층 다
      flip 으로 검증"이라는 과대주장을 차단한다.
  (2) MECHANISM — 반사실적 피벗 메커니즘(vote_pivotal)은 실제로 작동한다: contested 가지에서 폐기
      합의(quorum=2)를 이루는 층을 빼면 decision 이 뒤집힌다. 즉 메커니즘 자체는 load-bearing.
  (3) CORPUS(정직한 한계) — 현 dogfood 프로그램(euler/consumer3d 의 flip-호환 run())에서 *실제 flip 은
      0*. 이는 층이 죽었다는 증거가 아니라 *corpus 가 층 대립을 자극할 만큼 깊지 않다*는 증거다
      (대부분 단일-노드 가지 + run() 이 예측필드 미방출). 진짜 load-bearing 측정엔 contested
      multi-node 프로그램이 필요하다(→ C3 effectiveness corpus 확대와 연결). 0 이 1+ 로 바뀌면 이
      회귀가 알려준다.
"""
import importlib

from lakatos.programme.flip import LAYERS, layer_flips, vote_pivotal
from lakatos.programme.stack import ABANDON, RETAIN, LayerVote, stack_verdict

# flip 이 다루지 *않는* 철학층 — stack voter 가 아니다(별도 메커니즘). 과대주장 차단용 명시 목록.
OUT_OF_FLIP_SCOPE = (
    'agm', 'dung_argue', 'kuhn', 'eigentrust', 'voi', 'bandit', 'multiplicity', 'prov_o',
)

# run() 이 flip-호환 노드 리스트를 *조용히* 반환하는 dogfood 프로그램(나머지 4개는 데모 리포트 출력).
FLIP_COMPATIBLE_DOGFOOD = ('euler_polyhedron_programme', 'consumer3d_inspection_programme')


def test_flip_scope_is_exactly_the_three_stack_layers():
    """SCOPE: flip 은 stack 3층만. non-stack 층은 out-of-flip-scope(겹침 0) — 과대주장 차단."""
    assert LAYERS == ('popper', 'bayes', 'laudan')
    assert set(LAYERS).isdisjoint(OUT_OF_FLIP_SCOPE)   # 8개 비-stack 층은 flip 측정 대상 아님


def test_flip_mechanism_detects_counterfactual_pivotality():
    """MECHANISM: contested 가지(2 abandon + 1 retain, quorum 2)에서 폐기-합의 층을 빼면 decision 이
    뒤집힌다 → 그 층은 pivotal. retain 표 층은 빼도 안 바뀜(피벗 아님). 메커니즘이 load-bearing 임을 증명."""
    sv = stack_verdict([
        LayerVote('popper', ABANDON, '최신 rejected'),
        LayerVote('bayes', ABANDON, 'credence<0.1'),
        LayerVote('laudan', RETAIN, '3규칙 미발동'),
    ], quorum=2)
    assert sv.decision == ABANDON                       # 폐기 2 ≥ 정족수 2
    assert vote_pivotal(sv, 'popper') is True           # 빼면 1<2 → retain (flip)
    assert vote_pivotal(sv, 'bayes') is True            # 빼면 1<2 → retain (flip)
    assert vote_pivotal(sv, 'laudan') is False          # retain 표: 빼도 abandon 유지(피벗 아님)


def test_non_voting_layer_is_never_pivotal():
    """투표 안 한(undecided/표 없음) 층은 반사실 자체가 없어 피벗 불가 — vote_pivotal False."""
    sv = stack_verdict([
        LayerVote('popper', ABANDON, 'x'),
        LayerVote('bayes', ABANDON, 'y'),
    ], quorum=2)                                          # laudan 표 없음
    assert vote_pivotal(sv, 'laudan') is False


def test_layer_flip_audit_over_dogfood_is_zero_honest_corpus_finding():
    """CORPUS: flip-호환 dogfood(euler/consumer3d)에서 stack 3층 flip 합계 = 0(정직한 발견을 freeze).

    0 = 층이 죽었다가 *아니라* corpus 가 층 대립을 안 자극(얕음). 메커니즘은 위 테스트가 증명함.
    contested 프로그램이 추가돼 1+ 가 되면 이 회귀가 알려주고 frozen 값을 갱신해야 한다(=신호)."""
    total = 0
    evaluated = 0
    for modname in FLIP_COMPATIBLE_DOGFOOD:
        mod = importlib.import_module('examples.' + modname)
        nodes = mod.run()
        lf = layer_flips(nodes, [])
        evaluated += lf['branches_evaluated']
        total += sum(lf[layer]['flips'] for layer in LAYERS)
    assert evaluated > 0                                  # 감사가 실제로 가지를 평가했다(공허하지 않음)
    assert total == 0, (f'dogfood flip 합계가 {total} (was 0) — contested 프로그램이 들어왔다는 신호. '
                        f'frozen 값을 갱신하고 어느 층이 어디서 뒤집었는지 기록할 것.')
