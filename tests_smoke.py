"""Tests de fumée. Ils tournent sur la configuration d'EXEMPLE (fictive) :
aucune marque réelle, aucun concurrent réel dans les assertions, et le
gabarit `config/clients/exemple.yaml` est ainsi vérifié en continu."""

from geotracker.config import load_client
from geotracker.extract import analyse, find_brand_mention
from geotracker.models import EngineResponse, Source, domain_matches

cfg = load_client("exemple")

# 1. matching de domaines
assert domain_matches("https://www.maison-dupont.fr/atelier?a=1", "maison-dupont.fr")
assert domain_matches("blog.maison-dupont.fr", "maison-dupont.fr")
assert not domain_matches("notmaison-dupont.fr", "maison-dupont.fr")
assert not domain_matches("maison-dupont.fr.evil.ru", "maison-dupont.fr")
print("OK  domaines (sous-domaines oui, homographes non)")

# 2. mention de marque, insensible aux accents et aux bornes de mot
assert find_brand_mention("Voir Maison Dupont pour commander.", cfg.brand_terms) == 5
assert find_brand_mention("Le site maison-dupont propose...", cfg.brand_terms) == 8
assert find_brand_mention("Aucune marque ici.", cfg.brand_terms) is None
print("OK  mention de marque")

# 3. analyse complete : cite en source rang 3 + mention texte
r = EngineResponse(
    engine_id="test", provider="test", model="m", search_enabled=True,
    answer_text="Plusieurs options existent. Maison Dupont propose un travail soigné.",
    sources=[
        Source(1, "https://www.atelier-martin.fr/tables", "Atelier Martin"),
        Source(2, "https://fournil-durand.fr/sur-mesure", "Fournil Durand"),
        Source(3, "https://www.maison-dupont.fr/atelier", "Maison Dupont"),
        Source(4, "https://exemple-annuaire.fr/menuisiers", "Annuaire"),
    ],
)
m, s = analyse(r, cfg)
assert m["cited"] is True and m["source_rank"] == 3, m
assert m["cited_in_text"] is True and m["n_sources"] == 4
assert 0.3 < m["text_position"] < 0.5, m["text_position"]
assert s[0]["competitor"] == "Atelier Martin"
assert s[2]["is_target"] is True
print("OK  analyse : rang", m["source_rank"], "| position texte", m["text_position"])

# 4. non cite du tout
r2 = EngineResponse("t", "t", "m", True,
                    answer_text="Atelier Martin et Fournil Durand sont des ateliers.",
                    sources=[Source(1, "https://atelier-martin.fr", "Atelier Martin")])
m2, _ = analyse(r2, cfg)
assert m2["cited"] is False and m2["source_rank"] is None
print("OK  cas non cite")

# 5. erreur moteur : on ne perd rien, on enregistre quand meme
r3 = EngineResponse("t", "t", "m", True, error="HTTP 429", raw={"x": 1})
m3, s3 = analyse(r3, cfg)
assert m3["cited"] is False and s3 == [] and r3.raw == {"x": 1}
print("OK  erreur moteur non bloquante, brut conserve")

# 6. extraction d'attributs : co-presence marque + attribut dans une phrase
from geotracker.attributs import attributs_dans

trouves, exemples = attributs_dans(
    "Maison Dupont fabrique des tables en chêne sur mesure. "
    "L'atelier de Lyon est reputé. Le bois massif vieillit bien.",
    cfg.brand_terms, cfg.attributs,
)
# « chêne » et « sur mesure » sont dans LA phrase de la marque ; « atelier »
# et « bois massif » sont dans d'autres phrases : ils ne comptent pas.
assert trouves == {"bois-massif", "sur-mesure"}, trouves
assert "chêne" in exemples["bois-massif"]
t2, _ = attributs_dans("L'atelier travaille le chêne.", cfg.brand_terms, cfg.attributs)
assert t2 == set(), t2
# Le point d'un domaine ne coupe PAS la phrase (defaut v1 corrige le 06/08) :
# la marque en forme de domaine garde son contexte.
t3, _ = attributs_dans("Le site maison-dupont.fr propose des tables en chêne.",
                       cfg.brand_terms, cfg.attributs)
assert t3 == {"bois-massif"}, t3
# Un slug d'URL ne fabrique PAS un attribut (2e piege corrige le 06/08) : la
# marque est nommee par le lien, mais rien n'est DIT en prose.
t4, _ = attributs_dans("Voir maison-dupont.fr/tables-chene-sur-mesure pour commander.",
                       cfg.brand_terms, cfg.attributs)
