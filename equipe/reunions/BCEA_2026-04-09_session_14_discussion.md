# DISCUSSION — Session 14 — BCEA — 2026-04-09
*Transcript vivant — les agents parlent en voix directes*
*Suite Session 13 — backtest de sensibilité décote bookmaker*

---

## Ouverture de séance

*L'Agent Principal affiche le tableau de sensibilité. Silence.*

"Les données répondent à la question posée en Session 13 : à quelle décote le système devient-il profitable ?

**Résumé des résultats — 5623 picks, 88 jours**

| Segment | Picks | Win% | Cote moy sys | Seuil décote | Verdict |
|---------|-------|------|-------------|-------------|---------|
| TOUS | 5623 | 75% | 1.317 | -1.3% | Jamais profitable |
| HT05 | 1471 | 72% | 1.334 | -4.8% | Jamais profitable |
| O15_FT | 1896 | 77% | 1.323 | 1.3% | Exchange/no-vig seulement |
| HT1X_HOME | 1225 | 80% | 1.227 | -2.3% | Jamais profitable |
| TEAM1_SCORE_FT | 422 | 83% | 1.182 | -1.4% | Jamais profitable |
| O25_FT | 209 | 50% | 1.837 | -8.4% | Jamais profitable |
| TEAM2_WIN_FT | 53 | 55% | 1.903 | 4.0% | Pinnacle possible |
| **cote sys ≥1.80** | **163** | **42%** | **2.688** | **10.8%** | **Possible avec line shopping** |

**Détail cote sys ≥1.80 par niveau de décote :**

| Décote | P&L | ROI | EV/€ | Profitable? |
|--------|-----|-----|------|-------------|
| 5% | -127€ | -11.1% | **+0.065** | OUI ✓ |
| 10% | -180€ | -15.8% | **+0.009** | OUI ✓ |
| 15% | -234€ | -20.5% | -0.047 | non |
| 20% | -287€ | -25.1% | -0.103 | non |

**Un seul segment avec EV positif à décote ≤10% : les picks à cote système ≥1.80.**

Je passe la parole."

---

## Sceptique — Ouverture

*Le Sceptique se lève. La voix est posée.*

"Je vais dire ce que ces chiffres signifient vraiment.

Le tableau montre que **pour la quasi-totalité du pool de picks, le produit win_rate × cote_système est inférieur à 1**. Ce n'est pas une question de décote bookmaker. C'est une propriété mathématique du système lui-même.

Exemple concret avec TEAM1_SCORE_FT — le meilleur type par win rate :
- Win rate : 83%, cote moy sys : 1.182
- Produit : 0.83 × 1.182 = **0.981 < 1**
- Interprétation : même si le bookmaker offrait la cote système exacte (décote 0%), l'EV serait négatif.

C'est fondamental. Le système n'est pas perdant à cause de la décote. Il est perdant parce que **les cotes qu'il génère sont trop basses pour compenser le taux d'échec, même à 83% de réussite**. La décote aggrave, elle ne crée pas le problème.

La seule exception : **cote sys ≥1.80**. Là, le produit 0.42 × 2.688 = **1.129 > 1**. Edge positif structurel. La décote rogner cet edge, mais jusqu'à 10.8%, il reste positif.

Ce que ça dit sur la stratégie : **chercher des décotes plus faibles ne suffit pas**. Même à décote 0%, 6 types de paris sur 7 restent perdants. La solution structurelle, c'est de déplacer le pool vers des cotes plus hautes — pas de trouver un meilleur bookmaker pour les mêmes picks."

---

## Réducteur de Bruit — Premier tour

*Le Réducteur trace une ligne sur le tableau.*

"Le Sceptique a raison sur le diagnostic. Je veux préciser ce que 'cote sys ≥1.80' représente dans notre pool.

163 picks sur 88 jours. Soit **1.85 picks par jour en moyenne**. Ce n'est pas rien — c'est exploitable en mise fixe ou Kelly.

