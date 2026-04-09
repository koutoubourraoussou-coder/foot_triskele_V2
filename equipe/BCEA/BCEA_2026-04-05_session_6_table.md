# BCEA Session 6 — Tableau des résultats
**Date :** 2026-04-05
**Sujet :** Impact de l'exclusion de familles de paris du SYSTEM (`excluded_bet_groups`)
**N :** 50 runs/variante — `--jobs 6` — 61 jours d'archive
**Seuil Bonferroni :** k=2 comparaisons simultanées → δ > +3% SAFE ×mult requis

---

## Paramètres des variantes

| Variante | `excluded_bet_groups` | SYSTEM conserve |
|----------|-----------------------|-----------------|
| Baseline | ∅ (aucun) | HT05 + HT1X + TEAM_SCORE + TEAM_WIN + O15 |
| Test A | `["HT05", "HT1X"]` | O15 + TEAM_SCORE + TEAM_WIN |
| Test B | `["HT05", "HT1X", "TEAM_WIN"]` | O15 + TEAM_SCORE uniquement |

---

## Résultats SYSTEM

| Variante | WR | SAFE ×mult | Doublings | NORM ruine | Tickets/run | Delta SAFE | Verdict |
|----------|----|-----------|-----------|------------|-------------|------------|---------|
| **Baseline** | 68.0% | **×27.87** | 8.1 | 18% | 83.2 | — | CHAMPION |
| Test A | 66.5% | ×14.61 | 5.6 | 28% | 71.0 | **-47.6%** | REJETÉ |
| Test B | 66.9% | ×14.16 | 5.6 | 36% | 71.1 | **-49.2%** | REJETÉ |

*Calculs delta : (14.61−27.87)/27.87 = −47.6% ; (14.16−27.87)/27.87 = −49.2%*

---

## Résultats RANDOM

| Variante | WR | SAFE ×mult | σ_safe | NORM ruine | Tickets/run | Delta SAFE | t-stat | Verdict |
|----------|----|-----------|--------|------------|-------------|------------|--------|---------|
| **Baseline** | 71.8% | **×56.09** | 40.55 | 16% | 72.6 | — | — | CHAMPION |
| Test A | 70.7% | ×54.89 | 35.80 | 18% | 72.3 | -2.1% | ~0.15σ | BRUIT |
| Test B | 71.4% | ×61.84 | 40.00 | 14% | 72.4 | +10.2% | ~1.02σ | BRUIT |

*SE RANDOM ≈ σ/√N ≈ 40/√50 ≈ 5.66. t(Test B) = (61.84−56.09)/5.66 ≈ 1.02σ < 2σ requis.*

---

## Note mécanique

- `excluded_bet_groups` n'affecte que le SYSTEM — le chemin RANDOM ne lit pas ce paramètre.
- Les variations RANDOM observées (±2 à ±10%) sont de la variance pure — aucun mécanisme causal.
- La perte de 12 tickets/run en SYSTEM (83.2→71.0) confirme que HT05 et HT1X contribuent activement au pool SYSTEM.
- Le RANDOM reste stable en volume (72.6→72.3→72.4) : confirmation que le paramètre est SYSTEM-only.

---

## Récapitulatif rapide

| Question | Réponse |
|----------|---------|
| HT05 + HT1X nuisent-ils au SYSTEM ? | **Non — leur exclusion dégrade SAFE ×mult de -48%** |
| TEAM_WIN est-il superflu ? | **Non — son exclusion aggrave encore la ruine (18%→36%)** |
| RANDOM est-il impacté ? | **Non — variance pure, aucun mécanisme** |
| Volume SYSTEM impacté ? | **Oui — -14.4% de tickets/run** |
