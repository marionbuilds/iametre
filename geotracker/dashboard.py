"""Génère le tableau de bord HTML à partir des données collectées.

    python -m geotracker.dashboard              # dernier run
    python -m geotracker.dashboard --run 13

Le fichier produit est autonome : aucun script ni police externe, il s'ouvre
partout et se partage tel quel.

Direction artistique imposée (CLAUDE.md §4 du front) : blanc épuré, minimaliste,
type Apple, futuriste. **Interface monochrome, la couleur n'apparaît QUE dans les
données.** C'est ce qui rend le produit rebrandable pour un futur client.
Palette de données validée avec le contrôleur d'accessibilité (bande de
luminosité, plancher de chroma, séparation daltonisme, contraste) : tous les
contrôles passent en clair et en sombre.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

from . import db
from .config import ROOT, load_client
from .report import run_summary

SORTIE = ROOT / "reports" / "dashboard.html"

# Seuil sous lequel une requête est traitée comme un trou de contenu.
# Toujours accompagné d'un libellé écrit : la couleur ne porte jamais seule
# une information (règle d'accessibilité).
SEUIL_TROU = 25.0


# --------------------------------------------------------------------- données

def collecte(conn, run_id: int) -> dict:
    meta = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if meta is None:
        raise SystemExit(f"Run #{run_id} introuvable.")

    resume = run_summary(conn, run_id)

    moteurs = [
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
               FROM responses WHERE run_id=? GROUP BY engine_id
               ORDER BY 4*1.0/MAX(3,1) DESC, engine_id""",
            (run_id,),
        ).fetchall()
    ]
    moteurs.sort(key=lambda m: m["taux"], reverse=True)

    requetes = [
        dict(
            id=r["prompt_id"],
            texte=r["prompt_text"],
            ok=r["ok"] or 0,
            cites=r["cited"] or 0,
            taux=(r["cited"] or 0) / r["ok"] * 100 if r["ok"] else 0,
        )
        for r in conn.execute(
            """SELECT prompt_id, prompt_text,
                      SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS ok,
                      SUM(COALESCE(cited,0)) AS cited
               FROM responses WHERE run_id=? GROUP BY prompt_id""",
            (run_id,),
        ).fetchall()
    ]
    requetes.sort(key=lambda q: q["taux"], reverse=True)

    # ⚠️ Le dénominateur de la part de voix doit couvrir TOUS les domaines cités,
    # pas seulement ceux qu'on affiche. Sinon la part est mécaniquement gonflée
    # par la troncature de l'affichage.
    total = (
        conn.execute(
            """SELECT COUNT(*) n FROM sources s JOIN responses r ON r.id = s.response_id
               WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''""",
            (run_id,),
        ).fetchone()["n"]
        or 1
    )
    lignes = conn.execute(
        """SELECT s.domain, MAX(s.is_target) AS moi, MAX(s.competitor) AS label,
                  COUNT(*) AS n, AVG(s.rank) AS rang
           FROM sources s JOIN responses r ON r.id = s.response_id
           WHERE r.run_id=? AND s.domain IS NOT NULL AND s.domain <> ''
           GROUP BY s.domain ORDER BY n DESC LIMIT 12""",
        (run_id,),
    ).fetchall()
    voix = [
        dict(
            domaine=r["domain"],
            label=r["label"],
            moi=bool(r["moi"]),
            n=r["n"],
            part=r["n"] / total * 100,
            rang=r["rang"],
        )
        for r in lignes
    ]

    # La courbe se compte en JOURS de mesure, pas en runs : plusieurs runs de
    # mise au point le même jour ne font qu'un seul point de série. Sinon le
    # tableau de bord annoncerait un historique qui n'existe pas.
    jours = conn.execute(
        """SELECT DATE(started_at) j, MAX(id) dernier FROM runs
           WHERE client=? GROUP BY DATE(started_at) ORDER BY j""",
        (meta["client"],),
    ).fetchall()
    serie = []
    for ligne in jours:
        taux = run_summary(conn, ligne["dernier"])["rate"]
        if taux is not None:
            serie.append(dict(date=ligne["j"], taux=taux))

    return {
        "run_id": run_id,
        "client": meta["client"],
        "date": meta["started_at"][:10],
        "resume": resume,
        "moteurs": moteurs,
        "requetes": requetes,
        "voix": voix,
        "serie": serie,
    }


