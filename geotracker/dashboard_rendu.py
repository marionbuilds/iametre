"""Couche rendu de l'interface d'IAmètre.

Reçoit le dictionnaire produit par `dashboard_donnees` (contrat dans
ARCHITECTURE.md §3) et retourne du HTML. Cette couche ne touche ni à SQLite,
ni aux YAML, ni au système de fichiers, et n'importe rien du projet hors du
module neutre `format` : elle est remplaçable sans toucher à la couche
données. Une fonction par bloc visuel ; chacune reçoit SA portion du
dictionnaire et rien d'autre, et s'appelle avec un dictionnaire écrit à la
main, sans base présente.

Répartition des rôles (ARCHITECTURE.md §2) : les nombres arrivent bruts et
prennent leur forme française ici (`nb`), les guillemets français sont posés
ici (`_cite`), l'échappement HTML se fait ici à l'insertion (`_e`), la
géométrie (SVG, jauges, largeurs de barres) se calcule ici. Les phrases
d'interprétation, elles, arrivent toutes faites : elles portent une décision
de sens, qui appartient à la couche données.
"""

from __future__ import annotations

import html

from .format import nb as _nb, points as _points


def _cite(texte: str) -> str:
    """Guillemets français avec espaces fines insécables : évite le guillemet
    fermant orphelin en bas de ligne, et respecte la typographie française."""
    fine = "&#8239;"
    return f"«{fine}{_e(texte)}{fine}»"


def _e(v) -> str:
    return html.escape(str(v), quote=True)


# ------------------------------------------------------------ marques moteurs
#
# Les logos sont écrits EN DUR, en SVG, et jamais chargés depuis un CDN : le
# fichier doit s'ouvrir hors ligne (règle de DA), et un logo qui ne charge pas
# casse la lecture d'une carte dont il est le point d'entrée visuel.
#
# Les couleurs de marque sont assumées (Marion, 10/08/2026) : c'est la forme
# ET la couleur qui font qu'on trouve son moteur sans lire. Le reste de la
# carte — chiffre, barre, texte — reste dans l'univers de verts.
#
# ⚠️ Fidélité : ChatGPT et le « G » de Google sont les tracés officiels.
# L'étoile de Claude et la marque Perplexity sont des APPROXIMATIONS dessinées
# ici, reconnaissables mais pas au pixel près. Si un jour ce tableau part chez
# un client, il faudra les remplacer par les fichiers officiels.
#
# `--mark-openai` et `--mark-pplx` basculent avec le thème (noir illisible sur
# fond sombre, turquoise trop sourd) : ils sont définis dans les trois blocs de
# variables, comme toutes les autres couleurs.

_LOGO_OPENAI = (
    '<svg viewBox="0 0 24 24" fill="var(--mark-openai)" aria-hidden="true"><path d="M22.2819 '
    '9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 '
    '4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 '
    '0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 '
    '0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 '
    '0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 '
    '4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 '
    '.038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 '
    '1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804'
    ' 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 '
    '0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 '
    '1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 '
    '7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 '
    '0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 '
    '9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 '
    '4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 '
    '7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 '
    '2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"/></svg>'
)

# Étoile de Claude : huit rayons effilés, de longueurs alternées — c'est
# l'inégalité des rayons qui la distingue d'un astérisque quelconque.
_LOGO_CLAUDE = (
    '<svg viewBox="0 0 24 24" fill="#D97757" aria-hidden="true"><path d="M13.50 10.50 L12.42 1.20 '
    'L11.58 1.20 L10.50 10.50ZM14.12 12.00 L17.53 7.06 L16.94 6.47 L12.00 9.88ZM13.50 13.50 '
    'L22.20 12.42 L22.20 11.58 L13.50 10.50ZM12.00 14.12 L16.94 17.53 L17.53 16.94 L14.12 '
    '12.00ZM10.50 13.50 L11.58 22.80 L12.42 22.80 L13.50 13.50ZM9.88 12.00 L6.47 16.94 L7.06 '
    '17.53 L12.00 14.12ZM10.50 10.50 L1.80 11.58 L1.80 12.42 L10.50 13.50ZM12.00 9.88 L7.06 6.47 '
    'L6.47 7.06 L9.88 12.00Z"/></svg>'
)

# Perplexity : au trait, parce que la marque est faite de traits. Épaisseur
# 1,9 et non 1,7 : à 19 px, en dessous, les six segments se referment en pâté
# (constaté à l'écran le 10/08, deux autres pistes écartées pour ça).
_LOGO_PERPLEXITY = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="var(--mark-pplx)" stroke-width="1.9" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 2.2 V21.8"/><path d="M4 8.2 H20 V15.8 H4 Z"/>'
    '<path d="M12 8.2 L5.4 3.2"/><path d="M12 8.2 L18.6 3.2"/>'
    '<path d="M12 15.8 L5.4 20.8"/><path d="M12 15.8 L18.6 20.8"/></svg>'
)

_LOGO_GOOGLE = (
    '<svg viewBox="0 0 48 48" aria-hidden="true">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 '
    '14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 '
    '5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C'
    '.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 '
    '2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>'
)

# `anthropic-memory`, c'est Claude sans recherche : même modèle, même marque.
# Deux cartes portent donc la même étoile, et ce sont leurs titres qui les
# séparent (« Claude » et « Claude · mémoire de marque »).
LOGOS = {
    "openai": _LOGO_OPENAI,
    "anthropic": _LOGO_CLAUDE,
    "anthropic-memory": _LOGO_CLAUDE,
    "perplexity": _LOGO_PERPLEXITY,
    "ai_overview": _LOGO_GOOGLE,
}


def _logo(moteur_id: str, classe: str) -> str:
    """La marque d'un moteur, ou rien du tout. Un moteur inconnu (v2 : Mistral,
    Grok) ne casse pas la mise en page : il s'affiche sans logo, avec son nom.
    """
    svg = LOGOS.get(moteur_id)
    return f'<span class="{classe}">{svg}</span>' if svg else ""


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
  --mark-openai:#0B0B0B; --mark-pplx:#20808D;
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
  --mark-openai:#E9F2E3; --mark-pplx:#3FB4C4;
}}
:root[data-theme="dark"]{
  --ink:#E9F2E3; --ink-soft:rgba(233,242,227,.66); --ink-faint:rgba(233,242,227,.42);
  --bg:#0C140E; --paper:#151F17; --line:rgba(233,242,227,.09);
  --forest:#16251B; --forest-2:#23392A;
  --data:#8FCB57; --data-deep:#A9DA74; --data-soft:rgba(143,203,87,.16);
  --lime:#B7DC85; --piste:#1E2B20;
  --alert:#E5764A; --alert-soft:rgba(229,118,74,.14);
  --opp:#E0A72E; --opp-soft:rgba(224,167,46,.13);
  --mark-openai:#E9F2E3; --mark-pplx:#3FB4C4;
}
body{font-family:var(--f-body); background:var(--bg); color:var(--ink); line-height:1.55;
  -webkit-font-smoothing:antialiased}
.app{display:flex; align-items:flex-start; gap:20px; max-width:1420px; margin:0 auto;
  padding:16px}

.side{flex:none; width:188px; position:sticky; top:16px; height:calc(100vh - 32px);
  min-height:480px; background:var(--forest); color:var(--sur-forest); border-radius:26px;
  padding:16px 10px 18px; display:flex; flex-direction:column; align-items:center; gap:8px;
  overflow-y:auto}
/* Passe 1 : le libellé de vue est VISIBLE à côté de l'icône (avant, les noms
   de vues n'existaient qu'en title/aria-label, donc invisibles). */
.nav{display:flex; align-items:center; gap:9px; width:100%; min-height:44px; border:none;
  background:none; color:var(--sur-forest-soft); border-radius:15px; cursor:pointer;
  padding:9px 13px; font-family:inherit; text-align:left}
