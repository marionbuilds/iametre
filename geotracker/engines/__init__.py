"""Adaptateurs de moteurs.

Contrat : chaque `ask(prompt, engine, config)` renvoie un EngineResponse et ne
lève JAMAIS d'exception. Une panne réseau ou un parseur cassé remplit
`error` et laisse quand même `raw` : on ne perd pas la mesure.
"""

from __future__ import annotations

from ..config import ClientConfig, Engine
from ..models import EngineResponse


def get_engine(provider: str):
    if provider == "anthropic":
        from . import anthropic_engine

        return anthropic_engine.ask
    if provider == "openai":
        from . import openai_engine

        return openai_engine.ask
    if provider == "perplexity":
        from . import perplexity_engine

        return perplexity_engine.ask
    if provider in ("dataforseo", "ai_overview"):
        from . import dataforseo_engine

        return dataforseo_engine.ask
    raise ValueError(f"Fournisseur inconnu : {provider}")


def required_env(provider: str) -> list[str]:
    return {
        "anthropic": ["ANTHROPIC_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "perplexity": ["PERPLEXITY_API_KEY"],
        "dataforseo": ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"],
        "ai_overview": ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"],
    }.get(provider, [])


__all__ = ["get_engine", "required_env", "ClientConfig", "Engine", "EngineResponse"]
