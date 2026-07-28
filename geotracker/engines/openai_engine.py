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
TIMEOUT = 300.0
MAX_RETRIES = 5

# Un compte OpenAI neuf est plafonné à 10 000 tokens/minute, alors qu'un appel
# avec recherche en consomme 13 000 à 30 000. Les erreurs 429 sont donc la
# NORME au début, pas une anomalie : on attend le délai qu'OpenAI indique et on
# recommence. Le plafond se relève tout seul avec l'ancienneté du compte.
def _post_avec_reprise(body: dict, api_key: str) -> httpx.Response:
    for tentative in range(MAX_RETRIES):
        response = httpx.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=TIMEOUT,
        )
        if response.status_code != 429:
            return response
        attente = _delai_conseille(response) or (5 * 2**tentative)
        if tentative == MAX_RETRIES - 1:
            return response
        time.sleep(min(attente, 120))
    return response


def _delai_conseille(response: httpx.Response) -> float | None:
    """OpenAI indique le délai à respecter, soit en en-tête, soit dans le message."""
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


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="openai",
        model=engine.model,
        search_enabled=engine.search,
    )
    started = time.perf_counter()

    try:
        # Sans la consigne explicite, gpt-5 répond DE MÉMOIRE sans jamais
        # chercher, même avec l'outil disponible (mesuré le 28/07 : 0 recherche,
        # 0 source). On mesurerait alors son humeur du jour au lieu de la
        # visibilité GEO. Avec la consigne : 5 à 6 recherches, sources exploitables.
        system = f"Tu réponds à un internaute situé en {config.country}, en français."
        if engine.search:
            system += (
                " Fais TOUJOURS une recherche web avant de répondre, même si tu penses "
                "connaître la réponse, puis appuie-toi sur les sources trouvées."
            )
        body = {
            "model": engine.model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt_text},
            ],
        }
        if engine.search:
            # `search_context_size: low` réduit le volume de résultats avalés,
            # donc le coût ET la pression sur la limite de débit.
            body["tools"] = [{"type": "web_search", "search_context_size": "low"}]

        response = _post_avec_reprise(body, os.environ["OPENAI_API_KEY"])
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
