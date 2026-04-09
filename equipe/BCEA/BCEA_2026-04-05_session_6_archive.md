# BCEA Session 6 — Verdict final et acquis structurels
**Date :** 2026-04-05
**Sujet :** `excluded_bet_groups` — HT05, HT1X, TEAM_WIN dans le SYSTEM
**Scribe :** rôle 5, rédige après lecture complète de la discussion

---

## Verdicts

| Variante | Hypothèse | Verdict | Motif principal |
|----------|-----------|---------|----------------|
| Test A | `excluded = ["HT05", "HT1X"]` | **REJETÉ** | SAFE SYSTEM −47.6%, doublings −31%, ruine +56% |
| Test B | `excluded = ["HT05", "HT1X", "TEAM_WIN"]` | **REJETÉ** | SAFE SYSTEM −49.2%, ruine +100% vs baseline |

**Profil champion : inchangé.** `excluded_bet_groups = ∅` confirmé optimal.

---

## Acquis structurels — Session 6

### Acquis 1 — HT05 et HT1X sont des contributeurs positifs nets au SYSTEM
**Source : Validateur Froid + Réducteur de Bruit — convergence 4 métriques**

Leur exclusion conjointe (Test A) entraîne :
- SAFE ×mult SYSTEM : −47.6% (×27.87 → ×14.61)
- Doublings : −31% (8.1 → 5.6)
- NORM ruine : +56% en relatif (18% → 28%)
- Tickets/run : −14.4% (83.2 → 71.0)

Toutes les métriques convergent. Ce n'est pas un artefact de variance. HT05 et HT1X participent activement aux séquences gagnantes du SYSTEM — leur WR moyen dans le profil filtré est supérieur à celui des familles restantes (sinon le WR global ne baisserait pas à l'exclusion).

**Règle dérivée : ne pas exclure HT05 ni HT1X sans preuve positive (signal ≥ +3% sur 50 runs).**

### Acquis 2 — TEAM_WIN est un stabilisateur de séquences, pas un générateur de volume
**Source : Innovateur — observation Test A vs Test B**

Comparaison Test A → Test B (exclusion de TEAM_WIN en plus) :
- Volume tickets : quasi-stable (71.0 → 71.1) — TEAM_WIN ne contribue pas au volume absolu final
- SAFE ×mult : quasi-stable (14.61 → 14.16) — TEAM_WIN ne génère pas de profit marginal brut significatif
- NORM ruine : aggravée (28% → 36%) — TEAM_WIN réduit les séries de défaites

Interprétation : TEAM_WIN joue un rôle d'équilibreur en creux de séquence — victoires plus faciles qui brisent les séries défavorables. Sa présence réduit la ruine sans augmenter le profit médian.

**Règle dérivée : TEAM_WIN est protecteur de la martingale. Ne pas exclure.**

### Acquis 3 — `excluded_bet_groups = ∅` est confirmé optimal pour le profil champion
**Source : Validateur Froid — verdict final Session 6**

Cet acquis ferme définitivement la question "faut-il exclure des familles ?" pour le profil Amélioré #1. La réponse est non — toutes les familles actuelles (HT05, HT1X, TEAM_SCORE, TEAM_WIN, O15) contribuent positivement à l'ensemble.

**À ne pas rouvrir sans signal positif fort (δ > +3%, N ≥ 50 runs) sur une exclusion spécifique.**

### Acquis 4 — La dégradation volumétrique n'explique pas tout
**Source : Sceptique — analyse mécanique**

-14.4% de volume (tickets/run) → devrait provoquer −14% de doublings environ si les familles exclues étaient neutres. Observé : −31% de doublings. L'excès de dégradation (×2.2) montre que HT05/HT1X sont sur-représentés dans les tickets *gagnants*, pas seulement dans le volume brut.

Corollaire : le WR global baisse légèrement malgré l'exclusion des paris "à risque", ce qui indique que HT05/HT1X avaient un WR *supérieur* à la moyenne des autres familles dans le profil champion filtré.

---

## Limitations et biais du test

**Confounding du design :** Test A exclut HT05 ET HT1X simultanément. On ne peut pas isoler la contribution de chaque famille individuellement. Si l'une était neutre et l'autre catastrophique, on ne le saurait pas. Cette limitation est documentée mais ne change pas le verdict pratique.

**Contrefactuelle partielle :** Les données contrefactuelles sur HT1X_HOME (44% un jour / 60% un autre) proviennent de 2 jours seulement — observations qualitatives sans poids statistique. Elles ne doivent pas influencer le verdict. Le Sceptique a correctement identifié et écarté cet argument.

---

## Backlog ouvert par cette session

| Piste | Priorité | Mécanisme | Développement requis |
|-------|----------|-----------|----------------------|
| Test isolé `excluded = ["HT05"]` seul | Basse | Isoler la contribution de HT05 vs HT1X | Non — compare_variants.py |
| Test isolé `excluded = ["HT1X"]` seul | Basse | Idem | Non — compare_variants.py |
| Seuillage par niveau de confiance HT05/HT1X (FORT PLUS uniquement) | Basse | Filtrer sans exclure | Modification ticket_builder.py |
| Analyse WR réel HT1X sur archive complète (contrefactuelle v3) | Basse | Qualifier le WR réel sur 61 jours | Non — counterfactual.py disponible |

**Note :** ces pistes sont d'intérêt secondaire — le signal de cette session est clair et le profil champion reste en place. Ces tests ne changeraient probablement pas le verdict final (le profil ∅ domine largement), mais pourraient fournir des données diagnostiques sur la structure du pool SYSTEM.

---

## Profil champion après Session 6

**Inchangé. Amélioré #1 avec `excluded_bet_groups = ∅`.**

Le paramètre `excluded_bet_groups` a été exploré sur :
- Phase 5 (finetune) : `{TEAM1_WIN_FT, TEAM2_WIN_FT}` → signal à 20 runs, validé 200 runs comme Super Fusion
- Phase 6 (comparaison) : Super Fusion vs Amélioré #1 → revert vers Amélioré #1 (mécanisme RANDOM non affecté, exclusion superflue)
- Session 6 BCEA : `["HT05", "HT1X"]` et `["HT05", "HT1X", "TEAM_WIN"]` → rejet massif

**Conclusion transversale :** les exclusions de familles de paris dégradent systématiquement le SYSTEM dans ce profil. Les familles actuellement incluses sont toutes utiles. La question est fermée pour cette configuration.

---

*Scribe — Session 6 — 2026-04-05*
*Agents impliqués : Réducteur de Bruit, Sceptique, Innovateur, Validateur Froid*
