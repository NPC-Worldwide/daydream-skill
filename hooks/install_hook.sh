#!/usr/bin/env bash
# Install the daydream pre-commit guard into the enclosing git repo.
#
# Non-destructive by design: if the repo already has a pre-commit hook, this
# appends a guarded call to it instead of replacing it. Re-running is a no-op.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/hooks/pre-commit"
MARKER="# >>> daydream-skill guard >>>"

GIT_DIR="$(git -C "$ROOT" rev-parse --git-dir)"
case "$GIT_DIR" in
  /*) ;;
  *) GIT_DIR="$(cd "$ROOT" && cd "$GIT_DIR" && pwd)" ;;
esac
TARGET="$GIT_DIR/hooks/pre-commit"

chmod +x "$HOOK"

if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
  if grep -qF "$MARKER" "$TARGET"; then
    echo "already installed in $TARGET"
    exit 0
  fi
  cat >> "$TARGET" <<BLOCK

$MARKER
# Added by daydream-skill. Remove this block to uninstall.
if [ -x "$HOOK" ]; then
  "$HOOK" || exit 1
fi
# <<< daydream-skill guard <<<
BLOCK
  echo "appended daydream guard to existing hook -> $TARGET"
  exit 0
fi

if [ -L "$TARGET" ] && [ "$(readlink -f "$TARGET")" = "$(readlink -f "$HOOK")" ]; then
  echo "already installed in $TARGET"
  exit 0
fi

ln -sf "$HOOK" "$TARGET"
echo "installed $TARGET -> $HOOK"
