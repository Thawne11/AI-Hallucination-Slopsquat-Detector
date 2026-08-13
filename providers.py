"""
Model-provider adapters for generating code samples.

Only local (free) providers via Ollama are wired up right now -- no paid
API billing exists yet for Claude/GPT/Gemini (see issue #4). Adding one
later is a small addition, not a rewrite: write a
`generate_<provider>(prompt, model) -> str` function and register it in
PROVIDERS.
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TIMEOUT = 120


def generate_ollama(prompt: str, model: str) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=OLLAMA_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["response"]


PROVIDERS = {
    "ollama": generate_ollama,
}


def generate(provider: str, prompt: str, model: str) -> str:
    return PROVIDERS[provider](prompt, model)
