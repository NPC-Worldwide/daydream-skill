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
  drift.py                 Markovian temperature drift (AR(1) / OU process)
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

The agent picks one via the `mode` input. These mirror the three exploration
tools in `papers/research/ai/creativity/divergence_survey_benchmarking`
(`temperature_switch`, `markovian_drift`, `tinytim_explore`), all of which are
accepted as aliases.

| mode | what happens | model calls |
| --- | --- | --- |
| `wander` | Alternating low/high temperature streams, random word-count cutoffs, word subsampling, injected events. The original wander algorithm, headless. | one per stream |
| `markovian_drift` | Each stream is generated in chunks, and the sampling temperature is resampled between chunks by an AR(1) process. | one per chunk |
| `tinytim` | The same wandering, dreamed by the TinyTim 1B locally. | one per stream, local |

## Markovian drift

The `markovian_drift` mode is **not** an n-gram text chain. The Markov structure
is on the sampler's temperature:

```
tau_0 = Normal(mu, sigma)
tau_t = mu + rho * (tau_{t-1} - mu) + eps_t      eps_t ~ Normal(0, sigma*sqrt(1 - rho^2))
```

The innovation scale is chosen so the stationary law is `Normal(mu, sigma)`
whatever `rho` is: with `Var(eps) = sigma^2 (1 - rho^2)`, the stationary
variance is `sigma^2 (1 - rho^2) / (1 - rho^2) = sigma^2`. So `rho` alone
controls memory, and `rho = 0` degrades to independent sampling per chunk — the
control condition.

Each chunk is a fresh call at the current temperature, prompted with the text
generated so far, under the divergent-continuation system instruction from the
survey harness. Temperatures are clipped to `[0.1, 2.0]`.

| flag | meaning | default |
| --- | --- | --- |
| `--drift-mu` | mean sampling temperature | `1.0` |
| `--drift-sigma` | stationary sd of the temperature | `0.3` |
| `--drift-rho` | lag-1 autocorrelation (the memory) | `0.8` |
| `--drift-chunk-tokens` | tokens per temperature sample | `20` |
| `--drift-max-tokens` | token budget per stream | `60` |

Budgets are deliberately short: the survey reports decoherence as temperature
and stream length grow, so a long drifting stream drifts into noise.

`verify_skill.py` checks the process offline against its stationary law
(mean→`mu`, sd→`sigma`, lag-1→`rho` within tolerance over 20k samples), that
`rho=0` is indistinguishable from independent sampling, that persistence grows
monotonically with `rho`, and that every chunk budget actually reaches the
model — otherwise the chunking would be cosmetic.

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

`allowed-tools: Read Bash` is in the frontmatter, so an invoked skill does not
prompt for permission on every command.

## Use it in npcsh

The jinx takes `mode` and `problem`:

```
/run_jinx jinx_ref=daydream input_values={"mode":"markovian_drift","problem":"why do we dream"}
```

## Use it standalone

No npcpy needed for the temperature process:

```bash
python3 scripts/daydream.py --mode markovian_drift --problem "why do we dream"
python3 scripts/daydream.py --mode wander --problem "why do we dream" --n-streams 2 --no-events --no-synthesis
python3 scripts/daydream.py --mode tinytim --problem "why do we dream" --tinytim-max-tokens 120
python3 scripts/daydream.py --help
```

`wander` and `tinytim` seed from a model; if the host NPC's provider is
unavailable they fall back to local TinyTim.

## The hook

```bash
bash hooks/install_hook.sh
```

It **appends** to an existing pre-commit hook (never overwrites), is
idempotent, and no-ops unless a change under this folder is staged.

On a relevant commit it recompiles the skill and runs 29 checks: frontmatter
contract, Claude loader rules, skill-slug validity, no leftover jinja, every
module compiles, the folder imports offline in a fresh process and the drift
process matches its stationary law, the step script loads without a jinx
context, the body carries no npcsh-only command, and the TinyTim default is
still localhost. Any failure refuses the commit. The artifact is re-staged so
the commit always holds matching source and artifact.

Compiling needs `npcpy`, and importing it costs about 20 seconds -- so the
compile step records a hash of its inputs (`daydream.jinx`, the runtime
modules, `skill_usage.md`, and `compile_skill.py` itself) in a gitignored
`skills/.compile_stamp`. When nothing feeding the compile has changed the hook
skips the recompile and goes straight to verification, which takes under a
second. Touching any input re-triggers a real compile. If `npcpy` is not
importable the hook warns and still runs the verification against the
already-compiled folder.

If you use the `pre-commit` framework instead, `.pre-commit-config.yaml` has
the same two steps.

## CI

`.github/workflows/verify.yml` verifies the committed artifact on every push,
then recompiles and fails if the result differs from what is committed — so a
jinx edit that was never recompiled cannot land.

## License

MIT
