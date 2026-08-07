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
from .config import load_client
from .run import load_dotenv


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator * 100:.0f} %" if denominator else "n/a"


def _delta(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return ""
    diff = current - previous
    if abs(diff) < 0.5:
        return "="
    return f"{diff:+.0f} pts"


def run_summary(conn, run_id: int, exclure=(), avec_memoire: bool = False) -> dict:
    """`exclure` : ids des requêtes « en observation », tenues hors des
    agrégats pour qu'un test de requête ne fasse jamais bouger la série.

    ⚠️ AXE DE MESURE (bug de méthode corrigé le 05/08/2026) : par défaut, le
    taux ne compte que les moteurs AVEC recherche web (`search_enabled = 1`).
    Une réponse à qui on a interdit de chercher ne mesure pas la visibilité,
    elle mesure la notoriété : la mémoire de marque vit sur son propre axe et
    ne s'additionne jamais au taux de visibilité (elle le sous-estimait de
    7 points). `avec_memoire=True` redonne les totaux de COLLECTE, tous
    moteurs : à réserver aux compteurs d'appels, jamais à un taux."""
    exclure = tuple(sorted(exclure))
    clause = f" AND prompt_id NOT IN ({','.join('?' * len(exclure))})" if exclure else ""
    if not avec_memoire:
        clause += " AND search_enabled=1"
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0))       AS cited,
               AVG(source_rank)              AS avg_rank,
               AVG(text_position)            AS avg_position
        FROM responses WHERE run_id = ?{clause}
        """,
        (run_id, *exclure),
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


def couverture(conn, run_id: int, exclure=()) -> tuple[set, set]:
    """Moteurs et requêtes réellement présents dans une collecte, SUR L'AXE
    VISIBILITÉ : seuls les moteurs avec recherche web comptent. La mémoire de
    marque n'entre ni dans les comparaisons ni dans la courbe (05/08/2026)."""
    exclure = set(exclure)
    engines, prompts = set(), set()
    for row in conn.execute(
        "SELECT DISTINCT engine_id, prompt_id FROM responses "
        "WHERE run_id = ? AND search_enabled=1", (run_id,)
    ):
        if row["prompt_id"] in exclure:
            continue
        engines.add(row["engine_id"])
        prompts.add(row["prompt_id"])
    return engines, prompts


