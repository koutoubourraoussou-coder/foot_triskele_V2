# LABORATOIRE TRISKÈLE V2
## Journal d'évolution du Ticket Builder

---

## PROTOCOLE DE LECTURE — Pour Claude

**À lire en priorité dès le début de chaque conversation.**

Ce fichier est la mémoire vivante du projet. Il contient :
- Les décisions clés avec leur **attribution** (qui a eu l'idée)
- Les expériences rejetées (pour ne pas les re-proposer)
- Les benchmarks de référence
- Les pistes en cours

**Convention d'attribution :**
- `[Claude]` — idée proposée par Claude
- `[Utilisateur]` — idée proposée par l'utilisateur
- `[Utilisateur corrige Claude]` — l'utilisateur a contredit Claude et avait raison
- `[Convergence]` — émergé de la discussion

**Règle absolue :** Ne jamais affirmer qu'un paramètre est "arbitraire" ou "non optimisé" sans avoir vérifié dans ce fichier ou dans le code (finetune_profile.py, compare_all_profiles.py, optimizer_top_profiles.json).

---

## PROFIL CHAMPION ACTUEL — Amélioré #1
*Appliqué dans `services/ticket_builder.py` depuis le 2026-04-01 — confirmé définitif le 2026-04-02*

Ce profil est la version optimisée du meilleur profil sorti de l'optimizer (rank_score=220.47),
enrichi de 4 améliorations confirmées par fine-tuning et validation Monte Carlo (200 runs, 61 jours).

> **Super Fusion testé et rejeté** (2026-04-02) : exclusion TEAM_WIN_FT n'a aucun mécanisme sur le pool RANDOM (O15 uniquement), et la différence SYSTEM (+0.033) est du bruit. Amélioré #1 reste champion.

### Paramètres clés du profil champion

| Paramètre | Valeur | Note |
|-----------|--------|------|
| `system_select_source` | HYBRID | Sélection finale SYSTEM : mix league + team |
| `hybrid_alpha` | 0.6 | Poids LEAGUE dans le mix hybride |
| `random_build_source` | TEAM | Construction tickets RANDOM depuis stats équipes |
| `random_select_source` | TEAM | Sélection finale RANDOM depuis stats équipes |
| `two_team_high` | **0.90** | ← amélioré (était 0.80) |
| `two_team_low` | 0.66 | Seuil bas pour paris two-team |
| `global_bet_min_winrate` | **0.65** | ← amélioré (était 0.62) |
| `global_bet_min_decided` | 10 | Matchs décidés minimum (global) |
| `league_bet_min_winrate` | **0.60** | ← amélioré (était 0.65) |
| `league_bet_require_data` | **False** | ← amélioré (était True) |
| `team_min_decided` | 6 | Matchs décidés minimum (équipe) |
| `team_min_winrate` | 0.75 | Win rate minimum équipe |
| `topk_size` | 10 | Taille du top-K pour la sélection |
| `topk_uniform_draw` | True | Tirage uniforme dans le top-K |
| `league_ranking_mode` | CLASSIC | Mode ranking ligue |
| `team_ranking_mode` | COMPOSITE | Mode ranking équipe |
| `weight_min` | 1.0 | Poids minimum |
| `weight_max` | 2.0 | Poids maximum |
| `weight_ceil` | 0.95 | Plafond pondération |
| `prefer_3legs_delta` | 0.08 | Bonus préférence tickets 3 paris |
| `min_accept_odd` | 1.8 | Cote minimale acceptée |
| `day_max_windows_rich` | 4 | Fenêtres max les jours riches |
| `min_side_matches_for_split` | 5 | Min matchs pour découper une fenêtre |
| `split_gap_weight` | 0.6 | Bonus si découpe dans creux horaire |
| `excluded_bet_groups` | ∅ | Aucun type de pari exclu |

### Pourquoi ces 4 améliorations fonctionnent

- **`two_team_high` 0.80→0.90** : sélection plus stricte → meilleures cotes → plus de profit par victoire → plus de doublings martingale
- **`global_bet_min_winrate` 0.62→0.65** : filtre global légèrement plus exigeant → qualité supérieure
- **`league_bet_require_data` True→False** : les ligues sans historique ne sont plus rejetées → plus de volume de tickets
- **`league_bet_min_winrate` 0.65→0.60** : seuil league plus permissif → plus de tickets, interaction positive avec require_data=False

---

## PROFIL #2 — Réserve (rank_score=216.84)
*Source : `data/optimizer/optimizer_top_profiles.json` — rang 2*

Point fort : **WR 89.1% en RANDOM**, série max 36 victoires, jamais de ruine. Très sélectif (peu de tickets).

| Paramètre | Valeur | Différence vs Amélioré #1 |
|-----------|--------|---------------------------|
| `system_select_source` | TEAM | ← différent (HYBRID) |
| `random_build_source` | **LEAGUE** | ← différent (TEAM) |
| `random_select_source` | TEAM | = |
| `hybrid_alpha` | 0.4 | ← différent (0.6) |
| `topk_size` | **3** | ← différent (10) |
| `topk_uniform_draw` | False | ← différent (True) |
| `two_team_high` | 0.88 | ← différent (0.90) |
| `two_team_low` | 0.60 | ← différent (0.66) |
| `global_bet_min_decided` | **7** | ← différent (10) |
| `global_bet_min_winrate` | 0.62 | ← différent (0.65) |
| `league_bet_require_data` | False | = |
| `league_bet_min_winrate` | 0.65 | ← différent (0.60) |
| `team_min_decided` | 8 | ← différent (6) |
| `team_min_winrate` | 0.70 | ← différent (0.75) |
| `weight_min` | 1.2 | ← différent (1.0) |
| `weight_ceil` | 1.0 | ← différent (0.95) |
| `prefer_3legs_delta` | 0.0 | ← différent (0.08) |
| `min_accept_odd` | 1.7 | ← différent (1.8) |
| `day_max_windows_rich` | **2** | ← différent (4) |
| `min_side_matches_for_split` | **3** | ← différent (5) |
| `split_gap_weight` | 0.35 | ← différent (0.6) |
| `excluded_bet_groups` | **HT05** | ← différent (∅) |
| `search_budget_ms_random` | 300 | ← différent (500) |

---

## PROFIL #3 — Réserve (rank_score=215.94)
*Source : `data/optimizer/optimizer_top_profiles.json` — rang 3*

Point fort : **WR 78.3% en SYSTEM**, 0% ruine partout. Très stable, bonne régularité.

| Paramètre | Valeur | Différence vs Amélioré #1 |
|-----------|--------|---------------------------|
| `system_build_source` | **TEAM** | ← différent (LEAGUE) |
| `system_select_source` | TEAM | ← différent (HYBRID) |
| `random_build_source` | TEAM | = |
| `random_select_source` | TEAM | = |
| `hybrid_alpha` | 0.8 | ← différent (0.6) |
| `topk_size` | **5** | ← différent (10) |
| `two_team_high` | 0.85 | ← différent (0.90) |
| `two_team_low` | 0.58 | ← différent (0.66) |
| `global_bet_min_winrate` | **0.70** | ← différent (0.65) |
| `league_bet_require_data` | True | ← différent (False) |
| `league_bet_min_winrate` | 0.72 | ← différent (0.60) |
| `team_min_decided` | 8 | ← différent (6) |
| `team_min_winrate` | **0.78** | ← différent (0.75) |
| `weight_min` | 0.8 | ← différent (1.0) |
| `weight_baseline` | 0.78 | ← différent (0.74) |
| `weight_ceil` | 1.0 | ← différent (0.95) |
| `prefer_3legs_delta` | 0.0 | ← différent (0.08) |
| `min_accept_odd` | 1.6 | ← différent (1.8) |
| `target_odd` | 2.3 | ← différent (2.4) |
| `rich_day_match_count` | 20 | ← différent (18) |
| `day_max_windows_rich` | **3** | ← différent (4) |
| `min_side_matches_for_split` | 4 | ← différent (5) |
| `split_gap_weight` | 0.2 | ← différent (0.6) |
| `league_ranking_mode` | **COMPOSITE** | ← différent (CLASSIC) |
| `team_ranking_mode` | **CLASSIC** | ← différent (COMPOSITE) |
| `search_budget_ms_system` | 800 | ← différent (500) |
| `search_budget_ms_random` | 300 | ← différent (500) |
| `topk_uniform_draw` | True | = |

---

## RÉSULTATS DE RÉFÉRENCE — Monte Carlo 200 runs, 61 jours

### Amélioré #1 vs Super Fusion — 200 runs (2026-04-02)

| Mode | Profil | Tickets | Win rate | NORM ×mult | NORM ruine | SAFE ×mult | SAFE ruine | Doublings |
|------|--------|---------|----------|------------|------------|------------|------------|-----------|
| SYSTEM | **Super Fusion** | 85.9 | 69.0% | ×797 | 14% | ×31.01 | **0%** | 8.5 |
| SYSTEM | Amélioré #1 | 85.8 | 68.4% | ×830 | 11% | ×31.08 | 0% | 8.6 |
| RANDOM | **Super Fusion** | 70.0 | 72.1% | ×1303 | 20% | **×49.07** | **0%** | 7.2 |
| RANDOM | Amélioré #1 | 70.1 | 72.2% | ×1194 | 21% | ×45.63 | 0% | 7.0 |

> SYSTEM : tie (0.033 d'écart, bruit statistique). RANDOM : Super Fusion +1.721. **Super Fusion désigné champion.**

### 5 profils comparés — 200 runs (2026-04-01)

#### MODE SYSTEM — du meilleur au moins bon

| # | Profil | Tickets | Win rate | Pire L (moy/max) | Meill. V (moy/max) | NORM ×mult | NORM ruine | SAFE ×mult | SAFE ruine | Doublings |
|---|--------|---------|----------|------------------|---------------------|------------|------------|------------|------------|-----------|
| 1 | **Amélioré #1** | 85.8 | 68.6% | 3.0 / 7 | 8.4 / 17 | ×782 | 14% | **×31.09** | **0%** | 8.5 |
| 2 | Profil #3 | 71.4 | 78.3% | 2.7 / 4 | 13.1 / 18 | ×307 | 13% | ×22.04 | 0% | 7.0 |
| 3 | Profil #1 | 84.9 | 72.4% | 3.4 / 6 | 10.8 / 22 | ×571 | 42% | ×21.23 | 32% | 5.9 |
| 4 | Profil #2 | 66.9 | 76.8% | 2.2 / 4 | 12.4 / 20 | ×216 | ~0% | ×20.13 | 0% | 6.7 |
| 5 | Actuel | 84.6 | 58.6% | 5.0 / 12 | 7.8 / 13 | ×69 | 72% | ×14.81 | 15% | 5.1 |

#### MODE RANDOM — du meilleur au moins bon

| # | Profil | Tickets | Win rate | Pire L (moy/max) | Meill. V (moy/max) | NORM ×mult | NORM ruine | SAFE ×mult | SAFE ruine | Doublings |
|---|--------|---------|----------|------------------|---------------------|------------|------------|------------|------------|-----------|
| 1 | **Amélioré #1** | 70.1 | 72.0% | 3.2 / 5 | 9.9 / 24 | ×1233 | 17% | **×45.18** | **0%** | 7.0 |
| 2 | Profil #1 | 70.0 | 76.4% | 2.7 / 7 | 12.7 / 32 | ×705 | 9% | ×32.85 | 0% | 7.1 |
| 3 | Profil #2 | 58.7 | 89.1% | 1.2 / 2 | 26.7 / 36 | ×288 | 0% | ×21.77 | 0% | 7.0 |
| 4 | Profil #3 | 61.9 | 82.4% | 2.1 / 4 | 12.1 / 24 | ×204 | ~0% | ×19.68 | 0% | 6.9 |
| 5 | Actuel | 67.4 | 54.9% | 5.1 / 10 | 6.4 / 12 | ×63 | 78% | ×16.33 | 2% | 4.6 |

---

## HISTORIQUE DES ÉTAPES CLÉS

### Phase 1 — Seuils dynamiques (match_analysis.py)
- Calcul automatique des seuils min par `bet_key` depuis `verdict_post_analyse.txt`
- Script : `compute_label_thresholds.py` → génère `data/min_level_by_bet.json`
- Chargement automatique au démarrage de `match_analysis.py`
- Résultat : seuils adaptatifs basés sur ≥73% winrate avec ≥20 échantillons

### Phase 2 — Identification du vrai profil #1
- L'optimizer avait produit `optimizer_top_profiles.json` avec rank_score=220.47
- Le ticket_builder.py contenait des valeurs incorrectes (profil imaginaire)
- Vérification et correction des 32 paramètres un par un contre le JSON
- Profil #1 réel : HYBRID system, TEAM random, topk=10, two_team_high=0.80

### Phase 3 — Fine-tuning one-at-a-time
- Script : `finetune_profile.py`
- Méthode : un paramètre varie à la fois, les autres restent fixés
- Score composite : `SAFE_SYS×0.4 + SAFE_RND×0.4 + WR×0.2 − ruine×0.5`
- 21 paramètres testés, ~140 évaluations initiales (2 runs) + validation (10 runs)
- **4 améliorations confirmées** (voir profil champion)

### Phase 4 — Validation Monte Carlo
- Script : `compare_variants.py` → profil #1 original vs Amélioré (50 puis 100 runs)
- Script : `compare_all_profiles.py` → 5 profils, 200 runs chacun
- Amélioré #1 domine dans les deux modes sur le profit SAFE

### Phase 5 — Fine-tuning sur base Amélioré #1 (2026-04-02)
- Base : Amélioré #1 (baked dans `_load_profile1()` via `_AMELIORE_OVERRIDES`)
- Paramètres testés : `topk_size` (10 est optimal), `excluded_bet_groups`, `team_ranking_mode`, `random_build_source`
- Résultat : `excluded_bet_groups={TEAM1_WIN_FT, TEAM2_WIN_FT}` améliore le score de +3.880
- Super Fusion = Amélioré #1 + exclusion WIN_FT — validé 200 runs

### Phase 6 — Comparaison Amélioré #1 vs Super Fusion (2026-04-02)
- Script : `compare_variants.py`, 200 runs chacun
- SYSTEM : tie (0.033 d'écart)
- RANDOM : Super Fusion +7.5% SAFE mult (×49.07 vs ×45.63)
- **Décision : revert vers Amélioré #1** — le gain était du bruit (excluded_bet_groups n'affecte pas le pool RANDOM qui est O15-only via filter_o15_random_all)

### Phase 8 — Système Portfolio Martingale (2026-04-03 / 04)

**Contexte :** L'utilisateur se lance en conditions réelles (premier ticket joué le 2026-04-03). Besoin de gérer plusieurs stratégies en parallèle avec des réserves communes.

#### Décisions et attributions

**Architecture "organes vitaux" [Convergence]**
- 4 stratégies : RANDOM SAFE (RS), RANDOM NORMALE (RN), SYSTEM SAFE (SS), SYSTEM NORMALE (SN)
- Réserves communes alimentées par les doublings SAFE
- Tirage des réserves sur crise (bankroll à zéro)

**Priorité d'accès aux réserves — 3 itérations :**

1. **RS en premier [Claude]** → testé, résultats désastreux. RS drainait les réserves avant que SS/SN puissent en profiter.

2. **SAFE en premier (RS > SS > SN > RN) [Utilisateur]** — "Je ne suis pas d'accord. Les safe doivent primer." → amélioration, mais pas optimal.

3. **RS en dernier (SS > SN > RN > RS) [Utilisateur corrige Claude]** — "J'avais oublié que le Random Safe c'est 3 défaites max. Donc en vrai il doit être dernier." → ML=3 = mises plus petites = moins besoin des réserves → priorité basse logique. **Décision finale retenue.**

**Règle 50% cap [Claude]** → testé 100 runs. Résultat paradoxal : le cap force des pauses qui empêchent les stratégies de profiter des bonnes séries → min floor pire (×88 vs ×116 sans cap). Rejeté. `MAX_DRAW_RATIO = 1.00` (pas de cap).

**600€ de réserves [Convergence]** — initialement 200€, puis 600€ pour couvrir crises simultanées avant le 1er doubling.

**Reset d'urgence [Claude]** — quand TOUTES les stratégies sont en pause et que même la moins gourmande a besoin de > 50% des réserves → elle prend 50% et repart à la baisse. Validé.

**Lancement décalé des stratégies [Utilisateur]** — "Ok. Mais j'ai pas d'argent, je vais commencer par le random safe." → insight clé : la fenêtre de vulnérabilité initiale (avant le 1er doubling SAFE) est dangereuse si toutes les stratégies démarrent ensemble. L'utilisateur a naturellement choisi RS seul au départ.

#### Résultats de référence portfolio (100 runs, 61 jours, 1000€ investis)

| Stat | Valeur |
|------|--------|
| Moyenne | ×218.07 (218 069€) |
| Min | ×11.86 |
| Max | ×613.34 |
| σ | 125.91 |

SN = moteur dominant (moy 129k€). RS = moins fiable (ruines possibles). SS = le plus stable.

#### Observations clés issues de cette phase

- **Multiplier ≠ euros** : ×312 sur 600€ semble mieux que ×222 sur 1000€ mais en euros c'est 186k vs 218k. [Utilisateur a identifié la confusion]
- **Bookmaker réel** : cotes ~14% inférieures au système (2.20 vs 2.56) → -23% sur le profit brut. Nécessite plus de données pour calibrer.
- **Tirage uniforme Top-K** : Bielefeld/Kaiserslautern (88%/70%) absents du ticket non pas parce que rejetés, mais car le tirage uniforme parmi les 10 meilleurs candidats a sélectionné un autre ticket. [Utilisateur a identifié l'incohérence apparente, Claude a expliqué le mécanisme]

#### Fichiers créés / modifiés
- `run_portfolio.py` — simulation 4 stratégies avec réserves communes + priorités + urgence
- `run_portfolio_detail.py` — affichage détaillé jour par jour
- `tools/audit/app.py` — tab4 "💰 Martingale" (dashboard + simulateur état réel)
- `data/optimizer/martingale_state.json` — état réel de la martingale (persisté)

---

### Phase 7 — Correctif filtre RANDOM pool (2026-04-02)
- **Problème identifié** : `filter_effective_random_pool` en mode TEAM prenait le minimum de TOUTES les équipes, y compris celles avec < 1 match. Une équipe avec 1 défaite (ex. Coritiba 0/1 = 0% WR) bloquait tous les picks d'un match, même avec d'autres équipes fiables.
- **Correction appliquée** (`services/ticket_builder.py`) :
  - Mode TEAM : ne considère que les équipes avec ≥ `team_min_decided` matchs (6 par défaut)
  - Prend le **minimum** des équipes fiables uniquement
  - Si aucune équipe n'a assez de données → accepter (pas de données = pas de blocage)
- **Paramètre** : `team_min_decided=6` (déjà dans Amélioré #1, maintenant effectif dans le filtre)
- **Résultats validés** (100 runs, 61 jours, compare_pool_filter_2026-04-02_100runs.txt) :

| Mode | Ancien filtre (min=1) | Nouveau filtre (min=6) | Gain |
|------|-----------------------|------------------------|------|
| SYSTEM SAFE | ×31.89, 0% ruine | ×31.20, 0% ruine | −2.2% (stable) |
| RANDOM SAFE | ×44.29, 0% ruine | **×67.48**, 0% ruine | **+52%** |

- **Champion actuel : Amélioré #1 avec team_min_decided=6 (filtre corrigé)**
- Stratégie recommandée : **RANDOM SAFE** en principal (×67.48 moy, 0% ruine), SYSTEM SAFE en parallèle, NORMALE pour fun mensuel

---

## OBSERVATIONS IMPORTANTES

### Pourquoi le win rate ne suffit pas
Le profit en martingale SAFE dépend avant tout du **nombre de doublings**, pas du win rate brut.
L'Amélioré a un WR plus bas que #2 et #3, mais génère plus de doublings (8.5 vs 7.0)
grâce à de meilleures cotes et plus de volume de tickets.

### Points forts de chaque profil (à exploiter)
- **Profil #2 RANDOM** : WR 89.1%, série max 36 victoires — extraordinaire en sélectivité
  - Paramètres distinctifs : `topk_size=3`, `system_select_source=TEAM`, `random_build_source=LEAGUE`
- **Profil #3 SYSTEM** : WR 78.3%, 0% ruine — très stable
  - Paramètres distinctifs : `topk_size=5`, `league_ranking_mode=COMPOSITE`, `team_ranking_mode=CLASSIC`

### La ruine en martingale NORMALE est mathématiquement attendue
À 70-75% de WR avec max_losses=4, une série de 5 défaites consécutives est statistiquement
inévitable sur 60+ jours. La martingale SAFE résout ce problème en bankant les profits.

---

## PROCHAINES PISTES

### Ticket Builder — Tests en attente

- ~~**[BCEA Session 2]** Combinaisons `random_build_source` × `random_select_source`~~ → **REJETÉ** (2026-04-04, N=50 runs) — toutes variantes alternatives inférieures à TEAM/TEAM. Build LEAGUE néfaste pour RANDOM (-57% à -74%). TEAM/LEAGUE : signal brut +14.5% mais t=0.83σ non significatif. Baseline TEAM/TEAM confirmée définitivement. Ne pas retester avant changement majeur de dataset.
- ~~Tester `global_bet_min_winrate=0.5`~~ → **REJETÉ** (2026-04-04, BCEA Session 1, 100 runs) — SAFE SYSTEM -4.4%, WR -0.9 pts, NORM ruine +50%, pire série 6→10. Baseline 0.65 confirmée. Ne pas retester avant 6 mois ou changement majeur de dataset.
- Tester `system_build_source=TEAM` vs LEAGUE (finetune +1.249 à 20 runs, effacé à 100 runs → bruit probable)
- Tester d'autres championnats dans le pool RANDOM pour augmenter le volume

### Développement requis (sessions code)

**Session 3 — 2026-04-05 — RÉALISÉ :**

- ~~**Maestro log enrichi**~~ [Utilisateur, 2026-04-04] → **LIVRÉ Session 3**
  - Modifié : `services/ticket_builder.py` L.2879-2918
  - Log niveau 2 enrichi : résumé agrégé par raison de rejet (TEAM_LOW_SR×N, etc.) + détail pick par pick + liste picks acceptés avec poids
  - Aucune nouvelle logique métier — s'appuie sur `diag["REASONS"]` existant dans `_diagnose_pool()`

- ~~**Analyse contrefactuelle quotidienne**~~ [Fondateur, 2026-04-04] → **LIVRÉ Session 3 (v1)**
  - Créé : `tools/audit/counterfactual.py` — script autonome avec CLI (`--days N`, `--output`)
  - Panneau tab5 "Contrefactuel" dans `tools/audit/app.py`
  - Comparaison par cote totale du ticket joué vs. pool de candidats (cap 5000 combinaisons)
  - Limitation documentée : résultats réels des picks non joués indisponibles → v2 possible si archive enrichie

**Session 4 — 2026-04-05 — RÉALISÉ :**

- ~~**Contrefactuelle v2 avec résultats réels**~~ [Fondateur] → **LIVRÉ Session 4 — CORRIGÉ Session 5**
  - Session 4 : réécriture avec predictions.tsv col 9. **ERREUR** : cette colonne = `is_candidate` (qualité pick), pas résultat réel. Tous les picks jouables ayant is_candidate=1, le tool affichait 100% de combos gagnantes — sans signification.
  - Session 5 [Claude] : correction complète → v3 utilisant `results.tsv` (scores réels des matchs)

- ~~**Contrefactuelle v3 — résultats réels depuis results.tsv**~~ [Claude, Session 5] → **LIVRÉ 2026-04-05**
  - Source de vérité : `archive/analyse_YYYY-MM-DD/results.tsv` (FT score + HT score par match)
  - Évaluation réelle de chaque bet_key depuis le score : O15_FT = ft_h+ft_a≥2, HT05 = ht_h+ht_a≥1, etc.
  - Pool depuis `*_jouables.tsv` cross-référencé avec results.tsv par (home.lower(), away.lower())
  - Résultats réalistes : O15 jouables 60-80% en réalité (pas 100%), combos gagnantes 7-60%
  - Flags significatifs : CATASTROPHIQUE (2026-02-22 : 51.8% du pool gagnait, notre ticket LOSS)

- ~~**Panneau Streamlit contrefactuel amélioré**~~ [Fondateur] → **LIVRÉ Session 4**
  - tab5 `tools/audit/app.py` reécrit : filtre par flag, 5 métriques, coloration enrichie, statistiques avancées
  - Contrôle `min-odd` dans l'interface

- ~~**Lancement décalé des stratégies portfolio (start_delay)**~~ [Utilisateur] → **LIVRÉ Session 4**
  - `run_portfolio.py` : paramètre `start_delay=True/False`, méthode `is_ready()` sur `Strategy`
  - `python run_portfolio.py --start-delay` pour simuler démarrage progressif
  - Comportement par défaut inchangé (rétrocompatible)

**Pistes futures :**
- Tester `--start-delay` et comparer P25 vs baseline (session 5)
- Équipe d'optimisation portfolio : après lancement réel (2026-04-05)

### Portfolio Martingale
- ~~**Lancement décalé des stratégies**~~ [Utilisateur] → **LIVRÉ Session 4** — voir ci-dessus
- **Équipe d'optimisation** [Convergence, 2026-04-04] : grid search systématique sur les paramètres portfolio (ML par stratégie, répartition bankrolls/réserves, timing). Critère : maximiser P25 (plancher 1er quartile) sur 100+ runs. **Priorité : après lancement réel 2026-04-05.**

### Principe directeur [Utilisateur, 2026-04-04]
> "Plus y'a d'instruments de mesure, moins on avance à l'aveugle. Il faut en mettre partout. C'est là que les corrélations apparaîtront vraiment."

---

## OUTILS DISPONIBLES

| Fichier | Rôle |
|---------|------|
| `services/ticket_builder.py` | Cœur du système — construction des tickets |
| `services/match_analysis.py` | Analyse des matchs, seuils dynamiques |
| `compute_label_thresholds.py` | Calcule les seuils min par bet_key |
| `finetune_profile.py` | Fine-tuning one-at-a-time d'un profil |
| `compare_variants.py` | Comparaison tête-à-tête de 2 variantes |
| `compare_all_profiles.py` | Comparaison de 5 profils en parallèle |
| `data/optimizer/optimizer_top_profiles.json` | Top profils de l'optimizer |
| `data/optimizer/builder_config_2026-03-31_score193.json` | Profil "Actuel" avant optimizer |
| `data/min_level_by_bet.json` | Seuils dynamiques calculés |

### Phase 9 — BCEA Session 1 (2026-04-04)

**Contexte :** Première réunion du Bureau Central d'Excellence Analytique. Agents impliqués : Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid.

#### global_bet_min_winrate = 0.50 — REJETÉ

| Métrique | Baseline 0.65 | Variante 0.50 | Delta |
|----------|---------------|---------------|-------|
| SAFE ×mult SYSTEM | ×29.25 | ×28.02 | **-4.4%** |
| SAFE ×mult RANDOM | ×65.07 | ×58.83 | -9.6% |
| Win rate SYSTEM | 68.2% | 67.3% | -0.9 pts |
| NORM ruine SYSTEM | 10% | 15% | +50% |
| Pire série SYSTEM | 6 | 10 | +4 |
| Score composite SYSTEM | 14.829 | 14.212 | -4.2% |

*N=100 runs, compare_variants.py, 2026-04-04*

**Verdict Validateur Froid : REJETÉ.** Dégradation sur toutes les métriques SYSTEM, qui est le seul canal causalement affecté par le paramètre. Baseline 0.65 confirmée définitivement.

#### Acquis structurels permanents (BCEA Session 1)

1. **Taux de faux positifs finetune (50-70%) [Innovateur + Sceptique, Convergence]** — Tester k=5 valeurs simultanément sur 20 runs à forte variance génère mécaniquement un biais de sélection. L'espérance du maximum parmi 5 variables est μ + 1.16σ même si aucune valeur n'est réellement supérieure. Le delta +1.459 de cette session est l'exemple de référence.

2. **global_bet_min_winrate n'affecte pas RANDOM [Innovateur — vérification code]** — `_random_accept_pick()` utilise `league_bet_min_winrate` (0.60), pas `global_bet_min_winrate`. Tout écart RANDOM lors d'un test de ce paramètre = variance pure, pas signal causal.

3. **Filtre Bonferroni obligatoire pour les sorties finetune [Validateur Froid]** — Avec k=5 et notre variance, exiger delta > +2.5 à 20 runs pour considérer un signal candidat. Le delta +1.459 de Session 1 n'aurait pas passé ce filtre — économie de 100 runs évitable.

4. **Protocole finetune révisé [Validateur Froid]** — Tout résultat finetune sur N ≤ 30 runs = SIGNAL CANDIDAT uniquement. Ne peut pas modifier le profil champion sans test complémentaire à ≥ 100 runs.

---

### Phase 10 — BCEA Session 2 (2026-04-04)

**Contexte :** Session 2 du Bureau Central d'Excellence Analytique. Sujet : observation Fondateur sur l'efficacité de LEAGUE-first pour RANDOM et les ligues prolifiques en buts.

#### random_build_source × random_select_source — REJETÉ (toutes variantes)

*Test exécuté le 2026-04-05 — N=50 runs — Verdict Validateur Froid : 2026-04-04*

**Hypothèse testée :** les combinaisons build/select source RANDOM impactent significativement SAFE RANDOM ×mult. Le test de `random_build_source` en Phase 5 précédait la correction +52% du filtre pool (Phase 7) et était potentiellement invalide.

**Résultats (RANDOM SAFE ×mult — métrique principale) :**
| Variante | build | select | SAFE ×mult | σ | Ruine | Delta | t-stat | Verdict |
|----------|-------|--------|-----------|---|-------|-------|--------|---------|
| TEAM/TEAM | TEAM | TEAM | ×56.69 | 40.84 | 0% | baseline | — | **CHAMPION CONFIRMÉ** |
| TEAM/LEAGUE | TEAM | LEAGUE | ×64.91 | 57.20 | 0% | +14.5% | **0.83σ** | **REJETÉ** — non significatif |
| LEAGUE/TEAM | LEAGUE | TEAM | ×24.27 | 23.64 | 8% | -57.2% | — | **REJETÉ** — dégradation nette |
| LEAGUE/LEAGUE | LEAGUE | LEAGUE | ×14.68 | 20.42 | 32% | -74.1% | — | **REJETÉ** — catastrophique |

**Conclusion :**
- TEAM/TEAM reste le profil champion. Aucune variante ne passe le seuil Bonferroni k=4.
- TEAM/LEAGUE : delta brut +14.5% mais t=0.83σ (SE≈9.94). Non significatif sur 50 runs. La haute variance (σ=57.20) indique une distribution à queue lourde — instable.
- **Acquis définitif : build_source LEAGUE est néfaste pour RANDOM.** LEAGUE build dégrade RANDOM quel que soit le select_source. Le filtre TEAM avec team_min_decided=6 (Phase 7) est confirmé optimal.
- Le WR inversé de TEAM/LEAGUE (60.6% WR mais ×mult plus haut) = artefact de variance, pas signal réel.

#### Découverte code permanente (BCEA Session 2)

**Incohérence TEAM build entre filtre pool et gate construction [Innovateur — vérification code] :**
- `filter_effective_random_pool()` filtre TEAM avec `dec >= team_min_decided` (6 min)
- `_random_accept_pick()` filtre TEAM avec `dec > 0` (1 match minimum)
- Impact pratique limité (pool pré-filtré), mais asymétrie documentée pour future maintenance.

#### Acquis structurels permanents (BCEA Session 2)

5. **Bonferroni ajusté k=4 [Validateur Froid, Session 2]** — Avec 4 variantes simultanées, valeur attendue du maximum = μ + 1.03σ sans signal réel. Seuil adapté : delta > +3% SAFE ×mult requis sur 50 runs pour signal valide. (vs delta > +2.5 pour k=5 en Session 1)

6. **Confounding dans les comparaisons multi-profils [Sceptique, Session 2]** — Les profils de l'optimizer diffèrent sur plusieurs paramètres simultanément. On ne peut pas attribuer une performance à un paramètre isolé. Toute analyse de type "Profil #2 a X donc X explique Y" = confounding. Test isolé obligatoire.

7. **Analyse contrefactuelle = outil de session code, pas de session test [Réducteur, Session 2]** — Distinguer systématiquement les items testables avec compare_variants.py des items requérant développement. Deux types de sessions BCEA à prévoir : sessions test (compare_variants) et sessions code (développement outils).

### Phase 11 — Session 5 (2026-04-05) — Correction contrefactuelle

**Erreur critique détectée et corrigée :**

La colonne index 9 de `predictions.tsv` est `is_candidate` (1 si le pick passe le filtre qualité, 0 sinon), **pas** le résultat réel du pari. Cette confusion avait produit un taux de "victoire" de 100% pour les picks jouables (tous is_candidate=1 par définition), rendant l'analyse sans signification.

**Correction [Claude] :** Réécriture en v3 utilisant `archive/analyse_YYYY-MM-DD/results.tsv` :
- Scores réels FT et HT de chaque match
- Évaluation directe : O15_FT → ft_h+ft_a≥2, HT05 → ht_h+ht_a≥1, HT1X_HOME → ht_h≥1, etc.
- Cross-référencement jouables × results par (home.lower(), away.lower())

**Premiers résultats réels (5 jours avec results.tsv disponible) :**

| Date | O15 jouables réel | Combos gagnantes | Flag ticket principal |
|------|-------------------|------------------|----------------------|
| 2026-03-09 | 60% (3/5) | 7.1% (5/70) | MALCHANCEUX |
| 2026-03-08 | 71% (35/49) | 34.1% (682/2000) | OPTIMAL ✓ |
| 2026-03-01 | 80% (41/51) | 31.2% (625/2000) | MALCHANCEUX / OPTIMAL |
| 2026-02-22 | 76% (39/51) | 51.8% (1035/2000) | CATASTROPHIQUE ⚠️ |
| 2026-02-21 | 79% (53/67) | 59.4% (1188/2000) | CATASTROPHIQUE / OPTIMAL |

**Acquis : predictions.tsv col 9 ≠ résultat réel [Utilisateur corrige Claude (indirect) + Claude]** — Ne jamais interpréter cette colonne comme issue d'un match. Source de vérité pour résultats = results.tsv.

**Limitation persistante :** La plupart des archives avant mars 2026 n'ont pas de `results.tsv` — ces jours sont exclus de l'analyse.

---

### Phase 12 — BCEA Session 6 (2026-04-05)

**Contexte :** Tests d'exclusion de familles de paris du SYSTEM via `excluded_bet_groups`. N=50 runs/variante, --jobs 6, 61 jours d'archive.

#### Variantes testées

| Variante | `excluded_bet_groups` | SYSTEM conserve |
|----------|-----------------------|-----------------|
| Baseline | ∅ | HT05 + HT1X + TEAM_SCORE + TEAM_WIN + O15 |
| Test A | `["HT05", "HT1X"]` | O15 + TEAM_SCORE + TEAM_WIN |
| Test B | `["HT05", "HT1X", "TEAM_WIN"]` | O15 + TEAM_SCORE uniquement |

#### Résultats SYSTEM

| Variante | WR | SAFE ×mult | Doublings | NORM ruine | Tickets/run | Delta SAFE |
|----------|----|-----------|-----------|------------|-------------|------------|
| Baseline | 68.0% | **×27.87** | 8.1 | 18% | 83.2 | — |
| Test A | 66.5% | ×14.61 | 5.6 | 28% | 71.0 | **−47.6%** |
| Test B | 66.9% | ×14.16 | 5.6 | 36% | 71.1 | **−49.2%** |

#### Résultats RANDOM (variance pure — `excluded_bet_groups` n'affecte pas le chemin RANDOM)

| Variante | WR | SAFE ×mult | σ_safe | NORM ruine | Delta | t-stat |
|----------|----|-----------|--------|------------|-------|--------|
| Baseline | 71.8% | ×56.09 | 40.55 | 16% | — | — |
| Test A | 70.7% | ×54.89 | 35.80 | 18% | −2.1% | ~0.15σ |
| Test B | 71.4% | ×61.84 | 40.00 | 14% | +10.2% | ~1.02σ |

#### Verdicts

- **Test A : REJETÉ** — SAFE SYSTEM −47.6%, doublings −31%, ruine +56%. Signal massif négatif convergent sur 4 métriques.
- **Test B : REJETÉ** — SAFE SYSTEM −49.2%, ruine doublée (36% vs 18%). L'exclusion additionnelle de TEAM_WIN ne fait qu'aggraver.
- **Profil champion inchangé : `excluded_bet_groups = ∅`.**

#### Acquis structurels permanents (BCEA Session 6)

8. **HT05 et HT1X sont des contributeurs positifs nets au SYSTEM [Réducteur + Validateur Froid, Session 6]** — Leur exclusion conjointe dégrade SAFE ×mult de −47.6%, doublings de −31%, et hausse la ruine de +56%. Toutes les métriques convergent. La dégradation excède ce qu'explique seule la perte de volume (−14.4% tickets → −31% doublings) : HT05/HT1X sont sur-représentés dans les tickets gagnants, avec WR supérieur à la moyenne du pool filtré.

9. **TEAM_WIN est un stabilisateur de séquences, pas un générateur de volume [Innovateur, Session 6]** — Son exclusion (Test A → Test B) laisse le volume et le SAFE ×mult quasi-stables, mais aggrave la ruine (28%→36%). Il joue un rôle d'équilibreur en creux de séquence — victoires faciles qui brisent les séries défavorables.

10. **`excluded_bet_groups = ∅` est confirmé optimal — question fermée [Validateur Froid, Session 6]** — Exploré en Phase 5 (Super Fusion rejeté), Phase 6 (revert Amélioré #1), et Session 6 BCEA. Les exclusions de familles dégradent systématiquement le SYSTEM dans ce profil. Ne pas rouvrir sans signal positif fort (δ > +3%, N ≥ 50 runs).

#### Backlog ouvert par Session 6 (pistes secondaires, pas urgentes)

- Test isolé `excluded = ["HT05"]` seul (isoler contribution HT05 vs HT1X) — compare_variants.py
- Test isolé `excluded = ["HT1X"]` seul — compare_variants.py
- Seuillage par niveau de confiance HT05/HT1X (FORT PLUS uniquement) — modification ticket_builder.py

---

### Phase 13 — BCEA Sessions 7, 8, 9 (2026-04-05)

#### Session 7 — Test C : league_bet_min_winrate=0.65 SYSTEM / 0.60 RANDOM — REJETÉ

**Hypothèse :** reverting `league_bet_min_winrate` de 0.60 → 0.65 pour SYSTEM uniquement (avec `random_league_bet_min_winrate=0.60` pour ancrer RANDOM) améliorerait SYSTEM sans dégrader RANDOM.

| Métrique | Baseline (0.60) | Test C (0.65 SYS / 0.60 RND) | Delta |
|---|---|---|---|
| SYSTEM SAFE ×mult | ×27.04 | ×25.47 | **−5.8%** (1.2σ) |
| SYSTEM doublings | 7.9 | 7.7 | −0.2 |
| RANDOM SAFE ×mult | ×46.19 | ×29.24 | **−36.7%** |
| RANDOM tickets/run | 72.4 | 69.1 | −3.3 |

**Verdict : REJETÉ.** Les deux chemins sont dégradés. La hausse de `league_bet_min_winrate` à 0.65 réduit le pool de 4.6% sur RANDOM malgré `random_league_bet_min_winrate=0.60` — suggérant que d'autres filtres en amont lisent `league_bet_min_winrate`. Baseline 0.60 confirmée.

---

#### Session 8 — Test D : league_ranking_mode=COMPOSITE — REJETÉ

**Hypothèse :** basculer `league_ranking_mode` de CLASSIC → COMPOSITE (0.70×base_rate + 0.30×goals_score) améliorerait la qualité du pool SYSTEM (RANDOM non affecté : utilise TEAM/TEAM uniquement).

| Métrique | Baseline (CLASSIC) | Test D (COMPOSITE 70/30) | Delta |
|---|---|---|---|
| SYSTEM SAFE ×mult | ×28.98 | ×28.47 | **−1.8%** (0.54σ) |
| SYSTEM ruine NORMALE | 14% | 12% | −2% |
| SYSTEM doublings | 8.1 | 8.0 | −0.1 |

**Verdict : REJETÉ.** Signal quasi nul (0.54σ). `league_ranking_mode=CLASSIC` confirmé.

---

#### Session 9 — Analyse corrélation composite (pré-test ratio 70/30) — DÉPRIORITISÉ

**Question posée :** Le ratio `COMPOSITE_BASE_WEIGHT=0.70 / COMPOSITE_GOALS_WEIGHT=0.30` est-il sous-optimal ? Vaut-il le coup de tester 60/40 ou 50/50 ?

**Étape préalable (Innovateur) :** calculer corrélation Pearson entre `goals_score` et `base_rate` sur `triskele_composite_team_x_bet.tsv`.

**Résultats :**

| Scope | r Pearson |
|---|---|
| Global (n=4170) | **0.8738** |
| HT05 | 0.9349 |
| O15_FT | 0.9562 |
| TEAM1_WIN_FT | 0.9435 |
| TEAM2_WIN_FT | 0.9309 |
| HT1X_HOME | 0.8925 |
| O25_FT | **0.0000** ← anomalie |

**Verdict (Validateur Froid) : DÉPRIORITISÉ.** Corrélation globale r=0.8738 ≥ 0.85 → `goals_score` et `base_rate` sont quasi-redondants pour la plupart des paris. Changer le ratio produira un signal minimal. Anomalie O25_FT (r=0.0000) documentée mais non exploitée — O25_FT n'est pas un pari dominant dans le système actuel.

**Acquis :** Le ratio 70/30 n'est pas une priorité d'optimisation. Les deux métriques contiennent essentiellement la même information prédictive.

---

---

### Phase 14 — BCEA Sessions 14 & 14b (2026-04-09)

#### Session 14 — Analyse de sensibilité aux décotes bookmaker (88 jours)

**Contexte :** Lancement réel depuis le 2026-04-05. Série de défaites SYSTEM (8 pertes consécutives en LEAGUE/HYBRID). Question : le système est-il profitable malgré la décote bookmaker ?

**Script créé :** `bcea_session14_sensitivity.py` → résultats dans `data/optimizer/bcea_session14_sensitivity.txt`

**Méthode :** Sur 88 jours d'archive, calculer le P&L réel à différentes décotes (5%, 10%, 15%, 20%) par type de pari et par tranche de cote système.

**Résultats clés :**

| Segment | WR | Avg cote sys | WR×C | Décote BE |
|---|---|---|---|---|
| O15_FT | ~70% | ~2.10 | ~1.47 | ≥32% |
| O25_FT | ~57% | ~1.73 | ~0.99 | **négatif (jamais rentable)** |
| HT05 | ~70% | ~1.60 | ~1.12 | ~10% |
| Cote sys ≥1.80 (tous types) | — | — | >1 | **≤10.8%** ← seul segment rentable à Pinnacle |

**Acquis structurels (Session 14) :**

- **WR×C < 1 pour O25_FT [Validateur Froid]** : quelle que soit la décote, O25_FT ne génère jamais d'EV positif. Structurellement non rentable dans ce profil.
- **Pinnacle viable pour cote sys ≥1.80** : marge Pinnacle ≈2% < 10.8% breakeven. Seule fenêtre actionnable identifiée.
- **Formule breakeven décote** : `(1 - 1/(WR × avg_cote_sys)) × 100%`

---

#### Session 14b — Analyse croisée type×confiance (88 jours)

**Script créé :** `bcea_session14b_analysis.py` → résultats dans `data/optimizer/bcea_session14b_analysis.txt`

**Analyse A — O25_FT par niveau de confiance :**

| Confiance | Picks | WR | Avg cote | WR×C | Verdict |
|---|---|---|---|---|---|
| MEGA EXPLOSION | ~340 | **57.4%** | 1.730 | **0.994** | JAMAIS rentable |
| FORT PLUS | — | <60% | — | <1 | idem |

**O25_FT est confirmé non rentable quel que soit le niveau de confiance.** [Validateur Froid]

**Analyse B — Picks ≥1.80 par confiance :**
- FORT a cote moy 4.077 (skewé par quelques valeurs extrêmes) — EV trompeuse

**Analyse C — Croisement type×confiance (top WR×C) :**

| Segment | Picks | WR | Avg cote | WR×C | Décote BE |
|---|---|---|---|---|---|
| **O15_FT × MOYEN PLUS** | ~80 | **80%** | ~1.61 | **1.29** | **6.8%** ← PINNACLE VIABLE |
| HT05 × FORT PLUS | — | ~73% | ~1.55 | ~1.13 | ~10% |

**Acquis (Session 14b) :**
- **O15_FT × MOYEN PLUS = segment le plus actionnable** à Pinnacle (marge 2% < seuil 6.8%). [Utilisateur + Convergence]
- Filtrer sur WR×C > 1 est nécessaire mais pas suffisant — vérifier que la décote réelle < décote BE.

---

### Phase 15 — Changement SYSTEM TEAM/TEAM + Portfolio 200 runs (2026-04-09)

#### Découverte TEAM/TEAM [Utilisateur]

**Contexte :** L'utilisateur observe que la série de 8 défaites (4-9 avril) est anormale. Il soulève l'hypothèse que `system_build_source=LEAGUE` est problématique et propose de tester TEAM/TEAM.

**Script créé :** `bcea_backtest_team_team.py` — compare tickets réels joués vs simulation TEAM/TEAM sur 4-9 avril.

**Résultats sur la période de crise :**

| Mode | Wins | Losses | Win% |
|---|---|---|---|
| RÉEL (LEAGUE/HYBRID) | 1 | 11 | **8%** |
| SIMULÉ (TEAM/TEAM) | 9 | 3 | **75%** |

**La série de défaites aurait été effacée avec TEAM/TEAM.** [Utilisateur avait raison]

#### Backtest configurations SYSTEM (88 jours, 7€/ticket) [Utilisateur]

**Script créé :** `bcea_backtest_configs.py` — teste 9 configurations (min_odd × structure legs).

| Configuration | Tickets | Win% | P&L | ROI |
|---|---|---|---|---|
| ACTUEL (LEAGUE/HYBRID ≥1.15 3-4L) | 137 | 69% | +670€ | 74.2% |
| **TEAM/TEAM ≥1.15 3-4 legs** | **137** | **73%** | **+741€** | **82.7%** ← GAGNANT |
| TEAM/TEAM ≥1.15 3 legs forcé | 138 | 63% | +524€ | 58.1% |
| TEAM/TEAM ≥1.20 3-4 legs | 133 | 69% | +663€ | 76.4% |
| TEAM/TEAM ≥1.30 3-4 legs | 98 | 71% | +588€ | 90.4% |

**Acquis (Phase 15 — builder) :**
- **Forcer 3 legs = toujours moins bon** : −6 à −8pts de WR vs 3-4 legs libres. Contre-intuitif mais confirmé sur 88 jours.
- **Monter le min_odd réduit le volume sans améliorer le WR** → TEAM/TEAM ≥1.15 reste optimal.
- **Changement appliqué en production** : `SYSTEM_BUILD_SOURCE = "TEAM"`, `SYSTEM_SELECT_SOURCE = "TEAM"` dans `services/ticket_builder.py`.
- **JSON mis à jour** : `data/optimizer/optimizer_top_profiles.json` — profil #1 aligné TEAM/TEAM.

#### Portfolio 200 runs (ML: RS=3, RN=4, SS=4, SN=4 — réserves 6514€) [Convergence]

**Config :** 4 stratégies × 100€ bankroll + 6514€ réserves communes = 6914€ total. N=200 runs, 88 jours.

| Stat | Valeur |
|---|---|
| **Moyenne** | **3 631 931€ (×525)** |
| Min (run 66) | 11 818€ (×1.71) |
| Max (run 45) | 8 749 483€ (×1265) |
| σ | ×242 |

| Stratégie | Moyenne | Max |
|---|---|---|
| RANDOM SAFE (ML=3) | 253 182€ | 559 371€ |
| RANDOM NORMALE (ML=4) | 293 900€ | 765 950€ |
| SYSTEM SAFE (ML=4) | 286 809€ | 768 823€ |
| **SYSTEM NORMALE (ML=4)** | **1 414 747€** | **4 989 115€** |

**SYSTEM NORMALE = moteur dominant** (~39% du capital moyen). La variance extrême (σ=242) est inhérente à la Martingale NORMALE ML=4.

**Piste ouverte :** Test ML=3 universel (toutes stratégies à ML=3) pour mesurer gain de stabilité vs perte de rendement. En cours.

---

*Dernière mise à jour : 2026-04-09 (Sessions 14, 14b — sensibilité décote, croisement type×confiance ; Phase 15 — TEAM/TEAM confirmé, portfolio 200 runs ×525 moyen)*
*Profil actif dans ticket_builder.py : Amélioré #1 + TEAM/TEAM (system_build=TEAM, system_select=TEAM)*
