"""programme authoring — 연구프로그램 트리 노드를 선언하는 **공개 프리미티브**.

`tree_metrics`(lakatos.quant.metrics)·judge 하네스가 소비하는 노드 dict 를 스키마-정합하게
만든다. 외부 저자는 `pip install lakatotree` 후

    from lakatos.programme.authoring import node
    from lakatos.programme.evidence import load_record, is_grounded, summarize
    from lakatos.programme.record_judge import judge_record

로 **벤더링 없이·엔진 repo 미접촉**으로 프로그램을 저술한다. (이 모듈은 examples/ 의 `_n`
정본을 승격한 것 — examples 는 하위호환 re-export 로 남는다.)
"""
from __future__ import annotations


def node(tag, verdict, parent, *, m=None, base=None, scope='registration',
         direction='lower', nr=False, nc=False, q=None, comment='', limitation='', algo='', mn=None):
    """연구프로그램 트리 노드 dict 를 구성한다.

    mn = metric_name. gap8 다중비교 family 키 = (metric_name, scope). 같은 물리량끼리만 묶이도록
    노드마다 진짜 측정 구성(seam mm / 마커 count / σ mm / synthetic max_dev …)을 명시한다 —
    누락 시 None 으로 뭉쳐 이질 metric(거리·개수·무차원)이 한 family 가 되어 BH/FDR 통제가 미정의가
    된다(multiplicity.py 스스로 "다른 측정 한 family 로 묶지 말라" 경고를 코드가 위반하던 버그).

    m=metric_value, base=pred_baseline, nr=novel_registered, nc=novel_confirmed, q=questions.
    """
    return dict(tag=tag, verdict=verdict, parent=parent,
                metric_value=m, metric_scope=scope, metric_name=mn, pred_baseline=base,
                pred_noise_band=0.05, pred_direction=direction,
                novel_registered=nr, novel_confirmed=nc,
                algorithm=algo or 'classical', comment=comment, limitation=limitation,
                questions=q or [])
