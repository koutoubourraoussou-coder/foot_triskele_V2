# ARCHIVE TECHNIQUE — Session 2 — BCEA — 2026-04-04
*Transcription technique complète — tous les chiffres, toutes les décisions*

---

## IDENTIFICATION

- **Date :** 2026-04-04
- **Numéro de session :** 2
- **Sujet :** Observation Fondateur — Ligues prolifiques et combinaisons build_source/select_source RANDOM
- **Agents impliqués :** Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid
- **Statut :** Partiel — test configuré, en attente d'exécution

---

## CONTEXTE D'ENTRÉE

### Observation Fondateur (soumise comme faits bruts, 2026-04-04)
- Certaines ligues sont structurellement prolifiques (Bundesliga 1&2 : 10/11 matchs à +1.5 goals ce jour)
- LEAGUE-first semble efficace sur tests personnels (~1 semaine)
- TEAM/TEAM est le profil champion — le Fondateur s'en étonne
- Combinaisons build_source/select_source RANDOM n'ont peut-être pas été testées correctement en isolation

### Acquis de Session 1 appliqués
- Filtre Bonferroni : delta > +2.5 requis à 20 runs pour k=5
- Tout résultat finetune N ≤ 30 = SIGNAL CANDIDAT uniquement
- global_bet_min_winrate n'affecte pas RANDOM

### Profil champion en cours
- random_build_source=TEAM, random_select_source=TEAM
- Déployé depuis 2026-04-02
- Résultats de référence : SAFE RANDOM ×67.48 (0% ruine), 100 runs, 61 jours

---

## ÉTAPE 1 — RÉDUCTEUR DE BRUIT — PRIORISATION

### Backlog évalué (8 items)

| Item | Impact | Facilité | Urgence | Décision |
|------|--------|----------|---------|----------|
| Ligues prolifiques / build/select source RANDOM [NEW] | ÉLEVÉ | HAUTE (compare_variants.py) | HAUTE (déploiement réel) | **PRIORITÉ 1** |
| Analyse contrefactuelle quotidienne | ÉLEVÉ | FAIBLE (nouveau script) | MODÉRÉE | REPORTÉ |
| Maestro log enrichi | MODÉRÉ | FAIBLE (code à compléter) | MODÉRÉE | REPORTÉ |
| Correction finetune (Bonferroni) | N/A | N/A | N/A | CLOS — acquis S1 |
| RANDOM O15 filtre winrate | INCERTAIN | FAIBLE | BASSE | REPORTÉ |
| Poids composite 70/30 | INCERTAIN | FAIBLE | BASSE | REPORTÉ |
| Nouveaux types de paris | INCERTAIN | FAIBLE | BASSE | REPORTÉ |
| Recency weighting | INCERTAIN | FAIBLE | BASSE | REPORTÉ |