assert t4 == set(), t4
print("OK  attributs : co-presence par phrase, domaines non coupes, slugs exclus")

# 7. carnet d'idees : insertion textuelle dans le YAML, commentaires intacts
import yaml as _yaml
from geotracker.carnet import inserer_prompts, prochain_id

assert prochain_id(["q01", "q02", "q03"]) == "q04"
assert prochain_id([]) == "q01"

_texte = cfg.path.read_text(encoding="utf-8")
_nouveau = inserer_prompts(_texte, [("q04", 'Ou trouver une table "rustique" ?')],
                           "2026-08-06")
_relu = _yaml.safe_load(_nouveau)
assert len(_relu["prompts"]) == 4
assert _relu["prompts"][3] == {"id": "q04",
                              "text": 'Ou trouver une table "rustique" ?',
                              "statut": "observation"}
# La chirurgie preserve TOUT le reste du fichier : memes commentaires,
# memes cles, seule la fin du bloc prompts a change.
assert _nouveau.count("#") == _texte.count("#") + 1  # le commentaire d'import
assert "plafond_observation: 5" in _nouveau
print("OK  carnet : insertion chirurgicale, ids, guillemets echappes")

# 8. exactitude des faits : juste / faux / muet (chantier c, 08/08)
from geotracker.faits import verdict

fait = cfg.faits[0]  # le label « Artisan en Or » du gabarit d'exemple
assert verdict("Le label Artisan en Or est décerné par la fédération.", fait) == "juste"
assert verdict("Ils portent le label artisan d'or depuis 2019.", fait) == "faux"
assert verdict("Maison Dupont est un atelier réputé.", fait) == "muet"
# Jamais depuis une URL : un slug ne prouve pas que le modèle DIT la réponse.
assert verdict("Voir https://exemple.fr/artisan-en-or pour vérifier.", fait) == "muet"
# Bornes de mots strictes : le cas réel du chantier, MAPS ≠ MAPST.
f2 = {"juste": ["MAPST"], "faux": ["MAPS"]}
assert verdict("Le MAPST remplace l'APT.", f2) == "juste"
assert verdict("Le MAPS remplace l'APT.", f2) == "faux"
# Juste et faux co-présents : juste gagne (limite documentée dans faits.py).
assert verdict("Le MAPST, parfois écrit MAPS à tort.", f2) == "juste"
assert verdict("", f2) == "muet"
# `contexte` (resserrage 08/08) : la preuve ne compte que dans une phrase qui
# porte aussi le contexte — le cas réel : « tronc commun » vaut pour l'APSF
# comme pour l'ASEC, seul le contexte les départage.
f3 = {"contexte": ["APSF"], "juste": ["tronc commun"], "faux": ["4 blocs"]}
assert verdict("L'APSF propose un tronc commun.", f3) == "juste"
assert verdict("L'ASEC repose sur un tronc commun. L'APSF évolue aussi.", f3) == "muet"
assert verdict("L'APSF garde 4 blocs.", f3) == "faux"
print("OK  faits : juste/faux/muet, URLs exclues, MAPS≠MAPST, contexte par phrase")

# 9. etats vides : aucun bloc ne disparait sans un mot (passe du 06/08).
# Les fonctions de rendu s'appellent avec des dictionnaires ecrits a la main,
# sans base : c'est exactement ce que l'architecture garantit.
from geotracker import dashboard_rendu as rendu

# A faire vide : le constat, pas une carte muette
h = rendu._a_faire({"items": []})
assert "plus de trou évident à combler" in h, h
# Duel : pas de rival = disparition (choix documente) ; rival sans donnees = attente dite
assert rendu._duel({"rival_configure": False, "lignes": [], "affiche": False,
                    "rival_label": None, "menees": 0, "perdues": 0, "egales": 0}) == ""
h = rendu._duel({"rival_configure": True, "lignes": [], "affiche": False,
                 "rival_label": "Atelier Martin", "menees": 0, "perdues": 0, "egales": 0})
