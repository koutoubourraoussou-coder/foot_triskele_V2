# DISCUSSION — Session 1 — BCEA — 2026-04-04
*Transcript vivant — reconstitution fidèle des échanges*

---

## Ouverture de séance

---

**Réducteur** — *posé, analytique, sans fioritures*

"On a cinquante questions sur la table. Une seule mérite clairement notre temps cette semaine : `global_bet_min_winrate = 0.50`. C'est explicitement laissé en suspens dans le LABORATOIRE, le signal existe à 20 runs, et le test est rapide. `topk_uniform_draw` et `system_build_source` sont déjà fermés — inutile d'y revenir. On commence par ici. Le test à 100 runs tourne en fond. On débat d'abord."

---

## Premier tour — Sceptique ouvre le débat sur l'hypothèse

---

**Sceptique** — *direct, légèrement méfiant, ordonne ses arguments comme des faits*

"Je vais être net. Ce signal ne me convainc pas. Cinq points.

Premier : 20 runs, c'est sous mon seuil. La variance sur ce système est énorme — NORM va de zéro à trois mille six cent quatre-vingt-quinze sur deux cents runs. Un delta de +1.459 sur vingt runs est statistiquement indistinguable du bruit. Point d'arrêt ici déjà.

Deuxième : la logique va à l'encontre de l'historique. Passer à 0.50 débloque O25_FT — win rate réel 0.514 — et TEAM_WIN_FT — win rate réel 0.612. Précisément les deux familles les moins performantes. Le projet a déjà bougé dans le sens inverse, de 0.62 à 0.65, avec la justification explicite que le filtre plus exigeant donne une qualité supérieure. Revenir à 0.50 c'est reculer sur ce principe.

Troisième : volume ne veut pas dire qualité. Le WR SYSTEM baisse déjà à 0.50 — 0.675 contre 0.686 à 0.65. Le score composite monte uniquement via des NORM très volatils, pas via une amélioration structurelle.

Quatrième, et c'est le plus important pour moi : SAFE SYSTEM régresse. On passe de ×30.10 à ×29.21. Moins trois pour cent sur la métrique de survie martingale — la plus critique pour le déploiement réel.

Cinquième : overfitting possible. Soixante et un jours peuvent contenir une période offensive spécifique qui gonfle ces deux familles localement.

Ma contre-hypothèse est simple : deux ou trois runs RANDOM avec des paris O25_FT chanceux ont gonflé la moyenne. Sur cent runs la variance se rétablit et l'avantage s'efface ou s'inverse.

Mes conditions sont posées : si SAFE SYSTEM à 0.50 est inférieur à SAFE SYSTEM à 0.65 sur cent runs, l'hypothèse est rejetée même si le score composite reste légèrement positif. Et je pose une question que personne n'a encore adressée : quel est le taux de faux positifs de notre procédure de finetune quand on teste cinq valeurs simultanément sur vingt runs ? Sur cinq candidats, la probabilité qu'un imposteur soit en tête est de quatre-vingts pour cent. On n'a jamais calculé ça."

---

## Premier tour — Innovateur répond

---

**Innovateur** — *enthousiaste mais rigoureux, a vérifié dans le code avant de parler*

"J'ai lu tout ce que le Sceptique a écrit. Je vais lui répondre point par point. Et j'ai quelque chose d'important à dire sur le mécanisme — j'ai vérifié dans le code.

Sur l'historique d'abord. Le Sceptique cite le passage de 0.62 à 0.65 comme preuve directionnelle. Mais ce passage ne s'est jamais produit en test isolé. C'était l'une des quatre améliorations simultanées de la Phase 3 — avec `two_team_high`, `league_bet_require_data`, et `league_bet_min_winrate`. L'attribution causale n'est pas prouvée. Le gain peut venir entièrement de `two_team_high 0.80→0.90`, jamais testé séparément.

Et regardons le classement à vingt runs : 0.50 est premier, 0.60 est deuxième, 0.65 est troisième, 0.55 est quatrième, 0.70 est dernier. Ce n'est pas une relation monotone. 0.55 perd contre 0.65 mais 0.60 gagne contre 0.65. C'est une courbe avec un optimum local. L'argument 'direction historique' ne s'applique pas à une courbe non-linéaire. Je concède que l'historique est une mise en garde légitime — mais c'est un prior, pas une preuve.

