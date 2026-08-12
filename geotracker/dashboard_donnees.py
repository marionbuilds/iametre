"""Couche données de l'interface d'IAmètre.

Construit, pour une collecte donnée, le dictionnaire COMPLET de ce que la page
affiche : valeurs calculées, phrases d'interprétation, conditions résolues en
booléens (le contrat champ par champ est dans ARCHITECTURE.md §3). C'est la
SEULE couche autorisée à ouvrir SQLite et à lire les YAML. Elle ne produit
jamais de HTML et n'importe rien de la couche rendu : les deux ne partagent
que le module neutre `format`.

Déterminisme : cette couche ne lit jamais l'horloge. `date_du_jour` est un
paramètre ; à base et date égales, le dictionnaire est identique octet par
octet, ce qui rend l'export JSON et la comparaison de rendus reproductibles.

⚠️ RÈGLE ABSOLUE : aucun chiffre inventé.
Chaque valeur est calculée depuis la base, et tout indicateur sans données
est résolu en `affiche: False` ou en variante vide plutôt qu'inventé. Un
instrument de mesure qui affiche un faux chiffre ne vaut rien, et c'est
encore plus vrai le jour où on le montre en entretien.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from urllib.parse import urlparse

from . import db
from .config import load_client, load_produit
from .format import nb, points
from .report import collecte_comparable, couverture, run_summary, serie_commune, taux_commun

SEUIL_TROU = 25.0

# ------------------------------------------------------------ familles de panne
#
# Console (12/08/2026). Le message brut d'un fournisseur ne dit pas à Marion ce
# qu'elle doit faire : `HTTP 429: {'message': 'You have no credits remaining'}`
# et `tâche DataForSEO 40101` demandent l'un une carte bancaire, l'autre rien du
# tout. Cette table traduit le brut en VERDICT, et c'est le verdict qui décide
# si la panne remonte dans « Ce que tu dois faire ».
#
#   action  : quelque chose est cassé de son côté, elle seule peut le réparer
#   subir   : l'incident est chez le fournisseur, la collecte suivante repart
#   inconnu : jamais vu — on n'invente pas de conseil, on propose le diagnostic
#
# ⚠️ L'ORDRE COMPTE : le message de crédits épuisés d'OpenAI est SERVI EN 429,
# donc la famille « crédits » doit être testée avant la famille « cadence »,
# sinon une panne sèche s'affiche en « ça se dissipe tout seul » et le run
# suivant est amputé pareil. C'est exactement ce qui est arrivé au run #16.
FAMILLES_PANNE = (
    dict(cle="credits", titre="Crédits épuisés chez le fournisseur", verdict="action",
         motifs=("credit_balance_exhausted", "no credits remaining",
                 "insufficient_quota", "credit balance is too low", "billing"),
         quoi_faire="Recharger le compte, et poser une limite de dépense mensuelle "
                    "dans la foulée : le rechargement empêche la panne sèche, la "
                    "limite empêche l'emballement.",
         liens={"openai": "https://platform.openai.com/settings/organization/billing",
                "anthropic": "https://console.anthropic.com/settings/billing"}),
    dict(cle="cle", titre="Clé d'accès refusée", verdict="action",
         motifs=("HTTP 401", "HTTP 403", "invalid_api_key", "authentication",
                 "unauthorized"),
         quoi_faire="La clé est absente, expirée, ou n'a pas les droits. Elle se "
                    "corrige dans trousseau.env, section « PARTIE TRACKER GEO ».",
         liens={}),
    dict(cle="cadence", titre="Trop d'appels d'un coup", verdict="subir",
         motifs=("HTTP 429", "rate_limit", "rate limit"),
         quoi_faire="Limite de cadence du fournisseur. Elle se dissipe seule ; les "
                    "appels manquants sont simplement absents de cette collecte.",
         liens={}),
    dict(cle="fournisseur", titre="Panne chez le fournisseur", verdict="subir",
         motifs=("DataForSEO", "Internal SE Server Error", "HTTP 500", "HTTP 502",
                 "HTTP 503", "HTTP 504", "timeout", "Timeout", "connection"),
         quoi_faire="Incident de leur côté, rien à faire ici : la collecte suivante "
                    "repart normalement.",
         liens={}),
)

FAMILLE_INCONNUE = dict(
    cle="inconnu", titre="Panne non répertoriée", verdict="inconnu",
    quoi_faire="Ce message n'a jamais été rencontré : aucun conseil automatique ne "
               "serait fiable. Copie le diagnostic et fais-le analyser.",
    liens={})


def _famille(message: str) -> dict:
    """Traduit un message brut en famille. Insensible à la casse, sur le message
    ENTIER : les fournisseurs déplacent leurs codes d'un champ à l'autre."""
    m = (message or "").lower()
    for f in FAMILLES_PANNE:
        if any(motif.lower() in m for motif in f["motifs"]):
            return f
    return FAMILLE_INCONNUE

NOMS_MOTEURS = {
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "anthropic-memory": "Claude · mémoire de marque",
    "ai_overview": "Google AI Overviews",
}

# Version courte, pour les en-têtes de colonnes de la matrice moteur × requête.
NOMS_COURTS = {
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "anthropic-memory": "Claude mém.",
    "ai_overview": "Google AIO",
}


# ------------------------------------------------------------ lecture en base

def _exclusion(exclure, prefixe: str = "") -> tuple[str, tuple]:
    """Clause SQL « hors requêtes en observation », composable partout."""
    if not exclure:
        return "", ()
    ids = tuple(sorted(exclure))
    return f" AND {prefixe}prompt_id NOT IN ({','.join('?' * len(ids))})", ids


def _cout_appel(usage_json: str | None) -> float | None:
    """Le coût RÉEL d'un appel, quand le fournisseur le renvoie — jamais un
    coût reconstitué à partir des jetons.

    Deux fournisseurs sur quatre le donnent en dollars : DataForSEO sous
    `cost`, Perplexity sous `cost.total_cost`. Anthropic et OpenAI ne
    renvoient que des jetons ; les convertir supposerait une grille de prix
    écrite en dur ici, qui vieillirait en silence et finirait par afficher un
    montant faux avec l'aplomb d'un montant vrai (règle n°1 du dossier :
    aucun chiffre sans sa source). On préfère un trou signalé.
    """
    if not usage_json:
        return None
    try:
        u = json.loads(usage_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(u, dict):
        return None
    cout = u.get("cost")
    if isinstance(cout, (int, float)):
        return float(cout)
    if isinstance(cout, dict) and isinstance(cout.get("total_cost"), (int, float)):
        return float(cout["total_cost"])
    return None


def _couts_par_run(conn, client: str) -> dict[int, dict]:
    """Coût par collecte : ce qui est connu, et si c'est partiel.
    `partiel` vaut vrai dès qu'un seul appel de la collecte n'a pas rendu de
    coût — c'est ce drapeau qui empêche d'afficher un total pour un total."""
    par_run: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT run_id, usage_json FROM responses WHERE client=?", (client,)
    ).fetchall():
        etat = par_run.setdefault(r["run_id"], {"connu": 0.0, "n_connus": 0, "n": 0})
        etat["n"] += 1
        c = _cout_appel(r["usage_json"])
        if c is not None:
            etat["connu"] += c
            etat["n_connus"] += 1
    for etat in par_run.values():
        etat["partiel"] = etat["n_connus"] < etat["n"]
        if not etat["n_connus"]:
            etat["connu"] = None
    return par_run


def _duree_min(debut: str | None, fin: str | None) -> int | None:
    """Durée d'une collecte en minutes. `finished_at` est nul quand le run a
    été interrompu : dans ce cas on ne devine pas, on ne montre rien."""
    if not debut or not fin:
        return None
    try:
        d = datetime.fromisoformat(debut)
        f = datetime.fromisoformat(fin)
    except ValueError:
        return None
    return max(0, round((f - d).total_seconds() / 60))


def _collecte(conn, run_id: int) -> dict:
    """Les agrégats bruts d'une collecte, tels que la base les donne.
    Matière première interne : `donnees()` les transforme en dictionnaire
    d'affichage, rien d'autre ne doit les consommer."""
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        raise SystemExit(f"Collecte #{run_id} introuvable.")

    # La config d'abord : elle porte le statut des requêtes (titulaire ou en
    # observation) et le rival du duel. Une config illisible ARRÊTE la
    # génération : une page sans concurrents, sans rival et sans statuts
    # serait silencieusement FAUSSE, et en prestation c'est un rapport faux
    # envoyé à un client. On échoue bruyamment, on ne dégrade jamais.
    try:
        cfg = load_client(meta["client"])
    except FileNotFoundError:
        raise SystemExit(
            f"Client '{meta['client']}' sans fichier de configuration "
            f"(config/clients/{meta['client']}.yaml) : interface non générée."
        )
    except Exception as exc:
        raise SystemExit(
            f"Configuration '{meta['client']}' illisible ({type(exc).__name__}: {exc}) : "
            "interface non générée plutôt que fausse."
        )
    etiquette, set_version, n_conc = cfg.label, cfg.set_version, len(cfg.competitors)
    statuts = {p.id: p.statut for p in cfg.prompts}
    rival = cfg.rival
    rival_label = (cfg.competitor_label(rival) or rival) if rival else None
    exclure = frozenset(i for i, s in statuts.items() if s == "observation")
    n_titulaires = sum(1 for s in statuts.values() if s != "observation")
    cl_r, pr_r = _exclusion(exclure)          # sur `responses` sans alias
    cl_j, pr_j = _exclusion(exclure, "r.")    # sur les jointures (alias r)

    # Le PÉRIMÈTRE D'AFFICHAGE, c'est la config, pas la base (même principe que
    # la Passe 7 plus bas, qui compare la complétude aux moteurs activés).
    # Un moteur éteint garde ses réponses en base — on ne réécrit pas le brut —
    # mais il sort du tableau de bord ENTIÈREMENT : cartes, colonnes de la
    # matrice, ligne de santé et compteurs d'appels. Un filtre à moitié posé
    # donnerait une vue à quatre cartes annonçant les appels de cinq moteurs.
    # Éteint le 10/08/2026 : `anthropic-memory` (voir le YAML client).
    actifs = {e.id for e in cfg.engines if e.enabled}

    resume = run_summary(conn, run_id, exclure=exclure,
                         moteurs=actifs)                         # axe visibilité
    resume_total = run_summary(conn, run_id, exclure=exclure, avec_memoire=True,
                               moteurs=actifs)                   # totaux de collecte

    moteurs = sorted(
        (
            dict(
                id=r["engine_id"], recherche=bool(r["search_enabled"]),
                ok=r["ok"] or 0, cites=r["cited"] or 0,
                taux=(r["cited"] or 0) / r["ok"] * 100 if r["ok"] else 0,
                rang=r["avg_rank"],
            )
            for r in conn.execute(
                f"""SELECT engine_id, search_enabled,
                          SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
                          SUM(COALESCE(cited,0)) AS cited, AVG(source_rank) AS avg_rank
                   FROM responses WHERE run_id=?{cl_r} GROUP BY engine_id""",
                (run_id, *pr_r),
            ).fetchall()
            if r["engine_id"] in actifs
        ),
        key=lambda m: m["taux"], reverse=True,
    )

    # Santé de la collecte. Un moteur sans clé valide, ou en panne chez son
    # fournisseur, est sauté PROPREMENT : le job reste vert et le trou est
    # silencieux (voir 03-TRACKER-GEO/MEMORY.md, 31/07). Ici il se voit.
    sante = [
        dict(id=r["engine_id"], total=r["total"], ok=r["ok"] or 0,
             erreurs=(r["total"] - (r["ok"] or 0)), exemple=r["exemple"] or "")
        for r in conn.execute(
            f"""SELECT engine_id, COUNT(*) AS total,
                      SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
                      MAX(error) AS exemple
               FROM responses WHERE run_id=?{cl_r} GROUP BY engine_id""",
            (run_id, *pr_r),
        ).fetchall()
        if r["engine_id"] in actifs
    ]
    # Passe 7 (décision Marion, 08/08/2026) : la complétude se compare aux
    # moteurs ACTIVÉS dans la config, JAMAIS aux moteurs présents dans le
    # run. Sans ça, un run interrompu après un seul moteur affichait
    # « Collecte complète » avec une jauge à 100 % : le faux silencieux
    # le plus grave du banc d'essai.
    presents = {s["id"] for s in sante}
    for e in cfg.engines:
        if e.enabled and e.id not in presents:
            sante.append(dict(id=e.id, total=0, ok=0, erreurs=0,
                              exemple="", absent=True))

    # Matrice moteur × requête : le croisement que ni le taux par requête ni le
    # taux par moteur ne donnent. C'est là que se lisent les décisions du type
    # « Google me prend sur la méthode, jamais sur les chiffres ».
    matrice: dict[str, dict[str, dict]] = {}
    for r in conn.execute(
        f"""SELECT prompt_id AS pid, engine_id AS eid,
                  SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
                  SUM(COALESCE(cited,0)) AS cites
           FROM responses WHERE run_id=?{cl_r} GROUP BY prompt_id, engine_id""",
        (run_id, *pr_r),
    ).fetchall():
        matrice.setdefault(r["pid"], {})[r["eid"]] = dict(
            ok=r["ok"] or 0, cites=r["cites"] or 0,
            taux=(r["cites"] or 0) / r["ok"] * 100 if r["ok"] else None,
        )

    toutes = sorted(
        (
            dict(
                id=r["prompt_id"], texte=r["prompt_text"], type=r["prompt_type"] or "",
                statut=statuts.get(r["prompt_id"], "titulaire"),
                ok=r["ok"] or 0, cites=r["cited"] or 0,
                taux=(r["cited"] or 0) / r["ok"] * 100 if r["ok"] else 0,
            )
            for r in conn.execute(
                f"""SELECT prompt_id, prompt_text, MAX(prompt_type) AS prompt_type,
                          SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
                          SUM(COALESCE(cited,0)) AS cited
                   FROM responses WHERE run_id=? AND search_enabled=1
                   GROUP BY prompt_id""",
                (run_id,),
            ).fetchall()
        ),
        key=lambda q: q["taux"], reverse=True,
    )
    requetes = [q for q in toutes if q["statut"] != "observation"]
    # Le bloc « En observation » est revenu avec le carnet d'idées (06/08) :
    # les requêtes proposées y atterrissent, collectées mais hors agrégats.
    observation = [q for q in toutes if q["statut"] == "observation"]

    total = conn.execute(
        f"""SELECT COUNT(*) n FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''{cl_j}""",
        (run_id, *pr_j),
    ).fetchone()["n"] or 1
    distincts = conn.execute(
        f"""SELECT COUNT(DISTINCT s.domain) n FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''{cl_j}""",
        (run_id, *pr_j),
    ).fetchone()["n"]
    voix = [
        dict(domaine=r["domain"], label=r["label"], moi=bool(r["moi"]), n=r["n"],
             part=r["n"] / total * 100, rang=r["rang"])
        for r in conn.execute(
            f"""SELECT s.domain, MAX(s.is_target) AS moi, MAX(s.competitor) AS label,
                      COUNT(*) AS n, AVG(s.rank) AS rang
               FROM sources s JOIN responses r ON r.id=s.response_id
               WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''{cl_j}
               GROUP BY s.domain ORDER BY n DESC LIMIT 8""",
            (run_id, *pr_j),
        ).fetchall()
    ]

    # Qui occupe le terrain sur chaque requête : la matière première du brief.
    occupants: dict[str, list[str]] = {}
    for r in conn.execute(
        """SELECT r.prompt_id AS pid, s.domain AS dom, COUNT(*) n
           FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.is_target=0 AND s.domain IS NOT NULL AND s.domain <> ''
           GROUP BY r.prompt_id, s.domain ORDER BY n DESC""",
        (run_id,),
    ).fetchall():
        liste = occupants.setdefault(r["pid"], [])
        if len(liste) < 4:
            liste.append(r["dom"])

    # Dominance (méthode La WAB) : être cité ne suffit pas. Quand la marque
    # est citée, est-elle la source n°1 ? Est-elle nommée dans le texte ?
    dom = conn.execute(
        f"""SELECT SUM(COALESCE(cited,0)) c,
               SUM(CASE WHEN COALESCE(cited,0)=1 AND source_rank=1 THEN 1 ELSE 0 END) n1,
               SUM(COALESCE(cited_in_text,0)) t,
               SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) ok
           FROM responses WHERE run_id=? AND search_enabled=1{cl_r}""",
        (run_id, *pr_r),
    ).fetchone()
    dominance = dict(cites=dom["c"] or 0, n1=dom["n1"] or 0,
                     en_texte=dom["t"] or 0, ok=dom["ok"] or 0)
    dominance_requetes = sorted(
        (
            dict(id=r["prompt_id"], texte=r["texte"], cites=r["c"],
                 part=r["n1"] / r["c"] * 100 if r["c"] else 0)
            for r in conn.execute(
                f"""SELECT prompt_id, MAX(prompt_text) texte,
                       SUM(COALESCE(cited,0)) c,
                       SUM(CASE WHEN COALESCE(cited,0)=1 AND source_rank=1
                           THEN 1 ELSE 0 END) n1
                   FROM responses WHERE run_id=? AND {db.EXPLOITABLE}
                     AND search_enabled=1{cl_r}
                   GROUP BY prompt_id HAVING SUM(COALESCE(cited,0)) > 0""",
                (run_id, *pr_r),
            ).fetchall()
        ),
        key=lambda x: (x["part"], x["cites"]), reverse=True,
    )

    # Alignement au sujet : QUELLES pages du site les IA citent-elles ?
    # On garde le DÉTAIL requête par requête : « quelle intention de recherche
    # atterrit sur quelle URL » est ce qui dit si le maillage est cohérent, et
    # c'est le croisement qu'aucun total ne peut restituer.
    agg: dict[str, dict] = {}
    for r in conn.execute(
        f"""SELECT s.url u, r.prompt_id pid, r.prompt_text ptxt
           FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.is_target=1 AND s.url IS NOT NULL AND s.url <> ''{cl_j}""",
        (run_id, *pr_j),
    ).fetchall():
        chemin = urlparse(r["u"]).path.rstrip("/") or "/"
        e = agg.setdefault(chemin, {"n": 0, "reqs": {}})
        e["n"] += 1
        q = e["reqs"].setdefault(r["pid"], {"texte": r["ptxt"], "n": 0})
        q["n"] += 1
    pages = sorted(
        (
            dict(
                page=k, n=v["n"], requetes=len(v["reqs"]),
                detail=sorted(
                    (dict(id=i, texte=q["texte"], n=q["n"]) for i, q in v["reqs"].items()),
                    key=lambda x: x["n"], reverse=True,
                ),
            )
            for k, v in agg.items()
        ),
        key=lambda x: x["n"], reverse=True,
    )[:6]

    # Le duel : la marque contre SON rival direct, requête par requête.
    duel = []
    if rival:
        for r in conn.execute(
            f"""SELECT prompt_id pid, MAX(prompt_text) texte,
                   SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) ok,
                   SUM(COALESCE(cited,0)) moi,
                   SUM(CASE WHEN {db.EXPLOITABLE} AND EXISTS(
                         SELECT 1 FROM sources s WHERE s.response_id=responses.id
                           AND (s.domain=? OR s.domain LIKE '%.'||?)
                       ) THEN 1 ELSE 0 END) lui
               FROM responses WHERE run_id=? AND search_enabled=1{cl_r}
               GROUP BY prompt_id""",
            (rival, rival, run_id, *pr_r),
        ).fetchall():
            if r["ok"]:
                duel.append(dict(id=r["pid"], texte=r["texte"],
                                 moi=(r["moi"] or 0) / r["ok"] * 100,
                                 lui=(r["lui"] or 0) / r["ok"] * 100))
        # Les requêtes où le rival fait mieux d'abord : c'est là qu'on agit.
        duel.sort(key=lambda x: x["lui"] - x["moi"], reverse=True)

    # Comparaison et série : LA règle commune du produit vit dans report.py
    # (collecte_comparable / serie_commune). Le dashboard et le rapport texte
    # l'appellent tous les deux ; deux sorties, un seul cerveau.
    comp = collecte_comparable(conn, run_id, meta["client"], exclure)
    delta, delta_ctx = None, None
    if comp is not None:
        a = taux_commun(conn, run_id, comp["engines"], comp["prompts"])
        b = taux_commun(conn, comp["prev_id"], comp["engines"], comp["prompts"])
        if a["rate"] is not None and b["rate"] is not None:
            delta = a["rate"] - b["rate"]
            delta_ctx = {"prev_id": comp["prev_id"], "n_moteurs": len(comp["engines"]),
                         "reduit": comp["reduit"], "resume": a}

    # ⚠️ DEUX COMPTEURS, JAMAIS UN SEUL (console, 12/08/2026). Une PANNE (le
    # fournisseur renvoie une erreur) et une ABSENCE DE RÉPONSE (l'appel
    # aboutit, la réponse est vide — Google qui n'affiche pas d'AI Overview)
    # sortent toutes les deux du dénominateur, mais n'appellent PAS la même
    # action : la première se répare, la seconde est le comportement normal du
    # moteur. L'ancienne colonne « Erreurs » les additionnait, ce qui faisait
    # passer un non-événement pour un incident — 3 « échecs » affichés au run
    # #16 côté Google AIO, dont 1 qui n'en était pas un.
    # Restreint aux moteurs ACTIFS, comme tous les compteurs de la page : un
    # moteur éteint garde ses réponses en base mais sort du tableau de bord
    # entièrement (voir plus haut). Sans ce filtre, le journal afficherait des
    # pannes d'un moteur dont plus aucune carte ne parle.
    cl_a = f" AND engine_id IN ({','.join('?' * len(actifs))})" if actifs else ""
    pr_a = tuple(sorted(actifs))
    pannes: dict[int, list[dict]] = {}
    for r in conn.execute(
        f"""SELECT run_id, engine_id, error, COUNT(*) AS n
            FROM responses
            WHERE client=? AND error IS NOT NULL AND error <> ''{cl_a}
            GROUP BY run_id, engine_id, error""",
        (meta["client"], *pr_a),
    ).fetchall():
        pannes.setdefault(r["run_id"], []).append(
            dict(moteur=r["engine_id"], message=r["error"], n=r["n"]))
    sans_reponse: dict[int, int] = {
        r["run_id"]: r["n"]
        for r in conn.execute(
            f"""SELECT run_id, COUNT(*) AS n FROM responses
                WHERE client=? AND (error IS NULL OR error='')
                  AND (answer_text IS NULL OR answer_text=''){cl_a}
                GROUP BY run_id""",
            (meta["client"], *pr_a),
        ).fetchall()
    }
    couts = _couts_par_run(conn, meta["client"])

    historique = []
    for r in conn.execute(
        "SELECT id, started_at, finished_at, note FROM runs WHERE client=? "
        "ORDER BY id DESC LIMIT 25",
        (meta["client"],),
    ).fetchall():
        s_vis = run_summary(conn, r["id"], exclure=exclure, moteurs=actifs)
        s_tot = run_summary(conn, r["id"], exclure=exclure, avec_memoire=True,
                            moteurs=actifs)
        # Un run à ZÉRO réponse (interrompu avant le premier appel) s'affiche
        # aussi : sa ligne datée compte pour le garde-fou --sauf-si-recente et
        # peut bloquer une relance le jour même — l'écarter du registre, c'est
        # cacher à la fois l'interruption à rattraper et la cause du blocage
        # (états vides, 06/08 ; mécanique tracée au journal le 31/07).
        n_pannes = sum(p["n"] for p in pannes.get(r["id"], ()))
        historique.append(dict(
            id=r["id"], date=r["started_at"][:16].replace("T", " à "),
            note=r["note"] or "", n=s_tot["n"],
            erreurs=s_tot["errors"],       # total, gardé pour le rapport texte
            pannes=n_pannes, sans_reponse=sans_reponse.get(r["id"], 0),
            taux=s_vis["rate"], detail=pannes.get(r["id"], []),
            duree_min=_duree_min(r["started_at"], r["finished_at"]),
            cout=couts.get(r["id"], {}).get("connu"),
            cout_partiel=couts.get(r["id"], {}).get("partiel", True),
            # « Hors série » se DÉDUIT, il ne se devine pas : une collecte qui
            # a lancé moins d'appels qu'il n'y a de requêtes n'a pas pu couvrir
            # le jeu de suivi. Essai de mise au point ou interruption, on ne
            # tranche pas — mais dans les deux cas la ligne n'est pas
            # comparable aux autres, et la mettre au même rang rendait le
            # tableau illisible (5 lignes de juillet sur 16).
            hors_serie=s_tot["n"] < n_titulaires,
        ))

    points, serie_ctx = serie_commune(conn, meta["client"], exclure, reference=run_id)
    serie = [dict(date=p["date"], taux=p["taux"]) for p in points]

    return {
        "run_id": run_id, "client": meta["client"], "client_label": etiquette,
        "set_version": set_version, "n_concurrents": n_conc,
        "date": meta["started_at"][:10], "resume": resume,
        "resume_total": resume_total, "moteurs": moteurs,
        "sante": sante, "matrice": matrice,
        "requetes": requetes, "voix": voix,
        "occupants": occupants, "total_citations": total, "domaines_distincts": distincts,
        "dominance": dominance, "dominance_requetes": dominance_requetes,
        "pages": pages, "duel": duel, "rival": rival, "rival_label": rival_label,
        "n_titulaires": n_titulaires,
        # Le périmètre de la machine se lit dans la CONFIG, pas dans le run :
        # un moteur éteint doit pouvoir se dire éteint, et il n'a par
        # définition aucune réponse dans la collecte du jour.
        "engines_config": [dict(id=e.id, actif=e.enabled, recherche=e.search,
                                modele=e.model or "", fournisseur=e.provider)
                           for e in cfg.engines],
        "run_debut": meta["started_at"], "run_fin": meta["finished_at"],
        "historique": historique, "serie": serie, "delta": delta,
        "delta_ctx": delta_ctx, "serie_ctx": serie_ctx,
        "observation": observation,
        "plafond_observation": cfg.plafond_observation,
        # La CONFIG fait foi pour la liste des requêtes suivies : une requête
        # importée entre deux collectes n'a encore aucune réponse en base,
        # elle doit pourtant exister pour le contrôle de doublon et le bloc
        # observation (« en attente de première collecte »).
        "prompts_config": [{"id": q.id, "texte": q.text, "statut": q.statut}
                           for q in cfg.prompts],
        "produit": load_produit(),
    }


# -------------------------------------------------------------------- calculs

def _impact(q: dict, requetes: list[dict], resume: dict) -> float:
    """Combien de points de taux global gagnerait-on si cette requête passait
    au niveau de celles qui fonctionnent déjà ?

    Calcul vérifiable : la cible est la MÉDIANE des requêtes au-dessus du
    seuil (un niveau déjà atteint ailleurs, pas un idéal à 100 %), et on
    mesure ce que ça déplace sur l'ensemble des appels réussis.
    """
    bonnes = sorted(x["taux"] for x in requetes if x["taux"] >= SEUIL_TROU)
    if not bonnes or not resume["ok"]:
        return 0.0
    cible = bonnes[len(bonnes) // 2]
    gagnees = max(0.0, (cible - q["taux"]) / 100 * q["ok"])
    return gagnees / resume["ok"] * 100


def _marge(r: dict) -> float:
    """Marge de fluctuation à 95 % du taux de citation, en points.

    Une réponse d'IA est non déterministe : le taux mesuré est un sondage,
    pas un recensement. Sur n appels avec une proportion p, l'écart type
    d'échantillonnage vaut sqrt(p(1-p)/n) ; à effort strictement constant,
    la mesure suivante a 95 % de chances de tomber dans ±1,96 écart type.
    C'est LA réponse au « pourquoi j'ai perdu 3 points sans rien changer ? » :
    parce que 3 points, ici, c'est du bruit. L'interface ne doit jamais
    présenter comme un événement une variation qui tient dans cette marge.
    """
    if not r["ok"] or r["rate"] is None:
        return 0.0
    prop = r["rate"] / 100
    return 1.96 * math.sqrt(prop * (1 - prop) / r["ok"]) * 100


def _promesse(imp: float) -> str:
    """Formule une promesse d'impact en borne basse (principe Apple, décidé
    par Marion le 29/07/2026) : on arrondit l'estimation VERS LE BAS et on
    dit « au moins ». Si le réel dépasse, c'est du bonus perçu ; s'il colle,
    la promesse est tenue. Ne s'applique qu'aux promesses : les mesures
    (taux, parts de voix), elles, restent exactes au dixième."""
    if imp >= 1:
        return f"au moins +{int(imp)} pts"
    return f"+{nb(imp)} pts"


def _objectif(taux: float) -> tuple[int, float]:
    palier = min(100, (int(taux // 10) + 1) * 10)
    # À moins d'un demi-point du palier, l'affichage arrondi dirait
    # « Palier 60 % · +0 pts restants » : on vise directement le suivant
    # (validé par Marion le 06/08/2026).
    if palier - taux < 0.5 and palier < 100:
        palier = min(100, palier + 10)
    return palier, palier - taux


def _lecture_moteur(m: dict, tous: list[dict]) -> str:
    """Le chiffre seul ne dit rien : on écrit ce qu'il faut en comprendre."""
    if not m["recherche"]:
        return ("Le modèle ne connaît pas encore la marque sans aller chercher."
                if m["taux"] < 5 else "Le modèle commence à connaître la marque de mémoire.")
    avec = [x for x in tous if x["recherche"]]
    if not avec:
        return ""
    meilleur, pire = max(x["taux"] for x in avec), min(x["taux"] for x in avec)
    rangs = [x["rang"] for x in avec if x["rang"]]
    if m["taux"] >= meilleur:
        base = ("Le moteur le plus favorable, et de loin" if meilleur - pire > 20
                else "Le moteur le plus favorable")
        # Citée souvent mais bas : le dire, sinon la carte se lit comme une
        # bonne nouvelle sans réserve (méthode La WAB, cf. CLAUDE.md §4).
        if m["rang"] and len(rangs) > 1 and m["rang"] >= max(rangs):
            return f"{base}, mais c'est là que la marque est citée le plus bas."
        return f"{base}."
    if m["rang"] and rangs and m["rang"] <= min(rangs):
        return "Le plus dur à percer, mais la meilleure place quand elle apparaît."
    if m["taux"] <= pire:
        return "Le plus difficile à percer."
    return f"Bien placée quand elle apparaît : rang moyen {nb(m['rang'])}." if m["rang"] else ""


