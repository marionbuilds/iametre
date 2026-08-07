"""Exactitude des faits (chantier c, 08/08/2026).

Le tracker répond à « est-ce qu'on me cite », les attributs à « que dit-il
de la marque ». Ce module répond à la troisième question : « dit-il JUSTE ? »
Sur une requête comme « quel diplôme remplace le BPJEPS ? », la métrique
utile n'est pas la citation mais la justesse de la réponse — le prolongement
de la mémoire de marque : de « connaît-il la marque » à « connaît-il les
faits du secteur ».

    python -m geotracker.faits                    # tout l'historique
    python -m geotracker.faits --run 15           # une collecte
    python -m geotracker.faits --sans-exemples    # chiffres seuls

Un fait est déclaré dans le YAML du client (`faits:`) : les requêtes où il
est attendu, les termes qui prouvent la bonne réponse (`juste`), et les
erreurs CONNUES (`faux`), observées dans le brut et enrichies sans coût
puisque tout se rejoue. Verdict par réponse :

    juste  — un terme de `juste` apparaît dans la prose (URLs retirées :
             un lien /bpjeps-apsf ne prouve pas que le modèle DIT la bonne
             réponse, même règle d'honnêteté que les attributs)
    faux   — sinon, une erreur connue apparaît
    muet   — sinon : le modèle n'aborde pas le fait, ou répond à côté

Différence assumée avec les attributs : PAS de découpage en phrases. Le
ciblage se fait par requête (toute la réponse à q12 parle du remplacement),
donc le piège du découpage disparaît au lieu d'être géré. Les bornes de mots
restent strictes : « MAPS » (faux) ne matche pas dans « MAPST » (juste).

Limites documentées d'avance : une négation (« l'APSF ne remplace pas… »)
serait comptée juste — rare, et la liste `faux` attrape les erreurs
réellement observées ; si `juste` et `faux` apparaissent tous deux, juste
gagne. Et le croisement avec les sources est une CO-OCCURRENCE, pas une
attribution : être cité dans une réponse juste ne prouve pas que
l'information vient de nous.

Extraction PURE, comme extract.py et attributs.py : aucun appel réseau,
aucun stockage, rejouable sur tout le brut déjà conservé.
"""

from __future__ import annotations

import argparse
import sys

from . import db
from .attributs import _URL, _contient, _phrases
from .config import load_client
from .extract import _fold


def verdict(texte: str, fait: dict) -> str:
    """Le verdict d'une réponse sur un fait : « juste », « faux » ou « muet ».
    Pur et déterministe, appelable sur n'importe quel texte, sans base.

    Champ optionnel `contexte` (resserrage du 08/08, décision Marion) : quand
    un terme de preuve est trop générique (« tronc commun » vaut pour l'APSF
    comme pour l'ASEC), le fait déclare des termes de contexte, et la preuve
    ne compte que DANS UNE PHRASE qui porte aussi le contexte — la règle des
    attributs, appliquée au cas par cas. Même limite héritée : dans une liste
    à puces, contexte et preuve peuvent être séparés (borne basse). Sans
    `contexte`, la preuve se cherche sur toute la prose."""
    juste, faux = fait.get("juste", []), fait.get("faux", [])
    ctx = fait.get("contexte")
    if not ctx:
        prose = _fold(_URL.sub(" ", texte or ""))
        if any(_contient(prose, t) for t in juste):
            return "juste"
        if any(_contient(prose, t) for t in faux):
            return "faux"
        return "muet"
    a_juste = a_faux = False
    for phrase in _phrases(texte or ""):
        prose = _fold(_URL.sub(" ", phrase))
        if not any(_contient(prose, c) for c in ctx):
            continue
        a_juste = a_juste or any(_contient(prose, t) for t in juste)
        a_faux = a_faux or any(_contient(prose, t) for t in faux)
    return "juste" if a_juste else ("faux" if a_faux else "muet")


