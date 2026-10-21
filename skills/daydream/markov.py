"""Markovian wandering: an order-k word chain you can walk.

Pure functions over a plain dict, no dependencies beyond the stdlib.

    chain = fit(["the dream keeps walking"], order=2)
    text, steps, restarts = walk(chain, order=2, n_words=60)
"""

from __future__ import annotations

import math
import random

START = "\x00<S>"
END = "\x00</S>"

Chain = dict


def tokenize(text):
    return text.split()


def fit(texts, order=2):
    """Build {tuple_of_n_words: {next_word: count}} from an iterable of texts."""
    depth = max(1, int(order))
    chain = {}
    for text in texts:
        if not text:
            continue
        tokens = [START] * depth + tokenize(text) + [END]
        for i in range(len(tokens) - depth):
            key = tuple(tokens[i:i + depth])
            following = tokens[i + depth]
            row = chain.setdefault(key, {})
            row[following] = row.get(following, 0) + 1
    return chain


def sample_next(chain, key, temperature=1.0, rng=None):
    """Draw the next word. Higher temperature flattens the distribution."""
    rng = rng or random
    row = chain.get(key) or {}
    if not row:
        return None
    words = list(row)
    heat = max(1e-3, float(temperature))
    weights = [count ** (1.0 / heat) for count in row.values()]
    return rng.choices(words, weights=weights, k=1)[0]


def walk(chain, order=2, n_words=90, temperature=1.0, seed_text=None, rng=None):
    """Walk the chain from `seed_text` (or the start token).

    Returns (text, steps_taken, restarts).
    """
    rng = rng or random
    depth = max(1, int(order))
    if not chain:
        return "", 0, 0

    keys = list(chain)
    if seed_text and seed_text.split():
        tokens = seed_text.split()
        key = tuple(tokens[-depth:]) if len(tokens) >= depth else (START,) * depth
        if key not in chain:
            key = (START,) * depth
    else:
        key = (START,) * depth
    if key not in chain:
        key = rng.choice(keys)

    out = []
    steps = 0
    restarts = 0
    while len(out) < n_words and steps < n_words * 8:
        steps += 1
        following = sample_next(chain, key, temperature=temperature, rng=rng)
        if following is None or following == END:
            if len(out) >= n_words:
                break
            restarts += 1
            if restarts > 12:
                break
            key = rng.choice(keys)
            continue
        out.append(following)
        key = tuple(list(key)[1:] + [following])
    return " ".join(out[:n_words]), steps, restarts


def stats(chain):
    states = len(chain)
    if not states:
        return {"states": 0, "transitions": 0, "branching": 0.0, "entropy": 0.0}
    transitions = sum(len(row) for row in chain.values())
    entropy = 0.0
    for row in chain.values():
        total = sum(row.values())
        if not total:
            continue
        for count in row.values():
            p = count / total
            entropy -= p * math.log(p)
    return {
        "states": states,
        "transitions": transitions,
        "branching": round(transitions / states, 2),
        "entropy": round(entropy / states, 3),
    }
