#!/usr/bin/env python3
"""Compile daydream.jinx into skills/daydream/ -- an Anthropic-style skill folder.

The compiled folder is the artifact other agent runtimes load: a SKILL.md with
YAML frontmatter plus flat, importable .py step files. The runtime support
modules are copied next to the step so the folder stands alone -- no npcpy,
no npcsh, no jinja, no relative paths reaching back out of the folder.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JINX = os.path.join(ROOT, "daydream.jinx")
OUT_DIR = os.path.join(ROOT, "skills")
SUPPORT_FILES = ("daydream.py", "markov.py", "tinytim.py")
GITIGNORE = "__pycache__/\n*.pyc\n"
USAGE_FILE = os.path.join(HERE, "skill_usage.md")

# Only field names from the Claude Code frontmatter reference. Anything
# else is ignored silently, so a typo would just disappear.
CLAUDE_FIELDS = (
    "allowed-tools: Read Bash",
    'argument-hint: "<problem>"',
    "when_to_use: User asks to daydream, wander, brainstorm divergently, "
    "free-associate, or wants associative rather than analytical thinking.",
)


def _repo_relative(path):
    """Path for source_jinx: relative to the git toplevel when there is one."""
    import subprocess

    try:
        top = subprocess.run(
            ["git", "-C", os.path.dirname(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True).stdout.strip()
        if top:
            return os.path.relpath(path, top)
    except Exception:
        pass
    return os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)


def add_provenance(skill_md, jinx_path):
    """Record where the skill came from, matching the repo's existing skills.

    Anthropic-style loaders only require name+description; source_jinx and
    engine are additive provenance so a reader can find the jinx again.
    """
    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()
    if "source_jinx:" in text.split("---")[1]:
        return skill_md
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return skill_md
    closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if closing is None:
        return skill_md
    provenance = [
        f"source_jinx: {_repo_relative(jinx_path)}",
        "engine: skill",
    ]
    lines[closing:closing] = provenance
    with open(skill_md, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return skill_md


def _insert_before_closing(text, lines):
    """Insert frontmatter lines before the closing --- of a SKILL.md."""
    split = text.split("\n")
    if not split or split[0].strip() != "---":
        return text
    closing = next((i for i, line in enumerate(split[1:], 1) if line.strip() == "---"), None)
    if closing is None:
        return text
    present = "\n".join(split[:closing])
    fresh = [line for line in lines if line.split(":", 1)[0] not in present]
    split[closing:closing] = fresh
    return "\n".join(split)


def add_claude_fields(skill_md):
    """Add the Claude Code fields this skill needs to run unattended.

    jinx_to_skill only emits name+description, so Claude would ask for Bash
    permission on every call and show no argument hint. These are documented
    field names, so Claude reads them and other loaders ignore them.
    """
    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()
    updated = _insert_before_closing(text, list(CLAUDE_FIELDS))
    if updated != text:
        with open(skill_md, "w", encoding="utf-8") as handle:
            handle.write(updated)
    return skill_md


def apply_usage(skill_md):
    """Replace jinx_to_skill's npcsh-only Usage block with runnable steps.

    The generated block says `/run_jinx jinx_ref=...`, which is an npcsh
    command. An agent loading this skill has Bash, not npcsh, so leaving it in
    gives the only run instruction in the file an unusable command.
    """
    if not os.path.isfile(USAGE_FILE):
        return skill_md
    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()
    marker = "\n## Usage"
    cut = text.find(marker)
    if cut != -1:
        text = text[:cut].rstrip() + "\n"
    with open(USAGE_FILE, "r", encoding="utf-8") as handle:
        usage = handle.read().strip()
    text = text.rstrip() + "\n\n" + usage + "\n"
    with open(skill_md, "w", encoding="utf-8") as handle:
        handle.write(text)
    return skill_md


def compile_skill(jinx_path=JINX, out_dir=OUT_DIR, quiet=False, if_available=False):
    try:
        from npcpy.convert import jinx_to_skill
    except ImportError as exc:
        if if_available:
            if not quiet:
                print("skipped compile: npcpy not importable (" + str(exc) + ")")
            return None
        raise SystemExit("compiling needs npcpy (pip install npcpy): " + str(exc))

    skill_md = jinx_to_skill(jinx_path, out_dir)
    add_provenance(skill_md, jinx_path)
    add_claude_fields(skill_md)
    apply_usage(skill_md)
    skill_dir = os.path.dirname(skill_md)

    for name in SUPPORT_FILES:
        source = os.path.join(HERE, name)
        if not os.path.isfile(source):
            raise SystemExit(f"missing support module: {source}")
        shutil.copy2(source, os.path.join(skill_dir, name))

    ignore = os.path.join(out_dir, ".gitignore")
    if not os.path.isfile(ignore):
        with open(ignore, "w", encoding="utf-8") as handle:
            handle.write(GITIGNORE)

    if not quiet:
        print(f"compiled {os.path.relpath(jinx_path, ROOT)} -> {os.path.relpath(skill_dir, ROOT)}")
        print("  " + ", ".join(sorted(os.listdir(skill_dir))))
    return skill_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jinx", default=JINX)
    parser.add_argument("--out", default=OUT_DIR)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--if-available", action="store_true", dest="if_available",
                        help="warn instead of failing when npcpy is not importable")
    args = parser.parse_args(argv)
    compile_skill(args.jinx, args.out, quiet=args.quiet, if_available=args.if_available)
    return 0


if __name__ == "__main__":
    sys.exit(main())