.nav svg{flex:none}
.nav span{font-size:.78rem; font-weight:700; letter-spacing:.02em; line-height:1.25}
.nav[aria-selected="true"]{background:var(--forest-2); color:var(--sur-forest)}
@media(hover:hover){.nav:hover{color:var(--sur-forest)}}
.nav:focus-visible{outline:3px solid var(--lime); outline-offset:2px}
.side__client{width:38px; height:38px; border-radius:50%; background:var(--lime); margin-bottom:16px; flex:none;
  color:#1D3826; display:grid; place-items:center; font-weight:800; font-size:.95rem}

.main{flex:1; min-width:0; padding:6px 2px 60px}
/* Finition 06/08 : UN seul écart vertical entre les sections d'une vue,
   porté par le panneau. Avant, .hero/.engines/.grid portaient 18px chacun
   mais .card ne portait RIEN : le rythme alternait large/collé selon la
   nature de la section. Plus aucune section ne porte de marge externe. */
[role="tabpanel"]>*{margin:0 0 18px}
[role="tabpanel"]>*:last-child{margin-bottom:0}
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
.reqform{display:flex; gap:10px; margin:2px 0 16px; flex-wrap:wrap}
.reqform input{flex:1; min-width:240px; border:1px solid var(--line); border-radius:999px;
  padding:12px 18px; font-family:inherit; font-size:.9rem; background:var(--bg);
  color:var(--ink)}
.reqform input:focus-visible{outline:3px solid var(--data-deep); outline-offset:1px}
.reqform input::placeholder{color:var(--ink-faint)}
.reqattente{border:1px dashed var(--line); border-radius:14px; padding:14px 16px;
  margin-bottom:16px}
.reqattente__t{font-size:.78rem; font-weight:600; color:var(--ink-soft); margin-bottom:8px}
/* Carnet d'idées (06/08) : messages d'erreur visibles, avertissement de
   fragilité du brouillon navigateur, aide d'import, bloc observation. */
.req-erreur{color:var(--alert); font-size:.8rem; font-weight:600; margin:-6px 0 12px}
.reqattente__avert{font-size:.75rem; font-weight:600; color:var(--opp); margin:10px 0}
.reqattente__aide{font-size:.75rem; color:var(--ink-faint); margin-top:8px}
.reqattente__aide code, .obs code{font-family:var(--f-mono); font-size:.72rem;
  background:var(--piste); border-radius:5px; padding:1px 5px}
/* Passe 5 : 18px des deux côtés du trait (le bas via padding-top ; le haut
   par fusion des marges avec les 16px du bloc précédent). Avant : 22/18,
   le trait flottait. Le titre h3 : une sous-section, un cran sous le titre
   de carte — deux h2 de même poids dans une carte brouillaient la hiérarchie. */
.obs{margin-top:18px; border-top:1px solid var(--line); padding-top:18px}
.obs .card__head h3{font-family:var(--f-display); font-weight:700; font-size:.95rem;
  letter-spacing:-.01em}
.reqattente ul{list-style:none; display:grid; gap:6px; margin-bottom:10px}
.reqattente li{display:flex; align-items:center; justify-content:space-between; gap:12px;
  font-size:.88rem; background:var(--data-soft); color:var(--ink);
  border-radius:10px; padding:8px 12px}
.reqattente li button{border:none; background:none; color:var(--ink-faint); cursor:pointer;
  font-size:1rem; line-height:1; padding:2px}
a.btn--mini{text-decoration:none; display:inline-block; margin-top:0}
.duel{display:grid}
/* Finition 06/08 : colonne question FIXE (mêmes départs de barres sur toutes
   les lignes) et barres flexibles qui démarrent juste après le texte au lieu
   d'être rejetées au bord droit. Interligne resserré. */
.duel__row{display:grid; grid-template-columns:420px minmax(0,1fr); gap:24px; align-items:center;
  padding:7px 0; border-bottom:1px solid var(--line)}
.duel__row:last-child{border-bottom:none}
.duel__row>p{font-size:.87rem; font-weight:600}
.duel__bars{display:grid; gap:4px}
.duel__bar{display:flex; align-items:center; gap:8px}
.duel__bar small{font-size:.64rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.06em; color:var(--ink-faint); width:26px; flex:none}
.duel__piste{flex:1; height:7px; border-radius:99px; background:var(--h0); overflow:hidden}
.duel__piste i{display:block; height:100%; border-radius:99px}
.duel__bar.moi .duel__piste i{background:var(--data)}
.duel__bar.lui .duel__piste i{background:var(--alert)}
.duel__bar b{font-family:var(--f-mono); font-size:.74rem; font-weight:700; width:40px;
  text-align:right; flex:none}
.chip{font-size:.78rem; font-weight:600; padding:6px 12px; border-radius:999px;
  background:var(--paper); border:1px solid var(--line); color:var(--ink); font-family:inherit}
button.chip{cursor:pointer}
button.chip[aria-selected="true"]{background:var(--forest); color:var(--sur-forest);
  border-color:transparent}
.chip:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.print-head{display:none}

/* Finition 06/08 : deux colonnes seulement (la 3e, vidée de ses stats,
   laissait la jauge isolée dans le vide), et la règle graduée devient une
   RANGÉE du bloc (grid-column:1/-1) au lieu de flotter sous le texte. */
.hero{background:var(--paper); border:1px solid var(--line); border-radius:22px;
  padding:28px 32px; display:grid; grid-template-columns:auto 1fr; gap:6px 30px;
  align-items:center}
.hero > .ruler{grid-column:1/-1; margin-top:14px}
.gauge{position:relative; width:210px}
.gauge svg{display:block; width:100%; height:auto}
.gauge__value{position:absolute; left:0; right:0; top:58%; text-align:center;
  font-family:var(--f-mono); font-weight:700; font-size:2.9rem; letter-spacing:-.04em;
  line-height:1}
/* Le chiffre porte son périmètre sur lui (règle du 05/08) : la jauge se
   qualifie, elle ne change pas de valeur. */
.gauge__perim{font-family:var(--f-body); font-size:.68rem; font-weight:600;
  color:var(--ink-faint); letter-spacing:.04em; margin-top:4px}
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
/* Passe 1 : les stats descendues du hero, posées à côté du classement voix. */
.lb-stats{display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:0 0 18px}
/* Passe 1 : la mission vit DANS la carte « À faire ». */
.card .mission{margin:0 0 14px}
/* Une grille à un seul occupant : la carte prend toute la largeur.
   (Sélecteur composé : .grid est définie plus bas dans la feuille et
   gagnerait sinon la cascade.) */
.grid.grid--pleine{grid-template-columns:1fr}

.mission{border-radius:22px; background:var(--forest); color:var(--sur-forest);
  padding:26px 30px; display:grid; grid-template-columns:1fr auto;
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
.queue__rank{display:block; font-size:.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.09em; color:var(--ink-faint); margin-bottom:5px}
/* Dans une carte, les vignettes ne peuvent plus être blanches sur blanc. */
.card .queue{margin-bottom:0}
.card .queue__card{background:var(--sur-forest); border-color:transparent}
.btn--mini{border:1px solid var(--line); background:var(--data-soft); color:var(--data-deep);
  border-radius:9px; padding:6px 12px; font-family:inherit; font-size:.78rem; font-weight:700;
  cursor:pointer; margin-top:11px}
.btn--mini:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}

/* align-items:start : une carte courte garde sa hauteur au lieu de s'étirer
   et de laisser un grand vide blanc à côté d'une carte longue. */
.grid{display:grid; grid-template-columns:1fr 1fr; gap:18px;
  align-items:start}
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
/* Finition 06/08 : le domaine sur colonne fixe, la barre prend l'espace
   restant juste après lui au lieu d'un petit trait collé au bord droit. */
.lb li{display:grid; grid-template-columns:26px 280px 1fr 58px; gap:12px; align-items:center;
  padding:9px 10px; border-radius:12px; font-size:.9rem; border-bottom:1px solid var(--line)}
.lb li:last-child{border-bottom:none}
.lb__rank{font-family:var(--f-mono); font-weight:600; font-size:.8rem; color:var(--ink-faint)}
.lb__dom{font-weight:600; overflow-wrap:anywhere}
.lb__dom small{display:block; font-weight:500; font-size:.74rem; color:var(--ink-soft)}
.lb__part{font-family:var(--f-mono); font-weight:700; text-align:right}
.lb__bar{width:auto; height:7px; border-radius:99px; background:var(--piste); overflow:hidden}
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
/* Fusion forteresses × dominance et carte « points faibles » (12/08/2026).
   Les points faibles portent l'AMBRE, jamais le rouge : un trou de couverture
   est un sujet à écrire, pas un incident (§2 bis du brief de front). */
.st__n1{font-family:var(--f-mono); font-size:.72rem; color:var(--ink-faint); margin-top:6px}
.st__n1 b{color:var(--ink-soft)}
.st--faible li h3 span{color:var(--opp)}
.st__bar--faible i{background:var(--opp)}
.wk__occ{font-size:.78rem; color:var(--ink-soft); margin-top:5px}
.wk__occ b{font-family:var(--f-mono); font-size:.76rem; color:var(--ink); font-weight:700}
.wk__occ--libre{color:var(--ink-faint); font-style:italic}

.engines{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:14px}
.eng{background:var(--paper); border:1px solid var(--line); border-radius:var(--r);
  padding:18px 20px}
/* La marque du moteur AVANT son nom : sur des cartes toutes identiques, c'est
   elle qui sert de point d'entrée, on trouve son moteur sans lire.
   `flex:none` sur le logo, et `flex-start` plutôt que `center` : un nom de
   moteur peut tenir sur deux lignes, et un logo centré sur deux lignes flotte
   entre les deux au lieu d'introduire la première. */
.eng__hd{display:flex; align-items:flex-start; gap:8px; margin-bottom:2px}
.eng__logo{width:19px; height:19px; flex:none; line-height:0; margin-top:1px}
.eng__logo svg{width:100%; height:100%; display:block}
.eng h3{font-size:.9rem; font-weight:700}
/* Un moteur à 0 % : la marque s'efface avec le reste de la carte, sinon elle
   crie plus fort que le chiffre qu'elle est censée introduire. */
.eng--zero .eng__logo{opacity:.42}
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
.health{font-size:.78rem; color:var(--ink-soft); margin-top:8px;
  padding-left:11px; border-left:2px solid var(--line)}
.health--ok{border-left-color:var(--data)}
.health--bad{border-left-color:var(--alert); color:var(--alert); font-weight:600}
.eng__meta{font-family:var(--f-mono); font-size:.72rem; color:var(--ink-faint);
  margin-bottom:8px}
.eng__meta b{color:var(--ink-soft)}

/* Matrice moteur x requete : le croisement, la ou se lisent les decisions. */
.mx{overflow-x:auto}
table.mx__t{border-collapse:separate; border-spacing:0; width:100%; font-size:.82rem}
table.mx__t th,table.mx__t td{padding:7px 8px; border-bottom:1px solid var(--line)}
/* Passe 5 : mêmes réglages d'en-tête que les autres tableaux (.7rem/.07em),
   un en-tête de tableau est un en-tête de tableau. */
table.mx__t thead th{font-size:.7rem; font-weight:700; color:var(--ink-faint);
  letter-spacing:.07em; text-transform:uppercase; text-align:center; white-space:nowrap;
  vertical-align:bottom; padding-bottom:9px}
/* Même repère que sur les cartes, en plus petit : la matrice a cinq colonnes
   aux libellés courts, le logo les distingue avant la lecture. */
.mx__logo{display:block; width:16px; height:16px; margin:0 auto 5px; line-height:0}
.mx__logo svg{width:100%; height:100%; display:block}
table.mx__t thead th small{display:block; font-family:var(--f-mono); font-size:.78rem;
  color:var(--ink-soft); letter-spacing:0; text-transform:none; margin-top:3px}
/* vertical-align:top : « Requête » s'aligne sur la ligne des NOMS de moteurs
   (ses pairs), pas sur la ligne des taux en dessous (Passe 5). */
table.mx__t th.mx__q{text-align:left; width:38%; vertical-align:top}
table.mx__t td.mx__q{text-align:left; color:var(--ink-soft); line-height:1.35;
  padding-right:16px}
table.mx__t td.mx__q b{color:var(--ink); font-weight:600}
.mx__c{text-align:center; font-family:var(--f-mono); font-weight:700; white-space:nowrap}
.mx__c i{display:block; font-style:normal; border-radius:7px; padding:5px 0}
.mx--high i{background:var(--data); color:#fff}
.mx--mid  i{background:var(--data-soft); color:var(--data-deep)}
.mx--low  i{background:var(--opp-soft); color:var(--opp)}
.mx--0    i{background:var(--alert-soft); color:var(--alert)}
.mx--na   i{background:transparent; color:var(--ink-faint)}
table.mx__t tr:last-child td{border-bottom:none}

/* Alignement : quelle intention de recherche atterrit sur quelle page. */
.al__row{padding:13px 0; border-bottom:1px solid var(--line)}
.al__row:last-child{border-bottom:none}
.al__head{display:flex; align-items:baseline; gap:10px; justify-content:space-between}
.al__url{font-family:var(--f-mono); font-weight:700; font-size:.88rem; word-break:break-all}
.al__n{font-family:var(--f-mono); font-size:.78rem; color:var(--ink-faint); white-space:nowrap}
.al__qs{margin-top:8px; display:grid; gap:3px}
.al__q{display:flex; justify-content:space-between; align-items:baseline; gap:12px;
  font-size:.78rem; color:var(--ink-soft); background:var(--piste);
  border-radius:7px; padding:5px 10px}
.al__q b{font-family:var(--f-mono); color:var(--ink-faint); font-weight:700}
/* Passe 5 : bas-de-casse. Les capitales conviennent aux pastilles de 2-3 mots
   (« Ton allié ») ; sur une phrase entière elles fatiguent et pèsent plus
   lourd que le titre de la carte. Même pastille, même texte. */
.al__flag{display:inline-block; font-size:.74rem; font-weight:600;
  padding:3px 9px; border-radius:6px; margin-top:9px;
  background:var(--opp-soft); color:var(--opp)}

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
/* Passe 5 : les colonnes où l'on COMPARE des quantités s'alignent à droite
   (255, 3, 210 s'empilent), comme partout ailleurs dans le produit. Les
   identifiants (Réf.) et les dates restent à gauche : on ne les compare pas. */
table.d th.num,table.d td.num{text-align:right}
table.d tr:last-child td{border-bottom:none}

/* Console (12/08/2026). Deux choix de couleur, tous les deux volontaires :
   les cartes d'action portent l'AMBRE (--opp), pas le rouge — une tâche à
   faire n'est pas un incident, et le rouge venait d'être retiré des cartes
   moteur pour cette raison exacte. Le journal, lui, reste entièrement neutre :
   une panne archivée ne demande plus rien. */
.conshd{display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:18px}
.conshd .btn--ghost{border-color:var(--line); background:var(--paper); color:var(--ink)}
.conshd__aide{font-size:.78rem; color:var(--ink-faint); max-width:52ch}
.card+.card{margin-top:18px}
.card--todo{border-left:3px solid var(--opp)}
.vide{font-size:.9rem; color:var(--ink-soft); background:var(--data-soft);
  border-radius:12px; padding:14px 16px; margin-top:8px}
.todo{background:var(--opp-soft); border-radius:14px; padding:16px 18px; margin-top:12px}
.todo__hd{display:flex; align-items:baseline; justify-content:space-between; gap:12px}
.todo__hd h3{font-size:.98rem; font-weight:700; color:var(--opp)}
.todo__recur{flex:none; font-size:.7rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.07em; color:var(--opp)}
.todo__qui{font-family:var(--f-mono); font-size:.74rem; color:var(--ink-faint);
  margin:2px 0 8px}
.todo p{font-size:.86rem; color:var(--ink-soft)}
.todo__lien{display:inline-block; margin-top:9px; font-family:var(--f-mono);
  font-size:.76rem; color:var(--data-deep); word-break:break-all}
.subi{list-style:none; display:grid; gap:12px; margin-top:12px}
.subi li{font-size:.85rem; color:var(--ink-soft); background:var(--piste);
  border-radius:12px; padding:13px 16px}
.subi strong{color:var(--ink)}
/* Le brut est REPLIÉ, jamais absent : c'est lui qui permet de diagnostiquer,
   mais il ne doit pas occuper la place de la phrase qui dit quoi faire. */
.brut{margin-top:9px}
.brut summary{font-size:.74rem; font-weight:600; color:var(--ink-faint); cursor:pointer}
.brut summary:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.brut pre{margin-top:7px; padding:10px 12px; background:var(--piste); border-radius:9px;
  font-family:var(--f-mono); font-size:.72rem; color:var(--ink-soft);
  white-space:pre-wrap; word-break:break-word}
.mach{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:12px}
.mach__c{background:var(--piste); border-radius:12px; padding:14px 16px}
.mach__c b{display:block; font-family:var(--f-mono); font-size:1.02rem; font-weight:700}
.mach__c span{display:block; font-size:.76rem; color:var(--ink-soft); margin-top:4px}
.mach__off{color:var(--ink-faint)}
/* Hors série : replié, pas supprimé. Une collecte qui n'a pas couvert le jeu
   reste une ligne du registre (garde-fou --sauf-si-recente), elle ne doit
   simplement pas se lire au même rang qu'une vraie collecte. */
.hors{margin-top:16px; border-top:1px solid var(--line); padding-top:14px}
.hors summary{font-size:.8rem; color:var(--ink-faint); cursor:pointer; max-width:62ch}
.hors summary:focus-visible{outline:3px solid var(--data-deep); outline-offset:2px}
.hors table.d{margin-top:10px; opacity:.7}
@media(max-width:1020px){.mach{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.mach{grid-template-columns:1fr}}

[hidden]{display:none!important}
@media(max-width:1020px){
  .app{flex-direction:column; gap:14px}
  .side{position:static; width:100%; height:auto; min-height:0; flex-direction:row;
    border-radius:18px; padding:10px 14px}
  .side__client{margin-bottom:0}
  .hero{grid-template-columns:1fr; text-align:center}
  .gauge{margin:0 auto}
  .hero__side{grid-template-columns:repeat(3,1fr); min-width:0}
  .stat{border-left:none; border-top:2px solid var(--line); padding:10px 0 0}
  .engines{grid-template-columns:repeat(2,1fr)}
  .grid,.queue{grid-template-columns:1fr}
  .mission{grid-template-columns:1fr}
  .mission__side{justify-items:start; text-align:left}
  .mission__acts{justify-content:flex-start}
  .duel__row{grid-template-columns:1fr; gap:8px}
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
  .side,.mhead__acts,.pop,.mission__acts,.btn--mini,button{display:none!important}
  .print-head{display:flex; align-items:baseline; justify-content:space-between; gap:12px;
    padding-bottom:14px; margin-bottom:18px; border-bottom:2px solid #1D3826}
  .print-head strong{font-size:1.1rem}
  .print-head span{font-size:.8rem; color:#555}
  .hero,.mission,.card,.eng,.queue__card{border:1px solid #ccc; break-inside:avoid}
  .mission{background:#fff; color:#152A1C}
  .mission p{color:#3d4a40}
  .mission__eyebrow,.mission__impact{color:#3E7D28}
  [role="tabpanel"][hidden]{display:block!important}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

# ⚠️ Chaîne BRUTE (r"""), obligatoire : sans le r, Python interprète les
# séquences d'échappement du JavaScript. Un « \n » dans une chaîne JS devient
# un vrai retour à la ligne, la chaîne n'est plus fermée, et TOUT le script
# meurt au chargement (navigation, boutons de copie, thème, périodes).
# Panne réelle introduite par le commit bbad266 (formulaire de proposition de
# requête) et corrigée le 05/08/2026 : navigation, boutons « Copier », thème et
# sélecteur de période étaient morts. Invisible tant qu'on ne clique pas.
# Le test 6 de tests_smoke.py monte la garde (node --check).
JS = r"""
(function(){
  // navigator.clipboard n'existe qu'en contexte securise (https, localhost).
  // Ce fichier s'ouvre en file:// : le repli execCommand est donc le chemin
  // NORMAL ici, pas un cas rare. Et si tout echoue, on le DIT au lieu de
  // laisser un bouton mort.
  function copier(texte, apres){
    function secours(){
      var ta=document.createElement('textarea');
      ta.value=texte;
      ta.setAttribute('readonly','');
      ta.style.position='fixed';
      ta.style.top='-1000px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      var reussi=false;
      try{reussi=document.execCommand('copy');}catch(e){reussi=false;}
      document.body.removeChild(ta);
      apres(reussi);
    }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(texte).then(function(){apres(true);},secours);
    }else{secours();}
  }
  document.querySelectorAll('[data-copy]').forEach(function(b){
    b.addEventListener('click',function(){
      var self=this, ok=this.getAttribute('data-ok')||'Copié', avant=this.textContent;
      copier(this.getAttribute('data-copy'),function(reussi){
        self.textContent=reussi?ok:'Copie impossible dans ce navigateur';
        setTimeout(function(){self.textContent=avant;},reussi?1800:3200);
      });
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
  // Carnet d'idees (06/08/2026) : le brouillon vit dans localStorage, le
  // vrai chemin est le telechargement + import CLI (une page file:// ne
  // peut pas ecrire sur le disque). Chaque refus est DIT, jamais muet.
  var CLE_REQ='iametre-requetes-proposees',
      champ=document.getElementById('req-champ'),
      valider=document.getElementById('req-valider'),
      attente=document.getElementById('req-attente'),
      listeEl=document.getElementById('req-liste'),
      telecharger=document.getElementById('req-telecharger'),
      erreur=document.getElementById('req-erreur'),
      donneesEl=document.getElementById('req-donnees');
  var suivies=[], client='';
  try{
    var d=JSON.parse(donneesEl?donneesEl.textContent:'{}');
    suivies=d.suivies||[]; client=d.client||'';
  }catch(e){}
  function plier(t){
    return (t||'').toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim();
  }
  function ditErreur(msg){
    if(erreur){erreur.textContent=msg||''; erreur.hidden=!msg;}
  }
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
  }
  if(valider){
    valider.addEventListener('click',function(){
      var v=(champ.value||'').trim();
      if(v.length<10){
        ditErreur('Trop court : formule la question comme tu la poserais \u00e0 une IA (10 caract\u00e8res minimum).');
        champ.focus(); return;
      }
      var pv=plier(v);
      var deja=null;
      suivies.forEach(function(s){if(plier(s.texte)===pv){deja=s;}});
      if(deja){ditErreur('D\u00e9j\u00e0 suivie ('+deja.id+').'); return;}
      var l=litProps(), doublon=false;
      l.forEach(function(q){if(plier(q)===pv){doublon=true;}});
      if(doublon){ditErreur('D\u00e9j\u00e0 dans ta liste d\u2019attente.'); return;}
      ditErreur('');
      l.push(v); ecritProps(l); champ.value=''; dessine();
    });
    champ.addEventListener('keydown',function(e){
      if(e.key==='Enter'){valider.click();}
    });
    champ.addEventListener('input',function(){ditErreur('');});
    dessine();
  }
  if(telecharger){
    telecharger.addEventListener('click',function(){
      var l=litProps();
      if(!l.length){ditErreur('Rien \u00e0 t\u00e9l\u00e9charger : la liste d\u2019attente est vide.'); return;}
      var contenu={client:client, date:new Date().toISOString().slice(0,10), propositions:l};
      var blob=new Blob([JSON.stringify(contenu,null,2)],{type:'application/json'});
      var a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download='propositions-requetes.json';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    });
  }
})();
"""


# --------------------------------------------------- les blocs, un par carte

def _hero(h: dict) -> str:
    """Le hero : l'état ET la règle graduée (revenue en Passe 1 corrigée,
    sans elle le hero était à moitié vide). Les stats de part de voix, elles,
    vivent à côté de la carte voix."""
    taux, palier, reste = h["taux"], h["palier"], h["reste"]
    L = 267
    badge = ""
    if h["badge"] is not None:
        if h["badge"]["variante"] == "stable":
            badge = '<span class="delta delta--flat">≈ stable</span>'
        else:
            haut = h["badge"]["variante"] == "hausse"
            badge = (f'<span class="delta delta--{"up" if haut else "down"}">'
                     f'{"▲" if haut else "▼"} {_nb(abs(h["badge"]["delta"]))} pts</span>')
    s = h["sante"]
    classe = {"ok": " health--ok", "partielle": "", "muette": " health--bad"}[s["variante"]]
    sante_html = f'<p class="health{classe}">{s["texte"]}</p>'
    reste_txt = f"<strong>+{reste:.0f} pts</strong>"
    if h["contenus"]:
        reste_txt += f" · <strong>{h['contenus']} à {h['contenus'] + 1} contenus à créer</strong>"
    # Sans mesure, pas de règle graduée : un palier vers 70 % depuis un taux
    # inexistant n'aurait aucun sens (états vides, 06/08).
    ruler = ""
    if h["mesurable"]:
        ruler = f"""<div class="ruler">
      <div class="ruler__track">
        <span class="ruler__ticks"></span>
        <span class="ruler__fill" style="width:{taux:.0f}%"></span>
        <span class="ruler__goal" style="left:{palier}%"><span>Palier {palier} %</span></span>
      </div>
      <div class="ruler__caption">
        <span><strong>{taux:.0f} %</strong> aujourd'hui</span><span>{reste_txt}</span>
      </div>
    </div>"""
    return f"""  <section class="hero">
    <div class="gauge">
      <svg viewBox="0 0 210 130" aria-hidden="true">
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--piste)"
              stroke-width="14" stroke-linecap="round"/>
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--ink-faint)"
              stroke-width="14" stroke-linecap="round" stroke-dasharray="{L * palier / 100:.1f} {L}"/>
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--signal)"
              stroke-width="14" stroke-linecap="round" stroke-dasharray="{L * taux / 100:.1f} {L}"/>
      </svg>
      <div class="gauge__value">{f'{taux:.0f}' if h["mesurable"] else "—"}{'<small>%</small>' if h["mesurable"] else ''}
        <div class="gauge__perim">{h["n_moteurs"]} moteurs de recherche</div></div>
    </div>
    <div class="hero__mid">
      <h2>{h["titre"]}{badge}</h2>
      <p class="eyebrow">Visibilité IA</p>
      <p>{f'Mesuré sur <strong>{h["appels_reussis"]} appels réussis</strong>, {h["n_moteurs"]} moteurs '
          f'avec recherche web' + (' ; la mémoire de marque (moteur sans recherche) est suivie à '
          'part, hors de ce taux' if h["memoire_suivie"] else '') + '. '
          if h["mesurable"] else ''}{_e(h["phrase"])}</p>
      {sante_html}
    </div>
    {ruler}
  </section>"""


def _moteurs(moteurs: list) -> str:
    tags = {"allie": '<span class="eng__tag eng__tag--best">Ton allié</span>',
            "objectif": '<span class="eng__tag eng__tag--goal">Objectif long terme</span>'}
    eng = ""
    for m in moteurs:
        # Le rang compte autant que le taux : citée souvent mais en 6e source
        # ne vaut pas citée rarement mais en 1re. Les deux, côte à côte.
        rang = (f'rang moyen <b>{_nb(m["rang"])}</b>' if m["rang"]
                else '<b>aucune citation</b>')
        # Les échecs ne sont PLUS sur la carte (Marion, 12/08/2026). En rouge
        # et en gras à côté du taux, ils faisaient lire un incident de
        # facturation comme un mauvais résultat de visibilité — deux sujets
        # sans rapport, dont un seul appartient à cette carte. Ils vivent
        # maintenant dans la vue Console, où ils portent une action.
        appels = f'{m["appels"]["ok"]} appels'
        eng += (f'<article class="eng{" eng--zero" if m["est_zero"] else ""}">'
                f'<div class="eng__hd">{_logo(m["id"], "eng__logo")}'
                f'<h3>{_e(m["nom"])}</h3></div>'
                f'<div class="eng__rate">{m["taux"]:.0f} %</div>'
                f'<div class="eng__bar"><i style="width:{max(m["taux"], 2):.0f}%"></i></div>'
                f'<div class="eng__meta">{rang} · {appels}</div>'
                f'<p>{_e(m["lecture"])}</p>{tags.get(m["tag"], "")}</article>')
    return eng


def _a_faire(af: dict) -> str:
    """La section unique « À faire » (fusion Passe 1) : trois entrées classées
    par impact décroissant, structure unifiée, la première mise en avant comme
    l'ancienne mission. `contexte` et `brief` sont optionnels : quand ils sont
    là (l'entrée n°1), la phrase de terrain et le bouton « Copier le brief »
    s'affichent — une fusion ne supprime pas de fonctionnalité."""
    tete = ""
    if af["items"]:
        q = af["items"][0]
        contexte = f" {_e(q['contexte'])}" if q["contexte"] else ""
        brief = ""
        if q["brief"]:
            brief = (f'<button class="btn--ghost" data-copy="{_e(q["brief"])}" '
                     f'data-ok="Brief copié">Copier le brief</button>\n        ')
        tete = f"""
  <section class="mission">
    <div>
      <div class="mission__eyebrow">Ta prochaine action · opportunité n°1</div>
      <h2>{_cite(q['question'])}</h2>
      <p>{_e(q['diagnostic'])}{contexte}
      <strong>C'est le sujet où un contenu rapporterait le plus.</strong></p>
    </div>
    <div class="mission__side">
      <div class="mission__impact">{_e(q['impact'])}<small>impact estimé, borne basse</small></div>
      <div class="mission__acts">
        {brief}<button class="btn btn--primary" data-copy="{_e(q['recette'])}" data-ok="Recette copiée, colle-la dans une IA">Copier la recette d'article</button>
      </div>
    </div>
  </section>"""

    suite = "".join(
        f'<article class="queue__card"><div class="queue__txt">'
        f'<span class="queue__rank">Article n°{q["numero"]}</span>'
        f'<h3>{_cite(q["question"])}</h3><p>{_e(q["diagnostic"])} '
        f'Gain estimé : <strong>{_e(q["impact"])}</strong> sur le taux global.</p>'
        f'<button class="btn--mini" data-copy="{_e(q["recette"])}" '
        f'data-ok="Recette copiée">Copier la recette d\'article</button></div>'
        f'<div class="queue__rate{" queue__rate--warn" if q["taux_warn"] else ""}">'
        f'{q["taux"]:.0f} %</div></article>'
        for q in af["items"][1:]
    )
    queue = f'<div class="queue">{suite}</div>' if suite else ""
    # Quand tout dépasse 60 %, la carte le DIT au lieu de rester vide
    # (états vides, 06/08).
    corps = f"{tete}\n    {queue}" if af["items"] else (
        '<p class="card__lead">Toutes les requêtes suivies dépassent 60 % de '
        'citation : plus de trou évident à combler.</p>')

    return f"""
  <section class="card">
    <div class="card__head"><h2>À faire</h2>
      <span class="card__hint">classés par gain estimé sur le taux global</span></div>
    {corps}
  </section>"""


def _voix(v: dict) -> str:
    lead = v["lead"]
    lead_voix = (
        "Aucune source citée sur cette collecte : rien à classer."
        if lead["variante"] == "vide"
        else f"La marque domine, mais <strong>{_e(lead['poursuivant'])} n'est "
             f"qu'à {_nb(lead['ecart'])} {_points(lead['ecart'])}</strong>."
        if lead["variante"] == "domine"
        else "Répartition des citations relevées pendant la collecte."
    )
    st = v["stats"]
    stats = (
        f'<div class="lb-stats">'
        f'<div class="stat stat--crown"><div class="stat__num">{st["place"] or "—"}<sup>{st["place_suffixe"]}</sup></div>'
        f'<div class="stat__lbl">sur {st["domaines"]} domaines cités</div></div>'
        f'<div class="stat"><div class="stat__num">{_nb(st["part"]) + " %" if st["part"] is not None else "n/d"}</div>'
        f'<div class="stat__lbl">part de voix</div></div>'
        f'<div class="stat"><div class="stat__num">{_nb(st["rang"]) if st["rang"] else "n/d"}</div>'
        f'<div class="stat__lbl">rang moyen dans les sources</div></div>'
        f'</div>'
    )
    tete = v["lignes"][0]["part"] if v["lignes"] else 1
    lb = ""
    for ligne in v["lignes"]:
        cls = "is-you" if ligne["est_moi"] else ("is-chaser" if ligne["est_poursuivant"] else "")
        ecart = ""
        if ligne["ecart"] is not None:
            ecart = (f'<span class="lb__gap">à {_nb(ligne["ecart"])} '
                     f'{_points(ligne["ecart"])} derrière la marque</span>')
        lb += (f'<li class="{cls}"><span class="lb__rank">{ligne["rang"]}</span>'
               f'<span class="lb__dom">{_e(ligne["domaine"])}'
               + (f"<small>{_e(ligne['sous_titre'])}</small>" if ligne["sous_titre"] else "")
               + f'</span><span class="lb__bar"><i style="width:{ligne["part"] / tete * 100:.0f}%"></i>'
               f'</span><span class="lb__part">{_nb(ligne["part"])} %</span>{ecart}</li>')
    return f"""    <section class="card">
      <div class="card__head"><h2>Qui te prend des citations</h2>
        <span class="card__hint">{v['total_citations']} citations<br>{v['domaines_distincts']} domaines</span></div>
      <p class="card__lead">{lead_voix}</p>
      {stats}
      <ol class="lb">{lb}</ol>
    </section>"""


def _forteresses(f: dict) -> str:
    """Fusion du 12/08/2026 : cette carte portait le taux de citation, la carte
    « Dominance » portait la part de n°1 — sur presque les mêmes requêtes, donc
    lues comme une répétition. Les deux mesures tiennent maintenant sur la même
    ligne : citée à X %, première à Y %."""
    lead = (
        f"<strong>{_e(f['lead']['texte_requete'])}</strong> à {f['lead']['taux']:.0f} % : la preuve que la "
        f"méthode fonctionne. Il suffit de la répliquer sur les sujets de la carte « À faire »."
        if f["lead"]["variante"] == "exemples"
        else "Aucune requête au-dessus de 60 % pour l'instant."
    )
    if f["a_dominance"]:
        lead += (f' Et être citée ne suffit pas : quand la marque apparaît, elle est '
                 f'<strong>source n°1 dans {f["part_n1"]:.0f} % des cas</strong>, et nommée dans '
                 f'le texte même de la réponse dans {f["part_texte"]:.0f} % des appels.')
    st = ""
    for q in f["items"]:
        # « — » et non « 0 % » : une part de n°1 sur zéro citation n'existe
        # pas, elle ne vaut pas zéro (même règle que le hero d'une collecte
        # morte, passe du 06/08).
        n1 = f'{q["part_n1"]:.0f} %' if q["part_n1"] is not None else "—"
        st += (f'<li><h3>{_e(q["texte"])} <span>{q["taux"]:.0f} %</span></h3>'
               f'<div class="st__bar"><i style="width:{q["taux"]:.0f}%"></i></div>'
               f'<p class="st__n1">source n°1 dans <b>{n1}</b> de ses citations</p></li>')
    return f"""    <section class="card">
      <div class="card__head"><h2>Tes forteresses</h2>
        <span class="card__hint">citée, et à quelle place</span></div>
      <p class="card__lead">{lead}</p>
      <ul class="st">{st}</ul>
    </section>"""


def _faiblesses(w: dict) -> str:
    """Carte demandée par Marion le 12/08/2026, à la place de « Dominance ».

    Elle répond à sa question — « une fois les opportunités faites, comment je
    passe devant le concurrent ? » — en montrant, sur chaque trou, QUI occupe
    la place. ⚠️ Ce n'est pas un doublon de « À faire » : celle-là prescrit
    trois actions classées par gain, celle-ci pose le diagnostic sur tous les
    trous et nomme l'occupant. Un terrain vide et un terrain tenu par un
    concurrent n'appellent pas le même contenu.
    """
    if w["aucune"]:
        return f"""    <section class="card">
      <div class="card__head"><h2>Tes points faibles</h2>
        <span class="card__hint">et qui prend la place</span></div>
      <p class="card__lead">Aucune requête suivie sous {w['seuil']:.0f} % de citation :
      il n'y a pas de trou à combler sur cette collecte.</p>
    </section>"""

    items = ""
    for q in w["items"]:
        if q["occupants"]:
            occ = ('<p class="wk__occ">La place est prise par '
                   + ", ".join(f'<b>{_e(o)}</b>' for o in q["occupants"]) + '.</p>')
        else:
            occ = ('<p class="wk__occ wk__occ--libre">Personne ne s\'impose : '
                   'terrain libre, pas une place à prendre.</p>')
        st = f'{q["cites"]} citation{"s" if q["cites"] > 1 else ""} sur {q["ok"]} réponses'
        items += (f'<li><h3>{_e(q["texte"])} <span>{q["taux"]:.0f} %</span></h3>'
                  f'<div class="st__bar st__bar--faible">'
                  f'<i style="width:{max(q["taux"], 2):.0f}%"></i></div>'
                  f'<p class="st__n1">{st}</p>{occ}</li>')
    reste = ""
    if w["n_total"] > len(w["items"]):
        reste = (f' Les {len(w["items"])} plus bas sont ici, sur '
                 f'{w["n_total"]} au total.')
    return f"""    <section class="card">
      <div class="card__head"><h2>Tes points faibles</h2>
        <span class="card__hint">et qui prend la place</span></div>
      <p class="card__lead">Les requêtes suivies sous {w['seuil']:.0f} % de citation, et le
      domaine qui occupe le terrain à ta place.{reste} <strong>Savoir qui est devant
      ne dit pas encore pourquoi</strong> : c'est ce que la carte ne prétend pas faire.</p>
      <ul class="st st--faible">{items}</ul>
    </section>"""


def _duel(du: dict) -> str:
    # Pas de rival dans le YAML : la carte disparaît, et c'est un CHOIX —
    # suivre un rival est une option de configuration, pas un dû. Une carte
    # « pas de rival » serait du bruit permanent (états vides, 06/08).
    if not du["rival_configure"]:
        return ""
    # Rival configuré mais aucune donnée exploitable : l'attente est dite.
    if not du["lignes"]:
        return f"""
  <section class="card">
    <div class="card__head"><h2>Duel : toi contre {_e(du["rival_label"])}</h2></div>
    <p class="card__lead">Le duel contre {_e(du["rival_label"])} attend une collecte
    exploitable.</p>
  </section>"""
    if not du["affiche"]:
        return ""
    lignes = "".join(
        f'<div class="duel__row"><p>{_cite(x["question"])}</p>'
        f'<div class="duel__bars">'
        f'<span class="duel__bar moi"><small>Toi</small>'
        f'<span class="duel__piste"><i style="width:{x["moi"]:.0f}%"></i></span>'
        f'<b>{x["moi"]:.0f} %</b></span>'
        f'<span class="duel__bar lui"><small>Lui</small>'
        f'<span class="duel__piste"><i style="width:{x["lui"]:.0f}%"></i></span>'
        f'<b>{x["lui"]:.0f} %</b></span>'
        f'</div></div>'
        for x in du["lignes"]
    )
    return f"""
  <section class="card">
    <div class="card__head"><h2>Duel : toi contre {_e(du["rival_label"])}</h2>
      <span class="card__hint">{du["menees"]} menées · {du["perdues"]} à reprendre · {du["egales"]} égalités</span></div>
    <p class="card__lead">Ton concurrent éditorial direct, requête par requête, du duel le plus
    disputé au plus tranquille. <strong>Vert : toi. Ambre : lui.</strong></p>
    <div class="duel">{lignes}</div>
  </section>"""


def _courbe(c: dict) -> str:
    """La courbe de visibilité, avec sa bande de fluctuation dessinée. Toute
    la géométrie (coordonnées, bande, étiquette) se calcule ici : la couche
    données fournit les points et la marge, rien d'autre."""
    marge = c["marge"]
    if c["variante"] == "attente":
        return f"""<section class="card">
  <div class="card__head"><h2>Courbe de visibilité</h2>
    <span class="card__hint">un point par jour de collecte</span></div>
  <p class="card__lead">La courbe apparaîtra à la deuxième collecte, automatique. D'ici là,
  le repère qui compte : <strong>±{_nb(marge)} pts de marge de fluctuation.</strong>
  Une réponse d'IA oscille naturellement dans cette bande ; seul un mouvement qui en sort,
  ou une tendance sur 3-4 collectes, est un vrai signal. Depuis le balisage du site en
  entités (07/08/2026), la courbe se lit en avant-après : elle mesure une évolution,
  elle ne démontre pas une cause (la rentrée BPJEPS ou une mise à jour des modèles
  la font bouger aussi).</p>
</section>"""

    serie = c["points"]
    # Finition 06/08 : hauteur ajustée au contenu réel (150 -> 112 -> 80,
    # le tiers inférieur restait vide), étiquette collée au point (-7).
    W, H, PAD = 640, 80, 16
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
    # Chaque chiffre porte son périmètre SUR LUI (règle du 05/08) : l'étiquette
    # du dernier point dit sur combien de moteurs il est mesuré. La ligne
    # courte de l'en-tête suffit, pas de phrase d'explication en plus.
    n_mot = c["n_moteurs"]
    dernier = serie[-1]
    etiquette = (f'<text x="{xs[-1]:.1f}" y="{y(dernier["taux"]) - 7:.1f}" text-anchor="end" '
                 f'class="curve__val">{dernier["taux"]:.0f} % · {n_mot} moteurs</text>')

    return f"""<section class="card">
  <div class="card__head"><h2>Courbe de visibilité</h2>
    <span class="card__hint">comparé sur les {n_mot} moteurs communs à toutes les collectes ·
    bande grisée : marge de fluctuation ±{_nb(marge)} pts</span></div>
  <p class="card__lead">Tant que la ligne reste dans sa bande, la mesure est <strong>stable</strong> :
  l'oscillation est le comportement normal d'une réponse d'IA, pas un recul.
  Le vrai signal, c'est la tendance sur 3-4 collectes. Depuis le balisage du site en
  entités (07/08/2026), la courbe se lit en <strong>avant-après</strong> : une évolution,
  pas une preuve de cause (rentrée BPJEPS et mises à jour des modèles la font bouger aussi).</p>
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


def _matrice(mx: dict) -> str:
    # Sans données, la vue ne reste pas BLANCHE : elle dit pourquoi
    # (états vides, 06/08 — c'était le pire cas de l'inventaire).
    if not mx["affiche"]:
        return """
  <section class="card">
    <div class="card__head"><h2>Quel moteur te cite, sur quel sujet</h2></div>
    <p class="card__lead">Aucune donnée exploitable sur cette collecte : la matrice
    apparaîtra à la première collecte réussie.</p>
  </section>"""
    entetes = "".join(
        f'<th>{_logo(col["id"], "mx__logo")}{_e(col["nom_court"])}'
        f'<small>{col["taux"]:.0f} %</small></th>'
        for col in mx["colonnes"]
    )
    classes = {"zero": "mx--0", "low": "mx--low", "mid": "mx--mid",
               "high": "mx--high", "na": "mx--na"}
    lignes = ""
    for q in mx["lignes"]:
        cells = ""
        for c in q["cellules"]:
            if c["niveau"] == "na":
                cells += '<td class="mx__c mx--na"><i>·</i></td>'
            else:
                cells += (f'<td class="mx__c {classes[c["niveau"]]}">'
                          f'<i>{c["cites"]}/{c["ok"]}</i></td>')
        lignes += (f'<tr><td class="mx__q"><b>{_e(q["id"])}</b> {_e(q["texte"])}</td>'
                   f'{cells}</tr>')

    lead = ""
    mh = mx["lead"]["moteur_haut"]
    if mh:
        lead += (f"<strong>{_e(mh['nom'])}</strong> "
                 f"place la marque le plus haut quand il la cite (rang "
                 f"{_nb(mh['rang'])}). ")
    if mx["lead"]["muettes"] == 1:
        lead += ("<strong>1 requête</strong> ne sort chez aucun moteur : c'est le trou "
                 "à combler en premier, un contenu la débloque partout à la fois.")
    elif mx["lead"]["muettes"]:
        lead += (f"<strong>{mx['lead']['muettes']} requêtes</strong> ne sortent chez aucun moteur : "
                 f"ce sont les trous à combler en premier, un contenu les débloque "
                 f"partout à la fois.")
    else:
        lead += "Chaque requête sort au moins chez un moteur."

    return f"""
  <section class="card">
    <div class="card__head"><h2>Quel moteur te cite, sur quel sujet</h2>
      <span class="card__hint">citations / appels, par moteur et par requête</span></div>
    <p class="card__lead">{lead}</p>
    <div class="mx"><table class="mx__t">
      <thead><tr><th class="mx__q">Requête</th>{entetes}</tr></thead>
      <tbody>{lignes}</tbody>
    </table></div>
  </section>"""


def _alignement(al: dict) -> str:
    if al["vide"]:
        return """
  <section class="card">
    <div class="card__head"><h2>Ce que les IA citent chez toi</h2></div>
    <p class="card__lead">Aucune page du site citée sur cette collecte.</p>
  </section>"""

    rows = ""
    for p in al["pages"]:
        qs = "".join(
            f'<span class="al__q"><span>{_e(q["texte"])}</span><b>{q["n"]}</b></span>'
            for q in p["detail"]
        )
        if p["reste"] > 0:
            s = "s" if p["reste"] > 1 else ""
            qs += f'<span class="al__q"><span>+ {p["reste"]} autre{s} requête{s}</span></span>'
        flag = ""
        if p["flag"] is not None and p["flag"]["variante"] == "accueil":
            flag = (f'<span class="al__flag">l\'accueil répond à {p["flag"]["n"]} questions '
                    f'précises : autant de pages dédiées à créer</span>')
        elif p["flag"] is not None:
            flag = (f'<span class="al__flag">cette page absorbe {p["flag"]["n"]} sujets '
                    f'différents : vérifie qu\'elle répond vraiment à chacun, sinon il te '
                    f'manque des pages dédiées</span>')
        rows += (f'<div class="al__row"><div class="al__head">'
                 f'<span class="al__url">{_e(p["page"])}</span>'
                 f'<span class="al__n">{p["n"]} citations · {p["requetes"]} requêtes</span>'
                 f'</div><div class="al__qs">{qs}</div>{flag}</div>')

    lead = (f"<strong>{_e(al['lead']['page'])}</strong> concentre {al['lead']['n']} des "
            f"{al['lead']['total']} citations de tes pages. Ce qui compte ici n'est pas le "
            f"total mais la colonne de droite : "
            f"<strong>la question posée et la page où l'IA envoie la personne doivent "
            f"parler du même sujet</strong>, sinon la citation ne convertit pas.")

    return f"""
  <section class="card">
    <div class="card__head"><h2>Ce que les IA citent chez toi</h2>
      <span class="card__hint">de la question posée à la page citée</span></div>
    <p class="card__lead">{lead}</p>
    {rows}
  </section>"""


# ------------------------------------------------------- les vues (panneaux)

def _vue_ensemble(d: dict) -> str:
    """Vue 1 (Passe 1 corrigée) : hero avec sa règle graduée, les cartes
    moteurs, « À faire », le duel, la part de voix avec ses stats, puis
    forteresses et points faibles, et la courbe en toute dernière position.
    *(12/08/2026 : « dominance » a fusionné dans « forteresses », sa place est
    prise par « points faibles », qui nomme l'occupant de chaque trou.)*"""
    return f"""
{_hero(d["hero"])}
  <div class="engines">{_moteurs(d["moteurs"])}</div>
{_a_faire(d["a_faire"])}
{_duel(d["duel"])}

  <div class="grid grid--pleine">
{_voix(d["voix"])}
  </div>

  <div class="grid">
{_forteresses(d["forteresses"])}
{_faiblesses(d["faiblesses"])}
  </div>

{_courbe(d["courbe"])}"""


def _vue_moteurs_sujets(d: dict) -> str:
    """Vue 2 : la matrice requête × moteur."""
    return _matrice(d["matrice"])


def _vue_citations(d: dict) -> str:
    """Vue 3 : l'alignement question → page, en version détaillée."""
    return _alignement(d["alignement"])


def _vue_requetes(j: dict) -> str:
    """Le carnet d'idées (06/08/2026). Une idée tapée ici finit dans le YAML
    au statut observation, par le chemin en deux temps : la page fait
    TÉLÉCHARGER un fichier de propositions (une page file:// ne peut pas
    écrire sur le disque), et `python -m geotracker.carnet` l'importe.
    Les requêtes en observation s'affichent en dessous, collectées mais hors
    taux global."""
    import json as _json
    donnees_js = _json.dumps(
        {"client": j["client"], "suivies": j["suivies"]}, ensure_ascii=False
    ).replace("</", "<\\/")

    obs = j["observation"]
    # Vide, le bloc ne disparaît pas : la ligne dit où atterrissent les
    # requêtes du carnet, sinon le parcours d'import finit dans l'invisible
    # (états vides, 06/08).
    obs_html = ("""
  <div class="obs">
    <p class="reqattente__aide">Rien en observation pour l'instant : les requêtes
      importées du carnet apparaîtront ici.</p>
  </div>""")
    if obs["lignes"]:
        lignes_obs = "".join(
            f'<tr><td>{_e(q["texte"])}</td><td class="n">{_e(q["id"])}</td>'
            + (f'<td class="n num">{q["taux"]:.0f} %</td><td class="n num">{q["cites"]}/{q["ok"]}</td>'
               if q["taux"] is not None else
               '<td class="n" colspan="2">en attente de première collecte</td>')
            + '</tr>'
            for q in obs["lignes"]
        )
        obs_html = f"""
  <div class="obs">
    <div class="card__head"><h3>En observation</h3>
      <span class="card__hint">{len(obs['lignes'])}/{obs['plafond']} ·
      ≈ +{len(obs['lignes'])}&nbsp;$/mois · hors taux global</span></div>
    <p class="card__lead">Ces requêtes sont collectées et mesurées, mais n'entrent ni dans le
    taux global ni dans le périmètre de comparaison : on peut les <strong>tester sans faire
    bouger la série</strong>. Bonnes sur 2-3 collectes, elles sont promues titulaires, c'est-à-dire
    comptées dans le taux global (dans le YAML, en retirant leur ligne <code>statut</code>).</p>
    <div class="tw"><table class="d">
    <tr><th>Requête</th><th>Réf.</th><th class="num">Citation</th><th class="num">Ratio</th></tr>
    {lignes_obs}</table></div>
  </div>"""

    return f"""<section class="card">
  <div class="card__head"><h2>Jeu de requêtes</h2>
    <span class="card__hint">version {j['set_version']} · {j['n_requetes']} requêtes ·
    {j['n_concurrents']} concurrents suivis</span></div>
  <p class="card__lead">Une requête est une question posée comme un humain la pose, pas un mot-clé.
  <strong>Ajouter une requête est sans danger : elle démarre « en observation », collectée mais
  hors taux global, le temps de la valider.</strong> En modifier une casse la comparabilité :
  on n'y touche jamais, on en crée une nouvelle.</p>
  <div class="reqform">
    <input id="req-champ" type="text" maxlength="180"
           placeholder="Proposer une requête, formulée comme on la poserait à une IA…"
           aria-label="Nouvelle requête à suivre">
    <button class="btn--report" id="req-valider">Ajouter au carnet</button>
  </div>
  <p class="req-erreur" id="req-erreur" role="alert" hidden></p>
  <div class="reqattente" id="req-attente" hidden>
    <p class="reqattente__t">En attente d'import dans le jeu de suivi
      (~1&nbsp;$/mois par requête) :</p>
    <ul id="req-liste"></ul>
    <p class="reqattente__avert">⚠ Ces idées ne sont enregistrées que dans CE navigateur
      tant qu'elles ne sont pas importées.</p>
    <button class="btn--mini" id="req-telecharger">Télécharger pour import</button>
    <p class="reqattente__aide">Puis : <code>python -m geotracker.carnet
      ~/Downloads/propositions-requetes.json</code></p>
  </div>{obs_html}
  <script type="application/json" id="req-donnees">{donnees_js}</script></section>"""


def _vue_console(c: dict) -> str:
    """La vue Console : ce qu'il y a à faire, l'état de la machine, le journal.

    L'ordre n'est pas décoratif. L'ancienne vue « Collectes » présentait le
    journal en premier et ne proposait aucune action ; Marion l'a décrite le
    12/08/2026 comme inutilisable (« je ne sais pas quelle action je dois
    faire »). Ce qui se décide passe donc devant ce qui s'archive.
    """
    e = c["etat"]

    # --- Bloc 1 : ce que tu dois faire.
    if c["actions"]:
        cartes = ""
        for a in c["actions"]:
            recur = ""
            if a["recurrence"] > 1:
                recur = (f'<span class="todo__recur">vue sur {a["recurrence"]} '
                         f'collectes</span>')
            portee = (f'{a["n"]} appel{"s" if a["n"] > 1 else ""} perdu'
                      f'{"s" if a["n"] > 1 else ""}' if a["n"] else "collecte amputée")
            lien = ""
            if a["lien"]:
                lien = (f'<a class="todo__lien" href="{_e(a["lien"])}" target="_blank" '
                        f'rel="noopener">{_e(a["lien"])}</a>')
            brut = ""
            if a["messages"]:
                # TOUS les messages de la famille, pas le premier : deux pannes
                # rangées ensemble peuvent porter deux codes différents, et
                # c'est justement le code qui sert à diagnostiquer.
                s = "s" if len(a["messages"]) > 1 else ""
                brut = (f'<details class="brut"><summary>Message{s} brut{s} du '
                        f'fournisseur</summary>'
                        + "".join(f'<pre>{_e(m)}</pre>' for m in a["messages"])
                        + '</details>')
            cartes += (f'<article class="todo">'
                       f'<div class="todo__hd"><h3>{_e(a["titre"])}</h3>{recur}</div>'
                       f'<p class="todo__qui">{_e(a["moteur_nom"])} · {portee}</p>'
                       f'<p>{_e(a["quoi_faire"])}</p>{lien}{brut}</article>')
        bloc_actions = f"""<section class="card card--todo">
  <div class="card__head"><h2>Ce que tu dois faire</h2>
    <span class="card__hint">{len(c['actions'])} en attente</span></div>
  <p class="card__lead">Déduit des pannes de la dernière collecte. Ce qui n'est pas
  réparable de ton côté n'apparaît pas ici : c'est plus bas, dans « Subi ».</p>
  {cartes}</section>"""
    else:
        bloc_actions = """<section class="card card--todo">
  <div class="card__head"><h2>Ce que tu dois faire</h2></div>
  <p class="vide">Rien à faire. La machine tourne, la dernière collecte n'a demandé
  aucune intervention.</p></section>"""

    # --- « Subi » : ce qui a cassé sans que personne puisse rien y faire. Le
    # dire explicitement, plutôt que de le taire, c'est ce qui empêche de
    # rouvrir le sujet chaque lundi.
    bloc_subi = ""
    if c["subies"]:
        lignes = "".join(
            f'<li><strong>{_e(s["moteur_nom"])}</strong> · {_e(s["titre"])} '
            f'({s["n"]} appel{"s" if s["n"] > 1 else ""}'
            + (f', vu sur {s["recurrence"]} collectes' if s["recurrence"] > 1 else '')
            + f') — {_e(s["quoi_faire"])}'
            f'<details class="brut"><summary>Message brut</summary>'
            + "".join(f'<pre>{_e(m)}</pre>' for m in s["messages"])
            + '</details></li>'
            for s in c["subies"])
        bloc_subi = f"""<section class="card">
  <div class="card__head"><h2>Subi, rien à faire</h2></div>
  <ul class="subi">{lignes}</ul></section>"""

    # --- Bloc 2 : l'état de la machine.
    eteints = (f' <span class="mach__off">+ {len(e["moteurs_eteints"])} éteint : '
               f'{_e(", ".join(e["moteurs_eteints"]))}</span>'
               if e["moteurs_eteints"] else "")
    duree = f'{e["duree_min"]} min' if e["duree_min"] is not None else "durée inconnue"
    if e["cout"] is None:
        cout = ('<b>non communiqué</b><span>aucun fournisseur de cette collecte '
                'ne renvoie de coût</span>')
    else:
        muets = (f'hors {_e(", ".join(e["cout_muets"]))}, qui ne le renvoient pas'
                 if e["cout_partiel"] and e["cout_muets"]
                 else "coût rapporté par les fournisseurs")
        cout = f'<b>{_nb(e["cout"], 2)} $</b><span>{muets}</span>'
    bloc_etat = f"""<section class="card">
  <div class="card__head"><h2>L'état de la machine</h2>
    <span class="card__hint">{_e(e['prochaine'])}</span></div>
  <div class="mach">
    <div class="mach__c"><b>{e['n_moteurs_actifs']} moteurs</b>
      <span>{_e(', '.join(e['moteurs_actifs']))}{eteints}</span></div>
    <div class="mach__c"><b>{e['n_requetes']} requêtes</b>
      <span>jeu de suivi version {e['set_version']}</span></div>
    <div class="mach__c"><b>collecte #{e['run_id']}</b>
      <span>{_e(e['run_date'])} · {duree} · {e['appels']} appels dont
        {e['exploitables']} exploitables</span></div>
    <div class="mach__c">{cout}</div>
  </div></section>"""

    # --- Bloc 3 : le journal. Un ARCHIVE, pas un poste de travail : aucune
    # ligne ne porte d'action, donc aucune ne se déplie. Les messages bruts de
    # la collecte lue sont dans les blocs du dessus, ceux des collectes
    # passées dans le diagnostic copiable — les remettre ici mettait six
    # pavés de code dans une colonne de chiffres alignée à droite.
    def ligne(h):
        t = f'{h["taux"]:.0f} %' if h["taux"] is not None else "—"
        cout = f'{_nb(h["cout"], 2)} $' if h["cout"] is not None else "—"
        # Le détail des pannes en infobulle : présent pour qui le cherche,
        # absent de la mise en page pour qui ne le cherche pas.
        titre = ""
        if h["detail"]:
            titre = ' title="' + _e(" · ".join(
                f'{x["moteur"]} ×{x["n"]} : {x["famille"]}' for x in h["detail"])) + '"'
        return (f'<tr><td class="n">#{h["id"]}</td><td class="n">{_e(h["date"])}</td>'
                f'<td class="n num">{h["n"]}</td>'
                f'<td class="n num"{titre}>{h["pannes"] or "—"}</td>'
                f'<td class="n num">{h["sans_reponse"] or "—"}</td>'
                f'<td class="n num">{cout}</td>'
                f'<td class="n num">{t}</td><td>{_e(h["note"])}</td></tr>')

    entete = ('<tr><th>Réf.</th><th>Date</th><th class="num">Appels</th>'
              '<th class="num">Pannes</th><th class="num">Sans réponse</th>'
              '<th class="num">Coût</th><th class="num">Citation</th><th>Note</th></tr>')
    serie = [h for h in c["journal"]["lignes"] if not h["hors_serie"]]
    hors = [h for h in c["journal"]["lignes"] if h["hors_serie"]]

    # Les essais de mise au point sont REPLIÉS, pas supprimés : ils gardent
    # leur ligne datée (le garde-fou --sauf-si-recente s'appuie dessus) mais
    # ils ne se lisent plus au même rang que les vraies collectes. Sans ce
    # repli, 13 lignes de 3 appels noyaient les 3 collectes réelles.
    replie = ""
    if hors:
        replie = (f'<details class="hors"><summary>{len(hors)} collecte'
                  f'{"s" if len(hors) > 1 else ""} hors série : moins d\'appels que '
                  f'de requêtes suivies, donc sans couverture du jeu — essais de mise '
                  f'au point ou collecte interrompue</summary>'
                  f'<div class="tw"><table class="d">{entete}'
                  f'{"".join(ligne(h) for h in hors)}</table></div></details>')

    bloc_journal = f"""<section class="card">
  <div class="card__head"><h2>Le journal des collectes</h2>
    <span class="card__hint">{len(serie)} collecte{"s" if len(serie) > 1 else ""}
      de la série{f" · {len(hors)} hors série" if hors else ""}</span></div>
  <p class="card__lead">Chaque collecte interroge tous les moteurs sur toutes les requêtes,
  plusieurs fois. <strong>Les réponses brutes sont conservées horodatées</strong> : les taux se
  recalculent, une réponse perdue ne se rattrape pas.
  <br><strong>Pannes</strong> : le fournisseur a renvoyé une erreur, c'est réparable.
  <strong>Sans réponse</strong> : l'appel a abouti mais la réponse est vide, typiquement
  une requête où Google n'affiche pas d'AI&nbsp;Overview. Les deux sortent du taux,
  une seule demande quelque chose. <em>Les additionner, comme le faisait l'ancienne
  colonne « Erreurs », faisait passer un comportement normal pour un incident.</em></p>
  <div class="tw"><table class="d">{entete}
  {''.join(ligne(h) for h in serie)}</table></div>{replie}</section>"""

    return f"""<div class="conshd">
  <button class="btn--ghost" data-copy="{_e(c['diagnostic'])}"
          data-ok="Diagnostic copié">Copier le diagnostic</button>
  <span class="conshd__aide">Colle-le dans une conversation avec Claude : il contient
    l'état de la machine et les messages bruts des fournisseurs.</span>
</div>
{bloc_actions}{bloc_subi}{bloc_etat}{bloc_journal}"""


# ------------------------------------------------------------------ la page

def rendu(d: dict) -> str:
    m = d["meta"]
    return f"""<div class="app">
  <aside class="side">
    <div class="side__client" title="{_e(m['client_label'])}">{_e(m['client_initiale'])}</div>
    <button class="nav" role="tab" aria-selected="true" aria-controls="v-ens"
            title="Vue d'ensemble" aria-label="Vue d'ensemble">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="2" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/></svg><span>Vue d'ensemble</span></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-mot"
            title="Moteurs et sujets" aria-label="Moteurs et sujets">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="12" height="12" rx="2.4" stroke="currentColor" stroke-width="1.6"/>
        <path d="M2 6.4 H14 M6.4 6.4 V14" stroke="currentColor" stroke-width="1.4"/>
        <rect x="8.4" y="8.4" width="3.6" height="3.2" rx="1" fill="currentColor"/></svg><span>Moteurs et sujets</span></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-cit"
            title="Pages citées" aria-label="Pages citées">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M6.6 9.4 L9.4 6.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        <path d="M7.8 4.6 L9.2 3.2 a2.6 2.6 0 0 1 3.6 3.6 L11.4 8.2" stroke="currentColor"
              stroke-width="1.6" stroke-linecap="round" fill="none"/>
        <path d="M8.2 11.4 L6.8 12.8 a2.6 2.6 0 0 1 -3.6 -3.6 L4.6 7.8" stroke="currentColor"
              stroke-width="1.6" stroke-linecap="round" fill="none"/></svg><span>Pages citées</span></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-req"
            title="Requêtes" aria-label="Requêtes">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="12" height="12" rx="3" stroke="currentColor" stroke-width="1.6"/>
        <circle cx="5.6" cy="5.6" r="1.05" fill="currentColor"/>
        <circle cx="10.4" cy="5.6" r="1.05" fill="currentColor"/>
        <circle cx="8" cy="8" r="1.05" fill="currentColor"/>
        <circle cx="5.6" cy="10.4" r="1.05" fill="currentColor"/>
        <circle cx="10.4" cy="10.4" r="1.05" fill="currentColor"/></svg><span>Requêtes</span></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-col"
            title="Console" aria-label="Console">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="1.8" y="2.8" width="12.4" height="10.4" rx="2" stroke="currentColor"
              stroke-width="1.6"/>
        <path d="M4.8 6.6 L6.8 8 L4.8 9.4" stroke="currentColor" stroke-width="1.6"
              stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M8.6 10 H11" stroke="currentColor" stroke-width="1.6"
              stroke-linecap="round"/></svg><span>Console</span></button>
  </aside>
  <main class="main">
    <div class="print-head"><strong>{_e(m['produit_nom'])} · {_e(m['client_label'])}</strong>
      <span>Collecte #{m['run_id']} · {_e(m['date'])} · {_e(m['produit_signature'])}</span></div>
    <header class="mhead">
      <div><h1>{_e(m['client_label'])}</h1>
        <p class="mhead__sub">Collecte #{m['run_id']} · {_e(m['date'])} ·
          {m['n_appels']} appel{'' if m['n_appels'] < 2 else 's'} · {_e(m['prochaine_collecte'])}</p></div>
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
    <div id="v-ens" role="tabpanel">{_vue_ensemble(d)}</div>
    <div id="v-mot" role="tabpanel" hidden>{_vue_moteurs_sujets(d)}</div>
    <div id="v-cit" role="tabpanel" hidden>{_vue_citations(d)}</div>
    <div id="v-req" role="tabpanel" hidden>{_vue_requetes(d["jeu_requetes"])}</div>
    <div id="v-col" role="tabpanel" hidden>{_vue_console(d["console"])}</div>
  </main>
</div>
<style>{CSS}</style>
<script>{JS}</script>"""
