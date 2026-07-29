"""Génère l'interface du produit à partir des données collectées.

    python -m geotracker.dashboard              # dernier run
    python -m geotracker.dashboard --run 13

Le fichier produit est autonome : aucun script ni police externe. Il s'ouvre
d'un double-clic, fonctionne hors ligne, et se régénère à chaque collecte.

Trois vues, qui suivent le parcours d'un utilisateur :
  Résultats  ce que la collecte a mesuré
  Requêtes   ce qui est suivi, et comment on en ajoute
  Collectes  l'historique des exécutions

Direction artistique (CLAUDE.md §4 du front) : blanc épuré, minimaliste, type
Apple, futuriste. **Interface monochrome, la couleur n'apparaît QUE dans les
données** : c'est ce qui rend le produit rebrandable pour un client. Palette de
données validée (luminosité, chroma, séparation daltonisme, contraste), en clair
comme en sombre.

Les textes sont écrits du point de vue d'un utilisateur quelconque, jamais de
Marion : « la marque », pas « toi ». C'est ce qui sépare un rapport personnel
d'un produit.
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime
from pathlib import Path

from . import db
from .config import ROOT, clients_disponibles, load_client, load_produit
from .report import run_summary

SORTIE = ROOT / "reports" / "dashboard.html"

# Seuil sous lequel une requête est traitée comme un trou de contenu. Toujours
# doublé d'un libellé écrit : la couleur ne porte jamais seule une information.
SEUIL_TROU = 25.0

NOMS_MOTEURS = {
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "anthropic-memory": "Claude, mémoire de marque",
    "ai_overview": "Google AI Overviews",
}


# --------------------------------------------------------------------- données

def collecte(conn, run_id: int) -> dict:
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        raise SystemExit(f"Run #{run_id} introuvable.")

    moteurs = sorted(
        (
            dict(
                id=r["engine_id"],
                recherche=bool(r["search_enabled"]),
                ok=r["ok"] or 0,
                cites=r["cited"] or 0,
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
        key=lambda m: m["taux"],
        reverse=True,
    )

    requetes = sorted(
        (
            dict(
                id=r["prompt_id"],
                texte=r["prompt_text"],
                type=r["prompt_type"] or "",
                ok=r["ok"] or 0,
                cites=r["cited"] or 0,
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
        key=lambda q: q["taux"],
        reverse=True,
    )

    # ⚠️ Le dénominateur de la part de voix couvre TOUS les domaines cités, pas
    # seulement ceux qu'on affiche, sinon la part est gonflée par la troncature.
    total = conn.execute(
        """SELECT COUNT(*) n FROM sources s JOIN responses r ON r.id = s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''""",
        (run_id,),
    ).fetchone()["n"] or 1
    distincts = conn.execute(
        """SELECT COUNT(DISTINCT s.domain) n FROM sources s
           JOIN responses r ON r.id = s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''""",
        (run_id,),
    ).fetchone()["n"]
    voix = [
        dict(
            domaine=r["domain"],
            label=r["label"],
            moi=bool(r["moi"]),
            n=r["n"],
            part=r["n"] / total * 100,
            rang=r["rang"],
        )
        for r in conn.execute(
            """SELECT s.domain, MAX(s.is_target) AS moi, MAX(s.competitor) AS label,
                      COUNT(*) AS n, AVG(s.rank) AS rang
               FROM sources s JOIN responses r ON r.id = s.response_id
               WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''
               GROUP BY s.domain ORDER BY n DESC LIMIT 12""",
            (run_id,),
        ).fetchall()
    ]

    # Matrice requête × moteur : une forme de lecture que les barres ne donnent
    # pas. On voit d'un coup d'œil quel moteur est aveugle sur quel sujet.
    matrice = {}
    for r in conn.execute(
        """SELECT prompt_id, engine_id,
                  SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
                  SUM(COALESCE(cited,0)) AS cited
           FROM responses WHERE run_id=? GROUP BY prompt_id, engine_id""",
        (run_id,),
    ).fetchall():
        matrice[(r["prompt_id"], r["engine_id"])] = (
            (r["cited"] or 0) / r["ok"] * 100 if r["ok"] else None
        )

    historique = []
    for r in conn.execute(
        """SELECT id, started_at, note FROM runs WHERE client=? ORDER BY id DESC LIMIT 25""",
        (meta["client"],),
    ).fetchall():
        s = run_summary(conn, r["id"])
        if s["n"]:
            historique.append(
                dict(id=r["id"], date=r["started_at"][:16].replace("T", " à "),
                     note=r["note"] or "", n=s["n"], erreurs=s["errors"], taux=s["rate"])
            )

    # La courbe se compte en JOURS de mesure, pas en runs : plusieurs runs de
    # mise au point le même jour ne font qu'un seul point de série.
    serie = []
    for ligne in conn.execute(
        """SELECT DATE(started_at) j, MAX(id) dernier FROM runs
           WHERE client=? GROUP BY DATE(started_at) ORDER BY j""",
        (meta["client"],),
    ).fetchall():
        taux = run_summary(conn, ligne["dernier"])["rate"]
        if taux is not None:
            serie.append(dict(date=ligne["j"], taux=taux))

    try:
        cfg = load_client(meta["client"])
        etiquette = cfg.label
        set_version = cfg.set_version
        n_concurrents = len(cfg.competitors)
    except Exception:
        etiquette, set_version, n_concurrents = meta["client"], meta["set_version"], 0

    return {
        "run_id": run_id,
        "client": meta["client"],
        "client_label": etiquette,
        "clients": clients_disponibles(),
        "set_version": set_version,
        "n_concurrents": n_concurrents,
        "date": meta["started_at"][:10],
        "resume": run_summary(conn, run_id),
        "moteurs": moteurs,
        "requetes": requetes,
        "matrice": matrice,
        "voix": voix,
        "total_citations": total,
        "domaines_distincts": distincts,
        "historique": historique,
        "serie": serie,
        "produit": load_produit(),
    }


# ----------------------------------------------------------------------- rendu

def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _barre(largeur: float, couleur: str, valeur: str, tip: str, etiquette: str = "") -> str:
    marque = f'<span class="etiq">{_e(etiquette)}</span>' if etiquette else ""
    return (
        f'<div class="piste" tabindex="0" data-tip="{_e(tip)}">'
        f'<div class="barre {couleur}" style="width:{max(largeur, 0.6):.1f}%"></div>'
        f'<span class="val">{_e(valeur)}{marque}</span></div>'
    )


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --fond:#f4f6f9;
  --verre:rgba(255,255,255,.72);
  --verre-haut:rgba(255,255,255,.86);
  --bord:rgba(9,14,24,.08);
  --ink:#0a0d12; --ink-2:#59606b; --ink-3:#98a0ac;
  --data:#2a78d6; --gap:#d03b3b; --neutre:#c4cbd4;
  --ombre:0 1px 2px rgba(9,14,24,.04), 0 10px 30px -12px rgba(9,14,24,.16);
  --ombre-h:0 1px 2px rgba(9,14,24,.05), 0 18px 44px -14px rgba(9,14,24,.22);
  --h0:#eaf1fb; --h1:#cde2fb; --h2:#9ec5f4; --h3:#5598e7; --h4:#2a78d6; --h5:#184f95;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;
  --fond:#08090c;
  --verre:rgba(28,31,38,.62); --verre-haut:rgba(36,40,48,.78);
  --bord:rgba(255,255,255,.09);
  --ink:#f2f4f8; --ink-2:#a2aab6; --ink-3:#6b7482;
  --data:#3987e5; --gap:#e05a5a; --neutre:#39404b;
  --ombre:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -12px rgba(0,0,0,.6);
  --ombre-h:0 1px 2px rgba(0,0,0,.5), 0 18px 44px -14px rgba(0,0,0,.7);
  --h0:#151a24; --h1:#16304f; --h2:#1c4a7d; --h3:#2568ac; --h4:#3987e5; --h5:#79b2f0;
}}
:root[data-theme="dark"]{
  color-scheme:dark;
  --fond:#08090c;
  --verre:rgba(28,31,38,.62); --verre-haut:rgba(36,40,48,.78);
  --bord:rgba(255,255,255,.09);
  --ink:#f2f4f8; --ink-2:#a2aab6; --ink-3:#6b7482;
  --data:#3987e5; --gap:#e05a5a; --neutre:#39404b;
  --ombre:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -12px rgba(0,0,0,.6);
  --ombre-h:0 1px 2px rgba(0,0,0,.5), 0 18px 44px -14px rgba(0,0,0,.7);
  --h0:#151a24; --h1:#16304f; --h2:#1c4a7d; --h3:#2568ac; --h4:#3987e5; --h5:#79b2f0;
}

body{margin:0; background:var(--fond); color:var(--ink); min-height:100vh;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; font-size:14px;
  line-height:1.5; -webkit-font-smoothing:antialiased}
/* Lueur ambiante tres faible : c'est elle qui donne au verre depoli quelque
   chose a flouter. Sans elle, l'effet de matiere n'existe pas. */
body::before{content:""; position:fixed; inset:-25%; z-index:0; pointer-events:none;
  background:
    radial-gradient(38% 38% at 16% 10%, rgba(42,120,214,.16), transparent 70%),
    radial-gradient(34% 34% at 86% 6%, rgba(28,170,190,.12), transparent 70%),
    radial-gradient(44% 38% at 66% 96%, rgba(42,120,214,.10), transparent 70%);
  filter:blur(30px)}

.app{position:relative; z-index:1; display:grid;
  grid-template-columns:236px minmax(0,1fr); min-height:100vh}

/* ---------------------------------------------------------------- colonne */
.rail{padding:26px 18px; display:flex; flex-direction:column; gap:26px;
  border-right:1px solid var(--bord); position:sticky; top:0; height:100vh}
.logo{display:flex; align-items:center; gap:10px; font-size:15px; font-weight:650;
  letter-spacing:-.015em}
.logo i{width:26px; height:26px; border-radius:9px; flex:none;
  background:linear-gradient(145deg,var(--data),#1c5cab); box-shadow:var(--ombre)}
.logo small{display:block; font-size:11px; font-weight:400; color:var(--ink-3);
  letter-spacing:0; margin-top:1px}
nav{display:flex; flex-direction:column; gap:2px}
.nav{appearance:none; background:none; border:0; text-align:left; font:inherit;
  color:var(--ink-2); padding:9px 12px; border-radius:10px; cursor:pointer;
  display:flex; align-items:center; gap:10px; transition:background .12s}
.nav:hover{background:var(--verre)}
.nav[aria-selected="true"]{background:var(--verre-haut); color:var(--ink);
  font-weight:550; box-shadow:var(--ombre)}
.nav:focus-visible{outline:2px solid var(--data); outline-offset:2px}
.nav b{width:6px; height:6px; border-radius:50%; background:var(--ink-3); flex:none}
.nav[aria-selected="true"] b{background:var(--data)}
.rail .bas{margin-top:auto; display:flex; flex-direction:column; gap:10px;
  font-size:12px; color:var(--ink-3)}
.selclient{font:inherit; font-size:13px; color:var(--ink); width:100%;
  background:var(--verre); border:1px solid var(--bord); border-radius:10px; padding:8px 10px}
.puce{display:inline-block; padding:7px 11px; border-radius:10px; background:var(--verre);
  border:1px solid var(--bord); font-size:13px; color:var(--ink); font-weight:550}

/* ------------------------------------------------------------------ grille */
main{padding:26px 30px 60px; min-width:0}
@media(max-width:900px){
  .app{grid-template-columns:1fr}
  .rail{position:static; height:auto; border-right:0; border-bottom:1px solid var(--bord);
    flex-direction:row; align-items:center; gap:16px; flex-wrap:wrap}
  .rail nav{flex-direction:row} .rail .bas{margin:0; flex-direction:row; align-items:center}
  main{padding:20px}
}
.grille{display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px}
.c4{grid-column:span 4} .c5{grid-column:span 5} .c6{grid-column:span 6}
.c7{grid-column:span 7} .c8{grid-column:span 8} .c12{grid-column:span 12}
@media(max-width:1080px){.c4,.c5,.c6,.c7,.c8{grid-column:span 12}}

.carte{background:var(--verre); backdrop-filter:blur(26px) saturate(1.7);
  -webkit-backdrop-filter:blur(26px) saturate(1.7);
  border:1px solid var(--bord); border-radius:20px; padding:20px 22px;
  box-shadow:var(--ombre); transition:box-shadow .18s, transform .18s}
.carte:hover{box-shadow:var(--ombre-h)}
.carte.forte{background:var(--verre-haut)}
.tete{display:flex; align-items:baseline; gap:10px; margin:0 0 16px}
.tete h2{font-size:12.5px; font-weight:600; margin:0; letter-spacing:-.005em}
.tete em{font-style:normal; font-size:11.5px; color:var(--ink-3); margin-left:auto;
  font-variant-numeric:tabular-nums}
.aide{width:15px; height:15px; border-radius:50%; border:1px solid var(--bord);
  color:var(--ink-3); font-size:10px; line-height:13px; text-align:center; cursor:help;
  background:none; padding:0; flex:none}
.aide:focus-visible{outline:2px solid var(--data); outline-offset:2px}

/* ------------------------------------------------------------------ jauge */
.jauge{display:flex; align-items:center; gap:22px; flex-wrap:wrap}
.jauge svg{flex:none}
.jauge .txt .n{font-size:52px; font-weight:700; letter-spacing:-.04em; line-height:1}
.jauge .txt .n s{text-decoration:none; font-size:.44em; font-weight:600; margin-left:2px}
.jauge .txt p{margin:6px 0 0; color:var(--ink-2); font-size:13px; max-width:26ch}

.stat .n{font-size:34px; font-weight:680; letter-spacing:-.03em; line-height:1.05}
.stat .sous{font-size:12.5px; color:var(--ink-2); margin-top:6px}
.stat .sous b{color:var(--ink); font-weight:600}

/* ------------------------------------------------------------------ barres */
.rangs{display:flex; flex-direction:column; gap:11px}
.rang{display:grid; grid-template-columns:minmax(84px,132px) 1fr auto; gap:12px;
  align-items:center; font-size:13px}
.rang .lib{color:var(--ink-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.piste{height:10px; border-radius:5px; background:var(--h0); overflow:hidden}
.piste i{display:block; height:100%; border-radius:5px; background:var(--data)}
.piste i.trou{background:var(--gap)}
.rang .v{font-variant-numeric:tabular-nums; color:var(--ink); font-weight:550; min-width:38px;
  text-align:right}

/* ---------------------------------------------------------- barre empilee */
.empile{display:flex; gap:2px; height:34px; border-radius:9px; overflow:hidden; margin-bottom:14px}
.empile span{display:block; background:var(--neutre); transition:filter .12s}
.empile span.moi{background:var(--data)}
.empile span:hover{filter:brightness(1.12)}
.liste{display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:7px 18px;
  font-size:12.5px}
.liste div{display:flex; align-items:center; gap:8px; color:var(--ink-2)}
.liste i{width:8px; height:8px; border-radius:2px; background:var(--neutre); flex:none}
.liste i.moi{background:var(--data)}
.liste b{margin-left:auto; color:var(--ink); font-weight:550; font-variant-numeric:tabular-nums}

/* --------------------------------------------------------------- matrice */
.mat{width:100%; border-collapse:separate; border-spacing:3px; font-size:12px}
.mat th{font-weight:500; color:var(--ink-3); font-size:11px; text-align:center; padding:0 0 4px}
.mat th.g{text-align:left; font-weight:400; color:var(--ink-2)}
.mat td{text-align:center; border-radius:7px; height:30px; color:var(--ink-2);
  font-variant-numeric:tabular-nums; cursor:default}
.mat td.h0{background:var(--h0)} .mat td.h1{background:var(--h1)}
.mat td.h2{background:var(--h2)} .mat td.h3{background:var(--h3); color:#fff}
.mat td.h4{background:var(--h4); color:#fff} .mat td.h5{background:var(--h5); color:#fff}
.mat td.vide{background:var(--h0); color:var(--ink-3)}
.mat .lib{text-align:left; padding-right:10px; color:var(--ink-2); max-width:0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; background:none}
.echelle{display:flex; align-items:center; gap:7px; margin-top:14px; font-size:11.5px;
  color:var(--ink-3)}
.echelle u{text-decoration:none; width:26px; height:9px; border-radius:3px; display:block}

/* ---------------------------------------------------------------- actions */
.todo{display:flex; flex-direction:column; gap:2px}
.todo a{display:grid; grid-template-columns:auto 1fr auto; gap:14px; align-items:center;
  padding:13px 12px; border-radius:12px; text-decoration:none; color:inherit}
.todo a:hover{background:var(--verre-haut)}
.todo .pt{width:8px; height:8px; border-radius:50%; background:var(--gap); flex:none}
.todo .q{font-size:13.5px}
.todo .q s{display:block; text-decoration:none; font-size:12px; color:var(--ink-3); margin-top:2px}
.todo .n{font-size:13px; font-variant-numeric:tabular-nums; color:var(--ink-3)}

/* ------------------------------------------------------------------ table */
.tw{overflow-x:auto; margin:-4px -6px}
table.d{border-collapse:collapse; width:100%; font-size:13px}
table.d th,table.d td{text-align:left; padding:10px 14px; border-bottom:1px solid var(--bord)}
table.d th{font-size:11px; font-weight:600; color:var(--ink-3); letter-spacing:.07em;
  text-transform:uppercase; white-space:nowrap}
table.d td.n{font-variant-numeric:tabular-nums; white-space:nowrap}
table.d tr:last-child td{border-bottom:0}
.mini{display:inline-block; width:52px; height:5px; border-radius:3px; background:var(--h0);
  vertical-align:middle; margin-right:9px; overflow:hidden}
.mini i{display:block; height:100%; background:var(--data); border-radius:3px}
.mini i.trou{background:var(--gap)}
.note{font-size:12.5px; color:var(--ink-2); margin:16px 0 0; max-width:74ch}
[hidden]{display:none!important}

/* --- carte du taux : jauge, chiffre, puis le cap a atteindre --- */
.gros{display:flex; align-items:center; gap:8px; margin-bottom:22px; flex-wrap:wrap}
.gros svg{flex:none; margin-left:-8px}
.chiffre{font-size:56px; font-weight:700; letter-spacing:-.045em; line-height:1}
.chiffre s{text-decoration:none; font-size:.42em; font-weight:600; margin-left:2px}
.gros p{margin:6px 0 0; color:var(--ink-2); font-size:13.5px; max-width:24ch}
.cap .jauge{position:relative; height:8px; border-radius:4px; background:var(--h0)}
.cap .jauge i{display:block; height:100%; border-radius:4px; background:var(--data)}
.cap .jauge u{position:absolute; top:-5px; width:2px; height:18px; border-radius:1px;
  background:var(--ink-3); text-decoration:none}
.cap p{margin:11px 0 0; font-size:12.5px; color:var(--ink-2)}
.cap b{color:var(--ink); font-weight:600}

/* --- carte des reperes --- */
.reperes{display:flex; flex-direction:column; gap:18px}
.reperes>div:not(.tete){display:flex; flex-direction:column; gap:1px}
.reperes span{font-size:11.5px; color:var(--ink-3)}
.reperes b{font-size:26px; font-weight:660; letter-spacing:-.022em; line-height:1.15}
.reperes em{font-style:normal; font-size:11.5px; color:var(--ink-3)}

/* --- barres par moteur : le libelle porte sa propre interpretation --- */
.rang{grid-template-columns:minmax(150px,240px) 1fr auto}
.rang .lib{white-space:normal; line-height:1.3}
.rang .lib s{display:block; text-decoration:none; font-size:11.5px; color:var(--ink-3);
  margin-top:2px}

/* --- tableaux : la colonne d'interpretation est le coeur du produit --- */
table.d td.fort{font-weight:550; color:var(--ink)}
table.d td.lec{color:var(--ink-2); font-size:12.5px; line-height:1.4}
table.d tr.moi td{background:rgba(42,120,214,.08)}
table.d tr.moi td:first-child{border-radius:8px 0 0 8px}
table.d tr.moi td:last-child{border-radius:0 8px 8px 0}
table.d tr.moi td.fort{font-weight:680}
table.d b.rouge{color:var(--gap)}

#tip{position:fixed; z-index:20; pointer-events:none; opacity:0; transform:translateY(3px);
  transition:opacity .12s,transform .12s; background:rgba(10,13,18,.94); color:#fff;
  font-size:12.5px; line-height:1.45; padding:8px 11px; border-radius:9px; max-width:280px;
  box-shadow:0 8px 26px rgba(0,0,0,.28); backdrop-filter:blur(8px)}
#tip.on{opacity:1; transform:translateY(0)}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  var tip=document.getElementById('tip'), cible=null;
  function placer(e){var x=(e.clientX||0)+14,y=(e.clientY||0)+16,r=tip.getBoundingClientRect();
    if(x+r.width>innerWidth-12)x=innerWidth-r.width-12;
    if(y+r.height>innerHeight-12)y=(e.clientY||0)-r.height-12;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function montrer(el,e){tip.textContent=el.getAttribute('data-tip');tip.classList.add('on');
    placer(e||{clientX:0,clientY:0});cible=el;}
  function cacher(){tip.classList.remove('on');cible=null;}
  addEventListener('mouseover',function(e){var el=e.target.closest('[data-tip]');
    if(el&&el!==cible)montrer(el,e);});
  addEventListener('mousemove',function(e){if(cible)placer(e);});
  addEventListener('mouseout',function(e){var r=e.relatedTarget;
    if(cible&&!(r&&r.closest&&r.closest('[data-tip]')))cacher();});
  addEventListener('focusin',function(e){var el=e.target.closest('[data-tip]');if(!el)return;
    var r=el.getBoundingClientRect();montrer(el,{clientX:r.left+30,clientY:r.top});});
  addEventListener('focusout',cacher);
  addEventListener('keydown',function(e){if(e.key==='Escape')cacher();});

  var nav=[].slice.call(document.querySelectorAll('.nav'));
  function activer(id){nav.forEach(function(o){
    var a=o.getAttribute('aria-controls')===id;
    o.setAttribute('aria-selected',a?'true':'false');
    document.getElementById(o.getAttribute('aria-controls')).hidden=!a;});}
  nav.forEach(function(o,i){
    o.addEventListener('click',function(){activer(o.getAttribute('aria-controls'));});
    o.addEventListener('keydown',function(e){
      var d=e.key==='ArrowDown'||e.key==='ArrowRight'?1:
            e.key==='ArrowUp'||e.key==='ArrowLeft'?-1:0;
      if(!d)return; e.preventDefault();
      var n=nav[(i+d+nav.length)%nav.length]; n.focus(); activer(n.getAttribute('aria-controls'));});
  });
})();
"""


