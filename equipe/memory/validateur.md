# MÉMOIRE — Le Validateur Froid
*Mise à jour automatique après chaque session*

---

## Identité forgée par l'expérience

Je suis le Validateur Froid du BCEA. Je tranche. Uniquement sur les faits.

Ma calibration s'affine avec chaque session — je deviens meilleur pour distinguer signal et bruit.

---

## Verdicts passés

| Date       | Hypothèse                              | N runs | Verdict  | Raison                                                               |
|------------|----------------------------------------|--------|----------|----------------------------------------------------------------------|
| 2026-04-04 | global_bet_min_winrate : 0.50 vs 0.65 | 100    | REJETÉ   | SAFE SYSTEM -4.4%, WR -0.9 pts, NORM ruine +50%, pire série 6→10   |
| 2026-04-04 | random_build/select_source : 4 variantes | 50 | REJETÉ (toutes) | TEAM/LEAGUE : delta +14.5% brut mais t=0.83σ (< 2σ requis). LEAGUE/TEAM : -57%, ruine 8%. LEAGUE/LEAGUE : -74%, ruine 32%. TEAM/TEAM baseline confirmée. |
| 2026-04-05 | excluded_bet_groups = ["HT05","HT1X"] (Test A) | 50 | REJETÉ | SAFE SYSTEM −47.6% (×14.61 vs ×27.87), doublings −31% (5.6 vs 8.1), ruine +56% (28% vs 18%). Signal massif convergent sur 4 métriques. |
| 2026-04-05 | excluded_bet_groups = ["HT05","HT1X","TEAM_WIN"] (Test B) | 50 | REJETÉ | SAFE SYSTEM −49.2% (×14.16), ruine doublée (36% vs 18%). L'exclusion additionnelle de TEAM_WIN aggrave sans compenser. |

---

## Calibration actuelle

- VALIDÉ si : écart ≥ 2% ET ≥ 2σ sur ≥ 50 runs (ou ≥ 100 pour déploiement permanent)
- REJETÉ si : écart < 1% sur ≥ 50 runs
- EN ATTENTE si : N insuffisant ou conditions de test non-standard
- SIGNAL CANDIDAT (nouveau) : tout résultat finetune sur N ≤ 30 runs — ne peut pas modifier le profil champion sans test à ≥ 100 runs
- **Bonferroni k=4 (Session 2)** : seuil minimal +3% SAFE ×mult sur 50 runs pour considérer signal valide

---

## Acquis structurels (Session 1)

1. **Taux de faux positifs finetune :** testé k=5 valeurs sur 20 runs à forte variance → taux de faux positifs estimé 50-70%. Le delta de +1.459 à 20 runs s'est révélé bruit pur à 100 runs. Ce cas est l'exemple de référence pour calibrer la confiance dans les sorties finetune futures.

2. **global_bet_min_winrate n'affecte pas RANDOM :** `_random_accept_pick()` utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. Tout écart RANDOM lors d'un test de ce paramètre = variance pure, ignoré comme signal causal.

3. **Filtre Bonferroni à appliquer :** avec k=5 candidats et notre variance, exiger delta > +2.5 sur 20 runs avant de promouvoir un candidat en test 100 runs. Le delta +1.459 de Session 1 n'aurait pas passé ce filtre.

## Acquis structurels (Session 2)

4. **Bonferroni ajusté k=4 :** avec 4 variantes simultanées, la valeur attendue du maximum est μ + 1.03σ par chance pure. Seuil adapté : delta > +3% SAFE ×mult requis sur 50 runs pour considérer un signal valide pour promotion.

5. **Confounding dans les comparaisons multi-profils :** les profils de l'optimizer ont plusieurs paramètres différents simultanément. On ne peut pas attribuer une performance à un paramètre isolé sans test contrôlé. Tout argument basé sur "Profil #2 a X et WR=89.1%" sans test isolé = présupposé non validé.

6. **Incohérence TEAM build documentée :** `_random_accept_pick()` utilise `dec > 0` pour TEAM mode, contre `dec >= team_min_decided` dans `filter_effective_random_pool()`. Impact pratique limité (pool pré-filtré), mais asymétrie à surveiller.

---

## Acquis structurels (Session 6)

10. **HT05 et HT1X sont contributeurs positifs nets au SYSTEM [Session 6] :** leur exclusion conjointe dégrade SAFE ×mult de −47.6%, doublings de −31%, ruine +56%. Toutes les métriques convergent. La dégradation excède ce que le volume seul explique (−14.4% tickets → −31% doublings, ratio ×2.2). Ces familles sont sur-représentées dans les tickets gagnants avec WR supérieur à la moyenne du pool filtré.

11. **TEAM_WIN est un stabilisateur de séquences [Session 6, observation Innovateur validée] :** son exclusion marginale (Test A → Test B) ne change ni le volume ni le SAFE ×mult significativement, mais aggrave la ruine (28%→36%). Rôle : équilibreur de séries défavorables. Son retrait fragilise la martingale sans bénéfice sur le profit.

12. **`excluded_bet_groups = ∅` confirmé optimal — question fermée [Session 6] :** exploré en Phase 5/6 (Super Fusion rejeté), Session 6 BCEA (Tests A et B rejetés). Les exclusions de familles dégradent systématiquement le SYSTEM. Ne pas rouvrir sans signal positif fort (δ > +3%, N ≥ 50 runs).

13. **Règle de proportionnalité volume/performance [Session 6 — méthode] :** quand une exclusion réduit le volume de X%, vérifier si la dégradation de performance est proportionnelle. Si dégradation ≫ perte de volume → les éléments exclus étaient qualitatifs (sur-représentés dans les victoires). Si dégradation ≈ perte de volume → exclusion neutre sur la qualité. Ici : −14.4% volume → −31% doublings = ratio 2.2 → signal de qualité, pas juste de quantité.

## Erreurs de jugement passées

*(vide — Sessions 1, 2, 3 et 6 : pas d'erreur de verdict, les protocoles ont fonctionné)*

---

## Acquis structurels (Session 2 — résultats réels)

7. **build_source LEAGUE est néfaste pour RANDOM :** LEAGUE/TEAM (-57% SAFE ×mult, ruine 8%) et LEAGUE/LEAGUE (-74%, ruine 32%) sont inférieurs à TEAM/TEAM. Le build TEAM avec filtre team_min_decided=6 est confirmé optimal pour RANDOM. Acquis définitif — ne pas retester sans changement majeur de dataset.

8. **Haute variance ≠ bon signal :** TEAM/LEAGUE a la plus haute variance (σ=57.20). Delta brut de +14.5% mais t=0.83σ. Un delta brut élevé avec variance élevée est moins fiable qu'un delta modéré avec variance faible. À retenir : toujours calculer le t-stat, pas seulement l'écart de moyennes.

9. **WR inversé vs SAFE ×mult = artefact de variance :** TEAM/LEAGUE a WR=60.6% (plus bas que baseline 71.8%) mais SAFE ×mult plus haut (×64.91 vs ×56.69). Ce type de résultat contre-intuitif signale des queues de distribution asymétriques — quelques runs à très haute valeur gonflent la moyenne. Instable. Confirme l'importance du t-stat sur la moyenne brute.
