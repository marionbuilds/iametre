"""Chargement et validation du jeu de suivi d'un client."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "config" / "clients"
PRODUIT_YAML = ROOT / "config" / "produit.yaml"


def load_produit() -> dict:
    """Identité du produit. Un seul endroit : renommer coûte une ligne."""
    defaut = {"nom": "Tracker GEO", "signature": ""}
    if not PRODUIT_YAML.exists():
        return defaut
    return {**defaut, **(yaml.safe_load(PRODUIT_YAML.read_text(encoding="utf-8")) or {})}


def clients_disponibles() -> list[str]:
    """Le schéma est multi-clients depuis le premier jour : un client s'ajoute
    par un fichier YAML, sans migration. L'interface le rend visible."""
    return sorted(p.stem for p in CLIENTS_DIR.glob("*.yaml"))


@dataclass
class Prompt:
    id: str
    text: str
    type: str = "inconnue"
    # "titulaire" : compte dans le taux global. "observation" : collectée et
    # affichée à part, mais EXCLUE des agrégats tant qu'elle n'est pas promue.
    # C'est ce qui permet de tester une requête sans plomber la série.
    statut: str = "titulaire"


@dataclass
class Engine:
    id: str
    provider: str
    model: str | None
    search: bool
    enabled: bool
    repetitions: int | None = None  # sinon on prend celui du sampling global
    # Tous les modèles n'acceptent pas le même outil de recherche ni les mêmes
    # paramètres. Mesuré le 28/07 : Haiku 4.5 refuse `web_search_20260209` et
    # ne connaît pas `effort`. On rend donc les deux explicites plutôt que
    # de deviner à partir du nom du modèle.
    search_tool: str = "web_search_20250305"
    effort: str | None = None


@dataclass
class ClientConfig:
    client: str
    label: str
    set_version: int
    locale: str
    country: str
    target_domains: list[str]
    brand_terms: list[str]
    competitors: list[dict]
    prompts: list[Prompt]
    engines: list[Engine]
    repetitions: int
    repetitions_ai_overview: int
    # LE concurrent direct à battre : alimente la vue « Duel » du dashboard.
    rival: str | None = None
    # Attributs de marque (chantier b, 06/08/2026) : ce que les modèles
    # associent à la marque. Liste de {id, label, termes}.
    attributs: list = field(default_factory=list)
    # Faits vérifiables du secteur (chantier c, 08/08/2026) : liste de
    # {id, label, requetes, juste, faux} — voir geotracker/faits.py.
    faits: list = field(default_factory=list)
    # Expérience contrôlée (chantier a) : bloc figé du YAML, tel quel.
    experience: dict | None = None
    # Garde-fou du carnet d'idées (06/08/2026) : l'import refuse d'ajouter
    # une requête en observation au-delà de ce plafond.
    plafond_observation: int = 5
    path: Path = field(default=None, repr=False)

    def competitor_label(self, domain: str) -> str | None:
        from .models import domain_matches

        for competitor in self.competitors:
            if domain_matches(domain, competitor["domain"]):
                return competitor.get("label") or competitor["domain"]
        return None

    def repetitions_for(self, engine: Engine) -> int:
        if engine.repetitions:
            return engine.repetitions
        if engine.provider == "dataforseo":
            return self.repetitions_ai_overview
        return self.repetitions


# Les fournisseurs que get_engine() (engines/__init__.py) sait construire.
# Dupliqué ICI et pas importé de là-bas : engines importe config, l'inverse
# créerait un cycle. Si un fournisseur s'ajoute, les DEUX listes bougent.
PROVIDERS_CONNUS = ("anthropic", "openai", "perplexity", "dataforseo", "ai_overview")


