"""Lance un run complet : prompts x moteurs x répétitions.

    python -m geotracker.run --client smart-bpjeps
    python -m geotracker.run --client smart-bpjeps --engines perplexity --prompts 2
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db
from .config import ROOT, Engine, load_client
from .engines import get_engine, required_env
from .extract import analyse


# Un seul trousseau pour TOUS les projets de Marion, à la racine de Smart BPJEPS.
# Volontairement HORS du dépôt Git du tracker : les clés ne peuvent donc pas
# être commitées ici par accident.
TROUSSEAU = ROOT.parent.parent / "trousseau.env"
PLACEHOLDER = "<À FOURNIR"


def load_dotenv(path: Path | None = None) -> Path | None:
    """Charge le trousseau sans dépendance externe.

    N'écrase JAMAIS une variable déjà présente : sur GitHub Actions ce sont les
    secrets du dépôt qui doivent gagner. En local, c'est `trousseau.env`.
    Un chemin explicite peut être imposé via la variable TROUSSEAU_PATH.
    """
    candidates = [
        Path(os.environ["TROUSSEAU_PATH"]) if os.environ.get("TROUSSEAU_PATH") else None,
        path,
        TROUSSEAU,
        ROOT / ".env",  # repli, non recommandé : on ne veut qu'UN fichier de clés
    ]
    source = next((p for p in candidates if p and p.exists()), None)
    if source is None:
        return None

    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Une valeur encore à remplir ne doit pas passer pour une vraie clé.
        if key and value and not value.startswith(PLACEHOLDER) and key not in os.environ:
            os.environ[key] = value
    return source


def usable_engines(config, only: list[str] | None) -> tuple[list[Engine], list[str]]:
    """Sépare les moteurs exploitables de ceux qu'on doit sauter, avec la raison."""
    selected, skipped = [], []
    for engine in config.engines:
        if only and engine.id not in only and engine.provider not in only:
            continue
        if not engine.enabled:
            skipped.append(f"{engine.id} : désactivé dans le YAML")
            continue
        missing = [n for n in required_env(engine.provider) if not os.environ.get(n)]
        if missing:
            skipped.append(f"{engine.id} : clé manquante ({', '.join(missing)})")
            continue
        selected.append(engine)
    return selected, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tracker GEO : lance un run.")
    parser.add_argument("--client", default="smart-bpjeps")
    parser.add_argument("--engines", help="liste séparée par des virgules")
    parser.add_argument("--prompts", type=int, help="ne prendre que les N premières requêtes")
    parser.add_argument("--repetitions", type=int, help="forcer le nombre de répétitions")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    parser.add_argument("--note", default="")
    parser.add_argument("--dry-run", action="store_true", help="n'appelle rien, montre le plan")
    parser.add_argument("--sauf-si-recente", type=int, metavar="JOURS",
                        help="ne rien lancer si une collecte du client date de moins de JOURS jours")
    args = parser.parse_args(argv)

    # Garde-fou anti-doublon (Marion, 29/07/2026) : la mesure d'impact après
    # publication ne doit pas payer une collecte qui vient d'avoir lieu (le
    # cron du lundi, par exemple). Sauter n'est PAS un échec : code retour 0.
    if args.sauf_si_recente:
        conn = db.connect(args.db)
        row = conn.execute("SELECT MAX(started_at) AS m FROM runs WHERE client = ?",
                           (args.client,)).fetchone()
        conn.close()
        if row and row["m"]:
            age = (datetime.now(timezone.utc).date() - date.fromisoformat(row["m"][:10])).days
            if age < args.sauf_si_recente:
                print(f"⏭  Collecte sautée : la dernière ({row['m'][:10]}) date d'il y a "
                      f"{age} jour(s), seuil fixé à {args.sauf_si_recente}. "
                      f"Rien n'a été appelé, rien n'a été payé.")
                return 0

    source = load_dotenv()
    config = load_client(args.client)
    only = [e.strip() for e in args.engines.split(",")] if args.engines else None
    engines, skipped = usable_engines(config, only)

    prompts = config.prompts[: args.prompts] if args.prompts else config.prompts

    print(f"Trousseau     : {source if source else 'aucun (secrets d environnement seuls)'}")

    tasks = []
    for prompt in prompts:
        for engine in engines:
            repetitions = args.repetitions or config.repetitions_for(engine)
            for repetition in range(1, repetitions + 1):
                tasks.append((prompt, engine, repetition))

    print(f"Client        : {config.label} (set v{config.set_version})")
    print(f"Requêtes      : {len(prompts)}")
    print(f"Moteurs       : {', '.join(e.id for e in engines) or 'AUCUN'}")
    for reason in skipped:
        print(f"  ⏭  sauté  {reason}")
    print(f"Appels prévus : {len(tasks)}")

    if not engines:
        print(
            f"\n❌ Aucun moteur utilisable.\n"
            f"   Renseigne les clés dans le trousseau commun : {TROUSSEAU}\n"
            f"   (section « 📡 PARTIE TRACKER GEO », tout en bas du fichier)"
        )
        return 1
    if args.dry_run:
        print("\n(dry-run : rien n'a été appelé)")
        return 0

    conn = db.connect(args.db)
    run_id = db.start_run(conn, config.client, config.set_version, args.note)
    print(f"Run #{run_id} -> {args.db}\n")

    def call(task):
        prompt, engine, repetition = task
        response = get_engine(engine.provider)(prompt.text, engine, config)
        return prompt, engine, repetition, response

    done = 0
    errors = 0
    cited = 0

    # Les appels réseau partent en parallèle, mais l'écriture SQLite reste
    # dans le thread principal : un seul écrivain, aucun verrou à gérer.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for prompt, engine, repetition, response in pool.map(call, tasks):
            metrics, sources = analyse(response, config)
            db.save_response(
                conn,
                run_id,
                {
                    "client": config.client,
                    "set_version": config.set_version,
                    "prompt_id": prompt.id,
                    "prompt_text": prompt.text,
                    "prompt_type": prompt.type,
                    "engine_id": engine.id,
                    "provider": response.provider,
                    "model": response.model,
                    "search_enabled": response.search_enabled,
                    "repetition": repetition,
                    "requested_at": db.now_iso(),
                    "latency_ms": response.latency_ms,
                    "error": response.error,
                    "answer_text": response.answer_text,
                    "raw": response.raw,
                    "usage": response.usage,
                    **metrics,
                },
                sources,
            )
            done += 1
            errors += 1 if response.error else 0
            cited += 1 if metrics["cited"] else 0
            flag = "❌" if response.error else ("✅" if metrics["cited"] else "· ")
            print(
                f"[{done:>4}/{len(tasks)}] {flag} {prompt.id} {engine.id:<18} "
                f"{metrics['n_sources']:>2} sources"
                + (f"  rang {metrics['source_rank']}" if metrics["source_rank"] else "")
                + (f"  {response.error[:60]}" if response.error else "")
            )

    db.finish_run(conn, run_id)
    conn.close()

    rate = (cited / done * 100) if done else 0
    print(f"\nRun #{run_id} terminé : {done} appels, {errors} erreurs.")
    print(f"Taux de citation brut : {cited}/{done} ({rate:.1f} %)")
    print(f"Rapport : python -m geotracker.report --run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
