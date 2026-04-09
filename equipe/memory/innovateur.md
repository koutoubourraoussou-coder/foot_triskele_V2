# MÉMOIRE — L'Innovateur
*Mise à jour automatique après chaque session*

---

## Identité forgée par l'expérience

Je suis l'Innovateur du BCEA. J'explore ce qui n'a pas été fait. Je me trompe parfois — c'est prévu. Chaque erreur ferme un chemin et en ouvre un autre.

---

## Sessions passées

### Session 1 — 2026-04-04 — global_bet_min_winrate=0.50 vs 0.65
- Contribution clé : découverte que `_random_accept_pick()` utilise `league_bet_min_winrate`, pas `global_bet_min_winrate` → le signal RANDOM à 20 runs était de la variance pure, pas un signal indirect réel
- J'ai retracté mon argument "effet indirect réel sur SAFE RANDOM" : sans mécanisme explicite dans le code, ce n'est pas une inférence défendable
- J'ai admis honnêtement le taux de faux positifs (50-70%) de notre procédure de finetune sur k=5 valeurs à 20 runs
- Contribution durable : proposition du filtre Bonferroni (delta > +2.5 pour k=5 à 20 runs) et des tests séquentiels 2-par-2

### Session 2 — 2026-04-04 — Combinaisons random_build_source × random_select_source
- Vérification code approfondie de `filter_effective_random_pool()` et `_random_accept_pick()` dans ticket_builder.py
- Découverte : **incohérence TEAM build entre filtre pool et gate construction** — `filter_effective_random_pool()` utilise `dec >= team_min_decided` (6), mais `_random_accept_pick()` utilise `dec > 0` (1 minimum). Impact pratique limité (pool déjà pré-filtré), mais asymétrie documentée.
- Hypothèse proposée : **LEAGUE/TEAM** (build LEAGUE, select TEAM) comme combinaison non testée potentiellement intéressante — LEAGUE build maximise le pool via WR ligue, TEAM select affine par qualité d'équipe.
- Mécanisme explicite vérifié : `_random_ticket_final_score()` sépare bien LEAGUE (score par WR ligue) et TEAM (score par WR équipes) pour la sélection finale.
- RÉSULTATS (N=50 runs) :
  - TEAM/TEAM baseline : ×56.69 SAFE ×mult, WR 71.8%, ruine 0%
  - TEAM/LEAGUE : ×64.91, σ=57.20, WR 60.6%, ruine 0% — t=0.83σ (non significatif)
  - LEAGUE/TEAM : ×24.27, ruine 8%
  - LEAGUE/LEAGUE : ×14.68, ruine 32%, WR 49.0%
- VERDICT : **TOUTES REJETÉES. TEAM/TEAM baseline confirmée.**
- RÉSULTAT POUR MON HYPOTHÈSE LEAGUE/TEAM : rejeté. Build LEAGUE dégrade le pool RANDOM — l'élargissement du pool par WR de ligue ne compense pas la précision du filtre TEAM post-Phase 7. Mon raisonnement sur "LEAGUE build maximise le pool" était mécaniquement correct mais les données ne confirment pas l'avantage.
- LEÇON : l'élégance théorique d'une combinaison n'est pas un prédicteur de performance. Le test a bien tranché.

---

## Idées proposées et leur destin

| Idée | Session | Verdict |
|------|---------|---------|
| global_bet_min_winrate=0.50 améliore le score (signal finetune +1.459) | 1 | REJETÉ — bruit pur à 100 runs |
| O25_FT hétérogène (FORT PLUS 72.7%, MEGA EXPLOSION 66.7%) — argument contre "famille faible" | 1 | VALIDÉ comme observation, mais pas assez pour contrer SAFE SYSTEM -4.4% |
| global_bet_min_winrate n'affecte pas RANDOM (vérification code) | 1 | VALIDÉ — acquis structurel permanent |
| Filtre Bonferroni : delta > +2.5 pour k=5 à 20 runs | 1 | ACCEPTÉ par le Validateur Froid — appliqué dès Session 2 |
| Tests séquentiels 2-par-2 (vs 5 valeurs simultanées) | 1 | ACCEPTÉ en principe — à implémenter |
| Incohérence TEAM build dans _random_accept_pick() vs filter_effective_random_pool() | 2 | DOCUMENTÉ — asymétrie réelle, impact pratique limité |
| LEAGUE/TEAM comme combinaison hybride non testée (hypothèse) | 2 | REJETÉ — build LEAGUE dégrade RANDOM (-57% SAFE ×mult, ruine 8%). Build TEAM confirmé supérieur. |
| TEAM_WIN est stabilisateur de séquences (déduction Test A vs Test B) | 6 | VALIDÉ comme observation — ruine +56% quand exclu, volume et SAFE stables. Rôle structurel documenté. |
| Plancher 5.6 doublings = propriété de O15+TEAM_SCORE seuls | 6 | VALIDÉ comme observation diagnostique |
| Test isolé HT05/HT1X séparément pour décomposer la contribution | 6 | EN ATTENTE — backlog secondaire, signal global déjà clos |

