"""라카토트리 하네스 — 상계·하계·인간·agent 를 한 연구 사이클로 엮는 오케스트레이터.

엮는 대상(사용자 사양 "싹다"):
  상계(read-only): 인터넷 정보(WebSearch/WebFetch) — 신뢰가중(TrustRank/EigenTrust)
  하계(read-write): bash 스크립트·TDD·실행파일·코드·KG·DB·git 이력
  인간+agent: 프롬프트·질문·코멘트·평가·의문(critique, Dung 논증)
  순수 agent: 코드 빌딩(build_cmd) + 채점(judge_cmd)

한 사이클 = 프로메테우스가 상계서 불(지식)을 read 해 하계에 write 하고 인간/agent 가 비판하는 과정.
포트-어댑터(주입): 프로덕션=실 HTTP/bash/git/web, 테스트=mock. 헥사고날 = 순수 이성구조(P3).
# KG: span_lakatotree_harness / SA_LakatoTree_Server_20260612
"""
import hashlib
import re
from dataclasses import dataclass, field


class BuildFailed(Exception):
    """하계 ground-truth 게이트 — 빌드/TDD 실패 시 채점·판결 중단."""


class ScoringRefused(Exception):
    """채점 게이트 — 서버가 채점을 거부(error/4xx)하거나 verdict 가 안 났으면 사이클 중단.

    BuildFailed 의 형제(M2 적대감사 2026-06-25): fail-loud 의 default 를 역전한다 —
    raise 가 default, 삼킴은 명시 정책. judge 거부(admissibility 위반 등)를 조용히 삼켜
    verdict=None 인데 exit 0(green) + stands=True 로 끝나는 가짜 green 을 차단.
    """


@dataclass
class CycleSpec:
    tree: str
    tag: str
    parent: str
    metric: str
    baseline: float
    direction: str = 'lower'
    noise_band: float = 0.0
    novel_metric: str | None = None
    novel_direction: str | None = None
    novel_threshold: float | None = None
    novel_measured: float | None = None  # prom-honesty/2: novel target 의 *독립* 측정값 — 없으면 novel 미주장
                                         #   (metric 재활용 금지). novel_metric 등록 시 judge 가 독립 측정 강제.
    novel_sha: str | None = None         # prom-honesty/sha: novel 측정의 출처(채점 sha 와 다르면 같은 metric 도 독립)
    build_cmd: str | None = None         # 하계: 빌드/TDD/실행 (ground truth 게이트)
    judge_cmd: str | None = None         # 하계: metric=<수> 출력하는 채점 스크립트
    judge_script: str | None = None      # 채점 스크립트 경로 (sha256 무결성)
    internet_sources: list = field(default_factory=list)   # 상계: [(url, trust|None)]
    human_critiques: list = field(default_factory=list)    # [(arg_id, attacks, by, kind, body)]
    algorithm: str = ''
    comment: str = ''


def _parse_metric(stdout: str) -> float:
    """채점 스크립트 stdout 에서 'metric = <수>' 추출 (LLM 점수 금지, 순수 파싱)."""
    m = re.search(r'metric\s*[=:]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', stdout)  # 과학적 표기 보존(OPS-COR-1)
    if not m:
        raise ValueError(f'채점 출력에 metric=<수> 없음: {stdout[:80]}')
    return float(m.group(1))


