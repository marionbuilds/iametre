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
  --ground:#ffffff; --voile:#f6f7f8;
  --ink:#08090a; --ink-2:#5f646c; --ink-3:#9aa0a8;
  --hairline:rgba(8,9,10,.09);
  --data:#2a78d6; --gap:#d03b3b; --neutre:#c9ced5;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --ground:#0a0a0b; --voile:#141417;
    --ink:#f5f5f7; --ink-2:#a2a7af; --ink-3:#6b7079;
    --hairline:rgba(255,255,255,.10);
    --data:#3987e5; --gap:#e05a5a; --neutre:#3a3f47;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --ground:#0a0a0b; --voile:#141417;
  --ink:#f5f5f7; --ink-2:#a2a7af; --ink-3:#6b7079;
  --hairline:rgba(255,255,255,.10);
  --data:#3987e5; --gap:#e05a5a; --neutre:#3a3f47;
}
body{margin:0; background:var(--ground); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased}

.bandeau{position:sticky; top:0; z-index:5; background:var(--ground);
  border-bottom:1px solid var(--hairline)}
.bandeau .dedans{max-width:1040px; margin:0 auto; padding:18px 28px;
  display:flex; align-items:baseline; gap:18px; flex-wrap:wrap}
.marque{font-size:15px; font-weight:650; letter-spacing:-.012em}
.marque em{font-style:normal; font-weight:400; color:var(--ink-3);
  font-size:12.5px; margin-left:12px; letter-spacing:0}
.spacer{flex:1 1 auto}
.client{display:inline-flex; align-items:center; gap:9px; font-size:13px; color:var(--ink-2)}
.client select{font:inherit; color:var(--ink); background:var(--voile);
  border:1px solid var(--hairline); border-radius:7px; padding:5px 9px}
.puce{display:inline-block; padding:4px 10px; border-radius:7px;
  background:var(--voile); font-size:13px; color:var(--ink); font-weight:550}

.onglets{max-width:1040px; margin:0 auto; padding:0 28px;
  display:flex; gap:26px; border-bottom:1px solid var(--hairline)}
.onglet{appearance:none; background:none; border:0; padding:15px 0 13px;
  font:inherit; font-size:14px; color:var(--ink-3); cursor:pointer;
  border-bottom:2px solid transparent; margin-bottom:-1px}
.onglet[aria-selected="true"]{color:var(--ink); border-bottom-color:var(--ink)}
.onglet:focus-visible{outline:2px solid var(--data); outline-offset:3px; border-radius:3px}

.page{max-width:1040px; margin:0 auto; padding:60px 28px 120px}
@media(max-width:640px){.page{padding:40px 20px 80px} .bandeau .dedans{padding:16px 20px}
  .onglets{padding:0 20px; gap:18px; overflow-x:auto}}
[hidden]{display:none!important}

.hero{display:flex; flex-wrap:wrap; align-items:flex-end; gap:28px; margin:0 0 12px}
.hero .chiffre{font-size:clamp(72px,12vw,124px); font-weight:700;
  letter-spacing:-.045em; line-height:.86; margin:0}
.hero .quoi{font-size:17px; color:var(--ink-2); max-width:30ch; margin:0 0 10px}
.sous{color:var(--ink-2); margin:0 0 60px; max-width:70ch}

.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(176px,1fr)); gap:40px;
  padding:30px 0; margin:0 0 68px;
  border-top:1px solid var(--hairline); border-bottom:1px solid var(--hairline)}
.k-lab{font-size:12.5px; color:var(--ink-3); margin:0 0 8px}
.k-val{font-size:32px; font-weight:650; letter-spacing:-.028em; line-height:1.05}
.k-note{font-size:12.5px; color:var(--ink-2); margin-top:5px}

section{margin:0 0 72px}
h2{font-size:12px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 6px}
.chapo{color:var(--ink-2); margin:0 0 28px; max-width:66ch}

.lignes{display:flex; flex-direction:column; gap:18px}
.ligne{display:grid; grid-template-columns:minmax(150px,272px) 1fr; gap:20px; align-items:center}
@media(max-width:640px){.ligne{grid-template-columns:1fr; gap:6px}}
.nom{font-size:14px; overflow-wrap:anywhere}
.nom .meta{display:block; font-size:12px; color:var(--ink-3)}
.piste{position:relative; display:flex; align-items:center; gap:11px;
  min-height:24px; border-radius:3px; outline:none}
