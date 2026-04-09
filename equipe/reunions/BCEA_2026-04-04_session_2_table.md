# TABLE DE RÉUNION — Session 2 — 2026-04-04
*Document partagé — tous les agents lisent tout avant de parler*

---

## CONTEXTE DE SÉANCE

**Date :** 2026-04-04
**Sujet :** Observation Fondateur — Ligues prolifiques et combinaisons build_source/select_source pour RANDOM

**Agents impliqués :** Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid

---

## OBSERVATION FONDATEUR (soumise comme faits bruts)

> "Certaines ligues sont structurellement prolifiques en buts (ex. Bundesliga 1&2 : 10/11 matchs à +1.5 goals aujourd'hui). Le Fondateur a observé que LEAGUE-first pour la construction semblait très efficace sur ses tests personnels (environ 1 semaine). Il est surpris que TEAM/TEAM soit le profil champion actuel. Les combinaisons build_source/select_source pour RANDOM n'ont peut-être pas été testées correctement en isolation. Question ouverte : le système exploite-t-il vraiment la structure des ligues prolifiques ?"

**Règle de soumission :** Cette observation est soumise comme faits bruts. Les agents raisonnent librement.

---

## BACKLOG COMPLET EN ENTRÉE

1. **Analyse contrefactuelle quotidienne** [Fondateur, 2026-04-04] — PRIORITÉ HAUTE — outil de diagnostic : pour chaque ticket joué, calculer dans quel percentile il se situait parmi tous les tickets possibles ce jour-là. Détecter les jours catastrophiques. Intégrer dans app Streamlit. Requiert script + nouveau panneau audit.
2. **RANDOM O15 avec filtre winrate léger** — requiert code
3. **Poids composite 70/30** — requiert code
4. **Maestro log enrichi** [Utilisateur, 2026-04-04] — afficher les raisons de rejet détaillées — infrastructure existe (`_system_reject_reason()`) mais données jamais loggées. Requiert code.
5. **Nouveaux types de paris** — requiert exploration
6. **Recency weighting rankings** — requiert code
7. **Correction procédure finetune (Bonferroni)** [Session 1] — appliquer filtre delta > +2.5 requis à 20 runs pour k=5. ACQUIS DE SESSION 1 — à appliquer dès maintenant systématiquement.
8. **[NEW] Ligues prolifiques / combinaisons build_source + select_source pour RANDOM** [Observation Fondateur, 2026-04-04]

**Acquis de Session 1 :**
- Filtre Bonferroni : delta > +2.5 requis à 20 runs pour k=5 avant de promouvoir en test 100 runs
- Tout résultat finetune N ≤ 30 runs = SIGNAL CANDIDAT uniquement
- global_bet_min_winrate n'affecte pas RANDOM

---

## RÉDUCTEUR DE BRUIT — Priorisation

**Posture :** choisir 2-3 items max, maximiser impact × facilité × urgence (déploiement réel en cours depuis le 2026-04-03).

### Évaluation du backlog

**Item 8 — Ligues prolifiques / combinaisons build_source + select_source RANDOM [NEW]**
- Impact estimé : POTENTIELLEMENT ÉLEVÉ. L'observation Fondateur porte sur le cœur du système de sélection RANDOM. Le profil champion TEAM/TEAM a été choisi par l'optimizer, mais les combinaisons LEAGUE/LEAGUE, LEAGUE/TEAM, HYBRID/TEAM n'ont pas été isolées proprement pour RANDOM. Le Profil #2 (LEAGUE build, TEAM select) a un WR RANDOM de 89.1% contre 72% pour Amélioré #1 — signal existant.
- Facilité de test : HAUTE. compare_variants.py peut tester plusieurs combinaisons directement, sans écrire de code nouveau.
- Urgence : HAUTE. Déploiement réel en cours, chaque amélioration du profil RANDOM a un impact direct sur les tickets joués.
- Verdict : **PRIORITÉ 1 POUR CETTE SESSION**