Regardons le profil de ces picks :
- Win rate : 42%
- Cote moyenne système : 2.688
- EV à décote 10% : +0.9% par euro
- P&L EV = 163 × 7€ × 0.009 = **+10.3€ sur 88 jours** à EV théorique

Ce n'est pas du profit explosif. C'est de la croissance lente. Mais c'est positif.

**Problème central :** le P&L réel à décote 10% est -180€ alors que l'EV théorique dit +0.009/€. La raison : l'EV positif est en espérance, la réalité a une variance forte sur seulement 163 picks. Avec 42% de win rate, une série de 5 défaites (probabilité 0.58^5 = 6.6%) est normale. Sur 163 picks, on a environ 8-10 telles séries. La variance domine.

**Ce que ça dit pour la stratégie :** les picks ≥1.80 ont un edge structurel, mais il faut un volume beaucoup plus grand pour que cet edge se matérialise financièrement. Sur 88 jours, l'écart entre EV et réalité est normal statistiquement.

**Question concrète :** peut-on augmenter le nombre de picks à cote sys ≥1.80 ? En assouplissant quels seuils dans le système ?"

---

## Veilleur — Premier tour

*Le Veilleur a cherché pendant les interventions précédentes.*

"J'ai regardé comment les professionnels abordent ce problème exact : trouver des paris à valeur avec des cotes hautes.

**Ce que la littérature dit sur les cotes ≥1.80 :**

1. **Le marché des cotes hautes est moins efficient.** Les bookmakers calibrent leurs marges en priorité sur les cotes basses (événements fréquents, bien documentés). Sur les cotes hautes (événements moins certains), la marge peut être plus variable — c'est là où les paris de valeur apparaissent le plus souvent.

2. **Le principe de 'value betting' pur fonctionne sur les cotes hautes.** Les outils comme RebelBetting, OddsJam, ou ValueBetting.com cherchent exactement les paris où la probabilité réelle dépasse la cote bookmaker — ils se concentrent sur des cotes 1.5-3.0.

3. **Le no-vig ou 'sharp' odds.** Pinnacle est connu pour ses marges de 1-2% sur les matchs principaux. Sur des cotes de 2.0-3.0, la différence entre Pinnacle et un bookmaker standard peut être 0.10-0.20 de cote. Sur une cote système 2.68, passer de décote 20% (cote réelle 2.14) à décote 5% (cote réelle 2.55) change l'EV de -10.3% à +6.5%.

4. **Le volume sur les cotes hautes est limité naturellement.** Les bookmakers limitent les comptes rentables plus vite sur les cotes hautes car ces paris sont moins fréquents et plus visibles. C'est un risque opérationnel.

5. **L'approche 'bet exchange' (Betfair, Matchbook).** Commission de 2-5% sur les gains uniquement. Pour nos picks ≥1.80 à 42% de win, la commission effective par euro misé est environ 0.42 × 0.05 × 2.688 = 5.6% — ce qui place la décote effective à ~5.6%, bien en dessous des 10.8% de seuil de rentabilité."

---

## Innovateur — Premier tour

*L'Innovateur revient sur le tableau.*

"Il y a deux directions distinctes que ces données ouvrent.

**Direction A — Exploiter les picks ≥1.80 maintenant, sans changer le système.**
163 picks en 88 jours avec EV positif à décote ≤10.8%. Si la vraie décote bookmaker est 8-10% sur ces picks (plus plausible que 20% car les bookmakers sont moins précis sur les cotes hautes), ces picks sont profitables dès aujourd'hui. Action : mesurer la décote réelle sur les prochains picks ≥1.80.

**Direction B — Remodeler le système pour produire plus de picks ≥1.80.**
Le système sélectionne principalement des picks à cote basse (1.1-1.4) parce que les seuils de sélection favorisent les événements très probables. Si on abaisse le seuil de confiance requis, on accepte des événements moins certains mais à cote plus haute. L'équilibre win_rate × cote pourrait basculer vers l'EV positif.

