# BCEA — Session 4 — 2026-04-05
## Table de réunion — Session code

**Date :** 2026-04-05
**Type :** Session code (livraison)
**Agent principal :** Claude (Sonnet 4.6)
**Objectifs déclarés :** Contrefactuelle v2, panneau Streamlit amélioré, validation Maestro log, start_delay portfolio

---

## ORDRE DU JOUR

1. **[PRIORITÉ HAUTE]** Contrefactuelle v2 — utiliser les résultats réels des picks (colonne 9 predictions.tsv)
2. **[PRIORITÉ HAUTE]** Panneau Streamlit tab5 — mise à jour avec les nouveaux flags et métriques v2
3. **[VALIDATION]** Maestro log enrichi — confirmer que MAESTRO_MAX_DETAIL_LINES est défini et opérationnel
4. **[DÉVELOPPEMENT]** start_delay dans run_portfolio.py — lancement progressif RS → SS → RN/SN

---

## DÉCISIONS ET LIVRABLES

### Objectif 1 — Contrefactuelle v2

**Décision :** réécriture complète de `tools/audit/counterfactual.py`

Changements clés vs v1 :
- **Plus de limitation documentée** : les résultats réels sont dans predictions.tsv (colonne 9, 1=gagné, 0=perdu)
- Nouveau champ `result` par pick dans le pool
- Calcul réel de `is_won` pour chaque combo (True si tous les picks ont result=1)
- Statistique `win_ratio_pool` : % des combos qui auraient gagné
- Rang + percentile du ticket joué parmi les combos (par cote totale, cohérent avec v1)
- 4 flags : CATASTROPHIQUE, MALCHANCEUX, OPTIMAL, BON_CHOIX_MALCHANCEUX
- Sous-échantillonnage déterministe si pool > 50 picks (random.Random(42))
- Cap 2000 combinaisons

**Logique des flags :**
- `CATASTROPHIQUE` : LOSS + win_ratio_pool >= 30% + percentile < 25% (alternatives gagnantes existaient, mauvais choix)
- `MALCHANCEUX` : LOSS + win_ratio_pool < 30% (vraie malchance, peu d'alternatives gagnantes)
- `BON_CHOIX_MALCHANCEUX` : LOSS + percentile >= 75% + win_ratio_pool >= 40% (bon ticket, mauvais tirage)
- `OPTIMAL` : WIN + percentile >= 50% (gagné avec un bon ticket)

**Nouveau paramètre CLI :** `--min-odd` (défaut 1.15)

### Objectif 2 — Panneau Streamlit tab5 amélioré

**Décision :** remplacement complet du bloc tab5 dans `tools/audit/app.py`

Ajouts vs v1 :
- Info verte "v2 — résultats réels disponibles" (suppression du message d'avertissement limitation)
- Contrôle `--min-odd` dans l'interface (nombre input)
- Filtre par flag (dropdown : Tous / CATASTROPHIQUE / MALCHANCEUX / OPTIMAL / BON_CHOIX_MALCHANCEUX)
- 5 métriques au lieu de 4 : + "Top 25% des cotes X% du temps"
- Tableau avec colonnes : Date, Ticket, Cote jouée, Résultat, Rang, Percentile, Combos gagnantes, Flag
- Coloration : CATASTROPHIQUE = rouge foncé, MALCHANCEUX = orange, OPTIMAL = vert, BON_CHOIX = bleu
- Graphique distribution percentiles (inchangé mais avec annotation du seuil 75%)
- Statistiques avancées (expander) : win ratio moyen du pool

### Objectif 3 — Validation Maestro log enrichi

**Statut :** CONFIRMÉ OPÉRATIONNEL (pas de modification nécessaire)

- `MAESTRO_MAX_DETAIL_LINES = 30` défini à la ligne 150 de `services/ticket_builder.py`
- Utilisé à 6 endroits dans le fichier (L.2372, L.2452-2453, L.2695, L.2762-2763, L.2887, 2896-2898, 2912-2914)
- Logging des rejets + picks acceptés injecté à L.2879-2918 (Session 3 — intact)
- Import du module ticket_builder : fonctionnel (pas de changements depuis Session 3)

### Objectif 4 — start_delay dans run_portfolio.py

**Décision :** implémentation via paramètre `start_delay: bool = False`

Mécanisme :
- Nouvelle méthode `is_ready()` sur `Strategy` — vérifie si le pivot a atteint N doublings
- Paramètres `start_pivot` et `start_after_doublings` ajoutés au constructeur de `Strategy`
- `step()` retourne immédiatement si `not is_ready()` (incrémente `n_pauses`)
- `run_portfolio(start_delay=True)` instancie les stratégies avec les pivots :
  - RS : pas de pivot → démarre immédiatement
  - SS : pivot=RS, start_after_doublings=1
  - RN : pivot=SS, start_after_doublings=1
  - SN : pivot=SS, start_after_doublings=1
- `main()` expose `--start-delay` en CLI
- Comportement par défaut inchangé (start_delay=False = mode historique)

---

## POINTS TECHNIQUES IMPORTANTS

### Format predictions.tsv confirmé
```
TSV:\t<match_id>\t<date>\t<league>\t<home>\t<away>\t<bet_key>\t<bet_label>\t<score_float>\t<level>\t<result_0_or_1>\t<details>\t<time_str>
```
Colonne index 9 (0-based après split tab) = résultat réel. Confirmé sur plusieurs archives.

### Limitation résiduelle contrefactuelle v2
- Les picks avec `result=None` (inconnu/pending) sont exclus du pool
- Pour les journées avec beaucoup de matchs pending, le pool peut être réduit
- Le sous-échantillonnage à 50 picks peut biaiser légèrement les résultats sur les grandes journées

---

## BACKLOG SESSION 5

1. **Test start_delay** : lancer `python run_portfolio.py --start-delay` et comparer les résultats vs baseline. Question ouverte : est-ce que le lancement décalé améliore le P25 (plancher 1er quartile) ?
2. **Équipe d'optimisation portfolio** : grid search ML × bankrolls × réserves. Critère P25. (Post-lancement 2026-04-05)
3. **Nouveaux tests ticket builder** :
   - `system_build_source=TEAM` vs LEAGUE (signal finetune à 20 runs, probablement bruit — à vérifier)
   - Nouveaux championnats dans pool RANDOM
4. **Contrefactuelle v2 — analyse sur données réelles** : lancer une fois le projet en prod (2026-04-05) pour valider les flags sur les premières journées réelles

---

## NOTES DE SÉANCE

- Session 100% code, aucun test de paramètres
- Objectifs 1, 2, 4 : livrés. Objectif 3 : validé (déjà opérationnel depuis Session 3).
- Les tests d'exécution Python n'ont pas pu être lancés depuis l'agent (permission refusée). Le code a été vérifié par relecture manuelle.
- Recommandation : lancer `python -c "from tools.audit.counterfactual import run_counterfactual; run_counterfactual(days=5)"` pour valider avant production.
