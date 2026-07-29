"""ChatGPT, via l'API OpenAI.

Deux formes d'API, incompatibles entre elles, choisies par `engine.api` :

  `chat_completions`  modèles *-search-preview. La recherche est faite côté
                      serveur et n'est PAS facturée en tokens.
                      Mesuré le 28/07 : 48 tokens d'entrée par appel.

  `responses`         gpt-5 & co. L'outil de recherche renvoie les pages
                      lues dans le contexte facturé.
                      Mesuré le 28/07 : 29 034 tokens d'entrée par appel,
                      soit 600 fois plus, et la limite de débit explose.

Les deux sont maintenues : la première pour le coût, la seconde parce que les
modèles « preview » peuvent disparaître et qu'il faudra alors un repli.
"""

from __future__ import annotations

import os
import time

import httpx

from ..config import ClientConfig, Engine
from ..models import EngineResponse, Source

RESPONSES_URL = "https://api.openai.com/v1/responses"
CHAT_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT = 300.0
MAX_RETRIES = 5


def _system_prompt(config: ClientConfig, search: bool) -> str:
    base = f"Tu réponds à un internaute situé en {config.country}, en français."
    if not search:
        return base
    # Sans cette consigne, gpt-5 répond DE MÉMOIRE sans jamais chercher, même
    # avec l'outil disponible (mesuré : 0 recherche, 0 source). On mesurerait
    # son humeur du jour au lieu de la visibilité GEO.
    return base + (
        " Fais TOUJOURS une recherche web avant de répondre, même si tu penses "
        "connaître la réponse, puis appuie-toi sur les sources trouvées."
    )


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="openai",
        model=engine.model,
        search_enabled=engine.search,
    )
    started = time.perf_counter()

    try:
        system = _system_prompt(config, engine.search)
        if engine.api == "chat_completions":
            url, body, parse = CHAT_URL, _corps_chat(engine, system, prompt_text), _parse_chat
        else:
            url, body, parse = (
                RESPONSES_URL,
                _corps_responses(engine, system, prompt_text),
                _parse_responses,
            )

        response = _post_avec_reprise(url, body)
        payload = response.json()
        result.raw = payload

        if response.status_code >= 400:
            result.error = f"HTTP {response.status_code}: {payload.get('error', payload)}"
            return result

        result.usage = payload.get("usage")
        result.answer_text, result.sources = parse(payload)

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    return result


def _corps_chat(engine: Engine, system: str, prompt_text: str) -> dict:
    body = {
        "model": engine.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_text},
        ],
    }
    if engine.search:
        body["web_search_options"] = {"search_context_size": "low"}
    return body


def _corps_responses(engine: Engine, system: str, prompt_text: str) -> dict:
    body = {
        "model": engine.model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_text},
        ],
    }
    if engine.search:
        body["tools"] = [{"type": "web_search", "search_context_size": "low"}]
    return body


# ---------------------------------------------------------------- reprise 429

def _post_avec_reprise(url: str, body: dict) -> httpx.Response:
    """Un compte OpenAI neuf est plafonné à 10 000 tokens/minute. Avec l'API
    `responses` un seul appel en consomme 13 000 à 30 000 : les erreurs 429
    sont la NORME au début, pas une anomalie. On attend le délai indiqué et on
    recommence. Le plafond se relève tout seul avec l'ancienneté du compte."""
    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json",
    }
    response = None
    for tentative in range(MAX_RETRIES):
        response = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
        if response.status_code != 429 or tentative == MAX_RETRIES - 1:
            return response
        time.sleep(min(_delai_conseille(response) or (5 * 2**tentative), 120))
    return response


def _delai_conseille(response: httpx.Response) -> float | None:
    """OpenAI indique le délai à respecter, en en-tête ou dans le message."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        message = response.json()["error"]["message"]
        return float(message.split("try again in ")[1].split("s.")[0]) + 2
    except Exception:
        return None


# ---------------------------------------------------------------- extraction

def _dedupe(pairs: list[tuple[str, str | None]]) -> list[Source]:
    seen: set[str] = set()
    sources: list[Source] = []
    for url, title in pairs:
        if url and url not in seen:
            seen.add(url)
            sources.append(Source(rank=len(sources) + 1, url=url, title=title))
    return sources


def _parse_chat(payload: dict) -> tuple[str, list[Source]]:
    choices = payload.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    pairs = []
    for annotation in message.get("annotations") or []:
        citation = annotation.get("url_citation") or {}
        if citation.get("url"):
            pairs.append((citation["url"], citation.get("title")))
    return (message.get("content") or "").strip(), _dedupe(pairs)


def _parse_responses(payload: dict) -> tuple[str, list[Source]]:
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

    if not text_parts and payload.get("output_text"):
        value = payload["output_text"]
        text_parts = value if isinstance(value, list) else [value]

    return "".join(text_parts).strip(), _dedupe(pairs)