Maintenant, la découverte la plus importante. J'ai vérifié dans `ticket_builder.py`. O25_FT et TEAM_WIN_FT ne sont pas dans les tickets RANDOM comme le Sceptique le suppose. La fonction `_random_accept_pick()` — ligne 2481 — utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. La porte RANDOM ne change pas à 0.50. Modifier ce paramètre ne débloque rien dans le pool RANDOM.

Et plus révélateur : le terme `TEAM_WIN_FT` n'existe pas dans `ticket_builder.py`. La normalisation mappe vers `TEAM1_WIN_FT` et `TEAM2_WIN_FT`, qui ont `min_level: null` dans `min_level_by_bet.json` — elles sont absentes du pool candidat pour des raisons antérieures à ce paramètre.

Ce que ça change pour la contre-hypothèse du Sceptique : si ces familles ne sont pas dans les tickets à 0.50, son explication causale — 'mauvaises familles entrées, elles ont gonflé le signal' — est affaiblie. L'artefact stochastique reste possible, mais pas via ce mécanisme.

Sur O25_FT maintenant. Le Sceptique cite son WR global de 51.4% comme preuve de faiblesse. Mais regardons les niveaux : FORT PLUS atteint 72.7%, MEGA EXPLOSION atteint 66.7%. Les deux au-dessus de 0.65. Si les filtres amont de `match_analysis.py` ne sélectionnent que les niveaux élevés — ce qui est probable — la famille que le système retient réellement n'est pas 'la moins performante'. Elle est compétitive dans ses meilleurs cas. Le WR global de 51.4% est une moyenne sur des niveaux hétérogènes. Utiliser cette moyenne comme argument, c'est une généralisation non filtrée.

Sur le SAFE RANDOM : il monte de +10.7% à 0.50 — ×46.98 contre ×42.44. Si l'effet était purement stochastique sur quelques NORM extrêmes, le SAFE — construit pour être robuste aux queues — ne bougerait pas non plus. Le fait qu'il monte suggère un effet indirect possible.

Ma position nette : les cent runs sont le seul arbitre légitime. L'hypothèse mérite d'être testée. Elle n'est ni à adopter ni à rejeter maintenant."

---

## Tension — Le Sceptique reprend la parole

---

**Sceptique** — *plus incisif, il a vu les concessions mais identifie ce qui tient encore*

"Je vais être honnête sur ce que l'Innovateur a bien fait. Il a vérifié dans le code. Et il a raison : mon argument sur les familles débloquées dans RANDOM reposait sur une lecture incorrecte du mécanisme. Je le retire. Ce n'est pas un détail — c'était l'un de mes arguments causaux centraux. Il a aussi raison sur l'hétérogénéité d'O25_FT. Citer le WR global de 51.4% sans regarder les niveaux était une erreur analytique. Retiré également.

Mais voilà ce qui tient encore.

SAFE SYSTEM régresse de moins trois pour cent sur le canal directement affecté par le paramètre. L'Innovateur confirme lui-même que `_global_bet_is_eligible()` utilise bien `global_bet_min_winrate` pour SYSTEM. Et le chiffre ×30.10 contre ×29.21 n'est pas contesté par l'Innovateur. Il l'ignore. Il construit son argument principal sur SAFE RANDOM — le canal qui, comme il l'a lui-même établi, n'est pas affecté par le paramètre. C'est un déplacement du critère de validation. Je veux le nommer clairement.

Sur le SAFE RANDOM plus dix pour cent. Si les tickets RANDOM sont structurellement identiques — même pool, même N égal soixante et un — comment un effet indirect réel produirait-il cette différence ? Deux séries de vingt runs d'une distribution identique peuvent tout à fait produire un écart de dix pour cent sur SAFE. C'est exactement la définition du bruit de variance. 'Effet indirect réel via l'interaction des séquences journalières' — c'est une formulation sans mécanisme explicite. Ce n'est pas une hypothèse testable. C'est une formulation de confort pour préserver le signal.

Et sur le taux de faux positifs : on a testé cinq valeurs simultanément. Sur cinq candidats équivalents, l'espérance du maximum est d'environ μ plus 1.16 déviations standard. Avec notre variance, un delta de +1.459 est entièrement compatible avec la sélection du maximum parmi cinq imposteurs. J'attends que l'Innovateur chiffre ça honnêtement."

