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


def generate_anthropic(prompt: str, model: str) -> str:
    """One generation through the Anthropic API.

    Costs money per call. For corpus-scale work use corpus_batch.py instead,
    which goes through the Batch API at half the price -- this path exists
    for smoke tests and one-off checks.

    The client reads ANTHROPIC_API_KEY (or an `ant auth login` profile) on
    its own; nothing here handles the key.
    """
    import anthropic

    response = anthropic.Anthropic().messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    )


# Generous enough not to truncate a code sample mid-function, which would
# corrupt the extraction step and quietly bias the hallucination rate.
MAX_OUTPUT_TOKENS = 4096

PROVIDERS = {
    "ollama": generate_ollama,
    "anthropic": generate_anthropic,
}


def generate(provider: str, prompt: str, model: str) -> str:
    return PROVIDERS[provider](prompt, model)
