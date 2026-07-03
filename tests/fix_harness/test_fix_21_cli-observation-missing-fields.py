"""FIX-HARNESS #21 (P3 surface gap): CLI 'observation' 가 rival/theory/longinus 증거 필드를 못 받음.

finding id: #21
locations:
  - lakatos/cli.py:186-196  (observation 서브파서)  — name/tag/event_id + url/trust 계열만 선언.
  - lakatos/cli.py:411-421  (observation 핸들러)     — body 에 위 필드만 전달.
  - lakatos/mcp_server.py:442-485  add_observation    — theory_basis/foundation_refs_csv/rival_name/
        rival_relation/rival_node/comparison_axes_csv/longinus_refs_json 을 노출하고 body 에 실음.
  - server/contexts/tree/evidence_claim_service.py:262-288  — ObservationIn 의 theory_basis/
        foundation_refs/rival_name/rival_relation/rival_node/comparison_axes/longinus_refs 를 소비
        (EmbeddedInternetEvidence 임베딩 트리거).

the bug:
  MCP/REST 표면은 인터넷 관측을 *이론 좌표 + 경쟁 프로그램(rival) 증거*로 임베딩하는 필드를
  받지만, CLI 'observation' 서브파서는 그 옵션을 전혀 선언하지 않는다. 따라서 CLI-only 운영자는
  관측을 rival-programme 증거로 박거나 이론 좌표에 앵커링할 수 없다(표면 비대칭/기능 결손).
  argparse 는 --theory-basis / --rival-name / --rival-relation / --longinus-refs 등을 '인식되지
  않는 인자'로 거부한다 → parse_known_args 의 extras 에 그대로 남는다.

the exact fix:
  lakatos/cli.py:186-196 observation 서브파서에 누락된 선택 인자(--theory-basis, --foundation-refs,
  --rival-name, --rival-relation, --rival-node, --comparison-axes, --longinus-refs)를 추가하고
  :411-421 핸들러에서 add_observation 과 동형으로 body 에 forward 한다.

xfail(strict) until fixed: 아래 negative oracle 는 사후(fix 후) 계약(이 플래그들이 인식되어
extras 가 비어야 함)을 고정한다. 오늘은 extras 가 비어있지 않으므로(=인식 안 됨) FAIL → 버그 증명.
고쳐지면 PASS → strict 가 trip. 파싱 계층(parse_known_args)만 때리므로 서버/Neo4j 불필요.
"""
import pytest

from lakatos.cli import _build_parser


# add_observation 이 노출하지만 CLI 가 빠뜨린 rival/theory/longinus 증거 플래그(케밥 표기).
_EVIDENCE_FLAGS = [
    '--theory-basis', 'string theory',
    '--rival-name', 'RivalProgramme',
    '--rival-relation', 'contradicts',
    '--longinus-refs', '[]',
]

_BASE_ARGV = ['observation', 'T', 'root', 'evt-1']


# [BUG 2026-06-27] #21 — defect axis (negative oracle): CLI observation 가 rival/theory 플래그를 인식해야 함.
# [FIXED 2026-06-27] #21 — green regression (cli observation subparser exposes rival/theory/longinus args)
def test_observation_subparser_exposes_rival_theory_evidence_args():
    # 실제 CLI 파서(_build_parser)를 호출 — 모킹 없음, 진짜 argparse 표면을 탄다.
    parser = _build_parser()
    # parse_known_args 는 인식 안 되는 옵션을 SystemExit 없이 extras 로 돌려준다.
    ns, extras = parser.parse_known_args(_BASE_ARGV + _EVIDENCE_FLAGS)
    # 사전조건: 기본 위치 인자는 정상 파싱(서브커맨드 자체는 존재).
    assert ns.cmd == 'observation' and ns.name == 'T' and ns.tag == 'root'
    # 올바른(fix 후) 동작: 모든 증거 플래그가 인식되어 extras 는 비어야 한다.
    # 오늘 동작: extras 에 --theory-basis/--rival-name/... 가 그대로 남는다(표면 결손=버그).
    assert extras == [], f"CLI observation 이 rival/theory 증거 인자를 거부함: {extras!r}"


# [GREEN] #21 — mechanism/positive oracle: observation 서브파서와 기존 신뢰 필드는 살아있다.
def test_observation_subparser_parses_existing_trust_fields():
    # 메커니즘 가드: 서브커맨드가 존재하고 기존 url/trust 계열은 정상 인식됨(extras 비어야 함).
    parser = _build_parser()
    ns, extras = parser.parse_known_args(
        _BASE_ARGV + ['--url', 'https://x', '--trust', '0.7', '--source-type', 'web'])
    assert ns.cmd == 'observation'
    assert ns.url == 'https://x' and ns.trust == 0.7 and ns.source_type == 'web'
    assert extras == [], f"기존 observation 필드가 인식 실패: {extras!r}"