### Justification du choix Session 2
- Observation Fondateur converge avec signal existant (Profil #2 WR=89.1% RANDOM avec build_source=LEAGUE)
- Aucun code nouveau requis — compare_variants.py suffit
- Déploiement réel en cours depuis 2026-04-03 — toute amélioration RANDOM a impact immédiat
- test précédent de random_build_source (Phase 5, 2026-04-02) précédait la correction +52% du filtre pool — potentiellement invalide

---

## ÉTAPE 2 — SCEPTIQUE — ANALYSE DES HYPOTHÈSES

### Présupposés attaqués

**P1 — "Les combinaisons n'ont pas été testées en isolation"**
Partiellement faux : LABORATOIRE.md mentionne `random_build_source` testé en finetune Phase 5 (2026-04-02). MAIS : ce test précédait la correction du filtre pool (Phase 7, +52% sur RANDOM SAFE). Résultat potentiellement invalide. Le point mérite vérification.

**P2 — "L'observation 1 semaine est un signal fiable"**
~7 jours, ~5-10 tickets réels. Échantillon statistiquement nul — aucun poids statistique accordé.

**P3 — "Profil #2 WR=89.1% prouve la supériorité de LEAGUE build"**
Confounding majeur : Profil #2 a simultanément topk_size=3 (vs 10), two_team_high=0.88, team_min_winrate=0.70. Le WR 89.1% peut provenir de la sélectivité extreme de topk=3, pas de LEAGUE build. Test isolé requis.

**P4 — "LEAGUE-first exploite la structure des ligues prolifiques"**
Mécanisme partiel seulement : LEAGUE build filtre sur WR historique ligue (61 jours), pas sur l'actualité du jour. Si la Bundesliga est prolifique aujourd'hui, c'est déjà dans son WR historique — capté par les deux modes. Le différentiel réel entre LEAGUE et TEAM build n'est pas démontré a priori.

**P5 — "select_source LEAGUE améliore par rapport à TEAM"**
Sur RANDOM (O15 uniquement), LEAGUE score = WR ligue sur O15, TEAM score = WR équipes sur O15. Si données équipes sparse (team_min_decided=6 exclut beaucoup), LEAGUE peut avoir signal plus stable. Mais c'est contextuel.

### Conditions de rejet définies avant le test
- Delta SAFE RANDOM ×mult < +3% sur 50 runs → pas de promotion (Bonferroni k=4)
- Si WR > baseline de +3 pts mais SAFE ×mult identique → volume seul n'est pas un gain (doublings comptent, pas WR brut)
- Si variante gagnante marginale < +3% → EN ATTENTE confirmation 100 runs

---

## ÉTAPE 3 — INNOVATEUR — VÉRIFICATION CODE ET MÉCANISMES

### Code vérifié : `services/ticket_builder.py`

**Pipeline RANDOM — deux étapes distinctes :**

1. `filter_effective_random_pool()` (ligne 1654-1751) — filtre le pool de base O15 :
   - LEAGUE (ligne 1738-1748) : filtre par `_league_bet_rate(league_bet, lg, fam)` — compare à `league_bet_min_winrate` (0.60)
   - TEAM (ligne 1675-1697) : filtre par `_team_rate()` des équipes avec `dec >= cfg.team_min_decided` (6 min) — équipes fiables uniquement
   - HYBRID (ligne 1699-1736) : blending alpha × score_league + (1-alpha) × score_team

2. `_try_build_ticket_random()` → `_random_accept_pick()` (ligne 2481-2503) — gate de sélection :
   - TEAM (ligne 2485-2498) : utilise `usable = [(wr, dec) for wr, dec in vals if dec > 0 and wr is not None]` — **PAS de filtre team_min_decided=6** (asymétrie vs filter_effective_random_pool)
   - LEAGUE (ligne 2500-2503) : utilise `_league_bet_rate()` directement

**Découverte critique :**
`_random_accept_pick()` pour TEAM mode utilise `dec > 0` (1 match minimum), tandis que `filter_effective_random_pool()` utilise `dec >= team_min_decided` (6 minimum). Asymétrie documentée. Impact pratique limité car le pool a été pré-filtré par `filter_effective_random_pool()`.

**`_random_ticket_final_score()` (ligne 1335-1345) :**
- LEAGUE : `_ticket_score_random(picks, league_bet)` — WR ligue par famille de paris
- TEAM : `_ticket_score_random_team(picks, team_bet)` — WR équipes

**Mécanisme LEAGUE build confirmé :**
LEAGUE build filtre sur WR historique de la ligue sur la famille de paris (O15 uniquement pour RANDOM). Les ligues prolifiques (Bundesliga, Championship) ont structurellement un meilleur WR O15 sur 61 jours → leurs matchs passent plus facilement le gate LEAGUE (seuil 0.60). C'est un mécanisme explicite et vérifiable.

**Hypothèse Innovateur — LEAGUE/TEAM :**
Build LEAGUE : maximise le pool des ligues prolifiques via WR ligue
Select TEAM : affine la sélection finale par qualité individuelle des équipes
Mécanisme : deux filtres en cascade de nature différente — pas de duplication, potentiellement complémentaires.

### 4 variantes configurées pour le test

| Variante | build_source | select_source | Différence vs baseline |
|----------|-------------|---------------|----------------------|
| TEAM/TEAM | TEAM | TEAM | Baseline — profil champion |
| LEAGUE/LEAGUE | LEAGUE | LEAGUE | Deux dimensions LEAGUE |
| LEAGUE/TEAM | LEAGUE | TEAM | Build LEAGUE, score TEAM |
| TEAM/LEAGUE | TEAM | LEAGUE | Build TEAM, score LEAGUE |

---

## ÉTAPE 4 — CONFIGURATION DU TEST

### Fichier modifié
`/Users/koutoubourraoussou/Desktop/foot_triskele_V2/compare_variants.py`

### Modification de `_build_variants()` pour SESSION 2

```python
def _build_variants(base: BuilderTuning):
    # SESSION 2 BCEA — 2026-04-04
    # Hypothèse : les combinaisons random_build_source x random_select_source
    # impactent significativement SAFE RANDOM. Observation Fondateur : LEAGUE-first
    # semble efficace. 4 combinaisons testées en isolation.
    return [
        ("TEAM/TEAM — baseline (profil champion actuel)",
         base),
        ("LEAGUE/LEAGUE — build LEAGUE, select LEAGUE",
         replace(base, random_build_source="LEAGUE", random_select_source="LEAGUE")),
        ("LEAGUE/TEAM — build LEAGUE, select TEAM",
         replace(base, random_build_source="LEAGUE", random_select_source="TEAM")),
        ("TEAM/LEAGUE — build TEAM, select LEAGUE",
         replace(base, random_build_source="TEAM", random_select_source="LEAGUE")),
    ]
```

### Paramètres du test
- N runs : 50 (minimum protocole)
- Commande : `python compare_variants.py --runs 50`
- Métrique primaire : SAFE ×mult RANDOM
- Seuil de promotion : delta > +3% (Bonferroni ajusté k=4)

### STATUT : EN ATTENTE D'EXÉCUTION
Le test n'a pas pu être exécuté automatiquement. Le Fondateur doit lancer : `python compare_variants.py --runs 50` depuis le répertoire du projet.

---

## ÉTAPE 5 — VALIDATEUR FROID — VERDICT PROVISOIRE

### Tests avec résultats

**Aucun résultat disponible — test en attente.**

### Décisions sans test

| Item | Décision | Raison |
|------|----------|--------|
| Analyse contrefactuelle quotidienne | EN ATTENTE DE DÉVELOPPEMENT | Requiert script + Streamlit. Impact élevé, planifier session code dédiée. |
| Maestro log enrichi | EN ATTENTE DE DÉVELOPPEMENT | Infrastructure existe, code à compléter. |
| Filtre Bonferroni procédure finetune | CLOS — ACQUIS | Intégré comme protocole standard dès Session 1. |
| Incohérence _random_accept_pick() vs filter_pool | DOCUMENTÉ | Asymétrie réelle, impact limité, à surveiller. |

---

## RÉSUMÉ DES DÉCISIONS DE SESSION 2

1. **Test configuré** : 4 variantes build/select source RANDOM, compare_variants.py, 50 runs
2. **Backlog épuré** : items sans code possible reportés, acquis Session 1 clos
3. **Seuil Bonferroni k=4** : delta > +3% requis pour signal valide
4. **Incohérence code documentée** : asymétrie TEAM build entre gate construction et filtre pool

---

## PROCHAINES ACTIONS

1. **IMMÉDIAT** : Exécuter `python compare_variants.py --runs 50` et reporter les résultats dans cette archive
2. **Si signal > +3%** : confirmer à 100 runs en Session 3, puis déployer si confirmé
3. **Session code dédiée** : Analyse contrefactuelle + Maestro log enrichi
4. **Restauration compare_variants.py** : après exécution du test, restaurer `_build_variants()` à son état SESSION 1 commenté (ou créer une version SESSION 2 archivée)

---

*Archive produite le 2026-04-04 — Session 2 — BCEA*
*Agent Principal — Bureau Central d'Excellence Analytique*
