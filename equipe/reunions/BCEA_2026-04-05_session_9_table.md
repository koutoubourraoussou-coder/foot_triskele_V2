# TABLE DE RÉUNION — Session 9 — 2026-04-05
*Document partagé — tous les agents lisent tout avant de parler*

---

## CONTEXTE DE SÉANCE

**Date :** 2026-04-05
**Sujet :** Poids composite scores — faut-il changer le ratio 70/30 ?
**Agents impliqués :** Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid

---

## OBSERVATION FONDATEUR (soumise comme faits bruts)

> "Le composite score est actuellement calculé comme `0.70 × base_rate + 0.30 × goals_score`. Ce ratio n'a jamais été optimisé — il a été choisi initialement. Les fichiers COMPOSITE sont utilisés par `team_ranking_mode=COMPOSITE` (champion actuel). Le Fondateur pense qu'il vaut le coup de fouiller : peut-être que le goals_score mérite plus de poids. Il propose de tester 60/40 puis 50/50 pour voir si ça améliore le système."

**Règle de soumission :** Cette observation est soumise comme faits bruts. Les agents raisonnent librement.

---

## DONNÉES TECHNIQUES DISPONIBLES POUR LA SÉANCE

### Résultat Test D — league_ranking_mode CLASSIC vs COMPOSITE (Session 8, N=50 runs, 2026-04-05)

| Métrique | Baseline (CLASSIC) | Test D (COMPOSITE 70/30) | Delta |
|---|---|---|---|
| SYSTEM SAFE ×mult | ×28.98 | ×28.47 | **-1.8%** (0.54σ) |
| SYSTEM WR | 66.8% | 67.3% | +0.5% |
| SYSTEM ruine NORMALE | 14% | 12% | -2% |
| SYSTEM doublings | 8.1 | 8.0 | -0.1 |

> Verdict : Test D REJETÉ. `league_ranking_mode=CLASSIC` confirmé. Le COMPOSITE ligue 70/30 n'apporte pas de signal mesurable.

### Rappel — Composite score actuel

```python
# post_analysis_core.py L.190-191
COMPOSITE_BASE_WEIGHT = 0.70   # poids du win rate brut (base_rate)
COMPOSITE_GOALS_WEIGHT = 0.30  # poids du score buts (goals_score)
```

- `base_rate` = win rate historique de la ligue/équipe sur ce type de pari
- `goals_score` = score normalisé basé sur les moyennes de buts (FT + HT), taux O05/O15/O25, home/away/BTTS

### Profil champion actuel
- `league_ranking_mode = "CLASSIC"` (COMPOSITE rejeté en Session 8)
- `team_ranking_mode = "COMPOSITE"` (70/30, jamais modifié depuis l'optimizer)

### Coût technique du test
Changer le ratio nécessite :
1. Modifier `COMPOSITE_BASE_WEIGHT` / `COMPOSITE_GOALS_WEIGHT` dans `post_analysis_core.py`
2. **Régénérer les fichiers TSV** (`data/rankings/triskele_composite_*.tsv`)
3. Lancer compare_variants avec `team_ranking_mode=COMPOSITE` (déjà le cas du champion)
4. **Note :** `league_ranking_mode=CLASSIC` → le test ne concerne que `team_ranking_mode`

---

## QUESTION POSÉE À LA TABLE

1. **Le 70/30 actuel est-il sous-optimal ?** Y a-t-il un mécanisme qui justifie de donner plus de poids au goals_score ?
2. **60/40 ou 50/50 — lequel tester en premier ?** Ou les deux simultanément ?
3. **La priorité est-elle justifiée** face au backlog (start-delay, optimisation portfolio) ?
