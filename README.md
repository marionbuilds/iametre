# IAmètre

Un outil de mesure de la visibilité d'une marque dans les réponses des IA génératives : ChatGPT, Claude, Perplexity et Google AI Overviews. Construit et utilisé sur mes propres sites.

**Stack** : Python · GitHub Actions (collecte automatique tous les lundis) · SQLite · APIs Anthropic, OpenAI, Perplexity et DataForSEO.

**Série en cours** : démarrée le 29 juillet 2026, collecte hebdomadaire automatique. Ce qui a de la valeur ici n'est pas l'outil, c'est la durée : la courbe se construit une semaine à la fois.

![Le tableau de bord du tracker](docs/dashboard.png)

## Le problème

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
> C'est pour ça que le rang et les domaines concurrents sont stockés à chaque réponse, et pas seulement le fait d'être cité.

## Moteurs

| Moteur | Ce qu'on interroge | Fidélité au produit grand public |
|---|---|---|
| `anthropic` | Claude + recherche web | proche |
| `openai` | ChatGPT + recherche web | proche |
| `perplexity` | API sonar | proche |
| `ai_overview` | Google AI Overviews via DataForSEO | **exacte** (vraie SERP) |
| `anthropic-memory` | Claude **sans** recherche | **éteint** depuis le 10/08/2026, voir ci-dessous |

### La mémoire de marque, et pourquoi elle n'est plus collectée chaque semaine

Le mode `anthropic-memory` interroge le modèle **sans recherche web**. Il ne mesure donc pas ce que le modèle trouve, mais ce qu'il sait : la marque est-elle connue sans aller la chercher ? On n'y entre pas en optimisant son site, on y entre quand le reste du web parle de la marque.

Il a été **éteint le 10 août 2026**, et la raison est une erreur de conception qui vaut d'être écrite : *le modèle interrogé est figé* — la règle « on ne change pas de modèle en cours de série » l'impose — **donc sa mémoire l'est aussi**. Ses poids ne bougent pas entre deux lundis. Les 30 appels hebdomadaires ne mesuraient aucune évolution : ils reconfirmaient une constante, 0 citation sur 30 à trois collectes complètes d'affilée.

Ce n'est pas un indicateur hebdomadaire, c'est **un indicateur par version de modèle**. Il se rallume le jour où l'on veut comparer une nouvelle génération à celle-ci — pas avant. La métrique reste juste et reste rare : le raisonnement complet est en tête du bloc dans le YAML client, pour qu'il soit lu avant tout rallumage par réflexe.

Ce que l'extinction change dans les chiffres, et ce qu'elle ne change pas : les 90 réponses déjà collectées **restent en base**, le taux de visibilité ne bouge pas d'un point (la mémoire n'y entrait déjà pas, elle vit sur son propre axe), seul le nombre d'appels par collecte passe de 255 à 225.

## Les attributs : ce que le modèle dit de la marque

Être cité répond à « est-ce qu'on me voit ». La question suivante est « qu'est-ce que le modèle dit de moi » : quels attributs il associe à la marque quand il en parle — le livre, les fiches, la plateforme, la personne qui la porte.

```bash
python -m geotracker.attributs        # rejoué sur tout l'historique
```

La règle de comptage : un attribut compte quand un de ses termes apparaît **dans la même phrase** qu'une mention de la marque, et jamais depuis une URL — un lien vers `/oral-bpjeps` nomme la marque, il ne dit rien d'elle. Le lexique d'attributs vit dans le YAML du client, comme le reste.