def _diagnostic(q: dict) -> str:
    """Un pourcentage ne fait rien ressentir. « 1 réponse sur 14 », si."""
    if q["taux"] < 1:
        return "Aucun domaine ne s'impose : personne n'est cité parce qu'il n'y a rien à citer."
    sur = max(2, round(q["ok"] / max(q["cites"], 1)))
    if q["taux"] < 10:
        return f"La question est posée, mais la marque n'apparaît que dans 1 réponse sur {sur}."
    return f"Sujet au cœur de l'offre, et la marque n'apparaît que dans 1 réponse sur {sur}."


def _prochaine_collecte(date_du_jour) -> str:
    """Le cron tourne le lundi à 06h00 UTC (.github/workflows/weekly.yml).
    La date vient du PARAMÈTRE, jamais de l'horloge : c'est ce qui rend la
    couche déterministe (ARCHITECTURE.md §2 bis)."""
    jours = (7 - date_du_jour.weekday()) % 7 or 7
    return ("Prochaine collecte demain, lundi." if jours == 1
            else f"Prochaine collecte dans {jours} jours, lundi.")


def _console(d: dict, prochaine: str) -> dict:
    """La vue « Console » : l'ancien registre des collectes retourné.

    Il se lisait dans l'ordre de la machine (un tableau de 16 lignes, une
    colonne « Erreurs », aucune action). Il se lit maintenant dans l'ordre de
    Marion : ce qu'elle doit faire, l'état de la machine, le journal en
    dernier. Restructuré le 12/08/2026 sur son constat : « la page collecte,
    je la comprends pas, elle me sert à rien, je ne sais pas quelle action je
    dois faire ».

    Aucune décision n'est prise ici sur ce qui n'est pas mesuré : les actions
    sortent des pannes RÉELLEMENT en base, jamais d'une prévision de budget
    écrite dans un fichier.
    """
    hist = d["historique"]
    courant = next((h for h in hist if h["id"] == d["run_id"]), None)

    # --- Bloc 1 : ce qu'il y a à faire, déduit des pannes de la collecte lue.
    # Une famille par carte, pas un appel par carte : 14 fois le même message
    # de crédits épuisés, c'est UNE action, pas quatorze.
    par_famille: dict[str, dict] = {}
    for p in (courant["detail"] if courant else []):
        f = _famille(p["message"])
        cle = (f["cle"], p["moteur"])
        e = par_famille.setdefault(cle, {
            "cle": f["cle"], "titre": f["titre"], "verdict": f["verdict"],
            "quoi_faire": f["quoi_faire"], "moteur": p["moteur"],
            "moteur_nom": NOMS_COURTS.get(p["moteur"], p["moteur"]),
            "lien": f["liens"].get(p["moteur"]) or f["liens"].get(
                p["moteur"].split("-")[0], ""),
            "n": 0, "messages": [],
        })
        e["n"] += p["n"]
        e["messages"].append(p["message"])

    # La récurrence se calcule sur TOUT l'historique : une panne vue trois
    # lundis d'affilée n'est pas le même objet qu'une panne vue une fois, et
    # c'est la seule chose qui distingue un incident d'un état de fait.
    for e in par_famille.values():
        e["recurrence"] = sum(
            1 for h in hist
            if any(_famille(x["message"])["cle"] == e["cle"]
                   and x["moteur"] == e["moteur"] for x in h["detail"])
        )

    actions = [e for e in par_famille.values() if e["verdict"] in ("action", "inconnu")]
    actions.sort(key=lambda e: (e["verdict"] != "action", -e["n"]))
    subies = [e for e in par_famille.values() if e["verdict"] == "subir"]

    # Une collecte interrompue est une action, et elle ne laisse aucune panne
    # derrière elle : le moteur n'a simplement jamais été appelé. Sans cette
    # entrée, le cas le plus grave du banc d'essai serait le seul à ne rien
    # afficher dans « Ce que tu dois faire ».
    absents = [s for s in d["sante"] if s.get("absent")]
    if absents:
        noms = ", ".join(NOMS_COURTS.get(s["id"], s["id"]) for s in absents)
        actions.insert(0, {
            "cle": "interrompue", "titre": "Collecte interrompue", "verdict": "action",
            "moteur": "", "moteur_nom": noms, "n": 0, "recurrence": 1, "messages": [],
            "quoi_faire": f"{noms} n'a jamais été interrogé : la collecte s'est "
                          f"arrêtée avant la fin. À relancer depuis le Mac, sans "
                          f"garde-fou de fraîcheur : "
                          f"python -m geotracker.run --client {d['client']}",
            "lien": "",
        })

    # --- Bloc 2 : l'état de la machine, lu dans la config et dans le run.
    moteurs_on = [e for e in d["engines_config"] if e["actif"]]
    moteurs_off = [e for e in d["engines_config"] if not e["actif"]]
    tot = d["resume_total"]
    etat = {
        "prochaine": prochaine,
        "n_moteurs_actifs": len(moteurs_on),
        "moteurs_actifs": [NOMS_COURTS.get(e["id"], e["id"]) for e in moteurs_on],
        "moteurs_eteints": [NOMS_COURTS.get(e["id"], e["id"]) for e in moteurs_off],
        "n_requetes": d["n_titulaires"],
        "set_version": d["set_version"],
        "run_id": d["run_id"],
        "run_date": d["date"],
        "duree_min": courant["duree_min"] if courant else None,
        "appels": tot["n"],
        "exploitables": tot["ok"],
        "cout": courant["cout"] if courant else None,
        "cout_partiel": courant["cout_partiel"] if courant else True,
        # Nommer les fournisseurs muets, plutôt qu'un astérisque : sans ça le
        # montant se lirait comme un total alors qu'il en couvre la moitié.
        "cout_muets": sorted({
            NOMS_COURTS.get(e["id"], e["id"]) for e in moteurs_on
            if e["fournisseur"] in ("openai", "anthropic")
        }),
    }

    return {
        "actions": actions,
        "subies": subies,
        "etat": etat,
        "journal": {
            "n": len(hist),
            "lignes": [{"id": h["id"], "date": h["date"], "n": h["n"],
                        "pannes": h["pannes"], "sans_reponse": h["sans_reponse"],
                        "taux": h["taux"], "note": h["note"],
                        "hors_serie": h["hors_serie"], "cout": h["cout"],
                        "detail": [{"moteur": NOMS_COURTS.get(x["moteur"], x["moteur"]),
                                    "n": x["n"], "message": x["message"],
                                    "famille": _famille(x["message"])["titre"]}
                                   for x in h["detail"]]}
                       for h in hist],
            "n_hors_serie": sum(1 for h in hist if h["hors_serie"]),
        },
        "diagnostic": _diagnostic_machine(d, etat, actions, subies, hist),
    }


