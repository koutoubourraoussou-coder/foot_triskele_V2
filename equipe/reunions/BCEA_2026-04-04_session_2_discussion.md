# DISCUSSION — Session 2 — BCEA — 2026-04-04
*Transcript vivant — les agents parlent en voix directes*

---

## Ouverture de séance

*L'Agent Principal pose le sujet sur la table.*

"Le Fondateur a observé quelque chose sur le terrain. Une semaine de données personnelles. La Bundesliga 1 et 2 : 10 matchs sur 11 à plus de 1.5 buts hier. Il se demande si le système capture vraiment ça. Et il s'étonne que TEAM/TEAM soit notre champion alors que LEAGUE-first lui semble plus naturel.

Je pose ça sur la table sans orientation. L'équipe décide."

---

## Réducteur de Bruit — Ouverture

*Le Réducteur prend la parole le premier, stylo en main sur son backlog.*

"Huit items. C'est trop pour une session. On en prend un, maximum deux.

L'observation du Fondateur m'intéresse pour une raison concrète : le test de `random_build_source` en Phase 5 date du 2026-04-02. Avant la correction du filtre pool. Avant le +52% sur RANDOM SAFE. Ce test est peut-être périmé. Si c'est le cas, on n'a jamais vraiment répondu à la question.

Les autres items — l'analyse contrefactuelle, le Maestro log enrichi — sont du développement. On ne peut pas les faire avec compare_variants.py. Ce n'est pas cette session.

Ma décision : on teste les combinaisons build/select source pour RANDOM. Quatre variantes. Cinquante runs. C'est rapide, c'est net."

---

## Sceptique — Premier tour

*Le Sceptique se lève à moitié, haussant un sourcil.*

"Je suis globalement d'accord sur le choix. Mais je veux qu'on soit honnêtes sur ce qu'on ne sait pas encore.

L'observation du Fondateur sur 1 semaine — je la respecte comme signal qualitatif. Ça veut dire : il a vu quelque chose. Ça ne veut pas dire : il a raison statistiquement. C'est une semaine. Cinq à dix tickets. C'est exactement ce que notre Bonferroni filtre à 20 runs de simulation.

Et le Profil #2 avec WR=89.1% et build_source=LEAGUE — attention. Ce profil a aussi topk_size=3 au lieu de 10. Et team_min_winrate=0.70 au lieu de 0.75. On ne peut pas isoler la contribution de LEAGUE build depuis cette comparaison. C'est un confounding factor massif.

Je veux un seuil propre avant le test : delta > +3% sur SAFE RANDOM ×mult pour considérer un signal. On est k=4 variantes — le biais de sélection est encore plus fort qu'en Session 1."

*Un silence.*

"On se souvient de la Session 1 ? Signal +1.459 à 20 runs. REJETÉ à 100 runs. -4.4% sur SAFE SYSTEM. Je ne dis pas que c'est pareil ici. Je dis qu'on a appris à se méfier de nos propres enthousiasmes."

---

## Innovateur — Réponse

*L'Innovateur pose son téléphone et ouvre le code sur son écran.*

"J'ai lu le code. `ticket_builder.py`. En entier, les parties qui comptent.

Voilà ce que j'ai trouvé.

Il y a deux étapes dans le pipeline RANDOM. Le filtre pool, et le gate de construction. `filter_effective_random_pool()` et `_random_accept_pick()`. Elles ne se comportent pas pareil pour TEAM mode.

Le filtre pool utilise `dec >= team_min_decided`, soit 6 matchs minimum. Le gate de construction utilise `dec > 0`, soit 1 match minimum. Il y a une asymétrie. L'impact pratique est limité — le pool est déjà pré-filtré — mais c'est une incohérence réelle dans le code."

*Le Sceptique fronce les sourcils.*

"Ça, c'est une vraie découverte. Pas une inférence."

