"""Ce que font les pages qui te devancent — scan sans API payante.

    python -m geotracker.concurrents                    # dernière collecte
    python -m geotracker.concurrents --run 16
    python -m geotracker.concurrents --seuil 40         # élargir aux requêtes moyennes
    python -m geotracker.concurrents --dry-run          # montre les pages, n'appelle rien

Le tracker dit QUI prend la place. Ce module va lire ces pages-là et mesure
ce qu'elles ont que la nôtre n'a pas : un blog, un auteur affiché, une date de
mise à jour, des tableaux, des mentions extérieures dans le balisage. Les six
critères viennent de la méthode d'audit de Marion (12/08/2026), et ils ont
tous été choisis pour une raison : **ils se vérifient dans le HTML**, sans
Ahrefs, sans Semrush, sans abonnement. Décision explicite : ni backlinks ni
autorité de domaine tant qu'on ne paye pas.

⚠️ CE QUE CE MODULE NE FAIT PAS, ET NE DOIT JAMAIS PRÉTENDRE FAIRE.
Il constate des DIFFÉRENCES, il n'établit pas de CAUSE. « Il est plus frais
que toi » n'est pas « il est devant parce qu'il est plus frais » : c'est le
garde-fou n°3 du produit, et un tableau comparatif est précisément le genre
d'objet qui donne envie de l'oublier. Tout affichage tiré d'ici doit rester au
constat.

⚠️ LE BRUT N'EST PAS CONSERVÉ, contrairement aux réponses d'IA.
Garder le HTML complet de ~20 pages par collecte gonflerait une base qui est
versionnée dans Git. On stocke donc les signaux extraits, pas la page. La
conséquence est réelle et assumée : **un scan est un instantané daté qui ne se
rejoue pas** — une page relue dans trois mois aura changé. C'est l'inverse de
la règle qui vaut pour les réponses d'IA, où le brut est le seul actif.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from . import db
from .config import load_client
from .models import normalize_domain

# Un vrai navigateur : plusieurs sites renvoient une page vide ou un 403 à un
# client sans en-têtes. On s'annonce quand même, on ne se déguise pas.
ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
                   "IAmetre/1.0 (audit GEO)"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

SCHEMA_SCAN = """
CREATE TABLE IF NOT EXISTS pages_scan (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    client       TEXT NOT NULL,
    prompt_id    TEXT NOT NULL,
    url          TEXT NOT NULL,
    domain       TEXT NOT NULL,
    est_cible    INTEGER NOT NULL DEFAULT 0,   -- 1 = notre page, 0 = celle d'un autre
    scanne_le    TEXT NOT NULL,
    lisible      INTEGER NOT NULL,
    raison       TEXT,                          -- pourquoi illisible, le cas échéant
    signaux_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_run ON pages_scan(run_id);
"""

# Chemins qui trahissent un espace éditorial. Volontairement large : mieux
# vaut un faux positif visible qu'un « pas de blog » qui serait faux.
MOTIFS_BLOG = ("/blog", "/actualite", "/actualités", "/article", "/conseil",
               "/guide", "/magazine", "/ressource", "/dossier", "/news",
               "/astuce", "/tuto")

# Plateformes où les six critères n'ont AUCUN sens : demander si une vidéo
# YouTube « a un blog » ou « affiche un auteur » produirait une ligne de
# tableau vide de sens, qui se lirait pourtant comme un point faible du
# concurrent. Elles sont écartées du scan et l'affichage le dit — le fait
# qu'elles occupent le terrain reste visible sur la carte « points faibles »,
# c'est là qu'il appartient.
PLATEFORMES = ("youtube.com", "facebook.com", "instagram.com", "tiktok.com",
               "linkedin.com", "x.com", "twitter.com", "reddit.com",
               "pinterest.com", "dailymotion.com")


def est_plateforme(domaine: str) -> bool:
    d = normalize_domain(domaine)
    return any(d == p or d.endswith("." + p) for p in PLATEFORMES)


class _Page(HTMLParser):
    """Extraction en une passe. `html.parser` est dans la bibliothèque
    standard : aucune dépendance ajoutée au projet, qui n'en a que trois."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = 0
        self.listes = 0
        self.liens: list[str] = []
        self.jsonld: list[str] = []
        self.metas: dict[str, str] = {}
        self.times: list[str] = []
        self.classes_auteur = 0
        self.rel_auteur = False
        self.texte: list[str] = []
        self._dans_jsonld = False
        self._dans_texte = 0
        self._ignore = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables += 1
        elif tag in ("ul", "ol"):
            self.listes += 1
        elif tag == "a":
            if a.get("href"):
                self.liens.append(a["href"])
            if "author" in (a.get("rel") or ""):
                self.rel_auteur = True
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._dans_jsonld = True
        elif tag in ("script", "style", "nav", "footer"):
            self._ignore += 1
        elif tag == "meta":
            cle = a.get("property") or a.get("name")
            if cle and a.get("content"):
                self.metas[cle.lower()] = a["content"]
        elif tag == "time" and a.get("datetime"):
            self.times.append(a["datetime"])
        elif tag in ("p", "h1", "h2", "h3", "li", "td"):
            self._dans_texte += 1
        # Encart auteur : la convention de classe est stable d'un CMS à l'autre.
        signature = f'{a.get("class", "")} {a.get("id", "")} {a.get("itemprop", "")}'.lower()
        if re.search(r"\b(author|auteur|byline|redacteur|rédacteur)", signature):
            self.classes_auteur += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._dans_jsonld = False
        if tag in ("script", "style", "nav", "footer"):
            self._ignore = max(0, self._ignore - 1)
        elif tag in ("p", "h1", "h2", "h3", "li", "td"):
            self._dans_texte = max(0, self._dans_texte - 1)

    def handle_data(self, data):
        if self._dans_jsonld:
            self.jsonld.append(data)
        elif self._dans_texte and not self._ignore:
            self.texte.append(data)


def _aplatir(obj):
    """Un JSON-LD est souvent un @graph, une liste, ou des objets imbriqués.
    On rend tous les dictionnaires qu'il contient, à n'importe quel niveau."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _aplatir(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _aplatir(v)


def signaux(contenu: str, url: str) -> dict:
    """Les six critères, extraits d'une page. FONCTION PURE : aucun réseau,
    donc testable hors ligne avec un HTML écrit à la main — c'est la règle du
    projet, et c'est ce qui rend ce module vérifiable sans dépendre d'un site
    tiers qui changera."""
    p = _Page()
    try:
        p.feed(contenu)
    except Exception:                       # HTML cassé : on garde ce qu'on a
        pass

    blocs = []
    for brut in p.jsonld:
        try:
            blocs.extend(_aplatir(json.loads(brut)))
        except (ValueError, TypeError):
            continue

    # ① Un blog ? On cherche un espace éditorial dans les liens du site, et on
    #    accepte aussi que l'URL scannée EN SOIT un article.
    hote = normalize_domain(url)
    chemins = [urlparse(urljoin(url, h)).path.lower() for h in p.liens]
    a_blog = (any(m in urlparse(url).path.lower() for m in MOTIFS_BLOG)
              or any(any(m in c for m in MOTIFS_BLOG) for c in chemins))

    # ② Un auteur affiché ? Trois preuves indépendantes, la première suffit.
    auteur_nom = None
    for b in blocs:
        a = b.get("author")
        if isinstance(a, dict) and a.get("name"):
            auteur_nom = str(a["name"])[:80]
            break
        if isinstance(a, str) and a.strip():
            auteur_nom = a.strip()[:80]
            break
    a_auteur = bool(auteur_nom) or p.rel_auteur or p.classes_auteur > 0

    # ③ Fraîcheur : le balisage d'abord (fiable), les balises <time> ensuite.
    maj = None
    for cle in ("datemodified", "dateModified", "datepublished", "datePublished"):
        for b in blocs:
            if b.get(cle) and isinstance(b[cle], str):
                maj = b[cle]
                break
        if maj:
            break
    if not maj:
        maj = (p.metas.get("article:modified_time")
               or p.metas.get("article:published_time")
               or (p.times[0] if p.times else None))
    maj = (maj or "")[:10] or None

    # ⑤ Mentions extérieures : le `sameAs` du balisage (l'entité se rattache à
    #    des références connues) ET les liens sortants vers d'autres domaines.
    same_as = set()
    for b in blocs:
        s = b.get("sameAs")
        if isinstance(s, str):
            same_as.add(s)
        elif isinstance(s, list):
            same_as.update(str(x) for x in s if isinstance(x, str))
    externes = set()
    for h in p.liens:
        d = normalize_domain(urljoin(url, h))
        if d and d != hote and not d.endswith("." + hote):
            externes.add(d)

    mots = len(" ".join(p.texte).split())
    return {
        "blog": a_blog,
        "auteur": a_auteur,
        "auteur_nom": auteur_nom,
        "maj": maj,
        "tableaux": p.tables,
        "listes": p.listes,
        "same_as": len(same_as),
        "domaines_externes": len(externes),
        "mentions_ext": len(same_as) + len(externes),
        "mots": mots,
        # Le balisage d'entité : ce que le site DÉCLARE être. C'est la
        # question « OK, cette personne ou cette compagnie, c'est ça ».
        "types_balises": sorted({str(b.get("@type")) for b in blocs
                                 if isinstance(b.get("@type"), str)})[:8],
    }


def lire(client: httpx.Client, url: str) -> tuple[str | None, str | None]:
    """Renvoie (contenu, raison_d_echec). ⚠️ Une page qui ne se laisse pas
    lire n'est JAMAIS enregistrée comme une page sans blog et sans auteur :
    l'absence de preuve n'est pas une preuve d'absence, et c'est exactement
    le genre de faux silencieux que le produit chasse depuis la passe 7."""
    try:
        r = client.get(url, headers=ENTETES, follow_redirects=True, timeout=20)
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    if "html" not in r.headers.get("content-type", ""):
        return None, f"type {r.headers.get('content-type', '?')[:40]}"
    if len(r.text) < 500:
        return None, "page quasi vide (rendue en JavaScript ?)"
    return r.text, None


def pages_a_scanner(conn, run_id: int, client: str, seuil: float,
                    par_requete: int) -> list[dict]:
    """Les requêtes faibles, et pour chacune : la page la plus citée de
    chaque domaine qui occupe le terrain, plus la nôtre s'il y en a une.

    Tout vient de la table `sources`, déjà remplie à chaque collecte : ce
    module ne déclenche AUCUNE collecte supplémentaire.
    """
    cfg = load_client(client)
    exclure = tuple(sorted(p.id for p in cfg.prompts if p.statut == "observation"))
    cl = f" AND prompt_id NOT IN ({','.join('?' * len(exclure))})" if exclure else ""

    faibles = [
        r["prompt_id"] for r in conn.execute(
            f"""SELECT prompt_id,
                       SUM(COALESCE(cited,0)) * 1.0
                         / NULLIF(SUM(CASE WHEN {db.EXPLOITABLE} THEN 1 ELSE 0 END), 0)
                         * 100 AS taux
                FROM responses
                WHERE run_id=? AND search_enabled=1{cl}
                GROUP BY prompt_id
                HAVING taux IS NOT NULL AND taux < ?
                ORDER BY taux""",
            (run_id, *exclure, seuil),
        ).fetchall()
    ]

    sortie = []
    for pid in faibles:
        lignes = conn.execute(
            """SELECT s.url, s.domain, s.is_target, COUNT(*) n
               FROM sources s JOIN responses r ON r.id = s.response_id
               WHERE r.run_id=? AND r.prompt_id=? AND s.url IS NOT NULL AND s.url<>''
               GROUP BY s.url ORDER BY n DESC""",
            (run_id, pid),
        ).fetchall()
        vus, retenus = set(), []
        for l in lignes:
            if l["is_target"]:
                # La nôtre passe toujours, elle sert de colonne « toi ».
                if not any(x["est_cible"] for x in retenus):
                    retenus.append(dict(prompt_id=pid, url=l["url"],
                                        domain=l["domain"], est_cible=1, n=l["n"]))
                continue
            if est_plateforme(l["domain"]) or l["domain"] in vus or len(vus) >= par_requete:
                continue
            vus.add(l["domain"])
            retenus.append(dict(prompt_id=pid, url=l["url"], domain=l["domain"],
                                est_cible=0, n=l["n"]))
        sortie.extend(retenus)
    return sortie


def scanner(conn, run_id: int, client: str, seuil: float, par_requete: int,
            dry_run: bool = False) -> int:
    conn.executescript(SCHEMA_SCAN)
    cibles = pages_a_scanner(conn, run_id, client, seuil, par_requete)
    if not cibles:
        print(f"Aucune requête sous {seuil:.0f} % avec des sources : rien à scanner.")
        return 0

    print(f"{len(cibles)} page(s) à lire, sur "
          f"{len({c['prompt_id'] for c in cibles})} requête(s) faible(s).")
    if dry_run:
        for c in cibles:
            marque = "TOI " if c["est_cible"] else "    "
            print(f"  {marque}{c['prompt_id']}  {c['url'][:96]}")
        print("\n--dry-run : aucune page n'a été lue.")
        return 0

    # Une page déjà lue pour ce run ne se relit pas : deux requêtes citent
    # souvent la même page, et on ne va pas taper deux fois chez les gens.
    cache: dict[str, tuple] = {}
    quand = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lus = 0
    with httpx.Client() as http:
        for c in cibles:
            if c["url"] in cache:
                contenu, raison = cache[c["url"]]
            else:
                contenu, raison = lire(http, c["url"])
                cache[c["url"]] = (contenu, raison)
            sig = signaux(contenu, c["url"]) if contenu else None
            conn.execute(
                """INSERT INTO pages_scan (run_id, client, prompt_id, url, domain,
                       est_cible, scanne_le, lisible, raison, signaux_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (run_id, client, c["prompt_id"], c["url"], c["domain"],
                 c["est_cible"], quand, 1 if sig else 0, raison,
                 json.dumps(sig, ensure_ascii=False) if sig else None),
            )
            etat = "ok" if sig else f"illisible ({raison})"
            print(f"  {c['domain']:<34} {etat}")
            lus += 1 if sig else 0
    conn.commit()
    print(f"\n{lus}/{len(cibles)} page(s) lue(s), enregistrées sur la collecte #{run_id}.")
    print("⚠️  Ce scan CONSTATE des différences, il n'établit aucune cause.")
    return lus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--client", default="smart-bpjeps")
    ap.add_argument("--run", type=int)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--seuil", type=float, default=25.0,
                    help="taux de citation en dessous duquel une requête est faible")
    ap.add_argument("--par-requete", type=int, default=3,
                    help="nombre de domaines concurrents scannés par requête")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    conn = db.connect(a.db)
    run_id = a.run
    if run_id is None:
        ligne = conn.execute(
            "SELECT id FROM runs WHERE client=? ORDER BY id DESC LIMIT 1", (a.client,)
        ).fetchone()
        if ligne is None:
            print("Aucune collecte enregistrée.")
            return 1
        run_id = ligne["id"]
    n = scanner(conn, run_id, a.client, a.seuil, a.par_requete, a.dry_run)
    conn.close()
    return 0 if (n or a.dry_run) else 1


if __name__ == "__main__":
    sys.exit(main())
