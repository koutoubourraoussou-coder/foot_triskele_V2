# TABLE — Session 12 — BCEA — 2026-04-08
*Résultats des backtests demandés en Session 11*

---

## Faits bruts — ce que les données disent

### 1. Flat betting (mise fixe 7€ par pick sélectionné)

| Métrique | Valeur |
|----------|--------|
| Jours analysés | 30 |
| Total picks | 1099 |
| P&L net | -373€ |
| ROI | -4.9% |
| Drawdown max | -373€ |

### 2. Volume de picks disponibles par seuil de cote réelle (décote ×0.80)

| Seuil cote réelle | Picks dispo | Win% | P&L 7€ fixe |
|-------------------|-------------|------|-------------|
| ≥ 1.20 | 60 (5%) | 63% | +248€ |
| ≥ 1.30 | 16 (1%) | 75% | +151€ |
| ≥ 1.38 | 11 (1%) | 73% | +121€ |
| ≥ 1.50 | 5 (0%) | 80% | +94€ |
| ≥ 1.60 | 4 (0%) | 75% | +83€ |

Picks à cote réelle ≥1.38 : moyenne **2.2 picks/jour**
(5 jours avec ≥2 picks disponibles pour un ticket 2 legs)

### 3. Corrélation entre legs

| Legs | Win rate |
|------|---------|
| Tickets même ligue (n=0) | 0% |
| Tickets ligues différentes (n=126) | 33% |

### 4. Simulations systèmes alternatifs (bankroll initiale 600€)

| Système | P&L net | Drawdown max |
|---------|---------|-------------|
| Flat betting pick single (7€ fixe) | -373€ | -373€ |
| D'Alembert sur tickets (unité 7€) | -492€ | -835€ |
| Paroli / Anti-martingale (unité 7€) | -226€ | -294€ |
| Kelly ×0.5 sur picks (décote ×0.80) | +1062€ | -160€ |

---

## Ce que ces chiffres ne disent pas encore

- Les simulations D'Alembert et Paroli utilisent les **127 tickets historiques** dans leur ordre chronologique. L'échantillon est court.
- Le Kelly utilise p=0.73 fixe. Si le taux réel en production est inférieur, le Kelly surperforme artificiellement.
- Les picks ≥1.38 de cote réelle : il faut vérifier si leur **win rate** se maintient à 73% ou s'il baisse quand on filtre par cote haute.
- La corrélation entre legs est mesurée par un proxy (même ligue). Une vraie corrélation statistique nécessite plus de données.

---

## Questions ouvertes pour la Session 12

1. Avec 5 jours ayant ≥2 picks à cote ≥1.38, est-ce suffisant pour jouer un ticket 2 legs tous les jours ?
2. Le P&L flat betting (-373€) est-il significatif ou dans le bruit statistique ?
3. Quel système est le plus robuste si le win rate passe de 73% à 65% ?
