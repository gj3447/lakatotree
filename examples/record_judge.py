"""[shim] 정본 이관 → `lakatos.programme.record_judge` (2026-07-03).

record→엔진판결 정본은 이제 엔진 패키지 안에 있다(외부 저자 pip install 로 쓰도록). 이 파일은
기존 `from examples.record_judge import judge_record` 하위호환 re-export 만 유지 — 신규 코드는
`from lakatos.programme.record_judge import ...` 를 직접 쓰라.
"""
from lakatos.programme.record_judge import (  # noqa: F401  (re-export)
    judge_record,
    audit_dir,
)

__all__ = ["judge_record", "audit_dir"]
