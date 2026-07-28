"""Perplexity, via l'API sonar.

C'est le moteur qui sert de continuité avec la baseline manuelle du 05/06/2026
(MEMOIRE-SEO.md §3.2). Attention : l'API sonar n'est pas strictement identique
au Perplexity grand public utilisé ce jour-là. D'où le calibrage manuel mensuel.
"""

from __future__ import annotations

import os
import time

import httpx

from ..config import ClientConfig, Engine
from ..models import EngineResponse, Source

ENDPOINT = "https://api.perplexity.ai/chat/completions"
TIMEOUT = 120.0


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="perplexity",
        model=engine.model,
        search_enabled=True,  # Perplexity cherche toujours
    )
    started = time.perf_counter()

    try:
        response = httpx.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": engine.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Tu réponds à un internaute situé en {config.country}, "
                            "en français."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
            },
            timeout=TIMEOUT,
        )
        payload = response.json()
        result.raw = payload

        if response.status_code >= 400:
            result.error = f"HTTP {response.status_code}: {payload.get('error', payload)}"
            return result

        result.usage = payload.get("usage")
        result.answer_text, result.sources = _parse(payload)

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    return result


def _parse(payload: dict) -> tuple[str, list[Source]]:
    choices = payload.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        text = (choices[0].get("message") or {}).get("content") or ""

    pairs: list[tuple[str, str | None]] = []

    # Forme riche (titre + url)
    for item in payload.get("search_results") or []:
        if isinstance(item, dict) and item.get("url"):
            pairs.append((item["url"], item.get("title")))

    # Forme historique : simple liste d'URL
    if not pairs:
        for url in payload.get("citations") or []:
            if isinstance(url, str):
                pairs.append((url, None))

    seen: set[str] = set()
    sources: list[Source] = []
    for url, title in pairs:
        if url not in seen:
            seen.add(url)
            sources.append(Source(rank=len(sources) + 1, url=url, title=title))

    return text.strip(), sources