# ----------------------------------------------------------------------- rendu

def _e(valeur) -> str:
    return html.escape(str(valeur), quote=True)


def _barre(
    largeur_pct: float, couleur: str, valeur: str, infobulle: str, etiquette: str = ""
) -> str:
    """`etiquette` est un libellé écrit qui double la couleur : une information
    n'est jamais portée par la teinte seule (règle d'accessibilité)."""
    marque = f'<span class="etiq">{_e(etiquette)}</span>' if etiquette else ""
    return (
        f'<div class="piste" tabindex="0" data-tip="{_e(infobulle)}">'
        f'<div class="barre {couleur}" style="width:{max(largeur_pct, 0.6):.1f}%"></div>'
        f'<span class="val">{_e(valeur)}{marque}</span></div>'
    )


NOMS_MOTEURS = {
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "anthropic-memory": "Claude, mémoire de marque",
    "ai_overview": "Google AI Overviews",
}

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --ground:#ffffff; --surface:#f7f8f9;
  --ink:#08090a; --ink-2:#5f646c; --ink-3:#9aa0a8;
  --hairline:rgba(8,9,10,.09);
  --data:#2a78d6; --gap:#d03b3b; --neutre:#c9ced5;
  --pas:8px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --ground:#0a0a0b; --surface:#141417;
    --ink:#f5f5f7; --ink-2:#a2a7af; --ink-3:#6b7079;
    --hairline:rgba(255,255,255,.10);
    --data:#3987e5; --gap:#e05a5a; --neutre:#3a3f47;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --ground:#0a0a0b; --surface:#141417;
  --ink:#f5f5f7; --ink-2:#a2a7af; --ink-3:#6b7079;
  --hairline:rgba(255,255,255,.10);
  --data:#3987e5; --gap:#e05a5a; --neutre:#3a3f47;
}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.page{max-width:1000px; margin:0 auto; padding:72px 28px 120px}
@media(max-width:640px){.page{padding:44px 20px 80px}}

.eyebrow{
  font-size:11px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 28px;
}
.hero{display:flex; flex-wrap:wrap; align-items:flex-end; gap:28px; margin:0 0 12px}
.hero .chiffre{
  font-size:clamp(76px,13vw,132px); font-weight:700; letter-spacing:-.045em;
  line-height:.86; margin:0;
}
.hero .quoi{font-size:17px; color:var(--ink-2); max-width:30ch; margin:0 0 10px}
.sous{color:var(--ink-2); margin:0 0 64px; max-width:70ch}

.kpis{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(178px,1fr));
  gap:calc(var(--pas)*5); padding:32px 0; margin:0 0 72px;
  border-top:1px solid var(--hairline); border-bottom:1px solid var(--hairline);
}
.kpi .k-lab{font-size:12.5px; color:var(--ink-3); margin:0 0 8px}
.kpi .k-val{font-size:33px; font-weight:650; letter-spacing:-.028em; line-height:1.05}
.kpi .k-note{font-size:12.5px; color:var(--ink-2); margin-top:5px}

section{margin:0 0 76px}
h2{font-size:12px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
   color:var(--ink-3); margin:0 0 6px}
.chapo{color:var(--ink-2); margin:0 0 30px; max-width:66ch}

.lignes{display:flex; flex-direction:column; gap:calc(var(--pas)*2.25)}
.ligne{display:grid; grid-template-columns:minmax(150px,264px) 1fr; gap:20px; align-items:center}
@media(max-width:640px){.ligne{grid-template-columns:1fr; gap:6px}}
.nom{font-size:14px; color:var(--ink); overflow-wrap:anywhere}
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

.actions{border-top:1px solid var(--hairline); padding-top:40px}
.action{display:grid; grid-template-columns:auto 1fr; gap:20px; padding:20px 0;
        border-bottom:1px solid var(--hairline)}
