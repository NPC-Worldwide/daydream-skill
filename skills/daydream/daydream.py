"""Daydream: three ways to let a mind wander.

Modes
-----
wander            Dual-temperature streams with random word cutoffs, word
                  sampling and injected events. The original wander algorithm,
                  made headless so it can run as a skill. Equivalent to the
                  `temperature_switch` tool in the divergence survey.
markovian_drift   Streams generated in chunks whose sampling temperature is
                  resampled by an AR(1)/Ornstein-Uhlenbeck process: a Markov
                  chain on the temperature, not on the text. Each chunk is a
                  fresh call at the drifted temperature, prompted with the text
                  so far. Equivalent to the `markovian_drift` tool in the
                  divergence survey.
tinytim           The same wandering, dreamed by TinyTim 1B running locally.
                  Equivalent to `tinytim_explore`.

Entry points
------------
    run(context) -> str          the npcsh jinx contract
    python daydream.py --mode markovian_drift --problem "why do we dream?"
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

import drift
import tinytim

MODES = ("wander", "markovian_drift", "tinytim")

# Names used in the papers repo map onto these modes, so an agent reproducing
# that work can ask for the tool name it knows.
MIN_LAG1_SAMPLES = 8

MODE_ALIASES = {
    "temperature_switch": "wander",
    "markov": "markovian_drift",
    "tinytim_explore": "tinytim",
}

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

    def generate(prompt, temperature=1.0, system_prompt=None, max_tokens=None):
        limit = int(max_tokens) if max_tokens else tiny_max_tokens
        if not use_tinytim and (model or provider or npc is not None):
            try:
                from npcpy.llm_funcs import get_llm_response

                kwargs = dict(model=model, provider=provider,
                              temperature=temperature, npc=npc,
                              max_tokens=limit)
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
            max_tokens=limit,
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
        "drift": None,
        "synthesis": synthesis,
        "backend": "tinytim" if mode == "tinytim" else "host",
        "tinytim": tinytim.health() if mode == "tinytim" else None,
    }


def drift_dream_stream(generate, problem, environment, history, events, cfg):
    """One stream whose sampling temperature drifts per chunk.

    Same seed/context construction as a high-temperature wandering stream, but
    instead of one call at one temperature the stream is generated in chunks,
    each at the next value of the AR(1) temperature process.
    """
    rng = cfg["rng"]
    seeds = subsample_words(history[-1]["insight"], k=20) if history else []
    seed_text = " ".join(seeds) if seeds else problem

    event = None
    if (cfg["include_events"] and events
            and rng.random() < cfg["interruption_likelihood"]):
        event = events[rng.randrange(len(events))]

    prompt = (
        f"Seeds: {seed_text}\n\nContext: {environment}\n"
        f"Problem: \"{problem}\""
    )
    if event:
        prompt += f"\n\nSuddenly, {event['text']}"

    result = drift.stream(
        generate,
        prompt,
        mu=cfg["drift_mu"],
        sigma=cfg["drift_sigma"],
        rho=cfg["drift_rho"],
        chunk_tokens=cfg["drift_chunk_tokens"],
        max_tokens=cfg["drift_max_tokens"],
        rng=rng,
    )

    insight = result["text"]
    record = {
        "index": len(history) + 1,
        "temperature": round(result.get("mean_temp", 0.0), 3),
        "temperatures": [round(t, 3) for t in result["temps"]],
        "drift": result.get("stats"),
        "chunks": len(result["chunks"]),
        "words": len(insight.split()),
        "insight": insight,
        "samples": extract_samples(insight, cfg["sample_rate"]),
        "event": event,
    }
    if result.get("error"):
        record["error"] = result["error"]
    return record


def run_markovian_drift(generate, problem, cfg):
    """Wandering streams drawn with a Markovian-drifting temperature.

    Not an n-gram text chain: the Markov process is on the sampler's
    temperature. See drift.py for the AR(1) definition.
    """
    environment = cfg["environment"] or build_environment(generate, problem)
    streams = []
    events = []
    for _ in range(cfg["n_streams"]):
        streams.append(
            drift_dream_stream(generate, problem, environment, streams, events, cfg))

    samples = [word for stream in streams for word in stream["samples"]]
    synthesis = (
        synthesize(generate, problem, environment,
                   [stream["insight"] for stream in streams], samples, events, cfg)
        if cfg["synthesis"] else ""
    )

    all_temps = [temp for stream in streams for temp in stream["temperatures"]]
    pooled = drift.stats(all_temps)
    # Lag-1 over concatenated streams would measure the jump from one stream's
    # end to the next one's start, which is not the process. Average the
    # per-stream autocorrelation instead.
    pooled["lag1"] = drift.pooled_lag1(
        [stream["temperatures"] for stream in streams])

    return {
        "mode": "markovian_drift",
        "problem": problem,
        "environment": environment,
        "streams": streams,
        "events": events,
        "samples": samples,
        "drift": {
            "mu": cfg["drift_mu"],
            "sigma": cfg["drift_sigma"],
            "rho": cfg["drift_rho"],
            "chunk_tokens": cfg["drift_chunk_tokens"],
            "max_tokens": cfg["drift_max_tokens"],
            "trajectories": [stream["temperatures"] for stream in streams],
            "pooled": pooled,
        },
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
                f"### Stream {stream['index']} (mean T={stream['temperature']}, "
                f"{stream['words']} words, {stream.get('chunks', 0)} chunks)"
            )
            lines.append("")
            if stream.get("temperatures"):
                lines.append(
                    "`" + " -> ".join(f"{t:.2f}" for t in stream["temperatures"]) + "`")
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

    if report.get("drift"):
        info = report["drift"]
        pooled = info["pooled"]
        lines += [
            "## Temperature drift",
            "",
            f"- process: AR(1) / Ornstein-Uhlenbeck on the sampling temperature",
            f"- mu (mean temp): {info['mu']}",
            f"- sigma (stationary sd): {info['sigma']}",
            f"- rho (lag-1 autocorrelation): {info['rho']}",
            f"- chunk: {info['chunk_tokens']} tokens, budget: {info['max_tokens']} tokens",
            "",
            f"Pooled over all chunks: mean {pooled['mean']:.3f}, "
            f"sd {pooled['sd']:.3f}, mean |step| {pooled['mean_abs_step']:.3f}",
            "",
        ]
        shortest = min((len(t) for t in info["trajectories"]), default=0)
        if shortest >= MIN_LAG1_SAMPLES:
            lines.append(
                f"Estimated lag-1 autocorrelation: {pooled['lag1']:.3f} "
                f"(target rho {info['rho']})")
            lines.append("")
        else:
            lines.append(
                f"Lag-1 autocorrelation needs at least {MIN_LAG1_SAMPLES} chunks "
                f"per stream to estimate (shortest was {shortest}).")
            lines.append("")
        for index, temps in enumerate(info["trajectories"], 1):
            trail = ", ".join(f"{t:.2f}" for t in temps)
            lines.append(f"- stream {index} trajectory: [{trail}]")
        lines.append("")

    if report["synthesis"]:
        lines += ["## Synthesis", "", report["synthesis"], ""]

    lines += [
        "## Next steps",
        "",
        "1. Star the streams that surprised you.",
        "2. Raise `drift_sigma` or `drift_rho` if the drift felt too flat; set "
        "`drift_rho` to 0 to compare against independent sampling.",
        "3. Compare `markovian_drift` against `wander` on the same problem: drift "
        "should show higher temporal variance in the temperatures.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------- entrypoint

def run(context):
    """npcsh jinx entry point. Sets context['output'] and context['daydream_result']."""
    mode = str(_get(context, "mode", "wander")).strip().lower()
    mode = MODE_ALIASES.get(mode, mode)
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
        "drift_mu": _num(context, "drift_mu", 1.0),
        "drift_sigma": max(0.0, _num(context, "drift_sigma", 0.3)),
        "drift_rho": max(-0.99, min(0.99, _num(context, "drift_rho", 0.8))),
        "drift_chunk_tokens": max(1, _num(context, "drift_chunk_tokens", 20, int)),
        "drift_max_tokens": max(1, _num(context, "drift_max_tokens", 60, int)),
        "n_seed_streams": max(1, _num(context, "n_seed_streams", 4, int)),
        "rng": random.Random(seed if seed is not None else None),
    }

    if mode == "markovian_drift":
        report = run_markovian_drift(make_generator(context), problem, cfg)
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
        description="Daydream on a problem: wander, markovian_drift, or tinytim.")
    parser.add_argument("--mode", default="wander", choices=MODES)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--n-streams", type=int, default=6, dest="n_streams")
    parser.add_argument("--n-seed-streams", type=int, default=4, dest="n_seed_streams")
    parser.add_argument("--low-temp", type=float, default=0.5, dest="low_temp")
    parser.add_argument("--high-temp", type=float, default=1.9, dest="high_temp")
    parser.add_argument("--drift-mu", type=float, default=1.0, dest="drift_mu",
                        help="mean sampling temperature (default: 1.0)")
    parser.add_argument("--drift-sigma", type=float, default=0.3, dest="drift_sigma",
                        help="stationary sd of the temperature (default: 0.3)")
    parser.add_argument("--drift-rho", type=float, default=0.8, dest="drift_rho",
                        help="lag-1 autocorrelation of the drift (default: 0.8)")
    parser.add_argument("--drift-chunk-tokens", type=int, default=20,
                        dest="drift_chunk_tokens",
                        help="tokens generated per temperature sample (default: 20)")
    parser.add_argument("--drift-max-tokens", type=int, default=60,
                        dest="drift_max_tokens",
                        help="token budget per drifting stream (default: 60)")
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