.piste:focus-visible{box-shadow:0 0 0 2px var(--ground),0 0 0 4px var(--data)}
.barre{height:12px; border-radius:0 4px 4px 0; background:var(--data)}
.barre.neutre{background:var(--neutre)}
.barre.trou{background:var(--gap)}
.val{font-size:13px; color:var(--ink-2); font-variant-numeric:tabular-nums; white-space:nowrap}
.etiq{display:inline-block; margin-left:9px; font-size:11px; font-weight:600;
  letter-spacing:.06em; text-transform:uppercase; color:var(--gap)}
.moi{font-weight:650}

.legende{display:flex; flex-wrap:wrap; gap:20px; margin:24px 0 0;
  font-size:12.5px; color:var(--ink-2)}
.legende span{display:inline-flex; align-items:center; gap:8px}
.pastille{width:11px; height:11px; border-radius:2.5px; flex:none}
.p-data{background:var(--data)} .p-neutre{background:var(--neutre)} .p-trou{background:var(--gap)}

.actions{border-top:1px solid var(--hairline); padding-top:38px}
.action{display:grid; grid-template-columns:auto 1fr; gap:20px; padding:20px 0;
  border-bottom:1px solid var(--hairline)}
.action:last-child{border-bottom:0}
.action .num{font-size:13px; color:var(--ink-3); font-variant-numeric:tabular-nums; padding-top:3px}
.action .txt strong{display:block; font-weight:600; margin-bottom:3px}
.action .txt span{color:var(--ink-2); font-size:14px}

.tablewrap{overflow-x:auto}
table{border-collapse:collapse; width:100%; font-size:13.5px}
th,td{text-align:left; padding:11px 18px 11px 0; border-bottom:1px solid var(--hairline)}
th{font-weight:600; color:var(--ink-3); font-size:11.5px; letter-spacing:.08em;
  text-transform:uppercase; white-space:nowrap}
td.n{font-variant-numeric:tabular-nums; white-space:nowrap}
td.q{min-width:290px}
.jauge{display:inline-block; width:64px; height:6px; border-radius:3px;
  background:var(--voile); overflow:hidden; vertical-align:middle; margin-right:10px}
.jauge i{display:block; height:100%; background:var(--data); border-radius:3px}
.jauge i.trou{background:var(--gap)}

.encart{background:var(--voile); border-radius:12px; padding:22px 24px; margin:36px 0 0;
  color:var(--ink-2); font-size:14px; max-width:72ch}
.encart strong{color:var(--ink)}
details{margin-top:48px; border-top:1px solid var(--hairline); padding-top:22px}
summary{cursor:pointer; font-size:13px; color:var(--ink-2)}
summary:focus-visible{outline:2px solid var(--data); outline-offset:3px}
footer{margin-top:76px; padding-top:24px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-3)}

