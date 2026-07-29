"""Transforme les runs en métriques lisibles.

    python -m geotracker.report                 # dernier run, comparé au précédent
    python -m geotracker.report --run 3
    python -m geotracker.report --serie         # la courbe, tous runs confondus

Rien n'est stocké ici : tout se recalcule depuis `responses`. On peut donc
corriger une règle de comptage et rejouer l'historique entier.
"""

from __future__ import annotations

import argparse
import sys

from . import db
from .run import load_dotenv


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator * 100:.0f} %" if denominator else "n/a"


def _delta(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return ""
    diff = current - previous
    if abs(diff) < 0.5:
        return "  (=)"
    return f"  ({diff:+.0f} pts)"


def run_summary(conn, run_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0))       AS cited,
               AVG(source_rank)              AS avg_rank,
               AVG(text_position)            AS avg_position
        FROM responses WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    n, ok = row["n"] or 0, row["ok"] or 0
    return {
        "n": n,
        "ok": ok,
        "errors": n - ok,
        "cited": row["cited"] or 0,
        "rate": (row["cited"] or 0) / ok * 100 if ok else None,
        "avg_rank": row["avg_rank"],
        "avg_position": row["avg_position"],
    }


def report_run(conn, run_id: int, previous_id: int | None) -> None:
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        print(f"Run #{run_id} introuvable.")
        return

    current = run_summary(conn, run_id)
    previous = run_summary(conn, previous_id) if previous_id else None

    print(f"\n# Run #{run_id} — {meta['client']} — {meta['started_at']}")
    print(f"Set de requêtes v{meta['set_version']}")
    if previous_id:
        print(f"Comparé au run #{previous_id}")

    print("\n## Vue d'ensemble")
    print(f"  Appels réussis        : {current['ok']}/{current['n']}"
          + (f"  ⚠️ {current['errors']} erreurs" if current["errors"] else ""))
    print(f"  Taux de citation      : {_pct(current['cited'], current['ok'])}"
          + _delta(current["rate"], previous["rate"] if previous else None))
    if current["avg_rank"]:
        print(f"  Rang moyen en source  : {current['avg_rank']:.1f}")
    if current["avg_position"] is not None:
        print(f"  Position dans le texte: {current['avg_position']:.2f}  "
              "(0 = tout en haut, 1 = tout en bas)")

    print("\n## Par moteur")
    rows = conn.execute(
        """
        SELECT engine_id, search_enabled,
               COUNT(*) AS n,
               SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0)) AS cited,
               AVG(source_rank) AS avg_rank
        FROM responses WHERE run_id = ?
        GROUP BY engine_id ORDER BY engine_id
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        mode = "recherche" if row["search_enabled"] else "mémoire "
        rank = f"rang moy. {row['avg_rank']:.1f}" if row["avg_rank"] else ""
        print(f"  {row['engine_id']:<20} {mode}  "
              f"{_pct(row['cited'], row['ok']):>5}  ({row['cited']}/{row['ok']})  {rank}")

    print("\n## Par requête  (cité / appels réussis)")
    rows = conn.execute(
        """
        SELECT prompt_id, prompt_text,
               SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0)) AS cited
        FROM responses WHERE run_id = ?
        GROUP BY prompt_id ORDER BY cited * 1.0 / MAX(ok, 1) DESC, prompt_id
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        bar = "█" * round((row["cited"] / row["ok"] * 10) if row["ok"] else 0)
        print(f"  {row['prompt_id']}  {_pct(row['cited'], row['ok']):>5} {bar:<10} "
              f"{row['prompt_text'][:58]}")

    print("\n## Part de voix  (qui occupe la place)")
    # ⚠️ Le dénominateur couvre TOUS les domaines cités, pas seulement les 15
    # affichés : sinon la part est gonflée par la troncature de l'affichage.
    total = (
        conn.execute(
            """SELECT COUNT(*) n FROM sources s JOIN responses r ON r.id = s.response_id
               WHERE r.run_id = ? AND s.domain IS NOT NULL AND s.domain <> ''""",
            (run_id,),
        ).fetchone()["n"]
        or 1
    )
    rows = conn.execute(
        """
        SELECT s.domain, s.is_target, s.competitor,
               COUNT(*) AS citations,
               AVG(s.rank) AS avg_rank
        FROM sources s JOIN responses r ON r.id = s.response_id
        WHERE r.run_id = ? AND s.domain IS NOT NULL AND s.domain <> ''
        GROUP BY s.domain ORDER BY citations DESC LIMIT 15
        """,
        (run_id,),
    ).fetchall()
    distincts = conn.execute(
        """SELECT COUNT(DISTINCT s.domain) n FROM sources s
           JOIN responses r ON r.id = s.response_id
           WHERE r.run_id = ? AND s.domain IS NOT NULL AND s.domain <> ''""",
        (run_id,),
    ).fetchone()["n"]
    print(f"  ({total} citations réparties sur {distincts} domaines distincts)")
    for row in rows:
        tag = "  ⬅ TOI" if row["is_target"] else (f"  [{row['competitor']}]" if row["competitor"] else "")
        print(f"  {row['citations']:>4}  {row['citations']/total*100:>4.1f} %  "
              f"rang {row['avg_rank']:.1f}  {row['domain']}{tag}")


def report_serie(conn, client: str) -> None:
    print(f"\n# Série temporelle — {client}")
    print("C'est ÇA le livrable. Le reste n'est que de la présentation.\n")
    rows = conn.execute(
        "SELECT id, started_at FROM runs WHERE client = ? ORDER BY started_at", (client,)
    ).fetchall()
    if not rows:
        print("Aucun run pour ce client.")
        return
    print(f"  {'date':<22} {'run':>4}  {'citation':>9}  {'rang moy':>9}")
    for row in rows:
        summary = run_summary(conn, row["id"])
        rate = f"{summary['rate']:.0f} %" if summary["rate"] is not None else "n/a"
        rank = f"{summary['avg_rank']:.1f}" if summary["avg_rank"] else "-"
        print(f"  {row['started_at']:<22} #{row['id']:<3}  {rate:>9}  {rank:>9}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tracker GEO : rapports.")
    parser.add_argument("--client", default="smart-bpjeps")
    parser.add_argument("--run", type=int, help="id du run (défaut : le dernier)")
    parser.add_argument("--serie", action="store_true", help="la courbe, tous runs")
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    args = parser.parse_args(argv)

    load_dotenv()
    conn = db.connect(args.db)

    if args.serie:
        report_serie(conn, args.client)
        return 0

    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM runs WHERE client = ? ORDER BY id DESC LIMIT 2", (args.client,)
        ).fetchall()
    ]
    if not ids:
        print("Aucun run enregistré. Lance : python -m geotracker.run")
        return 1

    run_id = args.run or ids[0]
    previous = next((i for i in ids if i < run_id), None)
    report_run(conn, run_id, previous)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
