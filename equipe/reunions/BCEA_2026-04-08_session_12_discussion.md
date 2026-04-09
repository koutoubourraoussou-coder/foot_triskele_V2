# DISCUSSION — Session 12 — BCEA — 2026-04-08
*Transcript vivant — les agents parlent en voix directes*
*Suite directe de la Session 11 — résultats des backtests*

---

## Ouverture de séance

*L'Agent Principal affiche les résultats des 4 backtests sur le tableau.*

"Les données sont là. Je pose tout sans commentaire.

**Backtest 1 — Flat betting (7€ fixe par pick sélectionné, 30 jours)**
- P&L net : **-373€** sur 7693€ misés
- ROI : **-4.9%**
- Drawdown max : -373€ (perte continue depuis le début)

**Backtest 2 — Volume de picks à cote réelle ≥1.38**
- Sur 1099 picks matchés : **11 picks seulement** ont une cote réelle ≥1.38
- Ces 11 picks : 73% de win, P&L **+121€** avec mise fixe 7€
- Disponibles seulement 5 jours sur 30. En moyenne 2.2 picks/jour ces jours-là.

**Backtest 3 — Corrélation entre legs**
- 0 ticket avec tous les legs dans la même ligue (le système diversifie déjà)
- 126 tickets avec ligues différentes → 33% win. Pas de corrélation mesurable.

**Backtest 4 — Systèmes alternatifs (bankroll 600€)**

| Système | P&L net | Drawdown max |
|---------|---------|-------------|
| Flat betting pick single (7€) | -373€ | -373€ |
| D'Alembert sur tickets (7€) | -492€ | **-835€** |
| Paroli / Anti-martingale (7€) | -226€ | -294€ |
| Kelly ×0.5 sur picks (cote ≥1.38) | **+1062€** | -160€ |

Note sur le Kelly : il n'a joué que **11 picks**. Ceux avec cote réelle > 1.37. Il a refusé automatiquement tous les autres.

Je passe la parole."

---

## Sceptique — Ouverture

*Le Sceptique se lève, les bras croisés.*

"Je vais dire la chose la plus inconfortable de cette réunion.

Le backtest Kelly montre +1062€. Mais il a joué 11 picks. Onze. Sur un total de 1099 disponibles. Ce résultat est **statistiquement non significatif**. Avec 11 picks, la variance est telle qu'on pourrait avoir +2000€ ou -500€ simplement par chance. Je ne tire aucune conclusion du Kelly sur cet échantillon.

Ce qui est significatif, c'est le backtest flat betting : **1099 picks, -4.9% de ROI**. Ça, c'est un chiffre solide. Et ce qu'il dit est brutal :

**À cote réelle ≤1.37, même avec 73% de win rate, les picks ne sont pas profitables.**

Faisons le calcul. Un pick à cote système 1.30 → cote réelle 1.04. Avec 73% de win :
- EV = 0.73 × 1.04 - 1 = **-0.24%** par euro misé.

Un pick à cote système 1.50 → cote réelle 1.20. Avec 73% de win :
- EV = 0.73 × 1.20 - 1 = **-12.4%** par euro misé.

Attends. À cote réelle 1.20 avec 73% de win, on perd quand même de l'argent ? Oui. Parce que pour être profitable à 73% de win, il faut une cote réelle ≥ 1/0.73 = **1.37 minimum**.

Tout ce qui est en dessous de 1.37 de cote réelle est structurellement perdant, même avec le meilleur système de prédiction du monde. Et 98% de nos picks sont en dessous de ce seuil."

*Un silence pesant.*

"Le problème n'est pas la martingale. Le problème n'est pas le nombre de legs. Le problème est que **notre système prédit bien mais joue sur des cotes trop faibles pour être profitable**."

---

## Réducteur de Bruit — Premier tour

*Le Réducteur hoche la tête lentement.*

"Le Sceptique a raison sur l'arithmétique. Je vais compléter.

Il y a deux façons de lire ces données.

