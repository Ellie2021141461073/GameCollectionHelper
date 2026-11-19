from __future__ import annotations

import os
from dataclasses import dataclass

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
    return OpenAI(api_key=config.api_key, base_url=config.base_url)


def create_json_completion(system_prompt: str, user_prompt: str) -> str:
    config = get_chat_config()
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    extra_body = {"thinking": {"type": "disabled"}} if config.provider == "deepseek" else None
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
    return response.choices[0].message.content or "{}"
