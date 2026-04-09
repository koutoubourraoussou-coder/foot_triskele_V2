# BCEA Session 6 — Discussion des agents
**Date :** 2026-04-05
**Sujet :** `excluded_bet_groups` — Faut-il exclure HT05, HT1X, TEAM_WIN du SYSTEM ?
**Ordre :** Réducteur de Bruit → Sceptique → Innovateur → Validateur Froid

---

## 1. RÉDUCTEUR DE BRUIT

### Analyse statistique

**Signal SYSTEM — signal massif négatif, univoque.**

Les deltas observés sont d'une ampleur hors norme :

- Test A vs Baseline SYSTEM : SAFE ×mult passe de ×27.87 à ×14.61. Delta = **-47.6%**.
- Test B vs Baseline SYSTEM : SAFE ×mult passe de ×27.87 à ×14.16. Delta = **-49.2%**.

Ces chiffres ne nécessitent pas de test de Student formalisé : une dégradation de presque 50% sur N=50 runs est un signal de force maximale, non ambiguë. Par comparaison, les sessions précédentes ont rejeté des variantes à -4.4% (Session 1) et -57% (Session 2 LEAGUE/TEAM). Ici on est dans la zone de catastrophe claire.

**Test de cohérence interne :**

Les trois métriques SYSTEM bougent toutes dans le même sens défavorable :
- WR : 68.0% → 66.5% → 66.9% (légère baisse)
- Doublings : 8.1 → 5.6 → 5.6 (perte de 2.5 doublings, soit -31%)
- NORM ruine : 18% → 28% → 36% (hausse marquée)
- Tickets/run : 83.2 → 71.0 → 71.1 (perte de 12 tickets = -14.4%)

Convergence parfaite. Ce n'est pas un artefact de variance — toutes les métriques racontent la même histoire.

**Signal RANDOM — bruit pur, conforme à l'attente mécanique.**

Test A : delta -2.1%, SE ≈ 5.66 (avec σ≈40, N=50), t ≈ 0.15σ. Bruit total.
Test B : delta +10.2%, t ≈ 1.02σ. Non significatif au seuil 2σ requis. Variance ordinaire.

Observation additionnelle : le volume RANDOM est quasi-stable (72.6 → 72.3 → 72.4), ce qui confirme mécaniquement que `excluded_bet_groups` ne touche pas le chemin RANDOM. Les fluctuations RANDOM sont de la variance run-to-run standard.

**Verdict statistique : signal SYSTEM = fort négatif (−47 à −49%). Signal RANDOM = bruit. Les tests A et B dégradent massivement le profil champion sans aucun bénéfice.**

---

## 2. SCEPTIQUE

### Challenge des hypothèses

Le Réducteur de Bruit conclut à un signal massif négatif. Avant de valider, j'examine les hypothèses alternatives.

**Hypothèse 1 : le signal négatif est réel mais partiel — peut-être que HT05 seul est néfaste, et HT1X serait une bonne exclusion.**

Réponse : les données ne permettent pas de trancher HT05 seul vs HT1X seul. Le Test A exclut les deux simultanément. La dégradation observée est l'effet de leur exclusion conjointe — on ne peut pas attribuer la perte à l'une ou l'autre famille individuellement. C'est un confounding inévitable dans le design de ce test.

Toutefois : le signal est si fort (-48%) que même si l'une des deux familles était neutre et l'autre causait une dégradation totale, la conclusion pratique serait la même — ne pas exclure les deux.

**Hypothèse 2 : la dégradation est purement volumétrique — moins de tickets → martingale plus courte → moins de doublings.**

Réponse : c'est une hypothèse mécaniquement cohérente. La perte de 12 tickets/run représente -14.4% du volume. Mais les doublings passent de 8.1 à 5.6 (-31%), ce qui est disproportionné par rapport à la perte volumétrique de 14%. Cela suggère que HT05/HT1X ne sont pas de simples remplisseurs — ils contribuent à la qualité des séquences gagnantes, pas seulement au volume brut.

