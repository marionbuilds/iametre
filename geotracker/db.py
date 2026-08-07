"""Stockage. Règle non négociable (TRACKER-GEO.md §7) : on garde le BRUT.

Les agrégats se recalculent, une réponse perdue ne se rattrape pas. Toute la
valeur du projet est dans l'accumulation de `responses.raw_json`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "runs.sqlite3"

# Un appel EXPLOITABLE : pas d'erreur ET une réponse non vide. Une réponse
# vide sans erreur (Google qui n'affiche pas d'AI Overview sur la requête)
# n'est PAS une non-citation : il n'y a pas eu de réponse où être citée.
# Elle est donc exclue du taux, comme les appels en échec — même logique,
# décision Marion du 08/08/2026 (passe 7 : 5 cas réels en base, dont 2 dans
# le run #15, faisaient baisser le taux à cause d'un comportement de Google
# sans rapport avec la visibilité). TOUT dénominateur du produit interpole
# cette définition — report, dashboard, faits, attributs : si elle change,
# tout change ensemble, aucun module ne peut diverger.
EXPLOITABLE = "(error IS NULL AND answer_text IS NOT NULL AND answer_text <> '')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client       TEXT NOT NULL,
    set_version  INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS responses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    client         TEXT NOT NULL,
    set_version    INTEGER NOT NULL,
    prompt_id      TEXT NOT NULL,
    prompt_text    TEXT NOT NULL,
    prompt_type    TEXT,
    engine_id      TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT,
    search_enabled INTEGER NOT NULL,
    repetition     INTEGER NOT NULL,
    requested_at   TEXT NOT NULL,
    latency_ms     INTEGER,
    error          TEXT,
    answer_text    TEXT,
    raw_json       TEXT,
    usage_json     TEXT,
    -- métriques dérivées, recalculables à tout moment depuis raw_json
    cited          INTEGER,
    cited_in_text  INTEGER,
    source_rank    INTEGER,
    text_position  REAL,
    n_sources      INTEGER
);

CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id  INTEGER NOT NULL REFERENCES responses(id),
    rank         INTEGER NOT NULL,
    url          TEXT,
    domain       TEXT,
    title        TEXT,
    is_target    INTEGER NOT NULL DEFAULT 0,
    competitor   TEXT
);

CREATE INDEX IF NOT EXISTS idx_responses_run     ON responses(run_id);
CREATE INDEX IF NOT EXISTS idx_responses_lookup  ON responses(client, prompt_id, engine_id);
CREATE INDEX IF NOT EXISTS idx_sources_response  ON sources(response_id);
CREATE INDEX IF NOT EXISTS idx_sources_domain    ON sources(domain);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def start_run(conn: sqlite3.Connection, client: str, set_version: int, note: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO runs (client, set_version, started_at, note) VALUES (?, ?, ?, ?)",
        (client, set_version, now_iso(), note),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE runs SET finished_at = ? WHERE id = ?", (now_iso(), run_id))
    conn.commit()


def save_response(conn: sqlite3.Connection, run_id: int, record: dict, sources: list[dict]) -> int:
    """Écrit une réponse et ses sources, puis commit immédiatement.

    Le commit par réponse est volontaire : si le run plante à la requête 200,
    les 199 premières sont déjà sur disque.
    """
    cur = conn.execute(
        """
        INSERT INTO responses (
            run_id, client, set_version, prompt_id, prompt_text, prompt_type,
            engine_id, provider, model, search_enabled, repetition,
            requested_at, latency_ms, error, answer_text, raw_json, usage_json,
            cited, cited_in_text, source_rank, text_position, n_sources
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            record["client"],
            record["set_version"],
            record["prompt_id"],
            record["prompt_text"],
            record.get("prompt_type"),
            record["engine_id"],
            record["provider"],
            record.get("model"),
            int(record["search_enabled"]),
            record["repetition"],
            record["requested_at"],
            record.get("latency_ms"),
            record.get("error"),
            record.get("answer_text"),
            json.dumps(record.get("raw"), ensure_ascii=False, default=str),
            json.dumps(record.get("usage"), ensure_ascii=False, default=str)
            if record.get("usage")
            else None,
            _as_int(record.get("cited")),
            _as_int(record.get("cited_in_text")),
            record.get("source_rank"),
            record.get("text_position"),
            record.get("n_sources"),
        ),
    )
    response_id = cur.lastrowid

    for source in sources:
        conn.execute(
            """
            INSERT INTO sources (response_id, rank, url, domain, title, is_target, competitor)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                response_id,
                source["rank"],
                source.get("url"),
                source.get("domain"),
                source.get("title"),
                int(bool(source.get("is_target"))),
                source.get("competitor"),
            ),
        )
    conn.commit()
    return response_id


def _as_int(value):
    return None if value is None else int(bool(value))
