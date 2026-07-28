"""Les trois seules choses qu'on extrait d'une réponse (TRACKER-GEO.md §3).

    1. la marque est-elle citée ?
    2. à quel rang ?
    3. quelles sources sont citées, donc qui prend la place ?

Le reste n'est que de la présentation. Cette étape est PURE : elle ne fait
aucun appel réseau, et elle est rejouable sur le brut déjà stocké.
"""

from __future__ import annotations

import re
import unicodedata

from .config import ClientConfig
from .models import EngineResponse, domain_matches


def _fold(text: str) -> str:
    """Minuscule + sans accents, pour comparer 'Réviser' et 'reviser'."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def find_brand_mention(answer_text: str, brand_terms: list[str]) -> int | None:
    """Position du premier caractère de la première mention de marque, sinon None."""
    folded = _fold(answer_text)
    positions = []
    for term in brand_terms:
        # \b ne marche pas avec un tiret ; on borne sur du non-alphanumérique.
        pattern = r"(?<![a-z0-9])" + re.escape(_fold(term)) + r"(?![a-z0-9])"
        match = re.search(pattern, folded)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def analyse(response: EngineResponse, config: ClientConfig) -> tuple[dict, list[dict]]:
    """Renvoie (métriques, sources enrichies)."""
    sources = []
    target_rank = None

    for source in response.sources:
        is_target = any(domain_matches(source.domain, d) for d in config.target_domains)
        if is_target and target_rank is None:
            target_rank = source.rank
        sources.append(
            {
                "rank": source.rank,
                "url": source.url,
                "domain": source.domain,
                "title": source.title,
                "is_target": is_target,
                "competitor": config.competitor_label(source.domain),
            }
        )

    mention_at = find_brand_mention(response.answer_text, config.brand_terms)
    text_length = len(response.answer_text or "")

    # Position normalisée de la marque dans le texte : 0.0 = tout en haut de la
    # réponse, 1.0 = tout en bas. C'est le "être en position dominante" de la
    # méthode La WAB, mesuré au lieu d'être constaté.
    text_position = (mention_at / text_length) if (mention_at is not None and text_length) else None

    metrics = {
        "cited": bool(target_rank) or mention_at is not None,
        "cited_in_text": mention_at is not None,
        "source_rank": target_rank,
        "text_position": round(text_position, 4) if text_position is not None else None,
        "n_sources": len(sources),
    }
    return metrics, sources