def _extrait(texte: str, termes: list[str], contexte: list[str] | None = None) -> str:
    """La première phrase où un des termes apparaît (hors URL, et portant le
    contexte si le fait en déclare un), pour montrer le verdict mot pour mot.
    Ce découpage en phrases ne sert qu'à L'AFFICHAGE."""
    for phrase in _phrases(texte or ""):
        prose = _fold(_URL.sub(" ", phrase))
        if contexte and not any(_contient(prose, c) for c in contexte):
            continue
        if any(_contient(prose, t) for t in termes):
            p = phrase.strip()
            return p if len(p) <= 160 else p[:157] + "…"
    return ""


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:3.0f} %" if d else "  — "


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exactitude des faits du secteur.")
    ap.add_argument("--client", default="smart-bpjeps")
    ap.add_argument("--run", type=int, help="limiter à une collecte")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--sans-exemples", action="store_true")
    a = ap.parse_args(argv)

    cfg = load_client(a.client)
    if not cfg.faits:
        print(f"Aucun bloc `faits:` dans la configuration de {a.client}.")
        return 1

    conn = db.connect(a.db)
    clause, params = ("AND run_id = ?", [a.run]) if a.run else ("", [])
    lignes = conn.execute(
        f"""SELECT run_id, prompt_id, engine_id, cited, answer_text
           FROM responses
           WHERE client = ? AND {db.EXPLOITABLE} {clause}""",
        (cfg.client, *params),
    ).fetchall()
    conn.close()

    perimetre = f"collecte #{a.run}" if a.run else "TOUT l'historique"
    print(f"\n# Exactitude des faits — {cfg.label} — {perimetre}")
    print("Verdict par réponse : juste / faux / muet, sur les seules requêtes où le "
          "fait est attendu.\nLa colonne « dont source » compte les réponses justes "
          "où la marque est citée en source :\nc'est une co-occurrence, pas une "
          "preuve que l'information vient de nous.")

    for fait in cfg.faits:
        cibles = [l for l in lignes if l["prompt_id"] in fait["requetes"]]
        if not cibles:
            print(f"\n## {fait['label']}\n  Aucune réponse exploitable sur "
                  f"{', '.join(fait['requetes'])} dans ce périmètre.")
            continue

        comptes = {"juste": 0, "faux": 0, "muet": 0}
        juste_et_source = 0
        par_moteur: dict[str, dict] = {}
        ex_juste = ex_faux = ""
        for l in cibles:
            v = verdict(l["answer_text"], fait)
            comptes[v] += 1
            m = par_moteur.setdefault(
                l["engine_id"], {"n": 0, "juste": 0, "faux": 0, "muet": 0, "source": 0})
            m["n"] += 1
            m[v] += 1
            if v == "juste":
                if l["cited"]:
                    juste_et_source += 1
                    m["source"] += 1
                ex_juste = ex_juste or _extrait(l["answer_text"], fait.get("juste", []),
                                                fait.get("contexte"))
            elif v == "faux":
                ex_faux = ex_faux or _extrait(l["answer_text"], fait.get("faux", []),
                                              fait.get("contexte"))

        n = len(cibles)
        print(f"\n## {fait['label']}  ({', '.join(fait['requetes'])} · {n} réponses)")
        print(f"  juste {_pct(comptes['juste'], n)} (dont source : "
              f"{_pct(juste_et_source, comptes['juste'])}) · "
              f"faux {_pct(comptes['faux'], n)} · muet {_pct(comptes['muet'], n)}")
        print(f"  {'moteur':<18} {'n':>3}  {'juste':>6} {'faux':>6} {'muet':>6}  {'dont source':>11}")
        for eid, m in sorted(par_moteur.items(), key=lambda x: -x[1]["n"]):
            print(f"  {eid:<18} {m['n']:>3}  {_pct(m['juste'], m['n']):>6}"
                  f" {_pct(m['faux'], m['n']):>6} {_pct(m['muet'], m['n']):>6}"
                  f"  {_pct(m['source'], m['juste']):>11}")
        if not a.sans_exemples:
            if ex_faux:
                print(f"  ✗ mot pour mot : « {ex_faux} »")
            if ex_juste:
                print(f"  ✓ mot pour mot : « {ex_juste} »")
    return 0


if __name__ == "__main__":
    sys.exit(main())