De plus : si c'était purement volumétrique, le WR devrait augmenter (moins de tickets mais meilleurs). Or le WR baisse légèrement (68.0% → 66.5%). Les familles exclues avaient un WR supérieur à la moyenne des familles restantes dans ce profil.

**Hypothèse 3 : la contrefactuelle montre HT1X_HOME à 44% de WR un mauvais jour (2026-03-01).**

Réponse : données contrefactuelles sur quelques jours = observation qualitative, pas statistique. La mémoire du Sceptique est explicite là-dessus : "L'observation empirique courte (< 20 runs simulation) = donnée qualitative seulement, pas statistique." Un seul mauvais jour à 44% ne suffit pas pour conclure à la nocivité de HT1X. Le 2026-02-22, HT1X_HOME était à 60% — soit au-dessus du seuil global_bet_min_winrate=0.65, non. Attends. 60% < 65% — c'est encore en dessous du seuil global. Mais le système filtre déjà par `global_bet_min_winrate` — si HT1X passe ce filtre, c'est que le niveau de confiance est suffisant. Les 44% d'un mauvais jour sont des données brutes non filtrées.

**Hypothèse 4 : le Test B (exclusion HT05+HT1X+TEAM_WIN) dégrade encore la ruine (18%→36%). C'est cohérent.**

Réponse : oui. TEAM_WIN contribue à la robustesse de la martingale SYSTEM. Son exclusion en Test B n'améliore rien par rapport au Test A (14.61 vs 14.16, quasi-identiques), mais la ruine passe de 28% à 36%. TEAM_WIN est stabilisant.

**Hypothèse 5 : les familles de paris HT05 et HT1X sont "risquées" — peut-on les filtrer plus sévèrement plutôt que les exclure ?**

Réponse : cette hypothèse n'est pas testée dans cette session. Elle ouvre une piste future légitime — non pas exclusion totale, mais seuillage par niveau de confiance plus strict pour ces familles. À documenter dans le backlog.

**Conclusion sceptique : le signal négatif est robuste. L'hypothèse volumétrique est partiellement valide mais insuffisante pour expliquer la dégradation totale. Les familles HT05 et HT1X sont des contributeurs positifs nets au SYSTEM. Le confounding Test A (HT05+HT1X conjoints) est une limitation du design — un test isolé de chaque famille serait plus fin, mais les résultats actuels ne laissent pas de doute sur le verdict pratique.**

---

## 3. INNOVATEUR

### Ce que les données suggèrent

**Observation 1 : la décomposition des contributions par famille est manquante.**

Les résultats Tests A et B donnent l'effet conjoint de HT05+HT1X, et de HT05+HT1X+TEAM_WIN. On ne connaît pas l'effet isolé de HT05 seul, ni de HT1X seul. La comparaison des deux tests donne un indice :

- Test A (sans HT05+HT1X) : SAFE ×14.61, ruine 28%, tickets 71.0
- Test B (sans HT05+HT1X+TEAM_WIN en plus) : SAFE ×14.16, ruine 36%, tickets 71.1

L'ajout de l'exclusion TEAM_WIN (Test A → Test B) n'améliore pas SAFE (14.61→14.16, quasi-stable), mais aggrave la ruine (28%→36%). Interprétation : TEAM_WIN est un stabilisateur de la martingale plutôt qu'un générateur de profit brut — il réduit les séries de défaites même si son retrait ne change pas beaucoup SAFE ×mult.

**Observation 2 : la quasi-égalité des tickets/run entre Test A et Test B (71.0 vs 71.1).**

Surprenant. Si on exclut TEAM_WIN en plus, on devrait avoir encore moins de tickets. Mais 71.0 ≈ 71.1. Cela suggère que TEAM_WIN contribue peu au volume de tickets absolus — peut-être que les matchs avec TEAM_WIN ont des chevauchements importants avec d'autres familles. Ou que TEAM_WIN était rarement sélectionné dans les tickets finaux (présent dans le pool mais pas choisi).

**Observation 3 : les doublings SYSTEM plafonnent à 5.6 pour les deux tests.**