Deux limites, assumées : le découpage de phrases est fruste (dans les listes à puces, la marque et l'attribut se retrouvent parfois séparés — les chiffres sont donc des bornes basses), et le lexique de départ est minimal ; il s'enrichit dans le YAML sans coût, puisque l'extraction se rejoue.

Un point de méthode qui compte : cette métrique a été écrite le 6 août et s'est calculée sur les collectes du 28 juillet. C'est ce que permet la conservation du brut : les agrégats se recalculent, y compris ceux qui n'existaient pas encore au moment de la collecte.

## L'exactitude des faits : est-ce que le modèle dit juste ?

Sur une question comme « quel diplôme remplace celui-ci ? », la citation n'est pas la bonne métrique : ce qui compte est la justesse de la réponse. Un fait vérifiable se déclare dans le YAML du client — les requêtes où il est attendu, les termes qui prouvent la bonne réponse, les erreurs déjà observées dans le brut — et chaque réponse reçoit un verdict : **juste**, **faux**, ou **muet**.

```bash
python -m geotracker.faits              # rejoué sur tout l'historique
```

Quatre limites, avant tout résultat. Un fait n'est cherché que dans les requêtes où on l'attend, et **la liste des erreurs est construite par observation** : elle attrape ce qui a déjà été vu, pas ce qui pourrait l'être — les « faux » sont donc une borne basse. Une négation (« ce diplôme ne remplace pas… ») serait comptée juste, cas rare mais réel. Quand la bonne réponse et une erreur connue apparaissent dans la même réponse, **juste l'emporte** : une coquille d'acronyme à côté de l'information correcte n'est pas une erreur de fond. Enfin, croiser un verdict juste avec le fait d'être cité en source est une **co-occurrence, pas une attribution** : être cité dans une réponse juste ne prouve pas que le modèle tient l'information de vous.

Deux règles de comptage héritées des attributs : jamais depuis une URL — un lien nommant la marque ne prouve pas que le modèle *dit* la bonne réponse —, et des bornes de mots strictes, pour qu'un sigle proche n'en valide pas un autre. Quand un terme de preuve est trop générique pour trancher seul, le fait déclare un contexte, et la preuve ne compte que dans une phrase qui le porte.

Ce que ça a donné, tant que le moteur sans recherche web était collecté : il ne connaissait **aucun** des faits déclarés — cohérent avec ce que mesurait la « mémoire de marque », et c'en était le prolongement : de « connaît-il la marque » à « connaît-il le domaine ».

## Les cinq garde-fous

**La marge de fluctuation.** Un taux de citation calculé sur un échantillon a une marge d'erreur. Elle est calculée à 95 % (`_marge()`, dans `dashboard_donnees.py`) et l'outil **refuse d'appeler « progression » un mouvement qui tient dedans** : il l'écrit à l'écran, en toutes lettres.

> *« Variation de 5,2 pts : dans la marge de fluctuation normale (±6,7 pts), ce n'est ni une progression ni un recul. »*


**La comparabilité de périmètre.** Deux collectes ne se comparent que si elles portent sur les **mêmes moteurs** et les **mêmes requêtes**. Quand ce n'est pas le cas, la collecte est écartée du calcul et le rapport le dit, plutôt que de produire un écart qui ne veut rien dire.

**Ce qui compte comme un appel mesuré.** Un appel n'entre dans le taux que s'il a produit une réponse : ni erreur, ni réponse vide. Une panne d'API comptée comme une non-citation ferait ressembler une panne à une chute de visibilité. Et une requête où Google n'affiche aucun AI Overview n'est pas une requête où la marque n'est pas citée : il n'y a pas eu de réponse où l'être — la faire compter reviendrait à mesurer un comportement de Google, pas une visibilité. Cette définition est écrite **à un seul endroit** (`EXPLOITABLE`, dans `db.py`) et interpolée par tous les calculs — rapport, tableau de bord, attributs, exactitude : aucun dénominateur ne peut diverger d'un autre. Corrigé le 8 août 2026, après qu'un banc d'essai sur données anormales a montré des réponses vides comptées comme des non-citations.

**Une configuration incohérente ne produit rien.** Un fichier de suivi peut être valide en YAML et faux en pratique : un concurrent à suivre qui est en réalité le domaine mesuré (le duel se jouerait contre soi-même), une requête référencée dans un fait mais absente du jeu (une faute de frappe qui survivrait indéfiniment), un lexique vide qui resterait à zéro pour toujours. Ces cas sont vérifiés au chargement, et l'outil **s'arrête en listant les incohérences** au lieu de produire une page plausible et fausse.

**L'évolution n'est pas une cause.** Depuis le 07/08/2026, tout le site est balisé en entités : la série mesure donc un **avant-après**, pas une expérience contrôlée (celle qui avait été montée a été close sans résultat, sa trace est dans le YAML). Un avant-après ne démontre aucune causalité : une hausse peut venir du balisage, mais aussi de la saisonnalité BPJEPS (rentrée) ou d'une mise à jour des modèles interrogés. L'outil suit une évolution, il ne prouve pas une cause, et tout ce qui en est présenté doit le dire.

## Limite assumée

Tous les moteurs sauf Google AI Overviews interrogent des **modèles via API**, pas les **interfaces** grand public. Les écarts viennent du system prompt du produit, de la personnalisation et du routage. Cet écart existe, donc il est calibré : **une requête témoin par mois, posée à la main dans la vraie interface**, et l'écart consigné dans le journal.

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

# Les deux extractions rejouables, sur tout l'historique
python -m geotracker.attributs         # ce que les modèles associent à la marque
python -m geotracker.faits             # est-ce qu'ils disent juste

# Importer les idées de requêtes proposées depuis le dashboard
python -m geotracker.carnet ~/Downloads/propositions-requetes.json
```

Le dashboard s'ouvre en `file://` et ne peut pas écrire sur le disque : les idées de requêtes s'y téléchargent en un fichier, que cette commande importe dans le YAML au statut « observation » — collectées dès le lundi suivant, hors taux global le temps de les valider. La commande propose elle-même le commit et le push : la collecte lit le dépôt.

## Règles à ne pas casser

1. **On garde le brut.** Chaque réponse complète est stockée horodatée dans `data/runs.sqlite3`. Les agrégats se recalculent à volonté, une réponse perdue ne se rattrape pas : c'est pour ça que tout est conservé, et que les extractions sont rejouables sur l'existant.
2. **On ne change pas le modèle en cours de série.** Changer de modèle casse la comparabilité. Si c'est nécessaire, faire tourner l'ancien et le nouveau en parallèle un mois.
3. **Ajouter une requête est sans danger. En modifier ou en retirer une, non.** Passer par un nouveau `set_version` dans le YAML.

## Structure

```
config/clients/*.yaml   le jeu de suivi (requêtes, concurrents, moteurs) — un fichier par site
geotracker/engines/     un adaptateur par moteur, contrat commun, aucun ne casse le run
geotracker/extract.py   les 3 extractions — pur, rejouable sur le brut déjà stocké
geotracker/db.py        SQLite, commit par réponse
geotracker/report.py    agrégation, aucun stockage
geotracker/faits.py     exactitude des faits — pur, rejouable, comme extract.py
data/runs.sqlite3       tout le brut, horodaté
```

Le schéma est multi-domaines dès le départ : un seul site suivi aujourd'hui, aucune migration à faire le jour où il y en a un deuxième.

## Ce que ce projet m'a appris

- **Une réponse d'IA n'est pas une position Google.** Elle bouge d'un appel à l'autre, donc un « cité / pas cité » ponctuel ne dit rien. Tout le reste découle de là.
- **Un écart n'est pas un résultat.** Tant qu'un mouvement tient dans la marge de fluctuation, ce n'est pas un mouvement. C'est la fonctionnalité que j'ai le plus retravaillée.
- **Comparer deux collectes qui n'ont pas le même périmètre produit des chiffres flatteurs et faux.** D'où le garde-fou : mieux vaut ne rien afficher qu'afficher une progression inventée.
- **Un appel qui échoue n'est pas une absence de citation.** Confondre les deux transforme une panne d'API en chute de visibilité. Une réponse vide non plus : c'est la même erreur, en plus discret.
- **Une définition dupliquée finit par diverger.** « Qu'est-ce qu'un appel qui compte » vivait dans quatorze requêtes SQL ; deux d'entre elles avaient déjà pris un autre sens. Une seule définition, interpolée partout, rend la divergence impossible plutôt qu'improbable.
- **Interroger une API n'est pas interroger le produit grand public.** D'où le calibrage manuel mensuel, plutôt que de faire comme si l'écart n'existait pas.
