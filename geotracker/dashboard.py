"""Génère l'interface d'IAmètre à partir des données collectées.

    python -m geotracker.dashboard              # dernière collecte
    python -m geotracker.dashboard --run 13

Le fichier produit s'ouvre d'un double-clic et se régénère à chaque collecte.

PRINCIPE DE L'ÉCRAN (design validé par Marion le 29/07/2026)
Ce n'est pas un rapport, c'est un poste de pilotage. L'écran raconte cinq
actes : où j'en suis → quoi faire maintenant → qui me menace → ce qui marche
→ où on me trouve. Une seule action est mise en avant et tout le reste reste
sobre : trois sujets présentés à égalité, c'est zéro article écrit.

⚠️ RÈGLE ABSOLUE : aucun chiffre inventé.
La maquette d'origine affichait une variation, une série de collectes et un
impact estimé qui étaient des remplissages. Ici chaque valeur est calculée
depuis la base, et **tout indicateur sans données est masqué** plutôt
qu'inventé. Un instrument de mesure qui affiche un faux chiffre ne vaut rien,
et c'est encore plus vrai le jour où on le montre en entretien.
"""

from __future__ import annotations

import argparse
import html
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .config import ROOT, clients_disponibles, load_client, load_produit
from .report import run_summary

SORTIE = ROOT / "reports" / "dashboard.html"
SEUIL_TROU = 25.0

NOMS_MOTEURS = {
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "anthropic-memory": "Claude · mémoire de marque",
    "ai_overview": "Google AI Overviews",
}


# --------------------------------------------------------------------- données

def _perimetre(conn, run_id: int) -> tuple[int, str]:
    """Signature d'une collecte : nombre de requêtes + moteurs interrogés.
    Deux collectes ne sont comparables que si leur périmètre est identique,
    sinon un « +3 points » ne voudrait strictement rien dire."""
    r = conn.execute(
        """SELECT COUNT(DISTINCT prompt_id) p, GROUP_CONCAT(DISTINCT engine_id) e
           FROM responses WHERE run_id=?""",
        (run_id,),
    ).fetchone()
    return r["p"] or 0, r["e"] or ""


