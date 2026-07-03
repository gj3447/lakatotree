"""[shim] 정본 이관 → `lakatos.programme.evidence` (2026-07-03).

evidence-record 로더/검증의 정본은 이제 엔진 패키지 안에 있다(외부 저자가 pip install 만으로
쓰도록). 이 파일은 기존 `from examples._evidence import ...` 하위호환 re-export 만 유지한다 —
신규 코드는 `from lakatos.programme.evidence import ...` 를 직접 쓰라.
"""
from lakatos.programme.evidence import (  # noqa: F401  (re-export)
    RECORD_SCHEMA,
    REQUIRED,
    load_record,
    validate_record,
    is_grounded,
    source_id,
    summarize,
)

__all__ = ["RECORD_SCHEMA", "REQUIRED", "load_record", "validate_record",
           "is_grounded", "source_id", "summarize"]
