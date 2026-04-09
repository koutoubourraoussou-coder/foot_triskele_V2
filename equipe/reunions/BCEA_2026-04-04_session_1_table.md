# TABLE DE RÉUNION — Session 1 — 2026-04-04
*Document partagé — tous les agents lisent tout avant de parler*

---

## CONTEXTE DE SÉANCE

**Sujet :** Hypothèse — global_bet_min_winrate=0.50 améliore le profil champion (baseline=0.65)

**Données disponibles :**
- Finetune 20 runs (2026-04-02) : 0.50 → score=30.611 vs 0.65 → score=29.153. Delta = +1.459
- Classement à 20 runs : 0.50 > 0.60 > 0.65 > 0.55 > 0.70
- Test 100 runs EN COURS (compare_variants.py en fond)
- Historique : global_bet_min_winrate est passé de 0.62 → 0.65 lors de la construction du profil champion (plus strict = meilleur à l'époque)

**Ce que fait ce paramètre :** seuil minimum de win rate global pour qu'une famille de paris soit acceptée. À 0.50, on débloque O25_FT (WR réel=0.514) et TEAM_WIN_FT (WR réel=0.612) — les deux familles les moins performantes historiquement.

---

## 🗣️ RÉDUCTEUR DE BRUIT

*Priorisation — a ouvert la séance*

"On a 50 questions sur la table. Une seule mérite clairement notre temps cette semaine : global_bet_min_winrate=0.50. C'est explicitement laissé en suspens dans le LABORATOIRE, le signal existe à 20 runs, et le test est rapide. topk_uniform_draw et system_build_source sont déjà fermés — inutile d'y revenir. On commence par ici."

---

## 🗣️ SCEPTIQUE

*Premier à analyser l'hypothèse*

**Points de vigilance :**

1. **20 runs = sous mon seuil.** La variance sur ce système est énorme (NORM va de ×0 à ×3695 sur 200 runs). Un delta de +1.459 sur 20 runs est statistiquement indistinguable du bruit.

2. **La logique va à l'encontre de l'historique.** Passer à 0.50 débloque O25_FT (WR=0.514) et TEAM_WIN_FT (WR=0.612) — précisément les deux familles les moins performantes. Le projet a déjà bougé dans le sens inverse (0.62 → 0.65) avec la justification "filtre plus exigeant = qualité supérieure". Aller à 0.50, c'est reculer sur ce principe.

3. **Volume ≠ qualité.** À 0.50, le WR SYSTEM baisse déjà dans les 20 runs (0.675 vs 0.686 à 0.65). Le score composite monte uniquement via des NORM très volatils — pas via une amélioration structurelle.

4. **SAFE régresse à 20 runs.** SAFE ×mult passe de ×30.10 à ×29.21 à 0.50. C'est -3% sur la métrique de survie martingale — la plus importante pour le déploiement réel.

5. **Overfitting possible.** 61 jours peuvent contenir une période offensive spécifique qui gonfle O25_FT et TEAM_WIN_FT localement.

**Contre-hypothèse :** Le signal est un artefact stochastique. 2-3 runs RANDOM avec des paris O25_FT chanceux ont gonflé la moyenne. Sur 100 runs, la variance se rétablit et l'avantage s'efface ou s'inverse.

**Tests adversariaux :**
- Si SAFE ×mult (0.50) < SAFE ×mult (0.65) sur 100 runs → hypothèse rejetée même si score composite légèrement positif
- Si WR(0.50) < WR(0.65) → le filtre permissif admet des paris plus faibles, pas plus forts
- Si pire_série(0.50) > pire_série(0.65) → les familles débloquées introduisent de l'instabilité

**Métriques à surveiller (dans l'ordre) :**
1. SAFE ×mult — métrique de déploiement réel
2. WR global — qualité des tickets
3. Pire série — risque martingale
4. NORM ruine — déjà à 25% à 20 runs (contre 15% à 0.65)

**Verdict provisoire : SIGNAL FRAGILE**
Conditions pour upgrade : delta > +1.0 sur 100 runs ET SAFE(0.50) ≥ SAFE(0.65)
Conditions pour downgrade : SAFE(0.50) < SAFE(0.65) OU delta < +0.3

---

## INNOVATEUR

*En réponse directe au Sceptique — après vérification dans le code et les données*

---

### 1. La logique "0.62→0.65 = plus strict = mieux" — vraie mais incomplète

Le Sceptique cite l'historique comme preuve directionnelle. Je veux interroger la solidité de cet argument.

Le passage `0.62→0.65` ne s'est jamais produit en test isolé. C'était l'une des **quatre améliorations simultanées** (LABORATOIRE.md, Phase 3) : `two_team_high`, `global_bet_min_winrate`, `league_bet_require_data`, `league_bet_min_winrate`. L'attribution causale n'est pas prouvée. Le gain peut venir entièrement de `two_team_high 0.80→0.90` — jamais testé séparément.

Plus révélateur : le classement à 20 runs est `0.50 > 0.60 > 0.65 > 0.55 > 0.70`. Ce n'est pas une relation monotone "plus strict = mieux". **0.55 perd contre 0.65** mais **0.60 gagne contre 0.65**. C'est une courbe avec un optimum local, pas une tendance linéaire. L'argument "direction historique" ne peut pas s'appliquer à une courbe non-linéaire.

**Concession :** l'historique est une mise en garde légitime. Mais il ne constitue pas une preuve — seulement un prior.

---

### 2. O25_FT et TEAM_WIN_FT sont-ils réellement utilisés dans les tickets à 0.50 ? — Non, pas comme le Sceptique le suppose

J'ai vérifié dans le code (`ticket_builder.py`). La réponse est plus nuancée que ce qui est présenté dans le contexte de séance.

**Pour le mode RANDOM :** `_random_accept_pick()` (ligne 2481) utilise `league_bet_min_winrate` (0.60) et `team_min_winrate` pour filtrer, **pas `global_bet_min_winrate`**. La porte RANDOM ne change pas à 0.50. Modifier `global_bet_min_winrate` de 0.65 à 0.50 ne débloque rien dans le pool RANDOM.

**Pour le mode SYSTEM :** oui, `_global_bet_is_eligible()` (ligne 1109) utilise bien `global_bet_min_winrate`. Mais le nombre de tickets SYSTEM reste identique (86) dans les deux variantes à 20 runs. L'effet sur le volume est marginal — probablement parce qu'`O25_FT` est filtré en amont par d'autres critères (`league_bet_min_winrate`, `team_min_winrate`).

**Pour TEAM_WIN_FT :** ce terme n'existe pas dans `ticket_builder.py`. La normalisation via `_norm_bet_family()` mappe vers `TEAM1_WIN_FT` / `TEAM2_WIN_FT`, dont `min_level: null` dans `min_level_by_bet.json` — elles sont absentes du pool candidat pour des raisons antérieures à `global_bet_min_winrate`.

**Ce que cela implique pour la contre-hypothèse du Sceptique :** si O25_FT et TEAM_WIN_FT ne sont pas réellement dans les tickets à 0.50 (ou très marginalement), alors le signal RANDOM positif à 20 runs n'est PAS expliqué par ces familles débloquées. L'explication stochastique reste possible, mais l'explication causale du Sceptique ("mauvaises familles entrées") est affaiblie.

---

### 3. L'artefact stochastique — explication possible, pas exclusive

Le Sceptique a raison de poser cette hypothèse. Mais il y en a au moins deux autres.

**Hypothèse A — Effet de composition sur le Top-K SYSTEM :**
À 0.65, `O25_FT` est absent du pool SYSTEM. Cela force la sélection à comparer d'autres familles entre elles. À 0.50, `O25_FT` entre dans la compétition (308 paris décidés sur 61 jours) et modifie les scores comparatifs dans le Top-K. Même s'il est rarement sélectionné au final, sa présence peut faire émerger des tickets différents. Le tirage uniforme parmi 10 candidats rend ce mécanisme non-trivial.

**Hypothèse B — Signal dans le SAFE RANDOM :**
Dans les 20 runs, SAFE RANDOM monte aussi (`x46.98` vs `x42.44` à 0.65 — +10.7%). Si l'effet était purement stochastique sur quelques NORM extrêmes, le SAFE — construit pour être robuste aux queues de distribution — ne bougerait pas. Le fait qu'il monte aussi, même si RANDOM n'est pas directement affecté par le paramètre, suggère un effet indirect réel (peut-être via l'interaction des séquences journalières entre SYSTEM et RANDOM).

---

### 4. Angle non exploré par le Sceptique — la structure par niveau d'O25_FT

Le Sceptique cite le WR global d'O25_FT à 0.514 comme preuve de sa faiblesse. Mais les données de `min_level_by_bet.json` montrent une hétérogénéité forte :

| Niveau | WR O25_FT |
|--------|-----------|
| KO | 40.4% |
| FAIBLE | 38.5% |
| MOYEN | 47.2% |
| MOYEN PLUS | 48.8% |
| FORT | 53.1% |
| FORT PLUS | **72.7%** |
| TRÈS FORT | 53.3% |
| MEGA EXPLOSION | **66.7%** |

Le WR global de 51.4% est une moyenne sur tous niveaux confondus. Les niveaux FORT PLUS et MEGA EXPLOSION d'O25_FT sont au-dessus de 0.65. Si le système ne sélectionne que les O25_FT aux niveaux élevés (ce qui est probable via les filtres amont de `match_analysis.py` et les seuils `min_level_by_bet`), la famille n'est pas du tout "la moins performante" — elle est performante dans ses meilleurs cas. La question pertinente n'est pas "O25_FT WR global = 0.514, donc mauvaise" mais "les O25_FT que le système retient ont-ils un WR suffisant".

---

### 5. Ce que je veux voir dans les 100 runs

**Pour que ma lecture soit validée :**
- SAFE RANDOM(0.50) ≥ SAFE RANDOM(0.65) — signal indirect réel, puisque RANDOM n'est pas directement affecté par le paramètre
- Score composite delta > +0.8 (signal qui persiste au-delà du bruit)
- Nombre de tickets inchangé (86 SYSTEM, 71 RANDOM) — confirme que le mécanisme est subtil, pas un effet de volume brut

**Pour que la position du Sceptique soit validée :**
- SAFE RANDOM baisse également — artefact stochastique confirmé
- WR SYSTEM descend sous 0.675 — familles débloquées dégradent la qualité
- Classement s'inverse (0.65 > 0.50) — 20 runs étaient du bruit, point final

**Ma position nette :**
Le Sceptique a produit une analyse solide sur les points 1 (volume des runs), 3 (WR SYSTEM baisse) et 4 (SAFE SYSTEM régresse). Ses points les plus forts. Mais il a sur-estimé l'effet des familles "débloquées" dans les tickets — le code ne supporte pas cette lecture. Et son argument d'historique est un prior, pas une preuve. L'hypothèse mérite les 100 runs. Elle n'est ni à adopter ni à rejeter maintenant.

---

*(Table ouverte — agents suivants : lire tout ce qui précède avant de parler)*

---

## 🗣️ INNOVATEUR — Réponse finale

*En réponse à la question la plus difficile du Sceptique — avant le verdict des 100 runs*

---

### 1. Taux de faux positifs — calcul honnête

Le Sceptique pose la bonne question. Je vais la traiter sérieusement, sans l'esquiver.

**Le problème formel.** On teste 5 valeurs. On prend la meilleure sur 20 runs. Si les 5 valeurs sont en réalité équivalentes (aucune supériorité réelle), la probabilité que la "meilleure" par hasard soit sélectionnée est 1/5 = 20% de chance que ce soit n'importe laquelle. La probabilité qu'un *imposteur* soit classé premier est donc 80% — le Sceptique a raison sur ce point de départ.

**Mais le problème n'est pas aussi simple.** Ce n'est pas un tirage uniforme. Il faut modéliser la distribution des scores.

Posons les hypothèses : notre score composite sur 20 runs a une variance élevée (NORM va de ×0 à ×3695). Si l'écart-type du score composite est σ et que les valeurs sont réellement équivalentes, alors l'espérance du maximum parmi 5 variables normales indépendantes est approximativement μ + σ × E[max(Z₁,...,Z₅)] ≈ μ + 1.16σ. Autrement dit : par construction, la meilleure valeur sur 5 sera systématiquement supérieure d'environ 1.16 déviations standards à la moyenne — même si rien n'est vrai.

**Le delta observé est +1.459.** Si l'écart-type du score composite sur 20 runs est de l'ordre de 1.0 à 1.5 (estimation raisonnée : le score moyen tourne autour de 29-30 et les queues sont larges), alors un delta de +1.459 est entièrement cohérent avec la sélection du maximum parmi 5 imposteurs. Le Sceptique a raison sur le fond.

**Estimation honnête du taux de faux positifs :** sans correction pour comparaisons multiples, et avec 20 runs sur une distribution à forte variance, je l'estime entre 50% et 70%. Ce n'est pas négligeable. C'est même le principal problème structurel de notre procédure de finetune actuelle.

**Je concède ce point au Sceptique.** La confiance qu'on peut accorder à "0.50 est meilleur" sans correction est insuffisamment calibrée. C'est un problème réel, pas un détail.

---

### 2. Effet indirect RANDOM — mécanisme précis ou concession ?

Le Sceptique attaque ma formulation "effet indirect réel via l'interaction des séquences journalières". Il a raison de la rejeter. Je l'avais posée comme intuition, pas comme mécanisme.

**La question précise :** si les tickets RANDOM sont structurellement identiques (même pool, même N=71), comment +10.7% sur SAFE RANDOM à 20 runs pourrait-il être réel ?

**Je cherche un mécanisme.** Un seul m'apparaît défendable : les runs de `compare_variants.py` génèrent SYSTEM et RANDOM dans le même appel journalier. Si la graine RANDOM n'est pas fixée de manière identique entre variantes, les séquences RANDOM ne sont pas les mêmes 20 tirages d'une même distribution — elles sont des tirages différents, potentiellement corrélés à la date ou à l'heure d'exécution. Mais je n'ai pas vérifié le code de `compare_variants.py` pour confirmer ce point.

**Sans ce mécanisme confirmé dans le code :** la position du Sceptique est correcte. Deux séries de 20 tirages d'une même distribution peuvent produire un écart de 10.7% sur SAFE, c'est précisément la définition de la variance. Je ne dispose pas d'un mécanisme défendable qui distinguerait ce signal du bruit pur.

**Concession franche :** l'argument "SAFE RANDOM monte donc signal indirect réel" était une inférence de trop. Je la retire. Sur 20 runs avec tickets identiques, cet écart ne constitue pas une preuve.

---

### 3. Amélioration structurelle de la procédure de finetune

Le problème des comparaisons multiples est réel dans notre procédure. Voici trois corrections possibles, par ordre de faisabilité :

**Option A — Correction de Bonferroni (simple, immédiate).**
Si on teste k=5 valeurs et qu'on veut un seuil de confiance global de α=0.05, on exige que chaque test individuel soit significatif à α/k = 0.01. En pratique : ne retenir la valeur gagnante que si son delta dépasse le seuil attendu pour le maximum de 5 tirages. Avec notre variance, cela exigerait probablement un delta > +2.5 à 20 runs pour être pris au sérieux. La valeur actuelle de +1.459 ne passerait pas ce filtre. Bonferroni est conservative mais simple à appliquer.

**Option B — Tests séquentiels (plus robuste, plus coûteux).**
Ne pas tester 5 valeurs simultanément. Tester d'abord 2 valeurs (meilleur candidat contre baseline), puis si le signal est là, confirmer sur 50 runs supplémentaires avant d'ouvrir aux autres valeurs. Cette approche "tournament-style" contrôle naturellement le taux de faux positifs à chaque étape. Elle double le nombre de runs nécessaires mais divise par 3 à 4 le taux de faux positifs.

**Option C — Méta-critère de validation croisée temporelle (innovant, plus difficile).**
Diviser les 61 jours en deux sous-périodes (j1-j30 et j31-j61). Finetune sur la première, validation sur la seconde. Un paramètre qui gagne uniquement sur la période d'entraînement mais pas sur la période de validation est un signe d'overfitting. Ce n'est pas de la validation croisée classique — c'est de la walk-forward validation, plus adaptée à nos données temporelles que le bootstrap standard.

**Ma recommandation pour les sessions futures :** Option B (séquentielle) pour les tests de paramètres importants comme celui-ci. Option A (Bonferroni) comme filtre rapide avant d'investir des runs supplémentaires. Option C comme vérification finale avant adoption dans le profil champion.

---

### 4. Position finale — en une phrase

Les 100 runs sont le seul arbitre légitime ici : si SAFE SYSTEM(0.50) ≥ SAFE SYSTEM(0.65) avec un delta > +1.0, le signal survit malgré le bruit des comparaisons multiples — sinon, le Sceptique avait raison dès le départ et la procédure de finetune doit être restructurée avant le prochain test.

---

*(Réponse finale de l'Innovateur — verdict aux 100 runs)*

---

## SCEPTIQUE — 2e tour

*En réponse directe à l'Innovateur — après lecture complète de son analyse*

---

### Concessions franches

**Point 1 — RANDOM : j'avais tort sur le mécanisme.**

L'Innovateur a vérifié dans le code. `_random_accept_pick()` utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. Mon argument "O25_FT et TEAM_WIN_FT débloqués dans les tickets RANDOM" reposait sur une lecture incorrecte du mécanisme. Je le retire. Ce n'est pas un détail — c'était l'un de mes arguments causaux centraux pour expliquer pourquoi 0.50 devrait dégrader les tickets RANDOM. Si la porte RANDOM ne change pas, mon explication stochastique ("quelques paris O25_FT chanceux dans RANDOM") n'est pas non plus valide comme elle était posée.

**Point 2 — Hétérogénéité d'O25_FT : j'ai utilisé une moyenne trompeuse.**

Citer WR global = 0.514 comme preuve de faiblesse était une erreur analytique. Les données montrent FORT PLUS à 72.7% et MEGA EXPLOSION à 66.7%, tous deux au-dessus du seuil 0.65. Si les filtres amont (`match_analysis.py`, `min_level_by_bet`) sélectionnent uniquement les niveaux élevés, alors la famille que le système retient réellement n'est pas "la moins performante" — elle est compétitive. Mon argument "WR=0.514 donc risque" était une généralisation non filtrée.

---

### Ce qui tient encore

**Sur SYSTEM, le paramètre agit — et SAFE SYSTEM régresse.**

L'Innovateur confirme que `_global_bet_is_eligible()` utilise bien `global_bet_min_winrate` pour le mode SYSTEM. Ce n'est pas contesté. Et voici ce qui n'a pas bougé : à 20 runs, SAFE SYSTEM ×mult passe de ×30.10 (0.65) à ×29.21 (0.50). C'est -3%. La métrique de survie martingale sur le canal directement affecté par le paramètre régresse. L'Innovateur ne conteste pas ce chiffre. Il l'ignore en se concentrant sur SAFE RANDOM.

**Ce déplacement d'attention mérite d'être nommé.**

L'Innovateur construit son argument principal sur SAFE RANDOM (+10.7%) alors que ce canal n'est pas directement affecté par le paramètre. C'est un déplacement du critère de validation. La métrique naturelle pour juger l'effet de `global_bet_min_winrate` sur SAFE est SAFE SYSTEM — pas SAFE RANDOM. Et SAFE SYSTEM régresse.

---

### Attaque principale : l'"effet indirect réel" sur SAFE RANDOM

L'Innovateur pose l'hypothèse suivante : puisque RANDOM n'est pas directement affecté par le paramètre mais que SAFE RANDOM monte quand même de +10.7%, il y a un "effet indirect réel", peut-être via "l'interaction des séquences journalières entre SYSTEM et RANDOM".

Je conteste cette interprétation. Voici pourquoi.

**SAFE RANDOM est calculé sur des séquences de runs RANDOM.** Si `global_bet_min_winrate` ne modifie pas le pool RANDOM, et si le nombre de tickets RANDOM reste identique (71 dans les deux variantes selon l'Innovateur lui-même), alors les tickets RANDOM à 0.50 et à 0.65 sont **structurellement identiques**. Deux échantillons de 20 runs tirés d'une distribution identique peuvent tout à fait produire des SAFE différents de +10.7% — c'est précisément ce que fait la variance.

L'Innovateur dit : "Si l'effet était purement stochastique, SAFE — construit pour être robuste aux queues — ne bougerait pas." C'est une affirmation non démontrée. SAFE ×mult sur 20 runs reste exposé à la variance de séquence. La robustesse de SAFE s'affirme sur des N grands, pas sur 20 runs. Sur 20 tirages d'une même distribution, l'écart de SAFE entre deux sous-échantillons peut dépasser 10% sans signal réel.

**Si les tickets sont identiques et que SAFE diverge quand même de 10.7% : c'est précisément la définition du bruit de variance.**

"Effet indirect réel" nécessite un mécanisme explicite. L'Innovateur n'en propose pas — il évoque une "interaction des séquences journalières" sans préciser le canal. Ce n'est pas une hypothèse testable, c'est une formulation de confort pour préserver le signal.

---

### La question la plus difficile — que personne n'a encore posée

**Quel est le taux de faux positifs de notre procédure de finetune sur 20 runs ?**

Voici le problème structurel : nous avons testé plusieurs valeurs (0.50, 0.55, 0.60, 0.65, 0.70). Le classement résultant est `0.50 > 0.60 > 0.65 > 0.55 > 0.70`. Sur 5 valeurs testées simultanément, quelle est la probabilité que la valeur gagnante à 20 runs soit simplement celle qui a eu les meilleurs tirages aléatoires — indépendamment de toute supériorité réelle ?

Avec 5 candidats, si on tire au sort, la probabilité que le "vrai" gagnant soit en tête est 20%. La probabilité qu'un imposteur soit en tête est 80%. Nous n'avons jamais calculé ce taux de faux positifs pour notre procédure de sélection à N runs. Sans ce calcul, la confiance que nous accordons à "0.50 est meilleur" n'est pas calibrée.

Cette question vaut pour toutes les hypothèses que nous avons testées — pas seulement celle-ci. Et elle n'a pas de réponse dans les données actuelles.

---

### Verdict maintenu — avec précision accrue

**SIGNAL FRAGILE**, toujours.

Mais les raisons ont changé. Je ne m'appuie plus sur "familles débloquées dans RANDOM" ni sur "WR global d'O25_FT = 0.514". Ces arguments étaient insuffisants.

Je m'appuie sur :
1. SAFE SYSTEM régresse à -3% sur le canal directement affecté par le paramètre
2. SAFE RANDOM +10.7% sur 20 runs avec tickets structurellement identiques = bruit de variance non réfuté
3. L'absence de mécanisme explicite pour "l'effet indirect réel"
4. Le problème de tests multiples sur 5 valeurs à 20 runs : taux de faux positifs non calculé

**Conditions d'upgrade inchangées :**
- Delta > +1.0 sur 100 runs ET SAFE SYSTEM(0.50) ≥ SAFE SYSTEM(0.65)
- Si SAFE RANDOM monte mais SAFE SYSTEM reste sous 0.65 : l'hypothèse "effet indirect" reste non démontrée

---

*(Table ouverte — agents suivants : lire tout ce qui précède avant de parler)*

---

## ⚖️ VALIDATEUR FROID — Verdict final

*Session 1 — 2026-04-04 — Lu : table complète, ADN, mémoire*

---

```
VALIDATEUR FROID — global_bet_min_winrate : 0.50 vs 0.65

PROTOCOLE VÉRIFIÉ : OUI
  → Métrique principale définie en amont par le Sceptique : SAFE ×mult SYSTEM
  → 100 runs effectués
  → Baseline et variante comparées sur les mêmes conditions

N_RUNS : 100

MÉTRIQUE PRINCIPALE : SAFE ×mult SYSTEM (métrique de survie martingale — priorité absolue selon ADN)

RÉSULTATS :

  Mode SYSTEM — canal directement affecté par le paramètre
  ─────────────────────────────────────────────────────────
  SAFE ×mult    : Baseline 0.65 → 29.25   /   Variante 0.50 → 28.02   →  Baseline +4.4%
  Win rate      : Baseline 0.65 → 68.2%   /   Variante 0.50 → 67.3%   →  Baseline +0.9 pts
  NORM ruine    : Baseline 0.65 → 10%     /   Variante 0.50 → 15%     →  Baseline meilleur
  Pire série    : Baseline 0.65 → 6       /   Variante 0.50 → 10      →  Baseline meilleur
  Score compos. : Baseline 0.65 → 14.829  /   Variante 0.50 → 14.212  →  Baseline gagne

  Mode RANDOM — canal NON affecté par le paramètre (variance pure)
  ─────────────────────────────────────────────────────────────────
  Écarts observés = non interprétables causalement.
  Découverte confirmée par l'Innovateur : global_bet_min_winrate n'affecte pas RANDOM.
  Toute différence RANDOM est du bruit de variance.

VERDICT : REJETÉ

RAISON :
  → Critère ADN appliqué : "Amélioration sur une métrique mais dégradation sur une autre
    plus importante → REJETÉ"
  → La variante 0.50 dégrade SAFE ×mult SYSTEM de -4.4% sur 100 runs.
    C'est la métrique de priorité absolue, sur le canal directement affecté par le paramètre.
  → Win rate SYSTEM : -0.9 pts — dégradation cohérente avec l'introduction de familles
    à WR plus faible dans la sélection SYSTEM.
  → NORM ruine : +50% (10% → 15%) — risque de ruine martingale aggravé.
  → Pire série : 6 → 10 — instabilité accrue, problème concret pour le suivi réel.
  → Score composite SYSTEM : -4.2% — défaite nette sur l'ensemble des métriques SYSTEM.
  → La contre-hypothèse du Sceptique est validée : le signal à 20 runs était du bruit.
    Les conditions d'upgrade qu'il avait posées (SAFE SYSTEM ≥ baseline) ne sont pas remplies.

PROCHAINE ÉTAPE :
  → Archiver : global_bet_min_winrate = 0.50 → REJETÉ le 2026-04-04.
  → Conserver la valeur baseline 0.65 dans le profil champion.
  → Ne pas retester ce paramètre avant au moins 6 mois ou changement majeur de dataset.
  → Documenter dans LABORATOIRE.md : "0.50 testé sur 100 runs, rejeté, baseline 0.65 confirmée."
```

---

### Note structurelle 1 — Faux positifs dans la procédure de finetune

L'Innovateur a produit une analyse honnête et correcte : le taux de faux positifs de notre procédure de finetune à 20 runs est estimé entre 50% et 70%.

Ce n'est pas une nuance — c'est un défaut de conception de notre méthode de sélection.

Le problème est précis : tester k=5 valeurs simultanément sur 20 runs à forte variance, puis retenir la meilleure, génère mécaniquement un biais de sélection. L'espérance du maximum parmi 5 variables est μ + 1.16σ — même si aucune valeur n'est réellement supérieure. Avec notre variance de score composite, un delta de +1.459 observé à 20 runs est entièrement compatible avec la sélection du maximum parmi 5 imposteurs. Le test à 100 runs vient de le confirmer empiriquement.

**Ce cas est désormais un exemple de référence pour calibrer notre confiance dans les sorties finetune futures.**

---

### Note structurelle 2 — global_bet_min_winrate n'affecte pas RANDOM

L'Innovateur a vérifié dans le code et établi un fait structurel : `_random_accept_pick()` utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. Ce paramètre est sans effet sur le pool RANDOM.

Conséquence immédiate pour les tests futurs : tout écart observé sur les métriques RANDOM lors d'un test de `global_bet_min_winrate` est de la variance pure et doit être ignoré comme signal causal.

Cette connaissance doit être documentée dans le profil technique du paramètre pour éviter de répéter l'erreur d'interprétation observée en séance.

---

### Recommandation sur la procédure de finetune — Sessions futures

Les trois options présentées par l'Innovateur sont toutes valides. Ma recommandation applique les critères du Validateur Froid, pas des préférences de confort.

**Niveau minimum requis dès maintenant (non négociable) :**
Tout paramètre sorti d'un finetune à N ≤ 30 runs est classé SIGNAL CANDIDAT, pas signal validé. Il ne peut pas modifier le profil champion sans test complémentaire à ≥ 100 runs.

**Filtre Bonferroni comme garde-fou immédiat :**
Si k valeurs sont testées, exiger un delta > 1.16σ × √(2 × ln(k)) pour considérer le gagnant comme non-imposteur. Avec k=5 et notre variance, cela correspond approximativement à un delta > +2.5 sur 20 runs. Le delta de +1.459 de cette session n'aurait pas franchi ce seuil — le signal aurait été écarté avant les 100 runs, économisant des ressources.

**Pour les paramètres à fort impact (comme global_bet_min_winrate) :**
Adopter le protocole séquentiel de l'Innovateur (Option B) : tester d'abord le meilleur candidat contre baseline en duel direct sur 50 runs, puis confirmer sur 50 runs supplémentaires si le signal tient.

**Ce que je ne recommande pas :**
Ne pas aller directement à l'Option C (walk-forward validation) avant d'avoir appliqué A et B de manière systématique. La complexité n'est justifiée que si les faux positifs persistent après les corrections simples.

---

*Verdict inscrit. Table de Session 1 close.*
*Prochaine session : documenter dans LABORATOIRE.md, mettre à jour la mémoire du Validateur Froid.*