def _diagnostic_machine(d: dict, etat: dict, actions: list, subies: list,
                        hist: list) -> str:
    """Le texte que copie le bouton « Copier le diagnostic ».

    Sa raison d'être (Marion, 12/08/2026) : « si vraiment il y a un problème
    que je ne comprends pas, je peux copier-coller un prompt et te le donner
    pour l'arranger ». Il porte donc les MESSAGES BRUTS des fournisseurs, pas
    leur traduction : c'est le brut qui permet de diagnostiquer, la
    traduction n'est qu'une aide à la lecture.
    """
    L = [f"DIAGNOSTIC IAMÈTRE — {d['client_label']}",
         f"Collecte lue : #{etat['run_id']} du {etat['run_date']}",
         "",
         "MACHINE",
         f"  {etat['prochaine']}",
         f"  Moteurs actifs : {len(etat['moteurs_actifs'])} "
         f"({', '.join(etat['moteurs_actifs']) or 'aucun'})"]
    if etat["moteurs_eteints"]:
        L.append(f"  Moteurs éteints : {', '.join(etat['moteurs_eteints'])}")
    L += [f"  Jeu de suivi : {etat['n_requetes']} requêtes, version {etat['set_version']}",
          "",
          "DERNIÈRE COLLECTE",
          f"  {etat['appels']} appels, {etat['exploitables']} exploitables"
          + (f", {etat['duree_min']} min" if etat["duree_min"] is not None else "")]
    if etat["cout"] is not None:
        L.append(f"  Coût rapporté par les fournisseurs : {etat['cout']:.2f} $"
                 + (f" (hors {', '.join(etat['cout_muets'])}, qui ne le renvoient pas)"
                    if etat["cout_partiel"] and etat["cout_muets"] else ""))

    if actions or subies:
        L += ["", "PANNES, MESSAGE BRUT DU FOURNISSEUR"]
        for e in actions + subies:
            if not e["messages"]:
                L.append(f"  [{e['moteur_nom']}] {e['titre']} — {e['quoi_faire']}")
                continue
            L.append(f"  [{e['moteur_nom']}] ×{e['n']} — {e['titre']} "
                     f"(verdict : {e['verdict']}, vu sur {e['recurrence']} collecte(s))")
            L += [f"    {m}" for m in e["messages"]]
    else:
        L += ["", "PANNES : aucune."]

    L += ["", "HISTORIQUE (25 dernières collectes)"]
    for h in hist:
        marque = " [hors série]" if h["hors_serie"] else ""
        t = f"{h['taux']:.0f} %" if h["taux"] is not None else "—"
        L.append(f"  #{h['id']} {h['date']} · {h['n']} appels · "
                 f"{h['pannes']} panne(s) · {h['sans_reponse']} sans réponse · "
                 f"{t}{marque}")
    return "\n".join(L)


