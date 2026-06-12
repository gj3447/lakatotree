#!/usr/bin/env python3
"""BPC 채점기 — perview_fixedr_joint_*.json 에서 LOO p95 worst-lot 을 산출 (순수 스크립트, LLM 무관).
사용: python bpc_loo_p95.py <result.json>  → metric 출력
     python bpc_loo_p95.py <result.json> --post <tree> <tag>  → 서버에 test_result 제출
"""
import json, sys, urllib.request
d = json.loads(open(sys.argv[1]).read())
loo = d['loo']
metric = max(v['p95'] for v in loo.values())
print(f'loo_p95_worstlot = {metric}')
if '--post' in sys.argv:
    i = sys.argv.index('--post')
    tree, tag = sys.argv[i+1], sys.argv[i+2]
    body = json.dumps(dict(metric_value=metric, script='judges/bpc_loo_p95.py',
                           result_path=sys.argv[1])).encode()
    req = urllib.request.Request(
        f'http://localhost:55170/api/tree/{tree}/node/{tag}/test_result',
        data=body, headers={'Content-Type': 'application/json'})
    print(urllib.request.urlopen(req).read().decode())
