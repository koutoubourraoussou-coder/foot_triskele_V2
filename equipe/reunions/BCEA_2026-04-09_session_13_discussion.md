# DISCUSSION — Session 13 — BCEA — 2026-04-09
*Transcript vivant — les agents parlent en voix directes*
*Suite Session 12 — résultats des 4 backtests sur 88 jours*

---

## Ouverture de séance

*L'Agent Principal affiche les résultats. Aucun commentaire.*

"88 jours. 5623 picks avec cote et résultat. Voici ce que les données disent.

**Backtest 1 — Win rate par tranche de cote système (décote bookmaker ×0.80)**

| Tranche cote sys | Cote réelle | Picks | Win% | EV/€ | P&L 7€ |
|------------------|-------------|-------|------|------|--------|
| 1.00 – 1.10 | ~0.84 | 364 | 92% | -0.225 | -573€ |
| 1.10 – 1.20 | ~0.92 | 1063 | 84% | -0.227 | -1689€ |
| 1.20 – 1.30 | ~0.99 | 1627 | 77% | -0.238 | -2710€ |
| 1.30 – 1.40 | ~1.07 | 1386 | 71% | -0.242 | -2351€ |
| 1.40 – 1.55 | ~1.15 | 835 | 69% | -0.209 | -1222€ |
| 1.55 – 1.80 | ~1.30 | 185 | 58% | -0.247 | -319€ |
| ≥ 1.80 | ~1.72 | 161 | 42% | -0.286 | -340€ |

**Backtest 2 — Picks cote sys ≥1.72 uniquement**
- Volume : 180 picks (3.2%), actifs 51 jours sur 88
- Win rate : 44% — P&L flat betting : **-289€** (ROI -22.9%)
- Kelly ×0.5 : **+783€** — mais uniquement sur les picks à cote sys >2.84 (très rares)

**Backtest 3 — Win rate par type de pari**

| Type | Picks | Win% | Cote réelle moy | Break-even | EV |
|------|-------|------|----------------|-----------|-----|
| HT05 | 1471 | 72% | 1.07 | 1.40 | -0.237 |
| O15_FT | 1896 | 77% | 1.06 | 1.31 | -0.189 |
| HT1X_HOME | 1225 | 80% | 0.98 | 1.26 | -0.218 |
| TEAM1_SCORE_FT | 422 | 83% | 0.95 | 1.20 | -0.211 |
| O25_FT | 209 | 50% | 1.47 | 1.99 | -0.262 |
| TEAM2_WIN_FT | 53 | 55% | 1.52 | 1.83 | -0.167 |

**Backtest 4 — SAFE uniquement (HT05 + O15_FT), 88 jours**
- 3367 picks, 74% win rate
- P&L : **-5379€** (ROI -22.8%)

**Résumé :**

| Filtre | Picks | Win% | P&L | ROI |
|--------|-------|------|-----|-----|
| Tous picks | 5623 | 75% | -9153€ | -23.3% |
| Cote sys ≥1.72 | 180 | 44% | -289€ | -22.9% |
| SAFE uniquement | 3367 | 74% | -5379€ | -22.8% |

Je passe la parole."

---

## Sceptique — Ouverture

*Le Sceptique se lève. Calme.*

"Je vais dire ce que tout le monde voit.

Quel que soit le filtre appliqué — tous les picks, cotes hautes uniquement, SAFE uniquement — le ROI converge vers **-22 à -23%**. Ce n'est pas une coïncidence. C'est une constante. Et une constante qui émerge indépendamment du filtre, ça ne vient pas des picks. Ça vient d'une hypothèse.

L'hypothèse : **décote bookmaker de 20%**.

Avec cette décote, des cotes système à 1.30 deviennent 1.04 en réel. À 1.04, même avec 92% de win rate, on perd de l'argent. C'est mathématiquement impossible d'être profitable dans ce scénario.

Donc la question centrale n'est plus 'quel système de mise fonctionne'. La question est : **est-ce que la décote de 20% est correcte ?**

