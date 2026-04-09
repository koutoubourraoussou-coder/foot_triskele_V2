# BCEA — Session 1 — 2026-04-04
## Sujet : Confirmation global_bet_min_winrate=0.50

---

## AGENTS IMPLIQUÉS
- Agent Principal (coordinateur, validateur de session)
- Réducteur de Bruit (priorisation)
- Sceptique (analyse du signal)
- Testeur (100 runs)
- Scribe (ce document)

---

## ÉTAPE 1 — BILAN
Première session. Pas de session précédente.

Contexte :
- Profil champion : Amélioré #1 (deployé 2026-04-02)
- Données : 61 jours de backtest
- Outils disponibles : compare_variants.py, finetune_profile.py, run_portfolio.py

---

## ÉTAPE 2 — MATIÈRE PREMIÈRE
Issu du travail Cartographe + Questionnaire (2026-04-04) :
- Carte complète du système (14 sections)
- 50+ questions classées par impact

---

## ÉTAPE 3 — PRIORISATION (Réducteur de Bruit)

**Candidates évaluées :**

| Hypothèse | Impact | Coût | Statut précédent |
|-----------|--------|------|-----------------|
| global_bet_min_winrate=0.50 | FORT | RAPIDE | Signal +1.459 à 20 runs — non confirmé |
| topk_uniform_draw=False | FORT | RAPIDE | REJETÉ à 2 runs (42.9 vs 22.1) — signal massif |
| system_build_source=TEAM | FORT | RAPIDE | Effacé à 100 runs — bruit confirmé |

**Décision Réducteur :**
- topk_uniform_draw=False → ÉCARTÉ (déjà rejeté clairement)
- system_build_source=TEAM → ÉCARTÉ (déjà testé à 100 runs, bruit confirmé)
- **global_bet_min_winrate=0.50 → RETENU. Test 100 runs.**

---

## ÉTAPE 4 — DÉBAT (Sceptique vs Innovateur)

### Hypothèse : global_bet_min_winrate=0.50 améliore le profil champion

**Sceptique :**
- 20 runs = fragile. +1.459 est un petit delta.
- La relation est non-monotone (0.50 > 0.55 mais 0.55 < 0.60 < 0.65 dans le baseline) — suspect.
- Abaisser le seuil global à 0.50 signifie accepter des familles de paris avec seulement 50% de WR global — est-ce vraiment de la qualité ?
- Risque : plus de tickets = plus de variance = score moyen mieux mais queue de distribution pire.
- Test adversarial : regarder le P10 et le P25 (plancher), pas seulement la moyenne.

**Innovateur :**
- Plus permissif = plus de volume de tickets = plus d'opportunités de doublings.
- Le finetune montre une courbe en U : trop strict (0.70) = mauvais, trop permissif (0.50) = légèrement mieux que la baseline actuelle.
- La logique : le filtre global (0.65) rejetait peut-être des familles de paris qui sont bonnes dans certaines ligues mais mauvaises dans d'autres — le filtre ligue (0.60) gère déjà ça plus finement.
- Hypothèse : le filtre global à 0.65 est redondant avec le filtre ligue à 0.60. Descendre à 0.50 laisse le filtre ligue faire le vrai travail.

**Synthèse Agent Principal :**
Signal fragile mais logique défendable. Test 100 runs lancé. Métriques surveillées : SAFE_mult moy, SAFE P25, WR, ruine%.

---

## ÉTAPE 5 — TEST

**Configuration :**
- Baseline : global_bet_min_winrate=0.65 (profil champion actuel)
- Variante : global_bet_min_winrate=0.50
- N_runs : 100
- Script : compare_variants.py
- Date lancement : 2026-04-04

**Fichier résultats attendu :** data/optimizer/compare_variants_2026-04-04_*.txt

---

## ÉTAPE 6 — RÉSULTATS
*(en attente — test en cours)*

---

## ÉTAPE 7 — VERDICT
*(en attente)*

---

## ÉTAPE 8 — ARCHIVAGE
*(à compléter après verdict)*

---

## QUESTIONS EN SUSPENS (pour sessions suivantes)
1. RANDOM O15 avec filtre winrate léger (WR > 0.55) — requiert modification code
2. Poids composite 70/30 — requiert modification post_analysis_core.py
3. Maestro log enrichi — logging des raisons de rejet détaillées
4. Nouveaux types de paris API non couverts
5. Recency weighting sur les rankings

---

*Scribe BCEA — Session ouverte 2026-04-04*
