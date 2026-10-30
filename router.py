"""Single entry point for every model call in SHA-I.

Callers ask for a tier ("nano", "super", "vision"), never a model or provider.
Swap providers by setting ROUTER_PROVIDER (default "nebius"); the router then
reads <PROVIDER>_API_KEY and <PROVIDER>_BASE_URL, so any OpenAI-compatible
endpoint works. Swap models per tier with MODEL_NANO / MODEL_SUPER / MODEL_VISION.
"""
import base64
import json
import mimetypes
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

load_dotenv(Path(__file__).with_name(".env"))

TIERS = {"nano": "MODEL_NANO", "super": "MODEL_SUPER", "vision": "MODEL_VISION"}
RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


@lru_cache(maxsize=None)
def _client() -> OpenAI:
    provider = os.getenv("ROUTER_PROVIDER", "nebius").upper()
    key = os.getenv(f"{provider}_API_KEY")
    url = os.getenv(f"{provider}_BASE_URL")
    if not key or not url:
        raise RuntimeError(f"Set {provider}_API_KEY and {provider}_BASE_URL in .env")
    return OpenAI(api_key=key, base_url=url, timeout=120)


def model_for(tier: str) -> str:
    if tier not in TIERS:
        raise ValueError(f"Unknown tier {tier!r}; use one of {list(TIERS)}")
    model = os.getenv(TIERS[tier])
    if not model:
        raise RuntimeError(f"Set {TIERS[tier]} in .env")
    return model


def _strip_thinking(text: str) -> str:
    # Some reasoning models inline their thoughts; callers only want the answer.
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def chat(tier: str, messages: list[dict], retries: int = 3, **kwargs) -> str:
    """Send chat messages to the model for `tier` and return the reply text."""
    model = model_for(tier)
    for attempt in range(retries + 1):
        try:
            resp = _client().chat.completions.create(model=model, messages=messages, **kwargs)
            return _strip_thinking(resp.choices[0].message.content)
        except RETRYABLE:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)


def ask(prompt: str, tier: str = "nano", system: str | None = None, **kwargs) -> str:
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    return chat(tier, messages, **kwargs)


def ask_json(prompt: str, tier: str = "nano", system: str | None = None, **kwargs) -> dict:
    """Ask for a JSON object and parse it, tolerating code fences or extra prose."""
    text = ask(prompt, tier, system, **kwargs)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError(f"No JSON object in model reply: {text[:200]!r}")
    return json.loads(match.group(0))


def see(image_path: str | Path, prompt: str, **kwargs) -> str:
    """Describe or read an image with the vision tier."""
    path = Path(image_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
    ]}]
    return chat("vision", messages, **kwargs)
