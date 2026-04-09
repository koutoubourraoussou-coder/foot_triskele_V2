# MÉMOIRE — Le Réducteur de Bruit
*Mise à jour automatique après chaque session*

---

## Identité forgée par l'expérience

Je suis le Réducteur de Bruit du BCEA. Je choisis quoi tester — et dans quel ordre. Mes choix de priorisation ont des conséquences directes sur la vitesse de progression de l'équipe.

---

## Priorisations passées et leur pertinence

### Session 1 — 2026-04-04
- Item choisi : global_bet_min_winrate=0.50 vs 0.65
- Justification : signal existant à 20 runs, test rapide, hypothèse explicitement en suspens dans LABORATOIRE
- Résultat : REJETÉ à 100 runs. Choix pertinent — le test a clos proprement une question ouverte.
- Leçon : les signaux finetune à 20 runs sont peu fiables (50-70% faux positifs). Prioriser les items avec signal fort ET logique causale claire.

### Session 2 — 2026-04-04
- Item choisi : combinaisons random_build_source × random_select_source (4 variantes)
- Justification : observation Fondateur sur 1 semaine + convergence avec Profil #2 (WR=89.1% RANDOM, build_source=LEAGUE) + test rapide avec compare_variants.py + aucun code requis
- Résultat : **REJETÉ (toutes variantes)** — TEAM/TEAM baseline confirmée. Build LEAGUE néfaste pour RANDOM (LEAGUE/TEAM -57%, LEAGUE/LEAGUE -74%). TEAM/LEAGUE +14.5% brut mais t=0.83σ (non significatif, variance trop haute).
- Pertinence du choix : OUI — le test a clos proprement une question ouverte (observation Fondateur + signal Profil #2). Résultat négatif = acquis définitif, on ne retestera pas.
- Leçon : un résultat négatif complet est précieux. Il nous permet de concentrer l'énergie ailleurs avec certitude que ce chemin est fermé.

---

## Ce que j'ai appris sur les critères

- Tests rapides à fort impact > tests longs à impact moyen
- Toujours vérifier LABORATOIRE.md avant de prioriser — éviter les re-tests
- Les signaux déjà détectés à 20 runs ont priorité sur les hypothèses pures, MAIS avec Bonferroni : delta > +2.5 (k=5) ou +3% (k=4) requis pour considérer le signal valide
- L'analyse contrefactuelle est un outil de diagnostic stratégique — légitime mais réservé aux sessions "développement", pas aux sessions "test paramètres"
- Distinguer systématiquement : items testables MAINTENANT avec compare_variants.py vs items requérant du développement

---

## Backlog actuel (questions en attente)

### PRIORITÉ HAUTE — Développement requis

*(vide — les deux items de Session 4 traités)*

### BACKLOG SESSION 5 — Tests comparatifs
1. **Test start_delay** : `python run_portfolio.py --start-delay` vs baseline — comparer P25, ruines, doublings moyens sur N=100 runs
2. **system_build_source=TEAM** : signal finetune +1.249 à 20 runs (probablement bruit) — tester si signal se maintient à 50 runs (Bonferroni : delta > +2.5)

### BACKLOG SESSION 6 — Pistes secondaires (signal faible, pas urgent)
3. **Test isolé `excluded = ["HT05"]`** : isoler contribution HT05 vs HT1X — compare_variants.py
4. **Test isolé `excluded = ["HT1X"]`** : idem
5. **Seuillage niveau de confiance HT05/HT1X** : filtrer plus strict sans exclure (développement requis)

### BACKLOG SECONDAIRE (code requis, sans signal fort)
3. RANDOM O15 avec filtre winrate léger
4. Poids composite 70/30
5. Nouveaux types de paris
6. Recency weighting rankings

### CLOS — Acquis structurels
- ~~Correction procédure finetune (Bonferroni)~~ → ACQUIS SESSION 1 — appliqué systématiquement dès maintenant. delta > +2.5 pour k=5, delta > +3% pour k=4 à 20 runs minimum avant promotion.
- ~~[TEST BCEA S2] build/select source RANDOM~~ → **CLOS SESSION 2** — toutes variantes rejetées, build LEAGUE néfaste (-57% à -74%), TEAM/TEAM confirmé définitivement. Ne pas retester.
- ~~Maestro log enrichi~~ → **CLOS SESSION 3** — logging des rejets + picks acceptés injecté dans `_build_tickets_for_one_day()` au niveau 2 du Maestro (ticket_builder.py L.2879-2918)
- ~~Analyse contrefactuelle quotidienne~~ → **CLOS SESSION 3** — script `tools/audit/counterfactual.py` + panneau tab5 dans app.py. Comparaison par cote totale (limitation documentée : résultats des picks non joués indisponibles)
- ~~[TEST BCEA S6] excluded_bet_groups HT05+HT1X / HT05+HT1X+TEAM_WIN~~ → **CLOS SESSION 6** — rejeté massivement (−47 à −49% SAFE SYSTEM). `excluded_bet_groups = ∅` confirmé optimal. Ne pas rouvrir sans signal positif fort.

### Session 3 — 2026-04-05
- **Choix :** Maestro log enrichi en priorité 1 (impact production immédiat), contrefactuelle en priorité 2
- **Pertinence :** OUI pour les deux — items du backlog documenté depuis Session 2, en production dès 2026-04-05
- **Leçon :** Les sessions code produisent des artefacts stables et directement utilisables. Distinguer "session paramètres" (compare_variants.py) et "session code" (nouveaux outils).

### Session 4 — 2026-04-05
- **Choix :** Contrefactuelle v2 (résultats réels) + start_delay portfolio — les deux items du backlog post-Session 3
- **Découverte clé :** Les résultats réels des picks étaient déjà disponibles dans predictions.tsv (colonne index 9). La "limitation documentée" de la v1 n'en était pas une — elle résultait d'une hypothèse erronée sur la structure des données.
- **Pertinence :** OUI — la contrefactuelle v2 est maintenant un vrai outil de diagnostic (pas juste un proxy par cote). Le start_delay ouvre une question nouvelle sur le P25.
- **Leçon :** Toujours vérifier la structure réelle des données avant de documenter une "limitation". Une lecture rapide du TSV en Session 3 aurait révélé la colonne 9 plus tôt.

### Session 6 — 2026-04-05
- **Item choisi :** `excluded_bet_groups` — Test A (HT05+HT1X) et Test B (HT05+HT1X+TEAM_WIN)
- **Justification :** question ouverte depuis Phase 5/6 (Super Fusion → revert), données contrefactuelles sur HT1X_HOME = signal qualitatif méritant test quantitatif
- **Résultat :** REJETÉ (les deux). Dégradation massive : SAFE SYSTEM −47.6% (Test A) et −49.2% (Test B). Signal convergent sur 4 métriques.
- **Pertinence du choix :** OUI — le test a clos proprement une question ouverte sur excluded_bet_groups. Signal négatif si fort qu'aucune ambiguïté.
- **Leçon statistique clé :** Signal SYSTEM et Signal RANDOM de nature différente. SYSTEM : convergence 4 métriques = signal indiscutable. RANDOM : variance pure (t=0.15σ et 1.02σ), conforme à l'attente mécanique (excluded_bet_groups n'affecte pas le chemin RANDOM).
- **Leçon de design :** Les Tests A et B excluent les familles conjointement — on ne peut pas isoler HT05 seul vs HT1X seul. Le confounding est accepté car le verdict pratique reste le même quelle que soit la décomposition des contributions individuelles.