**Lecture pessimiste :** les 98% de picks sous 1.37 réel ne sont pas profitables. Le système génère de bons picks mais dans une zone de cotes où le bookmaker a déjà absorbé l'edge. On ne peut rien y faire.

**Lecture optimiste :** il existe une zone rentable (cote réelle ≥1.38, 11 picks sur 30 jours, 73% de win, +121€ sur 77€ misés). Le problème est le volume. Si on trouve comment générer plus de picks dans cette zone, le système est viable.

La question concrète : pourquoi si peu de picks à cote haute ?

Deux hypothèses :
1. Le système est bien calibré — il sélectionne principalement des événements très probables (>73%), qui ont mécaniquement des cotes basses. C'est la nature du sport : ce qui est probable est peu payé.
2. Le filtre de sélection des picks élimine trop tôt les paris à cote haute, même quand le taux de réussite prédit justifierait de les garder.

Ces deux hypothèses ont des solutions très différentes. La première dit : accepter des cotes basses et trouver un système de mise qui fonctionne quand même. La deuxième dit : revoir les filtres pour laisser passer plus de cotes hautes."

---

## Veilleur — Premier tour

*Le Veilleur a cherché pendant que les autres parlaient.*

"J'ai regardé ce qui se fait dans la littérature sur les paris à cote basse. Quelques éléments pertinents.

**1. Le problème de la cote basse est universel.**
Tous les systèmes de paris professionnels font face à ce problème. La solution dominante dans la littérature n'est pas de chercher des cotes plus hautes — c'est de **maximiser le volume** de paris à cote basse avec edge positif, et d'appliquer le Kelly pur pour dimensionner les mises.

**2. Le seuil de rentabilité dépend du win rate, pas de la cote.**
Avec p=0.73, le seuil de rentabilité est 1/0.73 = 1.370. Mais si on a des sous-groupes de picks avec p=0.80, le seuil tombe à 1.25. Si on peut identifier ces sous-groupes (par ligue, par type de pari, par niveau de confiance), on trouve de l'edge même à cote basse.

**3. L'approche 'Asian handicap' contourne partiellement ce problème.**
Les bookmakers asiatiques ont des marges plus faibles (1-2% vs 5-8% en Europe). Les mêmes picks à cote système 1.30 donneraient peut-être 1.25-1.27 réel au lieu de 1.04. La différence peut remettre le système en zone profitable.

**4. Le 'line shopping' — comparer plusieurs bookmakers.**
Les meilleurs parieurs professionnels comparent 10-20 bookmakers pour chaque pari. La meilleure cote disponible peut être 5-15% supérieure à la cote d'un seul bookmaker. Sur cote 1.30, passer à 1.36 peut faire basculer de -EV à +EV.

**5. Le système de 'value betting automatisé'.**
Certains outils comparent en temps réel les cotes de tous les bookmakers avec les probabilités implicites. Quand la cote d'un bookmaker dépasse la vraie probabilité, on bet automatiquement. C'est légal, mais certains bookmakers limitent les comptes rentables rapidement.

Je ne recommande rien — je pose les options que le monde utilise."

---

## Innovateur — Premier tour

*L'Innovateur sort de son mutisme.*

"Je vais proposer quelque chose de radical.

Et si on arrêtait de chercher à gagner sur le ticket, et qu'on se concentrait uniquement sur **identifier les 11 picks rentables par mois** ?

Le backtest 2 nous dit : 11 picks à cote réelle ≥1.38, 73% de win, +121€ sur 77€ misés. C'est un ROI de **+57%** sur ces picks uniquement. Le problème n'est pas qu'on ne sait pas prédire — c'est qu'on noie ces 11 picks dans 1088 autres qui ne sont pas profitables.

**Proposition A : le filtre cote-haute.**
On ne joue que les picks où le système prédit une cote supérieure à 1.72 (soit ≥1.38 réel). En ce moment ça donne 11 picks sur 30 jours. Peut-être insuffisant pour une martingale — mais suffisant pour une mise fixe rentable.

