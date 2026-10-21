#!/usr/bin/env bash
# Link the compiled skill into a Claude Code skills directory.
#
#   bash scripts/install_claude_skill.sh              # ~/.claude/skills
#   bash scripts/install_claude_skill.sh --project .  # ./.claude/skills
#
# A symlink, not a copy: the compiled folder stays the single source of truth,
# so the pre-commit hook keeps Claude's view fresh with no second copy to rot.
# Claude Code reads SKILL.md through a symlinked skill folder by design.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "$SELF")/.." && pwd)"
SKILL="$ROOT/skills/daydream"

TARGET="$HOME/.claude/skills"
if [ "${1:-}" = "--project" ]; then
  BASE="${2:-.}"
  TARGET="$(cd "$BASE" && pwd)/.claude/skills"
fi

if [ ! -f "$SKILL/SKILL.md" ]; then
  printf 'no compiled skill at %s -- run: python3 %s/scripts/compile_skill.py\n' \
    "$SKILL" "$ROOT" >&2
  exit 1
fi

mkdir -p "$TARGET"
LINK="$TARGET/daydream"

if [ -L "$LINK" ]; then
  if [ "$(readlink -f "$LINK")" = "$(readlink -f "$SKILL")" ]; then
    printf 'already linked: %s -> %s\n' "$LINK" "$SKILL"
    exit 0
  fi
  printf 'relinking %s -> %s\n' "$LINK" "$SKILL"
  rm -f "$LINK"
elif [ -e "$LINK" ]; then
  printf '%s exists and is not a symlink; move it aside first\n' "$LINK" >&2
  exit 1
fi

ln -s "$SKILL" "$LINK"
printf 'linked: %s -> %s\n' "$LINK" "$SKILL"

# Prove it is readable through the link, the way Claude will read it.
head -1 "$LINK/SKILL.md" | grep -qx -- '---' ||
  { printf 'SKILL.md frontmatter not readable through the link\n' >&2; exit 1; }
printf 'ok: Claude will load /daydream\n'
