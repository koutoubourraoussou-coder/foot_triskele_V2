k# ARCHIVE — Session 1 — BCEA — 2026-04-04
*Document Scribe — Transcription technique complète*

---

## BILAN — Contexte de séance

**Paramètre examiné :** `global_bet_min_winrate`
**Hypothèse soumise :** la valeur 0.50 améliore le profil champion (baseline = 0.65)
**Origine du sujet :** laissé explicitement en suspens dans LABORATOIRE.md. Signal observé lors du finetune du 2026-04-02.
**État au démarrage :** test à 100 runs (compare_variants.py) en cours en arrière-plan.

---

## CARTE — Données d'entrée

**Finetune 20 runs (2026-04-02) :**
- 0.50 → score composite = 30.611
- 0.65 → score composite = 29.153
- Delta : +1.459 en faveur de 0.50

**Classement à 20 runs :** 0.50 > 0.60 > 0.65 > 0.55 > 0.70

**Ce que fait le paramètre :** seuil minimum de win rate global pour qu'une famille de paris soit acceptée dans le mode SYSTEM. À 0.50, débloque théoriquement O25_FT (WR réel = 0.514) et TEAM_WIN_FT (WR réel = 0.612).

**Historique :** le paramètre est passé de 0.62 à 0.65 lors de la construction du profil champion (Phase 3 — avec trois autres paramètres simultanément). La justification retenue à l'époque : filtre plus exigeant = qualité supérieure.

**Métriques disponibles à 20 runs :**
- WR SYSTEM : 0.675 (0.50) vs 0.686 (0.65)
- SAFE SYSTEM ×mult : 29.21 (0.50) vs 30.10 (0.65)
- SAFE RANDOM ×mult : 46.98 (0.50) vs 42.44 (0.65)
- NORM ruine à 20 runs : ~25% (0.50) vs ~15% (0.65)
- Nombre de tickets SYSTEM : 86 dans les deux variantes
- Nombre de tickets RANDOM : 71 dans les deux variantes

---

## QUESTIONS / HYPOTHÈSES

**Hypothèse principale :** global_bet_min_winrate = 0.50 est structurellement supérieur à 0.65.

**Contre-hypothèse (Sceptique) :** le signal à 20 runs est un artefact stochastique. 2-3 runs RANDOM avec des paris O25_FT chanceux ont gonflé la moyenne. Sur 100 runs, la variance se rétablit et l'avantage s'efface ou s'inverse.

**Hypothèse Innovateur — Effet de composition Top-K SYSTEM :** à 0.50, O25_FT entre dans la compétition du pool SYSTEM (308 paris sur 61 jours) et modifie les scores comparatifs dans le Top-K, faisant émerger des tickets différents — même s'il est rarement sélectionné au final.