def _brief(q: dict, d: dict) -> str:
    """Le bouton copie un VRAI brief de contenu, pas un texte décoratif :
    la question, l'état mesuré, qui occupe le terrain, l'impact attendu.
    (Supprimée à tort lors de la fusion de la Passe 1, restaurée sur ordre
    de Marion : une fusion ne supprime pas de fonctionnalité.)"""
    occ = d["occupants"].get(q["id"], [])
    lignes = [
        f"BRIEF DE CONTENU — {d['client_label']}",
        "",
        f"Question à couvrir : {q['texte']}",
        f"Mesuré le {d['date']} : citée dans {q['cites']} réponse(s) sur {q['ok']} testées "
        f"({q['taux']:.0f} %).",
        f"Diagnostic : {_diagnostic(q)}",
    ]
    if occ:
        lignes += ["", "Domaines actuellement cités sur cette question :"] + [f"  - {o}" for o in occ]
    else:
        lignes += ["", "Aucun domaine ne s'impose : terrain libre."]
    lignes += [
        "",
        f"Impact estimé si ce sujet atteint le niveau des sujets qui fonctionnent : "
        f"{_promesse(_impact(q, d['requetes'], d['resume']))} de taux de citation global "
        f"(borne basse volontaire).",
    ]
    return "\n".join(lignes)