def _problemes(cfg: ClientConfig) -> list[str]:
    """Les incohérences d'une config VALIDE en YAML mais fausse en pratique.

    Passe 7 (décision Marion, 08/08/2026) : même logique que la config
    illisible — on ne génère pas une page fausse. Chaque cas de cette liste
    a été observé produire un résultat faux SILENCIEUX (rival égal à la
    cible : duel contre soi-même à 15 égalités) ou un piège durable (une
    faute de frappe dans les requêtes d'un fait survivait pour toujours en
    « aucune réponse exploitable »)."""
    from .models import domain_matches

    pb: list[str] = []
    if not cfg.target_domains:
        pb.append("aucun domaine cible (target.domains) : rien ne peut être mesuré")
    if cfg.rival:
        if any(domain_matches(cfg.rival, d) or domain_matches(d, cfg.rival)
               for d in cfg.target_domains):
            pb.append(f"le rival ({cfg.rival}) est le domaine cible : "
                      f"le duel se jouerait contre soi-même")
    ids = {p.id for p in cfg.prompts}
    for a in cfg.attributs:
        if not a.get("termes"):
            pb.append(f"attribut '{a.get('id', '?')}' au lexique vide : "
                      f"il resterait à 0 % pour toujours")
    for f in cfg.faits:
        inconnues = [q for q in f.get("requetes", []) if q not in ids]
        if inconnues:
            pb.append(f"fait '{f.get('id', '?')}' : requête(s) {', '.join(inconnues)} "
                      f"absente(s) du jeu — faute de frappe ?")
        if not f.get("requetes"):
            pb.append(f"fait '{f.get('id', '?')}' sans requêtes : jamais mesuré")
        if not f.get("juste"):
            pb.append(f"fait '{f.get('id', '?')}' sans termes `juste` : "
                      f"il ne pourrait jamais être vrai")
    for e in cfg.engines:
        if e.provider not in PROVIDERS_CONNUS:
            pb.append(f"moteur '{e.id}' : fournisseur inconnu '{e.provider}' "
                      f"(connus : {', '.join(PROVIDERS_CONNUS)})")
    return pb


def load_client(name: str) -> ClientConfig:
    path = CLIENTS_DIR / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(p.stem for p in CLIENTS_DIR.glob("*.yaml")) or "aucun"
        raise FileNotFoundError(f"Client '{name}' introuvable. Disponibles : {available}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sampling = raw.get("sampling", {})

    engines = []
    for item in raw.get("engines", []):
        engines.append(
            Engine(
                id=item["id"],
                # `provider` permet d'avoir deux entrées (avec / sans recherche)
                # qui tapent le même fournisseur.
                provider=item.get("provider", item["id"]),
                model=item.get("model"),
                search=bool(item.get("search", True)),
                enabled=bool(item.get("enabled", True)),
                repetitions=item.get("repetitions"),
                search_tool=item.get("search_tool", "web_search_20250305"),
                effort=item.get("effort"),
            )
        )

    prompts = [
        Prompt(id=p["id"], text=p["text"], type=p.get("type", "inconnue"),
               statut=p.get("statut", "titulaire"))
        for p in raw.get("prompts", [])
    ]

    ids = [p.id for p in prompts]
    if len(ids) != len(set(ids)):
        raise ValueError("Deux requêtes portent le même id : la série serait ambiguë.")

    cfg = ClientConfig(
        client=raw["client"],
        label=raw.get("label", raw["client"]),
        set_version=int(raw.get("set_version", 1)),
        locale=raw.get("locale", "fr-FR"),
        country=raw.get("country", "France"),
        target_domains=raw["target"]["domains"],
        brand_terms=raw["target"].get("brand_terms", []),
        competitors=raw.get("competitors", []),
        prompts=prompts,
        rival=raw.get("rival"),
        attributs=raw.get("attributs", []),
        faits=raw.get("faits", []),
        experience=raw.get("experience"),
        plafond_observation=int(raw.get("plafond_observation", 5)),
        engines=engines,
        repetitions=int(sampling.get("repetitions", 5)),
        repetitions_ai_overview=int(sampling.get("repetitions_ai_overview", 3)),
        path=path,
    )
    pb = _problemes(cfg)
    if pb:
        details = "\n".join(f"  - {p}" for p in pb)
        raise SystemExit(
            f"Configuration incohérente ({path.name}) :\n{details}\n"
            f"Rien n'est généré : un rapport produit depuis cette config serait faux."
        )
    return cfg