"Exactement. Et ça me donne un mécanisme pour défendre LEAGUE/TEAM comme combinaison intéressante. LEAGUE build filtre sur le WR historique de la ligue sur O15. Les ligues prolifiques — Bundesliga, Championship — ont structurellement un meilleur WR O15 sur 61 jours. Leurs matchs passent plus facilement le gate LEAGUE. Ensuite, TEAM select affine par qualité individuelle des équipes.

Deux filtres de nature différente en cascade. Pas de duplication. Potentiellement complémentaires.

Je le pose comme hypothèse testable. Pas comme conclusion. Le test tranche."

*L'Innovateur lève la main avant que le Sceptique ne réponde.*

"Et je sais ce que tu vas dire. Je ne défends pas LEAGUE/TEAM parce que c'est beau en théorie. Je le défends parce qu'il y a un mécanisme explicite dans le code. Si ça ne passe pas le test, je retire l'hypothèse."

---

## Sceptique — Concession partielle

*Le Sceptique fait un geste de la main — accord partiel.*

"Le mécanisme est réel. Je ne le conteste pas. LEAGUE build donne accès aux ligues prolifiques via WR historique. C'est vérifiable.

Ce que je conteste, c'est la magnitude. On ne sait pas si ce différentiel — LEAGUE vs TEAM build sur le pool O15 — produit des résultats meilleurs ou simplement différents. Sur 61 jours, les données équipes et les données ligues peuvent converger énormément. Les équipes de Bundesliga ont probablement un bon WR O15 aussi bien en stats ligue qu'en stats équipe.

Mon point : tester quatre variantes simultanément, c'est beaucoup. Le biais de sélection k=4 va naturellement produire un gagnant. Ce gagnant n'est pas forcément meilleur."

*Pause.*

"Mais je valide le test. Avec un seuil clair : +3% minimum sur SAFE RANDOM ×mult. Si aucune variante n'atteint ça, le champion reste TEAM/TEAM. Point."

---

## Décision collective — Avant le test

*L'Agent Principal résume.*

"Accord. Quatre variantes : TEAM/TEAM baseline, LEAGUE/LEAGUE, LEAGUE/TEAM, TEAM/LEAGUE. Cinquante runs. Seuil +3% Bonferroni k=4.

compare_variants.py est configuré. Il faut lancer le test."

---

## [Pause — Test à lancer]

*Le test nécessite l'autorisation d'exécution. Le Fondateur est invité à lancer : `python compare_variants.py --runs 50`*

*La discussion reprend après les résultats.*

---

## [Section à compléter après les résultats]

---

## Validateur Froid — Verdict final sur les décisions sans test

*Le Validateur parle en dernier, comme toujours.*

"Sur les items sans test : trois décisions propres.

L'analyse contrefactuelle — c'est du développement, pas un test. Je la note EN ATTENTE DE CODE. L'impact est élevé à long terme. Mais cette session ne peut pas la produire.

Le Maestro log enrichi — idem. L'infrastructure existe dans le code. Le travail est d'y connecter les données. EN ATTENTE DE CODE.

Le filtre Bonferroni — c'est clos. On l'applique. Ce n'est pas une question ouverte.

Sur l'incohérence TEAM build dans `_random_accept_pick()` : c'est documenté. Ce n'est pas un bug critique — le pool pré-filtré atténue l'effet. Mais c'est une dette technique à surveiller.

Sur le test build/select source RANDOM : EN ATTENTE. Je rendrai mon verdict sur faits bruts, pas avant."

*Il referme son carnet.*

"Le protocole fonctionne. On ne conclut pas avant les chiffres."

---

## Note de clôture — Agent Principal

Cette session a produit :
- Une décision de test propre avec seuil défini a priori
- Une découverte de code réelle (incohérence TEAM build dans _random_accept_pick)
- Une priorisation claire du backlog
- Tous les fichiers mémoire mis à jour

Le test est configuré. Il attend l'exécution.

*BCEA — Session 2 — 2026-04-04*
