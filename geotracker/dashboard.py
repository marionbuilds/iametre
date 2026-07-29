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
            historique.append(dict(id=r["id"], iso=r["started_at"][:10],
                                   date=r["started_at"][:16].replace("T", " à "),
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
    return f"+{_nb(imp)} pts"


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
  --ink:#152A1C; --ink-soft:rgba(21,42,28,.64); --ink-faint:rgba(21,42,28,.42);
  --bg:#E7F0DE; --paper:#FCFDFA; --line:rgba(21,42,28,.10);
  --forest:#1D3826; --forest-2:#2A4A31;
  --sur-forest:#EFF6E8; --sur-forest-soft:rgba(239,246,232,.62);
  --data:#7DBE45; --data-deep:#3E7D28; --data-soft:#E6F2D8;
  --lime:#CDE9A5; --piste:#EDF3E2;
  --alert:#C14E24; --alert-soft:#F8E9E0;
  --opp:#8A6100; --opp-soft:#F6EFD3; --r:16px;
  --f-display:system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-body:system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ink:#E9F2E3; --ink-soft:rgba(233,242,227,.66); --ink-faint:rgba(233,242,227,.42);
  --bg:#0C140E; --paper:#151F17; --line:rgba(233,242,227,.09);
  --forest:#16251B; --forest-2:#23392A;
  --data:#8FCB57; --data-deep:#A9DA74; --data-soft:rgba(143,203,87,.16);
  --lime:#B7DC85; --piste:#1E2B20;
  --alert:#E5764A; --alert-soft:rgba(229,118,74,.14);
  --opp:#E0A72E; --opp-soft:rgba(224,167,46,.13);
}}
:root[data-theme="dark"]{
  --ink:#E9F2E3; --ink-soft:rgba(233,242,227,.66); --ink-faint:rgba(233,242,227,.42);
  --bg:#0C140E; --paper:#151F17; --line:rgba(233,242,227,.09);
  --forest:#16251B; --forest-2:#23392A;
  --data:#8FCB57; --data-deep:#A9DA74; --data-soft:rgba(143,203,87,.16);
  --lime:#B7DC85; --piste:#1E2B20;
  --alert:#E5764A; --alert-soft:rgba(229,118,74,.14);
  --opp:#E0A72E; --opp-soft:rgba(224,167,46,.13);
}
body{font-family:var(--f-body); background:var(--bg); color:var(--ink); line-height:1.55;
  -webkit-font-smoothing:antialiased}
.app{display:flex; align-items:flex-start; gap:20px; max-width:1420px; margin:0 auto;
  padding:16px}

.side{flex:none; width:76px; position:sticky; top:16px; height:calc(100vh - 32px);
  min-height:480px; background:var(--forest); color:var(--sur-forest); border-radius:26px;
  padding:16px 0 18px; display:flex; flex-direction:column; align-items:center; gap:8px}
.brand{margin-bottom:16px}
.brand__mark{width:44px; height:44px; border-radius:14px; background:rgba(239,246,232,.14);
  display:grid; place-items:center}
.nav{display:grid; place-items:center; width:46px; height:46px; border:none; background:none;
  color:var(--sur-forest-soft); border-radius:15px; cursor:pointer}