#tip{position:fixed; z-index:9; pointer-events:none; opacity:0; transform:translateY(3px);
  transition:opacity .12s ease,transform .12s ease; background:var(--ink); color:var(--ground);
  font-size:12.5px; line-height:1.45; padding:8px 11px; border-radius:7px; max-width:290px;
  box-shadow:0 6px 22px rgba(0,0,0,.16)}
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
  function montrer(el,e){tip.textContent=el.getAttribute('data-tip');
    tip.classList.add('on');placer(e||{clientX:0,clientY:0});cible=el;}
  function cacher(){tip.classList.remove('on');cible=null;}
  addEventListener('mouseover',function(e){var el=e.target.closest('[data-tip]');
    if(el&&el!==cible)montrer(el,e);});
  addEventListener('mousemove',function(e){if(cible)placer(e);});
  addEventListener('mouseout',function(e){
    if(cible&&!(e.relatedTarget&&e.relatedTarget.closest&&e.relatedTarget.closest('[data-tip]')))cacher();});
  addEventListener('focusin',function(e){var el=e.target.closest('[data-tip]');if(!el)return;
    var r=el.getBoundingClientRect();montrer(el,{clientX:r.left+40,clientY:r.top});});
  addEventListener('focusout',cacher);
  addEventListener('keydown',function(e){if(e.key==='Escape')cacher();});

  var onglets=[].slice.call(document.querySelectorAll('.onglet'));
  function activer(id){
    onglets.forEach(function(o){
      var actif=o.getAttribute('aria-controls')===id;
      o.setAttribute('aria-selected',actif?'true':'false');
      document.getElementById(o.getAttribute('aria-controls')).hidden=!actif;
    });
  }
  onglets.forEach(function(o,i){
    o.addEventListener('click',function(){activer(o.getAttribute('aria-controls'));});
    o.addEventListener('keydown',function(e){
      var d=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0; if(!d)return;
      e.preventDefault(); var n=onglets[(i+d+onglets.length)%onglets.length];
      n.focus(); activer(n.getAttribute('aria-controls'));
    });
  });
})();
"""


def _vue_resultats(d: dict) -> str:
    r = d["resume"]
    taux = r["rate"] or 0
    moi = next((v for v in d["voix"] if v["moi"]), None)
    place = next((i for i, v in enumerate(d["voix"], 1) if v["moi"]), None)
    trous = [q for q in d["requetes"] if q["taux"] < SEUIL_TROU]
    forts = [q for q in d["requetes"] if q["taux"] >= 70]

    moteurs = "".join(
        f'<div class="ligne"><div class="nom">{_e(NOMS_MOTEURS.get(m["id"], m["id"]))}'
        f'<span class="meta">{"avec recherche web" if m["recherche"] else "sans recherche, de mémoire"}'
        f"</span></div>"
        + _barre(
            m["taux"],
            "trou" if m["taux"] < SEUIL_TROU else "",
            f"{m['taux']:.0f} %",
            f"{NOMS_MOTEURS.get(m['id'], m['id'])} : {m['cites']} citations sur {m['ok']} appels"
            + (f" · rang moyen {m['rang']:.1f}" if m["rang"] else ""),
        )
        + "</div>"
        for m in d["moteurs"]
    )

    tete = d["voix"][0]["part"] if d["voix"] else 1
    voix = "".join(
        f'<div class="ligne"><div class="nom{" moi" if v["moi"] else ""}">{_e(v["domaine"])}'
        + (
            f'<span class="meta">{_e(v["label"] or ("la marque suivie" if v["moi"] else ""))}</span>'
            if (v["label"] or v["moi"])
            else ""
        )
        + "</div>"
        + _barre(
            v["part"] / (tete or 1) * 100,
            "" if v["moi"] else "neutre",
            f"{v['part']:.1f} %",
            f"{v['domaine']} : {v['n']} citations, rang moyen {v['rang']:.1f}",
        )
        + "</div>"
        for v in d["voix"]
    )

    requetes = "".join(
        f'<div class="ligne"><div class="nom">{_e(q["texte"])}'
        f'<span class="meta">{_e(q["id"])}</span></div>'
        + _barre(
            q["taux"],
            "trou" if q["taux"] < SEUIL_TROU else "",
            f"{q['taux']:.0f} %",
            f"{q['texte']} : {q['cites']} citations sur {q['ok']} appels",
            etiquette="trou de contenu" if q["taux"] < SEUIL_TROU else "",
        )
        + "</div>"
        for q in d["requetes"]
    )

    actions = "".join(
        f'<div class="action"><div class="num">{i:02d}</div><div class="txt">'
        f'<strong>{_e(q["texte"])}</strong><span>Citée {q["cites"]} fois sur {q["ok"]}. '
        f"La marque est absente parce qu'aucun contenu ne répond à cette question&nbsp;: "
        f"c'est un sujet à écrire.</span></div></div>"
        for i, q in enumerate(trous, 1)
    ) or (
        '<div class="action"><div class="num">—</div><div class="txt">'
        "<strong>Aucun trou de contenu sur cette collecte</strong>"
        "<span>Toutes les requêtes suivies dépassent le seuil.</span></div></div>"
    )

    part = f"{moi['part']:.1f} %" if moi else "n/d"
    rang = f"{r['avg_rank']:.1f}" if r["avg_rank"] else "n/d"
    rang_moi = ("1<sup>re</sup>" if place == 1 else f"{place}<sup>e</sup>") if place else ""
    n_jours = len(d["serie"])
    suivi = (
        "première collecte, la courbe démarre"
        if n_jours <= 1
        else f"{n_jours} jours de mesure depuis le {d['serie'][0]['date']}"
    )

    return f"""
