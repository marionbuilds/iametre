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

from .format import nb as _nb


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

.side{flex:none; width:138px; position:sticky; top:16px; height:calc(100vh - 32px);
  min-height:480px; background:var(--forest); color:var(--sur-forest); border-radius:26px;
  padding:16px 10px 18px; display:flex; flex-direction:column; align-items:center; gap:8px}
.brand{margin-bottom:16px}
.brand__mark{width:44px; height:44px; border-radius:14px; background:rgba(239,246,232,.14);
  display:grid; place-items:center}
/* Passe 1 : le libellé de vue est VISIBLE à côté de l'icône (avant, les noms
   de vues n'existaient qu'en title/aria-label, donc invisibles). */
.nav{display:flex; align-items:center; gap:9px; width:100%; height:44px; border:none;
  background:none; color:var(--sur-forest-soft); border-radius:15px; cursor:pointer;
  padding:0 13px; font-family:inherit}
.nav svg{flex:none}
.nav span{font-size:.8rem; font-weight:700; letter-spacing:.02em}
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
.duel{display:grid}
.duel__row{display:grid; grid-template-columns:minmax(0,1fr) 250px; gap:16px; align-items:center;
  padding:11px 0; border-bottom:1px solid var(--line)}
.duel__row:last-child{border-bottom:none}
.duel__row>p{font-size:.87rem; font-weight:600}
.duel__bars{display:grid; gap:5px}
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