.nav[aria-selected="true"]{background:var(--forest-2); color:var(--sur-forest)}
@media(hover:hover){.nav:hover{color:var(--sur-forest)}}
.nav:focus-visible{outline:3px solid var(--lime); outline-offset:2px}
.side__sep{flex:1}
.side__client{width:38px; height:38px; border-radius:50%; background:var(--lime);
  color:#1D3826; display:grid; place-items:center; font-weight:800; font-size:.95rem}

.main{flex:1; min-width:0; padding:6px 2px 60px}
.mhead{display:flex; align-items:flex-start; justify-content:space-between; gap:16px;
  flex-wrap:wrap; margin-bottom:20px}
.mhead h1{font-family:var(--f-display); font-weight:700; font-size:1.5rem;
  letter-spacing:-.02em; line-height:1.2}
.mhead__sub{font-size:.82rem; color:var(--ink-soft); margin-top:3px}
.mhead__acts{display:flex; align-items:center; gap:10px}
.iconbtn{width:42px; height:42px; border-radius:50%; border:1px solid var(--line);
  background:var(--paper); color:var(--ink); display:grid; place-items:center; cursor:pointer}
.iconbtn:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.btn--report{display:inline-flex; align-items:center; gap:8px; background:var(--forest);
  color:var(--sur-forest); border:none; border-radius:999px; font-family:inherit;
  font-weight:700; font-size:.88rem; padding:12px 22px; cursor:pointer;
  transition:transform .15s}
@media(hover:hover){.btn--report:hover{transform:translateY(-2px)}}
.btn--report:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.pop-wrap{position:relative}
.pop{position:absolute; right:0; top:calc(100% + 8px); background:var(--paper);
  border:1px solid var(--line); border-radius:14px; padding:14px; min-width:216px; z-index:10;
  box-shadow:0 10px 30px rgba(21,42,28,.14)}
.pop__t{font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em;
  color:var(--ink-faint); margin-bottom:8px}
.pop__row{display:flex; gap:6px}
.toolrow{margin-bottom:18px}
.reqform{display:flex; gap:10px; margin:2px 0 16px; flex-wrap:wrap}
.reqform input{flex:1; min-width:240px; border:1px solid var(--line); border-radius:999px;
  padding:12px 18px; font-family:inherit; font-size:.9rem; background:var(--bg);
  color:var(--ink)}
.reqform input:focus-visible{outline:3px solid var(--data-deep); outline-offset:1px}
.reqform input::placeholder{color:var(--ink-faint)}
.reqattente{border:1px dashed var(--line); border-radius:14px; padding:14px 16px;
  margin-bottom:16px}
.reqattente__t{font-size:.78rem; font-weight:600; color:var(--ink-soft); margin-bottom:8px}
.reqattente ul{list-style:none; display:grid; gap:6px; margin-bottom:10px}
.reqattente li{display:flex; align-items:center; justify-content:space-between; gap:12px;
  font-size:.88rem; background:var(--data-soft); color:var(--ink);
  border-radius:10px; padding:8px 12px}
.reqattente li button{border:none; background:none; color:var(--ink-faint); cursor:pointer;
  font-size:1rem; line-height:1; padding:2px}
a.btn--mini{text-decoration:none; display:inline-block; margin-top:0}
.chips{display:flex; align-items:center; gap:6px; flex-wrap:wrap}
.chip{font-size:.78rem; font-weight:600; padding:6px 12px; border-radius:999px;
  background:var(--paper); border:1px solid var(--line); color:var(--ink); font-family:inherit}
button.chip{cursor:pointer}
button.chip[aria-selected="true"]{background:var(--forest); color:var(--sur-forest);
  border-color:transparent}
.chip:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.chip--etat{color:var(--ink-soft); font-weight:500; border-style:dashed}
.print-head{display:none}

.hero{background:var(--paper); border:1px solid var(--line); border-radius:22px;
  padding:30px 32px; display:grid; grid-template-columns:auto 1fr auto; gap:36px;
  align-items:center; margin-bottom:18px}
.gauge{position:relative; width:210px}
.gauge svg{display:block; width:100%; height:auto}
.gauge__value{position:absolute; left:0; right:0; top:58%; text-align:center;
  font-family:var(--f-mono); font-weight:700; font-size:2.9rem; letter-spacing:-.04em;
  line-height:1}
.gauge__value small{font-size:1.1rem; font-weight:600; color:var(--ink-soft)}
.eyebrow{font-size:.7rem; font-weight:700; color:var(--ink-faint);
  text-transform:uppercase; letter-spacing:.12em; margin-bottom:10px}
.hero__mid h2{font-family:var(--f-display); font-weight:700; font-size:1.45rem;
  letter-spacing:-.02em; line-height:1.25; margin-bottom:6px}
.hero__mid p{color:var(--ink-soft); font-size:.92rem; max-width:50ch}
.hero__mid p strong{color:var(--ink)}
.delta{display:inline-flex; align-items:center; gap:5px; font-family:var(--f-mono);
  font-weight:600; font-size:.85rem; border-radius:8px; padding:3px 9px; margin-left:8px}
.delta--up{color:var(--data-deep); background:var(--data-soft)}
.delta--down{color:var(--alert); background:var(--alert-soft)}
.delta--flat{color:var(--ink-soft); background:var(--piste)}
.ruler{margin-top:18px}
.ruler__track{position:relative; height:26px; border-radius:7px; background:var(--piste)}
.ruler__ticks{position:absolute; inset:0; border-radius:7px; overflow:hidden;
  background:repeating-linear-gradient(90deg,rgba(120,140,110,.30) 0 1px,transparent 1px 10%)}
.ruler__fill{position:absolute; top:0; bottom:0; left:0;
  background:linear-gradient(90deg,var(--data),var(--data-deep)); border-radius:7px 0 0 7px}
.ruler__goal{position:absolute; top:-6px; bottom:-6px; width:2px; background:var(--forest)}
.ruler__goal span{position:absolute; top:-24px; left:-20px; font-family:var(--f-mono);
  font-size:.72rem; font-weight:600; white-space:nowrap; background:var(--forest);
  color:var(--sur-forest); padding:2px 7px; border-radius:6px}
.ruler__caption{display:flex; justify-content:space-between; font-size:.78rem;
  color:var(--ink-soft); margin-top:10px; gap:12px; flex-wrap:wrap}
.ruler__caption strong{color:var(--ink)}
.hero__side{display:grid; gap:14px; min-width:190px}
.stat{border-left:2px solid var(--line); padding-left:14px}
.stat__num{font-family:var(--f-mono); font-weight:700; font-size:1.35rem; letter-spacing:-.02em}
.stat__lbl{font-size:.76rem; color:var(--ink-soft)}
.stat--crown .stat__num{color:var(--data-deep)}

.mission{border-radius:22px; background:var(--forest); color:var(--sur-forest);
  padding:26px 30px; margin-bottom:18px; display:grid; grid-template-columns:1fr auto;
  gap:24px; align-items:center}
.mission__eyebrow{display:flex; align-items:center; gap:8px; font-size:.72rem; font-weight:700;
  text-transform:uppercase; letter-spacing:.12em; color:var(--lime); margin-bottom:8px}
.mission__eyebrow::before{content:""; width:8px; height:8px; border-radius:50%;
  background:var(--lime)}
.mission h2{font-family:var(--f-display); font-weight:700; font-size:1.32rem;
  letter-spacing:-.02em; margin-bottom:8px; line-height:1.3}
.mission p{font-size:.92rem; color:var(--sur-forest-soft); max-width:64ch}
.mission p strong{color:var(--sur-forest)}
.mission__side{display:grid; gap:14px; justify-items:end; text-align:right}
.mission__impact{font-family:var(--f-mono); font-weight:700; font-size:1.6rem;
  color:var(--lime); line-height:1}
.mission__impact small{display:block; font-family:var(--f-body); font-weight:600;
  font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; margin-top:4px;
  opacity:.85}
.mission__acts{display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end}
.btn{display:inline-flex; align-items:center; gap:8px; border:none; cursor:pointer;
  font-family:var(--f-body); font-weight:700; font-size:.9rem; padding:12px 22px;
  border-radius:12px; transition:transform .15s}
.btn--primary{background:var(--lime); color:#1D3826}
@media(hover:hover){.btn--primary:hover{transform:translateY(-2px)}}
.btn--ghost{background:none; border:1px solid rgba(239,246,232,.35); color:var(--sur-forest);
  font-family:inherit; font-weight:600; font-size:.82rem; padding:10px 16px;
  border-radius:10px; cursor:pointer}
.btn:focus-visible,.btn--ghost:focus-visible{outline:3px solid var(--lime); outline-offset:2px}

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
.btn--mini{border:1px solid var(--line); background:var(--data-soft); color:var(--data-deep);
  border-radius:9px; padding:6px 12px; font-family:inherit; font-size:.78rem; font-weight:700;
  cursor:pointer; margin-top:11px}
.btn--mini:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}

.grid{display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px}
.card{background:var(--paper); border:1px solid var(--line); border-radius:22px;
  padding:24px 26px}
.card__head{display:flex; align-items:baseline; justify-content:space-between; gap:12px;
  margin-bottom:6px}
.card__head h2{font-family:var(--f-display); font-weight:700; font-size:1.1rem;
  letter-spacing:-.01em}
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
.lb li.is-you{background:var(--data-soft); border-bottom-color:transparent}
.lb li.is-you .lb__dom{color:var(--data-deep)}
.lb li.is-you .lb__bar i{background:var(--data)}
.lb li.is-chaser .lb__part{color:var(--alert)}
.lb li.is-chaser .lb__bar i{background:var(--alert)}
.lb__gap{grid-column:2/-1; font-size:.78rem; color:var(--alert); font-weight:600;
  margin-top:-4px}

.st{list-style:none; display:grid; gap:14px}
.st li h3{font-size:.9rem; font-weight:600; margin-bottom:6px; display:flex;
  justify-content:space-between; gap:12px}
.st li h3 span{font-family:var(--f-mono); font-weight:700; color:var(--data-deep)}
.st__bar{height:8px; border-radius:99px; background:var(--piste); overflow:hidden}
.st__bar i{display:block; height:100%; border-radius:99px; background:var(--data)}

.engines{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px}
.eng{background:var(--paper); border:1px solid var(--line); border-radius:var(--r);
  padding:18px 20px}
.eng h3{font-size:.9rem; font-weight:700; margin-bottom:2px}
.eng__rate{font-family:var(--f-mono); font-weight:700; font-size:1.7rem; letter-spacing:-.03em;
  margin-bottom:8px}
.eng__bar{height:7px; border-radius:99px; background:var(--piste); overflow:hidden;
  margin-bottom:10px}
.eng__bar i{display:block; height:100%; background:var(--data); border-radius:99px}
.eng p{font-size:.79rem; color:var(--ink-soft); line-height:1.5}
.eng--zero .eng__rate{color:var(--ink-faint)}
.eng--zero .eng__bar i{background:var(--ink-faint)}
.eng__tag{display:inline-block; font-size:.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.08em; padding:3px 8px; border-radius:6px; margin-top:10px}
.eng__tag--goal{background:var(--opp-soft); color:var(--opp)}
.eng__tag--best{background:var(--data-soft); color:var(--data-deep)}

svg.curve{display:block; width:100%; height:auto; margin-top:4px}
.curve__mid{stroke:var(--line); stroke-width:1; stroke-dasharray:3 4}
.curve__val{font-family:var(--f-mono); font-weight:700; font-size:15px; fill:var(--ink)}
.curve__cap{display:flex; justify-content:space-between; font-size:.75rem;
  color:var(--ink-faint); margin-top:6px}

.tw{overflow-x:auto}
table.d{border-collapse:collapse; width:100%; font-size:.86rem}
table.d th,table.d td{text-align:left; padding:10px 14px; border-bottom:1px solid var(--line)}
table.d th{font-size:.7rem; font-weight:700; color:var(--ink-faint); letter-spacing:.07em;
  text-transform:uppercase; white-space:nowrap}
table.d td.n{font-family:var(--f-mono); white-space:nowrap}
table.d tr:last-child td{border-bottom:none}

[hidden]{display:none!important}
@media(max-width:1020px){
  .app{flex-direction:column; gap:14px}
  .side{position:static; width:100%; height:auto; min-height:0; flex-direction:row;
    border-radius:18px; padding:10px 14px}
  .brand{margin-bottom:0}
  .side__sep{display:none}
  .side__client{margin-left:auto}
  .hero{grid-template-columns:1fr; text-align:center}
  .gauge{margin:0 auto}
  .hero__side{grid-template-columns:repeat(3,1fr); min-width:0}
  .stat{border-left:none; border-top:2px solid var(--line); padding:10px 0 0}
  .engines{grid-template-columns:repeat(2,1fr)}
  .grid,.queue{grid-template-columns:1fr}
  .mission{grid-template-columns:1fr}
  .mission__side{justify-items:start; text-align:left}
  .mission__acts{justify-content:flex-start}
}
@media(max-width:560px){
  .app{padding:10px}
  .main{padding:4px 0 50px}
  .hero,.mission,.card{padding:20px}
  .engines,.hero__side{grid-template-columns:1fr}
  .lb li{grid-template-columns:22px 1fr auto}
  .lb__bar{display:none}
}
@media print{
  body{background:#fff}
  .app{display:block; padding:0; max-width:none}
  .side,.chips,.mhead__acts,.pop,.mission__acts,.btn--mini,button{display:none!important}
  .print-head{display:flex; align-items:baseline; justify-content:space-between; gap:12px;
    padding-bottom:14px; margin-bottom:18px; border-bottom:2px solid #1D3826}
  .print-head strong{font-size:1.1rem}
  .print-head span{font-size:.8rem; color:#555}
  .hero,.mission,.card,.eng,.queue__card,.foot{border:1px solid #ccc; break-inside:avoid}
  .mission{background:#fff; color:#152A1C}
  .mission p{color:#3d4a40}
  .mission__eyebrow,.mission__impact{color:#3E7D28}
  [role="tabpanel"][hidden]{display:block!important}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  document.querySelectorAll('[data-copy]').forEach(function(b){
    b.addEventListener('click',function(){
      var self=this, texte=this.getAttribute('data-copy'),
          ok=this.getAttribute('data-ok')||'Copié', avant=this.textContent;
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(texte).then(function(){
          self.textContent=ok;
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
  var ex=document.getElementById('exporter');
  if(ex){ex.addEventListener('click',function(){window.print();});}
  var per=[].slice.call(document.querySelectorAll('.per'));
  function filtre(jours){
    var limite=null;
    if(jours>0){limite=new Date(); limite.setDate(limite.getDate()-jours);}
    var visibles=0, total=0;
    [].slice.call(document.querySelectorAll('[data-date]')).forEach(function(el){
      var hors=!!(limite&&new Date(el.getAttribute('data-date')+'T12:00:00')<limite);
      el.hidden=hors;
      if(el.hasAttribute('data-collecte')){total++; if(!hors){visibles++;}}
    });
    var etat=document.getElementById('per-etat');
    if(etat){
      etat.textContent=limite
        ? visibles+' collecte'+(visibles>1?'s':'')+' sur la période'
        : 'toutes les collectes';
    }
  }
  per.forEach(function(o){o.addEventListener('click',function(){
    per.forEach(function(x){x.setAttribute('aria-selected',x===o?'true':'false');});
    filtre(parseInt(o.getAttribute('data-jours'),10));
  });});
  var rg=document.getElementById('reglages'), pop=document.getElementById('pop-reglages');
  if(rg&&pop){
    rg.addEventListener('click',function(){
      var ouvert=pop.hidden;
      pop.hidden=!ouvert;
      rg.setAttribute('aria-expanded',ouvert?'true':'false');
    });
    document.addEventListener('click',function(e){
      if(!pop.hidden&&!pop.contains(e.target)&&!rg.contains(e.target)){
        pop.hidden=true; rg.setAttribute('aria-expanded','false');
      }
    });
  }
  var CLE='iametre-theme', themes=[].slice.call(document.querySelectorAll('.theme'));
  function appliqueTheme(v){
    if(v){document.documentElement.setAttribute('data-theme',v);}
    else{document.documentElement.removeAttribute('data-theme');}
    themes.forEach(function(b){
      b.setAttribute('aria-selected',(b.getAttribute('data-theme-val')||'')===(v||'')?'true':'false');
    });
  }
  try{appliqueTheme(localStorage.getItem(CLE)||'');}catch(e){}
  themes.forEach(function(b){b.addEventListener('click',function(){
    var v=this.getAttribute('data-theme-val')||'';
    try{if(v){localStorage.setItem(CLE,v);}else{localStorage.removeItem(CLE);}}catch(e){}
    appliqueTheme(v);
  });});
  var CLE_REQ='iametre-requetes-proposees',
      champ=document.getElementById('req-champ'),
      valider=document.getElementById('req-valider'),
      attente=document.getElementById('req-attente'),
      listeEl=document.getElementById('req-liste'),
      envoyer=document.getElementById('req-envoyer');
  function litProps(){
    try{return JSON.parse(localStorage.getItem(CLE_REQ)||'[]');}catch(e){return [];}
  }
  function ecritProps(l){
    try{localStorage.setItem(CLE_REQ,JSON.stringify(l));}catch(e){}
  }
  function dessine(){
    if(!listeEl){return;}
    var l=litProps();
    attente.hidden=l.length===0;
    listeEl.innerHTML='';
    l.forEach(function(q,i){
      var li=document.createElement('li'), s=document.createElement('span'),
          x=document.createElement('button');
      s.textContent=q;
      x.textContent='\u00d7';
      x.setAttribute('aria-label','Retirer cette proposition');
      x.addEventListener('click',function(){
        var l2=litProps(); l2.splice(i,1); ecritProps(l2); dessine();
      });
      li.appendChild(s); li.appendChild(x); listeEl.appendChild(li);
    });
    if(envoyer){
      var corps='Requetes a ajouter au jeu de suivi (statut : en observation) :\n\n'
                +l.map(function(q){return '- '+q;}).join('\n');
      envoyer.href='https://github.com/marionbuilds/tracker-geo/issues/new'
        +'?title='+encodeURIComponent('Ajout de requetes au jeu de suivi')
        +'&body='+encodeURIComponent(corps);
    }
  }
  if(valider){
    valider.addEventListener('click',function(){
      var v=(champ.value||'').trim();
      if(v.length<10){champ.focus();return;}
      var l=litProps();
      if(l.indexOf(v)===-1){l.push(v);ecritProps(l);}
      champ.value=''; dessine();
    });
    champ.addEventListener('keydown',function(e){
      if(e.key==='Enter'){valider.click();}
    });
    dessine();
  }
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

    marge = _marge(r)
    if d["delta"] is None:
        badge = ""
        phrase = "Première collecte de ce périmètre : la courbe démarre ici."
    elif abs(d["delta"]) <= marge:
        # Dans la marge de fluctuation : ni victoire ni alerte, on le DIT.
        badge = '<span class="delta delta--flat">≈ stable</span>'
        phrase = (f"Variation de {_nb(abs(d['delta']))} pt(s) : dans la marge de fluctuation "
                  f"normale (±{_nb(marge)} pts), ce n'est ni une progression ni un recul.")
    else:
        haut = d["delta"] >= 0
        badge = (f'<span class="delta delta--{"up" if haut else "down"}">'
                 f'{"▲" if haut else "▼"} {_nb(abs(d["delta"]))} pts</span>')
        phrase = (f"{'▲' if haut else '▼'} {_nb(abs(d['delta']))} points depuis la collecte "
                  f"précédente, au-delà de la marge de ±{_nb(marge)} pts : le mouvement est réel.")

    reste_txt = f"<strong>+{reste:.0f} pts restants</strong>"
    if contenus:
        reste_txt += f" · <strong>{contenus} à {contenus + 1} contenus</strong>"

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
      <div class="mission__impact">{_e(_promesse(_impact(cible, d["requetes"], r)))}<small>impact estimé, borne basse</small></div>
      <div class="mission__acts">
        <button class="btn--ghost" data-copy="{_e(_brief(cible, d))}" data-ok="Brief copié">Copier le brief</button>
        <button class="btn btn--primary" data-copy="{_e(_prompt_ia(cible, d))}" data-ok="Recette copiée, colle-la dans une IA">Copier la recette d'article</button>
      </div>
    </div>
  </section>"""

    suite = [q for q in trous if cible is None or q["id"] != cible["id"]][:2]
    queue = "".join(
        f'<article class="queue__card"><div class="queue__txt">'
        f'<h3>{_cite(q["texte"])}</h3><p>{_e(_diagnostic(q))}</p>'
        f'<button class="btn--mini" data-copy="{_e(_prompt_ia(q, d))}" '
        f'data-ok="Recette copiée">Copier la recette d\'article</button></div>'
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
      <h2>{titre}{badge}</h2>
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

{_courbe(d, marge)}"""


def _courbe(d: dict, marge: float) -> str:
    """La courbe de visibilité, avec sa bande de fluctuation dessinée.

    C'est la réponse visuelle à la peur du « demain il y aura moins » :
    la bande matérialise la zone où la mesure peut osciller à effort
    constant. Un point qui reste dans la bande ne raconte rien ;
    la tendance de la ligne, si.
    """
    serie = d["serie"]
    if len(serie) < 2:
        return f"""<section class="card">
  <div class="card__head"><h2>Courbe de visibilité</h2>
    <span class="card__hint">un point par jour de collecte</span></div>
  <p class="card__lead">La courbe se dessine à partir de la deuxième collecte, qui arrive
  automatiquement. En attendant, le repère qui compte :
  <strong>la marge de fluctuation de cette mesure est de ±{_nb(marge)} pts.</strong>
  Une réponse d'IA n'est pas stable : à effort constant, le taux oscille naturellement dans
  cette bande. Une variation qui reste dedans n'est ni une victoire ni une alerte ; seuls un
  mouvement qui en sort ou une tendance sur 3-4 collectes sont de vrais signaux.</p>
</section>"""

    W, H, PAD = 640, 150, 16
    n = len(serie)
    xs = [PAD + i * (W - 2 * PAD) / (n - 1) for i in range(n)]

    def y(v: float) -> float:
        return H - PAD - max(0.0, min(100.0, v)) / 100 * (H - 2 * PAD)

    bande = (" ".join(f"{x:.1f},{y(pt['taux'] + marge):.1f}" for x, pt in zip(xs, serie))
             + " " + " ".join(f"{x:.1f},{y(pt['taux'] - marge):.1f}"
                              for x, pt in zip(reversed(xs), list(reversed(serie)))))
    ligne = " ".join(f"{x:.1f},{y(pt['taux']):.1f}" for x, pt in zip(xs, serie))
    points = "".join(
        f'<circle cx="{x:.1f}" cy="{y(pt["taux"]):.1f}" r="{5 if i == n - 1 else 3.5}" '
        f'fill="var(--data{"-deep" if i == n - 1 else ""})">'
        f'<title>{_e(pt["date"])} : {pt["taux"]:.0f} %</title></circle>'
        for i, (x, pt) in enumerate(zip(xs, serie))
    )
    dernier = serie[-1]
    etiquette = (f'<text x="{xs[-1]:.1f}" y="{y(dernier["taux"]) - 12:.1f}" text-anchor="end" '
                 f'class="curve__val">{dernier["taux"]:.0f} %</text>')

    return f"""<section class="card">
  <div class="card__head"><h2>Courbe de visibilité</h2>
    <span class="card__hint">bande grisée : marge de fluctuation ±{_nb(marge)} pts</span></div>
  <p class="card__lead">Tant que la ligne reste dans sa bande, la mesure est <strong>stable</strong> :
  l'oscillation est le comportement normal d'une réponse d'IA, pas un recul.
  Le vrai signal, c'est la tendance sur 3-4 collectes.</p>
  <svg class="curve" viewBox="0 0 {W} {H}" role="img"
       aria-label="Courbe du taux de citation avec sa marge de fluctuation">
    <line x1="{PAD}" y1="{y(50):.1f}" x2="{W - PAD}" y2="{y(50):.1f}" class="curve__mid"/>
    <polygon points="{bande}" fill="var(--data-soft)"/>
    <polyline points="{ligne}" fill="none" stroke="var(--data)" stroke-width="2.5"
              stroke-linecap="round" stroke-linejoin="round"/>
    {points}{etiquette}
  </svg>
  <div class="curve__cap"><span>{_e(serie[0]["date"])}</span>
    <span>{_e(dernier["date"])}</span></div>
</section>"""


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
  <div class="reqform">
    <input id="req-champ" type="text" maxlength="180"
           placeholder="Proposer une requête, formulée comme on la poserait à une IA…"
           aria-label="Nouvelle requête à suivre">
    <button class="btn--report" id="req-valider">Valider</button>
  </div>
  <div class="reqattente" id="req-attente" hidden>
    <p class="reqattente__t">En attente d'intégration à la prochaine collecte
      (~1&nbsp;$/mois par requête) :</p>
    <ul id="req-liste"></ul>
    <a id="req-envoyer" class="btn--mini" target="_blank" rel="noopener"
       href="https://github.com/marionbuilds/tracker-geo/issues/new">Transmettre au tracker</a>
  </div>
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
        client = ""

    return f"""<div class="app">
  <aside class="side">
    <div class="brand" title="{_e(p['nom'])} · {_e(p['signature'])}">
      <div class="brand__mark" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 20 20" fill="none">
          <path d="M2 15 L2 11 M5.2 15 L5.2 8 M8.4 15 L8.4 11 M11.6 15 L11.6 5 M14.8 15 L14.8 11 M18 15 L18 8"
                stroke="#EFF6E8" stroke-width="1.8" stroke-linecap="round"/></svg>
      </div>
    </div>
    <button class="nav" role="tab" aria-selected="true" aria-controls="v-res"
            title="Vue d'ensemble" aria-label="Vue d'ensemble">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="2" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/></svg></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-req"
            title="Requêtes" aria-label="Requêtes">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="12" height="12" rx="3" stroke="currentColor" stroke-width="1.6"/>
        <circle cx="5.6" cy="5.6" r="1.05" fill="currentColor"/>
        <circle cx="10.4" cy="5.6" r="1.05" fill="currentColor"/>
        <circle cx="8" cy="8" r="1.05" fill="currentColor"/>
        <circle cx="5.6" cy="10.4" r="1.05" fill="currentColor"/>
        <circle cx="10.4" cy="10.4" r="1.05" fill="currentColor"/></svg></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-col"
            title="Collectes" aria-label="Collectes">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.7"/>
        <path d="M8 4.5 L8 8 L10.6 9.6" stroke="currentColor" stroke-width="1.7"
              stroke-linecap="round"/></svg></button>
    <div class="side__sep"></div>
    <div class="side__client" title="{_e(d['client_label'])}">{_e(d['client_label'][:1].upper())}</div>
  </aside>
  <main class="main">
    <div class="print-head"><strong>{_e(p['nom'])} · {_e(d['client_label'])}</strong>
      <span>Collecte #{d['run_id']} · {_e(d['date'])} · {_e(p['signature'])}</span></div>
    <header class="mhead">
      <div><h1>{_e(d['client_label'])}</h1>
        <p class="mhead__sub">Collecte #{d['run_id']} · {_e(d['date'])} ·
          {d['resume']['n']} appels · {_e(_prochaine_collecte())}</p></div>
      <div class="mhead__acts">
        <div class="pop-wrap">
          <button class="iconbtn" id="reglages" aria-expanded="false"
                  title="Réglages" aria-label="Réglages">
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="2.2" stroke="currentColor" stroke-width="1.5"/>
              <path d="M8 1.6 L8 3.4 M8 12.6 L8 14.4 M1.6 8 L3.4 8 M12.6 8 L14.4 8
                       M3.5 3.5 L4.8 4.8 M11.2 11.2 L12.5 12.5 M12.5 3.5 L11.2 4.8
                       M4.8 11.2 L3.5 12.5"
                    stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </button>
          <div class="pop" id="pop-reglages" hidden>
            <p class="pop__t">Thème</p>
            <div class="pop__row">
              <button class="chip theme" data-theme-val="" aria-selected="true">Auto</button>
              <button class="chip theme" data-theme-val="light" aria-selected="false">Clair</button>
              <button class="chip theme" data-theme-val="dark" aria-selected="false">Sombre</button>
            </div>
          </div>
        </div>
        <button class="btn--report" id="exporter">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 3 L8 13 M3 8 L13 8" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round"/></svg>
          Créer un rapport</button>
      </div>
    </header>
    <div class="toolrow chips" role="group" aria-label="Période">
      {client}
      <button class="chip per" data-jours="7" aria-selected="false">7 jours</button>
      <button class="chip per" data-jours="28" aria-selected="false">28 jours</button>
      <button class="chip per" data-jours="90" aria-selected="false">3 mois</button>
      <button class="chip per" data-jours="0" aria-selected="true">Tout</button>
      <span class="chip chip--etat" id="per-etat">toutes les collectes</span>
    </div>
    <div id="v-res" role="tabpanel">{_vue_resultats(d)}</div>
    <div id="v-req" role="tabpanel" hidden>{_vue_requetes(d)}</div>
    <div id="v-col" role="tabpanel" hidden>{_vue_collectes(d)}</div>
  </main>
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