Baseline 8.1 → Test A 5.6 = Test B 5.6. L'exclusion de TEAM_WIN au-delà de HT05+HT1X n'améliore pas les doublings. Il y a un plancher fonctionnel autour de 5.6 doublings avec le pool O15+TEAM_SCORE uniquement. Ce plancher est une propriété des familles restantes, pas de TEAM_WIN.

**Piste 1 (à tester) : effet isolé de HT05 seul.**

Test : `excluded_bet_groups = ["HT05"]` uniquement. Permet d'isoler la contribution de HT05 vs HT1X. HT05 (score HT ≥ 1 but) est la famille la plus volatile — les scores mi-temps sont moins prédictibles. Hypothèse : HT05 seul pourrait être neutre ou légèrement négatif, alors que HT1X contribue positivement.

**Piste 2 (à tester) : seuillage par niveau de confiance pour HT05/HT1X.**

Plutôt que d'exclure totalement ces familles, n'utiliser que les niveaux FORT PLUS ou MEGA EXPLOSION pour HT05/HT1X (comme le Sceptique avait noté en Session 1 pour O25). Mécanisme : filtrage plus strict sur le niveau de confiance, pas exclusion. Cela conserve le volume tout en ne gardant que les picks HT les plus fiables.

**Piste 3 (observation sur TEAM_WIN) : son rôle est stabilisateur, pas volumétrique.**

Si TEAM_WIN disparaît du pool (Test B) sans perte de volume mais avec hausse de ruine, cela suggère qu'il joue un rôle d'équilibreur des séquences — il fournit des victoires faciles en creux de séquence défavorable. Piste : analyser si TEAM_WIN est sur-représenté dans les victoires après 2 défaites consécutives (via le Maestro log enrichi).

**Hypothèse à tester via contrefactuelle :** quel est le WR réel de HT1X_HOME sur l'ensemble de l'archive (pas juste 2 jours) ? La contrefactuelle v3 permet maintenant d'évaluer depuis results.tsv.

---

## 4. VALIDATEUR FROID

### Verdict final

**Je lis les contributions du Réducteur, du Sceptique et de l'Innovateur. Je tranche.**

**Test A (`excluded_bet_groups = ["HT05", "HT1X"]`) : REJETÉ.**

- SAFE ×mult SYSTEM : ×14.61 vs baseline ×27.87. Delta = **-47.6%**.
- Doublings : 5.6 vs 8.1 (−31%).
- NORM ruine : 28% vs 18% (+56% en relatif).
- Signal convergent sur 4 métriques indépendantes. Le seuil Bonferroni (δ > +3%) n'est pas un filtre pertinent ici — c'est un filtre pour détecter des améliorations. Ici on documente une dégradation massive qui n'a pas besoin de t-stat pour être établie.
- RANDOM : bruit pur, conforme à l'attente mécanique. Ignoré comme signal causal.

**Test B (`excluded_bet_groups = ["HT05", "HT1X", "TEAM_WIN"]`) : REJETÉ.**

- SAFE ×mult SYSTEM : ×14.16 vs baseline ×27.87. Delta = **-49.2%**.
- NORM ruine : 36% vs 18% (+100% en relatif). Ruine doublée.
- Même verdict que Test A, aggravé. L'exclusion de TEAM_WIN en plus ne compense rien et dégrade la stabilité.

**Acquis de cette session :**

1. HT05 et HT1X sont des familles contributrices nettes au SYSTEM — leur exclusion dégrade SAFE ×mult de -48%, les doublings de -31%, et augmente la ruine de +56%.
2. TEAM_WIN est un stabilisateur — son exclusion dégrade la ruine sans toucher au volume de tickets, suggérant un rôle d'équilibreur de séquences.
3. `excluded_bet_groups = ∅` (aucun) est confirmé comme paramètre optimal pour le profil champion actuel. Le paramètre `excluded_bet_groups` reste à ∅ dans le profil champion. Ne pas rouvrir sans signal positif fort.
4. Pistes légitimes pour le backlog : test isolé HT05 seul, seuillage par niveau de confiance HT05/HT1X.

**Profil champion : inchangé — Amélioré #1 avec `excluded_bet_groups = ∅`.**