def taux_commun(conn, run_id: int, engines, prompts) -> dict:
    """`run_summary` restreint à un périmètre (moteurs, requêtes) imposé."""
    engines, prompts = tuple(sorted(engines)), tuple(sorted(prompts))
    if not engines or not prompts:
        return {"n": 0, "ok": 0, "errors": 0, "cited": 0, "rate": None, "avg_rank": None}
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0)) AS cited,
               AVG(source_rank) AS avg_rank
        FROM responses WHERE run_id = ?
          AND engine_id IN ({','.join('?' * len(engines))})
          AND prompt_id IN ({','.join('?' * len(prompts))})
        """,
        (run_id, *engines, *prompts),
    ).fetchone()
    n, ok = row["n"] or 0, row["ok"] or 0
    return {"n": n, "ok": ok, "errors": n - ok, "cited": row["cited"] or 0,
            "rate": (row["cited"] or 0) / ok * 100 if ok else None,
            "avg_rank": row["avg_rank"]}


def plancher_moteurs(n_moins_fournie: int) -> int:
    """Nombre minimal de moteurs communs pour qu'une comparaison soit honnête :
    la MAJORITÉ des moteurs de la collecte la moins fournie, et jamais moins
    de 3. Deux collectes qui ne partageraient que Perplexity donneraient un
    delta qui ne mesure qu'un moteur en se présentant comme une évolution
    globale (plancher posé par Marion le 05/08/2026)."""
    return max(3, n_moins_fournie // 2 + 1)


def collecte_comparable(conn, run_id: int, client: str, exclure=()) -> dict | None:
    """La collecte antérieure la plus récente MESURABLE face à `run_id`.

    L'UNIQUE règle de comparaison du produit : le dashboard et le rapport
    texte passent tous les deux par ici. Deux collectes sont comparables sur
    leur PÉRIMÈTRE COMMUN : les requêtes communes doivent couvrir toutes les
    requêtes titulaires de la collecte courante, et les moteurs communs
    doivent atteindre le plancher (majorité de la collecte la moins fournie,
    minimum 3). Le delta se calcule ensuite pour les DEUX collectes
    restreintes à ce périmètre commun ; comparer 255 appels sur 5 moteurs à
    3 appels sur un seul n'est pas une mesure (bug réel du run #15, 05/08).
    """
    eng_cur, pr_cur = couverture(conn, run_id, exclure)
    if not eng_cur or not pr_cur:
        return None
    for row in conn.execute(
        "SELECT id FROM runs WHERE client = ? AND id < ? ORDER BY id DESC", (client, run_id)
    ):
        engines, prompts = couverture(conn, row["id"], exclure)
        commun = engines & eng_cur
        if pr_cur <= prompts and len(commun) >= plancher_moteurs(min(len(engines), len(eng_cur))):
            return {"prev_id": row["id"], "engines": commun,
                    "prompts": pr_cur, "reduit": commun < eng_cur}
    return None


def serie_commune(conn, client: str, exclure=(), reference: int | None = None) -> tuple[list, dict | None]:
    """La courbe, calculée à PÉRIMÈTRE CONSTANT.

    Un point par jour : le dernier run du jour qui couvre toutes les requêtes
    titulaires de la collecte de référence. Tous les points sont ensuite
    mesurés sur les moteurs COMMUNS à l'ensemble de ces runs : chaque point de
    la courbe est comparable à chaque autre, ou il n'y est pas.
    """
    if reference is None:
        row = conn.execute(
            "SELECT id FROM runs WHERE client = ? ORDER BY id DESC LIMIT 1", (client,)
        ).fetchone()
        if row is None:
            return [], None
        reference = row["id"]
    eng_cur, pr_cur = couverture(conn, reference, exclure)
    if not eng_cur or not pr_cur:
        return [], None

    par_jour: dict[str, tuple[int, set]] = {}
    for row in conn.execute(
        "SELECT id, DATE(started_at) AS j FROM runs WHERE client = ? ORDER BY id", (client,)
    ):
        engines, prompts = couverture(conn, row["id"], exclure)
        commun = engines & eng_cur
        if pr_cur <= prompts and len(commun) >= plancher_moteurs(min(len(engines), len(eng_cur))):
            par_jour[row["j"]] = (row["id"], engines)
    if not par_jour:
        return [], None

    eng_serie = set(eng_cur)
    for _, engines in par_jour.values():
        eng_serie &= engines
    # Le plancher vaut aussi pour la courbe entière : une série qui ne
    # mesurerait qu'un ou deux moteurs communs se présenterait comme LA
    # courbe de visibilité en n'étant que celle d'un moteur.
    if len(eng_serie) < 3:
        return [], None

    points = []
    for jour in sorted(par_jour):
        run_id, _ = par_jour[jour]
        t = taux_commun(conn, run_id, eng_serie, pr_cur)
        if t["rate"] is not None:
            points.append({"date": jour, "run": run_id, "taux": t["rate"],
                           "rang": t["avg_rank"]})
    ctx = {"n_moteurs": len(eng_serie), "n_requetes": len(pr_cur),
           "reduit": eng_serie < eng_cur}
    return points, ctx


def report_run(conn, run_id: int, comp: dict | None) -> None:
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        print(f"Run #{run_id} introuvable.")
        return

    current = run_summary(conn, run_id)                       # axe visibilité
    total = run_summary(conn, run_id, avec_memoire=True)      # totaux de collecte

    print(f"\n# Run #{run_id} — {meta['client']} — {meta['started_at']}")
    print(f"Set de requêtes v{meta['set_version']}")

    # Le delta vit sur SA ligne, avec SON périmètre (règle du 05/08), et le
    # taux de visibilité porte le sien : moteurs avec recherche web seulement,
    # la mémoire de marque est un axe à part (correction du 05/08).
    print("\n## Vue d'ensemble")
    # « non exploitables », pas « erreurs » : le compte inclut aussi les
    # réponses vides sans erreur (pas d'AI Overview affiché), exclues du
    # taux comme les échecs depuis le 08/08/2026.
    print(f"  Appels exploitables   : {total['ok']}/{total['n']}"
          + (f"  ⚠️ {total['errors']} non exploitables (erreur ou réponse vide)"
             if total["errors"] else ""))
    print(f"  Taux de visibilité    : {_pct(current['cited'], current['ok'])}  "
          f"(moteurs avec recherche web : {current['cited']}/{current['ok']})")
    if comp:
        a = taux_commun(conn, run_id, comp["engines"], comp["prompts"])
        b = taux_commun(conn, comp["prev_id"], comp["engines"], comp["prompts"])
        print(f"  Évolution             : {_delta(a['rate'], b['rate']) or 'n/a'}  "
              f"(périmètre commun avec le run #{comp['prev_id']} : "
              f"{len(comp['engines'])} moteurs, {len(comp['prompts'])} requêtes)")
    else:
        print("  Évolution             : aucune collecte antérieure comparable")
    if current["avg_rank"]:
        print(f"  Rang moyen en source  : {current['avg_rank']:.1f}")
    if current["avg_position"] is not None:
        print(f"  Position dans le texte: {current['avg_position']:.2f}  "
              "(0 = tout en haut, 1 = tout en bas)")

    print("\n## Par moteur")
    rows = conn.execute(
        f"""
        SELECT engine_id, search_enabled,
               COUNT(*) AS n,
               SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
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

    print("\n## Par requête  (cité / appels réussis, moteurs avec recherche)")
    rows = conn.execute(
        f"""
        SELECT prompt_id, prompt_text,
               SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END) AS ok,
               SUM(COALESCE(cited, 0)) AS cited
        FROM responses WHERE run_id = ? AND search_enabled=1
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


def report_serie(conn, client: str, exclure=()) -> None:
    print(f"\n# Série temporelle — {client}")
    print("C'est ÇA le livrable. Le reste n'est que de la présentation.\n")
    points, ctx = serie_commune(conn, client, exclure)
    if not points:
        print("Aucune collecte complète pour ce client : la série démarre à la première "
              "collecte couvrant toutes les requêtes titulaires.")
        return
    print(f"Périmètre constant : {ctx['n_moteurs']} moteurs communs, "
          f"{ctx['n_requetes']} requêtes titulaires."
          + (" (des moteurs plus récents sont hors courbe tant qu'une vieille"
             " collecte ne les a pas)" if ctx["reduit"] else ""))
    total = conn.execute(
        "SELECT COUNT(*) n FROM runs WHERE client = ?", (client,)
    ).fetchone()["n"]
    print(f"  {'date':<12} {'collecte':>8}  {'citation':>9}  {'rang moy':>9}")
    for p in points:
        rank = f"{p['rang']:.1f}" if p["rang"] else "-"
        print(f"  {p['date']:<12} #{p['run']:<7}  {p['taux']:>7.0f} %  {rank:>9}")
    ecartees = total - len(points)
    if ecartees:
        print(f"  ({ecartees} collecte(s) écartée(s) : périmètre non comparable, "
              "tests ou collectes partielles)")


def exclusions_client(client: str) -> frozenset:
    """Ids des requêtes « en observation », tenues hors de toute comparaison.
    Une config illisible ARRÊTE le rapport : un chiffre calculé sans les
    statuts serait faux en silence."""
    try:
        cfg = load_client(client)
    except FileNotFoundError:
        raise SystemExit(f"Client '{client}' sans fichier de configuration : rapport annulé.")
    except Exception as exc:
        raise SystemExit(f"Configuration '{client}' illisible ({exc}) : rapport annulé "
                         "plutôt que faux.")
    return frozenset(p.id for p in cfg.prompts if p.statut == "observation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tracker GEO : rapports.")
    parser.add_argument("--client", default="smart-bpjeps")
    parser.add_argument("--run", type=int, help="id du run (défaut : le dernier)")
    parser.add_argument("--serie", action="store_true", help="la courbe, tous runs")
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    args = parser.parse_args(argv)

    load_dotenv()
    conn = db.connect(args.db)
    exclure = exclusions_client(args.client)

    if args.serie:
        report_serie(conn, args.client, exclure)
        return 0

    dernier = conn.execute(
        "SELECT id FROM runs WHERE client = ? ORDER BY id DESC LIMIT 1", (args.client,)
    ).fetchone()
    if dernier is None:
        print("Aucun run enregistré. Lance : python -m geotracker.run")
        return 1

    run_id = args.run or dernier["id"]
    comp = collecte_comparable(conn, run_id, args.client, exclure)
    report_run(conn, run_id, comp)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
