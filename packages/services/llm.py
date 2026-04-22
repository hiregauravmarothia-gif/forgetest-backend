import hashlib
import json
import logging
import time
import httpx
from typing import Any
from apps.api.config import settings

logger = logging.getLogger(__name__)

# ── In-memory response cache ──────────────────────────────
# Key: SHA256(sorted messages JSON)  Value: response string
# Prevents re-scoring the same story content across runs.
_response_cache: dict[str, str] = {}


PROVIDERS = [
    {
        "name": "gpt-oss-120b",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-oss-120b:free",
        "api_key": lambda: settings.openrouter_api_key,
        "timeout": 60.0,
        "content_fallback": None,
        "extra_headers": {
            "HTTP-Referer": "https://forgetest.dev",
            "X-Title": "ForgeTest"
        }
    },
    {
        "name": "gpt-oss-20b",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-oss-20b:free",
        "api_key": lambda: settings.openrouter_api_key,
        "timeout": 60.0,
        "content_fallback": None,
        "extra_headers": {
            "HTTP-Referer": "https://forgetest.dev",
            "X-Title": "ForgeTest"
        }
    },
    {
        "name": "nemotron",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "api_key": lambda: settings.nvidia_api_key,
        "timeout": 120.0,
        "content_fallback": "reasoning",
        "extra_headers": {}
    },
    {
        "name": "gemini-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "api_key": lambda: settings.gemini_api_key,
        "timeout": 60.0,
        "content_fallback": None,
        "extra_headers": {}
    },
]


def _make_cache_key(messages: list[dict]) -> str:
    """SHA256 hash of the message content — provider-agnostic cache key."""
    canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class LLMService:
    def __init__(self):
        self.providers = PROVIDERS

    async def chat(self, messages: list[dict[str, Any]], use_cache: bool = True) -> str:
        # ── Cache check ───────────────────────────────────
        cache_key = _make_cache_key(messages)
        if use_cache and cache_key in _response_cache:
            logger.info(f"LLM cache hit: key={cache_key[:12]}...")
            return _response_cache[cache_key]

        last_error = None

        for provider in self.providers:
            provider_name = provider["name"]
            base_url = provider["base_url"]
            model = provider["model"]
            api_key = provider["api_key"]()
            timeout = provider["timeout"]
            content_fallback = provider.get("content_fallback")
            extra_headers = provider.get("extra_headers", {})

            if not api_key:
                logger.warning(f"Provider {provider_name}: no API key, skipping")
                continue

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **extra_headers
            }

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 8192,
                "temperature": 0,       # Lock to deterministic output
                "seed": 42,             # Supported by OpenRouter + NVIDIA; ignored gracefully by Gemini
            }

            start_time = time.perf_counter()

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=timeout
                    )

                    if response.status_code in (429, 503):
                        logger.warning(f"Provider {provider_name}: {response.status_code}, trying next...")
                        last_error = RuntimeError(f"{response.status_code} from {provider_name}")
                        continue

                    response.raise_for_status()
                    data = response.json()

                    content = data["choices"][0]["message"].get("content")

                    if not content and content_fallback:
                        content = data["choices"][0]["message"].get(content_fallback)

                    if not content:
                        raise RuntimeError(f"Empty response from {provider_name}")

                    duration_ms = (time.perf_counter() - start_time) * 1000
                    token_count = data.get("usage", {}).get("total_tokens")
                    logger.info(
                        f"LLM success: provider={provider_name}, model={model}, "
                        f"duration_ms={duration_ms:.2f}, tokens={token_count}"
                    )

                    # ── Cache the result ──────────────────
                    if use_cache:
                        _response_cache[cache_key] = content
                        logger.info(f"LLM cache stored: key={cache_key[:12]}..., cache_size={len(_response_cache)}")

                    return content

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.warning(
                    f"Provider {provider_name} failed: {str(e)[:100]}, "
                    f"duration_ms={duration_ms:.2f}, trying next..."
                )
                last_error = e
                continue

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    def clear_cache(self):
        """Clear the response cache — useful for testing or forced re-audit."""
        _response_cache.clear()
        logger.info("LLM response cache cleared")

    def cache_stats(self) -> dict:
        return {"size": len(_response_cache), "keys": [k[:12] for k in _response_cache]}


llm_service = LLMService()