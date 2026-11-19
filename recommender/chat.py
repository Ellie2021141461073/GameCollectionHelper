from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .store import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ChatConfig:
    api_key: str
    base_url: str
    model: str
    provider: str


def deepseek_configured() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


def get_deepseek_config() -> ChatConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Configure DEEPSEEK_API_KEY for recommendation enrichment and explanations"
        )
    return ChatConfig(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        provider="deepseek",
    )


def get_chat_config() -> ChatConfig:
    if deepseek_configured():
        return get_deepseek_config()

    # This key is intentionally scoped to the recommender. Never reuse the
    # card-page OPENAI_API_KEY, which may have exhausted quota or belong to
    # another feature.
    recommendation_key = os.getenv("RECOMMENDER_CHAT_API_KEY", "").strip()
    if recommendation_key:
        return ChatConfig(
            api_key=recommendation_key,
            base_url=os.getenv("RECOMMENDER_CHAT_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("RECOMMENDER_CHAT_MODEL", "gpt-4.1-mini"),
            provider="openai-compatible",
        )

    raise RuntimeError("Configure DEEPSEEK_API_KEY for recommendation chat completions")


def chat_configured() -> bool:
    return bool(
        deepseek_configured()
        or os.getenv("RECOMMENDER_CHAT_API_KEY", "").strip()
    )


def get_chat_client() -> OpenAI:
    config = get_chat_config()
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "3")),
    )


# The CS5481 gateway (LiteLLM) enforces about 50 requests per minute per team
# member and reports it in x-ratelimit-team_member-* headers. Bursting past that
# is not just slower: a 429 still consumes quota, so the retry storm starves the
# real work. Pacing client-side keeps every attempt useful.
#   0 = no throttling (use for an unrestricted provider).
RPM = int(os.getenv("DEEPSEEK_RPM", "0"))
_rpm_lock = threading.Lock()
_last_call_at = 0.0


def throttle() -> None:
    """Serialize request starts so the process stays under ``RPM`` per minute."""
    if RPM <= 0:
        return
    global _last_call_at
    interval = 60.0 / RPM
    with _rpm_lock:
        now = time.monotonic()
        wait = _last_call_at + interval - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _last_call_at = now


def create_json_completion(system_prompt: str, user_prompt: str) -> str:
    config = get_chat_config()
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "3")),
    )
    extra_body = {"thinking": {"type": "disabled"}} if config.provider == "deepseek" else None
    throttle()
    response = client.chat.completions.create(
        model=config.model,
        temperature=0.2,
        response_format={"type": "json_object"},
        extra_body=extra_body,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    record_usage(response)
    return response.choices[0].message.content or "{}"


# Process-wide token counter: enrichment and explanation calls both add to it, so
# a pipeline run can report what it actually cost instead of an estimate.
USAGE: dict[str, int] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def record_usage(response: Any) -> None:
    """Accumulate ``response.usage`` when the provider reports it."""
    USAGE["calls"] += 1
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    USAGE["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
    USAGE["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)


def reset_usage() -> None:
    for key in USAGE:
        USAGE[key] = 0


def usage_snapshot() -> dict[str, int]:
    return dict(USAGE)