**Proposition B : la chasse aux outliers.**
Certains jours ont des P&L très positifs en flat betting (30 mars : +15€, 17 mars : +8€). Ces jours ont peut-être plus de picks à cote haute. Peut-on identifier en avance les journées 'riches en valeur' ?

**Proposition C : inverser la logique.**
Au lieu de chercher des cotes hautes avec bon taux, chercher des cotes très basses (1.10-1.15) avec un taux encore plus élevé. Si on peut identifier des événements à 92% de probabilité à cote 1.10, l'EV est 0.92×1.10 - 1 = +1.2%. Faible mais positif. Avec beaucoup de volume et Kelly, c'est de la croissance lente mais solide.

**Proposition D : le système hybride SAFE uniquement.**
On abandonne complètement le combiné. On joue uniquement des picks SAFE (HT05, O15_FT) en mise fixe ou Kelly, et on utilise le bankroll ainsi construit pour alimenter des expériences plus risquées. Exactement la logique SAFE/NORMALE qu'on a en portfolio."

---

## Validateur Froid — Synthèse

*Le Validateur Froid se lève pour la première fois.*

"Je vais poser les conclusions que les données permettent — et seulement celles-là.

**Ce que les données prouvent :**
1. À cote réelle ≤1.37, le système perd de l'argent même avec 73% de win. (-4.9% ROI sur 1099 picks)
2. À cote réelle ≥1.38, le système est profitable (73% de win, +57% ROI sur les 11 picks disponibles). Mais 11 picks en 30 jours est trop peu pour conclure statistiquement.
3. D'Alembert et Paroli sont pires que le système actuel sur tickets. Ils amplifient les pertes.
4. La corrélation entre legs n'est pas mesurable avec les données actuelles (0 ticket same-ligue).

**Ce que les données suggèrent mais ne prouvent pas :**
1. Kelly sur les picks à cote haute semble prometteur — mais l'échantillon (11 picks) est trop petit.
2. La décote bookmaker de 20% pourrait être réduite en changeant de bookmaker ou en faisant du line shopping.
3. Il existe peut-être des sous-groupes de picks avec win rate >73% qui permettraient d'élargir la zone rentable.

**Les trois questions prioritaires pour la prochaine session :**
1. Sur les 88 jours d'archive, quel est le win rate des picks par tranche de cote système ? (ex. 1.1-1.2, 1.2-1.3, 1.3-1.4, 1.4-1.5, etc.)
2. Quelle est la vraie décote bookmaker en production — est-ce uniformément 20% ou variable par type de pari ?
3. Peut-on augmenter le volume de picks à cote système ≥1.72 en changeant les seuils de sélection dans ticket_builder ?

Avant de décider quoi que ce soit, on a besoin de ces trois réponses."

---

## VERDICT DE SÉANCE

**Ce que les backtests ont révélé :**
- Le vrai problème : **seuil de rentabilité à cote réelle ≥1.37** non atteint par 98% des picks
- Systèmes alternatifs testés : D'Alembert et Paroli sont pires que la situation actuelle
- Kelly prometteur sur les 2% de picks à cote haute — mais échantillon trop petit pour décider
- Corrélation entre legs : non mesurable sur les données actuelles

**Propositions en attente de données :**
- Filtre cote-haute (Innovateur A) : simulable dès maintenant sur 88 jours
- Line shopping / bookmakers alternatifs (Veilleur) : nécessite données externes
- Sous-groupes win rate élevé (Réducteur) : nécessite analyse par type de pari et ligue
- Système SAFE uniquement en flat betting (Innovateur D) : simulable dès maintenant

**Actions pour la prochaine session :**
1. Backtest win rate par tranche de cote système sur 88 jours
2. Backtest flat betting + Kelly sur picks à cote système ≥1.72 sur 88 jours
3. Évaluation de la décote réelle par type de pari (HT05 vs HT1X vs O15 vs TEAM1_SCORE)
4. Simulation flat betting sur picks SAFE uniquement (HT05 + O15_FT)

**Statu quo :** aucun changement en production. On produit les 4 backtests avant toute décision.
