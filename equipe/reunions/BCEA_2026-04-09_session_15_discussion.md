# DISCUSSION — Session 15 — BCEA — 2026-04-09
*Transcript vivant — les agents parlent en voix directes*
*Suite Session 14b — O25_FT MEGA EXPLOSION + picks ≥1.80 par confiance + croisement type × confiance*

---

## Ouverture de séance

*L'Agent Principal pose les trois tableaux.*

"Deux hypothèses étaient ouvertes depuis la Session 14. Les données répondent.

**Hypothèse A — O25_FT MEGA EXPLOSION a un win rate suffisant pour devenir profitable.**
Réponse : **Non.**
- 47 picks, 57.4% win, cote moy sys 1.730
- Produit win_rate × cote : 0.57 × 1.730 = **0.994 < 1**
- Jamais profitable, même à décote 0%.

**Hypothèse B — Les picks ≥1.80 MEGA EXPLOSION ont un meilleur win rate que l'ensemble.**
Réponse : **Non.**
- 19 picks MEGA EXPLOSION ≥1.80 : 47.4% win, cote moy 2.026 → produit 0.961 → jamais profitable
- Le niveau MEGA EXPLOSION sur les hautes cotes ne garantit pas l'edge

**Découverte inattendue — Analyse C :**
Certaines combinaisons type × confiance ont un produit WR×C > 1, et donc un seuil de rentabilité positif :

| Segment | Picks | Win% | Cote moy | WR×C | Seuil décote |
|---------|-------|------|---------|------|-------------|
| O15_FT × FORT | 48 | 68.8% | 2.985 | 2.052 | **51.3%** |
| O15_FT × MOYEN PLUS | 80 | 80.0% | 1.341 | 1.073 | **6.8%** |
| TEAM1_SCORE_FT × FORT | 74 | 87.8% | 1.181 | 1.037 | **3.6%** |
| HT1X_HOME × MOYEN PLUS | 125 | 79.2% | 1.298 | 1.028 | **2.7%** |
| HT05 × TRÈS FORT | 300 | 75.7% | 1.341 | 1.014 | **1.4%** |
| O15_FT × TRÈS FORT | 277 | 75.5% | 1.329 | 1.003 | **0.3%** |

Je passe la parole."

---

## Sceptique — Ouverture

*Le Sceptique regarde longuement l'Analyse C.*

"Avant d'aller plus loin, j'ai une alerte sur les deux premiers segments.

**O15_FT × FORT : 68.8% win, cote moy 2.985.**
O15_FT — 'Over 1.5 buts en temps plein' — avec une cote système de **2.985 en moyenne** ? C'est un événement qui se produit dans ~70% des matchs en général. Une cote système de 3.0 signifie que le modèle ne lui donne que 33% de probabilité. C'est contradictoire : le système dit '33% probable', mais l'événement se produit à 68.8%.

Deux interprétations :
1. Le modèle est systématiquement sous-estimateur sur O15_FT FORT — c'est du vrai edge
2. C'est du bruit — 48 picks, et peut-être que le win rate observé (68.8%) diverge de la réalité à long terme

48 picks n'est pas suffisant pour trancher. Sur 48 picks à 68.8% de win, l'intervalle de confiance à 95% est 53-81%. L'hypothèse nulle (win rate réel = 33%) est rejetée, mais l'hypothèse win rate réel ≥ 50% n'est pas solidement établie.

**O15_FT × MOYEN PLUS : 80% win, cote moy 1.341, seuil 6.8%.**
Ce segment est plus crédible : 80 picks, cote plausible (1.341), win rate cohérent avec les autres O15_FT de haut niveau. Si la vraie décote est ≤6.8%, ce segment est profitable.

**Ce qui est solide :**
Le seuil 6.8% pour O15_FT × MOYEN PLUS, et le seuil 1.4% pour HT05 × TRÈS FORT sur 300 picks — ces deux segments ont des échantillons significatifs."

---

## Réducteur de Bruit — Premier tour

*Le Réducteur décompose les chiffres.*

"Le Sceptique a raison sur O15_FT × FORT. Mettons-le en attente — trop peu de picks.

