"""D1 read-projection 드리프트 가드 — 서버 read-model 을 엔진만큼 조인다.

배경(D1 아키텍처 감사 2026-06-26): server/read_models.py 에 있던 *두 번째* 노드 projection
사본이 프로덕션 projection(server.contexts.tree.repository.TreeKgRepository.load_tree_data)과
갈라져, A2 eigentrust·D1 provenance 게이트가 매 HTTP 경로에서 조용히 무력했다(unit 테스트는
직접 만든 노드 dict 로 fake-green). 처방은 두 개였다: **(1) projection 통합(단일출처)** +
**(2) 재발 가드**. (1)은 실행됐다(projection 은 repository 에만). 이 스위트가 빠졌던 (2)다.

드리프트가 다시 생기는 두 경로를 못 박는다:
  · write⊆read : 노드에 SET 되는 필드는 전부 load_tree_data 가 project 해야 한다 — 안 하면
                 그 필드를 보는 게이트가 HTTP 경로에서 None 을 읽고 조용히 통과한다(A2/D1 그 자체).
  · 단일출처   : read_models 는 metric 합성만 — 노드 row projection(e.X AS X)을 재성장하면
                 갈라질 두 번째 사본이 부활한다.

순수 정적 검사(KG 불필요). 새 노드 필드를 write 에 추가하고 projection 에 안 넣으면 RED.
"""
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TREE = ROOT / 'server' / 'contexts' / 'tree'
REPO = TREE / 'repository.py'
READ_MODELS = ROOT / 'server' / 'read_models.py'

# 프로덕션 write 경로가 노드에 SET 하지만 *의도적으로* project 하지 않는 내부 필드(게이트가 안 봄).
# 새 항목은 반드시 근거와 함께 — silent-drift 를 여기로 숨기지 말 것.
_WRITE_ONLY_INTERNAL = {
    '_cas',   # compare-and-swap 동시성 카운터(낙관적 락) — 노드 데이터 아님
}

# 노드 alias `e` 에 대한 SET 대입(`e.foo = ...`)과 projection(`e.foo AS foo`) 추출.
_WRITE = re.compile(r'\be\.([a-z_]+)\s*=(?!=)')
_PROJ = re.compile(r'\be\.([a-z_]+)\s+AS\b')


def _match(path: pathlib.Path, pat: re.Pattern) -> set:
    return {m.group(1) for m in pat.finditer(path.read_text(encoding='utf-8'))}


def test_every_written_node_field_is_projected():
    """write 경로가 노드에 넣는 필드는 전부 load_tree_data 가 내보내야(HTTP 게이트 침묵 차단)."""
    written = set()
    for p in sorted(TREE.glob('*.py')):
        written |= _match(p, _WRITE)
    projected = _match(REPO, _PROJ)
    silent = written - projected - _WRITE_ONLY_INTERNAL
    assert not silent, (
        f"노드에 SET 되지만 load_tree_data 가 project 안 하는 필드 = HTTP 경로 게이트 침묵(D1 재발): "
        f"{sorted(silent)}. → repository.load_tree_data RETURN 에 `e.<field> AS <field>` 추가하거나, "
        f"게이트가 안 보는 순수 내부 필드면 _WRITE_ONLY_INTERNAL 에 근거와 함께 등재.")


def test_read_models_holds_no_second_node_projection():
    """read_models 는 metric 합성만 — 노드 projection 재성장 시 갈라질 두 번째 사본 부활(D1)."""
    reprojection = _match(READ_MODELS, _PROJ)
    assert not reprojection, (
        f"read_models.py 에 노드 projection 재출현({sorted(reprojection)}) — 단일출처 위반. "
        f"projection 은 repository.load_tree_data 에만(D1 통합 불변).")


def test_guard_is_not_vacuous():
    """가드가 실효적임을 자체 증명: 정규식이 실제 필드를 잡고, projection 이 write 를 덮는다."""
    projected = _match(REPO, _PROJ)
    written = set()
    for p in sorted(TREE.glob('*.py')):
        written |= _match(p, _WRITE)
    # 로드베어링 필드가 실제로 잡히는지(정규식 침묵=vacuous green 차단)
    assert {'verdict', 'metric_value', 'measurement_grade'} <= projected
    assert {'verdict', 'metric_value', 'measurement_grade'} <= written
    assert len(projected) >= 40 and len(written) >= 40
