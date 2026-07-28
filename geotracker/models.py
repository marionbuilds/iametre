"""Le contrat commun à tous les moteurs.

Chaque adaptateur de moteur renvoie un EngineResponse. Tout le reste du tracker
ne connaît que ce type : ajouter Mistral ou Grok en v2 ne touchera rien d'autre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


def normalize_domain(url_or_domain: str) -> str:
    """https://www.Smart-BPJEPS.com/livre?a=1  ->  smart-bpjeps.com"""
    value = (url_or_domain or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    netloc = urlparse(value).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def domain_matches(candidate: str, target: str) -> bool:
    """Vrai pour le domaine lui-même et ses sous-domaines."""
    candidate = normalize_domain(candidate)
    target = normalize_domain(target)
    if not candidate or not target:
        return False
    return candidate == target or candidate.endswith("." + target)


@dataclass
class Source:
    """Une source citée par le moteur, dans l'ordre où il la cite."""

    rank: int  # 1 = première source citée
    url: str
    title: str | None = None

    @property
    def domain(self) -> str:
        return normalize_domain(self.url)


@dataclass
class EngineResponse:
    engine_id: str
    provider: str
    model: str
    search_enabled: bool
    answer_text: str = ""
    sources: list[Source] = field(default_factory=list)
    raw: Any = None  # payload complet, stocké verbatim
    latency_ms: int = 0
    usage: dict | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
