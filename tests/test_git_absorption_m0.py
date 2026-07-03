"""git-흡수 M0 landed guards — GitNexus 구조 교차검증 (흡수설계 전수성의 방법론 근거).

  guard_defect(개선축)     : test_absorption_anchor_has_no_unaccounted_caller_path
        — '흡수설계가 눈-검증뿐이라 전수성 미확인' 결함이 닫혔다: 각 초크포인트의 caller 집합이
          공유 KG 에 *이름 단위 전수*로 적재돼 있고, 핀된 기대집합과 바이트동일. 미등재 caller 경로
          (=단일게이트 우회 가능성) 발견 시 RED. 로컬 git 소스가 있으면 추출기로 재유도 이중대조.
  guard_mechanism(novel축) : test_chokepoint_anchors_present_in_shared_kg
        — 초크포인트 6개가 공유 consumer KG 에 chokepoint:true + ABSORPTION_ANCHOR→(실재 G-노드) 로
          살아 있다(눈-검증 아닌 *구조* 증거가 흡수 프로그램 노드에 물리적으로 연결).

증거원: 공유 consumer KG(importBatch git-source-structure-20260702 + -m0complete) — GitNexus 인덱스
(41,064노드/92,918엣지, git@e9019fc)에서 수출 + column0-enclosing-scan 으로 caller 집합 완성
(scripts/extract_git_callers.py; 교정 4/3/2/3 통과, ref_transaction_commit 은 28>GitNexus 24 과포함).
KG 미접근 환경(클린 클론/오프라인)은 skip — 외부증거 테스트 선례(conftest collect_ignore 장르).

# KG: LakatosTree_GitAbsorption_20260702 / M0_gitnexus_structural_xcheck
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_KG_URL = os.environ.get('AIRO_KG_MCP_URL', 'http://localhost:55013/mcp/')
_GIT_SRC = Path(os.environ.get('LAKATOS_GIT_SRC', '<WORKSPACE>/PROJECT/PI/GIT/git'))
_TREE = 'LakatosTree_GitAbsorption_20260702'

# 초크포인트 → 흡수 G-노드 (ABSORPTION_ANCHOR 기대 배선).
EXPECTED_ANCHOR = {
    'finalize_object_file_flags': 'G1_immutable_verdict_receipts',
    'ref_transaction_commit': 'G1_immutable_verdict_receipts',
    'fsck_object': 'G8_lakatos_fsck',
    'mark_reachable_objects': 'G9_prune_pointer_death',
    'merge_incore_recursive': 'G7_consilience_operator',
    'migrate_one': 'G4_kg_mirror_content_verify',
}

# 초크포인트 → caller 전수집합(이름). 유도: scripts/extract_git_callers.py @ git e9019fc.
# 교정 확인: 앞 4개는 GitNexus 전수확인 값과 바이트동일(4/3/2/3).
EXPECTED_CALLERS = {
    'finalize_object_file_flags': frozenset({
        'finalize_object_file', 'migrate_one', 'odb_source_loose_write_stream', 'write_loose_object'}),
    'fsck_object': frozenset({'check_object', 'fsck_obj', 'sha1_object'}),
    'mark_reachable_objects': frozenset({'cmd_reflog_expire', 'perform_reachability_traversal'}),
    'merge_incore_recursive': frozenset({'do_remerge_diff', 'merge_ort_recursive', 'real_merge'}),
    'migrate_one': frozenset({'migrate_paths'}),
    'ref_transaction_commit': frozenset({
        'cmd_reflog_write', 'cmd_replay', 'cmd_tag', 'commit_ref_transaction', 'create_branch',
        'do_label', 'dump_tags', 'execute_commands_atomic', 'execute_commands_non_atomic',
        'fast_forward_to', 'files_optimize', 'files_transaction_finish',
        'files_transaction_finish_initial', 'handle_reference_updates', 'mv', 'parse_cmd_commit',
        'prune_ref', 'refs_delete_ref', 'refs_delete_refs', 'refs_update_ref',
        'refs_update_symref_extended', 'replace_object_oid', 'repo_migrate_ref_storage_format',
        'update_branch', 'update_head_with_reflog', 'update_refs_stdin', 'walker_fetch',
        'write_remote_refs'}),
}


def _kg_read(query: str) -> list[dict] | None:
    """공유 KG HTTP-MCP JSON-RPC 읽기. 미접근 = None(호출부 skip) — 이 박스 유일 경로(bolt 없음)."""
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'read_neo4j_cypher', 'arguments': {'query': query}}}
    req = urllib.request.Request(
        _KG_URL, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream'})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode()
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    for line in raw.splitlines():   # SSE 프레이밍: data: {...}
        if line.startswith('data: '):
            payload = json.loads(line[len('data: '):])
            result = payload.get('result') or {}
            if result.get('isError'):
                return None
            return json.loads(result['content'][0]['text'])
    return None


def _kg_or_skip(query: str) -> list[dict]:
    rows = _kg_read(query)
    if rows is None:
        pytest.skip(f'공유 consumer KG 미접근({_KG_URL}) — M0 증거는 KG 에 산다(오프라인/클린클론 skip)')
    return rows


# ── guard_mechanism (novel축, 양성 오라클): 구조 증거가 흡수 노드에 물리 연결 ────────────────
def test_chokepoint_anchors_present_in_shared_kg():
    rows = _kg_or_skip(
        "MATCH (s:GitSourceSymbol {chokepoint:true})-[:ABSORPTION_ANCHOR]->(g:LakatosNode) "
        "RETURN s.name AS s, g.tag AS g, g.name AS gname")
    got = {r['s']: r['g'] for r in rows}
    assert got == EXPECTED_ANCHOR, f'앵커 배선 드리프트: {got}'
    # G-노드는 GitAbsorption 트리 소속 실재 노드(name = tree/tag 규약).
    for r in rows:
        assert r['gname'] == f"{_TREE}/{r['g']}", r
    # 초크포인트 외 심볼이 몰래 chokepoint 를 달지 않았다(전수 = 정확히 6).
    n = _kg_or_skip("MATCH (s:GitSourceSymbol {chokepoint:true}) RETURN count(s) AS n")[0]['n']
    assert n == len(EXPECTED_ANCHOR), n


# ── guard_defect (개선축, 음성 오라클): 미등재 caller 경로(우회 가능성) 부재 ─────────────────
def test_absorption_anchor_has_no_unaccounted_caller_path():
    rows = _kg_or_skip(
        "MATCH (s:GitSourceSymbol {chokepoint:true}) "
        "OPTIONAL MATCH (c:GitSourceSymbol)-[:CALLS]->(s) "
        "RETURN s.name AS s, s.callerCount AS n, collect(c.name) AS callers")
    assert {r['s'] for r in rows} == set(EXPECTED_CALLERS)
    for r in rows:
        got = set(r['callers'])
        want = EXPECTED_CALLERS[r['s']]
        missing, extra = want - got, got - want
        assert not missing and not extra, \
            f"{r['s']}: KG 누락={sorted(missing)} KG 과잉={sorted(extra)} — 미등재 caller = 우회경로 미검증"
        assert r['n'] == len(want), f"{r['s']}: callerCount {r['n']} ≠ 전수 {len(want)}"


def test_local_rederivation_matches_pinned_sets():
    """이중 오라클(로컬 소스 보유 시): 추출기 재유도 == 핀 집합 — 핀이 손편집으로 표류하지 못한다."""
    if not (_GIT_SRC / 'object-file.c').exists():
        pytest.skip(f'git 소스 없음({_GIT_SRC}) — 재유도 대조는 소스 보유 박스에서만')
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'extract_git_callers', Path(__file__).resolve().parents[1] / 'scripts/extract_git_callers.py')
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    derived = mod.extract_callers(tuple(EXPECTED_CALLERS), _GIT_SRC)
    for sym, want in EXPECTED_CALLERS.items():
        assert frozenset(derived[sym]) == want, \
            f'{sym}: 재유도 {sorted(derived[sym])} ≠ 핀 {sorted(want)} (소스 드리프트 또는 핀 오염)'
