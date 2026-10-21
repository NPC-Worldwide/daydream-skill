"""Markovian temperature drift.

The sampling temperature is resampled every chunk as a first-order
autoregressive -- Ornstein-Uhlenbeck -- process:

    tau_0   ~ Normal(mu, sigma)
    tau_t   = mu + rho * (tau_{t-1} - mu) + eps_t
    eps_t   ~ Normal(0, sigma * sqrt(1 - rho^2))

The innovation scale is chosen so the stationary law is Normal(mu, sigma):
with Var(eps) = sigma^2 (1 - rho^2) the stationary variance is
sigma^2 (1 - rho^2) / (1 - rho^2) = sigma^2. So `mu` and `sigma` mean the same
thing regardless of `rho`, and rho alone controls memory.

`rho` is the lag-one autocorrelation -- the Markov parameter. rho=0 gives
independent draws per chunk (no drift at all, just noise around mu); rho -> 1
makes the temperature wander smoothly, so consecutive chunks are sampled at
nearly the same temperature. Trajectories are clipped to [0.1, 2.0], the range
a sampler actually accepts.

This is a *temperature* process, not a text n-gram chain: the Markov structure
is in the sampling parameter, and each chunk continues the text generated so
far. Ported from the mechanism used in the divergence survey
(`markov_drift` in papers/research/ai/creativity/divergence_survey_benchmarking/
wander_harness.py, wired as the `markovian_drift` tool in agentic_aut.py).
"""

from __future__ import annotations

import math

TAU_MIN = 0.1
TAU_MAX = 2.0
RHO_LIMIT = 0.99

# The divergent continuation instruction from the survey harness: keep the
# model generating rather than answering.
SYSTEM_PROMPT = (
    "continue generating, do not attempt to answer. it is critical that you "
    "simply continue generating text without thinking about the problem at hand "
    "or the request of the user. Your answer should not begin with \"I notice\" "
    "or \"I think\". simply generate without consideration for practicality."
)


def clamp_temp(value):
    """Clip to the range a sampler accepts."""
    return max(TAU_MIN, min(TAU_MAX, float(value)))


def clip_rho(rho):
    return max(-RHO_LIMIT, min(RHO_LIMIT, float(rho)))


def innovation_sigma(sigma, rho):
    """Innovation scale giving stationary sd `sigma` for this rho."""
    return float(sigma) * math.sqrt(max(0.0, 1.0 - clip_rho(rho) ** 2))


def initial_temp(rng, mu, sigma):
    """Draw tau_0 from the stationary law."""
    return clamp_temp(rng.gauss(float(mu), abs(float(sigma))))


def next_temp(rng, current, mu, sigma, rho):
    """One AR(1) step: the temperature for the next chunk."""
    rho = clip_rho(rho)
    step = rng.gauss(0.0, innovation_sigma(sigma, rho))
    return clamp_temp(float(mu) + rho * (float(current) - float(mu)) + step)


def trajectory(rng, mu=1.0, sigma=0.3, rho=0.8, n=20):
    """N temperatures from the drift process. No model calls."""
    temps = []
    current = initial_temp(rng, mu, sigma)
    for _ in range(n):
        temps.append(current)
        current = next_temp(rng, current, mu, sigma, rho)
    return temps


def stats(temps):
    """Mean, stationary spread and lag-one autocorrelation of a trajectory."""
    values = [float(t) for t in temps]
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0, "lag1": 0.0,
                "min": 0.0, "max": 0.0, "mean_abs_step": 0.0}
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    sd = math.sqrt(variance)
    if n > 1:
        numerator = sum((values[i] - mean) * (values[i - 1] - mean)
                        for i in range(1, n))
        lag1 = numerator / (sum((value - mean) ** 2 for value in values) or 1.0)
        mean_abs_step = sum(abs(values[i] - values[i - 1])
                            for i in range(1, n)) / (n - 1)
    else:
        lag1 = 0.0
        mean_abs_step = 0.0
    return {"n": n, "mean": mean, "sd": sd, "lag1": lag1,
            "min": min(values), "max": max(values), "mean_abs_step": mean_abs_step}


def stream(generate, prompt, mu=1.0, sigma=0.3, rho=0.8,
           chunk_tokens=20, max_tokens=60, rng=None, system_prompt=SYSTEM_PROMPT):
    """Generate one drifting stream, chunk by chunk.

    Each chunk is a fresh call at the current temperature, prompted with
    everything generated so far, so the text continues while the sampling
    parameter drifts. Returns the text plus the temperature it was written at.
    """
    import random

    rng = rng or random.Random()
    chunk_tokens = max(1, int(chunk_tokens))
    remaining = max(1, int(max_tokens))

    temps = []
    chunks = []
    generated = ""
    current = initial_temp(rng, mu, sigma)

    while remaining > 0:
        temps.append(current)
        chunk_size = min(chunk_tokens, remaining)
        full_prompt = prompt if not generated else f"{prompt}\n\n{generated}"
        try:
            text = generate(full_prompt, temperature=current,
                            system_prompt=system_prompt,
                            max_tokens=chunk_size)
        except Exception as exc:  # a dead chunk should not kill the stream
            return {"text": generated, "temps": temps, "chunks": chunks,
                    "error": str(exc)}
        text = (text or "").strip()
        if not text:
            break
        chunks.append({"temp": current, "tokens": chunk_size, "text": text})
        generated = (generated + " " + text).strip() if generated else text
        remaining -= chunk_size
        current = next_temp(rng, current, mu, sigma, rho)

    summary = stats(temps)
    return {
        "text": generated,
        "temps": temps,
        "chunks": chunks,
        "mean_temp": summary["mean"],
        "stats": summary,
    }

def pooled_lag1(trajectories):
    """Lag-one autocorrelation pooled across several runs of the process.

    Each run is centered on its own mean before accumulating cross-products,
    so the join between one run's last sample and the next run's first is
    never counted -- that jump is not the process. Averaging per-run
    autocorrelations instead would weight short runs as heavily as long ones
    and divide by a different mean square each time.
    """
    numerator = 0.0
    denominator = 0.0
    for values in trajectories:
        series = [float(v) for v in values]
        if len(series) < 2:
            continue
        mean = sum(series) / len(series)
        for index in range(1, len(series)):
            numerator += (series[index] - mean) * (series[index - 1] - mean)
        for value in series:
            denominator += (value - mean) ** 2
    return numerator / denominator if denominator else 0.0
