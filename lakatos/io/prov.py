"""출처추적 층 — W3C PROV-O 로 판결의 검증가능 계보.

이론: PROV-O (Entity/Activity/Agent + wasGeneratedBy/used/wasDerivedFrom/wasAttributedTo).
"LLM 점수 금지·스크립트 채점·재현가능" 독트린을 표준 provenance 그래프로 구현 →
"이 판결을 누가 무슨 스크립트로 어느 결과파일에서 냈나 + 재현 명령" 을 표준 질의/재생.
# KG: span_lakatotree_prov
"""


def prov_triples(tree: str, tag: str, script: str, result_path: str, verdict: str,
                 script_sha: str, ts: str) -> list:
    """test_result 판결 1건 → PROV-O 트리플 목록 (Neo4j 동시 기록용)."""
    node = f'{tree}/{tag}'
    act = f'judge:{node}@{ts}'
    return [
        {'kind': 'Activity', 'id': act, 'type': 'Scoring', 'at': ts},
        {'kind': 'Agent', 'id': script, 'type': 'Script', 'sha256': script_sha},
        {'kind': 'Entity', 'id': result_path or f'{node}#result', 'type': 'ResultFile'},
        {'kind': 'Entity', 'id': f'{node}#verdict:{verdict}', 'type': 'Verdict'},
        {'rel': 'used', 'from': act, 'to': result_path or f'{node}#result'},
        {'rel': 'wasAttributedTo', 'from': act, 'to': script},
        {'rel': 'wasGeneratedBy', 'from': f'{node}#verdict:{verdict}', 'to': act},
        {'rel': 'wasDerivedFrom', 'from': f'{node}#verdict:{verdict}',
         'to': result_path or f'{node}#result'},
    ]


def replay_command(script: str, result_path: str) -> str:
    """재현 명령 — provenance 에서 판결을 재생하는 쉘 한 줄."""
    return f'python {script} {result_path}'
