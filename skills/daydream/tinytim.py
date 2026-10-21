"""TinyTim client -- local by default.

No hand-rolled HTTP. Two transports, both first-class clients:

- the `ollama` package for the local daemon, so `num_predict` is actually
  honored (npcpy's ollama path forwards max_tokens under a key ollama
  ignores, which lets a 1B model ramble for minutes)
- npcpy's get_llm_response for the opt-in remote endpoint, so that path
  rides the same provider machinery the rest of the team uses

Backends
--------
ollama   npcpy -> local Ollama daemon (default http://localhost:11434).
         Pull the weights once, straight from the Hub:
             ollama pull hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M
hf       Run the same checkpoint from the Hub on this machine via transformers.

There is deliberately no default public endpoint. A skill that gets copied
into other people's agents must never quietly route their prompts at someone
else's GPU, so every default is localhost. A shared endpoint is opt-in:
set TINYTIM_API_URL and the `api` backend uses npcpy with that URL.

Environment
-----------
TINYTIM_BACKEND      ollama | hf | api        (default: ollama)
OLLAMA_HOST          default http://localhost:11434
TINYTIM_OLLAMA_MODEL default hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M
TINYTIM_HF_REPO      default npc-worldwide/tinytim-v2-1b-it
TINYTIM_API_URL      unset by default; opt-in remote
TINYTIM_API_KEY      unset by default
TINYTIM_TIMEOUT      seconds, default 120
"""

from __future__ import annotations

import os

try:
    from npcpy.llm_funcs import get_llm_response
except ImportError:  # pragma: no cover - reported at call time, not import time
    get_llm_response = None

DEFAULTS = {
    "backend": os.environ.get("TINYTIM_BACKEND", "ollama"),
    "ollama_host": os.environ.get("OLLAMA_HOST") or "http://localhost:11434",
    "ollama_model": os.environ.get("TINYTIM_OLLAMA_MODEL")
    or "hf.co/npc-worldwide/tinytim-v2-1b-it:Q4_K_M",
    "hf_repo": os.environ.get("TINYTIM_HF_REPO") or "npc-worldwide/tinytim-v2-1b-it",
    "api_url": os.environ.get("TINYTIM_API_URL", ""),
    "api_key": os.environ.get("TINYTIM_API_KEY", ""),
    "timeout": float(os.environ.get("TINYTIM_TIMEOUT", "120")),
}

_PIPELINES = {}


class TinyTimError(RuntimeError):
    """Raised when TinyTim cannot be reached or returns nothing usable."""


def resolve_config(overrides=None):
    config = dict(DEFAULTS)
    for key, value in (overrides or {}).items():
        if value is None or value == "" or value == "null":
            continue
        config[key] = value
    config["backend"] = str(config["backend"]).strip().lower()
    host = str(config["ollama_host"]).strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    config["ollama_host"] = host
    config["timeout"] = float(config["timeout"])
    return config


def _require_npcpy():
    if get_llm_response is None:
        raise TinyTimError(
            "tinytim needs npcpy: pip install npcpy (or pip install -r requirements.txt)"
        )


def _compose_prompt(prompt, system_prompt):
    """Fold the system prompt into a single prompt string.

    npcpy takes a single `prompt` plus optional `messages`. Passing `messages`
    alongside a prompt stalls the ollama path, so the system text is prepended
    and one plain prompt is sent.
    """
    if system_prompt:
        return f"{system_prompt.strip()}\n\n{prompt.strip()}"
    return prompt