**Item 1 — Analyse contrefactuelle quotidienne [Fondateur]**
- Impact estimé : ÉLEVÉ à long terme (outil de diagnostic structurel)
- Facilité de test : FAIBLE — requiert un script complet + panneau Streamlit
- Urgence : MODÉRÉE — n'affecte pas les tickets en cours
- Verdict : **REPORTER — code requis, pas de test immédiat possible**

**Item 4 — Maestro log enrichi**
- Impact estimé : MODÉRÉ — outil d'observabilité, pas d'amélioration directe des tickets
- Facilité de test : FAIBLE — requiert modification du pipeline de log
- Urgence : MODÉRÉE — priorité "après Maestro log" déjà notée dans LABORATOIRE
- Verdict : **REPORTER**

**Item 7 — Correction procédure finetune (Bonferroni)**
- Ce n'est pas un test mais un acquis de Session 1 déjà intégré comme protocole. APPLIQUÉ systématiquement dès maintenant.
- Verdict : **CLOS — déjà acquis structurel**

**Items 2, 3, 5, 6** — tous requièrent du code et aucun n'a de signal existant fort. Impact incertain.
- Verdict : **REPORTER**

### Décision du Réducteur

**Session 2 se concentre sur :**
1. **TEST PRINCIPAL : Combinaisons build_source/select_source RANDOM** — 4 combinaisons à tester : LEAGUE/LEAGUE, LEAGUE/TEAM, TEAM/LEAGUE, TEAM/TEAM (baseline). N=50 runs minimum. Objectif : vérifier si LEAGUE-first améliore significativement SAFE RANDOM.

**Pourquoi pas l'analyse contrefactuelle :** c'est un outil, pas un paramètre. On ne peut pas le tester avec compare_variants.py. Son développement est légitime mais appartient à une session "code" séparée.

**Pourquoi cet item maintenant :** le Fondateur a observé empiriquement sur 1 semaine une efficacité de LEAGUE-first. Il existe un signal dans les profils connus (Profil #2 RANDOM WR=89.1% avec build_source=LEAGUE). Ces deux faits convergent. Le coût du test est faible. Si le signal existe, on améliore le déploiement réel immédiatement.

---

## SCEPTIQUE — Analyse des hypothèses

**Posture :** vérifier les présupposés, identifier les failles, proposer les conditions de rejet. Leçons Session 1 appliquées : vérifier dans le code avant d'affirmer, ne pas utiliser des moyennes globales trompeuses.

### Attaque de l'hypothèse principale : LEAGUE-first améliore RANDOM

**Présupposé 1 — Les combinaisons build/select n'ont pas été testées en isolation**

Ce n'est pas tout à fait exact. LABORATOIRE.md mentionne explicitement (Phase 5, 2026-04-02) : "Paramètres testés : `topk_size`, `excluded_bet_groups`, `team_ranking_mode`, `random_build_source`". Le paramètre `random_build_source` a donc été testé dans le finetune de Phase 5. MAIS : ce finetune a eu lieu avant la correction du filtre pool (Phase 7, 2026-04-02) qui a amélioré RANDOM SAFE de +52%. Le résultat de ce test est donc potentiellement invalide avec le nouveau filtre. Ce point est réel et mérite vérification.

**Présupposé 2 — L'observation sur 1 semaine (Fondateur) est un signal fiable**

1 semaine de données réelles représente ~7 jours, probablement 5-10 tickets. C'est un échantillon extrêmement petit — exactement le type de signal que notre Bonferroni filtre à 20 runs de simulation. Je ne rejette pas l'observation, mais je ne lui accorde aucun poids statistique.

**Présupposé 3 — Profil #2 WR=89.1% prouve la supériorité de LEAGUE build**

Profil #2 a `random_build_source=LEAGUE` ET `topk_size=3` (vs 10), `two_team_high=0.88`, `team_min_winrate=0.70`. Le WR 89.1% peut être attribué à la sélectivité extreme de topk=3, pas à LEAGUE build. C'est un confounding factor majeur. On ne peut pas isoler la contribution de `random_build_source` depuis la comparaison des profils.

**Présupposé 4 — LEAGUE-first "exploite la structure des ligues prolifiques"**

Vérifier dans le code si LEAGUE build fait réellement quelque chose de différent de TEAM build pour les ligues à fort volume de buts. Le mécanisme LEAGUE build filtre sur le WR historique de la ligue par famille de paris (league_bet_rate). Si la Bundesliga a 10/11 matchs à +1.5 goals AUJOURD'HUI, ça ne change pas son WR historique sur 61 jours. L'argument "structure prolifique" peut être une corrélation spurieuse : la Bundesliga a un bon WR O15 parce qu'elle est prolifique, MAIS ce bon WR est déjà capté par les deux modes (LEAGUE et TEAM via team_bet). Le différentiel entre les deux modes n'est pas démontré.

**Présupposé 5 — select_source LEAGUE améliore par rapport à TEAM**

`_random_ticket_final_score()` : en mode LEAGUE, score = `_ticket_score_random()` sur league_bet. En mode TEAM, score = `_ticket_score_random_team()` sur team_bet. La différence : LEAGUE score les picks selon le WR de leur ligue sur cette famille, TEAM score selon le WR de leurs équipes. Sur RANDOM (qui est O15-only post-filtre), les deux devraient converger si les données sont suffisantes. Mais si les données équipes sont sparse (team_min_decided=6 coupe beaucoup), LEAGUE peut avoir un signal plus stable.

**Conditions claires de rejet (définies avant le test)**

- Si SAFE ×mult RANDOM (LEAGUE build) < SAFE ×mult RANDOM (TEAM build, baseline) sur 50 runs → LEAGUE build n'améliore pas RANDOM, toutes combinaisons confondues
- Si la variante gagnante a un gain < 2% sur SAFE RANDOM par rapport à TEAM/TEAM → bruit, ne pas promouvoir
- Si le WR de la variante LEAGUE build > baseline de +3 pts mais SAFE ×mult identique → volume seul n'est pas un gain (rappel : win rate ne suffit pas, c'est les doublings qui comptent)
- Filtre Bonferroni à 50 runs : exiger delta > +2% ET statistiquement significatif avant de conclure à un signal

