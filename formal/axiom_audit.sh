#!/usr/bin/env bash
# Axiom audit — Ω={propext, Classical.choice, Quot.sound} 외 공리 사용 시 exit 1.
# "formally verified" 표기의 정직 조건(D3-2): 커널 타입체크 + 공리 감사 세트일 때만.
# 사용: cd formal && lake build && bash axiom_audit.sh
set -euo pipefail
cd "$(dirname "$0")"

OUT="$(lake env lean AxiomAudit.lean)"
echo "$OUT"

USED="$(printf '%s\n' "$OUT" \
  | grep -o 'axioms: \[[^]]*\]' | sed 's/.*\[//;s/\]//' \
  | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -v '^$' | sort -u || true)"

BAD="$(comm -13 <(printf 'Classical.choice\nQuot.sound\npropext\n' | sort) \
        <(printf '%s\n' "$USED") || true)"

if [ -n "$BAD" ]; then
  echo "AXIOM AUDIT FAIL — Ω 외 공리 의존 감지:"
  echo "$BAD"
  exit 1
fi

echo "AXIOM AUDIT OK — 사용 공리 ⊆ Ω={propext, Classical.choice, Quot.sound} (${USED:-none})"