---

## Patterns détectés

- **La vérification du code prime sur l'intuition.** Ma découverte sur RANDOM en Session 1 a été la seule contribution durable — elle venait du code, pas d'une inférence. Confirmé Session 2 avec la découverte de l'asymétrie TEAM build.
- **Inférences sans mécanisme = à retirer.** "Effet indirect réel via l'interaction des séquences" sans mécanisme précis dans le code = formulation de confort. Ne plus jamais poser une hypothèse sans canal explicite.
- **Admettre franchement > défendre coûte que coûte.** La concession franche sur le taux de faux positifs et sur l'effet RANDOM indirect a renforcé ma crédibilité, pas affaibli.
- **La comparaison multi-paramètres entre profils ne permet pas d'isoler une contribution.** Le WR=89.1% du Profil #2 RANDOM peut venir de topk_size=3 plutôt que de LEAGUE build. Seul un test isolé tranche.

---

## Session 3 — 2026-04-05 — Implémentations code

### Maestro log enrichi
- **Fichier modifié :** `services/ticket_builder.py` L.2879-2918
- **Où :** dans `_build_tickets_for_one_day()`, au niveau 2 du Maestro, juste après le bloc de stats de pool existant
- **Ce qui est loggé :**
  1. Résumé agrégé par type de rejet (ex: `TEAM_LOW_SR×3 | GLOBAL_BET_LOW_SR×1`)
  2. Détail par pick rejeté : heure, match, famille de pari, raison complète
  3. Liste des picks acceptés (OK_WINDOW) avec leur poids de génération
- **Principe :** s'appuie sur `diag["REASONS"]` déjà produit par `_diagnose_pool()`, pas de nouvelle logique métier
- **Garde-fou :** limité à `MAESTRO_MAX_DETAIL_LINES` (30) lignes pour éviter les pavés

### Analyse contrefactuelle
- **Fichier créé :** `tools/audit/counterfactual.py`
- **Architecture :** script autonome + importé dynamiquement par app.py via `importlib.util`
- **Algorithme :** pour chaque match unique du pool, on garde le meilleur pick (odd max), puis on énumère toutes les combinaisons cross-match (C(N_matchs, 3) + C(N_matchs, 4)) avec cap à 5000 combinaisons
- **Métrique :** percentile de la cote totale du ticket joué dans la distribution des cotes candidates
- **Flags :**
  - `CATASTROPHIQUE` : LOSS + percentile ≤ 10% (mauvais ticket ET mauvais résultat)
  - `MALCHANCEUX` : LOSS + percentile ≥ 90% (bon ticket, mauvais résultat = malchance)
  - `TOP TICKET + WIN` : WIN + percentile ≥ 90% (bonne sélection et bon résultat)
- **Limitation structurelle documentée :** les picks non joués n'ont pas de résultat réel — la comparaison se fait sur la cote (proxy), pas sur le résultat réel

### Panneau Streamlit
- **Fichier modifié :** `tools/audit/app.py`
- **Ajout :** tab5 "Contrefactuel" — bouton "Lancer l'analyse", tableau coloré, distribution percentiles, export JSON
- **Import :** importlib.util.spec_from_file_location pour charger counterfactual.py sans modifier PYTHONPATH

## Session 5 — 2026-04-05 — Correction erreur critique contrefactuelle

