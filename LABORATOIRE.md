# LABORATOIRE TRISKÈLE V2
## Journal d'évolution du Ticket Builder

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

## PROCHAINES PISTES — Amélioré #1 + filtre corrigé

Le champion actuel est stabilisé. Pistes si on veut aller plus loin :
- Tester `global_bet_min_winrate=0.5` (finetune montre +1.459 mais signal à confirmer à 100 runs)
- Tester `system_build_source=TEAM` vs LEAGUE (finetune +1.249 à 20 runs, effacé à 100 runs → bruit probable)
- Tester d'autres championnats dans le pool RANDOM pour augmenter le volume

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

---

*Dernière mise à jour : 2026-04-02*
*Profil actif dans ticket_builder.py : Amélioré #1 + filtre corrigé (team_min_decided=6, min équipes fiables)*
