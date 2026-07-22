#!/usr/bin/env python3
"""EXTAUDIT S2 프로브용 고정 채점기 — 항상 metric=0.5 (결정론 픽스처).

라이브 replay 발효 e2e 프로브(extaudit_replay_default_novel.py)가 submit 하는 스크립트.
서버가 replay ON 이면 이 파일을 재실행해 0.5 를 재유도 → measurement_grade=server_regenerated.
args 무시 (서버 재현명령 'python <script> <result_path>' 계약).
"""
import sys

if __name__ == '__main__':
    print("metric=0.5")
    sys.exit(0)
