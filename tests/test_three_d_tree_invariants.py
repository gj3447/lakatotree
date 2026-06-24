"""구조 무결성 가드 — 멀티에이전트 verdict reconcile 이 그린을 *조용히* 깨도 트리 *구조*는 못 깨게.

배경(2026-06-24): 동시편집자가 라이브엔진 reconcile 로 LX3 verdict 를 정당하게 재판정했는데,
특정 verdict 를 핀한 dogfood 테스트가 뒤처져 그린이 깨졌다. 교훈: 연구 verdict 는 *정당하게*
변하므로 핀하면 안 된다 — 대신 변하면 안 되는 **불변식**(단일 root·orphan 0·중복 0·frontier
참조 유효·CANONICAL/CLOSED 정직)만 강제한다. 이 가드는 verdict reconcile 엔 안 깨지고, 진짜
구조 손상(orphan·가짜green·dangling frontier)엔만 깨진다.
"""
from examples.three_d_detection import UNIFIED_NODES as N, UNIFIED_FRONTIER as F, HARD_CORE
from lakatos.quant.metrics import tree_metrics


def test_external_trueness_ceiling_is_registered_and_honest():
    """★2026-06-24 사용자 적대검증: hard-core #3(precision≠accuracy)을 닫는 외부 trueness 노드가
    트리 전체에 0개였다. 이 천장 frontier 는 (a) 존재해야 하고 (b) traceable(CMM/CT) grounded 닫는
    노드 없이 조용히 CLOSED 되면 안 된다 — 사용자가 찾은 바로 그 갭의 가짜green 재발 방지."""
    q = next((x for x in F if x['name'] == 'q_external_trueness'), None)
    assert q is not None, 'q_external_trueness(외부 정확도 천장) 가 사라짐 — hard-core #3 닫는 노드 소실'
    # precision≠accuracy 가 hard core 에 남아 있어야(조용히 빼서 갭을 가짜로 닫지 못하게)
    assert any('precision' in h and 'accuracy' in h for h in HARD_CORE), \
        'hard-core #3(precision≠accuracy) 가 사라짐'
    # CLOSED 라면 닫은 노드가 traceable 근거여야(현재는 CMM 미수행 → OPEN 이 정직)
    if q['status'] == 'CLOSED':
        assert q.get('closed_by'), 'q_external_trueness CLOSED 인데 closer 없음(가짜green)'


def test_single_connected_root():
    roots = [n['tag'] for n in N if not n.get('parent') and not n.get('parents')]
    assert roots == ['prob_statement'], f"단일 root 깨짐(분리 트리/멀티루트): {roots}"


def test_no_duplicate_tags():
    tags = [n['tag'] for n in N]
    dup = sorted({t for t in tags if tags.count(t) > 1})
    assert not dup, f"중복 tag(가지 충돌): {dup}"


def test_no_orphan_parents():
    tagset = {n['tag'] for n in N}
    orphans = [(n['tag'], n['parent']) for n in N if n.get('parent') and n['parent'] not in tagset]
    assert not orphans, f"orphan(존재하지 않는 parent 가리킴): {orphans}"


def test_frontier_closed_by_references_real_nodes():
    tagset = {n['tag'] for n in N}
    bad = []
    for q in F:
        cb = q.get('closed_by')
        if cb:
            refs = cb if isinstance(cb, list) else [cb]
            if not set(refs) <= tagset:
                bad.append((q['name'], cb))
    assert not bad, f"closed_by 가 없는 노드 가리킴(dangling): {bad}"


def test_no_fake_green_closed_without_closer():
    """CLOSED frontier 는 반드시 닫은 노드(closed_by)가 있어야 — 측정 없이 닫으면 자기채점."""
    bad = [q['name'] for q in F if q['status'] == 'CLOSED' and not q.get('closed_by')]
    assert not bad, f"closed_by 없이 CLOSED(가짜green): {bad}"


def test_canonical_nodes_only_on_canonical_path():
    """CANONICAL verdict 노드는 정본 경로 위에만 — 미측정 가지(SX3i/LX3/DATUM)가 정본 가로채면 가짜green."""
    m = tree_metrics(N, F)
    path = set(m.get('canonical_path') or [])
    canon = {n['tag'] for n in N if n['verdict'] == 'CANONICAL'}
    assert canon <= path, f"CANONICAL 인데 정본경로 밖(가짜승격): {canon - path}"
    assert m['canonical'] in path, "정본 노드가 정본경로 밖"


def test_known_branches_bloom_at_declared_points():
    """각 가지가 BPC 줄기의 선언된 마디에서 피어남(접붙임 무결성)."""
    by = {n['tag']: n for n in N}
    # 줄기 마디 존재
    assert {'prob_statement', 'aruco_metric', 'v8_pipeline'} <= set(by)
    # SX3i 는 v8_pipeline, LX3 는 aruco_metric 에서 개화 (존재 시)
    if 'sx3i_prob' in by:
        assert by['sx3i_prob']['parent'] == 'v8_pipeline'
    if 'lx3_prob' in by:
        assert by['lx3_prob']['parent'] == 'aruco_metric'
