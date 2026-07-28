# Tracker GEO

Le SEO suit des **positions** sur des mots-clés. Le GEO suit des **citations** sur des prompts.

Une position Google est stable : tu la regardes une fois, tu as ta réponse. Une réponse de LLM est non déterministe : pose la même question trois fois, tu peux être citée une fois sur trois. On ne peut donc pas **constater** une visibilité IA, on peut seulement **l'échantillonner**.

Cet outil transforme quelque chose d'instable en métrique : un taux de citation sur N répétitions × M moteurs, rejoué à intervalle fixe.

## Ce qu'il mesure

Pour chaque réponse, trois choses seulement :

1. la marque est-elle **citée** ?
2. à quel **rang** dans la réponse (en source, et en position dans le texte) ?
3. quelles **sources** sont citées, donc **qui prend la place** ?

Puis on agrège en taux, et on rejoue chaque semaine pour obtenir une courbe.

> Être cité ne suffit pas : il faut être en position dominante ET sur les bons sujets.
> C'est ce que les outils du marché ne mesurent pas. Eux comptent les citations.

## Moteurs

| Moteur | Ce qu'on interroge | Fidélité au produit grand public |
|---|---|---|
| `anthropic` | Claude + recherche web | proche |
| `anthropic-memory` | Claude **sans** recherche | mesure la « mémoire de marque » |
| `openai` | ChatGPT + recherche web | proche |
| `perplexity` | API sonar | proche |
| `ai_overview` | Google AI Overviews via DataForSEO | **exacte** (vraie SERP) |

Le mode `anthropic-memory` répond à une question que les outils du marché ne posent pas : le modèle connaît-il la marque **sans aller chercher** ? C'est l'indicateur le plus lent et le plus durable qui existe.

## Limite assumée

Les moteurs 1 à 4 interrogent des **modèles via API**, pas les **interfaces** grand public. Les écarts viennent du system prompt du produit, de la personnalisation et du routage. Tous les outils du marché ont cette limite ; celui-ci la documente et la calibre : **une requête témoin par mois vérifiée à la main** dans la vraie interface, consignée dans le journal.

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Clés

**Il n'y a pas de `.env` dans ce dépôt, et il ne faut pas en créer.** Les clés vivent dans un trousseau unique, commun à tous les projets, situé **hors de ce dépôt** : elles ne peuvent donc pas être commitées ici par accident.

| Variable | Où l'obtenir |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com (facturation séparée de l'abonnement Claude) |
| `OPENAI_API_KEY` | platform.openai.com |
| `PERPLEXITY_API_KEY` | perplexity.ai > Settings > API |
| `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | dataforseo.com (un login et un mot de passe, pas une clé) |

Ordre de résolution : variables d'environnement déjà définies (les secrets GitHub Actions gagnent toujours) → `TROUSSEAU_PATH` si défini → le trousseau commun → un `.env` local en dernier recours. Une valeur encore marquée `<À FOURNIR…>` est ignorée, pas prise pour une vraie clé.

Pour le cron GitHub, les mêmes variables doivent être créées en **secrets du dépôt**.

## Usage

```bash
# Voir le plan sans rien appeler ni rien dépenser
python -m geotracker.run --dry-run

# Test à petite échelle avant de lancer le vrai run
python -m geotracker.run --engines perplexity --prompts 2 --repetitions 1

# Le run complet
python -m geotracker.run --client smart-bpjeps

# Lire les résultats
python -m geotracker.report            # dernier run vs précédent
python -m geotracker.report --serie    # la courbe
```

## Règles à ne pas casser

1. **On garde le brut.** Chaque réponse complète est stockée horodatée dans `data/runs.sqlite3`. Les agrégats se recalculent, une réponse perdue ne se rattrape pas. C'est le seul actif non copiable du projet.
2. **On ne change pas le modèle en cours de série.** Changer de modèle casse la comparabilité. Si c'est nécessaire, faire tourner l'ancien et le nouveau en parallèle un mois.
3. **Ajouter une requête est sans danger. En modifier ou en retirer une, non.** Passer par un nouveau `set_version` dans le YAML.

## Structure

```
config/clients/*.yaml   le jeu de suivi (requêtes, concurrents, moteurs) — un fichier par client
geotracker/engines/     un adaptateur par moteur, contrat commun, aucun ne casse le run
geotracker/extract.py   les 3 extractions — pur, rejouable sur le brut déjà stocké
geotracker/db.py        SQLite, commit par réponse
geotracker/report.py    agrégation, aucun stockage
data/runs.sqlite3       LA valeur du projet
```

Le schéma est multi-domaines dès le départ : un seul client dedans aujourd'hui, aucune migration à faire le jour où il y en a un deuxième.
