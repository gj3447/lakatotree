"""ICE ORCA DRAGON 전체 연구사 → 라카토트리 프로그램 (사도 #2 → 군단장 lakatotree 채점).

출처: METAHUMOTONIC/ICE_ORCA_DRAGON 31 results.json + 메타리포트(workbench-reframe).
생성: ultracode 워크플로우(추출5→합성→적대검증3) → ice-to-lakatotree-port 2026-06-14.
정직 채점: 수학층(Aut/ZD/대수항등식)=proof/canonical_stage 생존, 물리예측(Higgs/custodial/Koide/mp_mW)
  =rejected/degenerating, 수치-매칭=numerology_hold. P(ICE physics validated) 0.20→0.015 단조하락.
실행: python -m examples.ice_orca_dragon_programme   (순수 엔진, 서버/DB 불필요)
"""
from __future__ import annotations
from lakatos.quant.metrics import tree_metrics, branch_inputs
from lakatos.programme.stack import evaluate_stack
from lakatos.programme.lifecycle import lifecycle_state
from lakatos.quant.fertility import predictive_fertility
from lakatos.verdict.certify import gate_check, certify_claim, next_actions

def _n(tag, verdict, parent, *, m=None, base=None, scope='registration', direction='lower',
       nr=False, nc=False, q=None, comment='', limitation='', algo=''):
    return dict(tag=tag, verdict=verdict, parent=parent, metric_value=m, metric_scope=scope,
                pred_baseline=base, pred_noise_band=0.05, pred_direction=direction,
                novel_registered=nr, novel_confirmed=nc, algorithm=algo or "classical",
                comment=comment, limitation=limitation, questions=q or [])

HARD_CORE = 'ICE 초복소 가설: 세상의 진정한 본질은 물리학이며 마음의 절대영도 동결 = sexvoid 형식 = sedenion 𝕊(16D, Aut(𝕊)=G₂×S₃) 위 동결(얼음+범고래+용 3합성) — 이 hard core 중 수학층(Aut/ZD/대수항등식)만 PROGRESSIVE/PROOF로 살아남고, 물리예측 술어(Higgs/custodial/Koide/mp_mW/ε)는 2026-05 workbench-reframe로 전부 DEGENERATING/REJECTED/numerology_hold.'