### Erreur détectée et corrigée [Claude corrige Session 4]
- **Ce qui était faux :** Session 4 avait conclu que `predictions.tsv` col 9 = résultat réel (1=gagné, 0=perdu)
- **Réalité :** col 9 = `is_candidate` (qualité du pick). Tous les picks jouables ont is_candidate=1 → 100% de "victoires" factices
- **Preuve :** Tondela vs Rio Ave O15_FT : is_candidate=1 dans predictions.tsv, mais résultat réel = ❌ LOSS (score 0-1)
- **Correction v3 :** `counterfactual.py` réécrit pour utiliser `results.tsv` (scores FT+HT réels) avec évaluation directe des paris

### Résultats v3 réalistes
| Date | O15 réel | Combos gagnantes |
|------|----------|-----------------|
| 2026-03-09 | 60% (3/5) | 7.1% — MALCHANCEUX |
| 2026-03-08 | 71% (35/49) | 34.1% — OPTIMAL ✓ |
| 2026-03-01 | 80% (41/51) | 31.2% — mixte |
| 2026-02-22 | 76% (39/51) | 51.8% — CATASTROPHIQUE ⚠️ |
| 2026-02-21 | 79% (53/67) | 59.4% — CATASTROPHIQUE+OPTIMAL |

## Session 6 — 2026-04-05 — excluded_bet_groups

### Contributions à la discussion

**Observation 1 — décomposition Test A vs Test B :**
Comparaison des deux tests pour isoler l'effet marginal de l'exclusion de TEAM_WIN :
- Volume tickets : quasi-stable (71.0 → 71.1) — TEAM_WIN ne contribue pas au volume absolu final dans les tickets sélectionnés.
- SAFE ×mult : quasi-stable (×14.61 → ×14.16) — TEAM_WIN ne génère pas de profit marginal brut significatif.
- NORM ruine : aggravée (28% → 36%) — TEAM_WIN réduit les séries de défaites.

Interprétation proposée et retenue par le Validateur Froid : TEAM_WIN est un stabilisateur de séquences, pas un générateur de volume.

**Observation 2 — plancher à 5.6 doublings :**
Les deux tests plafonnent à exactement 5.6 doublings malgré leurs compositions différentes. Ce plancher est une propriété du pool O15+TEAM_SCORE uniquement — indépendant de TEAM_WIN.

**Pistes proposées (backlog) :**
1. Test isolé HT05 seul vs HT1X seul — compare_variants.py
2. Seuillage par niveau de confiance HT05/HT1X (FORT PLUS uniquement) — filtrer sans exclure
3. Analyse WR réel HT1X sur archive complète via contrefactuelle v3

### Verdict sur mes hypothèses

Le signal est négatif univoque — les exclusions dégradent. Mes pistes sont des questions diagnostiques de deuxième ordre, pas des alternatives au verdict.

---

## Pistes en cours d'exploration

- ~~**[TEST BCEA S2]** random_build_source × random_select_source~~ → **CLOS** — toutes variantes rejetées, TEAM/TEAM confirmé optimal
- ~~Maestro log enrichi~~ → **CLOS SESSION 3**
- ~~Analyse contrefactuelle v1~~ → **CLOS SESSION 3** (comparaison par cote)
- ~~**Contrefactuelle v2**~~ → **CLOS SESSION 4 — ERREUR** (is_candidate ≠ résultat réel)
- ~~**Contrefactuelle v3**~~ → **CLOS SESSION 5** — results.tsv, scores réels, flags significatifs
- ~~**start_delay portfolio**~~ → **CLOS SESSION 4** — `run_portfolio.py --start-delay` implémenté. À tester vs baseline.
- RANDOM O15 avec filtre winrate léger — non testé
- Poids composite 70/30 — non testé
- Nouveaux types de paris API
- **[EN COURS]** Test `--start-delay` : comparer P25 vs baseline sur 100 runs
- Test isolé `excluded = ["HT05"]` seul — compare_variants.py (priorité basse, signal fort déjà clos)
- Test isolé `excluded = ["HT1X"]` seul — compare_variants.py (priorité basse)
- Seuillage niveau de confiance HT05/HT1X (FORT PLUS uniquement) — développement requis (priorité basse)

---

## Mes biais connus (pour les corriger)

- Tendance à l'enthousiasme sur les idées nouvelles même sans données
- À surveiller : toujours ancrer une proposition dans une logique testable
- Nouveauté Session 2 : attention aux "belles combinaisons" — LEAGUE/TEAM paraît élégante en théorie, mais l'élégance n'est pas un critère. Le test tranche.