<div class="hero">
  <p class="chiffre">{taux:.0f}<span style="font-size:.42em;font-weight:600">&#8239;%</span></p>
  <p class="quoi">des réponses d'IA testées citent la marque</p>
</div>
<p class="sous">Une réponse d'IA n'est pas stable&nbsp;: posée trois fois, la même question
peut donner trois réponses différentes. On ne constate donc pas une visibilité, on
l'échantillonne. Ce taux est mesuré sur <strong>{r['n']} appels</strong> répartis sur
{len(d['moteurs'])} moteurs.</p>

<div class="kpis">
  <div><p class="k-lab">Part de voix</p><div class="k-val">{part}</div>
    <p class="k-note">{f"{rang_moi} position sur {d['domaines_distincts']} domaines cités" if place else "&nbsp;"}</p></div>
  <div><p class="k-lab">Rang moyen en source</p><div class="k-val">{rang}</div>
    <p class="k-note">place dans la liste des sources</p></div>
  <div><p class="k-lab">Appels</p><div class="k-val">{r['n']}</div>
    <p class="k-note">{r['errors']} erreur{'s' if r['errors'] > 1 else ''}</p></div>
  <div><p class="k-lab">Historique</p><div class="k-val">{n_jours}</div>
    <p class="k-note">{suivi}</p></div>
</div>

<section><h2>Par moteur</h2>
<p class="chapo">Tous les moteurs ne se valent pas. La ligne « mémoire de marque » mesure
autre chose&nbsp;: le modèle connaît-il la marque <em>sans</em> aller chercher sur le web&nbsp;?
C'est l'indicateur le plus lent à bouger, et celui que les outils du marché ne mesurent pas.</p>
<div class="lignes">{moteurs}</div></section>

<section><h2>Part de voix</h2>
<p class="chapo">Qui occupe la place quand ce n'est pas la marque. Calculé sur les
{d['total_citations']} citations relevées pendant la collecte, réparties sur
{d['domaines_distincts']} domaines.</p>
<div class="lignes">{voix}</div>
<div class="legende">
  <span><i class="pastille p-data"></i>La marque suivie</span>
  <span><i class="pastille p-neutre"></i>Autres domaines cités</span>
</div></section>

<section><h2>Par requête</h2>
<p class="chapo">{len(forts)} requête{'s' if len(forts) > 1 else ''} au-dessus de 70&nbsp;%,
{len(trous)} sous {SEUIL_TROU:.0f}&nbsp;%. Les secondes ne sont pas un échec&nbsp;: ce sont
les sujets sur lesquels il n'existe rien à citer.</p>
<div class="lignes">{requetes}</div>
<div class="legende">
  <span><i class="pastille p-data"></i>Visible</span>
  <span><i class="pastille p-trou"></i>Trou de contenu (sous {SEUIL_TROU:.0f}&nbsp;%)</span>
</div></section>

<section class="actions"><h2>Ce qu'il faut écrire</h2>
<p class="chapo">La valeur n'est pas dans le tableau de bord, elle est dans la correction.
Voici les sujets sur lesquels la marque est absente des réponses.</p>
{actions}</section>"""


def _vue_requetes(d: dict) -> str:
    lignes = "".join(
        f'<tr><td class="q">{_e(q["texte"])}</td>'
        f'<td class="n">{_e(q["id"])}</td><td class="n">{_e(q["type"])}</td>'
        f'<td class="n"><span class="jauge"><i class="{"trou" if q["taux"] < SEUIL_TROU else ""}" '
        f'style="width:{q["taux"]:.0f}%"></i></span>{q["taux"]:.0f} %</td>'
        f'<td class="n">{q["cites"]}/{q["ok"]}</td></tr>'
        for q in sorted(d["requetes"], key=lambda x: x["id"])
    )
    return f"""
