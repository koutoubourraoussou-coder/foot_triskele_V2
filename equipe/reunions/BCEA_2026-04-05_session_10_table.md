# TABLE DE RÉUNION — Session 10 — 2026-04-05
*Document partagé — tous les agents lisent tout avant de parler*

---

## CONTEXTE DE SÉANCE

**Date :** 2026-04-05
**Sujet :** SYSTEM dans le portfolio — faut-il le virer ou revoir la structure des réserves ?
**Agents impliqués :** Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid

---

## OBSERVATION FONDATEUR (soumise comme faits bruts)

> "Je viens d'enchaîner 6 défaites consécutives avec le SYSTEM aujourd'hui — premier jour de lancement réel. J'hésite à virer le SYSTEM du portfolio. Ou alors il faudrait repenser le portfolio pour qu'il crée d'immenses réserves avant d'avancer. Je ne sais pas encore."

**Règle de soumission :** Faits bruts. Les agents raisonnent librement.

---

## DONNÉES TECHNIQUES DISPONIBLES

### Structure actuelle du portfolio (run_portfolio.py)

| Stratégie | Bankroll active | max_losses | denom | Priorité réserves |
|-----------|----------------|-----------|-------|-------------------|
| RANDOM SAFE (RS) | 100€ | 3 | 7 | 4 (dernière) |
| RANDOM NORMALE (RN) | 100€ | 4 | 15 | 3 |
| SYSTEM SAFE (SS) | 100€ | 4 | 15 | 1 (première) |
| SYSTEM NORMALE (SN) | 100€ | 4 | 15 | 2 |
| **Réserves communes** | **600€** | — | — | — |
| **Total investi** | **1000€** | — | — | — |

### Règles de protection
- Cap 50% : une stratégie ne peut tirer que ≤ 50% des réserves → PAUSE sinon
- Reset d'urgence : si toutes en pause → la moins gourmande prend 50% et repart à la baisse
- Priorité SS > SN > RN > RS pour l'accès aux réserves

### Résultats Monte Carlo de référence (100 runs, 61 jours)

**SYSTEM SAFE (isolé, compare_variants.py) :**
| Métrique | Valeur |
|---|---|
| SAFE ×mult | moy=×28.98, min=×16.08, max=×38.16, σ=4.02 |
| Doublings/run | moy=8.1, min=7, max=9 |
| Pire série L | moy=3.1, **max_absolu=6** |
| Ruine SAFE | **0%** |
| Ruine NORMALE | 14% |

**RANDOM SAFE (isolé) :**
| Métrique | Valeur |
|---|---|
| SAFE ×mult | moy=×53.51, min=×2.22, max=×173.77, σ=36.87 |
| Doublings/run | moy=7.4, min=2, max=8 |
| Pire série L | moy=3.1, **max_absolu=6** |
| Ruine SAFE | **0%** |
| Ruine NORMALE | 16% |

**Portfolio complet (run_portfolio.py — 100 runs) :**
| Stat | Valeur |
|---|---|
| Moyenne | ×218 (218 069€) |
| Min | ×11.86 |
| Max | ×613.34 |
| σ | 125.91 |

### Ce que signifient 6 défaites consécutives en pratique

Avec `max_losses=4` (denom=15) en martingale SAFE :
- Après 4 pertes → bankroll active ≈ 0€ → tirage sur réserves communes
- Pertes 5 et 6 → tirage réserves × 2
- **La SAFE ne ruine pas** (0% sur 100 runs) mais elle vide les réserves communes
- La NORMALE ruine après 5 pertes (5e perte = bankroll 0 sans recours)

### Pire série L dans nos données (61 jours d'archive)
- SYSTEM : max_absolu = **6** (vu une fois sur 50 runs en Session 8)
- RANDOM : max_absolu = **6** (vu une fois aussi)
- Les deux strategies ont la même vulnérabilité aux séries longues

---

## QUESTIONS POSÉES À LA TABLE

1. **Faut-il virer SYSTEM du portfolio ?** Arguments pour et contre.
2. **Faut-il restructurer les réserves** — augmenter RESERVES_INIT avant de lancer SYSTEM ?
3. **Start-delay** — démarrer RS seul, attendre un doubling avant de lancer SS/SN — répond-il au problème ?
4. **max_losses=5 pour SYSTEM** — absorber les séries de 6 sans tirer sur les réserves — viable ?
