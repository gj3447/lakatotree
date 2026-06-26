"""lakatos.io — THEORY.md 계층 (engine reorg 2026-06-18).

LTDD 정본 소비: 벤더된 ooptdd(`<repo>/_vendor/ooptdd`, manifest+drift-test 로 핀)를 sys.path 에
얹어 `import ooptdd` 가 그 고정 사본으로 해석되게 한다. oo_sink/oo_verify 는 그 위에서
OpenObserve I/O·정책을 더하는 어댑터다 (레코드 빌더는 ooptdd 정본에 위임 — 중복 제거).
"""
import os as _os
import sys as _sys

# <repo>/_vendor (this file is <repo>/lakatos/io/__init__.py → up 3)
_VENDOR = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
    "_vendor",
)
if _os.path.isdir(_os.path.join(_VENDOR, "ooptdd")) and _VENDOR not in _sys.path:
    _sys.path.insert(0, _VENDOR)
