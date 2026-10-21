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
