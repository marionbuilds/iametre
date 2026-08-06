"""Extraction des ATTRIBUTS de marque (chantier b, 06/08/2026).

Le tracker répond à « est-ce qu'on me cite ». Ce module répond à « quand un
modèle parle de la marque, QUE DIT-IL exactement ? » : quels attributs lui
associe-t-il (le livre, la plateforme, les diplômes couverts, la
fondatrice…).

    python -m geotracker.attributs                    # tout l'historique
    python -m geotracker.attributs --run 15           # une collecte
    python -m geotracker.attributs --sans-exemples    # chiffres seuls

Règle de comptage : un attribut est associé à la marque quand un de ses
termes apparaît DANS LA MÊME PHRASE qu'une mention de la marque. Le lexique
vit dans le YAML du client (`attributs:`), versionnable comme le reste.

Extraction PURE, comme extract.py : aucun appel réseau, aucun stockage,
rejouable sur tout le brut déjà conservé (`answer_text`). C'est la
démonstration de la règle n°1 du projet : les agrégats se recalculent,
une réponse perdue ne se rattrape pas — ici, une métrique née le 06/08
se calcule sur des collectes du 28/07.
"""

from __future__ import annotations

import argparse
import re
import sys

from . import db
from .config import load_client
from .extract import _fold


def _phrases(texte: str) -> list[str]:
    """Découpage volontairement fruste : points, exclamations, interrogations,
    retours à la ligne (les réponses d'IA sont pleines de listes à puces)."""
    return [p for p in re.split(r"[.!?\n]+", texte or "") if p.strip()]


def _contient(phrase_pliee: str, terme: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(_fold(terme)) + r"(?![a-z0-9])"
    return re.search(pattern, phrase_pliee) is not None


def attributs_dans(texte: str, brand_terms: list[str], lexique: list[dict]) -> tuple[set, dict]:
    """Les attributs co-présents avec la marque dans une même phrase.

    Renvoie (ids trouvés, un exemple de phrase par attribut). Pure et
    déterministe : appelable sur n'importe quel texte, sans base présente.
    """
    trouves: set[str] = set()
    exemples: dict[str, str] = {}
    for phrase in _phrases(texte):
        pliee = _fold(phrase)
        if not any(_contient(pliee, t) for t in brand_terms):
            continue
        for attribut in lexique:
            if any(_contient(pliee, terme) for terme in attribut["termes"]):
                trouves.add(attribut["id"])
                exemples.setdefault(attribut["id"], phrase.strip())
    return trouves, exemples


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:3.0f} %" if d else "  — "


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Attributs associés à la marque.")
    ap.add_argument("--client", default="smart-bpjeps")
    ap.add_argument("--run", type=int, help="limiter à une collecte")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--sans-exemples", action="store_true")
    a = ap.parse_args(argv)

    cfg = load_client(a.client)
    if not cfg.attributs:
        print(f"Aucun lexique `attributs:` dans la configuration de {a.client}.")
        return 1

    conn = db.connect(a.db)
    clause, params = ("AND run_id = ?", [a.run]) if a.run else ("", [])
    lignes = conn.execute(
        f"""SELECT run_id, engine_id, answer_text FROM responses
           WHERE client = ? AND error IS NULL AND answer_text IS NOT NULL
             AND answer_text <> '' {clause}""",
        (cfg.client, *params),
    ).fetchall()

    # Agrégats : global, par moteur, par collecte. Le dénominateur est le
    # nombre de réponses qui NOMMENT la marque dans leur texte : on mesure ce
    # que le modèle dit d'elle quand il en parle, pas sa visibilité (déjà
    # couverte ailleurs).
    total = 0
    avec_marque = 0
    par_attr: dict[str, int] = {x["id"]: 0 for x in cfg.attributs}
    par_moteur: dict[str, dict] = {}
    par_run: dict[int, dict] = {}
    exemples: dict[str, str] = {}

    for l in lignes:
        total += 1
        trouves, ex = attributs_dans(l["answer_text"], cfg.brand_terms, cfg.attributs)
        # « la marque est nommée » = au moins une phrase de marque détectée,
        # attribut ou pas ; on la détecte via une passe dédiée bon marché.
        nomme = any(
            any(_contient(_fold(p), t) for t in cfg.brand_terms)
            for p in _phrases(l["answer_text"])
        )
        if not nomme:
            continue
        avec_marque += 1
        m = par_moteur.setdefault(l["engine_id"], {"n": 0, **{k: 0 for k in par_attr}})
        r = par_run.setdefault(l["run_id"], {"n": 0, **{k: 0 for k in par_attr}})
        m["n"] += 1
        r["n"] += 1
        for aid in trouves:
            par_attr[aid] += 1
            m[aid] += 1
            r[aid] += 1
        for aid, phrase in ex.items():
            exemples.setdefault(aid, phrase)

    conn.close()

    perimetre = f"collecte #{a.run}" if a.run else "TOUT l'historique"
    print(f"\n# Attributs associés à la marque — {cfg.label} — {perimetre}")
    print(f"{total} réponses exploitables, dont {avec_marque} nomment la marque "
          f"dans leur texte : c'est la base de calcul.\n")

    print("## Quand un modèle parle de la marque, il lui associe…")
    labels = {x["id"]: x["label"] for x in cfg.attributs}
    for aid, n in sorted(par_attr.items(), key=lambda x: -x[1]):
        barre = "█" * round(n / avec_marque * 20) if avec_marque else ""
        print(f"  {_pct(n, avec_marque)}  {barre:<20}  {labels[aid]}  ({n}/{avec_marque})")

    print("\n## Par moteur (part des réponses du moteur qui nomment la marque)")
    ordre_attrs = [x["id"] for x in cfg.attributs]
    entete = "  ".join(f"{aid[:8]:>8}" for aid in ordre_attrs)
    print(f"  {'moteur':<18} {'n':>4}  {entete}")
    for eid, m in sorted(par_moteur.items(), key=lambda x: -x[1]["n"]):
        cellules = "  ".join(f"{_pct(m[aid], m['n']):>8}" for aid in ordre_attrs)
        print(f"  {eid:<18} {m['n']:>4}  {cellules}")

    print("\n## Par collecte (les runs où la marque est nommée au moins 10 fois)")
    print(f"  {'run':>4} {'n':>4}  {entete}")
    for rid, r in sorted(par_run.items()):
        if r["n"] < 10:
            continue
        cellules = "  ".join(f"{_pct(r[aid], r['n']):>8}" for aid in ordre_attrs)
        print(f"  #{rid:>3} {r['n']:>4}  {cellules}")

    if not a.sans_exemples and exemples:
        print("\n## Ce qu'ils disent, mot pour mot (un exemple par attribut)")
        for aid in ordre_attrs:
            if aid in exemples:
                phrase = exemples[aid]
                if len(phrase) > 160:
                    phrase = phrase[:157] + "…"
                print(f"  [{labels[aid]}]")
                print(f"    « {phrase} »")
    return 0


if __name__ == "__main__":
    sys.exit(main())
