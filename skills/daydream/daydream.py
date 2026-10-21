"""Daydream: three ways to let a mind wander.

Modes
-----
wander    Dual-temperature streams with random word cutoffs, word sampling
          and injected events. This is the original wander algorithm, made
          headless so it can run as a skill.
markov    Fit an order-k Markov chain over the wandering text and walk it.
          The walk itself is the dream and needs no further model calls.
tinytim   The same wandering, dreamed by TinyTim 1B running locally.

Entry points
------------
    run(context) -> str          the npcsh jinx contract
    python daydream.py --mode markov --problem "why do we dream?"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import markov
import tinytim

MODES = ("wander", "markov", "tinytim")

EVENT_WEIGHTS = {
    "encounter": 0.20,
    "discovery": 0.20,
    "obstacle": 0.15,
    "insight": 0.20,
    "shift": 0.10,
    "memory": 0.15,
}


# ---------------------------------------------------------------- context utils

def _get(context, key, default=None):
    value = context.get(key)
    if value is None or value == "" or value == "null":
        return default
    return value


def _num(context, key, default, cast=float):
    try:
        return cast(_get(context, key, default))
    except (TypeError, ValueError):
        return cast(default)


def _flag(context, key, default=True):
    value = _get(context, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


# ------------------------------------------------------------------- generation

def make_generator(context, use_tinytim=False):
    """Return generate(prompt, temperature, system_prompt) -> text.

    Prefers the host NPC's model through npcpy; falls back to local TinyTim so
    the skill still works when npcpy or the provider is unavailable.
    """
    npc = context.get("npc")
    team = context.get("team")
    if isinstance(npc, str):
        npc = team.get(npc) if hasattr(team, "get") else None
    model = _get(context, "model") or getattr(npc, "model", None)
    provider = _get(context, "provider") or getattr(npc, "provider", None)
    tiny_config = tinytim.resolve_config({
        "backend": _get(context, "tinytim_backend"),
        "ollama_host": _get(context, "tinytim_host"),
        "ollama_model": _get(context, "tinytim_model"),
        "hf_repo": _get(context, "tinytim_repo"),
        "api_url": _get(context, "tinytim_api_url"),
    })
    tiny_max_tokens = max(32, _num(context, "tinytim_max_tokens", 160, int))

    def generate(prompt, temperature=1.0, system_prompt=None):
        if not use_tinytim and (model or provider or npc is not None):
            try:
                from npcpy.llm_funcs import get_llm_response

                kwargs = dict(model=model, provider=provider,
                              temperature=temperature, npc=npc)
                if system_prompt:
                    kwargs["system_prompt"] = system_prompt
                response = get_llm_response(prompt, **kwargs)
                text = response.get("response") if isinstance(response, dict) else response
                if text:
                    return str(text)
            except Exception:
                pass
        return tinytim.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=min(float(temperature), 1.5),
            max_tokens=tiny_max_tokens,
            config=tiny_config,
        )

    return generate


# ------------------------------------------------------------- wander primitives

def truncate_to_word_count(text, limit):
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit])


def subsample_words(text, k=20):
    words = text.split()
    if len(words) <= k:
        return words
    return random.sample(words, k)


def extract_samples(text, rate):
    words = text.split()
    if not words:
        return []
    count = max(1, int(len(words) * rate))
    if len(words) <= count:
        return words
    return random.sample(words, count)


def weighted_event_type(rng):
    kinds = list(EVENT_WEIGHTS)
    weights = [EVENT_WEIGHTS[kind] for kind in kinds]
    return rng.choices(kinds, weights=weights, k=1)[0]


def build_environment(generate, problem):
    prompt = (
        f'Create a vivid, metaphorical environment for wandering through while exploring:\n"{problem}"\n\n'
        "The environment should have distinct regions that map to aspects of the problem, "
        "include sensory details (sights, sounds, textures), feel alive and explorable, "
        "and be described in 4-6 evocative sentences. Respond with only the description."
    )
    try:
        text = generate(prompt, temperature=0.8)
    except Exception:
        text = ""
    return text.strip() or "A vast conceptual landscape stretches before you."


def trigger_event(generate, problem, environment, rng):
    kind = weighted_event_type(rng)
    prompt = (
        f"In the environment: {environment}\n"
        f'While exploring "{problem}", a {kind} occurs.\n\n'
        f"Describe this {kind} in 2-3 vivid sentences. Make it metaphorical and thought-provoking."
    )
    try:
        text = generate(prompt, temperature=1.0)
    except Exception:
        text = f"A {kind} occurred but faded before you could grasp it."
    return {"type": kind, "text": text.strip()}


def dream_stream(generate, problem, environment, history, events, cfg):
    """One wandering stream: alternate temperature, truncate, sample, maybe event."""
    low_temp = cfg["low_temp"]
    high_temp = cfg["high_temp"]
    index = len(history)
    temperature = low_temp if index % 2 == 0 else high_temp
    is_high = index % 2 == 1
    word_limit = random.randint(cfg["n_min"], cfg["n_max"])

    if is_high:
        seeds = subsample_words(history[-1]["insight"], k=20) if history else []
        seed_text = " ".join(seeds) if seeds else problem
        system_prompt = (
            "Just generate without thinking. Let words and ideas flow freely. "
            "Do not filter or organize."
        )
        prompt = (
            f"Seeds: {seed_text}\n\nContext: {environment}\nProblem: \"{problem}\"\n\n"
            "Generate freely from these seeds. Follow any tangent. No structure needed."
        )
    else:
        recent = history[-3:]
        recent_context = (
            "\n".join(stream["insight"][:200] for stream in recent)
            if recent else "Starting fresh"
        )
        system_prompt = None
        prompt = (
            f"You are wandering through: {environment}\n\nProblem: \"{problem}\"\n\n"
            f"Recent thoughts: {recent_context}\n\nIn this exploration:\n"
            "- Let associations flow freely\n"
            "- Notice unexpected connections\n"
            "- Follow interesting tangents\n"
            "- Share what emerges\n\n"
            "Respond naturally, 2-4 paragraphs."
        )

    try:
        insight = generate(prompt, temperature=temperature, system_prompt=system_prompt)
    except Exception as exc:
        insight = "Error: " + str(exc)

    if random.random() < cfg["interruption_likelihood"]:
        word_limit = random.randint(max(1, cfg["n_min"] // 2), max(2, cfg["n_min"]))
    insight = truncate_to_word_count(insight, word_limit)
    samples = extract_samples(insight, cfg["sample_rate"])

    stream = {
        "index": index + 1,
        "temperature": round(temperature, 2),
        "insight": insight,
        "words": len(insight.split()),
        "samples": samples,
        "event": None,
    }

    if (is_high and cfg["include_events"]
            and len(events) < cfg["num_events"]
            and random.random() < 0.3):
        event = trigger_event(generate, problem, environment, cfg["rng"])
        events.append(event)
        stream["event"] = event
    return stream


def synthesize(generate, problem, environment, insights, samples, events, cfg):
    sample_text = " ".join(samples[:50]) if samples else "N/A"
    event_text = (
        "; ".join(f"{event['type']}: {event['text'][:100]}" for event in events)
        if events else "None"
    )
    prompt = (
        f'You are synthesizing a wandering exploration of: "{problem}"\n\n'
        f"Environment traversed: {environment}\n\n"
        f"Selected explorations ({len(insights)}):\n{'---'.join(insights)}\n\n"
        f"Word samples extracted during wandering: {sample_text}\n\n"
        f"Events encountered: {event_text}\n\n"
        "From these wanderings, synthesize creative hypotheses:\n"
        "1. What unexpected patterns emerge from the word samples?\n"
        "2. What creative hypotheses can you form by connecting disparate ideas?\n"
        "3. What questions have emerged that weren't visible at the start?\n"
        "4. What surprising connections exist between the different explorations?\n\n"
        "Be bold, creative, and insightful. These hypotheses should feel like "
        "discoveries, not summaries."
    )
    try:
        return generate(prompt, temperature=0.4).strip()
    except Exception as exc:
        return "Synthesis unavailable: " + str(exc)


# ------------------------------------------------------------------------- modes

def run_wander(generate, problem, cfg, mode="wander"):
    environment = cfg["environment"] or build_environment(generate, problem)
    streams = []
    events = []
    for _ in range(cfg["n_streams"]):
        streams.append(dream_stream(generate, problem, environment, streams, events, cfg))
    samples = [word for stream in streams for word in stream["samples"]]
    synthesis = (
        synthesize(generate, problem, environment,
                   [stream["insight"] for stream in streams], samples, events, cfg)
        if cfg["synthesis"] else ""
    )
    return {
        "mode": mode,
        "problem": problem,
        "environment": environment,
        "streams": streams,
        "events": events,
        "samples": samples,
        "chain": None,
        "walks": [],
        "synthesis": synthesis,
        "backend": "tinytim" if mode == "tinytim" else "host",
        "tinytim": tinytim.health() if mode == "tinytim" else None,
    }


def run_markov(generate, problem, cfg):
    environment = cfg["environment"] or build_environment(generate, problem)
    rng = cfg["rng"]

    seed_streams = []
    events = []
    for _ in range(cfg["n_seed_streams"]):
        seed_streams.append(dream_stream(generate, problem, environment, seed_streams, events, cfg))

    corpus = [stream["insight"] for stream in seed_streams]
    samples = [word for stream in seed_streams for word in stream["samples"]]

    chain = markov.fit(corpus, order=cfg["markov_order"])
    chain_stats = markov.stats(chain)

    walks = []
    depth = cfg["markov_order"]
    for index in range(cfg["markov_walks"]):
        seed_text = seed_streams[-1]["insight"] if (index % 2 and seed_streams) else None
        text, steps, restarts = markov.walk(
            chain,
            order=depth,
            n_words=cfg["markov_walk_words"],
            temperature=cfg["markov_temperature"],
            seed_text=seed_text,
            rng=rng,
        )
        walks.append({"index": index + 1, "text": text, "steps": steps,
                      "restarts": restarts, "words": len(text.split())})

    if cfg["markov_rounds"] > 1 and walks:
        dream_chain = markov.fit([entry["text"] for entry in walks], order=depth)
        dream_stats = markov.stats(dream_chain)
        for index in range(cfg["markov_walks"]):
            text, steps, restarts = markov.walk(
                dream_chain,
                order=depth,
                n_words=cfg["markov_walk_words"],
                temperature=cfg["markov_temperature"],
                rng=rng,
            )
            walks.append({"index": len(walks) + 1, "text": text, "steps": steps,
                          "restarts": restarts, "words": len(text.split()),
                          "second_order": True})
    else:
        dream_stats = None

    synthesis = ""
    if cfg["synthesis"] and walks:
        synthesis = synthesize(
            generate,
            problem,
            environment,
            [stream["insight"] for stream in seed_streams] + [entry["text"] for entry in walks],
            samples,
            events,
            cfg,
        )

    return {
        "mode": "markov",
        "problem": problem,
        "environment": environment,
        "streams": seed_streams,
        "events": events,
        "samples": samples,
        "chain": {"order": depth, "corpus": chain_stats,
                  "dream_corpus": dream_stats},
        "walks": walks,
        "synthesis": synthesis,
        "backend": "host",
        "tinytim": None,
    }


def run_tinytim(generate, problem, cfg):
    return run_wander(generate, problem, cfg, mode="tinytim")


# ------------------------------------------------------------------------ render

def render(report):
    lines = [f"# Daydream — {report['mode']}", "", f"**Problem:** {report['problem']}", "",
             "## Environment", "", report["environment"], ""]

    if report.get("tinytim"):
        info = report["tinytim"]
        lines += [
            "## TinyTim",
            "",
            f"- backend: `{info.get('backend')}`",
            f"- ok: `{info.get('ok')}`",
            f"- model: `{info.get('model') or info.get('repo')}`",
            f"- model present: `{info.get('model_present')}`",
            "",
        ]

    if report["streams"]:
        lines += ["## Streams", ""]
        for stream in report["streams"]:
            lines.append(
                f"### Stream {stream['index']} (T={stream['temperature']}, {stream['words']} words)"
            )
            lines.append("")
            lines.append(stream["insight"] or "_(empty)_")
            lines.append("")
            if stream.get("event"):
                lines.append(f"> **[{stream['event']['type']}]** {stream['event']['text']}")
                lines.append("")

    if report["samples"]:
        lines += ["## Word samples", "", "`" + " ".join(report["samples"][:80]) + "`", ""]

    if report["events"]:
        lines += ["## Events", ""]
        for event in report["events"]:
            lines.append(f"- **{event['type']}** — {event['text'][:200]}")
        lines.append("")

    if report.get("chain"):
        corpus = report["chain"]["corpus"]
        lines += [
            "## Markov chain",
            "",
            f"- order: {report['chain']['order']}",
            f"- states: {corpus['states']}",
            f"- transitions: {corpus['transitions']}",
            f"- average branching: {corpus['branching']}",
            f"- entropy (nats/state): {corpus['entropy']}",
            "",
        ]
        if report["chain"].get("dream_corpus"):
            second = report["chain"]["dream_corpus"]
            lines += [
                f"- second-order dream chain: {second['states']} states, "
                f"{second['transitions']} transitions, entropy {second['entropy']}",
                "",
            ]

    if report["walks"]:
        lines += ["## Walks", ""]
        for entry in report["walks"]:
            label = "dream of a dream" if entry.get("second_order") else "walk"
            lines.append(
                f"### {label} {entry['index']} ({entry['words']} words, "
                f"{entry['steps']} steps, {entry['restarts']} restarts)"
            )
            lines.append("")
            lines.append(entry["text"] or "_(the chain had nowhere to go)_")
            lines.append("")

    if report["synthesis"]:
        lines += ["## Synthesis", "", report["synthesis"], ""]

    lines += [
        "## Next steps",
        "",
        "1. Star the streams that surprised you.",
        "2. Re-run with a higher `high_temp` or a higher `markov_order` if the dream was too coherent.",
        "3. Run `markov` over the transcripts to find recurrences you did not notice while reading.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------- entrypoint

def run(context):
    """npcsh jinx entry point. Sets context['output'] and context['daydream_result']."""
    mode = str(_get(context, "mode", "wander")).strip().lower()
    if mode not in MODES:
        mode = "wander"

    problem = str(_get(context, "problem", "")).strip()
    if not problem:
        problem = "What am I avoiding thinking about right now?"

    seed = _get(context, "seed")
    if seed is not None:
        random.seed(str(seed))

    cfg = {
        "environment": _get(context, "environment"),
        "low_temp": _num(context, "low_temp", 0.5),
        "high_temp": _num(context, "high_temp", 1.9),
        "n_min": _num(context, "n_min", 30, int),
        "n_max": _num(context, "n_max", 150, int),
        "interruption_likelihood": _num(context, "interruption_likelihood", 0.1),
        "sample_rate": _num(context, "sample_rate", 0.5),
        "n_streams": max(1, _num(context, "n_streams", 6, int)),
        "include_events": _flag(context, "include_events", True),
        "num_events": _num(context, "num_events", 3, int),
        "synthesis": _flag(context, "synthesis", True),
        "markov_order": max(1, _num(context, "markov_order", 2, int)),
        "markov_walk_words": max(4, _num(context, "markov_walk_words", 90, int)),
        "markov_walks": max(1, _num(context, "markov_walks", 3, int)),
        "markov_temperature": _num(context, "markov_temperature", 0.9),
        "markov_rounds": max(1, _num(context, "markov_rounds", 1, int)),
        "n_seed_streams": max(1, _num(context, "n_seed_streams", 4, int)),
        "rng": random.Random(seed if seed is not None else None),
    }

    if mode == "markov":
        report = run_markov(make_generator(context), problem, cfg)
    elif mode == "tinytim":
        report = run_tinytim(make_generator(context, use_tinytim=True), problem, cfg)
    else:
        report = run_wander(make_generator(context), problem, cfg)

    text = render(report)
    context["output"] = text
    context["daydream_result"] = report
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Daydream on a problem: wander, markov, or tinytim.")
    parser.add_argument("--mode", default="wander", choices=MODES)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--n-streams", type=int, default=6, dest="n_streams")
    parser.add_argument("--n-seed-streams", type=int, default=4, dest="n_seed_streams")
    parser.add_argument("--low-temp", type=float, default=0.5, dest="low_temp")
    parser.add_argument("--high-temp", type=float, default=1.9, dest="high_temp")
    parser.add_argument("--markov-order", type=int, default=2, dest="markov_order")
    parser.add_argument("--markov-walks", type=int, default=3, dest="markov_walks")
    parser.add_argument("--markov-walk-words", type=int, default=90, dest="markov_walk_words")
    parser.add_argument("--markov-rounds", type=int, default=1, dest="markov_rounds")
    parser.add_argument("--seed", default=None)
    parser.add_argument("--no-events", action="store_true", dest="no_events")
    parser.add_argument("--no-synthesis", action="store_true", dest="no_synthesis")
    parser.add_argument("--tinytim-backend", default=None, dest="tinytim_backend")
    parser.add_argument("--tinytim-max-tokens", type=int, default=160,
                        dest="tinytim_max_tokens",
                        help="cap generation per stream (default: 160)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    context = {key: value for key, value in vars(args).items()
               if value is not None and key not in ("json", "no_events", "no_synthesis")}
    context["include_events"] = not args.no_events
    context["synthesis"] = not args.no_synthesis

    text = run(context)
    if args.json:
        print(json.dumps(context.get("daydream_result", {}), indent=2, default=str))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