.hero{background:var(--paper); border:1px solid var(--line); border-radius:22px;
  padding:30px 32px; display:grid; grid-template-columns:auto 1fr auto; gap:36px;
  align-items:center; margin-bottom:18px}
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
/* Passe 1 : la règle graduée et la mission vivent DANS la carte « À faire ». */
.card > .ruler{margin:4px 0 22px}
.card .mission{margin:0 0 14px}

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
.grid{display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px;
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

.engines{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:14px; margin-bottom:18px}
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
.health{font-size:.78rem; color:var(--ink-soft); margin-top:8px;
  padding-left:11px; border-left:2px solid var(--line)}
.health--ok{border-left-color:var(--data)}
.health--bad{border-left-color:var(--alert); color:var(--alert); font-weight:600}
.eng__meta{font-family:var(--f-mono); font-size:.72rem; color:var(--ink-faint);
  margin-bottom:8px}
.eng__meta b{color:var(--ink-soft)}
.eng__warn{color:var(--alert); font-weight:700}

/* Matrice moteur x requete : le croisement, la ou se lisent les decisions. */
.mx{overflow-x:auto}
table.mx__t{border-collapse:separate; border-spacing:0; width:100%; font-size:.82rem}
table.mx__t th,table.mx__t td{padding:7px 8px; border-bottom:1px solid var(--line)}
table.mx__t thead th{font-size:.68rem; font-weight:700; color:var(--ink-faint);
  letter-spacing:.05em; text-transform:uppercase; text-align:center; white-space:nowrap;
  vertical-align:bottom; padding-bottom:9px}
table.mx__t thead th small{display:block; font-family:var(--f-mono); font-size:.78rem;
  color:var(--ink-soft); letter-spacing:0; text-transform:none; margin-top:3px}
table.mx__t th.mx__q{text-align:left; width:38%}
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
.al__flag{display:inline-block; font-size:.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.07em; padding:3px 8px; border-radius:6px; margin-top:9px;
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


# --------------------------------------------------- les blocs, un par carte

def _hero(h: dict) -> str:
    """Passe 1 : le hero ne dit plus que l'ÉTAT. La règle graduée est partie
    dans « À faire » (une promesse d'action), les stats à côté de voix (une
    preuve). La jauge garde son palier : c'est un repère de lecture."""
    taux = h["taux"]
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
    return f"""  <section class="hero">
    <div class="gauge">
      <svg viewBox="0 0 210 130" aria-hidden="true">
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--piste)"
              stroke-width="14" stroke-linecap="round"/>
        <path d="M20 110 A85 85 0 0 1 190 110" fill="none" stroke="var(--signal)"
              stroke-width="14" stroke-linecap="round" stroke-dasharray="{L * taux / 100:.1f} {L}"/>
      </svg>
      <div class="gauge__value">{taux:.0f}<small>%</small>
        <div class="gauge__perim">{h["n_moteurs"]} moteurs</div></div>
    </div>
    <div class="hero__mid">
      <h2>{h["titre"]}{badge}</h2>
      <p class="eyebrow">Visibilité IA</p>
      <p>Mesuré sur <strong>{h["appels_reussis"]} appels réussis</strong>, {h["n_moteurs"]} moteurs. {_e(h["phrase"])}</p>
      {sante_html}
    </div>
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
        a = m["appels"]
        appels = f'{a["ok"]} appels'
        if a["en_erreur"]:
            appels = (f'<span class="eng__warn">{a["ok"]}/{a["total"]} appels, '
                      f'{a["erreurs"]} échec(s)</span>')
        eng += (f'<article class="eng{" eng--zero" if m["est_zero"] else ""}">'
                f'<h3>{_e(m["nom"])}</h3>'
                f'<div class="eng__rate">{m["taux"]:.0f} %</div>'
                f'<div class="eng__bar"><i style="width:{max(m["taux"], 2):.0f}%"></i></div>'
                f'<div class="eng__meta">{rang} · {appels}</div>'
                f'<p>{_e(m["lecture"])}</p>{tags.get(m["tag"], "")}</article>')
    return eng


def _a_faire(af: dict) -> str:
    """Passe 1 : la section unique « À faire ». En tête, la règle graduée
    (ex-hero : c'est une promesse d'action, pas un état). Puis trois entrées
    classées par impact décroissant, structure unifiée : la première mise en
    avant comme l'ancienne mission, les suivantes en retrait."""
    r = af["regle"]
    taux, palier = r["taux"], r["palier"]
    reste_txt = f"<strong>+{r['reste']:.0f} pts restants</strong>"
    if r["contenus"]:
        reste_txt += f" · <strong>{r['contenus']} à {r['contenus'] + 1} contenus</strong>"

    tete = ""
    if af["items"]:
        q = af["items"][0]
        tete = f"""
  <section class="mission">
    <div>
      <div class="mission__eyebrow">Ta prochaine action · opportunité n°1</div>
      <h2>{_cite(q['question'])}</h2>
      <p>{_e(q['diagnostic'])}
      <strong>C'est le sujet où un contenu rapporterait le plus.</strong></p>
    </div>
    <div class="mission__side">
      <div class="mission__impact">{_e(q['impact'])}<small>impact estimé, borne basse</small></div>
      <div class="mission__acts">
        <button class="btn btn--primary" data-copy="{_e(q['recette'])}" data-ok="Recette copiée, colle-la dans une IA">Copier la recette d'article</button>
      </div>
    </div>
  </section>"""

    suite = "".join(
        f'<article class="queue__card"><div class="queue__txt">'
        f'<span class="queue__rank">Article n°{q["numero"]}</span>'
        f'<h3>{_cite(q["question"])}</h3><p>{_e(q["diagnostic"])} '
        f'<strong>{_e(q["impact"])}</strong> sur le taux global.</p>'
        f'<button class="btn--mini" data-copy="{_e(q["recette"])}" '
        f'data-ok="Recette copiée">Copier la recette d\'article</button></div>'
        f'<div class="queue__rate{" queue__rate--warn" if q["taux_warn"] else ""}">'
        f'{q["taux"]:.0f} %</div></article>'
        for q in af["items"][1:]
    )
    queue = f'<div class="queue">{suite}</div>' if suite else ""

    return f"""
  <section class="card">
    <div class="card__head"><h2>À faire</h2>
      <span class="card__hint">classées par impact sur le taux global</span></div>
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
{tete}
    {queue}
  </section>"""


def _voix(v: dict) -> str:
    lead = v["lead"]
    lead_voix = (
        f"La marque domine, mais <strong>{_e(lead['poursuivant'])} n'est "
        f"qu'à {_nb(lead['ecart'])} pts</strong>."
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
            ecart = (f'<span class="lb__gap">à {_nb(ligne["ecart"])} pts '
                     f'derrière la marque</span>')
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
    lead = (
        f"<strong>{_e(f['lead']['texte_requete'])}</strong> à {f['lead']['taux']:.0f} % : la preuve que la "
        f"méthode fonctionne. Il suffit de la répliquer sur les sujets ci-dessus."
        if f["lead"]["variante"] == "exemples"
        else "Aucune requête au-dessus de 60 % pour l'instant."
    )
    st = "".join(
        f'<li><h3>{_e(q["texte"])} <span>{q["taux"]:.0f} %</span></h3>'
        f'<div class="st__bar"><i style="width:{q["taux"]:.0f}%"></i></div></li>'
        for q in f["items"]
    )
    return f"""    <section class="card">
      <div class="card__head"><h2>Tes forteresses</h2>
        <span class="card__hint">ce qui a été travaillé se voit</span></div>
      <p class="card__lead">{lead}</p>
      <ul class="st">{st}</ul>
    </section>"""


def _dominance(dom: dict) -> str:
    items = "".join(
        f'<li><h3>{_e(x["texte"])} <span>{x["part"]:.0f} %</span></h3>'
        f'<div class="st__bar"><i style="width:{max(x["part"], 2):.0f}%"></i></div></li>'
        for x in dom["items"]
    ) or "<li>Aucune citation sur cette collecte.</li>"
    return f"""    <section class="card">
      <div class="card__head"><h2>Dominance</h2>
        <span class="card__hint">source n°1, pas juste citée</span></div>
      <p class="card__lead">Être citée ne suffit pas. Quand la marque apparaît, elle est
      <strong>source n°1 dans {dom["part_n1"]:.0f} % des cas</strong>, et nommée dans le texte même
      de la réponse dans {dom["part_texte"]:.0f} % des appels. C'est la prochaine frontière une fois
      la citation acquise.</p>
      <ul class="st">{items}</ul>
    </section>"""


def _duel(du: dict) -> str:
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
  <p class="card__lead">La courbe se dessine à partir de la deuxième collecte, qui arrive
  automatiquement. En attendant, le repère qui compte :
  <strong>la marge de fluctuation de cette mesure est de ±{_nb(marge)} pts.</strong>
  Une réponse d'IA n'est pas stable : à effort constant, le taux oscille naturellement dans
  cette bande. Une variation qui reste dedans n'est ni une victoire ni une alerte ; seuls un
  mouvement qui en sort ou une tendance sur 3-4 collectes sont de vrais signaux.</p>
</section>"""

    serie = c["points"]
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
    # Chaque chiffre porte son périmètre SUR LUI (règle du 05/08) : l'étiquette
    # du dernier point dit sur combien de moteurs il est mesuré. La ligne
    # courte de l'en-tête suffit, pas de phrase d'explication en plus.
    n_mot = c["n_moteurs"]
    dernier = serie[-1]
    etiquette = (f'<text x="{xs[-1]:.1f}" y="{y(dernier["taux"]) - 12:.1f}" text-anchor="end" '
                 f'class="curve__val">{dernier["taux"]:.0f} % · {n_mot} moteurs</text>')

    return f"""<section class="card">
  <div class="card__head"><h2>Courbe de visibilité</h2>
    <span class="card__hint">périmètre constant : {n_mot} moteurs communs ·
    bande grisée : marge de fluctuation ±{_nb(marge)} pts</span></div>
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


def _matrice(mx: dict) -> str:
    if not mx["affiche"]:
        return ""
    entetes = "".join(
        f'<th>{_e(col["nom_court"])}<small>{col["taux"]:.0f} %</small></th>'
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
    if mx["lead"]["muettes"]:
        lead += (f"<strong>{mx['lead']['muettes']} requête(s)</strong> ne sortent chez aucun moteur : "
                 f"ce sont les trous à combler en premier, un contenu les débloque "
                 f"partout à la fois.")
    else:
        lead += "Chaque requête sort au moins chez un moteur."

    return f"""
  <section class="card">
    <div class="card__head"><h2>Quel moteur te cite, sur quel sujet</h2>
      <span class="card__hint">réponses qui citent la marque, sur le nombre d'appels</span></div>
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
            qs += f'<span class="al__q"><span>+ {p["reste"]} autre(s) requête(s)</span></span>'
        flag = ""
        if p["flag"] is not None and p["flag"]["variante"] == "accueil":
            flag = (f'<span class="al__flag">l\'accueil répond à {p["flag"]["n"]} questions '
                    f'précises : autant de pages dédiées qui manquent</span>')
        elif p["flag"] is not None:
            flag = (f'<span class="al__flag">cette page absorbe {p["flag"]["n"]} sujets '
                    f'différents : vérifier qu\'elle répond vraiment à chacun, sinon les '
                    f'pages dédiées manquent</span>')
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

def _vue_produit(d: dict) -> str:
    """La vue produit (Passe 1). Quatre niveaux, dans l'ordre strict :
    où j'en suis (hero, courbe) → à faire (règle, mission, articles) →
    où pousser (duel) → la preuve (matrice, voix + stats, alignement,
    forteresses, dominance). Un bloc qui ne répond ni au chiffre, ni à
    l'action, ni à la preuve n'est pas dans cette vue."""
    return f"""
{_hero(d["hero"])}
{_courbe(d["courbe"])}
{_a_faire(d["a_faire"])}
{_duel(d["duel"])}
{_matrice(d["matrice"])}

  <div class="grid">
{_voix(d["voix"])}
{_alignement(d["alignement"])}
  </div>

  <div class="grid">
{_forteresses(d["forteresses"])}
{_dominance(d["dominance"])}
  </div>

  <div class="engines">{_moteurs(d["moteurs"])}</div>"""


def _vue_machine(d: dict) -> str:
    """La vue machine (Passe 1) : ce qui fait tourner l'instrument, pas ce
    qu'il mesure. Collectes et jeu de requêtes."""
    return f"""{_vue_collectes(d["collectes"])}
{_requetes_machine(d["jeu_requetes"])}"""


def _requetes_machine(j: dict) -> str:
    """La carte du jeu de requêtes, SANS le tableau : il a fusionné dans la
    matrice, qui porte la même information en plus riche. Le formulaire de
    proposition reste inchangé (il sera traité dans une passe suivante)."""
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
    <button class="btn--report" id="req-valider">Valider</button>
  </div>
  <div class="reqattente" id="req-attente" hidden>
    <p class="reqattente__t">En attente d'intégration à la prochaine collecte
      (~1&nbsp;$/mois par requête) :</p>
    <ul id="req-liste"></ul>
    <a id="req-envoyer" class="btn--mini" target="_blank" rel="noopener"
       href="https://github.com/marionbuilds/tracker-geo/issues/new">Transmettre au tracker</a>
  </div></section>"""


def _vue_collectes(c: dict) -> str:
    def ligne(h):
        t = f'{h["taux"]:.0f} %' if h["taux"] is not None else "—"
        return (f'<tr><td class="n">#{h["id"]}</td><td class="n">{_e(h["date"])}</td>'
                f'<td class="n">{h["n"]}</td><td class="n">{h["erreurs"] or "—"}</td>'
                f'<td class="n">{t}</td><td>{_e(h["note"])}</td></tr>')

    return f"""<section class="card">
  <div class="card__head"><h2>Collectes</h2>
    <span class="card__hint">{c['n']} enregistrées</span></div>
  <p class="card__lead">Chaque collecte interroge tous les moteurs sur toutes les requêtes,
  plusieurs fois. <strong>Les réponses brutes sont conservées horodatées</strong> : les taux se
  recalculent, une réponse perdue ne se rattrape pas.</p>
  <div class="tw"><table class="d">
  <tr><th>Réf.</th><th>Date</th><th>Appels</th><th>Erreurs</th><th>Citation</th><th>Note</th></tr>
  {''.join(ligne(h) for h in c['lignes'])}</table></div></section>"""


# ------------------------------------------------------------------ la page

def rendu(d: dict) -> str:
    m = d["meta"]
    return f"""<div class="app">
  <aside class="side">
    <div class="brand" title="{_e(m['produit_nom'])} · {_e(m['produit_signature'])}">
      <div class="brand__mark" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 20 20" fill="none">
          <path d="M2 15 L2 11 M5.2 15 L5.2 8 M8.4 15 L8.4 11 M11.6 15 L11.6 5 M14.8 15 L14.8 11 M18 15 L18 8"
                stroke="#EFF6E8" stroke-width="1.8" stroke-linecap="round"/></svg>
      </div>
    </div>
    <button class="nav" role="tab" aria-selected="true" aria-controls="v-prod"
            title="Produit" aria-label="Produit">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="2" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="2" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/>
        <rect x="8.8" y="8.8" width="5.2" height="5.2" rx="1.6" stroke="currentColor" stroke-width="1.6"/></svg><span>Produit</span></button>
    <button class="nav" role="tab" aria-selected="false" aria-controls="v-mach"
            title="Machine" aria-label="Machine">
      <svg width="19" height="19" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.7"/>
        <path d="M8 4.5 L8 8 L10.6 9.6" stroke="currentColor" stroke-width="1.7"
              stroke-linecap="round"/></svg><span>Machine</span></button>
    <div class="side__sep"></div>
    <div class="side__client" title="{_e(m['client_label'])}">{_e(m['client_initiale'])}</div>
  </aside>
  <main class="main">
    <div class="print-head"><strong>{_e(m['produit_nom'])} · {_e(m['client_label'])}</strong>
      <span>Collecte #{m['run_id']} · {_e(m['date'])} · {_e(m['produit_signature'])}</span></div>
    <header class="mhead">
      <div><h1>{_e(m['client_label'])}</h1>
        <p class="mhead__sub">Collecte #{m['run_id']} · {_e(m['date'])} ·
          {m['n_appels']} appels · {_e(m['prochaine_collecte'])}</p></div>
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
    <div id="v-prod" role="tabpanel">{_vue_produit(d)}</div>
    <div id="v-mach" role="tabpanel" hidden>{_vue_machine(d)}</div>
  </main>
</div>
<style>{CSS}</style>
<script>{JS}</script>"""