**Avertissement sur le test à 4 variantes simultanées**

Avec k=4 variantes, le biais de sélection est encore plus fort qu'à k=5 (Session 1). La valeur attendue du maximum parmi 4 variables est μ + 1.03σ même sans signal réel. Si on teste 4 combinaisons en un seul run, la meilleure sera vraisemblablement 1σ au-dessus des autres par chance pure. Il faut un delta très clair (> +3% SAFE ×mult) pour considérer un signal réel à 50 runs.

**Recommandation Sceptique**

Tester les 4 combinaisons, mais appliquer le critère Bonferroni ajusté : delta > +3% sur SAFE RANDOM ×mult pour promouvoir. Ne pas conclure sur la victoire marginale d'une variante.

---

## INNOVATEUR — Exploration et mécanismes

**Posture :** explorer les angles non explorés, défendre les hypothèses qui méritent d'être défendues, vérifier les mécanismes dans le code avant de les affirmer.

### Vérification code — mécanismes LEAGUE vs TEAM pour RANDOM

J'ai lu `services/ticket_builder.py` en détail. Voici ce que le code confirme réellement :

**Pipeline RANDOM : deux étapes distinctes**

1. `filter_effective_random_pool()` (ligne 1654) — filtre le pool de base O15 selon `random_build_source` :
   - LEAGUE : filtre par `_league_bet_rate()` — WR historique de la ligue sur cette famille de paris
   - TEAM : filtre par `_team_rate()` des équipes, mais seulement les équipes avec `dec >= team_min_decided` (=6)
   - HYBRID : blending alpha × league + (1-alpha) × team score

