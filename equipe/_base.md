# Socle commun — Tous les agents BCEA

Ce document est lu par chaque agent avant ses instructions spécifiques.
Il contient le contexte projet et les règles partagées.

---

## Le projet : Triskèle V2

Triskèle V2 est un système de prédiction de matchs de football et de génération de tickets de paris.

### Pipeline principal
```
API Football → run_machine.py
    → main.py (analyse 6 paris/match)
    → ticket_builder.py (tickets SYSTEM + RANDOM)
    → post_analysis.py (verdicts WIN/LOSS, mise à jour rankings)
```

### Les 6 paris analysés
HT05, HT1X_HOME, TEAM1_SCORE_FT, TEAM2_SCORE_FT, O15_FT, O25_FT

### Le profil champion actuel : Amélioré #1
Déployé depuis 2026-04-02. Paramètres clés :
- system_select_source=HYBRID, hybrid_alpha=0.6
- random_build_source=TEAM, random_select_source=TEAM
- two_team_high=0.90, global_bet_min_winrate=0.65
- league_bet_min_winrate=0.60, league_bet_require_data=False
- team_min_decided=6, team_min_winrate=0.75
- topk_size=10, topk_uniform_draw=True (tirage UNIFORME parmi Top-10)
- target_odd=2.40, min_accept_odd=1.80

### Les données disponibles
- 61 jours de données (archive/analyse_YYYY-MM-DD/)
- data/rankings/ — scores composites 0.70×base_rate + 0.30×goals_score
- data/optimizer/ — résultats optimisations passées
- LABORATOIRE.md — historique complet des décisions avec attribution

### Outils d'optimisation
- finetune_profile.py — test one-at-a-time d'un paramètre
- compare_variants.py — comparaison 2 profils en Monte Carlo
- compare_all_profiles.py — comparaison 5 profils
- validate_profiles.py — validation sur 61 jours
- run_portfolio.py — simulation martingale 4 stratégies

### Portfolio martingale (état actuel)
- 4 stratégies : RS (ML=3), RN (ML=4), SS (ML=4), SN (ML=4)
- Réserves communes 600€, priorité SS>SN>RN>RS
- Résultats 100 runs : moy ×218, min ×11.86, max ×613.34, σ=125.91

---

## Règles partagées par tous les agents

### 1. Vérifier avant d'affirmer
Ne jamais présenter une hypothèse comme un fait.
Avant de dire "ce paramètre est arbitraire" ou "cela n'a pas été testé" → **vérifier dans LABORATOIRE.md ou dans le code**.

### 2. Lire LABORATOIRE.md en priorité
Ce fichier contient l'histoire des décisions, avec attribution (qui a eu l'idée, qui a corrigé qui).
Ne pas re-proposer ce qui a été testé et rejeté.

### 3. Chaque observation doit être actionnable
Format : Observation → Hypothèse → Test proposé → Métrique d'évaluation → Impact estimé.
Pas d'observations flottantes sans suite proposée.

### 4. L'archivage est obligatoire
Chaque résultat significatif doit être documenté.
La trace vaut autant que le résultat lui-même.

### 5. La culture du BCEA prime
Lire CULTURE.md. L'intégrer. Y revenir.

---

## Fichiers clés à connaître

| Fichier | Rôle |
|---------|------|
| LABORATOIRE.md | Mémoire du projet — lire en PREMIER |
| equipe/CULTURE.md | Identité et philosophie du BCEA |
| services/ticket_builder.py | Cœur du système (121KB) |
| services/match_analysis.py | Analyse des matchs (89KB) |
| services/post_analysis_core.py | Verdicts + rankings (117KB) |
| data/rankings/*.tsv | Scores composites ligue/équipe |
| data/optimizer/optimizer_top_profiles.json | Top profils connus |
| data/min_level_by_bet.json | Seuils candidature par pari |

---

*Ce socle est vivant. L'Agent Principal peut le mettre à jour à tout moment.*
