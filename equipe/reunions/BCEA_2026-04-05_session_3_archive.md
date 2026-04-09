# BCEA — Session 3 — Archive
**Date :** 2026-04-05
**Type :** SESSION CODE
**Durée :** Session complète
**Animateur :** Agent Principal

---

## Fichiers lus en début de session

1. `equipe/CULTURE.md` — identité BCEA
2. `equipe/_base.md` — socle commun
3. `LABORATOIRE.md` — mémoire du projet (lignes 1-338)
4. `equipe/memory/reducteur.md` — backlog items à traiter
5. `equipe/memory/sceptique.md` — patterns de risques connus
6. `equipe/memory/innovateur.md` — implémentations passées

## Fichiers analysés (code)

- `services/ticket_builder.py` — L.1-150 (constantes), L.2140-2220 (`_diagnose_pool`, `_random_reject_reason`), L.2800-2990 (`_build_tickets_for_one_day`, Maestro existant)
- `tools/audit/app.py` — structure des tabs, format des données, parseurs existants
- `archive/analyse_2026-02-01/*` — format `predictions.tsv`, `tickets_report.txt`, `verdict_post_analyse_tickets_report.txt`
- `archive/analyse_2026-03-01/*` — confirmation format récent, présence `tickets_maestro_log.txt`

## Décisions prises

### Maestro log enrichi
- **Approche choisie :** enrichir le niveau 2 existant du Maestro dans `_build_tickets_for_one_day()`, juste après le bloc de stats de pool
- **Raison :** `_diagnose_pool()` retourne déjà `REASONS` (dict pick_key → raison). Zéro nouvelle logique métier.
- **Agrégation :** résumé par type (préfixe avant `|` dans la raison), puis détail pick par pick, puis OK_WINDOW avec poids

### Analyse contrefactuelle
- **Approche choisie :** script autonome `counterfactual.py` + import dynamique dans `app.py`
- **Algorithme :** combinaisons cross-match (1 pick = 1 match, meilleur odd), C(N_matchs, 3) + C(N_matchs, 4), cap 5000
- **Limitation identifiée et documentée :** résultats réels des picks non joués indisponibles dans l'archive
- **Flags :** CATASTROPHIQUE (LOSS + bottom 10%), MALCHANCEUX (LOSS + top 10%), TOP TICKET + WIN

## Chronologie des modifications

1. Création `equipe/reunions/BCEA_2026-04-05_session_3_table.md`
2. Analyse du code (ticket_builder.py + app.py + archives)
3. Patch `services/ticket_builder.py` L.2879-2918 (Maestro enrichi)
4. Vérification syntaxique du patch
5. Création `tools/audit/counterfactual.py` (script autonome complet)
6. Ajout tab5 dans `tools/audit/app.py` + import dynamique de counterfactual.py
7. Correction `st.rerun()` orphelin en fin de fichier
8. Mise à jour `equipe/memory/reducteur.md`
9. Mise à jour `equipe/memory/innovateur.md`
10. Mise à jour `LABORATOIRE.md`

## Fichiers modifiés / créés

| Fichier | Opération | Description |
|---------|-----------|-------------|
| `services/ticket_builder.py` | Modifié | L.2879-2918 : logging enrichi des rejets + picks acceptés |
| `tools/audit/counterfactual.py` | Créé | Script analyse contrefactuelle (CLI + lib) |
| `tools/audit/app.py` | Modifié | Tab5 "Contrefactuel" ajouté |
| `equipe/reunions/BCEA_2026-04-05_session_3_table.md` | Créé | Table de session |
| `equipe/memory/reducteur.md` | Modifié | Items Session 3 clos, Session 3 documentée |
| `equipe/memory/innovateur.md` | Modifié | Implémentations Session 3 documentées |
| `LABORATOIRE.md` | Modifié | Section "Développement requis" mise à jour |

## Découvertes dans le code

1. **`_diagnose_pool()` retourne déjà `REASONS`** — l'infrastructure était entièrement là, il manquait juste l'exploitation du dict dans le Maestro log
2. **Certaines archives récentes n'ont aucun ticket joué** (analyse_2026-03-12, 26) — "Aucun ticket." dans tickets_report.txt — géré proprement par le script counterfactual
3. **70 fichiers `predictions.tsv` pour 33 dossiers** — certains jours ont plusieurs runs (re-runs en cours de journée)
4. **Format archives ancien vs récent** : les archives de 2026-02 ont `verdict_post_analyse_tickets_o15_random_report.txt` à la racine du run_dir, les plus récentes dans l'analyse_dir — le script counterfactual cherche dans les deux
