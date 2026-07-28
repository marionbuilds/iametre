"""Claude, via l'API officielle Anthropic.

Deux modes selon `engine.search` :
  - True  : outil de recherche web activé = vraie mesure GEO
  - False : aucun outil = "mémoire de marque", le modèle répond de ses poids
"""

from __future__ import annotations

import time

import anthropic

from ..config import ClientConfig, Engine
from ..models import EngineResponse, Source

MAX_TOKENS = 8000
MAX_PAUSE_RESUMES = 3

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _system_prompt(config: ClientConfig, search: bool) -> str:
    base = (
        f"Tu réponds à un internaute situé en {config.country}, en français. "
        "Réponds comme tu le ferais dans une conversation normale."
    )
    if not search:
        return base
    # Sans cette consigne, le modèle répond parfois de mémoire alors que
    # l'outil de recherche est disponible. On mesurerait alors son humeur du
    # jour plutôt que la visibilité GEO, et la série deviendrait incomparable
    # d'une semaine sur l'autre. Le produit grand public pousse lui aussi à
    # chercher : cette consigne rapproche la mesure du comportement réel.
    return base + (
        " Fais TOUJOURS une recherche web avant de répondre, même si tu penses "
        "connaître la réponse, puis appuie-toi sur les sources trouvées."
    )


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="anthropic",
        model=engine.model,
        search_enabled=engine.search,
    )
    started = time.perf_counter()

    try:
        client = _get_client()
        params = {
            "model": engine.model,
            "max_tokens": MAX_TOKENS,
            "system": _system_prompt(config, engine.search),
            "messages": [{"role": "user", "content": prompt_text}],
        }
        # `effort` n'existe pas sur tous les modèles (Haiku 4.5 le refuse) :
        # on ne l'envoie que s'il est explicitement configuré.
        if engine.effort:
            params["output_config"] = {"effort": engine.effort}
        if engine.search:
            # max_uses borne le coût ET la variance : mesuré le 28/07, une même
            # question pouvait déclencher 1 ou 7 recherches selon l'humeur du
            # modèle, ce qui faisait varier le nombre de sources sans rapport
            # avec la visibilité réelle. 3 recherches suffisent largement pour
            # une question unique.
            params["tools"] = [
                {"type": engine.search_tool, "name": "web_search", "max_uses": 3}
            ]

        messages = list(params["messages"])
        raw_payloads = []
        response = None

        for _ in range(MAX_PAUSE_RESUMES + 1):
            response = client.messages.create(**{**params, "messages": messages})
            raw_payloads.append(response.model_dump())
            if response.stop_reason != "pause_turn":
                break
            # L'outil serveur a atteint sa limite d'itérations : on relance.
            messages = messages + [{"role": "assistant", "content": response.content}]

        result.raw = raw_payloads if len(raw_payloads) > 1 else raw_payloads[0]
        result.usage = response.usage.model_dump() if response.usage else None

        if response.stop_reason == "refusal":
            result.error = "refusal"

        result.answer_text, result.sources = _parse(raw_payloads)

    except Exception as exc:  # on ne laisse jamais un moteur casser le run
        result.error = f"{type(exc).__name__}: {exc}"

    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


def _parse(payloads: list[dict]) -> tuple[str, list[Source]]:
    """Sources = ce qui est CITÉ dans le texte en priorité, sinon ce qui a été
    récupéré par la recherche. On dédoublonne en gardant l'ordre d'apparition."""
    text_parts: list[str] = []
    cited_urls: list[tuple[str, str | None]] = []
    retrieved_urls: list[tuple[str, str | None]] = []

    for payload in payloads:
        for block in payload.get("content") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type == "text":
                text_parts.append(block.get("text") or "")
                for citation in block.get("citations") or []:
                    if isinstance(citation, dict) and citation.get("url"):
                        cited_urls.append((citation["url"], citation.get("title")))

            elif block_type == "web_search_tool_result":
                content = block.get("content")
                # En cas d'erreur outil, `content` est un objet, pas une liste.
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("url"):
                            retrieved_urls.append((item["url"], item.get("title")))

    chosen = cited_urls or retrieved_urls
    return "".join(text_parts).strip(), _dedupe(chosen)


def _dedupe(pairs: list[tuple[str, str | None]]) -> list[Source]:
    seen: set[str] = set()
    sources: list[Source] = []
    for url, title in pairs:
        if url in seen:
            continue
        seen.add(url)
        sources.append(Source(rank=len(sources) + 1, url=url, title=title))
    return sources
