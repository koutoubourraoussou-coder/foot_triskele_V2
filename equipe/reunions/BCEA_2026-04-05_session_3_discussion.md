# BCEA — Session 3 — Discussion
**Date :** 2026-04-05

---

## Réducteur de Bruit

**Priorisation :**
Les deux items du backlog sont traités dans cet ordre :

1. **Maestro log enrichi en premier** — impact en production immédiat (le Fondateur est live depuis 2026-04-05), changement minimal dans le code existant, aucun risque de régression car on n'ajoute que des `maestro_lines.append()` dans un bloc conditionnel déjà isolé

2. **Analyse contrefactuelle en second** — outil de diagnostic historique, pas time-sensitive, mais l'architecture est plus complexe (nouveau script + nouveau panneau)

**Note sur le scope :** La contrefactuelle "v1" avec cotes comme proxy est livrable dans cette session. La "v2" avec résultats réels des picks non joués nécessiterait un enrichissement de l'archive (stocker les résultats match par match, pas seulement les legs des tickets joués) — c'est un projet plus long, documenté pour une future session.

---

## Sceptique

**Risques identifiés avant implémentation :**

1. **Verbosité du log des rejets** — risque de pavés illisibles si des centaines de picks sont rejetés par journée. *Mitigation : cap à `MAESTRO_MAX_DETAIL_LINES` (30) + résumé agrégé par type en tête*

2. **Disponibilité de `predictions.tsv` dans toutes les archives** — *Vérifié : 70 fichiers présents pour 33 dossiers d'analyse. OK.*

3. **La contrefactuelle "tous les tickets possibles" est non-triviale** — le ticket dépend d'un tirage aléatoire (Top-K uniforme). La liste exhaustive des combinaisons est calculable mais pas équivalente au tirage du système. *Mitigation : documentation claire de la limitation + utilisation de la cote totale comme proxy (signal pertinent pour "était-ce un bon ticket ?")*

4. **Certains jours n'ont aucun ticket joué** — "Aucun ticket." dans le rapport. *Géré : le script retourne `{"status": "NO_TICKET"}` sans crasher*

5. **Format de `tickets_report.txt` potentiellement variable** — les anciens tickets n'ont pas le suffixe `_SYS` dans leur id. *Mitigation : regex non stricte sur le format de l'id*

**Verdict post-implémentation :** Les 5 risques sont mitigés. Le code ne crashe pas sur les cas vides ou les formats variables.

---

## Innovateur

**Architecture Maestro enrichi :**

L'approche la plus simple était la meilleure : `_diagnose_pool()` retourne déjà `{"REASONS": {pick_key: raison_str}, "PERF_REJECT": [...], "OK_WINDOW": [...]}`. Il suffisait d'exploiter ce dict dans le bloc `if mlevel >= 2:` de `_build_tickets_for_one_day()`.

Pas de nouvelle logique, pas de nouveau paramètre. Juste du formatage.

**Architecture contrefactuelle :**

Choix de l'import dynamique (`importlib.util.spec_from_file_location`) plutôt que d'un import standard pour éviter de modifier le PYTHONPATH de l'app Streamlit. C'est un pattern légèrement inhabituel mais documenté et robuste.

L'algorithme de combinaisons utilise une heuristique clé : pour chaque match, on ne garde que **le meilleur pick** (odd max) avant de faire les combinaisons cross-match. Ça réduit drastiquement l'espace de recherche tout en gardant la cote maximale par match (pessimiste pour le pool — les candidats calculés sont ceux avec les meilleures cotes disponibles).

**Points d'amélioration identifiés pour une v2 :**
- Stocker les résultats individuels des matchs dans l'archive (permettrait la contrefactuelle avec résultats réels)
- Ajouter le score estimé (winrate × pick) comme second axe de comparaison en plus de la cote
- Visualisation temporelle des percentiles (courbe jour par jour)
