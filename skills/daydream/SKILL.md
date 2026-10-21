---
name: daydream
description: Daydream on a problem in one of three modes. `wander` alternates low-
  and high-temperature streams with random word cutoffs, word sampling and injected
  events (the original wander algorithm, headless). `markov` fits an order-k Markov
  chain over the wandering text and walks it, producing a dream that needs no further
  model calls. `tinytim` dreams with the TinyTim 1B model running locally through
  Ollama (or the HF checkpoint), so nothing leaves the machine. Use when the user
  wants divergent, associative thinking rather than analysis, a summary, or a plan.
source_jinx: daydream.jinx
engine: skill
allowed-tools: Read Bash
argument-hint: "<problem>"
when_to_use: User asks to daydream, wander, brainstorm divergently, free-associate, or wants associative rather than analytical thinking.
---

# daydream

Daydream on a problem in one of three modes. `wander` alternates low- and high-temperature streams with random word cutoffs, word sampling and injected events (the original wander algorithm, headless). `markov` fits an order-k Markov chain over the wandering text and walks it, producing a dream that needs no further model calls. `tinytim` dreams with the TinyTim 1B model running locally through Ollama (or the HF checkpoint), so nothing leaves the machine. Use when the user wants divergent, associative thinking rather than analysis, a summary, or a plan.

## Inputs

- `mode` (default: `'wander'`)
- `problem` (default: `None`)
- `environment` (default: `None`)
- `low_temp` (default: `0.5`)
- `high_temp` (default: `1.9`)
- `n_min` (default: `30`)
- `n_max` (default: `150`)
- `interruption_likelihood` (default: `0.1`)
- `sample_rate` (default: `0.5`)
- `n_streams` (default: `6`)
- `include_events` (default: `True`)
- `num_events` (default: `3`)
- `synthesis` (default: `True`)
- `markov_order` (default: `2`)
- `markov_walks` (default: `3`)
- `markov_walk_words` (default: `90`)
- `markov_temperature` (default: `0.9`)
- `markov_rounds` (default: `1`)
- `n_seed_streams` (default: `4`)
- `tinytim_backend` (default: `None`)
- `tinytim_host` (default: `None`)
- `tinytim_model` (default: `None`)
- `tinytim_repo` (default: `None`)
- `tinytim_max_tokens` (default: `160`)
- `seed` (default: `None`)
- `model` (default: `None`)
- `provider` (default: `None`)

## Steps

- `run_daydream` → [`run_daydream.py`](./run_daydream.py)

## Usage

Run the step with Bash from this skill's directory. It is self-contained: no
npcpy, no npcsh, no network for `markov` once seeds exist.

```bash
python3 daydream.py --mode markov --problem "why do we dream"
python3 daydream.py --mode tinytim --problem "why do we dream" --tinytim-max-tokens 120
python3 daydream.py --mode wander --problem "why do we dream" --n-streams 2 --no-events --no-synthesis
python3 daydream.py --json --mode markov --problem "why do we dream"
```

Pick the mode from what the user wants:

| mode | use when | cost |
| --- | --- | --- |
| `markov` | cheapest; a dream of a dream, or when the machine is busy | seeds need a model, walks are free |
| `wander` | divergent associative text with interruptions | one generation per stream |
| `tinytim` | the user wants it fully local, or no other model is reachable | local 1B, ~6 tok/s |

Practical notes:

- `markov` and `wander` seed from a model. With no host model configured they
  fall back to local TinyTim, so they still work offline.
- Generation is bounded by `--tinytim-max-tokens` (default 160). Raise it for
  longer dreams, lower it when a run feels slow.
- A default `wander` run is 6 streams and can take minutes on a small box. Use
  `--n-streams 2 --no-events --no-synthesis` for a quick look.
- Add `--seed 7` for a reproducible run.
- `--json` emits the full report instead of prose.

TinyTim stays on this machine: default backend is `ollama` at
`http://localhost:11434`. Pull the weights once if the run reports the model is
missing:

```bash
ollama pull hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M
```