def _prompt_ia(q: dict, d: dict) -> str:
    """Prompt prêt à coller dans ChatGPT / Claude / Perplexity. Demande de
    Marion (29/07/2026) : « il faut vraiment être dans un outil d'action, de
    décision, de mouvement ». Le bouton ne copie pas un constat, il copie un
    prompt qui embarque les données mesurées ET les principes SEO/GEO, et
    demande la STRUCTURE de l'article, pas sa rédaction : l'expertise du
    contenu reste chez l'utilisateur."""
    occ = d["occupants"].get(q["id"], [])
    terrain = ("Domaines cités à sa place aujourd'hui : " + ", ".join(occ) + "."
               if occ else "Aucun domaine ne s'impose sur cette question : terrain libre.")
    taux = f"{q['taux']:.0f}"
    return f"""Tu es un rédacteur web senior, spécialiste du SEO et du GEO (la visibilité dans les réponses des IA).

MISSION
Construis la structure complète d'un article qui doit devenir LA source que les moteurs IA citent pour la question : « {q['texte']} »

CONTEXTE MESURÉ ({d['produit']['nom']}, le {d['date']})
- Marque à faire citer : {d['client_label']}.
- Sur cette question, la marque n'apparaît que dans {q['cites']} réponse(s) d'IA sur {q['ok']} testées ({taux} %).
- {terrain}
- Impact estimé d'un bon contenu : {_promesse(_impact(q, d['requetes'], d['resume']))} de visibilité IA globale.

CE QUE TU DOIS PRODUIRE (la structure seulement, pas la rédaction)
1. Le title SEO et le H1 : la question, formulée comme un humain la pose.
2. Une réponse directe de 2 à 3 phrases à placer juste sous le H1, autonome et citable telle quelle par une IA.
3. Le plan H2/H3 complet, avec pour chaque section une ligne sur l'intention à couvrir.
4. Une FAQ de 4 à 6 questions voisines, avec l'angle de réponse en une ligne.
5. La liste des chiffres, dates et définitions que l'article devra sourcer.

PRINCIPES SEO À RESPECTER
- Une page = une intention : ne pas mélanger cette question avec un autre sujet.
- La question exacte dans le title, le H1 et le premier paragraphe.
- Hiérarchie Hn stricte, paragraphes courts, listes dès que c'est scannable.
- Prévoir 2 à 3 liens internes vers des pages sœurs du site.

PRINCIPES GEO À RESPECTER
- Chaque section doit être auto-suffisante : une IA cite un passage, jamais une page entière.
- Les passages les plus repris par les IA sont les définitions, les chiffres datés et les réponses directes : en placer dans chaque section.
- Reprendre les formulations naturelles des utilisateurs, pas le jargon du métier.
- Terminer par la FAQ : c'est la partie la plus citée par les moteurs de réponse."""