<h2>Le jeu de requêtes</h2>
<p class="chapo">Ce que les moteurs sont interrogés sur, à chaque collecte. Une requête
est une <em>question posée comme un humain la pose</em>, pas un mot-clé.</p>
<div class="tablewrap"><table>
<tr><th>Requête</th><th>Réf.</th><th>Type</th><th>Taux de citation</th><th>Citée</th></tr>
{lignes}</table></div>
<div class="encart">
<strong>Ajouter une requête est sans danger. En modifier ou en retirer une, non.</strong><br>
Le jeu de requêtes définit la série temporelle&nbsp;: si une question change en cours de
route, les mesures d'avant et d'après ne sont plus comparables. Les ajouts se cumulent
sans rien casser&nbsp;; toute modification passe par une nouvelle version du jeu.
Jeu actuel&nbsp;: <strong>version&nbsp;{d['set_version']}</strong>, {len(d['requetes'])}&nbsp;requêtes,
{d['n_concurrents']}&nbsp;concurrents suivis.
</div>"""


def _vue_collectes(d: dict) -> str:
    def ligne(h: dict) -> str:
        taux = f"{h['taux']:.0f} %" if h["taux"] is not None else "—"
        return (
            f'<tr><td class="n">#{h["id"]}</td><td class="n">{_e(h["date"])}</td>'
            f'<td class="n">{h["n"]}</td><td class="n">{h["erreurs"] or "—"}</td>'
            f'<td class="n">{taux}</td><td>{_e(h["note"])}</td></tr>'
        )

    lignes = "".join(ligne(h) for h in d["historique"])
    return f"""
<h2>Les collectes</h2>
<p class="chapo">Chaque collecte interroge tous les moteurs sur toutes les requêtes,
plusieurs fois, puis enregistre les réponses. Elle se déclenche automatiquement chaque
semaine&nbsp;; les collectes courtes ci-dessous sont des essais de mise au point.</p>
<div class="tablewrap"><table>
<tr><th>Réf.</th><th>Date</th><th>Appels</th><th>Erreurs</th><th>Citation</th><th>Note</th></tr>
{lignes}</table></div>
<div class="encart">
<strong>Les réponses brutes sont conservées, horodatées, à chaque appel.</strong><br>
Les taux affichés se recalculent&nbsp;: si une règle de comptage évolue, tout l'historique
est rejoué. Une réponse perdue, elle, ne se rattrape pas. C'est aussi ce qui construit la
valeur du suivi&nbsp;: au bout de six mois, la courbe ne se refait pas depuis zéro.
</div>"""


def rendu(d: dict) -> str:
    p = d["produit"]
    if len(d["clients"]) > 1:
        options = "".join(
            f'<option{" selected" if c == d["client"] else ""}>{_e(c)}</option>'
            for c in d["clients"]
        )
        choix = f'<label class="client">Client <select>{options}</select></label>'
    else:
        choix = f'<span class="client">Client <span class="puce">{_e(d["client_label"])}</span></span>'

    return f"""<div class="bandeau"><div class="dedans">
  <span class="marque">{_e(p['nom'])}<em>{_e(p['signature'])}</em></span>
  <span class="spacer"></span>{choix}
</div></div>
<div class="onglets" role="tablist">
  <button class="onglet" role="tab" aria-selected="true"  aria-controls="v-res">Résultats</button>
  <button class="onglet" role="tab" aria-selected="false" aria-controls="v-req">Requêtes</button>
  <button class="onglet" role="tab" aria-selected="false" aria-controls="v-col">Collectes</button>
</div>
<div class="page">
  <div id="v-res" role="tabpanel">{_vue_resultats(d)}</div>
  <div id="v-req" role="tabpanel" hidden>{_vue_requetes(d)}</div>
  <div id="v-col" role="tabpanel" hidden>{_vue_collectes(d)}</div>
  <footer>Collecte #{d['run_id']} · {d['resume']['ok']}/{d['resume']['n']} appels aboutis ·
  généré le {datetime.now().strftime('%d/%m/%Y')} par {_e(p['nom'])}.</footer>
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