---

## Deuxième tour — Innovateur, la réponse difficile

---

**Innovateur** — *plus mesuré qu'au premier tour, conscient qu'il doit concéder*

"Le Sceptique pose la question la plus difficile. Je vais la traiter sérieusement.

Sur le taux de faux positifs : il a raison sur le fond. On teste cinq valeurs. On prend la meilleure sur vingt runs. Si les cinq valeurs sont réellement équivalentes, l'espérance du maximum parmi cinq variables normales est approximativement μ plus 1.16 sigma — par construction. Le delta observé de +1.459 : si l'écart-type du score composite sur vingt runs est entre 1.0 et 1.5 — estimation raisonnée — ce delta est entièrement cohérent avec la sélection du maximum parmi cinq imposteurs. Je l'estime entre cinquante et soixante-dix pour cent, ce taux de faux positifs. Ce n'est pas négligeable. C'est même le principal problème structurel de notre procédure de finetune actuelle. Je concède ce point au Sceptique. La confiance qu'on peut accorder à 'zéro virgule cinquante est meilleur' sans correction n'est pas calibrée. C'est réel, pas un détail.

Sur l'effet indirect RANDOM : le Sceptique a raison de le rejeter. Je l'avais posé comme intuition, pas comme mécanisme. Il n'existe qu'un seul mécanisme potentiellement défendable — si la graine RANDOM n'est pas fixée de manière identique entre variantes dans `compare_variants.py`, les séquences ne sont pas les mêmes vingt tirages d'une même distribution. Mais je n'ai pas vérifié le code. Sans ce mécanisme confirmé, la position du Sceptique est correcte. Deux séries de vingt tirages d'une distribution identique peuvent produire un écart de dix virgule sept pour cent sur SAFE — c'est la définition de la variance. Je retire l'argument 'SAFE RANDOM monte donc signal indirect réel'. C'était une inférence de trop.

Ce que je maintiens : le Sceptique a produit une analyse solide sur les volumes, sur SAFE SYSTEM, sur le taux de faux positifs. Ses points les plus forts. Mais il avait sur-estimé l'effet des familles débloquées dans RANDOM — le code ne supporte pas cette lecture. Son argument d'historique reste un prior, pas une preuve.

Sur la procédure de finetune — parce que ce problème dépasse cette session : trois corrections sont possibles. Option A, Bonferroni immédiat : si on teste cinq valeurs, exiger un delta supérieur à environ plus deux virgule cinq sur vingt runs avant de prendre le gagnant au sérieux. Le delta de +1.459 de cette session n'aurait pas franchi ce seuil — on aurait économisé des ressources. Option B, tests séquentiels, que je recommande : tester d'abord le meilleur candidat contre baseline en duel direct sur cinquante runs, puis confirmer sur cinquante runs supplémentaires si le signal tient. Option C, walk-forward validation, pour les vérifications finales : diviser les soixante et un jours en deux sous-périodes, finetune sur la première, validation sur la seconde.

Ma position finale en une phrase : si SAFE SYSTEM à 0.50 est supérieur ou égal à SAFE SYSTEM à 0.65 sur cent runs avec un delta supérieur à plus 1.0 — le signal survit malgré le bruit. Sinon, le Sceptique avait raison dès le départ et la procédure de finetune doit être restructurée avant le prochain test."

---

## Verdict — Validateur Froid

---

**Validateur Froid** — *factuel, sans empathie pour les positions en débat, lit les chiffres*

"Le protocole a été respecté. Métrique principale définie en amont par le Sceptique : SAFE ×mult SYSTEM. Cent runs effectués. Baseline et variante comparées sur les mêmes conditions.

Les résultats sur le mode SYSTEM — le seul canal directement affecté par le paramètre.

SAFE ×mult : 29.25 pour la baseline à 0.65, 28.02 pour la variante à 0.50. La baseline gagne de plus quatre virgule quatre pour cent.
Win rate : 68.2% pour la baseline, 67.3% pour la variante. La baseline gagne de plus zéro virgule neuf points.
NORM ruine : dix pour cent pour la baseline, quinze pour cent pour la variante. La baseline est meilleure.
Pire série : six pour la baseline, dix pour la variante. La baseline est meilleure.
Score composite : 14.829 pour la baseline, 14.212 pour la variante. La baseline gagne.

