"""Le carnet d'idées : importer des propositions de requêtes dans le YAML.

    python -m geotracker.carnet ~/Downloads/propositions-requetes.json
    python -m geotracker.carnet fichier.json --oui        # sans confirmations
    python -m geotracker.carnet fichier.json --sans-push  # écrire, ne pas pousser

Le chemin en deux temps (décidé le 06/08/2026) : une page ouverte en file://
ne peut pas écrire sur le disque, elle fait donc TÉLÉCHARGER un fichier de
propositions ; cette commande l'importe dans le YAML du client, au statut
`observation` — collectée dès le lundi suivant, hors taux global tant
qu'elle n'est pas promue. Le YAML reste l'unique source de vérité.

Règles de la commande :
- insertion TEXTUELLE dans le fichier (jamais de réécriture PyYAML, qui
  détruirait tous les commentaires : l'expérience figée, les notes de coût…) ;
- relecture et validation du YAML après écriture, restauration si échec ;
- plafond de requêtes en observation (YAML `plafond_observation`) : l'import
  refuse au-delà, il ne troue jamais une série en cours pour du budget ;
- propose de committer et POUSSER : le cron du lundi lit le dépôt, une
  requête non poussée n'est jamais collectée — et l'état est dit clairement
  si on refuse.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .config import CLIENTS_DIR, ROOT, load_client
from .extract import _fold

COUT_MENSUEL_PAR_REQUETE = 1  # $/mois, arrondi prudent (mesuré : ≈ 0,70 $)


def prochain_id(ids_existants: list[str]) -> str:
    """q01…q15 → q16. Ne réutilise jamais un numéro : la série est ambiguë
    sinon, même pour une requête retirée."""
    numeros = [int(m.group(1)) for i in ids_existants
               if (m := re.fullmatch(r"q(\d+)", i))]
    return f"q{max(numeros, default=0) + 1:02d}"


def inserer_prompts(texte_yaml: str, entrees: list[tuple[str, str]], date: str) -> str:
    """Insère des requêtes `observation` à la fin du bloc `prompts:`, par
    chirurgie textuelle : tous les commentaires du fichier survivent.

    Le bloc se termine à la première ligne non vide en colonne 0 qui suit
    `prompts:` (clé suivante ou bloc de commentaires de section).
    """
    lignes = texte_yaml.split("\n")
    try:
        debut = next(i for i, l in enumerate(lignes) if l.rstrip() == "prompts:")
    except StopIteration:
        raise SystemExit("Bloc `prompts:` introuvable dans le YAML.")
    derniere = debut
    for j in range(debut + 1, len(lignes)):
        if lignes[j].strip() and not lignes[j].startswith(" "):
            break
        if lignes[j].strip():
            derniere = j

    ajout = [f"  # Carnet d'idées, importées le {date} (observation : hors taux global)"]
    for pid, texte in entrees:
        propre = texte.replace("\\", "\\\\").replace('"', '\\"')
        ajout += [f"  - id: {pid}", f'    text: "{propre}"', "    statut: observation"]

    return "\n".join(lignes[: derniere + 1] + ajout + lignes[derniere + 1:])


def _confirmer(question: str, auto: bool) -> bool:
    if auto:
        return True
    reponse = input(f"{question} [O/n] ").strip().lower()
    return reponse in ("", "o", "oui", "y", "yes")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Importer des propositions de requêtes.")
    ap.add_argument("fichier", help="le JSON téléchargé depuis le dashboard")
    ap.add_argument("--oui", action="store_true", help="aucune confirmation demandée")
    ap.add_argument("--sans-push", action="store_true",
                    help="écrire le YAML sans committer ni pousser")
    a = ap.parse_args(argv)

    chemin = Path(a.fichier).expanduser()
    if not chemin.exists():
        raise SystemExit(f"Fichier introuvable : {chemin}")
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        client = donnees["client"]
        propositions = [str(x).strip() for x in donnees["propositions"]]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemExit(f"Fichier de propositions illisible ({exc}). Attendu : "
                         '{"client": …, "propositions": […]}')

    cfg = load_client(client)

    # Tri : doublons du YAML écartés (comparaison pliée), trop courts écartés.
    existants = {_fold(p.text): p.id for p in cfg.prompts}
    retenues, ecartees = [], []
    for texte in propositions:
        if len(texte) < 10:
            ecartees.append((texte, "trop courte"))
        elif _fold(texte) in existants:
            ecartees.append((texte, f"déjà suivie ({existants[_fold(texte)]})"))
        elif any(_fold(texte) == _fold(r) for r in retenues):
            ecartees.append((texte, "doublon dans le fichier"))
        else:
            retenues.append(texte)

    for texte, raison in ecartees:
        print(f"  ⏭  écartée ({raison}) : {texte[:60]}")
    if not retenues:
        print("Rien à importer.")
        return 0

    # Le plafond : on refuse À L'ENTRÉE, jamais à la collecte.
    en_observation = sum(1 for p in cfg.prompts if p.statut == "observation")
    if en_observation + len(retenues) > cfg.plafond_observation:
        raise SystemExit(
            f"Plafond atteint : {en_observation} requête(s) déjà en observation, "
            f"+{len(retenues)} demandée(s), plafond {cfg.plafond_observation} "
            f"(YAML `plafond_observation`). Promeus ou retire des requêtes en "
            f"observation avant d'en ajouter."
        )

    # Attribution des ids et récapitulatif AVANT d'écrire.
    entrees = []
    ids = [p.id for p in cfg.prompts]
    for texte in retenues:
        pid = prochain_id(ids)
        ids.append(pid)
        entrees.append((pid, texte))
    date = donnees.get("date") or "date inconnue"

    print(f"\nÀ importer dans {cfg.path.name}, au statut observation :")
    for pid, texte in entrees:
        print(f"  {pid}  {texte}")
    print(f"Coût de collecte : ≈ +{len(entrees) * COUT_MENSUEL_PAR_REQUETE} $/mois "
          f"({en_observation + len(entrees)}/{cfg.plafond_observation} en observation).")
    if not _confirmer("Écrire dans le YAML ?", a.oui):
        print("Abandon : rien n'a été écrit.")
        return 1

    # Écriture chirurgicale + relecture de validation, restauration si échec.
    chemin_yaml = CLIENTS_DIR / f"{client}.yaml"
    sauvegarde = chemin_yaml.read_bytes()
    chemin_yaml.write_text(
        inserer_prompts(sauvegarde.decode("utf-8"), entrees, date), encoding="utf-8"
    )
    try:
        relu = load_client(client)
        assert all(pid in [p.id for p in relu.prompts] for pid, _ in entrees)
    except Exception as exc:
        chemin_yaml.write_bytes(sauvegarde)
        raise SystemExit(f"Le YAML ne relit pas après écriture ({exc}) : "
                         "fichier RESTAURÉ à l'identique, rien n'est perdu.")
    print(f"✅ {len(entrees)} requête(s) écrite(s) dans {chemin_yaml.name}.")

    # Le commit-push fait partie du parcours : le cron du lundi lit le DÉPÔT.
    if a.sans_push or not _confirmer("Committer et pousser maintenant ?", a.oui):
        print("\n⚠️  Requêtes ajoutées LOCALEMENT, NON poussées : elles ne seront "
              "PAS collectées lundi.\n    Pour les activer : git add "
              f"config/clients/{client}.yaml && git commit && git push")
        return 0

    rel = str(chemin_yaml.relative_to(ROOT))
    for etape, args in (("add", ["add", rel]),
                        ("commit", ["commit", "-m",
                                    f"carnet : +{len(entrees)} requete(s) en observation"]),
                        ("push", ["push"])):
        r = _git(*args)
        if r.returncode != 0:
            print(f"\n⚠️  git {etape} a échoué :\n{r.stderr.strip()}")
            print("⚠️  Requêtes ajoutées localement, NON poussées : elles ne seront "
                  "PAS collectées lundi. Corrige puis `git push`.")
            return 1
    print("🚀 Poussé : la collecte de lundi les verra.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
