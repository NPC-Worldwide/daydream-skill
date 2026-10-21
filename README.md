# daydream-skill

A jinx skill that daydreams, plus the machinery that proves the compiled
version of it still loads — in npcsh, in Claude Code, and in any other runtime
that reads `SKILL.md`.

`daydream.jinx` is the source. `skills/daydream/` is the artifact: a flat
folder with a `SKILL.md` and importable Python, which is what agent runtimes
read. The pre-commit hook compiles one from the other and refuses the commit if
the result does not work.

```
daydream.jinx              jinx source of truth
scripts/
  daydream.py              runtime + standalone CLI
  markov.py                order-k chain: fit / walk / stats
  tinytim.py               local TinyTim client
  compile_skill.py         jinx -> skills/daydream
  verify_skill.py          29 checks, non-zero exit on failure
  skill_usage.md           the Usage block spliced into SKILL.md
  install_claude_skill.sh  symlink into ~/.claude/skills
skills/daydream/           the compiled artifact (committed)
hooks/pre-commit           compile, verify, re-stage the artifact
.github/workflows/verify.yml
```

## Three modes

The agent picks one via the `mode` input.

| mode | what happens | model calls |
| --- | --- | --- |
| `wander` | Alternating low/high temperature streams, random word-count cutoffs, word subsampling, injected events. The original wander algorithm, headless. | yes, host NPC |
| `markov` | Fits an order-`k` Markov chain over the wandering text and walks it. `markov_rounds > 1` walks the chain built from the walks. | seeds only, walks are free |
| `tinytim` | Same wandering, dreamed by the TinyTim 1B locally. | yes, local |

`markov` is the cheap one: once the corpus exists, walking costs nothing and
can be repeated forever, producing a dream of a dream.

## TinyTim stays on your machine

Default backend is `ollama` at `http://localhost:11434` with
`hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M`. Pull it once:

```
ollama pull hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M
```

The `api` backend has no default URL and only fires if `TINYTIM_API_URL` is
set, so a copy of this skill cannot silently point other people's prompts at
someone else's GPU. `verify_skill.py` asserts that default is still localhost.

| env var | default |
| --- | --- |
| `TINYTIM_BACKEND` | `ollama` (`ollama` / `hf` / `api`) |
| `OLLAMA_HOST` | `http://localhost:11434` |
| `TINYTIM_OLLAMA_MODEL` | `hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M` |
| `TINYTIM_HF_REPO` | `npc-worldwide/tinytim-v2-1b-it` |
| `TINYTIM_API_URL` | unset |

## Use it in Claude Code

A symlink, so the compiled folder stays the single source of truth and the
pre-commit hook keeps Claude's view fresh. Claude Code reads `SKILL.md` through
a symlinked skill folder by design.

```bash
bash scripts/install_claude_skill.sh               # ~/.claude/skills (all projects)
bash scripts/install_claude_skill.sh --project .   # ./.claude/skills (this repo)
```

Then either invoke it directly or just describe the task and let Claude pick it:

```
/daydream why do we dream
```

Claude sets `--mode markov` for cheap runs and `--mode tinytim` when it should
stay on the machine; the skill body documents the trade-offs. `allowed-tools:
Read Bash` is in the frontmatter, so an invoked skill does not prompt for
permission on every command.

## Use it in npcsh

The jinx takes `mode` and `problem`:

```
/run_jinx jinx_ref=daydream input_values={"mode":"markov","problem":"why do we dream"}
```

## Use it standalone

No npcpy needed for `markov`:

```bash
python3 scripts/daydream.py --mode markov --problem "why do we dream"
python3 scripts/daydream.py --mode tinytim --problem "why do we dream" --tinytim-max-tokens 120
python3 scripts/daydream.py --mode wander --problem "why do we dream" --n-streams 2 --no-events --no-synthesis
python3 scripts/daydream.py --help
```

`wander` and `tinytim` need a reachable model; if the host NPC's provider is
unavailable they fall back to local TinyTim.

## The hook

```bash
bash hooks/install_hook.sh
```

It **appends** to an existing pre-commit hook (never overwrites), is
idempotent, and no-ops unless a change under this folder is staged.

On a relevant commit it recompiles the skill and runs 29 checks: frontmatter
contract, Claude loader rules, skill-slug validity, no leftover jinja, every
module compiles, the folder imports and walks a chain offline in a fresh
process, the step script loads without a jinx context, the body carries no
npcsh-only command, and the TinyTim default is still localhost. Any failure
refuses the commit. The artifact is re-staged so the commit always holds
matching source and artifact.

Compiling needs `npcpy`; if it is not importable the hook warns and still runs
the verification against the already-compiled folder.

If you use the `pre-commit` framework instead, `.pre-commit-config.yaml` has
the same two steps.

## CI

`.github/workflows/verify.yml` verifies the committed artifact on every push,
then recompiles and fails if the result differs from what is committed — so a
jinx edit that was never recompiled cannot land.

## License

MIT