Je veux me concentrer sur **ce que les données disent clairement avec des échantillons suffisants** :

**Segments avec N ≥ 100 et WR×C ≥ 1 :**

| Segment | N | WR×C | Seuil |
|---------|---|------|-------|
| O15_FT × MOYEN PLUS | 80 | 1.073 | 6.8% |
| HT1X_HOME × MOYEN PLUS | 125 | 1.028 | 2.7% |
| HT05 × TRÈS FORT | 300 | 1.014 | 1.4% |
| O15_FT × TRÈS FORT | 277 | 1.003 | 0.3% |

Ces quatre segments couvrent **782 picks sur 88 jours**, soit **8.9 picks par jour**. Ce n'est pas marginal.

**Volume et seuil :**
- O15_FT × MOYEN PLUS (6.8%) : nécessite un bookmaker avec marge ≤7% — Pinnacle ou SBOBet peuvent offrir ça sur O15_FT
- HT1X_HOME × MOYEN PLUS (2.7%) : seuil très bas — exchange only
- HT05 × TRÈS FORT (1.4%) : exchange only
- O15_FT × TRÈS FORT (0.3%) : quasi impossibles — trop marginal

**Conclusion pratique :** parmi les segments robustes, **O15_FT × MOYEN PLUS** est le seul atteignable avec un bookmaker asiatique. Les autres nécessitent un exchange avec commission ≤2.7%, ce qui est possible sur Betfair Exchange."

---

## Veilleur — Premier tour

*Le Veilleur complète avec des informations externes.*

"J'ai cherché les marges réelles des bookmakers sur les types de paris qui nous concernent.

**Marges bookmaker par type de pari (sources : Pinnacle, OddsPortal, academic betting research) :**

- Over 1.5 buts (O15_FT) : 1.5-3% sur Pinnacle, 5-8% sur bookmakers standards, 2-5% commission sur Betfair Exchange
- Home Win at Half Time (HT1X_HOME) : 2-4% Pinnacle, 8-12% standards
- Over 2.5 buts (O25_FT) : 1.5-3% Pinnacle, 5-10% standards

**Application directe :**
- O15_FT × MOYEN PLUS, seuil 6.8% : **profitable chez Pinnacle (marge ~2-3%)** ✓
- HT1X_HOME × MOYEN PLUS, seuil 2.7% : **possible chez Pinnacle (marge ~3%)** — marginal
- HT05 × TRÈS FORT, seuil 1.4% : **nécessite Betfair Exchange (commission ~2%)** — juste à la limite

**Ce que Pinnacle implique pratiquement :**
Pinnacle n'accepte pas tous les clients. Les comptes rentables ne sont pas limités (c'est leur modèle), mais l'accès depuis certains pays est restreint. Si le Fondateur est en zone accessible, Pinnacle est l'action la plus directe pour O15_FT × MOYEN PLUS.

**Betfair Exchange :**
Commission de 2% sur les gains nets pour les nouveaux comptes (peut monter à 5% si le compte est rentable via le 'charge rate'). Pour HT05 × TRÈS FORT à seuil 1.4%, la commission Betfair peut effacer l'edge si le charge rate monte.

**Conclusion Veilleur :** Pinnacle est la cible principale. Un seul segment clairement profitable à leur marge : O15_FT × MOYEN PLUS."

---

## Innovateur — Premier tour

*L'Innovateur regarde la colonne 'O15_FT × FORT'.*

"Je ne veux pas lâcher O15_FT × FORT aussi vite.

68.8% win, cote moy 2.985, 48 picks. Le Sceptique dit que c'est peut-être du bruit. Je dis : regardons ce que signifie une cote système de 2.985 pour O15_FT.

Si le système sort une cote de 3.0 pour O15_FT, c'est qu'il estime la probabilité de cet événement à ~33%. Ces matchs sont probablement des matchs défensifs, des matchs à faible nombre de buts attendus. Le système est calibré sur ces matchs pour prédire que Over 1.5 est peu probable.

Et pourtant : 68.8% de win. Le système se trompe lourdement sur ces picks spécifiques — dans le bon sens.

