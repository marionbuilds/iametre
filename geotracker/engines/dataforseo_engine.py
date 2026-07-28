"""Google AI Overviews, via DataForSEO.

C'est le SEUL moteur du tracker qui mesure la VRAIE interface et non un modèle
derrière une API : DataForSEO lit la SERP Google telle qu'elle s'affiche. Zéro
écart interface/modèle sur celui-là.

⚠️ À VALIDER AU PREMIER RUN RÉEL (nom exact de l'endpoint et forme des
références). Le brut est stocké quoi qu'il arrive.
"""

from __future__ import annotations

import os
import time

import httpx

from ..config import ClientConfig, Engine
from ..models import EngineResponse, Source, normalize_domain

ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
TIMEOUT = 180.0


def ask(prompt_text: str, engine: Engine, config: ClientConfig) -> EngineResponse:
    result = EngineResponse(
        engine_id=engine.id,
        provider="dataforseo",
        model="google-ai-overview",
        search_enabled=True,
    )
    started = time.perf_counter()

    try:
        response = httpx.post(
            ENDPOINT,
            auth=(os.environ["DATAFORSEO_LOGIN"], os.environ["DATAFORSEO_PASSWORD"]),
            json=[
                {
                    "keyword": prompt_text,
                    "location_name": config.country,
                    "language_code": config.locale.split("-")[0],
                    "device": "desktop",
                    "os": "windows",
                    "depth": 20,
                    "load_html": False,
                    # Google charge souvent l'AI Overview APRÈS l'affichage de
                    # la page. Sans ce champ, DataForSEO ne renvoie qu'un
                    # emplacement vide (`asynchronous_ai_overview: true`, aucune
                    # source). Mesuré le 28/07 : 0 source extraite alors que
                    # l'AI Overview existait bel et bien.
                    "load_async_ai_overview": True,
                }
            ],
            timeout=TIMEOUT,
        )
        payload = response.json()
        result.raw = payload

        if response.status_code >= 400:
            result.error = f"HTTP {response.status_code}"
            return result

        # DataForSEO renvoie 200 avec un code d'erreur applicatif dans le corps.
        if payload.get("status_code") not in (20000, None):
            result.error = f"DataForSEO {payload.get('status_code')}: {payload.get('status_message')}"
            return result

        # ⚠️ Piège : la requête peut réussir (20000 à la racine) alors que la
        # TÂCHE a échoué (ex. 40101 Internal SE Server Error). Sans ce contrôle,
        # on enregistrerait « 0 source, aucune erreur », c'est-à-dire une fausse
        # mesure « Google ne cite personne » qui polluerait la série.
        for task in payload.get("tasks") or []:
            if task.get("status_code") not in (20000, None):
                result.error = (
                    f"tâche DataForSEO {task.get('status_code')}: {task.get('status_message')}"
                )
                return result

        result.usage = {"cost": payload.get("cost")}
        result.answer_text, result.sources, absent = _parse(payload)

        if absent and not result.error:
            # Pas d'AI Overview sur cette requête : ce n'est PAS une erreur,
            # c'est une mesure ("Google n'affiche pas d'AI Overview ici").
            result.answer_text = ""

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    return result


def _parse(payload: dict) -> tuple[str, list[Source], bool]:
    """Renvoie (texte de l'AI Overview, sources, aucun_ai_overview)."""
    items = []
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            items.extend(result.get("items") or [])

    overview = next(
        (i for i in items if isinstance(i, dict) and i.get("type") == "ai_overview"), None
    )
    if overview is None:
        return "", [], True

    text_parts: list[str] = []
    pairs: list[tuple[str, str | None]] = []

    def walk(node) -> None:
        """L'AI Overview est un arbre de blocs ; on ramasse texte et liens partout."""
        if isinstance(node, dict):
            for key in ("text", "snippet", "title"):
                value = node.get(key)
                if isinstance(value, str) and key in ("text", "snippet"):
                    text_parts.append(value)
            url = node.get("url") or node.get("source_url")
            if isinstance(url, str) and url.startswith("http"):
                pairs.append((url, node.get("title") or node.get("source")))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    # Les références explicites priment sur les liens croisés dans le texte.
    references = overview.get("references")
    if isinstance(references, list) and references:
        for reference in references:
            if isinstance(reference, dict):
                url = reference.get("url") or reference.get("source_url")
                if isinstance(url, str) and url.startswith("http"):
                    pairs.append((url, reference.get("title") or reference.get("source")))
        walk(overview.get("items"))
    else:
        walk(overview)

    seen: set[str] = set()
    sources: list[Source] = []
    for url, title in pairs:
        key = normalize_domain(url) + url
        if key not in seen:
            seen.add(key)
            sources.append(Source(rank=len(sources) + 1, url=url, title=title))

    return "\n".join(text_parts).strip(), sources, False