# ------------------------------------------------- le dictionnaire d'affichage

def donnees(conn, run_id: int, date_du_jour) -> dict:
    """Le contrat d'ARCHITECTURE.md §3 : tout ce que la page affiche, prêt à
    afficher, JSON-sérialisable (dict/list/str/int/float/bool/None)."""
    d = _collecte(conn, run_id)
    r = d["resume"]
    taux = r["rate"] or 0
    palier, reste = _objectif(taux)
    trous = [q for q in d["requetes"] if q["taux"] < SEUIL_TROU]
    forts = [q for q in d["requetes"] if q["taux"] >= 60][:5]
    moi = next((v for v in d["voix"] if v["moi"]), None)
    place = next((i for i, v in enumerate(d["voix"], 1) if v["moi"]), None)
    poursuivant = next((v for v in d["voix"] if not v["moi"]), None)

    impacts = [_impact(q, d["requetes"], r) for q in trous]
    moyen = (sum(impacts) / len(impacts)) if impacts else 0
    contenus = math.ceil(reste / moyen) if moyen > 0.2 else None

    marge = _marge(r)
    ctx = d["delta_ctx"]
    # La marge du VERDICT se calcule sur l'échantillon effectivement comparé
    # (le périmètre commun), pas sur la collecte entière.
    marge_cmp = _marge(ctx["resume"]) if ctx else marge
    # Le périmètre comparé s'affiche TOUJOURS (Marion, 05/08) : le lecteur
    # doit voir sur quoi porte le delta sans ouvrir un fichier.
    note_perim = ""
    if ctx:
        note_perim = (f" Comparaison avec la collecte #{ctx['prev_id']}, sur leurs "
                      f"{ctx['n_moteurs']} moteurs communs.")
    if d["delta"] is None:
        badge = None
        phrase = "Aucune collecte antérieure comparable : la courbe démarre ici."
    elif abs(d["delta"]) <= marge_cmp:
        # Dans la marge de fluctuation : ni victoire ni alerte, on le DIT.
        badge = {"variante": "stable", "delta": d["delta"]}
        phrase = (f"Variation de {nb(abs(d['delta']))} {points(d['delta'])} : dans la marge "
                  f"de fluctuation normale (±{nb(marge_cmp)} pts), ce n'est ni une "
                  f"progression ni un recul." + note_perim)
    else:
        haut = d["delta"] >= 0
        badge = {"variante": "hausse" if haut else "baisse", "delta": d["delta"]}
        phrase = (f"{'▲' if haut else '▼'} {nb(abs(d['delta']))} {points(d['delta'])} depuis "
                  f"la collecte précédente, au-delà de la marge de ±{nb(marge_cmp)} pts : "
                  f"le mouvement est réel." + note_perim)

    # Santé de la collecte. Un moteur qui tombe ne fait PAS échouer le job : il
    # est sauté proprement et creuse un trou muet dans la série. Le seul
    # remède est de le montrer ici, à côté du taux, à chaque lecture.
    # Passe 7 : les moteurs configurés mais ABSENTS du run (interruption en
    # cours d'écriture) passent en tête — un run amputé doit le dire.
    absents = [s for s in d["sante"] if s.get("absent")]
    casses = [s for s in d["sante"] if s["erreurs"] and not s.get("absent")]
    muets = [s for s in d["sante"] if s["ok"] == 0 and not s.get("absent")]
    n_conf = len(d["sante"])  # moteurs activés dans la config (présents + absents)
    if absents:
        noms = ", ".join(NOMS_COURTS.get(s["id"], s["id"]) for s in absents)
        seul = len(absents) == 1
        sante = {"variante": "muette",
                 "texte": (f"⚠ Collecte interrompue : {noms} "
                           f"{'n’a jamais été interrogé' if seul else 'n’ont jamais été interrogés'} "
                           f"({len(d['sante']) - len(absents)}/{n_conf} moteurs couverts). "
                           f"La collecte s'est arrêtée avant la fin, à relancer.")}
    elif muets:
        noms = ", ".join(NOMS_COURTS.get(s["id"], s["id"]) for s in muets)
        sante = {"variante": "muette",
                 "texte": (f"⚠ {noms} n'a rien renvoyé de la collecte : la série a un trou "
                           f"sur ce moteur, à traiter avant le prochain lundi.")}
    elif casses:
        detail = " · ".join(
            f'{NOMS_COURTS.get(s["id"], s["id"])} {s["ok"]}/{s["total"]}' for s in casses
        )
        tot = d["resume_total"]
        sante = {"variante": "partielle",
                 "texte": (f"Collecte partielle : {tot['ok'] / tot['n'] * 100:.0f} % des appels "
                           f"aboutis ({detail}). Les appels sans réponse exploitable sont "
                           f"exclus du taux, ils ne le font pas baisser.")}
    else:
        accord = ("le moteur configuré a répondu" if n_conf == 1
                  else f"les {n_conf} moteurs configurés ont répondu")
        sante = {"variante": "ok",
                 "texte": f"Collecte complète : {accord}, aucun appel perdu."}

    # Passe 1 corrigée (Marion, 05/08/2026) : la règle graduée REVIENT dans le
    # hero, sans elle il était à moitié vide. Les stats de part de voix, elles,
    # restent une preuve : elles vivent à côté de la carte voix.
    # Une collecte sans AUCUN appel exploitable n'a pas un taux de 0 %, elle
    # n'a pas de taux : afficher zéro serait le mensonge que le README dénonce
    # (états vides, passe du 06/08). La jauge affiche « — » et la phrase dit
    # ce qui s'est passé.
    mesurable = bool(r["ok"])
    if not mesurable:
        titre = "Aucun appel exploitable sur cette collecte"
        phrase = (f"Les {d['resume_total']['n']} appels de cette collecte ont tous "
                  f"échoué : le taux ne peut pas être mesuré. La ligne de santé "
                  f"ci-dessous dit quels moteurs sont tombés.")
    else:
        titre = ("Une réponse d'IA sur deux cite la marque" if 45 <= taux <= 55
                 else f"{taux:.0f} % des réponses d'IA citent la marque")
    hero = {
        "taux": taux,
        "mesurable": mesurable,
        # Le périmètre du taux : les moteurs AVEC recherche web uniquement.
        # La mémoire de marque garde sa carte, sur son propre axe.
        "n_moteurs": sum(1 for m in d["moteurs"] if m["recherche"]),
        # La phrase du hero précise que la mémoire de marque est suivie SUR UN
        # AUTRE AXE. Depuis qu'un moteur sans recherche peut être éteint
        # (10/08/2026), cette précision ne doit sortir que s'il en reste un :
        # sinon le tableau annonce un suivi qui n'existe plus.
        "memoire_suivie": any(not m["recherche"] for m in d["moteurs"]),
        "titre": titre,
        "badge": badge,
        "phrase": phrase,
        "appels_reussis": r["ok"],
        "sante": sante,
        "palier": palier,
        "reste": reste,
        "contenus": contenus,
    }
    stats = {"place": place, "place_suffixe": "re" if place == 1 else "e",
             "domaines": d["domaines_distincts"],
             "part": moi["part"] if moi else None,
             "rang": r["avg_rank"]}

    sante_par_moteur = {s["id"]: s for s in d["sante"]}
    meilleur = max((x["taux"] for x in d["moteurs"]), default=0)
    moteurs = []
    for m in d["moteurs"]:
        tag = None
        if m["recherche"] and m["taux"] >= meilleur:
            tag = "allie"
        elif not m["recherche"]:
            tag = "objectif"
        s = sante_par_moteur.get(m["id"], {})
        moteurs.append({
            # L'identifiant voyage avec le nom : la couche rendu en a besoin
            # pour choisir la marque du moteur, et un logo ne se déduit pas
            # d'un libellé traduisible.
            "id": m["id"],
            "nom": NOMS_MOTEURS.get(m["id"], m["id"]),
            "taux": m["taux"],
            "est_zero": m["taux"] < 1,
            "rang": m["rang"],
            "appels": {"ok": s.get("ok", m["ok"]), "total": s.get("total", m["ok"]),
                       "erreurs": s.get("erreurs", 0), "en_erreur": bool(s.get("erreurs"))},
            "lecture": _lecture_moteur(m, d["moteurs"]),
            "tag": tag,
        })

    # « À FAIRE », section unique (fusion mission + articles, Passe 1).
    # Trois entrées, la n°1 d'abord (la requête sous le seuil de trou qui
    # rapporterait le plus), puis les opportunités suivantes : on ne se limite
    # PAS aux requêtes sous le seuil, il y en a rarement trois, et la question
    # « qu'est-ce que j'écris ensuite ? » se pose à chaque collecte.
    # Structure UNIFIÉE pour les trois ; `contexte` et `brief` sont OPTIONNELS
    # et portés par la n°1 (l'ex-mission garde ses deux boutons et sa phrase
    # de terrain : une fusion ne supprime pas de fonctionnalité).
    cible = max(trous, key=lambda q: _impact(q, d["requetes"], r)) if trous else None
    candidats = sorted(
        (q for q in d["requetes"]
         if q["taux"] < 60 and (cible is None or q["id"] != cible["id"])),
        key=lambda q: _impact(q, d["requetes"], r), reverse=True,
    )[:2]
    entrees = ([cible] if cible is not None else []) + candidats
    items = []
    for i, q in enumerate(entrees, start=1):
        est_cible = cible is not None and q["id"] == cible["id"]
        occ = d["occupants"].get(q["id"], [])
        items.append({
            "numero": i, "question": q["texte"], "diagnostic": _diagnostic(q),
            "contexte": ((f"Le terrain est occupé par {', '.join(occ[:3])}." if occ
                          else "Aucun domaine ne s'impose : le terrain est libre.")
                         if est_cible else None),
            "impact": _promesse(_impact(q, d["requetes"], r)), "taux": q["taux"],
            "taux_warn": q["taux"] >= 10,
            "brief": _brief(q, d) if est_cible else None,
            "recette": _prompt_ia(q, d),
        })
    a_faire = {"items": items}

    lignes_voix = []
    for i, v in enumerate(d["voix"], 1):
        est_pours = v is poursuivant
        lignes_voix.append({
            "rang": i, "domaine": v["domaine"],
            "sous_titre": v["label"] or ("la marque suivie" if v["moi"] else None),
            "part": v["part"], "est_moi": v["moi"], "est_poursuivant": est_pours,
            "ecart": (moi["part"] - v["part"]) if (est_pours and moi and place == 1) else None,
        })
    voix = {
        "total_citations": d["total_citations"],
        "domaines_distincts": d["domaines_distincts"],
        # Les stats descendues du hero (Passe 1) : c'est de la preuve, elles
        # vivent à côté du classement qu'elles résument.
        "stats": stats,
        "lead": ({"variante": "vide", "poursuivant": None, "ecart": None}
                 if not lignes_voix
                 else {"variante": "domine", "poursuivant": poursuivant["domaine"],
                       "ecart": moi["part"] - poursuivant["part"]}
                 if moi and poursuivant and place == 1
                 else {"variante": "neutre", "poursuivant": None, "ecart": None}),
        "lignes": lignes_voix,
    }

    # ⚠️ FUSION DU 12/08/2026 (Marion) : « forteresses » et « dominance »
    # affichaient DEUX MESURES DIFFÉRENTES SUR LES MÊMES REQUÊTES — 4 des 5
    # lignes étaient communes au run #16 — et se lisaient donc comme une
    # répétition. Elles n'en font plus qu'une : une requête forte porte son
    # taux de citation ET sa part de n°1, côte à côte. La question « je suis
    # citée, mais est-ce que je suis première ? » se lit sur une seule ligne.
    domg = d["dominance"]
    n1_par_requete = {x["id"]: x["part"] for x in d["dominance_requetes"]}
    forteresses = {
        "lead": ({"variante": "exemples", "texte_requete": forts[0]["texte"],
                  "taux": forts[0]["taux"]}
                 if forts else {"variante": "vide", "texte_requete": None, "taux": None}),
        "part_n1": domg["n1"] / domg["cites"] * 100 if domg["cites"] else 0,
        "part_texte": domg["en_texte"] / domg["ok"] * 100 if domg["ok"] else 0,
        "a_dominance": bool(d["dominance_requetes"]),
        "items": [{"texte": q["texte"], "taux": q["taux"],
                   # None (et pas 0) quand la requête n'a aucune citation :
                   # une part de n°1 sur zéro citation n'existe pas, elle ne
                   # vaut pas zéro. Le render affiche « — ».
                   "part_n1": n1_par_requete.get(q["id"])}
                  for q in forts],
    }

    # Nouvelle carte, à la place de « dominance » (Marion, 12/08/2026) : les
    # requêtes où la marque est faible, ET QUI PREND LA PLACE À SA PLACE.
    # ⚠️ Ce n'est PAS un doublon de « À faire » : celle-là prescrit trois
    # actions classées par gain estimé, celle-ci pose le diagnostic
    # concurrentiel sur l'ensemble des trous. C'est le premier palier du
    # chantier « dépasser le concurrent » — et il ne coûte rien, parce que la
    # table `sources` stockait déjà l'occupant de chaque réponse.
    faiblesses = {
        "seuil": SEUIL_TROU,
        "aucune": not trous,
        "n_total": len(trous),
        "items": [
            {"texte": q["texte"], "taux": q["taux"], "cites": q["cites"], "ok": q["ok"],
             # Les domaines qui occupent le terrain, dans l'ordre où ils
             # occupent. Vide = personne ne s'impose, c'est un terrain libre
             # et pas une place à prendre à quelqu'un : deux situations qui
             # n'appellent pas le même contenu.
             "occupants": d["occupants"].get(q["id"], [])[:3]}
            for q in sorted(trous, key=lambda q: q["taux"])[:5]
        ],
    }

    # pages_resume a disparu en Passe 1 : c'était une version tronquée
    # d'alignement, qui seul subsiste (niveau « preuve » de la vue produit).
    pages_total = sum(p["n"] for p in d["pages"])
    lead_pages = ({"page": d["pages"][0]["page"], "n": d["pages"][0]["n"],
                   "total": pages_total} if d["pages"] else None)

    menees = sum(1 for x in d["duel"] if x["moi"] > x["lui"])
    perdues = sum(1 for x in d["duel"] if x["lui"] > x["moi"])
    duel = {
        "affiche": bool(d["duel"]),
        # Sans rival dans le YAML, la carte disparaît (choix documenté côté
        # rendu) ; avec un rival mais sans données, elle affiche l'attente.
        "rival_configure": d["rival"] is not None,
        "rival_label": d["rival_label"],
        "menees": menees, "perdues": perdues,
        "egales": len(d["duel"]) - menees - perdues,
        "lignes": [{"question": x["texte"], "moi": x["moi"], "lui": x["lui"]}
                   for x in d["duel"][:8]],
    }

    sctx = d["serie_ctx"]
    courbe = {
        "variante": "attente" if len(d["serie"]) < 2 else "tracee",
        "marge": marge,
        "n_moteurs": sctx["n_moteurs"] if sctx else len(d["moteurs"]),
        "points": d["serie"],
    }

    avec = [m for m in d["moteurs"] if m["recherche"]]
    plus_haut = min(avec, key=lambda m: m["rang"] or 99) if avec else None
    partout = sum(
        1 for q in d["requetes"]
        if all((d["matrice"].get(q["id"], {}).get(m["id"]) or {}).get("cites", 0) == 0
               for m in avec)
    )
    lignes_mx = []
    for q in d["requetes"]:
        cellules = []
        for m in d["moteurs"]:
            c = d["matrice"].get(q["id"], {}).get(m["id"])
            if not c or c["taux"] is None:
                cellules.append({"niveau": "na", "cites": 0, "ok": 0})
            else:
                t = c["taux"]
                # Le ratio brut, pas le pourcentage : sur 3 à 5 répétitions, un
                # « 100 % » se lirait comme une certitude alors que c'est 3 appels.
                niveau = ("zero" if t < 1 else "low" if t < 34
                          else "mid" if t < 67 else "high")
                cellules.append({"niveau": niveau, "cites": c["cites"], "ok": c["ok"]})
        lignes_mx.append({"id": q["id"], "texte": q["texte"], "cellules": cellules})
    matrice = {
        "affiche": bool(d["moteurs"] and d["requetes"]),
        "lead": {
            "moteur_haut": ({"nom": NOMS_COURTS.get(plus_haut["id"], plus_haut["id"]),
                             "rang": plus_haut["rang"]}
                            if plus_haut is not None and plus_haut["rang"] else None),
            "muettes": partout,
        },
        "colonnes": [{"id": m["id"], "nom_court": NOMS_COURTS.get(m["id"], m["id"]),
                      "taux": m["taux"]}
                     for m in d["moteurs"]],
        "lignes": lignes_mx,
    }

    pages_align = []
    for p in d["pages"]:
        # Deux signaux actionnables, et seulement ceux-là : l'accueil qui sert
        # de page d'atterrissage, et la page qui absorbe trop de sujets.
        flag = None
        if p["page"] == "/" and p["requetes"] >= 3:
            flag = {"variante": "accueil", "n": p["requetes"]}
        elif p["requetes"] >= 8:
            flag = {"variante": "absorbe", "n": p["requetes"]}
        pages_align.append({
            "page": p["page"], "n": p["n"], "requetes": p["requetes"],
            "detail": [{"texte": x["texte"], "n": x["n"]} for x in p["detail"][:5]],
            "reste": max(0, len(p["detail"]) - 5),
            "flag": flag,
        })
    alignement = {"vide": not d["pages"], "lead": lead_pages, "pages": pages_align}

    # Le tableau des requêtes a fusionné dans la matrice (Passe 1). La carte
    # porte les compteurs, le carnet d'idées (06/08) et le bloc observation :
    # `suivies` sert au contrôle de doublon côté navigateur, `observation`
    # affiche les requêtes proposées, collectées mais hors agrégats.
    jeu_requetes = {
        "set_version": d["set_version"],
        "n_requetes": len(d["requetes"]),
        "n_concurrents": d["n_concurrents"],
        "client": d["client"],
        "suivies": [{"id": q["id"], "texte": q["texte"]}
                    for q in d["prompts_config"]],
        "observation": {
            "lignes": [
                {
                    "id": q["id"], "texte": q["texte"],
                    # Les taux viennent des DONNÉES ; une requête importée
                    # entre deux collectes n'en a pas encore : taux None,
                    # le render affiche « en attente de première collecte ».
                    **next(
                        ({"taux": x["taux"], "cites": x["cites"], "ok": x["ok"]}
                         for x in d["observation"] if x["id"] == q["id"]),
                        {"taux": None, "cites": 0, "ok": 0},
                    ),
                }
                for q in d["prompts_config"] if q["statut"] == "observation"
            ],
            "plafond": d["plafond_observation"],
        },
    }

    console = _console(d, _prochaine_collecte(date_du_jour))

    meta = {
        "produit_nom": d["produit"]["nom"],
        "produit_signature": d["produit"]["signature"],
        "client": d["client"],
        "client_label": d["client_label"],
        "client_initiale": d["client_label"][:1].upper(),
        "run_id": d["run_id"],
        "date": d["date"],
        "n_appels": d["resume_total"]["n"],
        "prochaine_collecte": _prochaine_collecte(date_du_jour),
    }

    return {"meta": meta, "hero": hero, "moteurs": moteurs, "a_faire": a_faire,
            "voix": voix, "forteresses": forteresses, "faiblesses": faiblesses,
            "duel": duel, "courbe": courbe, "matrice": matrice,
            "alignement": alignement, "jeu_requetes": jeu_requetes,
            "console": console}
