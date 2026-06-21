"""베이즈 신뢰도 층 — 라카토스/라우든 위의 '수학적 심장'.

판결(judge)은 이산(progressive/rejected), 라우든(laudan)은 문제수지.
베이즈는 그 사이 **연속층**: 각 판결을 증거로 보고 가지의 사후 신뢰도를 갱신.
→ 강한 가지(자산 많음=과거 진보 누적)는 반례 하나로 안 죽는다 (사용자 직관의 수학화).

증거력 = P(E|진보 프로그램) / P(E|퇴행 프로그램) = Bayes factor.
  progressive (사전등록 novel 적중): 퇴행 프로그램에선 잘 안 나옴 → BF 큼
  partial (개선이나 사후 땜빵):       둘 다에서 흔함 → BF ≈ 1+
  rejected (악화):                    음의 증거 → BF < 1
효과크기(|delta|/noise)로 BF 를 1에서 더 멀리/가깝게 (마진 개선 < 대폭 개선).

엄격도 스택: 포퍼(judge 이산) > 베이즈(본 모듈, 연속) > 라우든(laudan, 문제수지).
한계 정직(사용자 정리 #10): ①사전확률 주관 → prior 명시 인자(감사 가능) ②새 가설 탄생은
  베이즈 범위 밖 → frontier/directions(가설공간 확장)가 담당, 베이즈는 within-tree 신뢰도만.
# KG: span_lakatotree_bayes
"""
import math
from lakatos.trust import evidence_weight
from lakatos.grounding import GROUNDED, interpret_bayes_factor

# 판결별 기본 Bayes factor — 값은 grounding 정본서 (Jeffreys 1961 / Kass-Raftery 1995 근거).
#  progressive=6.0(Jeffreys substantial 밴드), rejected=1/6(log-odds 대칭, F-MATH-2),
#  partial/equivalent=1.0(무정보, 누적금지 F-MATH-1). 야매 아님 — grounding.provenance 참조.
BF_BASE = {'progressive': GROUNDED['bf_progressive']['value'],
           'partial': GROUNDED['bf_partial_equivalent']['value'],
           'equivalent': GROUNDED['bf_partial_equivalent']['value'],
           'rejected': GROUNDED['bf_rejected']['value'],
           # THR-1: dialectical 판결도 명시 — 전엔 .get default 1.0(neutral) 로 degenerating 이
           # 음의 증거인데 신뢰도에 무영향이었다. degenerating=rejected 급 음의 증거,
           # withdrawn(철회)·progressive_conditional(미확증)=무정보(1.0, 누적금지).
           'degenerating': GROUNDED['bf_rejected']['value'],
           'withdrawn': GROUNDED['bf_partial_equivalent']['value'],
           # AXIS-CORR: different_programme(hard_core 위반)은 *정체성 축* 사건 — within-tree
           # likelihood(이 프로그램이 진보/퇴행?)의 *범위 밖*(frontier event, bayes.py:14-15 한계#2).
           # 그래서 BF=1.0(무정보, 누적금지): degenerating(1/6, 진보축 음의증거)처럼 깎으면 두 축을
           # 다시 섞는 곡해. 1.0 은 'evidence 가 두 프로그램 공통'이라서가 아니라 *모델 범위 밖*이라서다.
           # withdrawn(off-axis 철회)과 동형 그룹. ★범위 면책(line 14-15)을 고치지 않는 한 BF<1 승격 금지.
           'different_programme': GROUNDED['bf_partial_equivalent']['value'],
           'progressive_conditional': GROUNDED['bf_partial_equivalent']['value']}
DEFAULT_PRIOR = GROUNDED['default_prior']['value']        # 무차별 원리 (Laplace 1814)
ABANDON_CREDENCE = GROUNDED['abandon_credence']['value']  # odds 1:9 폐기 문턱
EFF_CAP = GROUNDED['eff_cap']['value']                    # 효과크기 상한 (Cohen d=4=large×5)
WEIGHT_FLOOR = GROUNDED['weight_floor']['value']          # 마진 개선 최소 증거력


def interpret(bf: float) -> dict:
    """Bayes factor → 문헌 등급(Jeffreys + Kass-Raftery). 점수의 해석(raw 숫자 금지)."""
    return interpret_bayes_factor(bf)


def effect_size(delta: float, noise_band: float,
                floor: float = GROUNDED['effect_size_floor']['value']) -> float:
    """증거 강도 = |delta| / max(noise_band, floor). 큰 개선 = 강한 증거."""
    return abs(delta) / max(noise_band, floor)


def bayes_factor(verdict: str, delta: float = 0.0, noise_band: float = 0.0,
                 source_trust: float = 1.0) -> float:
    """판결 + 효과크기 + 인터넷 출처신뢰 → Bayes factor. 권위 출처 = 강한 증거(P1).
    equivalent=1(무정보). source_trust 가 log(BF) 를 evidence_weight 로 감쇠 — 저신뢰도 증거는 약하게."""
    base = BF_BASE.get(verdict, 1.0)
    if base == 1.0:
        return 1.0
    es = min(effect_size(delta, noise_band), EFF_CAP) / EFF_CAP   # 0..1
    w = max(es, WEIGHT_FLOOR) * evidence_weight(source_trust)   # ★출처신뢰 결합
    return math.exp(math.log(base) * w)   # base>1 → BF>1, base<1 → BF<1