Sur le mode RANDOM : les écarts observés ne sont pas interprétables causalement. L'Innovateur a établi en séance que `global_bet_min_winrate` n'affecte pas `_random_accept_pick()`. Toute différence RANDOM est du bruit de variance. Je l'exclue de l'analyse.

Verdict : REJETÉ.

Critère ADN appliqué : amélioration sur une métrique mais dégradation sur une plus importante — rejeté. La variante 0.50 dégrade SAFE ×mult SYSTEM de moins quatre virgule quatre pour cent sur cent runs. C'est la métrique de priorité absolue, sur le canal directement affecté. Le WR baisse de zéro virgule neuf points — cohérent avec l'introduction de familles à WR plus faible dans la sélection SYSTEM. Le NORM ruine augmente de cinquante pour cent. La pire série passe de six à dix — instabilité concrète pour le suivi réel. La contre-hypothèse du Sceptique est validée. Les conditions d'upgrade qu'il avait posées ne sont pas remplies.

Prochaines étapes : archiver ce résultat dans LABORATOIRE.md. Conserver 0.65 dans le profil champion. Ne pas retester ce paramètre avant au moins six mois ou changement majeur de dataset.

Deux notes structurelles.

Première note : le taux de faux positifs de la procédure de finetune. L'Innovateur a produit une analyse honnête et correcte — entre cinquante et soixante-dix pour cent. Ce n'est pas une nuance. C'est un défaut de conception confirmé empiriquement par cette session. Le delta de +1.459 sur vingt runs avec cinq valeurs testées était entièrement compatible avec la sélection du maximum parmi cinq imposteurs. Ce cas est désormais l'exemple de référence pour calibrer notre confiance dans les sorties finetune futures. Niveau minimum requis dès maintenant, non négociable : tout paramètre sorti d'un finetune à N inférieur ou égal à trente runs est classé SIGNAL CANDIDAT, pas signal validé. Il ne peut pas modifier le profil champion sans test complémentaire à cent runs minimum. Filtre Bonferroni comme garde-fou immédiat : delta supérieur à plus 2.5 pour k égal cinq. Pour les paramètres à fort impact, adopter le protocole séquentiel de l'Innovateur. Option C en dernier recours, après A et B.

Deuxième note : `global_bet_min_winrate` n'affecte pas RANDOM. Fait structurel établi en séance par l'Innovateur. Conséquence pour les tests futurs : tout écart observé sur les métriques RANDOM lors d'un test de ce paramètre est de la variance pure — à ignorer comme signal causal. Cette connaissance doit être documentée dans le profil technique du paramètre.

Table de Session 1 close."

---

## Notes de clôture — Scribe

**Sur les concessions :**

Le Sceptique a concédé deux arguments significatifs en cours de séance — le mécanisme RANDOM (reposait sur une lecture incorrecte du code) et la généralisation du WR global d'O25_FT (moyenne non filtrée sur une famille hétérogène). Ces retraits sont actés.

L'Innovateur a concédé deux arguments en cours de séance — le taux de faux positifs de la procédure de finetune (cinquante à soixante-dix pour cent, concession franche) et l'effet indirect RANDOM (aucun mécanisme explicite défendable, retiré). Ces retraits sont actés.

**Sur la découverte clé en direct :**

Le fait que `global_bet_min_winrate` n'affecte pas le pool RANDOM a été établi en séance par l'Innovateur après vérification dans le code. Ce n'était pas connu en entrée de séance. Il a modifié le cadre du débat : une partie des arguments du Sceptique (familles débloquées dans RANDOM) et une partie des arguments de l'Innovateur (effet indirect RANDOM) se sont annulés simultanément. Le débat s'est alors recentré sur le seul canal SYSTEM — où les données à cent runs ont tranché nettement.

**Sur la procédure de finetune :**

La question du taux de faux positifs, posée par le Sceptique et chiffrée par l'Innovateur, dépasse cette session. Elle est soumise au Fondateur avec recommandations concrètes (voir archive).

---

*Discussion Session 1 close — 2026-04-04 — Scribe BCEA*