.action:last-child{border-bottom:0}
.action .num{font-size:13px; color:var(--ink-3); font-variant-numeric:tabular-nums; padding-top:3px}
.action .txt strong{display:block; font-weight:600; margin-bottom:3px}
.action .txt span{color:var(--ink-2); font-size:14px}

details{margin-top:56px; border-top:1px solid var(--hairline); padding-top:24px}
summary{cursor:pointer; font-size:13px; color:var(--ink-2)}
summary:focus-visible{outline:2px solid var(--data); outline-offset:3px}
.tablewrap{overflow-x:auto; margin-top:20px}
table{border-collapse:collapse; width:100%; font-size:13px}
th,td{text-align:left; padding:9px 16px 9px 0; border-bottom:1px solid var(--hairline);
      white-space:nowrap}
th{font-weight:600; color:var(--ink-3); font-size:11.5px; letter-spacing:.08em;
   text-transform:uppercase}
td.n{font-variant-numeric:tabular-nums}

footer{margin-top:80px; padding-top:26px; border-top:1px solid var(--hairline);
       font-size:12.5px; color:var(--ink-3)}

#tip{position:fixed; z-index:9; pointer-events:none; opacity:0; transform:translateY(3px);
     transition:opacity .12s ease, transform .12s ease;
     background:var(--ink); color:var(--ground); font-size:12.5px; line-height:1.45;
     padding:8px 11px; border-radius:7px; max-width:290px; box-shadow:0 6px 22px rgba(0,0,0,.16)}