Si la vraie décote est 10%, le calcul change radicalement. À cote système 1.30, réelle 1.17 — avec 77% de win, EV = 0.77 × 1.17 - 1 = +0.90% → positif.

Si la vraie décote est 5%, c'est encore mieux.

Avant de prendre une décision sur le système de mise, on doit mesurer la vraie décote. Pas l'estimer. La mesurer. Le Fondateur a joué des tickets réels — il a les cotes du bookmaker. On peut comparer avec les cotes du système sur les mêmes matches."

---

## Réducteur de Bruit — Premier tour

*Le Réducteur sort ses calculs.*

"Le Sceptique a raison sur la décote. Je vais compléter avec ce que les données révèlent autrement.

Regardons le break-even par type de pari — c'est la cote réelle minimale pour être profitable avec le win rate observé :
- HT1X_HOME : 80% de win → break-even à **1.26** réel
- TEAM1_SCORE_FT : 83% de win → break-even à **1.20** réel
- O15_FT : 77% de win → break-even à **1.31** réel

Ces seuils sont très bas. Si la vraie décote est 5-10% plutôt que 20%, ces types de paris deviennent profitables.

Il y a quelque chose d'important dans ces chiffres : **le win rate varie énormément selon le type de pari**. De 42% (cotes hautes ≥1.80) à 83% (TEAM1_SCORE_FT). Ce n'est pas homogène. Le système est beaucoup meilleur sur certains types que d'autres.

Deux observations concrètes :
1. TEAM1_SCORE_FT à 83% sur 422 picks — c'est le type le plus prévisible du système
2. O25_FT à 50% — c'est le moins prévisible, et avec une cote réelle moyenne de 1.47, c'est aussi le seul qui pourrait être profitable même avec 20% de décote si le win rate remontait à 68%

Ces deux infos orientent différemment. On ne devrait pas traiter tous les types de paris de la même façon dans le ticket."

---

## Veilleur — Premier tour

*Le Veilleur a cherché pendant la présentation.*

"J'ai regardé la question de la décote bookmaker dans la littérature.

**Ce que les professionnels font pour mesurer la décote réelle :**

La méthode standard est de comparer les cotes disponibles sur plusieurs bookmakers pour les mêmes événements. Les bookmakers ont des marges différentes selon les types de paris et les ligues :
- Ligues principales (Premier League, LaLiga) : marge 4-6%
- Ligues secondaires : marge 8-12%
- Ligues exotiques / amateurisme : marge 12-20%

**Un fait important :** la marge se calcule différemment selon que la cote est sur/sous 2.0. Pour une cote de 1.25, la marge implicite est souvent plus faible en valeur absolue que pour une cote de 2.5.

**La méthode de 'no-vig odds' :** certains outils calculent la cote 'vraie' (sans marge) en partant des cotes disponibles sur le marché. Avec les cotes vraies, on peut calculer exactement quelle décote notre bookmaker applique.

**Proposition concrète :** pour les 10 derniers tickets joués par le Fondateur, demander :
1. La cote système prédite pour chaque pick
2. La cote réelle disponible sur le bookmaker au moment du bet

Avec 10 tickets × 3-4 picks = 30-40 points de données, on peut calculer la vraie décote par type de pari. 30 points c'est suffisant pour une première estimation solide."

---

## Innovateur — Premier tour

*L'Innovateur a regardé le backtest 2 en détail.*

"Il y a quelque chose que tout le monde a raté dans le Backtest 2.

Le Kelly ×0.5 donne **+783€** sur les picks à cote sys ≥1.72. Mais le flat betting sur ces mêmes picks donne **-289€**. Comment est-ce possible ?

La réponse : Kelly n'a pas parié sur tous ces picks. Il a calculé k ≤ 0 pour la plupart et n'a misé que sur les rares picks où l'edge était positif — ceux avec cote sys > 2.84. Ce sont peut-être 10-20 picks sur 180. Et sur ces picks-là, Kelly a gagné.

Ce que ça dit : **il existe des picks dans notre système avec edge positif même avec 20% de décote**. Ce sont les picks à cote sys très haute (>2.84). Ce n'est pas du volume — c'est de la valeur rare.