2. `_try_build_ticket_random()` → `_random_accept_pick()` (ligne 2481) — gate de sélection lors de la construction :
   - TEAM : utilise `usable = [(wr, dec) for wr, dec in vals if dec > 0]` — PAS de filtre team_min_decided ici ! C'est une asymétrie avec le filtre pool.
   - LEAGUE : utilise `_league_bet_rate()` directement
   - NOTE : pas de branche HYBRID dans `_random_accept_pick()` — la condition `build_src == "TEAM"` ou le fallback LEAGUE seulement

**Découverte critique — incohérence build_src TEAM dans _random_accept_pick()**

`filter_effective_random_pool()` filtre les équipes avec `dec >= cfg.team_min_decided` (6 min). Mais `_random_accept_pick()` utilise `dec > 0` — n'importe quelle équipe avec au moins 1 match passe le gate de construction. En pratique, le pool effectif a déjà éliminé les picks non-fiables, donc cette incohérence est atténuée. Mais elle signifie que le gate de construction TEAM est plus permissif que le filtre pool.

**select_source : mécanisme de scoring final confirmé**

`_random_ticket_final_score()` (ligne 1335-1345) :
- LEAGUE : score = `_ticket_score_random()` sur league_bet — WR ligue par famille
- TEAM : score = `_ticket_score_random_team()` sur team_bet — WR équipes

La différence entre LEAGUE et TEAM pour select_source est le signal utilisé pour choisir le meilleur ticket dans le top-K. Avec select_source=LEAGUE, on favorise les tickets dont la ligue a historiquement le meilleur WR sur O15. Avec TEAM, on favorise les tickets dont les équipes ont le meilleur WR individuel.

**Argument pour LEAGUE build :**

Le LEAGUE build filtre selon le WR historique de la ligue sur O15. Les ligues prolifiques (Bundesliga, Championship anglais, Ligue 2 française) ont structurellement de meilleurs WR sur O15 — donc LEAGUE build leur donne naturellement la priorité. C'est un mécanisme explicite : si la Bundesliga a WR=0.75 sur O15 sur 61 jours, tous ses matchs passent le gate league ; si une équipe individuelle a WR=0.55 sur 6 matchs, elle peut être éliminée par TEAM build même dans une ligue forte.

**Argument pour TEAM build (pourquoi le champion actuel est TEAM/TEAM) :**

TEAM build va plus fin : il regarde les équipes spécifiques. Une ligue avec WR=0.75 global peut contenir des équipes à WR=0.50 (qui diluent la qualité). TEAM build les élimine. La correction de Phase 7 (team_min_decided=6) a précisément rendu ce filtre plus fiable — avant la correction, les équipes avec 1 match bloquaient injustement; maintenant le filtre est justement calibré.

**Hypothèse testable (Innovateur) :**

Il y a deux effets opposés en jeu :
- LEAGUE build = plus de picks en pool (filtre plus large par ligue), potentiellement plus de diversité, mais moins de précision par équipe
- TEAM build = pool plus restreint mais plus précis, picks individuellement validés

Si les données équipes sont maintenant fiables post-correction (team_min_decided=6), TEAM/TEAM peut être optimal. Si les données équipes sont encore sparse sur certaines ligues, LEAGUE build peut récupérer des picks perdus à tort par TEAM.

**Ce que je propose de tester :**

4 combinaisons en test 50 runs :
1. TEAM/TEAM (baseline — profil champion)
2. LEAGUE/LEAGUE (hypothèse LEAGUE-first totale)
3. LEAGUE/TEAM (build LEAGUE, score TEAM — exploite le volume de LEAGUE mais score par équipe)
4. TEAM/LEAGUE (build TEAM, score LEAGUE — filtre précis, score par ligue)

Je défends que LEAGUE/TEAM est l'hypothèse la plus intéressante : le build LEAGUE maximise le pool des ligues prolifiques, et le select TEAM affine par qualité d'équipe. C'est une combinaison hybride non testée. Sans mécanisme dans le code pour la confirmer a priori, je pose cela comme hypothèse testable — pas comme conclusion.

---

## DÉCISION DE TEST

