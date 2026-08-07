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
print("OK  faits : juste/faux/muet, URLs exclues, MAPS ne matche pas MAPST")

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
# Dominance jamais citee : le lead ne pretend pas « 0 % des cas »
h = rendu._dominance({"vide": True, "part_n1": 0, "part_texte": 0, "items": []})
assert "première citation" in h and "0 % des cas" not in h
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

print("\n10/10 tests passes")