class LakatoHarness:
    """주입된 포트로 한 라카토트리 사이클을 엮어 실행. 모든 계·행위자 관통."""

    def __init__(self, http, run_bash, read_internet=None, git_sha=None):
        self._http = http               # 하계 read-write: KG/DB (서버 API)
        self._bash = run_bash           # 하계 read-write: bash 실행 → (stdout, exit)
        self._internet = read_internet  # 상계 read-only: (url, prompt) → (content, trust)
        self._git = git_sha or (lambda: None)

    def run_cycle(self, s: CycleSpec) -> dict:
        """연구 사이클 오케스트레이터 — 각 realm/phase 를 자기 메서드에 위임(아래 _upper_internet/
        _register_node/_build_gate/_measure/_submit_and_judge/_critiques_and_standing). 전엔 한
        메서드에 6 phase(상계 read·하계 write/build/measure/write·인간 critique·이력)가 inline 융합."""
        prov: dict = {'tree': s.tree, 'tag': s.tag, 'realms': {}}

        evidence, trust = self._upper_internet(s)
        prov['internet_evidence'] = evidence
        prov['source_trust'] = trust
        prov['realms']['상계_read'] = len(evidence)

        sha = self._register_node(s)

        build = self._build_gate(s)              # BuildFailed 면 여기서 raise(사이클 중단)
        if build is not None:
            prov['build'] = build

        metric = self._measure(s)
        prov['metric'] = metric

        res = self._submit_and_judge(s, metric, sha, trust)
        # 채점 게이트(M2) — fail-loud default: 서버가 채점을 거부(error/4xx)했거나 verdict 가 안 났으면
        #   조용히 삼키지 말고 즉시 raise. 거부 코드/상세는 prov 에 기록(증거 보존, BuildFailed 와 대칭).
        if isinstance(res, dict) and res.get('error') is not None:
            prov['scoring_refused'] = {'error': res.get('error'), 'detail': res.get('detail')}
            raise ScoringRefused(f'서버 채점거부(error {res.get("error")}) — verdict 미생성. '
                                 f'{str(res.get("detail"))[:120]}')
        verdict = res.get('verdict') if isinstance(res, dict) else None
        if verdict is None:
            prov['scoring_refused'] = {'error': None, 'detail': 'verdict 미생성(채점 미성립)'}
            raise ScoringRefused(f'채점 미성립 — verdict=None. 응답: {str(res)[:120]}')
        prov['verdict'] = verdict
        prov['novel'] = res.get('novel')
        prov['delta'] = res.get('delta')

        prov['standing'] = self._critiques_and_standing(s)

        prov['git_sha'] = self._git()            # 이력: git sha(코드 버전 관통)
        prov['realms']['하계_write'] = True
        return prov

    # ── 사이클 phase (각 realm/단계 = 자기 메서드, 한 의미) ──────────────────────────
    def _upper_internet(self, s: CycleSpec) -> tuple[list, float]:
        """상계(read-only) — 인터넷서 지식 훔쳐 신뢰가중. (evidence, 평균 source_trust)."""
        evidence, trust = [], 1.0
        if s.internet_sources and self._internet:
            for url, seed_trust in s.internet_sources:
                content, t = self._internet(url, f'{s.tree}/{s.tag} 근거: {s.comment}')
                tw = seed_trust if seed_trust is not None else t
                evidence.append({'url': url, 'trust': round(tw, 3), 'excerpt': content[:160]})
            trust = round(sum(e['trust'] for e in evidence) / len(evidence), 3)
        return evidence, trust

    def _register_node(self, s: CycleSpec) -> str | None:
        """하계(write) — 노드 생성 + 구조적 예측 사전등록. 채점 스크립트 sha 반환."""
        sha = None
        if s.judge_script:
            try:
                sha = hashlib.sha256(open(s.judge_script, 'rb').read()).hexdigest()
            except OSError:
                sha = None
        self._http('POST', f'/api/tree/{s.tree}/node',
                   {'tag': s.tag, 'parent': s.parent, 'algorithm': s.algorithm, 'comment': s.comment})
        self._http('POST', f'/api/tree/{s.tree}/node/{s.tag}/prediction', {
            'metric_name': s.metric, 'direction': s.direction, 'baseline_value': s.baseline,
            'noise_band': s.noise_band, 'novel_metric': s.novel_metric,
            'novel_direction': s.novel_direction, 'novel_threshold': s.novel_threshold,
            'judge_script_sha': sha})
        return sha

    def _build_gate(self, s: CycleSpec) -> dict | None:
        """하계(execute, ground truth) — 빌드/TDD. 실패면 BuildFailed 로 사이클 중단(채점 전)."""
        if not s.build_cmd:
            return None
        out, code = self._bash(s.build_cmd)
        info = {'cmd': s.build_cmd, 'exit': code, 'tail': out[-120:]}
        if code != 0:
            raise BuildFailed(f'빌드/TDD 실패(exit {code}) — 채점 중단. {out[-120:]}')
        return info

    def _measure(self, s: CycleSpec) -> float | None:
        """하계(execute, measure) — 채점 스크립트 실행 → metric."""
        if not s.judge_cmd:
            return None
        out, code = self._bash(s.judge_cmd)
        # 나생문 #24: 채점 스크립트 종료코드 검사(_build_gate 와 대칭) — 비정상 종료한 judge 가 'metric=' 한 줄
        #   출력했다고 유효 외부측정으로 수용하면 측정 신뢰경계가 샌다. exit≠0 = 측정 거부(fail-loud).
        if code != 0:
            raise BuildFailed(f'채점 스크립트 비정상 종료(exit {code}) — metric 수용 거부. {out[-120:]}')
        return _parse_metric(out)

    def _submit_and_judge(self, s: CycleSpec, metric, sha, trust) -> dict:
        """하계(write) — test_result 제출 → 판결(judge + 인터넷 신뢰 결합)."""
        # prom-honesty/2 (적대감사 2026-06-20): metric 재활용 금지 — novel_measured 는 *독립* 측정(s.novel_measured)
        #   만 보낸다. novel_metric 을 등록했으면 독립 측정값을 줘야 하고(없으면 judge 가 P2 로 거부), 줄 게
        #   없으면 애초에 novel 을 주장하지 않는다(개선만이면 honest 하게 partial). 개선 측정 1개로 progressive 공짜 금지.
        return self._http('POST', f'/api/tree/{s.tree}/node/{s.tag}/test_result', {
            'metric_value': metric, 'script': s.judge_script or s.judge_cmd or 'inline',
            'script_sha': sha, 'novel_measured': s.novel_measured, 'novel_sha': s.novel_sha,
            'source_trust': trust})

    def _critiques_and_standing(self, s: CycleSpec) -> dict:
        """인간+agent(critique) — 의문/반박 등재 → 정당성(Dung grounded extension) standing."""
        for arg_id, attacks, by, kind, body in s.human_critiques:
            self._http('POST', f'/api/tree/{s.tree}/node/{s.tag}/critique',
                       {'arg_id': arg_id, 'attacks': attacks, 'by': by, 'kind': kind, 'body': body})
        return self._http('GET', f'/api/tree/{s.tree}/node/{s.tag}/standing')
