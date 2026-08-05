# ARCHITECTURE — Séparation données / rendu du dashboard

> Document préparatoire à la refactorisation, **validé par Marion le 05/08/2026 avec
> trois amendements** (formatage des nombres, déterminisme, guillemets/noms de fichiers),
> intégrés ci-dessous.
> Objectif : deux couches nettes. `donnees` construit un dictionnaire JSON-sérialisable
> décrivant tout ce que la page affiche ; `rendu` le transforme en HTML sans toucher
> ni à SQLite, ni aux YAML, ni au système de fichiers.
> Règle absolue de la refactorisation initiale : HTML identique **au caractère près**
> à `reports/reference-avant-refactor.html` — vérifié le 05/08/2026, `cmp` muet.
> **PASSE 1 (05/08/2026, corrigée le jour même)** : restructuration délibérée de
> l'interface. Le HTML change, la référence ne pilote plus rien (gardée comme trace).
> **5 vues à libellés visibles** : Vue d'ensemble (hero avec règle graduée, moteurs,
> À faire, duel, voix + stats, forteresses + dominance, courbe en dernier) ·
> Moteurs et sujets (matrice) · Ce que les IA citent chez toi (alignement) ·
> Requêtes (compteurs + formulaire) · Collectes. Acquis : `pages_resume` supprimé,
> mission + articles fusionnés en « À faire » (contexte et brief OPTIONNELS, portés
> par l'entrée n°1 : une fusion ne supprime pas de fonctionnalité), tableau des
> requêtes fusionné dans la matrice. Les tables du §3 reflètent cet état.

---

## 1. Découpage des fichiers

| Fichier | Rôle | Contenu |
|---|---|---|
| `geotracker/format.py` | **Module neutre** | `nb()` (nombres à la française) et toute fonction de formatage typographique partagée. **N'importe rien du projet.** La data et le render l'importent tous les deux ; aucun import direct entre data et render, dans aucun sens |
| `geotracker/dashboard_donnees.py` | **Couche 1 — data** | `donnees(conn, run_id, date_du_jour) -> dict`. Seule couche qui ouvre SQLite et lit les YAML. Reprend : `collecte()`, `_exclusion`, `_impact`, `_marge`, `_promesse`, `_objectif`, `_lecture_moteur`, `_diagnostic`, `_prochaine_collecte`, `_brief`, `_prompt_ia`, `SEUIL_TROU`, `NOMS_MOTEURS`, `NOMS_COURTS` |
| `geotracker/dashboard_rendu.py` | **Couche 2 — render** | `rendu(d: dict) -> str` et une fonction par bloc visuel. Reprend : `CSS`, `JS`, `_e` (échappement), `_cite` (guillemets français). Aucun import de `db`, `config`, `report` ni `dashboard_donnees` |
| `geotracker/dashboard.py` | **CLI, inchangé d'usage** | `python -m geotracker.dashboard` garde exactement les mêmes options. Orchestration : ouvre la base → `donnees()` → `rendu()` → écrit le fichier. Plus l'option d'export JSON (§5) |

Les tests (`tests_smoke.py`, test 6) continuent d'importer `JS` — depuis `dashboard_rendu`.

## 2. La frontière entre les deux couches, en 6 règles

1. **La data porte le sens, le render porte la forme** (amendement n°1). Tout champ numérique du dictionnaire est un nombre brut (`int` ou `float`), jamais une chaîne formatée. Le render applique la typographie française (`_nb`, virgule décimale) à l'affichage, au même titre que les guillemets. **Un même nombre n'existe jamais à deux endroits du dictionnaire sous deux représentations.**
2. **Exception unique et volontaire** : les phrases d'interprétation assemblées (`phrase` du badge, `sante.texte`, `lecture` d'un moteur, `diagnostic`, `contexte`, `impact`, `brief`, `recette`) restent en couche data avec leurs valeurs intégrées, parce qu'elles portent une décision de sens, pas seulement un chiffre. Pour composer ces phrases, la couche data importe `nb` depuis le module neutre `format.py` (§1) — **jamais depuis le render**. Aucun import direct entre data et render, dans aucun sens : le render est remplaçable sans toucher à la data.
3. **Toute condition d'affichage est résolue en booléen ou en variante nommée** dans la couche data (`affiche`, `variante: "stable"`). La couche render ne fait que tester ces booléens et brancher sur ces variantes ; elle ne compare jamais deux valeurs métier.
4. **Les seuils sont appliqués côté data, les classes CSS choisies côté render.** La data dit `niveau: "high"` ; le render traduit `high -> mx--high`.
5. **L'échappement HTML (`_e`) reste dans la couche render**, au moment de l'insertion. Le dictionnaire contient du texte brut : c'est ce qui le rend lisible en JSON.
6. **La géométrie reste dans la couche render** : coordonnées SVG, `stroke-dasharray` de la jauge, largeurs de barres — y compris les largeurs **relatives** (barre d'une part de voix rapportée à celle du premier). La data fournit les nombres, le render fait la mise en page.

## 2 bis. Déterminisme de la couche data (amendement n°2)

**La couche data ne lit jamais l'horloge.** `donnees(conn, run_id, date_du_jour)` reçoit la date du jour en paramètre ; `_prochaine_collecte(date_du_jour)` en découle. Le point d'entrée CLI passe la date courante par défaut. Aucun autre champ ne dépend de l'instant d'exécution (vérifié : `datetime.now` n'apparaît qu'à cet endroit de la chaîne dashboard).

Conséquence : `donnees()` est une fonction pure de `(base, run_id, date_du_jour)`. Deux exports JSON du même run avec la même date d'entrée sont identiques octet par octet, n'importe quel jour. La vérification du §7 devient reproductible en injectant la date de la référence.

## 3. Le dictionnaire, champ par champ

> Types notés `str`, `int`, `float`, `bool`, `list`, `dict`, `|null`.
> « Provenance » = où la valeur est calculée AUJOURD'HUI dans `dashboard.py`.
> Rappel des règles transverses : nombres bruts partout, formats français côté render,
> phrases assemblées = seule exception.

### 3.1 `meta` — en-tête, rail, impression

| Champ | Type | Provenance actuelle |
|---|---|---|
| `produit_nom` | str | `load_produit()["nom"]` via `d["produit"]` |
| `produit_signature` | str | `load_produit()["signature"]` |
| `client` | str | `runs.client` (`collecte()`) |
| `client_label` | str | `cfg.label` (`collecte()`) |
| `client_initiale` | str | `rendu()` : `d['client_label'][:1].upper()` |
| `run_id` | int | paramètre de `collecte()` |
| `date` | str `AAAA-MM-JJ` | `runs.started_at[:10]` |
| `n_appels` | int | `resume["n"]` (pour « 255 appels » du sous-titre) |
| `prochaine_collecte` | str | `_prochaine_collecte(date_du_jour)` — phrase assemblée (exception §2.2), calculée depuis le **paramètre** `date_du_jour`, jamais depuis l'horloge |

### 3.2 `hero` — le bandeau

| Champ | Type | Provenance actuelle |
|---|---|---|
| `taux` | float | `resume["rate"] or 0` (`_vue_resultats` l.1131) — jauge (géométrie) ET `{taux:.0f}` (render) |
| `n_moteurs` | int | `len(d["moteurs"])` — « 5 moteurs » sous la jauge et « , 5 moteurs. » dans la phrase de mesure |
| `titre` | str | règle 45-55 (l.1341) : « Une réponse d'IA sur deux… » sinon assemblée avec le taux (exception §2.2) |
| `badge` | dict\|null | l.1154-1169. `{variante: "stable"\|"hausse"\|"baisse", delta: float}` — delta **signé**, brut (le CLI affiche « +5.2 pts », le render affiche la valeur absolue). Render : variante → `delta--flat/up/down`, libellé « ≈ stable » ou « ▲/▼ {nb(abs(delta))} pts ». `null` si aucune comparaison |
| `phrase` | str | l.1154-1169 — phrase d'état assemblée (exception §2.2), note de périmètre incluse |
| `appels_reussis` | int | `resume["ok"]` (« Mesuré sur 253 appels réussis ») |
| `sante` | dict | l.1174-1191. `{variante: "ok"\|"partielle"\|"muette", texte: str}` — phrase assemblée (exception §2.2). Render : variante → `health--ok` / (rien) / `health--bad` |
| `palier` | int | `_objectif(taux)` — arc secondaire de la jauge et « Palier 60 % » |
| `reste` | float | `_objectif(taux)` — « +7 pts restants » |
| `contenus` | int\|null | « 2 à 3 contenus » (render affiche `contenus` à `contenus+1`) ; null = absent |

Passe 1 corrigée : la règle graduée est REVENUE dans le hero (sans elle il était à
moitié vide). Seules les `stats` restent parties, dans `voix.stats` (une preuve).

### 3.3 `moteurs` — les cartes moteurs (liste, déjà triée par taux décroissant)

| Champ | Type | Provenance actuelle |
|---|---|---|
| `nom` | str | `NOMS_MOTEURS[id]` (l.1312) |
| `taux` | float | requête SQL par moteur (`collecte()` l.94-111) — barre ET `{taux:.0f} %` |
| `est_zero` | bool | `taux < 1` (classe `eng--zero`) |
| `rang` | float\|null | rang moyen brut (l.1303-1305) — render : `rang moyen <b>{_nb(rang)}</b>` ou « aucune citation » si null |
| `appels` | dict | `{ok: int, total: int, erreurs: int, en_erreur: bool}` depuis l'agrégat `sante` (l.1306-1309) — render assemble « 75 appels » ou « 43/45 appels, 2 échec(s) » |
| `lecture` | str | `_lecture_moteur()` (l.381-404) — phrase assemblée (exception §2.2) |
| `tag` | str\|null | `"allie"` \| `"objectif"` \| null (l.1295-1299) — render → « Ton allié » / « Objectif long terme » |

### 3.4 `a_faire` — la section unique « À faire » (fusion mission + articles)

| Champ | Type | Provenance actuelle |
|---|---|---|
| `items` | list | 0 à 3 entrées, classées par impact décroissant : la requête sous `SEUIL_TROU` qui rapporterait le plus (ex-mission), puis les opportunités < 60 % hors n°1 (ex-articles), triées par `_impact()` |
| `items[].numero` | int | 1, 2, 3 |
| `items[].question` | str | texte brut (guillemets côté render) |
| `items[].diagnostic` | str | `_diagnostic(q)` (exception §2.2) |
| `items[].contexte` | str\|null | **OPTIONNEL**, porté par l'entrée n°1 : « Le terrain est occupé par… » / « …terrain est libre. » (exception §2.2) |
| `items[].impact` | str | `_promesse(_impact(q, …))` (exception §2.2) |
| `items[].taux` | float | taux de la requête |
| `items[].taux_warn` | bool | `taux >= 10` |
| `items[].brief` | str\|null | **OPTIONNEL**, porté par l'entrée n°1 : payload du bouton « Copier le brief » (`_brief()`, exception §2.2) |
| `items[].recette` | str | `_prompt_ia(q, d)` (exception §2.2) |

Structure unifiée ; l'entrée n°1 porte deux boutons (brief + recette) et la phrase
de contexte, les n°2 et n°3 un seul bouton. Règle gravée après la correction de la
Passe 1 : **une fusion ne supprime pas de fonctionnalité** — en cas de collision
entre une structure et une fonctionnalité existante, on s'arrête et on demande.

### 3.6 `voix` — « Qui te prend des citations »

| Champ | Type | Provenance actuelle |
|---|---|---|
| `total_citations` | int | requête `sources` (`collecte()` l.170-175) |
| `domaines_distincts` | int | idem (l.176-180) |
| `stats` | dict | Passe 1, descendu du hero : `{place: int\|null, place_suffixe: "re"\|"e", domaines: int, part: float\|null, rang: float\|null}` — render formate et affiche « — » / « n/d » sur les null |
| `lead` | dict | l.1344-1349. `{variante: "domine"\|"neutre", poursuivant: str\|null, ecart: float\|null}` — nombres bruts ; le render assemble les deux variantes de phrase avec `<strong>` et `_nb` |
| `lignes` | list | 8 max, triées par citations (l.1355-1367) |
| `lignes[].rang` | int | index d'affichage |
| `lignes[].domaine` | str | `sources.domain` |
| `lignes[].sous_titre` | str\|null | label concurrent ou « la marque suivie » (l.1363) |
| `lignes[].part` | float | `n / total * 100` — seule représentation du nombre ; le render en tire `_nb(part) %` ET la largeur de barre relative au premier (géométrie, §2.6) |
| `lignes[].est_moi` | bool | `is_target` (classe `is-you`) |
| `lignes[].est_poursuivant` | bool | premier non-moi (classe `is-chaser`) |
| `lignes[].ecart` | float\|null | seulement sur le poursuivant quand la marque est 1re (l.1358-1361) — render : « à {_nb(ecart)} pts derrière la marque » |

### 3.7 `forteresses`

| Champ | Type | Provenance actuelle |
|---|---|---|
| `lead` | dict | l.1350-1354. `{variante: "exemples"\|"vide", texte_requete: str\|null, taux: float\|null}` — le render assemble la phrase |
| `items` | list | 5 max, requêtes ≥ 60 % (l.1134) : `[{texte: str, taux: float}]` |

### 3.8 `dominance`

| Champ | Type | Provenance actuelle |
|---|---|---|
| `part_n1` | float | `n1 / cites * 100` (l.1370-1371) — « source n°1 dans 38 % des cas » (render formate) |
| `part_texte` | float | `en_texte / ok * 100` — « nommée dans le texte … 17 % » (render formate) |
| `items` | list | `dominance_requetes[:5]` (`collecte()` l.216-231) : `[{texte: str, part: float}]` |
| `vide` | bool | aucune citation (affiche « Aucune citation sur cette collecte. ») |

### 3.9 `pages_resume` — SUPPRIMÉ (Passe 1)

C'était une version tronquée d'`alignement`, qui seul subsiste (niveau « preuve »
de la vue produit).

### 3.10 `duel`

| Champ | Type | Provenance actuelle |
|---|---|---|
| `affiche` | bool | `bool(d["duel"])` — un rival est configuré ET mesuré (l.1388) |
| `rival_label` | str | `cfg.competitor_label(rival)` (`collecte()`) |
| `menees` / `perdues` / `egales` | int | l.1389-1391 |
| `lignes` | list | 8 max, triées par écart décroissant : `[{question: str, moi: float, lui: float}]` — guillemets côté render |

### 3.11 `courbe`

| Champ | Type | Provenance actuelle |
|---|---|---|
| `variante` | str | `"attente"` (moins de 2 points, texte seul) \| `"tracee"` (SVG) (`_courbe` l.1456) |
| `marge` | float | `_marge(resume)` — bande SVG (géométrie) ET `±{_nb(marge)} pts` du hint (render) |
| `n_moteurs` | int | `serie_ctx["n_moteurs"]` sinon `len(moteurs)` — « périmètre constant : 4 moteurs communs » et étiquette « 56 % · 4 moteurs » |
| `points` | list | `serie_commune()` via `collecte()` : `[{date: str, taux: float}]` — coordonnées calculées par le render |

### 3.12 `matrice` — vue « Moteurs et sujets », tableau croisé

| Champ | Type | Provenance actuelle |
|---|---|---|
| `affiche` | bool | moteurs ET requêtes non vides (`_matrice` l.1017) |
| `lead` | dict | l.1041-1057. `{moteur_haut: {nom: str, rang: float}\|null, muettes: int}` — nombres bruts, les deux morceaux de phrase assemblés par le render exactement comme aujourd'hui |
| `colonnes` | list | moteurs triés par taux : `[{nom_court: str, taux: float}]` — render : `{taux:.0f} %` |
| `lignes` | list | requêtes triées par taux global décroissant |
| `lignes[].id` | str | `q01`… |
| `lignes[].texte` | str | texte de la requête |
| `lignes[].cellules` | list | une par colonne : `{niveau: "high"\|"mid"\|"low"\|"zero"\|"na", cites: int, ok: int}` — seuils 1/34/67 appliqués côté data (l.1029-1034) ; render : `{cites}/{ok}` ou `·` si `niveau == "na"` |

### 3.13 `alignement` — vue « Moteurs et sujets », intention → page

| Champ | Type | Provenance actuelle |
|---|---|---|
| `vide` | bool | aucune page citée (`_alignement` l.1082) |
| `lead` | dict\|null | `{page: str, n: int, total: int}` (l.1116-1119) |
| `pages` | list | 6 max (`collecte()` l.233-259) |
| `pages[].page` / `n` / `requetes` | str / int / int | chemin, citations, nombre de requêtes distinctes |
| `pages[].detail` | list | 5 max : `[{texte: str, n: int}]` |
| `pages[].reste` | int | requêtes au-delà des 5 affichées (0 = pas de ligne « + N autre(s) ») |
| `pages[].flag` | dict\|null | `{variante: "accueil"\|"absorbe", n: int}` — seuils : accueil ≥ 3 requêtes, page ≥ 8 requêtes (l.1097-1104) |

### 3.14 `jeu_requetes` — vue « Machine »

| Champ | Type | Provenance actuelle |
|---|---|---|
| `set_version` / `n_requetes` / `n_concurrents` | int | config |

Passe 1 : le tableau des requêtes (`lignes`) a fusionné dans la matrice, qui porte
la même information en plus riche. Ne restent que les compteurs, pour la carte du
formulaire de proposition (vue Machine). Le formulaire et le lien GitHub restent du
gabarit statique du render, inchangés (traités dans une passe suivante).

### 3.15 `collectes` — vue « Collectes »

| Champ | Type | Provenance actuelle |
|---|---|---|
| `n` | int | `len(historique)` |
| `lignes` | list | 25 max, plus récentes d'abord : `[{id: int, date: str "2026-08-03 à 09:21", n: int, erreurs: int, taux: float\|null, note: str}]` — les « — » (erreurs 0, taux null) restent des choix d'affichage du render |

## 4. Ce qui disparaît du dictionnaire actuel

Champs du `d` actuel qui n'apparaissent PAS dans le nouveau dictionnaire, parce qu'ils étaient des données intermédiaires que la couche render recalculait :
`resume`, `requetes` (brut), `voix` (brut), `occupants`, `dominance` (brut), `dominance_requetes`, `pages` (brut), `duel` (brut), `rival`, `sante` (brut), `matrice` (brut), `delta`, `delta_ctx`, `serie_ctx`, `serie` (brut), `historique` (brut), `produit`.
Toute cette matière est consommée par la couche data pour produire les champs des §3.1-3.15.

## 5. Export JSON (la seule addition, exigée par la mission)

```bash
python -m geotracker.dashboard --donnees chemin.json
```

Écrit le dictionnaire complet, `json.dumps(..., ensure_ascii=False, indent=2)`, et ne génère PAS le HTML dans ce mode. Aucune autre option ajoutée, aucune option existante modifiée. Garantie de sérialisation : le dictionnaire ne contient que `dict`, `list`, `str`, `int`, `float`, `bool`, `null` (pas de set, pas de dataclass, pas de datetime).

Déterminisme (amendement n°2) : `donnees()` étant une fonction pure de `(base, run_id, date_du_jour)`, **deux exports du même run avec la même date d'entrée sont identiques octet par octet**, quel que soit le jour où on les lance.

## 6. Points d'implémentation actés

1. **Nombres** : bruts dans le dictionnaire, format français côté render, aucune double forme ; les phrases assemblées sont la seule exception (amendement n°1, §2.1-2.2). `nb()` vit dans le module neutre `format.py`, importé par les deux couches, qui n'importe rien du projet.
2. **Guillemets français** (`_cite`) : typographie, donc couche render. Le dictionnaire contient les questions sans « ». (Validé tel quel.)
3. **Échappement HTML** : couche render, au moment de l'insertion.
4. **Horloge** : jamais lue par la couche data ; `date_du_jour` est un paramètre (amendement n°2, §2 bis).
5. **Noms de fichiers** : `dashboard_donnees.py` / `dashboard_rendu.py`, `dashboard.py` point d'entrée. (Validés tels quels.)
6. **Une fonction render par bloc** (état après Passe 1 corrigée) : `_hero`, `_moteurs`, `_a_faire`, `_voix`, `_forteresses`, `_dominance`, `_duel`, `_courbe`, `_matrice`, `_alignement`, `_vue_requetes`, `_vue_collectes`, plus les composeurs `_vue_ensemble`, `_vue_moteurs_sujets`, `_vue_citations` et la coquille `rendu()` (rail à 5 boutons, libellés visibles). Chacune reçoit sa portion du dictionnaire et rien d'autre ; chacune est appelable avec un dictionnaire écrit à la main, sans base présente.

## 7. Méthode de vérification

1. Régénérer en injectant la date de la référence (générée le 05/08/2026) :
   `rendu(donnees(conn, run_id, date_du_jour=date(2026, 8, 5)))` — la comparaison est ainsi **reproductible n'importe quel jour** (amendement n°2).
2. Comparer octet par octet : `cmp <sortie> reports/reference-avant-refactor.html`
3. `cmp` silencieux (code 0) = identique. La moindre différence est corrigée avant de rendre la main.
4. Les 6 tests de fumée passent (dont `node --check` sur le JS).

## Observations (améliorations NON appliquées, notées comme exigé)

- `_vue_resultats` recalcule `_impact()` de la cible plusieurs fois (mission, tri des candidats) ; la séparation des couches le fera naturellement une fois, sans changer le résultat.
- La marge affichée par la carte courbe est celle de la collecte entière (`_marge(resume)`) alors que la courbe est à périmètre commun ; cohérent avec l'existant, conservé tel quel, mais un jour la bande pourrait se calculer sur l'échantillon du périmètre constant.
- `historique` est plafonné à 25 lignes par la requête SQL mais la vue s'intitule « N enregistrées » avec N = lignes affichées : à 26 collectes, le titre dira 25. Rien à faire aujourd'hui, à savoir.