def _call_npcpy(prompt, system_prompt, provider, model, api_url, temperature,
                max_tokens, api_key=None):
    _require_npcpy()
    kwargs = {
        "prompt": _compose_prompt(prompt, system_prompt),
        "model": model,
        "provider": provider,
        "api_url": api_url,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if api_key:
        kwargs["api_key"] = api_key
    result = get_llm_response(**kwargs)
    if not isinstance(result, dict):
        return str(result).strip()
    text = result.get("response")
    if text is None:
        text = ""
    return str(text).strip()


def generate_ollama(prompt, system_prompt=None, temperature=0.9, max_tokens=512, config=None):
    """Local ollama via the ollama client.

    npcpy's ollama path drops num_predict: it forwards max_tokens inside
    options under the key "max_tokens", which ollama ignores, so generation
    runs until the model stops on its own. On a small box that turns one
    stream into minutes. The ollama client lets num_predict be set properly,
    so max_tokens is actually respected here.
    """
    config = config or resolve_config()
    try:
        import ollama
    except ImportError as exc:
        raise TinyTimError(
            "the ollama backend needs the ollama client: pip install ollama"
        ) from exc
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt.strip()})
    options = {
        "temperature": float(temperature),
        "num_predict": int(max_tokens),
    }
    try:
        client = ollama.Client(host=config["ollama_host"])
        res = client.chat(model=config["ollama_model"], messages=messages,
                          stream=False, options=options)
    except Exception as exc:
        raise TinyTimError(
            f"ollama call failed: {type(exc).__name__}: {exc}\n"
            f"Is ollama running? Pull the weights once with:\n"
            f"  ollama pull {config['ollama_model']}"
        ) from exc
    message = res.get("message") if hasattr(res, "get") else {}
    text = str((message or {}).get("content") or "").strip()
    if not text:
        raise TinyTimError("ollama returned an empty response")
    return text


def generate_hf(prompt, system_prompt=None, temperature=0.9, max_tokens=512, config=None):
    config = config or resolve_config()
    repo = config["hf_repo"]
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise TinyTimError(
            "the hf backend needs transformers: pip install transformers torch"
        ) from exc
    pipe = _PIPELINES.get(repo)
    if pipe is None:
        pipe = pipeline("text-generation", model=repo, device_map="auto")
        _PIPELINES[repo] = pipe
    flat = _compose_prompt(prompt, system_prompt)
    try:
        output = pipe(flat, max_new_tokens=int(max_tokens),
                      temperature=float(temperature), do_sample=True)
        generated = output[0]["generated_text"]
    except Exception as exc:
        raise TinyTimError(f"hf pipeline failed: {exc}") from exc
    if isinstance(generated, list):
        generated = generated[-1].get("content", "")
    text = str(generated).strip()
    if text.startswith(flat):
        text = text[len(flat):].strip()
    if not text:
        raise TinyTimError("hf pipeline returned an empty response")
    return text


def generate_api(prompt, system_prompt=None, temperature=0.9, max_tokens=512, config=None):
    config = config or resolve_config()
    url = str(config["api_url"]).strip().rstrip("/")
    if not url:
        raise TinyTimError("TINYTIM_API_URL is not set (the api backend is opt-in)")
    try:
        text = _call_npcpy(
            prompt, system_prompt,
            provider="openai",
            model=config.get("ollama_model") or config["hf_repo"],
            api_url=url,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=config.get("api_key") or None,
        )
    except TinyTimError:
        raise
    except Exception as exc:
        raise TinyTimError(f"npcpy api call failed: {type(exc).__name__}: {exc}") from exc
    if not text:
        raise TinyTimError("api returned an empty response")
    return text


GENERATORS = {"ollama": generate_ollama, "hf": generate_hf, "api": generate_api}


def generate(prompt, system_prompt=None, temperature=0.9, max_tokens=512, config=None):
    config = config or resolve_config()
    backend = config["backend"]
    if backend not in GENERATORS:
        raise TinyTimError(
            f"unknown tinytim backend {backend!r}; pick one of {sorted(GENERATORS)}"
        )
    return GENERATORS[backend](
        prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        config=config,
    )


def health(config=None):
    """Never raises. Reports whether this machine can actually run TinyTim."""
    config = config or resolve_config()
    backend = config["backend"]
    if backend == "ollama":
        wanted = config["ollama_model"]
        try:
            import ollama
            client = ollama.Client(host=config["ollama_host"])
            models = client.list().get("models", [])
            names = [m.get("model") or m.get("name") or "" for m in models]
            return {
                "backend": "ollama",
                "host": config["ollama_host"],
                "ok": True,
                "model": wanted,
                "model_present": wanted in names or wanted + ":latest" in names,
            }
        except Exception as exc:
            return {"backend": "ollama", "host": config["ollama_host"],
                    "ok": False, "model": wanted, "detail": str(exc)}
    if backend == "hf":
        try:
            import transformers  # noqa: F401
        except ImportError:
            return {"backend": "hf", "repo": config["hf_repo"], "ok": False,
                    "detail": "transformers not installed"}
        return {"backend": "hf", "repo": config["hf_repo"], "ok": True}
    return {"backend": "api", "url": config["api_url"], "ok": bool(config["api_url"])}