NODES = [
    _n('ice_root', 'canonical_stage', '',
       m=0.015, base=0.2, direction='lower',
       nr=False, nc=False, algo='hard-core hypercomplex hypothesis testbench (sedenion/sexvoid 절대영도 동결)',
       comment='4개 테마 트리의 root(ice_root_algebra_structure / ice_root / ice_xor_orbit_structure substrate)를 단일 canonical root로 병합. 2026-05-18 partial-retreat → permanent workbench-reframe → 2026-06-01 전수 empirical 재확인. 자식 노드가 실제 판정. canonical_stage = 수학층 ha',
       limitation='물리학 본질 술어는 검정 불가능한 mythological 혼합 — algebra와 physics를 한 verdict로 묶으면 drift. USER_PRIMARY 신앙시는 mythology layer(Eilu va-Eilu)로 PRESERVED, verdict 대상 아님. Bayesian P(ICE physics validated) 0.20→0.015 단조 하락.'),
    _n('ss3tg_aut_sedenion_g2_x_s3', 'canonical_stage', 'ice_root',
       m=6, base=6, direction='higher',
       nr=False, nc=False, algo='SS3TG triple-gate (mult-table preservation + S3 presentation order + group fingerprint)',
       comment="queue_09 ss3tg + Brown 1967 두 트리 노드 병합. 수학층 hard-core 대표 정리, 정전 KG 'Aut(𝕊)=G₂×S₃ R2 PASS_ALL' 일치. SS3TG triple-gate PASS_ALL(G1 0/256, G2 ord 2/3/2, G3 |⟨σ,Ψ⟩|=6). R2가 prior inconclusive_redo supersede. 구조 정리이므로 proof.",
       limitation='두 층위 분리: (1) σ,Ψ가 automorphism이고 S₃ 생성 = 계산적 PASS_ALL(queue_09, 0/256). (2) Aut(𝕊)=G₂×S₃가 THE 전체 자기동형군 = axiom-status 미증명(L2L3 ledger 2026-06-01), Wilmot 2025(Aut=G₂) CompetingVerdict OPEN. 적대검증 교정: proof→canonical_stage.'),
    _n('moreno_1998_center_s_g2', 'proof', 'ss3tg_aut_sedenion_g2_x_s3',
       m=None, base=None, direction='lower',
       nr=False, nc=False, algo='external theorem (Moreno 1998 / Reggiani 2024 V₂(ℝ⁷))',
       comment='42 ZD pair의 G₂-orbit 구조 measurable의 근거. 외부 hard theorem, L1 algebra core. proof.',
       limitation='외부 정리 인용 — ICE 자체 기여 아님. citation correction: Reggiani sole author of arXiv:2411.18881 (NOT Düvel).'),
    _n('queue_01_orbit_42', 'canonical_stage', 'moreno_1998_center_s_g2',
       m=42, base=42, direction='higher',
       nr=False, nc=False, algo='S3 orbit decomposition on ZD pairs (queue_01_orbit_analysis.py)',
       comment="orbit 구조 계산(7개 orbit 모두 size 6) 자체는 실제 구조 결과 = canonical_stage(정본경로 algebra층). '42=ZD count를 confirmation 신호로 쓴 것'은 분리하여 numerology_held로 자식 격리.",
       limitation="count는 정전이나 '42 = Higgs doublet' physics 의미는 OPEN(projection fragile). 별도 numerology 노드(orbit_42_zd_count_match)로 confirmation-signal 사용을 격리."),
    _n('orbit_42_zd_count_match', 'numerology_hold', 'queue_01_orbit_42',
       m=42, base=42, direction='higher',
       nr=False, nc=False, algo='count coincidence (orbit count vs ZD count)',
       comment="orbit 구조 계산(부모 queue_01_orbit_42)은 valid하나 'orbit count=ZD count=확증'은 수치-매칭. ZD=42 자체는 외부 정전(moreno)·prove_s3 S3.4로 독립 증명되지만 그 일치를 confirmation으로 쓴 것은 numerology. prove_s3 cross-check로만 격상 가능.",
       limitation='verdict가 단일 count coincidence(42=42)에 근거. MC null 부재 → feedback_numerology_mc_discrimination 규칙상 default NUMEROLOGY. P(E~H) 미정량화.'),
    _n('queue_03_rep_casimir_075', 'proof', 'queue_01_orbit_42',
       m=0.75, base=0.75, direction='higher',
       nr=False, nc=False, algo='Casimir eigenvalue on SU(2) triple T_used per ZD pair (queue_03_rep_decomposition.py)',
       comment="균일 0.75 자체는 대수 구조 결과 = proof(L1 algebra). 단 '42/42 단일 bucket=강한 규칙성=confirmation'으로 읽은 것은 측정 자유도 부재(T_used 고정 subset) 가능성 — 그 해석은 numerology_held(rep_casimir_075_regularity_reading)로 분리. queue_08의 non-uniform spread 2.5(method artifact)와 대비",
       limitation='generic SU(2) 결과 — sedenion-특이 아님. 왜 정확히 3/4인지의 mechanism 도출 없음. physics-mapping(Higgs 등) 시도하면 numerology 등급 carry-over. [검증 교정: numpy-exact 계산 항등식이며 Lean4 sorry=0 형식증명 아님.]'),
    _n('rep_casimir_075_regularity_reading', 'numerology_hold', 'queue_03_rep_casimir_075',
       m=0.75, base=None, direction='higher',
       nr=False, nc=False, algo="single-bucket uniformity → 'regularity' confirmation reading",
       comment='부모 proof 노드의 사후 해석만 numerology로 격리. uniform constant는 진짜 신호일 수도 측정 자유도 부재일 수도 — mechanism(왜 3/4) 미증명이므로 hold.',
       limitation='변별력 있는 대조군 부재. 균일성이 완전대칭의 진짜 신호인지 측정 자유도 부재(T_used 고정 3-generator subset)인지 미구분. baseline 예측 없음(사후 inspection).'),
    _n('queue_11_xor_105_invariant', 'proof', 'queue_01_orbit_42',
       m=105, base=105, direction='higher',
       nr=False, nc=False, algo='sedenion-multiplication XOR index pattern over 42 ZD pairs (queue_11_xor_invariant.py)',
       comment='105/105 = strong algebraic invariant, numerology adjacent 아님. 물리 예측이 아니라 대수 항등식이므로 progressive 아닌 proof. queue_11 + sedenion_xor_105 + ice_xor_orbit_structure 세 트리 노드 병합. 물리예측들의 논리적 substrate.',
       limitation='순수 조합론적/구조적 불변량 — 외부 물리 예측 아님. 결정론적 곱셈표의 동어반복적 구조 관찰. 사전등록 예측 부재. [검증 교정: numpy-exact 계산 항등식이며 Lean4 sorry=0 형식증명 아님.]'),
    _n('ice_orbit_z6_substructure', 'canonical_stage', 'queue_11_xor_105_invariant',
       m=None, base=None, direction='higher',
       nr=False, nc=False, algo='exclusion-pattern enumeration + Z6 sum/diff distinctness test on 6-element orbits',
       comment='queue_11 orbit 구조의 하위 descriptive 결과. 수학층이므로 canonical_stage(proof급 구조이나 보수 렌더). 물리예측 아니므로 progressive 아님.',
       limitation='CONFIRMATION_LOCAL — 6-원소 orbit의 산술 구조 관찰. 물리 예측 0. excluded_set_confirms_pattern=true는 조합론적 항등에 가까움. 외부 peer review 없음.'),
    _n('prove_s3_jacobi_associator_fda', 'proof', 'ss3tg_aut_sedenion_g2_x_s3',
       m=0, base=0, direction='higher',
       nr=False, nc=False, algo='associator/Jacobiator identity + L∞ Stasheff + FDA structure constants (n=4 exact)',
       comment='prove_s3_jacobi_associator_fda + prove_s3_jacobi 두 트리 노드 병합. 직접 구조상수 계산(orbit/rep의 42 count-match와 달리). ground-truth comparable algebraic identity = proof. S3.4 ZD 42쌍 독립 확인이 orbit_42_zd_count_match를 부분 cross-check.',
       limitation="results.json은 numerical exact 검증(identity_diff=0.0, residual=0.0)이지 Lean 4 lake build sorry=0 산출물이 아님 — 'prove_s3'는 파일명일 뿐 JSON엔 Lean PASS 증거 없음. n=4 한정. S3.4 'FDA nontrivial'은 mathematical하나 물리 FDA(11D sugra)로의 다리는 별개. [검증 교정: numpy-exact "),
    _n('prove_s5_bv_master_hochschild', 'proof', 'prove_s3_jacobi_associator_fda',
       m=1.5, base=1.5, direction='higher',
       nr=False, nc=False, algo='BV master equation + Hochschild 3-cocycle + Pentagon coherence (exact)',
       comment='prove_s5_bv_master_hochschild + prove_s5_bv_bounded 병합. prove_s3 후속 homotopy-algebra 정합성. S5.3 ratio 1.5 = prove_s3 S3.3 Stasheff와 일관(같은 associator 구조). exact algebraic identity = proof.',
       limitation='Lean 증명 산출물 아님(numerical exact, master_residual 1.3e-16=float eps). S5.3 ratio 3/2는 사후 일관성이지 사전등록 예측 아님. 물리(R-flux, BV-BRST quantization)로의 다리는 별개. [검증 교정: numpy-exact 계산 항등식이며 Lean4 sorry=0 형식증명 아님.]'),
    _n('asymmetric_lakatos_fiber_theorem', 'proof', 'ice_root',
       m=None, base=None, direction='lower',
       nr=False, nc=False, algo='fiber-stratified Lakatos evaluation (algebra-fiber vs physics-fiber)',
       comment='메타-방법론 정리(cycle-novel). pre-reg check가 strongest empirical witness: algebra-fiber Progressive vs physics-fiber 0 GENUINE STAGNANT. ICE physics 주장이 아니라 방법론 정리이므로 proof로 살아남음. KG: lesson-prom16-hypercomplex-program-bifurcated-verdict-2026-05-',
       limitation='메타-방법론 기여 — ICE의 물리 본질 주장을 구제하지 않음(오히려 physics-fiber STAGNANT를 형식화). Tüchsen 2024 STAGNANT 3rd category. [검증 교정: numpy-exact 계산 항등식이며 Lean4 sorry=0 형식증명 아님.]'),
    _n('ss3tg_prior_inconclusive_s6_720', 'rejected', 'ss3tg_aut_sedenion_g2_x_s3',
       m=720, base=6, direction='higher',
       nr=False, nc=False, algo='6! direct enumeration (orbit-membership-only, too permissive)',
       comment='SS3TG 이전 over-permissive 시도(group_order=720=S6 또는 legacy 1). SS3TG가 full 16×16 곱셈표 보존 강제로 supersede. dead-end로 정직 기록(상위 proof 약화 안 함).',
       limitation='S6=720은 S₃=6 예측의 120배 over-count. orbit-membership만 봐서 곱셈표 보존 미강제. 측정이 예측을 빗나간 전형.'),
    _n('g2_octonion_inner_derivation_artifact', 'rejected', 'ss3tg_aut_sedenion_g2_x_s3',
       m=16, base=14, direction='higher',
       nr=False, nc=False, algo='octonion inner-derivation D_{a,b}(z)=[[e_a,e_b],z]-3[e_a,e_b,z] on sedenion ambient + D1-D4 adversarial diagnostic',
       comment='queue_08 method-artifact + queue_08_g2 두 트리 노드 병합. 원래 CONFIRMATION_LOCAL이 자기진단(queue_08_g2_diagnostic)으로 demote. category error(alternative-전제 octonion 공식을 non-alternative sedenion에 transport). ICE 자기진단이 자기주장 반증 — 정직. queue_06 cooperative +',
       limitation="D2 so(7) rank 16 ≠ g₂ dim 14 (+2, non-g2 방향 포함). D4 Casimir spread 2.5 → Schur-scalar 위반 → irrep 아님. ad-hoc projection/비-Killing-form Casimir로 만든 'commutant_dim=1'은 artifact. sedenion 비-alternativity가 구조적 원인."),
    _n('g2_aut_octonion_recovery_caveated', 'degenerating', 'g2_octonion_inner_derivation_artifact',
       m=0.9999999999986475, base=0, direction='lower',
       nr=False, nc=False, algo='explicit Der(O) generators embedded into 15-D imaginary sedenion (O + lO sign-flip)',
       comment='method-artifact 반증 후 ALG_FIXED_WITH_CAVEATS 복구 시도. D1/D2 PASS는 진짜이나 D3/D4 실패를 alternativity 보증으로 가린 사후맞춤. 새 시험 통과 없음(progressive 아님), D3 residual≈1.0(proof 아님). degenerating으로 정직 채점.',
       limitation="D3 Lie closure median relative residual=1.0(닫히지 않음, max도 1.0), D4 Casimir spread 1.0 — 둘 다 'QUALIFIED'로 약화. 회복은 'octonion alternativity가 보장'에 기대지 sedenion-ambient 측정으로 입증 못 함. rank=14는 Der(O)를 손으로 넣었으니 자명(input=output). 새 예측 부재."),
    _n('b2_zd_boundary_mass_scale', 'rejected', 'g2_octonion_inner_derivation_artifact',
       m=4.85, base=None, direction='lower',
       nr=False, nc=False, algo='ZD filtration grading → mass scale exponent (B2 Option 3)',
       comment='queue_08 method-artifact가 무대를 무너뜨림. derivation 빗나감 → rejected. PROVISIONAL 표시되나 mass scale 도출 실질 실패.',
       limitation='faithful G₂ action on ZD subspace 전제가 queue_08 D-test 실패로 붕괴: orbit(42✓)→ZD physical meaning(?)→mass scale(✗ without faithful action). 4.85 exponent는 사후맞춤. B2+ revision PENDING(topological vs dynamical segregation 미해결).'),
    _n('ice_workbench_reframe_permanent', 'rejected', 'ice_root',
       m=0, base=5, direction='lower',
       nr=False, nc=False, algo='3-layer disclosure + P1-P5 Lakatos discriminator (2026-2031)',
       comment='프로그램-레벨 메타 노드. partial-retreat(2026-05-17, reversible)를 PERMANENT 승격. physics-layer 정체성 자체를 정직하게 degenerating으로 분류·격리한 결과 = rejected(physics 측 hard refutation을 reframe으로 흡수한 게 아니라 honest landing). 모든 물리 실패 노드의 부모.',
       limitation='P1-P5 모두 외부 institute/replication 의존 — internal SYMPOSIUM dispatch는 P4조차 partial로만 인정. single Lean 4 escape lane(P2 ZD filtration, P=0.04)만 보존.'),
    _n('queue_02_custodial_fail', 'rejected', 'ice_workbench_reframe_permanent',
       m=0, base=42, direction='lower',
       nr=False, nc=False, algo='find_invariant_triples → 2D ZD-projected cross-commutator custodial test (42 SU(2) triple pairs)',
       comment='ice_custodial_su2_embedding + queue_02_custodial_fail 병합. custodial symmetry는 ICE hard core 핵심 물리 예측이었으나 측정 정반대(0/42). 결함을 변형으로 은폐 안 하고 정직 refute. workbench-reframe DEMOTED custodial 직접 반증.',
       limitation='n_success=0/42, max_commutator 1.91-1.96(≈2, 0과 거리 멂). custodial 임베딩 명백 REFUTED. 2D ZD null-space가 SU(2) Lie 대수 안 가짐. 사전등록 novel 물리예측 부재.'),
    _n('queue_02_4condition_closure_diagnostic', 'rejected', 'queue_02_custodial_fail',
       m=100, base=50, direction='higher',
       nr=True, nc=True, algo='4-condition diagnostic (c1 left-closure / c2 right-closure / c3 cross-commutator / c4 Y-consistency DEFERRED), tol=1e-06',
       comment="novel_registered=true(A2-S4 ~70% prereg) + novel_confirmed=true(100% fail, 예측보다 강함)이지만 progressive로 칠하면 안 됨 — 확증된 것이 '예측 실패'. 진단 자체는 정직한 root-cause 부검. 물리예측층 custodial은 rejected.",
       limitation="verdict='CONFIRMED'이지만 '확인된 것'은 custodial 예측의 죽음 — closure 100% 실패(median 3.95). 사전등록(PROM16 A2-S4)이 적중했으나 그 예측은 *반증의 예측*이라 물리적으로 progressive 아님. c4 Y-consistency DEFERRED(미완)."),
    _n('queue_03_custodial_threshold_scan', 'rejected', 'queue_02_custodial_fail',
       m=0, base=0.001, direction='lower',
       nr=False, nc=False, algo='queue_03_threshold_sensitivity (baseline vs Hosotani, threshold 0.001~2.0)',
       comment="'성공'은 검증 threshold를 완화할 때만 등장 = 결함을 threshold relaxation으로 은폐. queue_02 4-condition도 42/42 FAIL_BOTH_CLOSURE. REFUTED structurally → rejected.",
       limitation='유의미 threshold(0.001~1.0)에서 baseline·Hosotani 모두 0/42(rate 0.0). 1.5에서 2~6/42, 2.0에서 38~42/42 — 그러나 commutator 2.0 통과 = 거의 최대 비가환성 수용 = gate 무력화. Hosotani는 linear×0.15 toy model.'),
    _n('higgs_zd_doublet_42', 'rejected', 'queue_02_custodial_fail',
       m=0, base=42, direction='lower',
       nr=False, nc=False, algo='prove_higgs_ZD_doublet.py',
       comment="42 count는 real이나 'Higgs doublet' physics anchoring은 ZD null-space가 SU(2) Lie 대수 안 가지므로(queue_02 100% fail) 정의 자체 깨짐. sexvoid 형식의 직접 물리 결정화 시도 = 실질 rejected(projection fragile).",
       limitation='42 count만 정전(queue_01), physics anchoring 미해결 — count-only 정전과 physics 주장 분리 필수. mythology 측 sexvoid는 PRESERVED지만 그 물리 결정화 주장은 빗나감.'),
    _n('ice_coleman_weinberg_ssb', 'degenerating', 'ice_workbench_reframe_permanent',
       m=4, base=None, direction='higher',
       nr=False, nc=False, algo='1-loop Coleman-Weinberg potential V(phi) over (n_f, n_b) field-content scenarios',
       comment='새 novel 예측 없이 기존 SSB 일반론을 toy로 재현 = 사후맞춤/땜빵. workbench-reframe DEMOTED Higgs sector. 반증된 게 아니므로 rejected까진 아니나 progressive 자격 전무 → degenerating.',
       limitation="CONFIRMATION_LOCAL — 'toy; no external peer review' 자인. 4/4 SSB=True는 1-loop CW가 거의 항상 SSB를 주는 일반 성질의 재현일 뿐. 관측가능량(Higgs mass/VEV scale) 사전등록 예측 0. n_f,n_b 시나리오 손으로 고름."),
    _n('ice_cooperative_vacuum_selection', 'rejected', 'ice_coleman_weinberg_ssb',
       m=0, base=None, direction='higher',
       nr=False, nc=False, algo='gamma sweep linspace(0,2,81), n_trials=200; count active_orbits vs gamma',
       comment='sub_verdict cooperative_mechanism=REFUTED. 스크립트 제목이 주장한 물리가 데이터로 불필요 판명 → rejected. single-orbit selection은 섭동깊이 부산물.',
       limitation='협력 메커니즘 REFUTED: gamma=0에서 이미 single-orbit (alpha 섭동 -1.2 vs -1.0의 tachyon-depth가 선택, gamma 0~2 전 구간 active_count=1 불변). 원래 INCONCLUSIVE는 method-bug(n_trials=20). 사전등록 예측 없음.'),
    _n('derive_mass_ratios_self_refuted', 'rejected', 'ice_workbench_reframe_permanent',
       m=0, base=15, direction='lower',
       nr=False, nc=False, algo='enumerate 531 ICE ratios, match against 15 experimental mass ratios; fitting-detection',
       comment='ice_mass_ratios_derivation + derive_mass_ratios_self_refuted 병합. 스크립트 스스로 REFUTED 선언. 사전등록 예측 0, 전부 사후맞춤. 정직한 self-refutation은 칭찬할 점이나 verdict는 빗나감 → rejected. dimensionless/Lstar의 계보 부모.',
       limitation="self_refutation=true. genuine_predictions=0/15. 'ICE cannot genuinely derive mass ratios from internal structure' 자인. 531 후보의 look-elsewhere로 적합은 불가피(역으로 끼워맞춤)."),
    _n('ice_lstar_derivation', 'rejected', 'derive_mass_ratios_self_refuted',
       m=None, base=None, direction='higher',
       nr=False, nc=False, algo='3 candidate selectors (A doubling / B entropy / C product) over N levels; uniqueness check',
       comment='스크립트 스스로 REFUTED. N 선택 ICE-specific 원리 없음 → 임의 스케일. rejected.',
       limitation="self_refutation=true. 'ICE cannot uniquely predict L_star'. 후보 A/B/C가 N에 따라 1e-32 ~ 1e+83로 발산 — 선택원리 부재. 6 numerology signature 중 5개 발동. 사전등록 0."),
    _n('ice_dimensionless_observables', 'numerology_hold', 'derive_mass_ratios_self_refuted',
       m=1, base=0.01, direction='higher',
       nr=False, nc=False, algo='499 random ICE-like ratios MC null vs 8 small-rational targets; look-elsewhere',
       comment='P(E~H)=1.000 gate 처참 실패. NUMEROLOGY_CONFIRMED(HOLD 승격). Koide 2/3 derivation은 조합 산술 이상 정보 0. workbench-reframe DEMOTED Koide/ε.',
       limitation='P(any-target hit | null)=1.000 (8 타깃 × 499 후보) → look-elsewhere가 exact match 필연화. mc_p_e_given_not_h=1.0 ≫ 0.01. genuinely_structural=3 표기는 fitting_suspected=5와 함께 MC가 전부 무력화. 사전등록 0.'),
    _n('koide_q_2_over_3', 'numerology_hold', 'derive_mass_ratios_self_refuted',
       m=1, base=0.01, direction='lower',
       nr=False, nc=False, algo='numerology_mc_judge (20000 trials × 4 null models, look-elsewhere, 499-ratio ensemble)',
       comment='koide_q_2_over_3 + koide_q_two_thirds_numerology 병합. MC null로 P≥0.01 완전 실패(P=1.0) → NUMEROLOGY_CONFIRMED. ICE-specific 아님.',
       limitation='MC null P(E|~H)=1.000(자명, 499 ratio universal match). E1 post-hoc(Z₃ 사후), E5 유도없음. derivation이 PDG 확인 AFTER에 옴 = post-diction. 사전등록 novel 예측 없음.'),
    _n('mp_mw_3_256_literal', 'rejected', 'ice_workbench_reframe_permanent',
       m=88.8, base=0.01, direction='higher',
       nr=False, nc=False, algo='numerology_mc_judge layer1 literal/reciprocal',
       comment='ice_mp_mW_ratio_3x256 + mp_mw_3x256_literal + mp_mw_3_256 세 트리 노드 통합. numerology를 넘어 측정과 충돌 → rejected. layer3 a·2^n fit은 자식 numerology로 분리.',
       limitation='Observed mp/mW ≈ 0.01168. 가장 관대한 1/(3·256)=0.00130로 읽어도 rel_diff 88.8%, layer1 n_sigma=26.2. order-of-magnitude 빗나감 = 직접 반증.'),
    _n('mp_mw_a2n_layer3_fit', 'numerology_hold', 'mp_mw_3_256_literal',
       m=0.812, base=0.01, direction='lower',
       nr=False, nc=False, algo='a·2^n search (a in [1,500000] × n in {14..19}, ~3M 후보)',
       comment='빗나간 literal(부모)을 search-space로 땜빵 = degenerating의 numerology 형태. MC null P=0.812 ≫ 0.01 → numerology_hold.',
       limitation='ARBITRARY R(log-uniform)도 0.1% 안에 81.2% fit. P=0.812 = rational approximation theory, physics 아님. 검색공간 인플레이션 = 사후맞춤.'),
    _n('mu_e_mass_ratio_206_77', 'rejected', 'derive_mass_ratios_self_refuted',
       m=0, base=None, direction='higher',
       nr=False, nc=False, algo='numerology_hidden_scan (ICE integer-only primitive vs 206.77, tolerance 0.1)',
       comment="SIGNAL_GENUINE 라벨 함정 — physics 승리 아니라 '도달 불가=도출 실패'. SIGNAL_GENUINE을 progressive로 오인 금지 → rejected.",
       limitation="p_raw=0.0 'SIGNAL_GENUINE'이나 이는 ICE integer-only primitive set가 ~207을 stochastic으로 reach 못함을 뜻함(uninformative null). 즉 ICE가 이 값을 도출 못함 = 빗나감."),
    _n('tau_mu_mass_ratio_16_818', 'rejected', 'derive_mass_ratios_self_refuted',
       m=0, base=None, direction='higher',
       nr=False, nc=False, algo='numerology_hidden_scan (ICE primitive vs 16.818, tolerance 0.1)',
       comment='도출 실패 → rejected. 빗나간 예측. SIGNAL_GENUINE = uninformative null.',
       limitation="p_raw=0.0 SIGNAL_GENUINE = ICE primitive set가 16.818 도달 못함(uninformative). '16 근처' 직관은 tolerance 0.1 내 매칭 실패."),
    _n('registry_expansion_structural_incapacity', 'rejected', 'derive_mass_ratios_self_refuted',
       m=0, base=None, direction='higher',
       nr=False, nc=False, algo='numerology_registry_expansion (primitive_reachable check)',
       comment='빗나간 예측 → rejected. STRUCTURAL_INCAPACITY를 progressive로 오인 금지.',
       limitation="5/5 STRUCTURAL_INCAPACITY: primitive_reachable=false, p_raw=p_corrected=0.0. ICE primitive set가 이 PDG 값들에 구조적으로 도달 불가 = 물리 도출 실패. NUMEROLOGY_CONFIRMED 0개지만 그 이유가 '도달조차 못함' = 더 강한 부정."),
    _n('weinberg_sin2_theta_w_3_8', 'numerology_hold', 'ice_dimensionless_observables',
       m=0.811, base=0.01, direction='lower',
       nr=True, nc=False, algo='ice_prereg_check + numerology_hidden_scan (look-elsewhere corrected)',
       comment='사전등록(novel_registered=true)했으나 적중 아님(novel_confirmed=false, null 통과 실패) = NUMEROLOGY_CONFIRMED. 사전등록 ≠ progressive(적중해야 progressive).',
       limitation='E1 prereg ✓지만 P_corrected=0.811 ≫ 0.01 → look-elsewhere kill. 측정값 0.231과 62% 괴리(=SU(5)의 알려진 tree-level 재발견). 사전등록은 했으나 예측이 측정을 빗나감 + null 통과 실패.'),
    _n('cabibbo_angle_sqrt_1_20', 'numerology_hold', 'ice_dimensionless_observables',
       m=1, base=0.01, direction='lower',
       nr=True, nc=False, algo='ice_prereg_check + numerology_hidden_scan (look-elsewhere corrected)',
       comment='novel_registered=true이나 null 통과 실패 = NUMEROLOGY_CONFIRMED, novel_confirmed=false.',
       limitation='E1 prereg ✓지만 p_corrected=1.0 → look-elsewhere 전멸. 사전등록 통과분조차 LEE에서 죽음.'),
    _n('singh_delta_sq_3_8', 'numerology_hold', 'ice_dimensionless_observables',
       m=1, base=0.01, direction='lower',
       nr=False, nc=False, algo='numerology_hidden_scan (p_raw → look-elsewhere)',
       comment='NUMEROLOGY_CONFIRMED. small-rational 조합 우연.',
       limitation='p_raw=0.0156, p_corrected=1.0 (look-elsewhere 후). 3/8 같은 small-rational은 ICE integer set에서 거의 확실히 hit.'),
    _n('epsilon_adelberger_screening', 'degenerating', 'ice_workbench_reframe_permanent',
       m=0.238, base=0.01, direction='lower',
       nr=False, nc=False, algo='derive_epsilon_ICE + Adelberger ε(r) wide-prior null comparison',
       comment='epsilon_adelberger_screening + epsilon_adelberger_numerology_hold 병합. 유일한 ember이나 미증명 sorry conjecture에 contingent + 새 예측 없음 = life-support → degenerating(numerology_hold보다 약간 살아있되 progressive 아님). escape lane(p2)이 이것을 받침.',
       limitation="P(E|~H)=0.238 = SIGNAL_WEAK band(0.01~0.5)이나 'Adelberger 통과'는 wide-prior null에서 random power-law 23.8%가 통과 = permissive screening(D5 비변별), 증거 아님. ICE pre-prediction 없음. MB1 form_uniqueness_conjecture는 sorry(미증명), MB1-MB6 0/6 met. escape-lan"),
    _n('hidden_scan_v2_target_family_coverage', 'numerology_hold', 'ice_workbench_reframe_permanent',
       m=4, base=None, direction='higher',
       nr=False, nc=False, algo='numerology_hidden_scan_v2 (4-family target sweep, Naesengmoon axis5 fix)',
       comment='의미있는 결과 = 4 CONFIRMED + 2 orphan hazard anchor(e⁻², ln π). coverage 자체가 numerology 면적 측정이지 물리 신호 아님. numerology_hold.',
       limitation='15 target 중 NUMEROLOGY_CONFIRMED 4(Casimir 0.75/Koide 2/3 reconfirm + e⁻² orphan + ln π orphan), SIGNAL_GENUINE 11. 11개 SIGNAL_GENUINE은 uninformative null(integer-only primitive가 transcendental/log/큰정수 stochastic match 거의 0). 신호 0.'),
    _n('prereg_check_lakatos_fail', 'rejected', 'ice_workbench_reframe_permanent',
       m=0, base=15, direction='lower',
       nr=True, nc=False, algo='ice_prereg_predictions.py (sha256 0bbcbe40) + ice_prereg_check.py (MC null + Bonferroni n=300)',
       comment='MOST RIGOROUS test. 진짜 사전등록(sha256 frozen BEFORE PDG comparison) novel_registered=TRUE이나 적중 0이므로 가장 강한 negative witness → physics layer rejected/STAGNANT 확정. 사전등록했으나 적중 0 = progressive 아님. (방법론 자체는 cycle-novel publishable이나 그건 메타-기여.)',
       limitation='7 matches 전부 integer-level generic(어떤 Lie algebra/finite group도 trivially produce, P_corr=1.000); 13 predictions(5.25/5.163/4.573/4.305/1.333/72)는 SM measured value와 무대응. novel_confirmed=FALSE(0/15 적중).'),
    _n('ice_l2l3_e1_e5_full_verdict', 'rejected', 'ice_workbench_reframe_permanent',
       m=0, base=13, direction='lower',
       nr=True, nc=False, algo='L2/L3 E1-E5 5-condition ledger (numerology_mc_judge + look-elsewhere)',
       comment='테스트된 claim 13개 중 E1-E5 전체 통과 0 → 전수 rejected. 사전등록 novel 예측 다수였으나 적중 0(novel_confirmed=false). prereg_check와 별개 scope(L2/L3 ledger §정의적 결론).',
       limitation="사전등록(E1) 통과분(sin²θ_W·Cabibbo·P01·P02·P15)조차 look-elsewhere(E4)에서 전멸. TOE 본체('자유파라미터 0으로 SM 유도')는 통계적 부활 근거 없음. ε만 degenerating ember."),
    _n('hypercomplex_sm_50yr_stagnation', 'rejected', 'ice_workbench_reframe_permanent',
       m=0, base=None, direction='lower',
       nr=False, nc=False, algo='5-programme Lakatos audit (Tüchsen 2024 STAGNANT 3rd category)',
       comment='ICE도 같은 STAGNANT 패턴 = meta-numerology, workbench-reframe honest landing. 외부 프로그램 비교가 ICE physics 측 rejected를 강화.',
       limitation='감사 5 프로그램 novel confirmed prediction = 0 (Koide/G₂ Casimir = post-diction). hard core 보존 + sharp prediction 부재 + protective belt(Dixon hidden 6D, Furey deferred top, Singh Majorana-only, Köplinger untestable QG). Kaiser 1984/Procopio 2017/F'),
    _n('oq2_n_eff_11_pullback', 'rejected', 'epsilon_adelberger_screening',
       m=None, base=None, direction='higher',
       nr=False, nc=False, algo='n_eff fiber dim selection {4,9,11,12,14} → ε(r) exponent',
       comment="아침 RATIFIED_DELEGATED → 사용자 audit '수비학은 없냐' → 같은날 honest PULLED_BACK. 정직 철회 = rejected. sunk-cost insulation으로 workbench/algebra/mythology 손상 0. ε 파생.",
       limitation='5-candidate space + post-hoc rationalization, numerology_mc_judge gate를 prose로 우회, 1/r^12 unfalsifiable. 사전등록 0.'),
    _n('p2_zd_filtration_lean_escape_lane', 'numerology_hold', 'epsilon_adelberger_screening',
       m=0.04, base=0.01, direction='higher',
       nr=True, nc=False, algo='P2 ZD filtration uniqueness (n_eff = 16 − dim(ZD-locus)) + Lean 4 Mathlib sister 0-sorry MB1 theorem',
       comment='유일하게 열린 reversal 경로. :PreRegisteredPrediction sha256 timestamp BEFORE Adelberger(novel_registered=TRUE)이나 미적중·미증명(novel_confirmed=FALSE). P≈0.04 SIGNAL이나 confirmation 미달 + 8-gate 0/8 → numerology_hold(predictive_claim, calibration 필요). MB1 ',
       limitation="8-gate G1-G8 현재 0/8; MB1 theorem 아직 0 sorry proof 미완; single-expert circular prior(외부 seed 부재→calibration formally impossible, Garthwaite-Kadane-O'Hagan); 5 candidate dim {4,9,11,12,14} pre-registration mandatory(numerology hazard). v3 ABC+"),
    _n('ice_004_meta_bayes_non_numerology', 'numerology_hold', 'ice_workbench_reframe_permanent',
       m=0.037, base=0.01, direction='lower',
       nr=False, nc=False, algo='v3 ABC+KL dual gate (P(E|~H)=0.037, KL=1.533 bits)',
       comment='reframe 메타 신뢰도 자체의 재귀 검정. 신호 아님 = numerology_hold band. 자기참조적 메타 노드, ice_root 직속 reframe 측 메타.',
       limitation="SIGNAL_WEAK = weak-but-valid, STRONG SIGNAL 격상 아님. Single-expert circular-prior caveat(Garthwaite-Kadane-O'Hagan 2005, Cooke 1991 dependence) 미해소 — LLM subagent가 user KG share. P=0.037은 0.5 미만이라 numerology는 면했으나 0.01 SIGNAL_GENUINE에도 미달 = 경"),
    _n('cd_final_quick_no_verdict', 'rejected', 'ice_root',
       m=None, base=None, direction='higher',
       nr=False, nc=False, algo='cd_final_quick.py (CD embedding quick check, no explicit verdict)',
       comment="set_verdict 호출 없이 hook이 자동 생성한 structural placeholder — 'structural only, does not assert CONFIRMED/REFUTED/NUMEROLOGY'. 채점 가능한 과학적 주장 부재라 어떤 라카토스 verdict도 정당화 안 됨. 빈손방지 최소 노드로 rejected(공허=물리 검정 통과 못함, progressive/proof 근거 전무). ice_root 직속 ",
       limitation='results.json에 과학적 결과·metric·예측·통과여부 전무. verdict는 hook auto-emit placeholder(COMPLETED=실행종료 신호일 뿐, walltime 355s, exit normal만 기록). MT_RubberStampVerdict guard. 채점 가능한 claim 부재.'),
]

