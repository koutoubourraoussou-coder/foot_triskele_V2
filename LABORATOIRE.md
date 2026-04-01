# LABORATOIRE TRISKÈLE V2
## Journal d'évolution du Ticket Builder

---

## PROFIL CHAMPION ACTUEL — Amélioré #1
*Appliqué dans `services/ticket_builder.py` le 2026-04-01*

Ce profil est la version optimisée du meilleur profil sorti de l'optimizer (rank_score=220.47),
enrichi de 4 améliorations confirmées par fine-tuning et validation Monte Carlo (200 runs, 61 jours).

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

## RÉSULTATS DE RÉFÉRENCE — Monte Carlo 200 runs, 61 jours (2026-04-01)

### MODE SYSTEM — du meilleur au moins bon

| # | Profil | Tickets | Win rate | Pire L (moy/max) | Meill. V (moy/max) | NORM ×mult | NORM ruine | SAFE ×mult | SAFE ruine | Doublings |
|---|--------|---------|----------|------------------|---------------------|------------|------------|------------|------------|-----------|
| 1 | **Amélioré #1** | 85.8 | 68.6% | 3.0 / 7 | 8.4 / 17 | ×782 | 14% | **×31.09** | **0%** | 8.5 |
| 2 | Profil #3 | 71.4 | 78.3% | 2.7 / 4 | 13.1 / 18 | ×307 | 13% | ×22.04 | 0% | 7.0 |
| 3 | Profil #1 | 84.9 | 72.4% | 3.4 / 6 | 10.8 / 22 | ×571 | 42% | ×21.23 | 32% | 5.9 |
| 4 | Profil #2 | 66.9 | 76.8% | 2.2 / 4 | 12.4 / 20 | ×216 | ~0% | ×20.13 | 0% | 6.7 |
| 5 | Actuel | 84.6 | 58.6% | 5.0 / 12 | 7.8 / 13 | ×69 | 72% | ×14.81 | 15% | 5.1 |

### MODE RANDOM — du meilleur au moins bon

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

## PROCHAINE ÉTAPE — Profil Super Fusion

Objectif : partir de l'Amélioré #1 et tester les paramètres distinctifs de #2 et #3.

Paramètres candidats à tester :

| Paramètre | Amélioré #1 | À tester | Source |
|-----------|-------------|----------|--------|
| `topk_size` | 10 | 3, 5 | #2, #3 |
| `system_select_source` | HYBRID | TEAM | #2, #3 |
| `random_build_source` | TEAM | LEAGUE | #2 |
| `league_ranking_mode` | CLASSIC | COMPOSITE | #3 |
| `team_ranking_mode` | COMPOSITE | CLASSIC | #3 |
| `global_bet_min_winrate` | 0.65 | 0.70 | #3 |
| `excluded_bet_groups` | ∅ | HT05 | #2 |
| `weight_min` | 1.0 | 1.2 | #2 |

Commande à lancer :
```
python -u finetune_profile.py --param topk_size system_select_source random_build_source league_ranking_mode team_ranking_mode global_bet_min_winrate excluded_bet_groups weight_min --runs 20 --jobs 6
```

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

*Dernière mise à jour : 2026-04-01*
*Profil actif dans ticket_builder.py : Amélioré #1*
