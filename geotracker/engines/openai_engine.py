"""ChatGPT, via l'API OpenAI (endpoint Responses + outil de recherche web).

⚠️ À VALIDER AU PREMIER RUN RÉEL. Le parseur est défensif : si la forme de la
réponse a bougé, on stocke quand même le brut et on corrige `_parse` sans
perdre la mesure.
"""

from __future__ import annotations

import os
import time

import httpx

from ..config import ClientConfig, Engine
from ..models import EngineResponse, Source

ENDPOINT = "https://api.openai.com/v1/responses"
TIMEOUT = 120.0


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="openai",
        model=engine.model,
        search_enabled=engine.search,
    )
    started = time.perf_counter()

    try:
        body = {
            "model": engine.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        f"Tu réponds à un internaute situé en {config.country}, en français."
                    ),
                },
                {"role": "user", "content": prompt_text},
            ],
        }
        if engine.search:
            body["tools"] = [{"type": "web_search"}]

        response = httpx.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json=body,
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
    text_parts: list[str] = []
    pairs: list[tuple[str, str | None]] = []

    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("text"):
                text_parts.append(block["text"])
            for annotation in block.get("annotations") or []:
                if isinstance(annotation, dict) and annotation.get("url"):
                    pairs.append((annotation["url"], annotation.get("title")))

    # Repli si la forme a changé : certaines versions exposent output_text.
    if not text_parts and payload.get("output_text"):
        value = payload["output_text"]
        text_parts = value if isinstance(value, list) else [value]

    seen: set[str] = set()
    sources: list[Source] = []
    for url, title in pairs:
        if url not in seen:
            seen.add(url)
            sources.append(Source(rank=len(sources) + 1, url=url, title=title))

    return "".join(text_parts).strip(), sources