def _lecture_moteur(m: dict, tous: list[dict]) -> str:
    """LA colonne qui fait la différence : un chiffre seul ne dit rien, on écrit
    ce qu'il faut en comprendre. C'est le §6 du master, « la valeur n'est pas
    dans le tableau de bord, elle est dans l'interprétation ».
    Aucun outil du marché ne propose cette colonne."""
    if not m["recherche"]:
        return (
            "le modèle ne connaît pas encore la marque sans aller chercher"
            if m["taux"] < 5
            else "le modèle commence à connaître la marque de mémoire"
        )
    avec = [x for x in tous if x["recherche"]]
    if not avec:
        return ""
    meilleur = max(x["taux"] for x in avec)
    pire = min(x["taux"] for x in avec)
    rangs = [x["rang"] for x in avec if x["rang"]]
    if m["taux"] >= meilleur:
        ecart = meilleur - pire
        return "le moteur le plus favorable, et de loin" if ecart > 20 else "le moteur le plus favorable"
    if m["rang"] and rangs and m["rang"] <= min(rangs):
        return f"le plus dur à percer, mais la meilleure place quand la marque y est"
    if m["taux"] <= pire:
        return "le plus difficile à percer"
    if m["rang"]:
        return f"bien placée quand elle y est, rang {m['rang']:.1f}"
    return ""


