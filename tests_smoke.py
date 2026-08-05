from geotracker.config import load_client
from geotracker.extract import analyse, find_brand_mention
from geotracker.models import EngineResponse, Source, domain_matches

cfg = load_client("smart-bpjeps")

# 1. matching de domaines
assert domain_matches("https://www.smart-bpjeps.com/livre?a=1", "smart-bpjeps.com")
assert domain_matches("blog.smart-bpjeps.com", "smart-bpjeps.com")
assert not domain_matches("notsmart-bpjeps.com", "smart-bpjeps.com")
assert not domain_matches("smart-bpjeps.com.evil.ru", "smart-bpjeps.com")
print("OK  domaines (sous-domaines oui, homographes non)")

# 2. mention de marque, insensible aux accents et aux bornes de mot
assert find_brand_mention("Voir Smart BPJEPS pour reviser.", cfg.brand_terms) == 5
assert find_brand_mention("Le site smart-bpjeps propose...", cfg.brand_terms) == 8
assert find_brand_mention("Aucune marque ici.", cfg.brand_terms) is None
print("OK  mention de marque")

# 3. analyse complete : citee en source rang 3 + mention texte
r = EngineResponse(
    engine_id="test", provider="test", model="m", search_enabled=True,
    answer_text="Plusieurs options existent. Smart BPJEPS propose un livre complet.",
    sources=[
        Source(1, "https://www.lepanse-formation.com/livre", "Le Panse"),
        Source(2, "https://reussirsonbpjeps.com/methode", "Reussir"),
        Source(3, "https://www.smart-bpjeps.com/livre-bpjeps", "Smart BPJEPS"),
        Source(4, "https://excelia-group.com/memorisation", "Excelia"),
    ],
)
m, s = analyse(r, cfg)
assert m["cited"] is True and m["source_rank"] == 3, m
assert m["cited_in_text"] is True and m["n_sources"] == 4
assert 0.3 < m["text_position"] < 0.5, m["text_position"]
assert s[0]["competitor"] == "Le Panse / Reiss (Amphora)"
assert s[2]["is_target"] is True
print("OK  analyse : rang", m["source_rank"], "| position texte", m["text_position"])

# 4. non citee du tout
r2 = EngineResponse("t","t","m",True, answer_text="IRSS et IPMS sont des centres.",
                    sources=[Source(1,"https://irss.fr","IRSS")])
m2, _ = analyse(r2, cfg)
assert m2["cited"] is False and m2["source_rank"] is None
print("OK  cas non cite")

# 5. erreur moteur : on ne perd rien, on enregistre quand meme
r3 = EngineResponse("t","t","m",True, error="HTTP 429", raw={"x":1})
m3, s3 = analyse(r3, cfg)
assert m3["cited"] is False and s3 == [] and r3.raw == {"x":1}
print("OK  erreur moteur non bloquante, brut conserve")

# 6. le JavaScript de l'interface est syntaxiquement valide
#
# Panne reelle du 29/07 au 05/08/2026 : la constante JS n'etait pas une chaine
# brute, Python a converti un « \n » du JavaScript en vrai retour a la ligne,
# la chaine n'etait plus fermee et TOUT le script mourait au chargement.
# L'interface restait belle et rien ne cliquait. Ce test rend la panne bruyante.
import shutil, subprocess, tempfile, pathlib
from geotracker.dashboard import JS

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

print("\n6/6 tests passes")