**Hypothèse :** le niveau FORT pour O15_FT avec cote haute correspond à des matchs où le système juge que Over 1.5 est difficile (mauvaise équipe offensive), mais où l'événement se produit quand même parce que le scoring global du football est plus élevé que le modèle ne l'anticipe.

C'est un biais systématique exploitable — pas du bruit.

**Ce que je propose :** analyser ces 48 picks en détail. Quelles ligues ? Quels types de matchs ? Si le pattern est cohérent, c'est de l'edge réel."

---

## Validateur Froid — Synthèse

*Le Validateur Froid se lève.*

"Je vais poser ce que les trois backtests ont établi.

**Établi :**
1. O25_FT MEGA EXPLOSION n'est pas profitable à aucune décote — hypothèse fermée.
2. Picks ≥1.80 MEGA EXPLOSION n'ont pas d'edge supérieur — hypothèse fermée.
3. Le seul segment ≥1.80 avec EV positif est FORT (39 picks, cote moy 4.077) — mais l'EV positif est trompeur : le P&L réel est négatif car les grosses cotes tombent sur des défaites. Variance sur 39 picks.
4. O15_FT × MOYEN PLUS (80 picks, 6.8%) est le segment le plus robuste et actionnable.
5. HT1X_HOME × MOYEN PLUS (125 picks, 2.7%) et HT05 × TRÈS FORT (300 picks, 1.4%) existent mais nécessitent des conditions d'accès très strictes.

**Non établi :**
1. O15_FT × FORT (48 picks) — trop peu pour conclure. Edge possible ou bruit.
2. La vraie décote chez Pinnacle sur nos types de paris — estimée à 2-3%, mais non mesurée.

**La question pratique unique :**
Le Fondateur a-t-il accès à Pinnacle ? Si oui, tester O15_FT × MOYEN PLUS avec mise fixe sur les 20 prochains picks de ce type. Si non, la stratégie nécessite de passer par une solution intermédiaire.

**Actions décidées :**
1. **Vérifier l'accès Pinnacle** — c'est le seul bookmaker dont la marge (2-3%) est compatible avec nos segments profitables
2. **Isoler les 48 picks O15_FT × FORT** — extraire les détails (ligue, date, match) pour vérifier si le pattern est cohérent ou aléatoire
3. **Mise en production pilote** — si Pinnacle accessible, parier uniquement O15_FT × MOYEN PLUS en mise fixe (7€) pendant 30 jours, noter les cotes réelles"

---

## VERDICT DE SÉANCE

**Ce que les analyses ont fermé :**
- O25_FT MEGA EXPLOSION : jamais profitable (produit 0.994 < 1)
- Picks ≥1.80 MEGA EXPLOSION : pas d'edge supérieur aux autres niveaux de confiance

**Ce qui reste ouvert et actionnable :**

| Segment | Picks | Win% | Seuil décote | Statut |
|---------|-------|------|-------------|--------|
| O15_FT × MOYEN PLUS | 80 | 80% | 6.8% | **Profitable chez Pinnacle** |
| HT1X_HOME × MOYEN PLUS | 125 | 79% | 2.7% | Possible chez Pinnacle (marginal) |
| HT05 × TRÈS FORT | 300 | 76% | 1.4% | Exchange only |
| O15_FT × FORT | 48 | 69% | 51.3% | À vérifier (biais ou bruit ?) |

**La stratégie qui émerge :**
> Jouer uniquement les picks filtrés sur O15_FT × MOYEN PLUS chez un bookmaker à faible marge (Pinnacle, SBOBet). Volume : ~1 pick/jour. Mise fixe. Aucun ticket combiné.

**Actions décidées :**
1. Vérifier l'accès Pinnacle depuis la zone du Fondateur
2. Extraire et analyser les 48 picks O15_FT × FORT (détail ligue + résultat)
3. En production pilote : isoler les O15_FT × MOYEN PLUS sur le système actuel et noter les cotes bookmaker réelles

**Statu quo production :** toujours aucun changement sur le système de tickets actuel. Le pilote se fait en parallèle, pas en remplacement.