def _diagnostic(q: dict) -> str:
    """Même principe côté requêtes : un pourcentage bas n'est pas un échec,
    c'est un sujet manquant. On le dit, au lieu de laisser lire un chiffre."""
    if q["taux"] < 1:
        return "aucun contenu sur ce sujet : personne ne cite parce qu'il n'y a rien à citer"
    if q["taux"] < 10:
        return "quasi invisible, alors que la question est posée"
    return "sujet proche de l'offre, mais la marque y est trop peu présente"


def _objectif(taux: float) -> tuple[int, float]:
    """Le palier suivant, par tranches de 10 points : un cap plutôt qu'un
    simple constat, sans inventer d'objectif arbitraire."""
    palier = min(100, (int(taux // 10) + 1) * 10)
    return palier, palier - taux


def _jauge(taux: float) -> str:
    """Demi-cercle : la forme juste pour un ratio unique face à un maximum."""
    longueur = 3.14159 * 84
    return f"""<svg width="188" height="106" viewBox="0 0 196 108" aria-hidden="true">
<path d="M14 100 A84 84 0 0 1 182 100" fill="none" stroke="var(--h0)"
      stroke-width="16" stroke-linecap="round"/>
<path d="M14 100 A84 84 0 0 1 182 100" fill="none" stroke="var(--data)"
      stroke-width="16" stroke-linecap="round"
      stroke-dasharray="{longueur:.1f}" stroke-dashoffset="{longueur * (1 - taux / 100):.1f}"/>
</svg>"""


def _vue_resultats(d: dict) -> str:
    r = d["resume"]
    taux = r["rate"] or 0
    moi = next((v for v in d["voix"] if v["moi"]), None)
    place = next((i for i, v in enumerate(d["voix"], 1) if v["moi"]), None)
    trous = [q for q in d["requetes"] if q["taux"] < SEUIL_TROU]
    forts = [q for q in d["requetes"] if q["taux"] >= 60][:5]
    palier, reste = _objectif(taux)
    n_jours = len(d["serie"])

    def rang_moteur(m: dict) -> str:
        barre = "trou" if m["taux"] < SEUIL_TROU else ""
        nom = NOMS_MOTEURS.get(m["id"], m["id"])
        lecture = _lecture_moteur(m, d["moteurs"])
        tip = f"{nom} : {m['cites']} citations sur {m['ok']} appels"
        if m["rang"]:
            tip += f" · rang moyen {m['rang']:.1f}"
        return (
            f'<div class="rang" data-tip="{_e(tip)}">'
            f'<span class="lib">{_e(nom)}<s>{_e(lecture)}</s></span>'
            f'<span class="piste"><i class="{barre}" style="width:{m["taux"]:.0f}%"></i></span>'
            f'<span class="v">{m["taux"]:.0f}%</span></div>'
        )

    def tr_voix(v: dict) -> str:
        classe = ' class="moi"' if v["moi"] else ""
        note = v["label"] or ("la marque suivie" if v["moi"] else "")
        return (
            f"<tr{classe}><td class=\"fort\">{_e(v['domaine'])}</td>"
            f'<td class="n"><b>{v["part"]:.1f} %</b></td>'
            f'<td class="n">{v["rang"]:.1f}</td>'
            f'<td class="lec">{_e(note)}</td></tr>'
        )

    def tr_ecrire(q: dict) -> str:
        rouge = ' class="rouge"' if q["taux"] < 10 else ""
        return (
            f'<tr><td class="fort">{_e(q["texte"])}</td>'
            f'<td class="n"><b{rouge}>{q["taux"]:.0f} %</b></td>'
            f'<td class="lec">{_e(_diagnostic(q))}</td></tr>'
        )

    moteurs = "".join(rang_moteur(m) for m in d["moteurs"])
    voix = "".join(tr_voix(v) for v in d["voix"][:7])
    ecrire = "".join(tr_ecrire(q) for q in trous) or (
        '<tr><td colspan="3" class="lec">Aucun trou de contenu sur cette collecte.</td></tr>'
    )
    points = "".join(
        f'<tr><td class="fort">{_e(q["texte"])}</td>'
        f'<td class="n"><b>{q["taux"]:.0f} %</b></td></tr>'
        for q in forts
    ) or '<tr><td colspan="2" class="lec">Aucune requête au-dessus de 60 %.</td></tr>'

    part = f"{moi['part']:.1f} %" if moi else "n/d"
    rang_moi = ("1<sup>re</sup>" if place == 1 else f"{place}<sup>e</sup>") if place else "—"
    rang_moyen = f"{r['avg_rank']:.1f}" if r["avg_rank"] else "n/d"
    s_jours = "s" if n_jours > 1 else ""
    s_trous = "s" if len(trous) > 1 else ""

    return f"""<div class="grille">

<div class="carte forte c7">
  <div class="tete"><h2>Taux de citation</h2>
    <button class="aide" data-tip="Une réponse d'IA n'est pas stable : posée trois fois, la même question peut donner trois réponses différentes. Ce taux est mesuré, pas constaté une fois.">?</button>
    <em>{r['n']} appels</em></div>
  <div class="gros">{_jauge(taux)}
    <div><div class="chiffre">{taux:.0f}<s>%</s></div>
      <p>des réponses citent la marque</p></div></div>
  <div class="cap" data-tip="Le palier suivant se calcule par tranches de 10 points : un cap, sans objectif arbitraire.">
    <div class="jauge"><i style="width:{taux:.0f}%"></i><u style="left:{palier}%"></u></div>
    <p><b>+{reste:.0f} points</b> pour atteindre le palier de {palier}&nbsp;%</p>
  </div>
</div>

<div class="carte c5 reperes">
  <div class="tete"><h2>Repères</h2></div>
  <div><span>Part de voix</span><b>{part}</b><em>{rang_moi} position sur {d['domaines_distincts']} domaines cités</em></div>
  <div><span>Rang moyen en source</span><b>{rang_moyen}</b><em>place dans la liste des sources</em></div>
  <div><span>Historique</span><b>{n_jours}</b><em>jour{s_jours} de mesure</em></div>
</div>

<div class="carte c7">
  <div class="tete"><h2>Par moteur</h2>
    <button class="aide" data-tip="La dernière ligne mesure autre chose : le modèle connaît-il la marque sans aller chercher sur le web ?">?</button></div>
  <div class="rangs">{moteurs}</div>
</div>

<div class="carte c5">
  <div class="tete"><h2>Part de voix</h2>
    <em>{d['total_citations']} citations</em></div>
  <div class="tw"><table class="d">
    <tr><th>Domaine</th><th>Part</th><th>Rang</th><th></th></tr>
    {voix}</table></div>
</div>

<div class="carte forte c7">
  <div class="tete"><h2>Ce qu'il faut écrire</h2>
    <button class="aide" data-tip="Une requête où la marque est absente n'est pas un échec : c'est un sujet sur lequel aucun contenu n'existe encore.">?</button>
    <em>{len(trous)} sujet{s_trous}</em></div>
  <div class="tw"><table class="d">
    <tr><th>Requête</th><th>Taux</th><th>Diagnostic</th></tr>
    {ecrire}</table></div>
</div>

<div class="carte c5">
  <div class="tete"><h2>Points forts</h2><em>ce qui a été travaillé se voit</em></div>
  <div class="tw"><table class="d">
    <tr><th>Requête</th><th>Taux</th></tr>
    {points}</table></div>
</div>

</div>"""


def _vue_requetes(d: dict) -> str:
    lignes = "".join(
        f'<tr><td>{_e(q["texte"])}</td><td class="n">{_e(q["id"])}</td>'
        f'<td class="n">{_e(q["type"])}</td>'
        f'<td class="n"><span class="mini"><i class="{"trou" if q["taux"] < SEUIL_TROU else ""}" '
        f'style="width:{q["taux"]:.0f}%"></i></span>{q["taux"]:.0f} %</td>'
        f'<td class="n">{q["cites"]}/{q["ok"]}</td></tr>'
        for q in sorted(d["requetes"], key=lambda x: x["id"])
    )
    return f"""<div class="grille"><div class="carte c12">
  <div class="tete"><h2>Jeu de requêtes</h2>
    <button class="aide" data-tip="Une requête est une question posée comme un humain la pose, pas un mot-clé.">?</button>
    <em>version {d['set_version']} · {len(d['requetes'])} requêtes · {d['n_concurrents']} concurrents suivis</em></div>
  <div class="tw"><table class="d">
    <tr><th>Requête</th><th>Réf.</th><th>Type</th><th>Citation</th><th>Ratio</th></tr>
    {lignes}</table></div>
  <p class="note"><b>Ajouter une requête est sans danger. En modifier ou en retirer une, non.</b>
  Le jeu définit la série temporelle : si une question change en cours de route, les mesures
  d'avant et d'après ne sont plus comparables.</p>
</div></div>"""


def _vue_collectes(d: dict) -> str:
    def ligne(h: dict) -> str:
        t = f'{h["taux"]:.0f} %' if h["taux"] is not None else "—"
        return (
            f'<tr><td class="n">#{h["id"]}</td><td class="n">{_e(h["date"])}</td>'
            f'<td class="n">{h["n"]}</td><td class="n">{h["erreurs"] or "—"}</td>'
            f'<td class="n">{t}</td><td>{_e(h["note"])}</td></tr>'
        )

    return f"""<div class="grille"><div class="carte c12">
  <div class="tete"><h2>Collectes</h2>
    <button class="aide" data-tip="Chaque collecte interroge tous les moteurs sur toutes les requêtes, plusieurs fois. Elle se déclenche automatiquement chaque semaine.">?</button>
    <em>{len(d['historique'])} enregistrées</em></div>
  <div class="tw"><table class="d">
    <tr><th>Réf.</th><th>Date</th><th>Appels</th><th>Erreurs</th><th>Citation</th><th>Note</th></tr>
    {''.join(ligne(h) for h in d['historique'])}</table></div>
  <p class="note"><b>Les réponses brutes sont conservées, horodatées, à chaque appel.</b>
  Les taux se recalculent : si une règle de comptage évolue, tout l'historique est rejoué.
  Une réponse perdue, elle, ne se rattrape pas.</p>
</div></div>"""


def rendu(d: dict) -> str:
    p = d["produit"]
    if len(d["clients"]) > 1:
        options = "".join(
            f'<option{" selected" if c == d["client"] else ""}>{_e(c)}</option>'
            for c in d["clients"]
        )
        choix = f'<select class="selclient" aria-label="Client">{options}</select>'
    else:
        choix = f'<span class="puce">{_e(d["client_label"])}</span>'

    return f"""<div class="app">
<aside class="rail">
  <div class="logo"><i></i><span>{_e(p['nom'])}<small>{_e(p['signature'])}</small></span></div>
  <nav role="tablist" aria-orientation="vertical">
    <button class="nav" role="tab" aria-selected="true"  aria-controls="v-res"><b></b>Résultats</button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-req"><b></b>Requêtes</button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-col"><b></b>Collectes</button>
  </nav>
  <div class="bas">{choix}
    <span>Collecte #{d['run_id']} · {d['date']}</span></div>
</aside>
<main>
  <div id="v-res" role="tabpanel">{_vue_resultats(d)}</div>
  <div id="v-req" role="tabpanel" hidden>{_vue_requetes(d)}</div>
  <div id="v-col" role="tabpanel" hidden>{_vue_collectes(d)}</div>
</main>
</div>
<div id="tip" role="status"></div>
<style>{CSS}</style>
<script>{JS}</script>"""


# ------------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interface du tracker GEO.")
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
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendu(d), encoding="utf-8")
    conn.close()
    print(f"Interface écrite : {out}")
    print(f"  {d['produit']['nom']} · collecte #{run_id} · {d['resume']['n']} appels · "
          f"{(d['resume']['rate'] or 0):.0f} % de citation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