**Item retenu :** Combinaisons random_build_source × random_select_source
**Outil :** compare_variants.py modifié avec 4 variantes
**N runs :** 50 (minimum requis par notre protocole)
**Métrique primaire :** SAFE ×mult RANDOM
**Seuil de promotion :** delta > +3% SAFE RANDOM ×mult (Bonferroni ajusté k=4)

**4 variantes testées :**
1. TEAM/TEAM — baseline (profil champion)
2. LEAGUE/LEAGUE — hypothèse LEAGUE-first totale
3. LEAGUE/TEAM — build LEAGUE, select TEAM (hypothèse Innovateur)
4. TEAM/LEAGUE — build TEAM, select LEAGUE

**Justification N=50 vs 100 :** On teste une famille de 4 variantes, pas une seule. 50 runs donne déjà un signal clair si l'écart est > 5%. Si un signal à 50 runs passe le seuil +3%, on confirmera à 100 runs en Session 3 avant tout déploiement.

---

## RÉSULTATS BRUTS

**STATUT : TEST EN ATTENTE D'EXÉCUTION**

Le fichier `compare_variants.py` a été configuré pour les 4 variantes (SESSION 2 BCEA — 2026-04-04).
Commande à lancer : `python compare_variants.py --runs 50`

Le test sera exécuté dès que l'autorisation de lancement est accordée.
Résultats à reporter ici après exécution.

---

## VALIDATEUR FROID — Verdict

**STATUT : EN ATTENTE DES RÉSULTATS BRUTS**

Critères appliqués dès réception des résultats :

**Pour chaque variante vs baseline TEAM/TEAM sur SAFE RANDOM ×mult :**
- VALIDÉ si delta ≥ +3% (Bonferroni k=4) ET écart > 2σ sur 50 runs
- EN ATTENTE si 0 < delta < +3% → mérite confirmation 100 runs
- REJETÉ si delta < 0 sur 50 runs

**Pour les items sans test (protocoles décidés) :**
- Analyse contrefactuelle : EN ATTENTE DE DÉVELOPPEMENT — requiert script Python + panneau Streamlit. Prochaine action : session de développement dédiée.
- Maestro log enrichi : EN ATTENTE DE DÉVELOPPEMENT — infrastructure existe, code à compléter.
- Filtre Bonferroni (k=5, delta > +2.5) : ACQUIS SESSION 1 — APPLIQUÉ dès maintenant.

---

## ⚖️ VALIDATEUR FROID — Verdict Session 2

*Rendu le 2026-04-04 — sur N=50 runs, seuil Bonferroni k=4 : delta > +3% SAFE RANDOM ×mult requis*

### Résultats bruts (RANDOM SAFE ×mult — métrique principale)

| Variante | SAFE ×mult | σ | Ruine | Delta vs baseline | t-stat vs baseline |
|----------|-----------|---|-------|-------------------|--------------------|
| TEAM/TEAM (baseline) | ×56.69 | 40.84 | 0% | — | — |
| TEAM/LEAGUE | ×64.91 | 57.20 | 0% | **+14.5%** | **0.83σ** |
| LEAGUE/TEAM | ×24.27 | 23.64 | 8% | -57.2% | — |
| LEAGUE/LEAGUE | ×14.68 | 20.42 | 32% | -74.1% | — |

*Calcul t-stat TEAM/LEAGUE vs TEAM/TEAM : SE = √(40.84²/50 + 57.20²/50) = √(33.36 + 65.46) = √98.82 ≈ 9.94 → t = 8.22 / 9.94 = 0.83σ*

### Verdicts par variante

**TEAM/LEAGUE (build TEAM, select LEAGUE) — REJETÉ (signal insuffisant)**
- Delta brut : +14.5% sur SAFE RANDOM ×mult (×64.91 vs ×56.69)
- Statistique : t = 0.83σ, très en dessous du seuil 2σ requis
- Raison de rejet : le delta brut est trompeur. La variance de TEAM/LEAGUE est dramatiquement plus élevée (σ=57.20 vs σ=40.84). La différence des moyennes (+8.22) est absorbée dans le bruit de Monte Carlo. Sur 50 runs avec ces variances, ce résultat est compatible avec H0 (aucune différence réelle).
- Note supplémentaire : le WR de TEAM/LEAGUE est plus bas (60.6% vs 71.8%) mais SAFE ×mult est plus haut. C'est un artefact de haute variance — quelques runs exceptionnels gonflent la moyenne. Ce type de résultat est classiquement instable et régresserait vers la baseline sur 100+ runs.
- Décision : **PAS DE PROMOTION. Baseline TEAM/TEAM conservée.**