**Question structurelle soulevée en séance :** quel est le taux de faux positifs de la procédure de finetune sur 20 runs avec 5 valeurs testées simultanément ? (Posée par le Sceptique, chiffrée par l'Innovateur : entre 50% et 70%.)

**Fait nouveau établi en séance (Innovateur, vérification code) :**
- `_random_accept_pick()` (ticket_builder.py, ligne 2481) utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. Le pool RANDOM n'est pas affecté par ce paramètre.
- `TEAM_WIN_FT` n'existe pas dans ticket_builder.py. La normalisation mappe vers `TEAM1_WIN_FT` / `TEAM2_WIN_FT`, dont `min_level: null` dans min_level_by_bet.json — absentes du pool candidat pour des raisons antérieures au paramètre testé.
- `_global_bet_is_eligible()` (ligne 1109) utilise bien `global_bet_min_winrate` pour le mode SYSTEM uniquement.

---

## PRIORISATION — Réducteur de Bruit

**Agent :** Réducteur de Bruit
**Rôle :** ouverture de séance, sélection du sujet

Le Réducteur écarte les sujets fermés (`topk_uniform_draw`, `system_build_source`) et identifie `global_bet_min_winrate = 0.50` comme le seul sujet méritant la séance : explicitement en suspens dans LABORATOIRE.md, signal existant à 20 runs, test rapide.

**Décision :** séance centrée sur ce seul paramètre.

---

## DÉBAT — Sceptique vs Innovateur

### Tour 1 — Sceptique (analyse initiale)

**Points de vigilance :**

1. **Volume insuffisant.** 20 runs sous le seuil de confiance. Variance énorme (NORM va de ×0 à ×3695 sur 200 runs). Delta +1.459 statistiquement indistinguable du bruit.

2. **Contradiction historique.** Le passage 0.62→0.65 a été fait avec la justification "filtre plus exigeant = qualité supérieure". Passer à 0.50 revient sur ce principe.

3. **Volume ≠ qualité.** WR SYSTEM baisse déjà à 0.50 (0.675 vs 0.686). Le score composite monte via des NORM volatils, pas via une amélioration structurelle.

4. **SAFE SYSTEM régresse.** SAFE ×mult passe de ×30.10 à ×29.21 à 0.50. -3% sur la métrique de survie martingale, la plus importante pour le déploiement réel.

5. **Overfitting possible.** 61 jours peuvent contenir une période offensive spécifique gonflant O25_FT et TEAM_WIN_FT localement.

**Contre-hypothèse centrale :** signal artefact stochastique. 2-3 runs RANDOM avec paris O25_FT chanceux ont gonflé la moyenne.

**Tests adversariaux posés :**
- Si SAFE ×mult(0.50) < SAFE ×mult(0.65) sur 100 runs → rejet même si score composite légèrement positif
- Si WR(0.50) < WR(0.65) → filtre permissif admet des paris plus faibles
- Si pire_série(0.50) > pire_série(0.65) → familles débloquées introduisent de l'instabilité

**Métriques à surveiller (ordre de priorité) :**
1. SAFE ×mult (déploiement réel)
2. WR global (qualité tickets)
3. Pire série (risque martingale)
4. NORM ruine (déjà à 25% à 20 runs vs 15% à 0.65)

**Verdict provisoire :** SIGNAL FRAGILE
**Conditions d'upgrade :** delta > +1.0 sur 100 runs ET SAFE(0.50) ≥ SAFE(0.65)
**Conditions de downgrade :** SAFE(0.50) < SAFE(0.65) OU delta < +0.3

**Question structurelle posée :** quel est le taux de faux positifs de la procédure de finetune sur 20 runs avec 5 valeurs testées simultanément ? Non calculé. Estime à 80% la probabilité qu'un imposteur soit en tête parmi 5 candidats.

---

### Tour 1 — Innovateur (réponse au Sceptique)

**Point 1 — Argument historique : vrai mais incomplet.**

Le passage 0.62→0.65 n'a jamais été testé en isolation. C'était l'une des quatre améliorations simultanées de la Phase 3 (avec `two_team_high`, `league_bet_require_data`, `league_bet_min_winrate`). L'attribution causale n'est pas prouvée. Le gain peut venir entièrement de `two_team_high 0.80→0.90`, jamais testé séparément.

Le classement à 20 runs est non-monotone : 0.50 > 0.60 > 0.65 > 0.55 > 0.70. Ce n'est pas une tendance linéaire "plus strict = mieux" — c'est une courbe avec un optimum local. L'argument d'historique ne peut s'appliquer à une courbe non-linéaire.

**Concession :** l'historique est une mise en garde légitime. Pas une preuve — seulement un prior.

**Point 2 — O25_FT et TEAM_WIN_FT dans les tickets RANDOM : non, pas comme supposé.**

Après vérification dans ticket_builder.py :
- `_random_accept_pick()` (ligne 2481) utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. La porte RANDOM ne change pas à 0.50.
- Le terme `TEAM_WIN_FT` n'existe pas dans ticket_builder.py. Il est absent du pool candidat pour des raisons antérieures au paramètre.
- `_global_bet_is_eligible()` (ligne 1109) utilise bien `global_bet_min_winrate` pour SYSTEM, mais le nombre de tickets SYSTEM reste 86 dans les deux variantes — effet sur le volume marginal, probablement filtré en amont par d'autres critères.

**Implication :** si O25_FT et TEAM_WIN_FT ne sont pas dans les tickets à 0.50, l'explication causale du Sceptique ("mauvaises familles entrées") est affaiblie. L'hypothèse stochastique reste possible, mais pas via ce mécanisme.

**Point 3 — Hétérogénéité interne d'O25_FT.**

| Niveau | WR O25_FT |
|--------|-----------|
| KO | 40.4% |
| FAIBLE | 38.5% |
| MOYEN | 47.2% |
| MOYEN PLUS | 48.8% |
| FORT | 53.1% |
| FORT PLUS | 72.7% |
| TRÈS FORT | 53.3% |
| MEGA EXPLOSION | 66.7% |

Le WR global de 51.4% est une moyenne sur tous niveaux confondus. Les niveaux FORT PLUS et MEGA EXPLOSION dépassent 0.65. Si le système filtre en amont vers les niveaux élevés, la famille retenue n'est pas "la moins performante".

**Point 4 — Signal SAFE RANDOM.**

SAFE RANDOM monte de +10.7% à 0.50 (×46.98 vs ×42.44). Posé comme signal indirect possible via "l'interaction des séquences journalières entre SYSTEM et RANDOM".

**Concessions de l'Innovateur (après pression du Sceptique, tour 2) :**
- Sur le taux de faux positifs : estimé entre 50% et 70% pour la procédure actuelle. Delta de +1.459 entièrement compatible avec la sélection du maximum parmi 5 imposteurs (espérance ≈ μ + 1.16σ). Concession franche.
- Sur l'effet indirect RANDOM : aucun mécanisme explicite défendable identifié. L'argument "effet indirect réel" retiré. Sur 20 runs avec tickets structurellement identiques, un écart de 10.7% sur SAFE constitue précisément de la variance.

**Propositions d'amélioration de la procédure de finetune :**
- Option A — Correction Bonferroni : exiger delta > ~+2.5 sur 20 runs pour k=5 valeurs (α/k = 0.01). Le delta de +1.459 n'aurait pas franchi ce seuil.
- Option B — Tests séquentiels (recommandée) : tester d'abord le meilleur candidat contre baseline en duel direct sur 50 runs, puis confirmer sur 50 runs supplémentaires.
- Option C — Walk-forward validation : diviser les 61 jours en deux sous-périodes, finetune sur la première, validation sur la seconde.

---

### Tour 2 — Sceptique (réponse à l'Innovateur)

**Concessions du Sceptique :**

1. **RANDOM : argument retiré.** L'Innovateur a vérifié dans le code. `_random_accept_pick()` utilise `league_bet_min_winrate`, pas `global_bet_min_winrate`. L'argument "familles débloquées dans les tickets RANDOM" reposait sur une lecture incorrecte. Retiré.

2. **Hétérogénéité d'O25_FT : argument insuffisant.** Citer WR global = 0.514 comme preuve de faiblesse était une erreur analytique. Les niveaux FORT PLUS (72.7%) et MEGA EXPLOSION (66.7%) sont au-dessus du seuil 0.65. Si les filtres amont sélectionnent uniquement les niveaux élevés, la famille n'est pas "la moins performante". Concession franche.

**Ce qui tient encore :**

1. **SAFE SYSTEM régresse de -3%.** L'Innovateur confirme que `_global_bet_is_eligible()` agit sur SYSTEM. Le chiffre -3% (×30.10 → ×29.21) n'est pas contesté par l'Innovateur. Il est ignoré au profit de SAFE RANDOM.

2. **Déplacement d'attention nommé.** L'Innovateur construit son argument principal sur SAFE RANDOM (+10.7%) alors que ce canal n'est pas affecté par le paramètre. La métrique naturelle pour juger l'effet de `global_bet_min_winrate` est SAFE SYSTEM — et SAFE SYSTEM régresse.

3. **"Effet indirect RANDOM" sans mécanisme.** "Interaction des séquences journalières" est une formulation sans canal explicite. Deux séries de 20 runs d'une distribution identique peuvent produire +10.7% d'écart sur SAFE — c'est la définition du bruit de variance.

4. **Taux de faux positifs non calculé.** Sur 5 candidats testés simultanément, probabilité que le vrai gagnant soit en tête : 20%. Probabilité qu'un imposteur soit en tête : 80%. Ce calcul n'a jamais été fait pour notre procédure de finetune. La confiance accordée à "0.50 est meilleur" n'est pas calibrée.

**Verdict maintenu :** SIGNAL FRAGILE. Raisons recentrées :
1. SAFE SYSTEM régresse -3% sur le canal directement affecté
2. SAFE RANDOM +10.7% avec tickets structurellement identiques = bruit de variance non réfuté
3. Absence de mécanisme explicite pour "l'effet indirect"
4. Taux de faux positifs structurel non calculé

**Conditions d'upgrade inchangées :** delta > +1.0 sur 100 runs ET SAFE SYSTEM(0.50) ≥ SAFE SYSTEM(0.65)

---

## TEST — Conditions exactes

**Paramètre testé :** `global_bet_min_winrate`
**Valeurs comparées :** 0.50 (variante) vs 0.65 (baseline = profil champion)
**Outil utilisé :** compare_variants.py
**N runs :** 100
**Métriques prioritaires (définies en amont par le Sceptique) :**
1. SAFE ×mult SYSTEM (métrique principale — survie martingale)
2. WR SYSTEM
3. NORM ruine SYSTEM
4. Pire série SYSTEM
5. Score composite SYSTEM
**Canal RANDOM :** exclu de l'interprétation causale (paramètre sans effet sur RANDOM, confirmé en séance)
**Période de données :** 61 jours

---

## RÉSULTATS — Chiffres bruts (100 runs)

### Mode SYSTEM — canal directement affecté par le paramètre

| Métrique | Baseline 0.65 | Variante 0.50 | Delta |
|---|---|---|---|
| SAFE ×mult | 29.25 | 28.02 | Baseline +4.4% |
| Win rate | 68.2% | 67.3% | Baseline +0.9 pts |
| NORM ruine | 10% | 15% | Baseline meilleur |
| Pire série | 6 | 10 | Baseline meilleur |
| Score composite | 14.829 | 14.212 | Baseline gagne |

### Mode RANDOM — canal NON affecté par le paramètre

Écarts observés = non interprétables causalement.
`global_bet_min_winrate` n'affecte pas `_random_accept_pick()`.
Toute différence RANDOM est du bruit de variance.

---

## VERDICT — Validateur Froid

**Agent :** Validateur Froid
**Date :** 2026-04-04
**Session :** 1

**Protocole vérifié :** OUI
- Métrique principale définie en amont par le Sceptique : SAFE ×mult SYSTEM
- 100 runs effectués
- Baseline et variante comparées sur les mêmes conditions

**VERDICT : REJETÉ**

**Raisons (critère ADN appliqué : "amélioration sur une métrique mais dégradation sur une autre plus importante → REJETÉ") :**
- La variante 0.50 dégrade SAFE ×mult SYSTEM de -4.4% sur 100 runs. Métrique de priorité absolue, sur le canal directement affecté par le paramètre.
- WR SYSTEM : -0.9 pts — dégradation cohérente avec l'introduction de familles à WR plus faible dans la sélection SYSTEM.
- NORM ruine : +50% (10% → 15%) — risque de ruine martingale aggravé.
- Pire série : 6 → 10 — instabilité accrue, problème concret pour le suivi réel.
- Score composite SYSTEM : -4.2% — défaite nette sur l'ensemble des métriques SYSTEM.
- La contre-hypothèse du Sceptique est validée : le signal à 20 runs était du bruit. Les conditions d'upgrade (SAFE SYSTEM ≥ baseline) ne sont pas remplies.

---

## ARCHIVAGE

**Décision :** `global_bet_min_winrate = 0.50` → REJETÉ le 2026-04-04.
**Valeur conservée dans le profil champion :** 0.65
**Instruction de retour :** ne pas retester ce paramètre avant au moins 6 mois ou changement majeur de dataset.
**À documenter dans LABORATOIRE.md :** "0.50 testé sur 100 runs, rejeté, baseline 0.65 confirmée."

---

## TABLEAU DE BORD SESSION

| Élément | Statut |
|---|---|
| Sujet traité | global_bet_min_winrate : 0.50 vs 0.65 |
| N runs atteint | 100 |
| Verdict | REJETÉ |
| Paramètre champion mis à jour | NON — 0.65 confirmé |
| Faits nouveaux établis | 2 (voir ci-dessous) |
| Procédure finetune | À améliorer (faux positifs 50-70%) |

**Faits nouveaux établis en séance :**
1. `global_bet_min_winrate` n'affecte pas le pool RANDOM (`_random_accept_pick()` utilise `league_bet_min_winrate`). Toute différence RANDOM lors de tests de ce paramètre est de la variance pure.
2. `TEAM_WIN_FT` n'existe pas dans ticket_builder.py. Absent du pool candidat pour des raisons antérieures au paramètre.

**Concessions actées :**
- Sceptique → a retiré l'argument "familles débloquées dans RANDOM" (erreur de lecture du code)
- Sceptique → a retiré l'argument "WR global O25_FT = 0.514 = faible" (moyenne non filtrée, hétérogénéité ignorée)
- Innovateur → a retiré l'argument "SAFE RANDOM = signal indirect réel" (aucun mécanisme explicite, variance pure)
- Innovateur → a concédé le taux de faux positifs de 50-70% pour la procédure de finetune à 20 runs sur 5 valeurs

---

## QUESTIONS EN SUSPENS

1. **Procédure de finetune :** le taux de faux positifs de 50-70% est un défaut de conception confirmé empiriquement par cette session. Quelle correction adopter en priorité pour les sessions suivantes ? (Options A/B/C proposées par l'Innovateur)

2. **Attribution causale Phase 3 :** le passage 0.62→0.65 du profil champion n'a jamais été testé en isolation. L'amélioration observée à l'époque peut venir entièrement de `two_team_high 0.80→0.90`. Ce point reste ouvert.

3. **O25_FT aux niveaux élevés :** les niveaux FORT PLUS (72.7%) et MEGA EXPLOSION (66.7%) d'O25_FT dépassent 0.65. Si un futur paramètre permettait de cibler uniquement ces niveaux, la famille pourrait être compétitive. Non exploité en séance.

4. **Graine RANDOM dans compare_variants.py :** mécanisme non vérifié. Si la graine n'est pas fixée de manière identique entre variantes, les séquences RANDOM ne sont pas comparables — point méthodologique à vérifier pour les sessions futures.

---

## À SOUMETTRE AU FONDATEUR

1. **global_bet_min_winrate = 0.65 confirmé.** La valeur 0.50 a été testée sur 100 runs et rejetée. SAFE SYSTEM régresse de -4.4%, NORM ruine passe de 10% à 15%, pire série passe de 6 à 10. Le profil champion ne change pas.

2. **Défaut de la procédure de finetune.** Taux de faux positifs estimé à 50-70% sur 20 runs avec 5 valeurs testées simultanément. Recommandation : toute sortie finetune à N ≤ 30 runs est classée SIGNAL CANDIDAT, pas signal validé. Test complémentaire à ≥ 100 runs requis avant toute modification du profil champion. Filtrage Bonferroni (delta > +2.5 pour k=5) comme garde-fou immédiat.

3. **Fait structurel documenté.** `global_bet_min_winrate` n'affecte pas le pool RANDOM. Toute différence observée sur les métriques RANDOM lors des tests de ce paramètre est de la variance pure et doit être ignorée comme signal causal.

4. **Session de référence.** Cette session constitue désormais un exemple calibrant pour évaluer les futurs signaux finetune : un delta de +1.459 sur 20 runs avec 5 valeurs testées est entièrement compatible avec la sélection du maximum parmi 5 imposteurs. Confirmation empirique à 100 runs.

---

*Archive Session 1 close — 2026-04-04 — Scribe BCEA*