def branch_credence(verdicts: list, prior: float = DEFAULT_PRIOR,
                    source_trust_map: dict | None = None) -> float:
    """판결 시퀀스 → 사후 신뢰도. odds 곱셈(베이즈 갱신) + use-novelty 상관보정.

    ★use-novelty 독립성 보정 (Zahar 1973, grounding.SOURCES['zahar1973']): 진보의 증거력은
    *새로운(novel)* 사실의 확증에서 나온다. 같은 타깃(`target`, = 닫는 질문/novel target 정체성)을
    반복 확증해도 초과경험내용은 늘지 않는다(ρ=1 완전상관 가정) → 그건 독립증거가 아니라 같은
    증거의 재측정. 따라서 BF>1(확증) 방향에서 같은 target 의 기여는 *단일 최강 확증(max BF)*으로
    집계한다(content-dedup; max 라 입력순서 무관=commutative, 단일 BF 라 수렴). 전엔 모든 판결 BF 를
    무조건 곱해(조건독립 오가정) 같은 progressive 10번 → credence 0.63→~1.0 인위확신이었다.

    비대칭(Popper): 음의 증거(rejected/degenerating, BF<1)와 무정보(BF=1)·target 미지정은 *매번*
    누적한다 — 반례는 매 회 독립적 부담이어야 약한 가지가 죽는다(할인하면 should_abandon_bayes 무력화).
    ※ metrics.false_progressive_screen(BH/Bonferroni)와 중복 아님: 그건 *가지 간 family-level* 다중비교
    보정(progressive 개수), 이건 *가지 내* 같은-타깃 반복 상관 보정 — 직교 축.

    target 키가 없으면(현 호출자 대부분) None → 항상 novel 취급(할인 없음) = 기존 동작 비트동일.
    source_trust_map (P6): {source: global_trust} 주면 판결의 `source` 를 eigentrust 글로벌 신뢰로 가중.
    단조: novel target 추가/더 강한 확증은 비감소. 반환 (0,1] — 약 25개+ distinct *최대강도*(BF=6 포화)
    확증이면 float odds 가 포화해 정확히 1.0 에 도달한다(n=20→0.99999…998, n≥25→1.0). 실 트리 정본경로
    깊이(보통 ≤15, 그나마 전부 최대강도도 아님)로는 미도달 — 이 임계와 '깊이로는 미도달'을 test_doc_honesty
    가 고정(hedge→tested). prom-honesty/5: 옛 '[0,1)'은 이 포화를 부정하는 과장이라 (0,1] 로 정정.
    dedup 은 같은 타깃 반복을 max 1회로 접어 이 포화를 *완화*한다.
    """
    odds = prior / (1 - prior)
    best_log_bf: dict = {}   # target → max log(BF) (BF>1 content-dedup)
    for v in verdicts:
        st = v.get('source_trust', 1.0)
        if source_trust_map and v.get('source') in source_trust_map:
            st = source_trust_map[v['source']]   # ★고유벡터 글로벌 신뢰로 대체
        bf = bayes_factor(v['verdict'], v.get('delta', 0.0), v.get('noise_band', 0.0), st)
        tgt = v.get('target')
        if bf > 1.0 and tgt is not None:
            lb = math.log(bf)
            if lb > best_log_bf.get(tgt, 0.0):   # 같은 target → 최강 확증만(재확증=초과내용 0)
                best_log_bf[tgt] = lb
        else:
            odds *= bf   # 음의/무정보/target 미지정 = 매번(반례 독립부담·기존 동작 보존)
    for lb in best_log_bf.values():
        odds *= math.exp(lb)
    # prom-honesty/5 (적대감사 2026-06-20, 정정): distinct 강확증 다수에서 float odds 가 포화해 정확히
    #   1.0 을 반환할 수 있다 → docstring 을 [0,1) 에서 (0,1] 로 정정(상한 1.0 포함). 과장 제거.
    return odds / (1 + odds)


def should_abandon_bayes(verdicts: list, prior: float = DEFAULT_PRIOR,
                         threshold: float = ABANDON_CREDENCE,
                         source_trust_map: dict | None = None):
    """신뢰도 기반 폐기 — 강한 가지는 반례 하나로 안 죽고, 약한 가지는 누적되면 죽는다.

    laudan.should_abandon(이산 3규칙)의 연속·증거가중 버전. 둘 다 쓰면:
    laudan = 해석 가능한 휴리스틱, bayes = 자산 가중 연속 신뢰도.
    source_trust_map (A2): 정본경로와 동일하게 가지 폐기판정도 eigentrust 글로벌 신뢰로 가중.
    """
    c = branch_credence(verdicts, prior, source_trust_map=source_trust_map)
    return c < threshold, c