FRONTIER = [
    dict(name='q_aut_full_proof', status='OPEN', body='Aut(𝕊)=G₂×S₃ 전체군 Lean4 sorry=0 형식증명(현재 axiom-status, Wilmot dispute OPEN)', closed_by=None),
    dict(name='q_p2_zd_lean_escape', status='OPEN', body='P2 ZD filtration Lean escape lane (P=0.04, 유일 생존 물리 falsifier)', closed_by=None),
    dict(name='q_physics_discriminator', status='OPEN', body='2026-2031 P1-P5 5년 물리 discriminator window', closed_by=None),
    dict(name='q_custodial_su2', status='CLOSED', body='custodial SU(2) 42-ZD closure 성립?', closed_by=['queue_02_custodial_fail']),
    dict(name='q_mass_ratios', status='CLOSED', body='mp/mW·μ/e·τ/μ 대수 도출?', closed_by=['derive_mass_ratios_self_refuted']),
    dict(name='q_orbit_structure', status='CLOSED', body='42 ZD = 7 orbit × 6 (S₃) 구조?', closed_by=['queue_01_orbit_42']),
]

def run():
    print('═'*72); print('  ICE ORCA DRAGON — 라카토스 연구 프로그램 정직 채점 (사도#2 → lakatotree)'); print('═'*72)
    print('\n  hard core:', HARD_CORE[:120], '...')
    from collections import Counter
    print('  verdict 분포:', dict(Counter(n['verdict'] for n in NODES)), '(총 %d 노드)' % len(NODES))
    m = tree_metrics(NODES, FRONTIER)
    print('\n[1] 프로그램 지표')
    prog = m.get('progress') or {}
    print('  정본(CANONICAL)   :', m['canonical'])
    print('  기각률            :', m['rejection_ratio'])
    print('  최대 퇴행깊이     :', m['max_degeneration_depth'], '(≥3 경보)')
    print('  주석 커버리지     :', m['annotation_coverage'])
    print('  경보              :', m.get('alerts'))
    print('\n[2] 베이즈 + 발전성')
    print('  정본경로 신뢰도   :', m['bayes']['canonical_credence'])
    print('  저신뢰 가지       :', m['bayes']['low_credence_branches'])
    fert = predictive_fertility(NODES)
    print('  novel 등록/확증   :', fert['registered'], '/', fert['confirmed'])
    print('  발전성 지표       :', m.get('fertility'))
    print('\n[3] 라우든 문제해결력')
    print('  frontier 수지     :', m['laudan']['frontier_balance'], '(closed−open)')
    print('  폐기 후보         :', m['laudan']['abandon_candidates'])
    print('\n[4] 3층 메타규칙 + 수명주기')
    if m['canonical'] is None:
        print('  ⚠ CANONICAL 노드 없음 — ICE엔 검증된 정본 결과 0 (정직 발견). 수학 생존가지로 스택 평가.')
    _leaf = 'queue_11_xor_105_invariant'   # 수학층 최장 생존 가지
    bi = branch_inputs(NODES, FRONTIER, leaf=_leaf)
    sv = evaluate_stack(bi["verdicts"], bi["consecutive_nonprogressive"], bi["nodes_spent"], bi["prediction_hits"], bi["problem_balance_windowed"])
    print('  평가 가지         :', _leaf, '(수학 생존층)')
    print('  스택 결정         :', sv.decision, '(정족수', sv.quorum, ', conflict=', sv.conflict, ')')
    print('  스택 사유         :', sv.reason)
    ls = lifecycle_state(bi["verdicts"], sv, bi["novel_registered_recent"], bi["problem_balance_windowed"], bi["canonical_improved_recent"])
    print('  수명주기 상태     :', ls.state, '—', ls.reason)
    print('\n[5] 물리예측 가지 채점 (custodial)')
    try:
        bp = branch_inputs(NODES, FRONTIER, leaf='higgs_zd_doublet_42')
        sp = evaluate_stack(bp["verdicts"], bp["consecutive_nonprogressive"], bp["nodes_spent"], bp["prediction_hits"], bp["problem_balance_windowed"])
        lp = lifecycle_state(bp["verdicts"], sp, bp["novel_registered_recent"], bp["problem_balance_windowed"], bp["canonical_improved_recent"])
        print('  물리 가지 스택   :', sp.decision, '→ 수명주기', lp.state)
    except Exception as e: print('  (물리 가지 평가 skip:', e, ')')
    print('\n'+'═'*72)
    return dict(verdict_dist=dict(Counter(n['verdict'] for n in NODES)), metrics=m, stack=sv.decision, lifecycle=ls.state)

if __name__ == '__main__':
    run()
