# Table de Session — BCEA Session 3
**Date :** 2026-04-05
**Type :** SESSION CODE
**Animateur :** Agent Principal
**Ordre du jour :** Développement de deux outils (Maestro log enrichi + Analyse contrefactuelle)

---

## Présents

- Agent Principal (coordinateur)
- Réducteur de Bruit (priorisation, scope)
- Sceptique (risques, hypothèses)
- Innovateur (architecture, implémentation)

---

## Contexte de production

Le Fondateur est en production réelle depuis 2026-04-05 (bankroll 100€, mise initiale 7€). Tout code livré aujourd'hui sera utilisé en conditions réelles. La priorité est la stabilité.

---

## Agenda

### Item 1 — Maestro log enrichi [PRIORITÉ 1]
**Source :** Backlog Réducteur + mémoire Innovateur
**Portée :** Modifier `services/ticket_builder.py` pour logger les rejets de picks dans le log Maestro existant
**Critère de succès :** `python -c "import services.ticket_builder"` passe, le log contient les raisons de rejet lors d'un run

### Item 2 — Analyse contrefactuelle [PRIORITÉ 2]
**Source :** Backlog Réducteur (Fondateur, 2026-04-04)
**Portée :** Script `tools/audit/counterfactual.py` + panneau Streamlit dans `tools/audit/app.py`
**Critère de succès :** Le script tourne sur l'archive, le panneau s'affiche sans erreur

---

## Décisions préalables (avant code)

1. Le Maestro log enrichi est un changement ciblé dans `_build_tickets_for_one_day()` au niveau 2 du Maestro — l'infrastructure est déjà là (REASONS dans `_diagnose_pool()`)
2. L'analyse contrefactuelle s'appuie sur les `predictions.tsv` dans l'archive (données brutes) et les `verdict_post_analyse_*.txt` (résultats réels)
3. Les deux items sont indépendants — le Maestro en premier car plus rapide et à impact immédiat en production

---

## Notes en cours de session

*(remplies au fil de l'implémentation)*