#tip.on{opacity:1; transform:translateY(0)}
@media(prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
"""

JS = """
(function(){
  var tip=document.getElementById('tip'), cible=null;
  function placer(e){
    var x=(e.clientX||0)+14, y=(e.clientY||0)+16;
    var r=tip.getBoundingClientRect();
    if(x+r.width>window.innerWidth-12) x=window.innerWidth-r.width-12;
    if(y+r.height>window.innerHeight-12) y=(e.clientY||0)-r.height-12;
    tip.style.left=x+'px'; tip.style.top=y+'px';
  }
  function montrer(el,e){ tip.textContent=el.getAttribute('data-tip');
    tip.classList.add('on'); placer(e||{clientX:0,clientY:0}); cible=el; }
  function cacher(){ tip.classList.remove('on'); cible=null; }
  document.addEventListener('mouseover',function(e){
    var el=e.target.closest('[data-tip]'); if(el&&el!==cible) montrer(el,e); });
  document.addEventListener('mousemove',function(e){ if(cible) placer(e); });
  document.addEventListener('mouseout',function(e){
    if(cible&&!e.relatedTarget?.closest?.('[data-tip]')) cacher(); });
  document.addEventListener('focusin',function(e){
    var el=e.target.closest('[data-tip]'); if(!el) return;
    var r=el.getBoundingClientRect(); montrer(el,{clientX:r.left+40,clientY:r.top}); });
  document.addEventListener('focusout',cacher);
  document.addEventListener('keydown',function(e){ if(e.key==='Escape') cacher(); });
})();
"""


def rendu(d: dict) -> str:
    r = d["resume"]
    taux = r["rate"] or 0
    moi = next((v for v in d["voix"] if v["moi"]), None)
    place_moi = next((i for i, v in enumerate(d["voix"], 1) if v["moi"]), None)
    trous = [q for q in d["requetes"] if q["taux"] < SEUIL_TROU]
    forts = [q for q in d["requetes"] if q["taux"] >= 70]

    # --- moteurs
    lignes_moteurs = []
    for m in d["moteurs"]:
        nom = NOMS_MOTEURS.get(m["id"], m["id"])
        mode = "avec recherche web" if m["recherche"] else "sans recherche, de mémoire"
        rang = f" · rang moyen {m['rang']:.1f}" if m["rang"] else ""
        lignes_moteurs.append(
            f'<div class="ligne"><div class="nom">{_e(nom)}'
            f'<span class="meta">{_e(mode)}</span></div>'
            + _barre(
                m["taux"],
                "trou" if m["taux"] < SEUIL_TROU else "",
                f"{m['taux']:.0f} %",
                f"{nom} : cité {m['cites']} fois sur {m['ok']} appels{rang}",
            )
            + "</div>"
        )

    # --- part de voix
    lignes_voix = []
    for v in d["voix"]:
        etiquette = "  ⬅ toi" if v["moi"] else ""
        sous = v["label"] or ("ta marque" if v["moi"] else "")
        lignes_voix.append(
            f'<div class="ligne"><div class="nom{" moi" if v["moi"] else ""}">{_e(v["domaine"])}'
            + (f'<span class="meta">{_e(sous)}</span>' if sous else "")
            + "</div>"
            + _barre(
                v["part"] / (d["voix"][0]["part"] or 1) * 100,
                "" if v["moi"] else "neutre",
                f"{v['part']:.1f} %",
                f"{v['domaine']} : {v['n']} citations, rang moyen {v['rang']:.1f}{etiquette}",
            )
            + "</div>"
        )

    # --- requêtes
    lignes_req = []
    for q in d["requetes"]:
        trou = q["taux"] < SEUIL_TROU
        lignes_req.append(
            f'<div class="ligne"><div class="nom">{_e(q["texte"])}'
            f'<span class="meta">{_e(q["id"])}</span></div>'
            + _barre(
                q["taux"],
                "trou" if trou else "",
                f"{q['taux']:.0f} %",
                f"{q['texte']} : cité {q['cites']} fois sur {q['ok']} appels",
                etiquette="trou de contenu" if trou else "",
            )
            + "</div>"
        )

    # --- à faire
    actions = []
    for i, q in enumerate(trous, 1):
        actions.append(
            f'<div class="action"><div class="num">{i:02d}</div><div class="txt">'
            f'<strong>{_e(q["texte"])}</strong>'
            f'<span>Citée {q["cites"]} fois sur {q["ok"]}. Personne ne te cite parce '
            f"qu'il n'y a rien à citer : c'est un sujet à écrire.</span></div></div>"
        )
    if not actions:
        actions.append(
            '<div class="action"><div class="num">—</div><div class="txt">'
            "<strong>Aucun trou de contenu sur ce run</strong>"
            "<span>Toutes les requêtes suivies dépassent le seuil.</span></div></div>"
        )

    # --- tableau (accessibilité : toute valeur du graphique existe en texte)
    tab = [
        "<tr><th>Requête</th><th>Taux</th><th>Citée</th><th>Appels</th></tr>",
        *[
            f'<tr><td>{_e(q["texte"])}</td><td class="n">{q["taux"]:.0f} %</td>'
            f'<td class="n">{q["cites"]}</td><td class="n">{q["ok"]}</td></tr>'
            for q in d["requetes"]
        ],
    ]

    part_moi = f"{moi['part']:.1f} %" if moi else "n/d"
    rang_txt = f"{r['avg_rank']:.1f}" if r["avg_rank"] else "n/d"
    n_points = len(d["serie"])
    suivi = (
        "premier point, la courbe démarre"
        if n_points <= 1
        else f"{n_points} jours de mesure, du {d['serie'][0]['date']} à aujourd'hui"
    )
    rang_moi = (
        f"{place_moi}<sup>re</sup>" if place_moi == 1 else f"{place_moi}<sup>e</sup>"
    ) if place_moi else ""

    return f"""<div class="page">
<p class="eyebrow">Tracker GEO · {_e(d['client'])} · {_e(d['date'])}</p>

<div class="hero">
  <p class="chiffre">{taux:.0f}<span style="font-size:.42em;font-weight:600">&#8239;%</span></p>
  <p class="quoi">des réponses d'IA testées citent la marque</p>
</div>
<p class="sous">Une réponse d'IA n'est pas stable&nbsp;: posée trois fois, la même question
peut donner trois réponses différentes. On ne constate donc pas une visibilité, on
l'échantillonne. Ce chiffre est un taux mesuré sur
<strong>{r['n']} appels</strong> répartis sur {len(d['moteurs'])} moteurs.</p>

<div class="kpis">
  <div class="kpi"><p class="k-lab">Part de voix</p>
    <div class="k-val">{part_moi}</div>
    <p class="k-note">{f"{rang_moi} position parmi les domaines cités" if place_moi else "&nbsp;"}</p></div>
  <div class="kpi"><p class="k-lab">Rang moyen en source</p>
    <div class="k-val">{rang_txt}</div>
    <p class="k-note">place dans la liste des sources citées</p></div>
  <div class="kpi"><p class="k-lab">Appels</p>
    <div class="k-val">{r['n']}</div>
    <p class="k-note">{r['errors']} erreur{'s' if r['errors'] > 1 else ''}</p></div>
  <div class="kpi"><p class="k-lab">Historique</p>
    <div class="k-val">{n_points}</div>
    <p class="k-note">{suivi}</p></div>

</div>

<section>
  <h2>Par moteur</h2>
  <p class="chapo">Tous les moteurs ne se valent pas. La dernière ligne mesure autre chose&nbsp;:
  la marque est-elle connue <em>sans</em> aller chercher sur le web&nbsp;? C'est l'indicateur
  le plus lent à bouger, et celui que les outils du marché ne mesurent pas.</p>
  <div class="lignes">{''.join(lignes_moteurs)}</div>
</section>

<section>
  <h2>Part de voix</h2>
  <p class="chapo">Qui occupe la place quand ce n'est pas toi. Calculé sur l'ensemble des
  sources citées par les moteurs pendant ce run.</p>
  <div class="lignes">{''.join(lignes_voix)}</div>
  <div class="legende">
    <span><i class="pastille p-data"></i>Ta marque</span>
    <span><i class="pastille p-neutre"></i>Autres domaines cités</span>
  </div>
</section>

<section>
  <h2>Par requête</h2>
  <p class="chapo">{len(forts)} requête{'s' if len(forts) > 1 else ''} au-dessus de 70&nbsp;%,
  {len(trous)} sous {SEUIL_TROU:.0f}&nbsp;%. Les secondes ne sont pas un échec&nbsp;: ce sont
  les sujets sur lesquels il n'existe rien à citer.</p>
  <div class="lignes">{''.join(lignes_req)}</div>
  <div class="legende">
    <span><i class="pastille p-data"></i>Visible</span>
    <span><i class="pastille p-trou"></i>Trou de contenu (sous {SEUIL_TROU:.0f}&nbsp;%)</span>
  </div>
</section>

<section class="actions">
  <h2>Ce qu'il faut écrire</h2>
  <p class="chapo">La valeur n'est pas dans le tableau de bord, elle est dans la correction.
  Voici les sujets où la marque est absente des réponses.</p>
  {''.join(actions)}
</section>

<details>
  <summary>Voir toutes les valeurs sous forme de tableau</summary>
  <div class="tablewrap"><table>{''.join(tab)}</table></div>
</details>

<footer>Run #{d['run_id']} · {r['ok']}/{r['n']} appels aboutis ·
généré le {datetime.now().strftime('%d/%m/%Y')} par le tracker GEO.
Les réponses brutes de chaque appel sont conservées horodatées.</footer>
</div>
<div id="tip" role="status"></div>
<style>{CSS}</style>
<script>{JS}</script>"""


# ------------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tracker GEO : tableau de bord HTML.")
    p.add_argument("--client", default="smart-bpjeps")
    p.add_argument("--run", type=int, help="id du run (défaut : le dernier)")
    p.add_argument("--db", default=str(db.DEFAULT_DB))
    p.add_argument("--out", default=str(SORTIE))
    args = p.parse_args(argv)

    conn = db.connect(args.db)
    run_id = args.run
    if run_id is None:
        ligne = conn.execute(
            "SELECT id FROM runs WHERE client=? ORDER BY id DESC LIMIT 1", (args.client,)
        ).fetchone()
        if ligne is None:
            print("Aucun run enregistré. Lance : python -m geotracker.run")
            return 1
        run_id = ligne["id"]

    donnees = collecte(conn, run_id)
    sortie = Path(args.out)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(rendu(donnees), encoding="utf-8")
    conn.close()

    print(f"Tableau de bord écrit : {sortie}")
    print(f"  run #{run_id} · {donnees['resume']['n']} appels · "
          f"{(donnees['resume']['rate'] or 0):.0f} % de citation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