assert "attend une collecte" in h and "Atelier Martin" in h
# Matrice vide : jamais une vue blanche
h = rendu._matrice({"affiche": False, "lead": {}, "colonnes": [], "lignes": []})
assert "première collecte réussie" in h
# Forteresses (dominance fusionnee dedans le 12/08/2026) : jamais citee, la
# phrase de dominance NE SORT PAS — elle pretendrait « source n°1 dans 0 % des
# cas » alors qu'il n'y a aucune citation d'ou tirer une part. Garantie heritee
# de l'ancienne carte Dominance, elle survit a la fusion.
h = rendu._forteresses({"lead": {"variante": "vide", "texte_requete": None, "taux": None},
                        "part_n1": 0, "part_texte": 0, "a_dominance": False, "items": []})
assert "en moyenne" not in h and "au-dessus de 60 %" in h
# Et quand il y a de la dominance, les deux mesures tiennent sur la meme ligne.
# Le test porte sur la GARANTIE (le chiffre global sort, la part par requete
# aussi), pas sur la formulation exacte : le chapeau se reecrit, la garantie non.
h = rendu._forteresses({"lead": {"variante": "exemples", "texte_requete": "Q ?", "taux": 90.0},
                        "part_n1": 32.0, "part_texte": 21.0, "a_dominance": True,
                        "items": [{"texte": "Q ?", "taux": 90.0, "part_n1": 32.0},
                                  {"texte": "R ?", "taux": 70.0, "part_n1": None}]})
assert "32&nbsp;%" in h and "<b>32 %</b>" in h
# part_n1 absente : « — », jamais un faux 0 % (meme regle que le hero mort)
assert "<b>—</b>" in h

# --- Courbe de visibilite : l'axe part de zero, la marge prime sur le signe -
_cv = {"variante": "tracee", "marge": 6.7, "n_moteurs": 3, "haut": 66.0,
       "bas": 59.0, "amplitude": 5.0,
       "points": [{"date": "2026-07-29", "taux": 59.0, "delta": None, "dans_marge": None},
                  {"date": "2026-08-03", "taux": 66.0, "delta": 6.1, "dans_marge": True},
                  {"date": "2026-08-10", "taux": 64.0, "delta": -1.5, "dans_marge": True}]}
h = rendu._courbe(_cv)
# ⛔ L'axe commence a ZERO : tronquer une echelle de pourcentage exagererait
# le moindre ecart, sur un instrument dont tout l'argument est l'inverse.
assert '>0&nbsp;%<' in h, "la graduation zero doit exister"
assert '>75&nbsp;%<' in h and '>100&nbsp;%<' not in h  # sommet ajuste, pas fixe
# Chaque point porte son ecart ET de quel cote de la marge il tombe : c'est
# ce que l'infobulle lit, et c'est le garde-fou n1 rendu point par point.
assert 'data-delta="6.1" data-marge="1"' in h
assert 'data-delta="" data-marge=""' in h          # 1re collecte : pas d'ecart
assert 'class="cv__band"' in h and 'class="cv__line"' in h
# Le survol vise une DATE : autant de zones que de points, pleine hauteur.
assert h.count('class="cv__hit"') == 3
# Une seule serie : pas de legende, le titre nomme la courbe.
assert "legend" not in h.lower()
print("OK  courbe : axe a zero, ecart et marge par point, zones de survol")

# --- Scan des pages concurrentes : extraction PURE, sans reseau ------------
# Le module lit des sites tiers, qui changent : le test ne doit dependre
# d'AUCUN d'entre eux. `signaux()` est donc une fonction pure, verifiee sur
# un HTML ecrit a la main.
from geotracker.concurrents import signaux, est_plateforme

_riche = """<html><head>
<script type="application/ld+json">{"@graph":[
 {"@type":"Article","dateModified":"2026-08-04T10:00:00+02:00",
  "author":{"@type":"Person","name":"Julie Martin"}},
 {"@type":"Organization","sameAs":["https://fr.wikipedia.org/x","https://linkedin.com/y"]}]}
</script></head><body>
<nav><a href="/blog/taux">Blog</a></nav><p>Une intro.</p>
<table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table>
<ul><li>un</li></ul><a href="https://sports.gouv.fr/t">source</a>
<div class="author-box">Par Julie</div></body></html>"""
s = signaux(_riche, "https://exemple.fr/page")
assert s["blog"] and s["auteur"] and s["auteur_nom"] == "Julie Martin"
assert s["maj"] == "2026-08-04"          # le balisage prime sur la meta plus vieille
assert s["tableaux"] == 2 and s["listes"] == 1
assert s["same_as"] == 2 and s["mentions_ext"] >= 3