**LEAGUE/TEAM (build LEAGUE, select TEAM) — REJETÉ**
- Delta : -57.2% sur SAFE RANDOM ×mult (×24.27 vs ×56.69)
- Ruine SAFE 8% (vs 0% baseline) — régression nette de la robustesse
- Décision : **REJETÉ sans ambiguïté. Build LEAGUE dégrade RANDOM.**

**LEAGUE/LEAGUE (build LEAGUE, select LEAGUE) — REJETÉ**
- Delta : -74.1% sur SAFE RANDOM ×mult (×14.68 vs ×56.69)
- Ruine SAFE 32% (catastrophique), WR RANDOM 49.0% (sous 50% — pire que le hasard en pratique)
- Décision : **REJETÉ catégoriquement. LEAGUE/LEAGUE est destructeur pour RANDOM.**

### Conclusion globale

**TEAM/TEAM reste baseline et profil champion. Aucune des 3 variantes testées ne justifie une modification du profil.**

Le signal TEAM/LEAGUE (+14.5% brut) ne passe pas le filtre statistique à 50 runs. Pour qu'il devienne candidat à confirmation, il faudrait un t-stat ≥ 2σ. Avec les variances observées, cela nécessiterait N ≈ 500 runs — économiquement déraisonnable pour un signal aussi incertain. Ce test est clos.

**Découverte structurelle permanente :** build_source LEAGUE est systématiquement néfaste pour RANDOM (LEAGUE/TEAM : -57%, LEAGUE/LEAGUE : -74%). Le build TEAM (avec filtre team_min_decided=6 de Phase 7) est confirmé supérieur pour construire le pool RANDOM. C'est un acquis définitif.

**select_source LEAGUE (TEAM/LEAGUE) :** le signal brut ne suffit pas à conclure. La hausse de variance est préoccupante. Sans amélioration du t-stat, ce n'est pas un candidat prioritaire.

### Prochaine action recommandée

1. Restaurer compare_variants.py en état neutre (test Session 2 terminé)
2. Mettre à jour LABORATOIRE.md — Phase 10 avec résultats réels
3. Session suivante : prioriser Maestro log enrichi (infrastructure existe, impact observabilité immédiat) ou analyse contrefactuelle (outil diagnostic priorité Fondateur)
4. Ne pas re-tester build/select source RANDOM sans hypothèse mécaniste nouvelle et N ≥ 200 runs

---

## DÉCISIONS ET MISES À JOUR

### Décisions prises (sans test)

1. **Filtre Bonferroni k=4 pour cette session** — avec 4 variantes simultanées, le seuil de signal est delta > +3% SAFE RANDOM ×mult sur 50 runs. [Sceptique + Validateur]

2. **Analyse contrefactuelle** — REPORTÉE en session code dédiée. Impact élevé mais requiert développement.

3. **Maestro log enrichi** — REPORTÉ. Priorité après stabilisation du profil.

4. **Incohérence _random_accept_pick() vs filter_effective_random_pool()** — IDENTIFIÉE par Innovateur (vérification code). `_random_accept_pick()` utilise `dec > 0` pour TEAM mode (pas de team_min_decided=6), contrairement à `filter_effective_random_pool()`. Impact pratique limité (le pool effectif a déjà pré-filtré), mais c'est une asymétrie à documenter pour future maintenance.

### Test configuré

compare_variants.py configuré pour SESSION 2 BCEA — 4 variantes build/select source RANDOM, 50 runs.
Commande : `python compare_variants.py --runs ,ç,,ççoi,;,çkl,; ,iç50`
