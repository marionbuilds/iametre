"""Génère l'interface d'IAmètre à partir des données collectées.

    python -m geotracker.dashboard                    # dernière collecte
    python -m geotracker.dashboard --run 13
    python -m geotracker.dashboard --donnees d.json   # le dictionnaire, sans HTML

Point d'entrée CLI seulement. Les données viennent de `dashboard_donnees`
(seule couche à toucher SQLite et les YAML), le HTML de `dashboard_rendu`
(pure mise en forme). Le contrat entre les deux est dans ARCHITECTURE.md.
La date du jour est passée en paramètre à la couche données, qui ne lit
jamais l'horloge : à base et date égales, la sortie est identique.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import ROOT
from .dashboard_donnees import donnees
from .dashboard_rendu import rendu

SORTIE = ROOT / "reports" / "dashboard.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interface d'IAmètre.")
    ap.add_argument("--client", default="smart-bpjeps")
    ap.add_argument("--run", type=int)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--out", default=str(SORTIE))
    ap.add_argument("--donnees", metavar="CHEMIN",
                    help="écrit le dictionnaire de données en JSON, sans générer le HTML")
    a = ap.parse_args(argv)

    conn = db.connect(a.db)
    run_id = a.run
    if run_id is None:
        ligne = conn.execute(
            "SELECT id FROM runs WHERE client=? ORDER BY id DESC LIMIT 1", (a.client,)
        ).fetchone()
        if ligne is None:
            print("Aucune collecte enregistrée. Lance : python -m geotracker.run")
            return 1
        run_id = ligne["id"]

    d = donnees(conn, run_id, date_du_jour=datetime.now(timezone.utc).date())
    conn.close()

    if a.donnees:
        Path(a.donnees).parent.mkdir(parents=True, exist_ok=True)
        Path(a.donnees).write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"Données écrites : {a.donnees}")
        return 0

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(rendu(d), encoding="utf-8")

    badge = d["hero"]["badge"]
    delta = "aucune collecte comparable" if badge is None else f"{badge['delta']:+.1f} pts"
    print(f"Interface écrite : {a.out}")
    print(f"  {d['meta']['produit_nom']} · collecte #{run_id} · {d['meta']['n_appels']} appels · "
          f"{d['hero']['taux']:.0f} % · évolution : {delta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