**Proposition :** au lieu de chercher à jouer beaucoup de picks avec système de mise, on joue uniquement les picks à très haute cote — 5 à 10 par mois — avec des mises Kelly adaptées. Volume très faible, mais EV positif.

**Deuxième observation :** le type O25_FT a un win rate de 50% et une cote réelle moyenne de 1.47. Break-even à 1.99. Si la vraie décote est 10% au lieu de 20%, cote réelle → 1.66 — toujours pas profitable. Mais si on filtre les O25_FT sur les matchs à MEGA EXPLOSION uniquement ? Le win rate pourrait être différent.

**Troisième piste :** et si on combinait le bon type de pari (TEAM1_SCORE_FT à 83%) avec le bon bookmaker (cote réelle plus haute) ? Sur une cote système 1.18 avec 5% de décote → réelle 1.12. EV = 0.83 × 1.12 - 1 = -0.07% → encore légèrement négatif. Avec 0% de décote → EV = 0.83 × 1.18 - 1 = -0.02% → quasi neutre.

La conclusion est là : **le système prédit bien mais les cotes bookmaker absorbent presque tout l'edge**. La solution est peut-être de trouver un bookmaker avec marge plus faible, pas de changer la structure des paris."

---

## Validateur Froid — Synthèse

*Le Validateur Froid se lève.*

"Je vais formuler ce que les données ont établi et ce qu'elles n'ont pas établi.

**Établi avec certitude (88 jours, 5623 picks) :**
1. Avec décote ×0.80, tous les filtres convergent vers -22 à -23% de ROI. La décote absorbe tout l'edge.
2. Le win rate varie fortement par type de pari : 42% (hautes cotes) à 83% (TEAM1_SCORE_FT).
3. Il existe des picks avec edge positif même à 20% de décote — ceux à cote sys >2.84. Volume très faible.
4. Aucun système de mise (flat, D'Alembert, Paroli, Kelly sur gros volume) ne peut rendre profitable un ensemble de picks structurellement perdants.

**Non établi — nécessite mesure :**
1. La vraie décote bookmaker. L'hypothèse 20% est une estimation. Pas une mesure.
2. Le win rate par type de pari sur sous-groupes (MEGA EXPLOSION uniquement, ligues spécifiques).
3. L'existence d'un bookmaker avec marge <10% sur nos types de paris.

**La décision prioritaire :**
Mesurer la vraie décote avant toute autre action. Sans cette donnée, les simulations sont construites sur une hypothèse non vérifiée. Si la décote est 8-10%, plusieurs types de paris redeviennent profitables et le problème change complètement.

**Action concrète proposée :**
Le Fondateur note les cotes réelles disponibles sur les 20 prochains picks du système. On compare avec les cotes système. On calcule la vraie décote. On revient en session avec cette donnée."

---

## VERDICT DE SÉANCE

**Ce que 88 jours ont établi :**
- Avec décote ×0.80 : TOUS les systèmes perdent ~22% du capital misé
- La décote de 20% est l'hypothèse critique non vérifiée
- Les picks à cote sys >2.84 semblent avoir un edge positif (Kelly +783€) — à confirmer
- TEAM1_SCORE_FT (83% win) et O15_FT (77% win) sont les types les plus prédictibles
- Aucun système de mise ne compense un EV négatif structurel

**La question qui prime sur tout le reste :**
> Quelle est la vraie décote bookmaker sur nos picks ?

**Actions décidées :**
1. **Mesure immédiate** — Le Fondateur note pour les 20 prochains picks : cote système vs cote réelle bookmaker. On calcule la décote réelle.
2. **Backtest de sensibilité** — Simuler le P&L avec décote 5%, 10%, 15%, 20% pour voir à partir de quel seuil le système devient profitable.
3. **Focus picks rares** — Identifier et analyser les picks à cote sys >2.84 (le seul segment à EV positif confirmé avec décote 20%)

**Statu quo :** toujours pas de changement en production avant la mesure de décote réelle.
