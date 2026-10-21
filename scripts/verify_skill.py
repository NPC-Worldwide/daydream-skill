#!/usr/bin/env python3
"""Verify the compiled daydream skill actually loads.

Checks the SKILL.md contract, template hygiene, that every shipped module
compiles, and that the folder imports and walks a chain in a fresh process
with no network. Exits non-zero on failure so a pre-commit hook can refuse.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess

# Verifying must not dirty the tree it inspects: keep child interpreters
# from writing __pycache__ into the skill folder.
_CHILD_ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JINX = os.path.join(ROOT, "daydream.jinx")
SKILLS_DIR = os.path.join(ROOT, "skills")
SUPPORT_FILES = ("daydream.py", "markov.py", "tinytim.py")
MODES = ("wander", "markov", "tinytim")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
TEXT_SUFFIXES = (".md", ".py", ".txt", ".yaml", ".yml", ".json")

# Claude Code documents these frontmatter fields; anything else is ignored
# without an error, so a typo in one of these names would be silently dropped.
CLAUDE_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments",
    "disable-model-invocation", "user-invocable", "allowed-tools",
    "disallowed-tools", "model", "effort", "context", "agent", "background",
    "hooks", "paths",
}
# Our own additive provenance. Claude ignores these; they stay on an explicit
# allowlist so a misspelt Claude field cannot hide behind "unknown is fine".
PROVENANCE_FIELDS = {"source_jinx", "engine"}
RESERVED_NAMES = {"synced"}
LISTING_CAP = 1536

results = []


def record(ok, label, detail=""):
    results.append((bool(ok), label, detail))
    return bool(ok)


def split_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    data = {}
    key = None
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t" and key:
            data[key] = (str(data[key]) + " " + line.strip()).strip()
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            data[key] = value.strip().strip('"').strip("'")
    return data, text[end + 4:]


def verify_claude_compat(name, text, front, body):
    """Checks that matter to a Claude Code skill loader specifically.

    These encode the documented loading rules: frontmatter is read only when
    the opening --- is the file's first line, unparseable YAML loads with no
    fields, unknown field names are ignored, and description + when_to_use are
    truncated together at 1,536 characters in the listing.
    """
    record(text.startswith("---"), f"{name}: opening --- is the first line")

    raw = ""
    if text.startswith("---"):
        close = text.find("\n---", 3)
        if close != -1:
            raw = text[3:close]
    try:
        import yaml
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except ImportError:
        record(True, f"{name}: strict YAML parse skipped (pyyaml not installed)")
        parsed = front
    except Exception as exc:
        record(False, f"{name}: frontmatter parses as strict YAML", str(exc)[:200])
        parsed = front
    else:
        record(isinstance(parsed, dict), f"{name}: frontmatter parses as strict YAML",
               f"got {type(parsed).__name__}")
        parsed = parsed if isinstance(parsed, dict) else {}

    keys = set(parsed) if parsed else set(front)
    unknown = sorted(keys - CLAUDE_FIELDS - PROVENANCE_FIELDS)
    record(not unknown, f"{name}: every frontmatter field is a known name",
           ", ".join(unknown))

    listing = str(parsed.get("description") or "") + str(parsed.get("when_to_use") or "")
    record(len(listing) <= LISTING_CAP,
           f"{name}: description + when_to_use under {LISTING_CAP} chars",
           f"{len(listing)} chars")

    record(str(parsed.get("name") or name) not in RESERVED_NAMES
           and not str(parsed.get("name") or name).startswith("anthropic-skills"),
           f"{name}: name is not reserved")
    record("<" not in name and "\u200b" not in name,
           f"{name}: folder name has no characters Claude rejects")

    tools = str(parsed.get("allowed-tools") or "")
    record("Bash" in tools, f"{name}: allowed-tools grants Bash so it can run",
           repr(tools))

    record("/run_jinx" not in body,
           f"{name}: body has no npcsh-only command the agent cannot run")
    record("daydream.py" in body,
           f"{name}: body tells the agent how to run the step")


def verify_skill(skill_dir):
    name = os.path.basename(skill_dir)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not record(os.path.isfile(skill_md), f"{name}: SKILL.md exists"):
        return

    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()
    front, body = split_frontmatter(text)
    if not record(front is not None, f"{name}: SKILL.md has YAML frontmatter"):
        return

    record(front.get("name") == name, f"{name}: frontmatter name matches folder",
           str(front.get("name")))
    record(bool(NAME_RE.match(name)) and len(name) <= MAX_NAME_LEN,
           f"{name}: folder name is a valid skill slug")
    description = str(front.get("description") or "").strip()
    record(0 < len(description) <= MAX_DESC_LEN,
           f"{name}: description is 1-{MAX_DESC_LEN} chars", f"{len(description)} chars")
    record(bool(body.strip()), f"{name}: SKILL.md has a body")
    verify_claude_compat(name, text, front, body)

    leftovers = []
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(TEXT_SUFFIXES):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            if "{{" in content or "{%" in content:
                leftovers.append(os.path.relpath(path, skill_dir))
    record(not leftovers, f"{name}: no unresolved jinja in compiled output",
           ", ".join(leftovers))

    for support in SUPPORT_FILES:
        record(os.path.isfile(os.path.join(skill_dir, support)),
               f"{name}: ships {support}")

    py_files = sorted(f for f in os.listdir(skill_dir) if f.endswith(".py"))
    broken = []
    for filename in py_files:
        path = os.path.join(skill_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                compile(handle.read(), path, "exec")
        except SyntaxError as exc:
            broken.append(f"{filename}: {exc.msg} line {exc.lineno}")
    record(not broken, f"{name}: all {len(py_files)} python files compile",
           "; ".join(broken))

    steps = [f for f in py_files if f not in SUPPORT_FILES]
    record(bool(steps), f"{name}: ships at least one step script", ", ".join(steps))

    load_code = "\n".join([
        "import json, sys",
        f"sys.path.insert(0, {skill_dir!r})",
        "import markov, tinytim, daydream",
        "assert callable(daydream.run), 'daydream.run missing'",
        "chain = markov.fit(['the dream keeps walking through the house'], order=2)",
        "text, steps, restarts = markov.walk(chain, order=2, n_words=12, seed_text='the dream')",
        "assert isinstance(text, str)",
        "cfg = tinytim.resolve_config()",
        "assert cfg['backend'] in ('ollama', 'hf', 'api'), cfg['backend']",
        "assert 'localhost' in cfg['ollama_host'] or '127.0.0.1' in cfg['ollama_host'], 'ollama default must stay local'",
        "print(json.dumps({'states': markov.stats(chain)['states'], 'walk': text[:48], 'backend': cfg['backend']}))",
    ])
    proc = subprocess.run([sys.executable, "-c", load_code],
                          cwd=skill_dir, capture_output=True, text=True,
                          env=_CHILD_ENV)
    record(proc.returncode == 0,
           f"{name}: imports and walks a chain in a fresh process, offline",
           (proc.stderr or proc.stdout).strip()[-400:])

    for step in steps:
        proc = subprocess.run([sys.executable, step, "--help"],
                              cwd=skill_dir, capture_output=True, text=True,
                              env=_CHILD_ENV)
        record(proc.returncode == 0, f"{name}: {step} loads without a jinx context",
               (proc.stderr or "").strip()[-400:])


def verify_source():
    if not record(os.path.isfile(JINX), "source: daydream.jinx exists"):
        return
    raw = open(JINX, "r", encoding="utf-8").read()
    try:
        import yaml
    except ImportError:
        record(True, "source: yaml parse skipped (pyyaml not installed)")
    else:
        data = yaml.safe_load(raw)
        record(isinstance(data, dict) and data.get("jinx_name") == "daydream",
               "source: jinx_name is daydream")
        record(bool(data.get("steps")), "source: jinx declares steps")
        record(bool(str(data.get("description") or "").strip()),
               "source: jinx has a description for agent routing")
    missing = [mode for mode in MODES if mode not in raw]
    record(not missing, "source: jinx offers all three modes", ", ".join(missing))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    verify_source()

    skill_dirs = []
    if os.path.isdir(SKILLS_DIR):
        skill_dirs = sorted(
            os.path.join(SKILLS_DIR, entry)
            for entry in os.listdir(SKILLS_DIR)
            if os.path.isdir(os.path.join(SKILLS_DIR, entry))
            and not entry.startswith((".", "_"))
        )
    if not record(bool(skill_dirs), "compiled: at least one skill folder under skills/"):
        skill_dirs = []
    for skill_dir in skill_dirs:
        verify_skill(skill_dir)

    failures = [item for item in results if not item[0]]
    if not args.quiet or failures:
        for ok, label, detail in results:
            line = f"[{'PASS' if ok else 'FAIL'}] {label}"
            if detail and not ok:
                line += f" :: {detail}"
            print(line)
    print(f"{len(results) - len(failures)}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
