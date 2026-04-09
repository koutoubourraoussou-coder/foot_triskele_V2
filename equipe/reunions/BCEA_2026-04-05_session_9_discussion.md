# DISCUSSION — Session 9 — BCEA — 2026-04-05
*Transcript vivant — les agents parlent en voix directes*

---

## Ouverture de séance

*L'Agent Principal pose le sujet sur la table.*

"Le Fondateur veut qu'on fouille les recoins. Le composite score 70/30 n'a jamais été touché depuis l'optimizer. La question est simple : est-ce que goals_score mérite plus de poids ? Le Test D vient de nous dire que le COMPOSITE ligue 70/30 ne bat pas le CLASSIC. Mais ça ne répond pas à la question du ratio lui-même. On débat."

---

## Réducteur de Bruit — Ouverture

*Le Réducteur consulte ses notes, puis lève les yeux.*

"Je vais commencer par ce qui me gêne dans la question.

Le Test D nous a donné -1.8% sur SAFE SYSTEM à 0.54σ. Ça veut dire que le COMPOSITE ligue 70/30, sur les données actuelles, ne bat pas le CLASSIC. Si on change le ratio vers 60/40 ou 50/50, on augmente le poids de goals_score. Mais la question est : pourquoi goals_score serait meilleur que base_rate pour prédire les wins ?

goals_score est une métrique de contexte — il mesure si une ligue ou une équipe produit beaucoup de buts. base_rate mesure directement le taux de victoire historique sur ce type de pari. Ces deux métriques ne sont pas équivalentes. Et je n'ai pas de raison a priori de croire que l'une est meilleure que l'autre.

Ce que je veux avant de décider : est-ce que quelqu'un a une hypothèse sur le mécanisme par lequel goals_score dominant améliorerait les picks ?"

---

## Sceptique — Premier tour

*Le Sceptique pose ses mains à plat sur la table.*

"Trois points.

**Un.** Le Test D a échoué avec 70/30 COMPOSITE pour les ligues. On veut maintenant changer le ratio qui s'applique aux équipes uniquement — puisque league_ranking_mode est resté CLASSIC. C'est cohérent de tester team_ranking_mode séparément. Mais je note que le champion utilise déjà team_ranking_mode=COMPOSITE depuis le début. On n'a donc jamais testé si COMPOSITE est meilleur que CLASSIC pour les équipes non plus. C'est un acquis non vérifié.

**Deux.** goals_score capture la fréquence des buts, pas la qualité prédictive du pari. Une équipe qui marque beaucoup de buts n'est pas nécessairement une équipe sur qui le pari O15_FT a un taux élevé — ça dépend aussi de la défense adverse, des confrontations, du contexte. base_rate est plus direct car il mesure précisément ce qu'on veut prédire.

**Trois.** Si on veut tester le ratio, je propose de tester les deux ratios simultanément dans le même run : 60/40, 50/50, et en bonus CLASSIC pour les équipes. Ça donne trois variantes d'un coup au lieu de deux runs séparés. Coût : un seul run supplémentaire."

*Une pause.*

"Et je pose la question que personne n'a posée : est-ce que goals_score est corrélé positivement avec le win rate réel sur nos données ? Si oui, augmenter son poids a du sens. Si non, on optimise dans le vide."

---

## Innovateur — Premier tour

*L'Innovateur se lève, enthousiaste.*

"La question du Sceptique est exactement la bonne. Et je peux y répondre partiellement depuis les données disponibles.

Dans les fichiers composite, chaque ligne a `base_rate` et `composite_score` côte à côte. Si on calcule la corrélation entre ces deux colonnes et le win rate réel — et on peut le faire sur `data/rankings/triskele_composite_team_x_bet.tsv` directement — on saura si goals_score apporte de l'information marginale.

Ma proposition : avant de régénérer les TSV avec un nouveau ratio, on calcule la corrélation `goals_score ~ base_rate` sur les données actuelles. Si la corrélation est forte (>0.85), goals_score est redondant et changer le ratio ne changera rien. Si la corrélation est faible, goals_score capture autre chose — et là le test vaut le coup.

C'est 10 lignes de Python sur les données existantes. Pas besoin de régénérer quoi que ce soit."

*L'Innovateur s'assoit.*

"Et pour répondre à la question du Sceptique sur CLASSIC vs COMPOSITE pour les équipes : c'est un test légitime aussi. On pourrait l'inclure."

---

## Validateur Froid — Synthèse

*Le Validateur Froid intervient, voix posée.*

"Je vais synthétiser ce que j'entends.

**Ce qu'on sait :**
1. COMPOSITE ligue 70/30 = pas de signal vs CLASSIC (Test D, 0.54σ). Clos.
2. COMPOSITE équipe 70/30 = jamais testé en isolation vs CLASSIC équipe. C'est un acquis non vérifié du champion.
3. Le ratio 70/30 lui-même = jamais touché. Question ouverte légitime.

**Ce qu'on ne sait pas :**
- Si goals_score apporte de l'information marginale sur base_rate.
- Si COMPOSITE équipe bat CLASSIC équipe.

**Proposition de l'Innovateur :** calculer la corrélation goals_score ~ base_rate sur les données existantes. C'est rapide, ça informe la décision sur le ratio. Je valide cette étape préalable.

**Si corrélation forte (>0.85) :** changer le ratio ne changera pas grand chose — les deux métriques disent la même chose. Le test 60/40 / 50/50 a peu de chances de produire un signal. Je recommanderais de déprioritiser.

**Si corrélation faible (<0.70) :** goals_score capture quelque chose d'indépendant. Tester 60/40 et 50/50 simultanément avec CLASSIC équipe comme troisième variante est justifié.

**Décision proposée :** calculer la corrélation d'abord, puis décider du plan de test."

---

## Réducteur de Bruit — Clôture

*Le Réducteur ferme son carnet.*

"D'accord avec le Validateur Froid. Étape préalable obligatoire : corrélation goals_score ~ base_rate sur les données actuelles.

Si on teste, on teste proprement : trois variantes simultanées (60/40, 50/50, CLASSIC équipe comme contrôle). Pas de runs séparés.

Et je maintiens la priorité backlog : start-delay et optimisation portfolio restent devant en impact production. Ce test est une exploration — pas une urgence."

---

## VERDICT DE SÉANCE

**Étape 1 (immédiate) :** Calculer la corrélation entre `goals_score` et `base_rate` sur `triskele_composite_team_x_bet.tsv`. Informe la décision sur le ratio.

**Étape 2 (conditionnelle) :**
- Si corrélation < 0.70 : lancer trois variantes simultanées — ratio 60/40, ratio 50/50, CLASSIC équipe comme contrôle. N=50 runs.
- Si corrélation ≥ 0.85 : déprioritiser — signal peu probable.
- Entre 0.70 et 0.85 : jugement d'équipe.

**Priorité relative :** Exploration secondaire. Start-delay et optimisation portfolio conservent leur priorité.
