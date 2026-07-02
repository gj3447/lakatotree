"""git 소스 caller 전수 추출기 — M0(GitNexus 구조 교차검증)의 재현 가능 방법론 (git-흡수 2026-07-02).

git C 코드 스타일 불변식을 이용한다: 함수 정의부는 칼럼 0 에서 시작(`int foo(...)`,
`static void bar(...)`), 본문은 탭 들여쓰기. 각 호출 지점에서 위로 스캔해 처음 만나는
칼럼0 함수 시그니처가 둘러싼(caller) 함수다.

충실도: GitNexus C 지원(tree-sitter, import 해석 없는 이름 매칭)과 동급. 교정(calibration):
GitNexus 가 전수 확인한 finalize_object_file_flags=4 / fsck_object=3 / mark_reachable_objects=2 /
merge_incore_recursive=3 을 바이트동일 재현해야 신뢰한다(tests/test_git_absorption_m0.py 가 대조).
ref_transaction_commit 은 본 추출기가 28 을 찾음(GitNexus 24) — 과포함 방향이라 전수성 주장엔 안전
(우회경로 부재 확인엔 누락이 치명, 과포함은 검토 대상일 뿐).

사용: python scripts/extract_git_callers.py [git소스루트] [심볼 ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_GIT_ROOT = Path('<WORKSPACE>/PROJECT/PI/GIT/git')
CHOKEPOINTS = ('finalize_object_file_flags', 'fsck_object', 'mark_reachable_objects',
               'ref_transaction_commit', 'merge_incore_recursive', 'migrate_one')

# 칼럼0 함수 정의 휴리스틱: 식별자로 시작, '(' 포함, ';' 미종결(프로토타입 선언 제외), 제어문 제외.
_DEF_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_ \t\*]*\b([a-z_][a-z0-9_]*)\s*\(')
_SKIP_HEADS = frozenset({'if', 'for', 'while', 'switch', 'return', 'else', 'do', 'sizeof', 'case'})


def _enclosing_function(lines: list[str], idx: int) -> str | None:
    for i in range(idx, -1, -1):
        line = lines[i]
        if not line or line[0] in ' \t}/*#':
            continue
        m = _DEF_RE.match(line)
        if m and not line.rstrip().endswith(';') and m.group(1) not in _SKIP_HEADS:
            return m.group(1)
    return None


def extract_callers(symbols: tuple[str, ...] = CHOKEPOINTS,
                    git_root: Path = DEFAULT_GIT_ROOT) -> dict[str, dict[str, set]]:
    """{symbol → {caller_fn → {상대경로,...}}} — 전 *.c 단일 패스(파일당 1회 읽기)."""
    call_res = {s: re.compile(r'\b' + re.escape(s) + r'\s*\(') for s in symbols}
    out: dict[str, dict[str, set]] = {s: {} for s in symbols}
    for f in git_root.rglob('*.c'):
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        hits = [s for s in symbols if s in text]
        if not hits:
            continue
        lines = text.split('\n')
        rel = str(f.relative_to(git_root))
        for i, line in enumerate(lines):
            for s in hits:
                if not call_res[s].search(line):
                    continue
                if line and line[0] not in ' \t':
                    continue   # 칼럼0 = 정의 시그니처(호출 아님)
                stripped = line.lstrip()
                if stripped.startswith(('*', '//', '/*')):
                    continue   # 주석행
                fn = _enclosing_function(lines, i)
                if fn is None or fn == s:
                    continue   # 미해석/자기재귀 제외
                out[s].setdefault(fn, set()).add(rel)
    return out


if __name__ == '__main__':
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GIT_ROOT
    syms = tuple(sys.argv[2:]) or CHOKEPOINTS
    for sym, callers in extract_callers(syms, root).items():
        print(f'{sym}: {len(callers)} callers')
        for fn in sorted(callers):
            print(f'    {fn}  ({", ".join(sorted(callers[fn]))})')