# Une page nue : tout tombe a FAUX, et rien ne plante
nu = signaux("<html><body><p>rien</p></body></html>", "https://x.fr/")
assert not nu["blog"] and not nu["auteur"] and nu["maj"] is None
assert nu["tableaux"] == 0 and nu["mentions_ext"] == 0

# HTML casse : on garde ce qu'on a pu lire, on ne leve jamais
casse = signaux("<html><body><table><tr><td>a<ul><li>x", "https://x.fr/")
assert casse["tableaux"] == 1

# Les plateformes sont ecartees : demander si une video YouTube « a un blog »
# produirait une ligne vide de sens, lue comme un point faible du concurrent.
assert est_plateforme("youtube.com") and est_plateforme("www.youtube.com")
# Domaine fictif : ce fichier part sur le depot PUBLIC, aucun nom de
# concurrent reel ne doit y figurer (regle du miroir).
assert not est_plateforme("centre-exemple.fr")

# Points faibles : sans trou, la carte le CONSTATE au lieu de lister du vide
h = rendu._faiblesses({"seuil": 25.0, "aucune": True, "n_total": 0, "items": []})
assert "pas de trou à combler" in h
# Avec des trous : l'occupant est nomme, et un terrain vide se dit autrement
h = rendu._faiblesses({"seuil": 25.0, "aucune": False, "n_total": 4, "items": [
    {"texte": "Q1 ?", "taux": 0.0, "cites": 0, "ok": 20, "occupants": ["exemple.fr"]},
    {"texte": "Q2 ?", "taux": 8.0, "cites": 1, "ok": 12, "occupants": []}]})
assert "exemple.fr" in h and "terrain libre" in h
assert "d'une liste de 4" in h          # le reste non affiche est annonce
assert "occupe la place à la tienne" in h  # la carte nomme l'occupant
# Part de voix sans aucune source
h = rendu._voix({"total_citations": 1, "domaines_distincts": 0,
                 "stats": {"place": None, "place_suffixe": "e", "domaines": 0,
                           "part": None, "rang": None},
                 "lead": {"variante": "vide", "poursuivant": None, "ecart": None},
                 "lignes": []})
assert "rien à classer" in h
# Hero d'une collecte morte : « — », pas un faux 0 %
h = rendu._hero({"taux": 0, "mesurable": False, "n_moteurs": 4,
                 "titre": "Aucun appel exploitable sur cette collecte",
                 "badge": None, "phrase": "Les 255 appels ont tous échoué.",
                 "appels_reussis": 0, "palier": 10, "reste": 10.0, "contenus": None,
                 "sante": {"variante": "muette", "texte": "tout est tombé"}})
assert ">—" in h and "0<small>%</small>" not in h and "Palier" not in h
print("OK  etats vides : chaque bloc dit pourquoi il est vide")

# 10. le JavaScript de l'interface est syntaxiquement valide
#
# Panne reelle du 29/07 au 05/08/2026 : la constante JS n'etait pas une chaine
# brute, Python a converti un « \n » du JavaScript en vrai retour a la ligne,
# la chaine n'etait plus fermee et TOUT le script mourait au chargement.
# L'interface restait belle et rien ne cliquait. Ce test rend la panne bruyante.
import shutil, subprocess, tempfile, pathlib
from geotracker.dashboard_rendu import JS

if shutil.which("node"):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(JS)
        chemin = f.name
    v = subprocess.run(["node", "--check", chemin], capture_output=True, text=True)
    pathlib.Path(chemin).unlink()
    assert v.returncode == 0, f"JavaScript invalide :\n{v.stderr}"
    print("OK  javascript de l'interface valide")
else:
    print("--  javascript non verifie (node absent)")

# 11. la config incohérente est refusée au chargement (passe 7, 08/08) :
# même logique que la config illisible, on ne génère pas une page fausse.
_src = cfg.path.read_text(encoding="utf-8")
_casse = (_src.replace("rival: atelier-martin.fr", "rival: maison-dupont.fr")
              .replace("requetes: [q01]", "requetes: [q99]"))
_tmp = cfg.path.parent / "casse-test.yaml"
_tmp.write_text(_casse, encoding="utf-8")
try:
    try:
        load_client("casse-test")
        raise AssertionError("la config incohérente aurait dû être refusée")
    except SystemExit as e:
        _msg = str(e)
        assert "rival" in _msg and "q99" in _msg, _msg
finally:
    _tmp.unlink()
print("OK  config incohérente refusée (rival = cible, requête fantôme)")

print("\n11/11 tests passes")