def collecte(conn, run_id: int) -> dict:
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        raise SystemExit(f"Collecte #{run_id} introuvable.")
    resume = run_summary(conn, run_id)

    moteurs = sorted(
        (
            dict(
                id=r["engine_id"], recherche=bool(r["search_enabled"]),
                ok=r["ok"] or 0, cites=r["cited"] or 0,
                taux=(r["cited"] or 0) / r["ok"] * 100 if r["ok"] else 0,
                rang=r["avg_rank"],
            )
            for r in conn.execute(
                """SELECT engine_id, search_enabled,
                          SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
                          SUM(COALESCE(cited,0)) AS cited, AVG(source_rank) AS avg_rank
                   FROM responses WHERE run_id=? GROUP BY engine_id""",
                (run_id,),
            ).fetchall()
        ),
        key=lambda m: m["taux"], reverse=True,
    )

    requetes = sorted(
        (
            dict(
                id=r["prompt_id"], texte=r["prompt_text"], type=r["prompt_type"] or "",
                ok=r["ok"] or 0, cites=r["cited"] or 0,
                taux=(r["cited"] or 0) / r["ok"] * 100 if r["ok"] else 0,
            )
            for r in conn.execute(
                """SELECT prompt_id, prompt_text, MAX(prompt_type) AS prompt_type,
                          SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
                          SUM(COALESCE(cited,0)) AS cited
                   FROM responses WHERE run_id=? GROUP BY prompt_id""",
                (run_id,),
            ).fetchall()
        ),
        key=lambda q: q["taux"], reverse=True,
    )

    total = conn.execute(
        """SELECT COUNT(*) n FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''""",
        (run_id,),
    ).fetchone()["n"] or 1
    distincts = conn.execute(
        """SELECT COUNT(DISTINCT s.domain) n FROM sources s JOIN responses r ON r.id=s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''""",
        (run_id,),
    ).fetchone()["n"]
    voix = [
        dict(domaine=r["domain"], label=r["label"], moi=bool(r["moi"]), n=r["n"],
             part=r["n"] / total * 100, rang=r["rang"])
        for r in conn.execute(
            """SELECT s.domain, MAX(s.is_target) AS moi, MAX(s.competitor) AS label,
                      COUNT(*) AS n, AVG(s.rank) AS rang
               FROM sources s JOIN responses r ON r.id=s.response_id
               WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''
               GROUP BY s.domain ORDER BY n DESC LIMIT 8""",
            (run_id,),
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

    # Comparaison avec la collecte précédente DE MÊME PÉRIMÈTRE uniquement.
    signature = _perimetre(conn, run_id)
    precedent = None
    for r in conn.execute(
        "SELECT id FROM runs WHERE client=? AND id<? ORDER BY id DESC", (meta["client"], run_id)
    ).fetchall():
        if _perimetre(conn, r["id"]) == signature:
            precedent = r["id"]
            break
    delta = None
    if precedent is not None:
        avant = run_summary(conn, precedent)["rate"]
        if avant is not None and resume["rate"] is not None:
            delta = resume["rate"] - avant

    historique = []
    for r in conn.execute(
        "SELECT id, started_at, note FROM runs WHERE client=? ORDER BY id DESC LIMIT 25",
        (meta["client"],),
    ).fetchall():
        s = run_summary(conn, r["id"])
        if s["n"]:
            historique.append(dict(id=r["id"], date=r["started_at"][:16].replace("T", " à "),
                                   note=r["note"] or "", n=s["n"], erreurs=s["errors"],
                                   taux=s["rate"]))

    # Série : un point par JOUR, et seulement les collectes de même périmètre.
    serie = []
    for ligne in conn.execute(
        """SELECT DATE(started_at) j, MAX(id) dernier FROM runs
           WHERE client=? GROUP BY DATE(started_at) ORDER BY j""",
        (meta["client"],),
    ).fetchall():
        if _perimetre(conn, ligne["dernier"]) != signature:
            continue
        t = run_summary(conn, ligne["dernier"])["rate"]
        if t is not None:
            serie.append(dict(date=ligne["j"], taux=t))

    try:
        cfg = load_client(meta["client"])
        etiquette, set_version, n_conc = cfg.label, cfg.set_version, len(cfg.competitors)
    except Exception:
        etiquette, set_version, n_conc = meta["client"], meta["set_version"], 0

    return {
        "run_id": run_id, "client": meta["client"], "client_label": etiquette,
        "clients": clients_disponibles(), "set_version": set_version, "n_concurrents": n_conc,
        "date": meta["started_at"][:10], "resume": resume, "moteurs": moteurs,
        "requetes": requetes, "voix": voix, "occupants": occupants,
        "total_citations": total, "domaines_distincts": distincts,
        "historique": historique, "serie": serie, "delta": delta,
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


def _objectif(taux: float) -> tuple[int, float]:
    palier = min(100, (int(taux // 10) + 1) * 10)
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
        return ("Le moteur le plus favorable, et de loin." if meilleur - pire > 20
                else "Le moteur le plus favorable.")
    if m["rang"] and rangs and m["rang"] <= min(rangs):
        return "Le plus dur à percer, mais la meilleure place quand la marque y est."
    if m["taux"] <= pire:
        return "Le plus difficile à percer."
    return f"Bien placée quand la marque y est, rang {_nb(m['rang'])}." if m["rang"] else ""


def _diagnostic(q: dict) -> str:
    """Un pourcentage ne fait rien ressentir. « 1 réponse sur 14 », si."""
    if q["taux"] < 1:
        return "Aucun domaine ne s'impose : personne n'est cité parce qu'il n'y a rien à citer."
    sur = max(2, round(q["ok"] / max(q["cites"], 1)))
    if q["taux"] < 10:
        return f"La question est posée, mais la marque n'apparaît que dans 1 réponse sur {sur}."
    return f"Sujet au cœur de l'offre, et la marque n'apparaît que dans 1 réponse sur {sur}."


def _prochaine_collecte() -> str:
    """Le cron tourne le lundi à 06h00 UTC (.github/workflows/weekly.yml)."""
    maintenant = datetime.now(timezone.utc)
    jours = (7 - maintenant.weekday()) % 7 or 7
    return ("Prochaine collecte demain, lundi." if jours == 1
            else f"Prochaine collecte dans {jours} jours, lundi.")


# ---------------------------------------------------------------------- rendu

def _nb(x, dec: int = 1) -> str:
    """Nombre à la française : virgule décimale. « 10.6 » est une faute en
    français, et ça saute aux yeux sur un produit qui vise ce marché."""
    return f"{x:.{dec}f}".replace(".", ",")


def _cite(texte: str) -> str:
    """Guillemets français avec espaces fines insécables : évite le guillemet
    fermant orphelin en bas de ligne, et respecte la typographie française."""
    fine = "&#8239;"
    return f"«{fine}{_e(texte)}{fine}»"


def _e(v) -> str:
    return html.escape(str(v), quote=True)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --ink:#0E1420; --ink-soft:rgba(14,20,32,.62); --ink-faint:rgba(14,20,32,.40);
  --bg:#F2F4F8; --paper:#FFFFFF; --line:rgba(14,20,32,.08);
  --signal:#2650F0; --signal-soft:#E8EDFE;
  --alert:#D9482B; --ok:#178A50; --ok-soft:#E6F5EC;
  --opp:#8A6100; --opp-soft:#FFF3D6; --piste:#EDF0F6; --r:16px;
  --f-display:system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-body:system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ink:#EEF1F6; --ink-soft:rgba(238,241,246,.62); --ink-faint:rgba(238,241,246,.38);
  --bg:#0B0D12; --paper:#141821; --line:rgba(255,255,255,.09);
  --signal:#5B84FF; --signal-soft:rgba(91,132,255,.14);
  --alert:#F2704F; --ok:#3FC57F; --ok-soft:rgba(63,197,127,.14);
  --opp:#E0A72E; --opp-soft:rgba(224,167,46,.13); --piste:#1E232E;
}}
:root[data-theme="dark"]{
  --ink:#EEF1F6; --ink-soft:rgba(238,241,246,.62); --ink-faint:rgba(238,241,246,.38);
  --bg:#0B0D12; --paper:#141821; --line:rgba(255,255,255,.09);
  --signal:#5B84FF; --signal-soft:rgba(91,132,255,.14);
  --alert:#F2704F; --ok:#3FC57F; --ok-soft:rgba(63,197,127,.14);
  --opp:#E0A72E; --opp-soft:rgba(224,167,46,.13); --piste:#1E232E;
}
body{font-family:var(--f-body); background:var(--bg); color:var(--ink); line-height:1.55;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px; margin:0 auto; padding:28px 24px 80px}

.topbar{display:flex; align-items:center; justify-content:space-between; gap:16px;
  margin-bottom:26px; flex-wrap:wrap}
.brand{display:flex; align-items:center; gap:12px}
.brand__mark{width:38px; height:38px; border-radius:10px; background:var(--ink);
  display:grid; place-items:center; flex:none}
.brand__name{font-family:var(--f-display); font-weight:700; font-size:1.15rem; letter-spacing:-.01em}
.brand__sub{font-size:.78rem; color:var(--ink-soft)}
.topbar__meta{display:flex; align-items:center; gap:8px; flex-wrap:wrap}
.chip{font-size:.78rem; font-weight:600; padding:6px 12px; border-radius:999px;
  background:var(--paper); border:1px solid var(--line); color:var(--ink)}
button.chip{cursor:pointer; font-family:inherit}
button.chip[aria-selected="true"]{background:var(--ink); color:var(--paper); border-color:transparent}
.chip:focus-visible{outline:3px solid var(--signal); outline-offset:2px}

.hero{background:var(--paper); border:1px solid var(--line); border-radius:22px;
  padding:30px 32px; display:grid; grid-template-columns:auto 1fr auto; gap:36px;
  align-items:center; margin-bottom:18px}
.gauge{position:relative; width:210px}
.gauge svg{display:block; width:100%; height:auto}
.gauge__value{position:absolute; left:0; right:0; top:58%; text-align:center;
  font-family:var(--f-mono); font-weight:700; font-size:2.9rem; letter-spacing:-.04em; line-height:1}
.gauge__value small{font-size:1.1rem; font-weight:600; color:var(--ink-soft)}
.eyebrow{font-size:.7rem; font-weight:700; color:var(--ink-faint);
  text-transform:uppercase; letter-spacing:.12em; margin-bottom:10px}
.hero__mid h1{font-family:var(--f-display); font-weight:700; font-size:1.45rem;
  letter-spacing:-.02em; line-height:1.25; margin-bottom:6px}
.hero__mid p{color:var(--ink-soft); font-size:.92rem; max-width:50ch}
.hero__mid p strong{color:var(--ink)}
.delta{display:inline-flex; align-items:center; gap:5px; font-family:var(--f-mono);
  font-weight:600; font-size:.85rem; border-radius:8px; padding:3px 9px; margin-left:8px}
.delta--up{color:var(--ok); background:var(--ok-soft)}
.delta--down{color:var(--alert); background:var(--opp-soft)}
.ruler{margin-top:18px}
.ruler__track{position:relative; height:26px; border-radius:7px; background:var(--piste)}
.ruler__ticks{position:absolute; inset:0; border-radius:7px; overflow:hidden;
  background:repeating-linear-gradient(90deg,rgba(127,140,160,.30) 0 1px,transparent 1px 10%)}
.ruler__fill{position:absolute; top:0; bottom:0; left:0;
  background:linear-gradient(90deg,#3B63F4,var(--signal)); border-radius:7px 0 0 7px}
.ruler__goal{position:absolute; top:-6px; bottom:-6px; width:2px; background:var(--ink)}
.ruler__goal span{position:absolute; top:-24px; left:-20px; font-family:var(--f-mono);
  font-size:.72rem; font-weight:600; white-space:nowrap; background:var(--ink);
  color:var(--paper); padding:2px 7px; border-radius:6px}
.ruler__caption{display:flex; justify-content:space-between; font-size:.78rem;
  color:var(--ink-soft); margin-top:10px; gap:12px; flex-wrap:wrap}
.ruler__caption strong{color:var(--ink)}
.hero__side{display:grid; gap:14px; min-width:190px}
.stat{border-left:2px solid var(--line); padding-left:14px}
.stat__num{font-family:var(--f-mono); font-weight:700; font-size:1.35rem; letter-spacing:-.02em}
.stat__lbl{font-size:.76rem; color:var(--ink-soft)}
.stat--crown .stat__num{color:var(--signal)}

.mission{border-radius:22px; border:1px solid rgba(138,97,0,.28); background:var(--opp-soft);
  padding:26px 30px; margin-bottom:18px; display:grid; grid-template-columns:1fr auto;
  gap:24px; align-items:center}
.mission__eyebrow{display:flex; align-items:center; gap:8px; font-size:.72rem; font-weight:700;
  text-transform:uppercase; letter-spacing:.12em; color:var(--opp); margin-bottom:8px}
.mission__eyebrow::before{content:""; width:8px; height:8px; border-radius:50%; background:var(--opp)}
.mission h2{font-family:var(--f-display); font-weight:700; font-size:1.32rem;
  letter-spacing:-.02em; margin-bottom:8px; line-height:1.3}
.mission p{font-size:.92rem; color:var(--ink-soft); max-width:64ch}
.mission p strong{color:var(--ink)}
.mission__side{display:grid; gap:12px; justify-items:end; text-align:right}
.mission__impact{font-family:var(--f-mono); font-weight:700; font-size:1.6rem; color:var(--opp);
  line-height:1}
.mission__impact small{display:block; font-family:var(--f-body); font-weight:600; font-size:.72rem;
  letter-spacing:.06em; text-transform:uppercase; margin-top:4px; opacity:.85}
.btn{display:inline-flex; align-items:center; gap:8px; border:none; cursor:pointer;
  font-family:var(--f-body); font-weight:700; font-size:.9rem; padding:12px 22px;
  border-radius:12px; transition:transform .15s}
.btn--primary{background:var(--ink); color:var(--paper)}
@media(hover:hover){.btn--primary:hover{transform:translateY(-2px)}}
.btn:focus-visible{outline:3px solid var(--signal); outline-offset:2px}

.queue{display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:18px}
.queue__card{background:var(--paper); border:1px solid var(--line); border-radius:var(--r);
  padding:18px 20px; display:flex; gap:18px; align-items:flex-start;
  justify-content:space-between}
.queue__txt{min-width:0}
.queue__txt h3{font-size:.95rem; font-weight:700; margin-bottom:3px}
.queue__txt p{font-size:.82rem; color:var(--ink-soft)}
.queue__rate{font-family:var(--f-mono); font-weight:700; font-size:1.05rem; color:var(--alert);
  white-space:nowrap; flex:none; line-height:1.5}
.queue__rate--warn{color:var(--opp)}

.grid{display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px}
.card{background:var(--paper); border:1px solid var(--line); border-radius:22px; padding:24px 26px}
.card__head{display:flex; align-items:baseline; justify-content:space-between; gap:12px;
  margin-bottom:6px}
.card__head h2{font-family:var(--f-display); font-weight:700; font-size:1.1rem; letter-spacing:-.01em}
.card__hint{font-size:.76rem; color:var(--ink-faint); text-align:right}
.card__lead{font-size:.85rem; color:var(--ink-soft); margin-bottom:16px; max-width:58ch}
.card__lead strong{color:var(--ink)}

.lb{list-style:none}
.lb li{display:grid; grid-template-columns:26px 1fr auto auto; gap:12px; align-items:center;
  padding:11px 10px; border-radius:12px; font-size:.9rem; border-bottom:1px solid var(--line)}
.lb li:last-child{border-bottom:none}
.lb__rank{font-family:var(--f-mono); font-weight:600; font-size:.8rem; color:var(--ink-faint)}
.lb__dom{font-weight:600; overflow-wrap:anywhere}
.lb__dom small{display:block; font-weight:500; font-size:.74rem; color:var(--ink-soft)}
.lb__part{font-family:var(--f-mono); font-weight:700}
.lb__bar{width:88px; height:7px; border-radius:99px; background:var(--piste); overflow:hidden}
.lb__bar i{display:block; height:100%; border-radius:99px; background:var(--ink-faint)}
.lb li.is-you{background:var(--signal-soft); border-bottom-color:transparent}
.lb li.is-you .lb__dom{color:var(--signal)}
.lb li.is-you .lb__bar i{background:var(--signal)}
.lb li.is-chaser .lb__part{color:var(--alert)}
.lb li.is-chaser .lb__bar i{background:var(--alert)}
.lb__gap{grid-column:2/-1; font-size:.78rem; color:var(--alert); font-weight:600; margin-top:-4px}

.st{list-style:none; display:grid; gap:14px}
.st li h3{font-size:.9rem; font-weight:600; margin-bottom:6px; display:flex;
  justify-content:space-between; gap:12px}
.st li h3 span{font-family:var(--f-mono); font-weight:700; color:var(--ok)}
.st__bar{height:8px; border-radius:99px; background:var(--piste); overflow:hidden}
.st__bar i{display:block; height:100%; border-radius:99px; background:var(--ok)}

.engines{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px}
.eng{background:var(--paper); border:1px solid var(--line); border-radius:var(--r); padding:18px 20px}
.eng h3{font-size:.9rem; font-weight:700; margin-bottom:2px}
.eng__rate{font-family:var(--f-mono); font-weight:700; font-size:1.7rem; letter-spacing:-.03em;
  margin-bottom:8px}
.eng__bar{height:7px; border-radius:99px; background:var(--piste); overflow:hidden; margin-bottom:10px}
.eng__bar i{display:block; height:100%; background:var(--signal); border-radius:99px}
.eng p{font-size:.79rem; color:var(--ink-soft); line-height:1.5}
.eng--zero .eng__rate{color:var(--ink-faint)}
.eng--zero .eng__bar i{background:var(--ink-faint)}
.eng__tag{display:inline-block; font-size:.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.08em; padding:3px 8px; border-radius:6px; margin-top:10px}
.eng__tag--goal{background:var(--opp-soft); color:var(--opp)}
.eng__tag--best{background:var(--ok-soft); color:var(--ok)}

.foot{display:flex; align-items:center; justify-content:space-between; gap:16px;
  background:var(--paper); border:1px solid var(--line); border-radius:var(--r);
  padding:16px 22px; font-size:.84rem; color:var(--ink-soft); flex-wrap:wrap}
.foot strong{color:var(--ink)}
.foot__spark{display:flex; align-items:flex-end; gap:3px; height:26px}
.foot__spark i{width:7px; border-radius:2px; background:var(--signal-soft)}
.foot__spark i.on{background:var(--signal)}

.tw{overflow-x:auto}
table.d{border-collapse:collapse; width:100%; font-size:.86rem}
table.d th,table.d td{text-align:left; padding:10px 14px; border-bottom:1px solid var(--line)}
table.d th{font-size:.7rem; font-weight:700; color:var(--ink-faint); letter-spacing:.07em;
  text-transform:uppercase; white-space:nowrap}
table.d td.n{font-family:var(--f-mono); white-space:nowrap}
table.d tr:last-child td{border-bottom:none}

[hidden]{display:none!important}
@media(max-width:960px){
  .hero{grid-template-columns:1fr; text-align:center}
  .gauge{margin:0 auto}
  .hero__side{grid-template-columns:repeat(3,1fr); min-width:0}
  .stat{border-left:none; border-top:2px solid var(--line); padding:10px 0 0}
  .engines{grid-template-columns:repeat(2,1fr)}
  .grid,.queue{grid-template-columns:1fr}
  .mission{grid-template-columns:1fr}
  .mission__side{justify-items:start; text-align:left}
}
@media(max-width:560px){
  .wrap{padding:18px 14px 60px}
  .hero,.mission,.card{padding:20px}
  .engines,.hero__side{grid-template-columns:1fr}
  .lb li{grid-template-columns:22px 1fr auto}
  .lb__bar{display:none}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  document.querySelectorAll('[data-brief]').forEach(function(b){
    b.addEventListener('click',function(){
      var self=this, texte=this.getAttribute('data-brief'), avant=this.textContent;
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(texte).then(function(){
          self.textContent='Brief copié';
          setTimeout(function(){self.textContent=avant;},1800);
        });
      }
    });
  });
  var nav=[].slice.call(document.querySelectorAll('.nav'));
  nav.forEach(function(o){o.addEventListener('click',function(){
    nav.forEach(function(x){
      var actif=x===o;
      x.setAttribute('aria-selected',actif?'true':'false');
      document.getElementById(x.getAttribute('aria-controls')).hidden=!actif;
    });
  });});
})();
"""


def _brief(q: dict, d: dict) -> str:
    """Le bouton copie un VRAI brief de contenu, pas un texte décoratif :
    la question, l'état mesuré, qui occupe le terrain, l'impact attendu."""
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
        f"+{_nb(_impact(q, d['requetes'], d['resume']))} points de taux de citation global.",
    ]
    return "\n".join(lignes)


def _vue_resultats(d: dict) -> str:
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

    if d["delta"] is None:
        badge = ""
        phrase = "Première collecte de ce périmètre : la courbe démarre ici."
    else:
        haut = d["delta"] >= 0
        badge = (f'<span class="delta delta--{"up" if haut else "down"}">'
                 f'{"▲" if haut else "▼"} {_nb(abs(d["delta"]))} pts</span>')
        phrase = f"{'▲' if haut else '▼'} {_nb(abs(d['delta']))} points depuis la collecte précédente."

    reste_txt = f"<strong>+{reste:.0f} pts restants</strong>"
    if contenus:
        reste_txt += f" · <strong>~{contenus} contenu{'s' if contenus > 1 else ''}</strong>"

    mission, cible = "", None
    if trous:
        cible = max(trous, key=lambda q: _impact(q, d["requetes"], r))
        occ = d["occupants"].get(cible["id"], [])
        contexte = (f"Le terrain est occupé par {', '.join(occ[:3])}." if occ
                    else "Aucun domaine ne s'impose : le terrain est libre.")
        mission = f"""
  <section class="mission">
    <div>
      <div class="mission__eyebrow">Ta prochaine action · opportunité n°1</div>
      <h2>{_cite(cible['texte'])}</h2>
      <p>{_e(_diagnostic(cible))} {_e(contexte)}
      <strong>C'est le sujet où un contenu rapporterait le plus.</strong></p>
    </div>
    <div class="mission__side">
      <div class="mission__impact">+{_nb(_impact(cible, d["requetes"], r))} pts<small>impact estimé</small></div>
      <button class="btn btn--primary" data-brief="{_e(_brief(cible, d))}">Copier le brief</button>
    </div>
  </section>"""

    suite = [q for q in trous if cible is None or q["id"] != cible["id"]][:2]
    queue = "".join(
        f'<article class="queue__card"><div class="queue__txt">'
        f'<h3>{_cite(q["texte"])}</h3><p>{_e(_diagnostic(q))}</p></div>'
        f'<div class="queue__rate{" queue__rate--warn" if q["taux"] >= 10 else ""}">'
        f'{q["taux"]:.0f} %</div></article>'
        for q in suite
    )

    tete = d["voix"][0]["part"] if d["voix"] else 1
    lb = ""
    for i, v in enumerate(d["voix"], 1):
        cls = "is-you" if v["moi"] else ("is-chaser" if v is poursuivant else "")
        ecart = ""
        if v is poursuivant and moi and place == 1:
            ecart = (f'<span class="lb__gap">à {_nb(moi["part"] - v["part"])} pts '
                     f'derrière la marque</span>')
        sous = v["label"] or ("la marque suivie" if v["moi"] else "")
        lb += (f'<li class="{cls}"><span class="lb__rank">{i}</span>'
               f'<span class="lb__dom">{_e(v["domaine"])}'
               + (f"<small>{_e(sous)}</small>" if sous else "")
               + f'</span><span class="lb__bar"><i style="width:{v["part"] / tete * 100:.0f}%"></i>'
               f'</span><span class="lb__part">{_nb(v["part"])} %</span>{ecart}</li>')

    st = "".join(
        f'<li><h3>{_e(q["texte"])} <span>{q["taux"]:.0f} %</span></h3>'
        f'<div class="st__bar"><i style="width:{q["taux"]:.0f}%"></i></div></li>'
        for q in forts
    )

    eng, meilleur = "", max((x["taux"] for x in d["moteurs"]), default=0)
    for m in d["moteurs"]:
        tag = ""
        if m["recherche"] and m["taux"] >= meilleur:
            tag = '<span class="eng__tag eng__tag--best">Ton allié</span>'
        elif not m["recherche"]:
            tag = '<span class="eng__tag eng__tag--goal">Objectif long terme</span>'
        eng += (f'<article class="eng{" eng--zero" if m["taux"] < 1 else ""}">'
                f'<h3>{_e(NOMS_MOTEURS.get(m["id"], m["id"]))}</h3>'
                f'<div class="eng__rate">{m["taux"]:.0f} %</div>'
                f'<div class="eng__bar"><i style="width:{max(m["taux"], 2):.0f}%"></i></div>'
                f'<p>{_e(_lecture_moteur(m, d["moteurs"]))}</p>{tag}</article>')

    if len(d["serie"]) > 1:
        barres = "".join(
            f'<i class="{"on" if i >= len(d["serie"]) - 2 else ""}" '
            f'style="height:{6 + p["taux"] / 100 * 20:.0f}px"></i>'
            for i, p in enumerate(d["serie"])
        )
        spark = f'<div class="foot__spark">{barres}</div>'
    else:
        spark = '<span>La courbe apparaîtra à la deuxième collecte.</span>'

    titre = ("Une réponse d'IA sur deux cite la marque" if 45 <= taux <= 55
             else f"{taux:.0f} % des réponses d'IA citent la marque")
    L = 267
    lead_voix = (
        f"La marque domine, mais <strong>{_e(poursuivant['domaine'])} n'est "
        f"qu'à {_nb(moi['part'] - poursuivant['part'])} pts</strong>."
        if moi and poursuivant and place == 1
        else "Répartition des citations relevées pendant la collecte."
    )
    lead_forts = (
        f"<strong>{_e(forts[0]['texte'])}</strong> à {forts[0]['taux']:.0f} % : la preuve que la "
        f"méthode fonctionne. Il suffit de la répliquer sur les sujets ci-dessus."
        if forts else "Aucune requête au-dessus de 60 % pour l'instant."
    )

    return f"""
  <section class="hero">
    <div class="gauge">
      <svg viewBox="0 0 210 130" aria-hidden="true">
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--piste)"
              stroke-width="14" stroke-linecap="round"/>
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--ink-faint)"
              stroke-width="14" stroke-linecap="round" stroke-dasharray="{L * palier / 100:.1f} {L}"/>
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--signal)"
              stroke-width="14" stroke-linecap="round" stroke-dasharray="{L * taux / 100:.1f} {L}"/>
      </svg>
      <div class="gauge__value">{taux:.0f}<small>%</small></div>
    </div>
    <div class="hero__mid">
      <h1>{titre}{badge}</h1>
      <p class="eyebrow">Visibilité IA</p>
      <p>Mesuré sur <strong>{r['n']} appels</strong>, {len(d['moteurs'])} moteurs. {_e(phrase)}</p>
      <div class="ruler">
        <div class="ruler__track">
          <span class="ruler__ticks"></span>
          <span class="ruler__fill" style="width:{taux:.0f}%"></span>
          <span class="ruler__goal" style="left:{palier}%"><span>Palier {palier} %</span></span>
        </div>
        <div class="ruler__caption">
          <span><strong>{taux:.0f} %</strong> aujourd'hui</span><span>{reste_txt}</span>
        </div>
      </div>
    </div>
    <div class="hero__side">
      <div class="stat stat--crown"><div class="stat__num">{place or "—"}<sup>{"re" if place == 1 else "e"}</sup></div>
        <div class="stat__lbl">sur {d['domaines_distincts']} domaines cités</div></div>
      <div class="stat"><div class="stat__num">{_nb(moi["part"]) + " %" if moi else "n/d"}</div>
        <div class="stat__lbl">part de voix</div></div>
      <div class="stat"><div class="stat__num">{_nb(r["avg_rank"]) if r["avg_rank"] else "n/d"}</div>
        <div class="stat__lbl">rang moyen dans les sources</div></div>
    </div>
  </section>
{mission}
  <section class="queue">{queue}</section>

  <div class="grid">
    <section class="card">
      <div class="card__head"><h2>Qui te prend des citations</h2>
        <span class="card__hint">{d['total_citations']} citations<br>{d['domaines_distincts']} domaines</span></div>
      <p class="card__lead">{lead_voix}</p>
      <ol class="lb">{lb}</ol>
    </section>
    <section class="card">
      <div class="card__head"><h2>Tes forteresses</h2>
        <span class="card__hint">ce qui a été travaillé se voit</span></div>
      <p class="card__lead">{lead_forts}</p>
      <ul class="st">{st}</ul>
    </section>
  </div>

  <div class="engines">{eng}</div>

  <footer class="foot">
    <div><strong>{_e(_prochaine_collecte())}</strong> Publie aujourd'hui, mesure l'effet ensuite.</div>
    {spark}
  </footer>"""


def _vue_requetes(d: dict) -> str:
    lignes = "".join(
        f'<tr><td>{_e(q["texte"])}</td><td class="n">{_e(q["id"])}</td>'
        f'<td class="n">{_e(q["type"])}</td><td class="n">{q["taux"]:.0f} %</td>'
        f'<td class="n">{q["cites"]}/{q["ok"]}</td></tr>'
        for q in sorted(d["requetes"], key=lambda x: x["id"])
    )
    return f"""<section class="card">
  <div class="card__head"><h2>Jeu de requêtes</h2>
    <span class="card__hint">version {d['set_version']} · {len(d['requetes'])} requêtes ·
    {d['n_concurrents']} concurrents suivis</span></div>
  <p class="card__lead">Une requête est une question posée comme un humain la pose, pas un mot-clé.
  <strong>Ajouter une requête est sans danger ; en modifier une casse la comparabilité de la
  série.</strong></p>
  <div class="tw"><table class="d">
  <tr><th>Requête</th><th>Réf.</th><th>Type</th><th>Citation</th><th>Ratio</th></tr>
  {lignes}</table></div></section>"""


def _vue_collectes(d: dict) -> str:
    def ligne(h):
        t = f'{h["taux"]:.0f} %' if h["taux"] is not None else "—"
        return (f'<tr><td class="n">#{h["id"]}</td><td class="n">{_e(h["date"])}</td>'
                f'<td class="n">{h["n"]}</td><td class="n">{h["erreurs"] or "—"}</td>'
                f'<td class="n">{t}</td><td>{_e(h["note"])}</td></tr>')

    return f"""<section class="card">
  <div class="card__head"><h2>Collectes</h2>
    <span class="card__hint">{len(d['historique'])} enregistrées</span></div>
  <p class="card__lead">Chaque collecte interroge tous les moteurs sur toutes les requêtes,
  plusieurs fois. <strong>Les réponses brutes sont conservées horodatées</strong> : les taux se
  recalculent, une réponse perdue ne se rattrape pas.</p>
  <div class="tw"><table class="d">
  <tr><th>Réf.</th><th>Date</th><th>Appels</th><th>Erreurs</th><th>Citation</th><th>Note</th></tr>
  {''.join(ligne(h) for h in d['historique'])}</table></div></section>"""


def rendu(d: dict) -> str:
    p = d["produit"]
    if len(d["clients"]) > 1:
        opts = "".join(f'<option{" selected" if c == d["client"] else ""}>{_e(c)}</option>'
                       for c in d["clients"])
        client = f'<select class="chip" aria-label="Client">{opts}</select>'
    else:
        client = f'<span class="chip">{_e(d["client_label"])}</span>'

    return f"""<div class="wrap">
  <header class="topbar">
    <div class="brand">
      <div class="brand__mark" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path d="M2 15 L2 11 M5.2 15 L5.2 8 M8.4 15 L8.4 11 M11.6 15 L11.6 5 M14.8 15 L14.8 11 M18 15 L18 8"
                stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>
      </div>
      <div><div class="brand__name">{_e(p['nom'])}</div>
        <div class="brand__sub">{_e(d['client_label'])}</div></div>
    </div>
    <div class="topbar__meta">
      {client}
      <span class="chip">Collecte #{d['run_id']} · {_e(d['date'])}</span>
      <button class="chip nav" role="tab" aria-selected="true" aria-controls="v-res">Résultats</button>
      <button class="chip nav" role="tab" aria-selected="false" aria-controls="v-req">Requêtes</button>
      <button class="chip nav" role="tab" aria-selected="false" aria-controls="v-col">Collectes</button>
    </div>
  </header>
  <div id="v-res" role="tabpanel">{_vue_resultats(d)}</div>
  <div id="v-req" role="tabpanel" hidden>{_vue_requetes(d)}</div>
  <div id="v-col" role="tabpanel" hidden>{_vue_collectes(d)}</div>
</div>
<style>{CSS}</style>
<script>{JS}</script>"""


# ------------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interface d'IAmètre.")
    ap.add_argument("--client", default="smart-bpjeps")
    ap.add_argument("--run", type=int)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--out", default=str(SORTIE))
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

    d = collecte(conn, run_id)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(rendu(d), encoding="utf-8")
    conn.close()

    delta = "aucune collecte comparable" if d["delta"] is None else f"{d['delta']:+.1f} pts"
    print(f"Interface écrite : {a.out}")
    print(f"  {d['produit']['nom']} · collecte #{run_id} · {d['resume']['n']} appels · "
          f"{(d['resume']['rate'] or 0):.0f} % · évolution : {delta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