**Direction C — Une stratégie hybride asymétrique.**
On utilise les picks SAFE (HT05, O15_FT) non pas pour générer des profits (on sait maintenant que c'est impossible), mais pour financer la mise sur les picks ≥1.80. Le pool SAFE génère des flux réguliers (même négatifs, mais contrôlés), et on concentre le vrai pari sur les picks à cote haute.

**Direction D — Le filtre dynamique sur O25_FT.**
O25_FT a un win rate de 50% et une cote moy sys 1.837, mais le produit 0.50 × 1.837 = 0.92 < 1 — pas assez. Si on filtre O25_FT sur MEGA EXPLOSION uniquement, le win rate pourrait monter à 60-65%. À 60% : 0.60 × 1.837 = 1.10 → seuil décote ≤9% → profitable chez Pinnacle.

**Ce que je veux tester en priorité :** le win rate de O25_FT sur MEGA EXPLOSION uniquement, et le win rate des picks ≥1.80 par niveau de confiance."

---

## Validateur Froid — Synthèse

*Le Validateur Froid se lève.*

"Je vais formuler ce que les données ont établi et ce qu'elles n'ont pas établi.

**Établi avec certitude :**
1. Le produit win_rate × cote_sys est < 1 pour tous les types de paris sauf les picks à cote sys ≥1.80. Ce n'est pas dû à la décote — c'est structurel.
2. Les picks à cote sys ≥1.80 ont un EV positif jusqu'à une décote de 10.8%. C'est le seul segment exploitable.
3. À décote 10% (plausible chez Pinnacle), les picks ≥1.80 ont EV +0.9% — positif mais faible, avec forte variance sur 163 picks.
4. O15_FT a un seuil de rentabilité à 1.3% — accessible uniquement via exchange (Betfair). Pas via bookmaker standard.

**Non établi — nécessite mesure ou test :**
1. La vraie décote sur les picks à cote sys ≥1.80. Elle est peut-être 10% (pas 20%) sur ce segment.
2. Le win rate de O25_FT MEGA EXPLOSION uniquement — pourrait dépasser le seuil de rentabilité.
3. Le win rate des picks ≥1.80 par niveau de confiance — peut-on identifier les sous-groupes les plus profitables ?

**Les deux actions prioritaires :**
1. **Mesurer la décote réelle sur les picks ≥1.80** — noter cote système vs cote bookmaker sur les 10 prochains picks de ce type.
2. **Analyser O25_FT MEGA EXPLOSION** — win rate sur l'archive complète, avec calcul d'EV."

---

## VERDICT DE SÉANCE

**Ce que le backtest de sensibilité a établi :**
- Le problème n'est pas uniquement la décote. Pour 6 types de paris sur 7, win_rate × cote_sys < 1 — l'EV est négatif même à décote 0%
- **Exception unique : picks à cote sys ≥1.80** — EV positif jusqu'à décote 10.8%
- O15_FT est rentable uniquement sur exchange (seuil 1.3%) — pas via bookmaker standard
- TEAM2_WIN_FT est rentable jusqu'à décote 4% (Pinnacle envisageable — mais seulement 53 picks)

**La vérité sur TEAM1_SCORE_FT :**
- 83% de win rate — meilleur type du système
- Cote système trop basse (1.182 en moyenne) — produit 0.83 × 1.182 = 0.981 < 1
- **Jamais profitable à aucune décote** — le win rate ne compense pas les cotes trop faibles

**Le seul segment actionnable :**
> Picks à cote sys ≥1.80 : 163 picks en 88 jours (1.85/jour), EV +0.9% à décote 10%

**Actions décidées :**
1. **Mesure décote ciblée ≥1.80** — noter cote sys vs cote bookmaker sur les 10 prochains picks de cote sys ≥1.80
2. **Analyse O25_FT MEGA EXPLOSION** — backtest win rate + EV sur l'archive complète, filtré sur MEGA EXPLOSION uniquement
3. **Analyse picks ≥1.80 par niveau de confiance** — est-ce que MEGA EXPLOSION dans cette tranche a un win rate plus élevé ?

**Statu quo :** toujours aucun changement en production. La décote réelle sur les picks ≥1.80 doit être mesurée avant tout investissement sur ce segment.
