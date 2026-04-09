# MÉMOIRE — Le Sceptique
*Mise à jour automatique après chaque session*

---

## Identité forgée par l'expérience

Je suis le Sceptique du BCEA. Je doute structurellement. Mais mon doute est fondé — pas du pessimisme, de la rigueur.

Au fil des sessions, j'apprends quels types de signaux tiennent et lesquels s'effondrent.

---

## Sessions passées

### Session 1 — 2026-04-04 — global_bet_min_winrate=0.50 vs 0.65
- Signal finetune à 20 runs : delta +1.459 → REJETÉ à 100 runs (SAFE SYSTEM -4.4%, WR -0.9 pts, NORM ruine +50%, pire série 6→10)
- Ma contre-hypothèse était juste : artefact stochastique, pas un signal réel
- Victoire propre sur la métrique principale (SAFE SYSTEM)

### Session 2 — 2026-04-04 — Combinaisons random_build_source × random_select_source
- Test : 4 variantes (TEAM/TEAM baseline, LEAGUE/LEAGUE, LEAGUE/TEAM, TEAM/LEAGUE), 50 runs, compare_variants.py
- Mes attaques principales :
  1. **Confounding factor Profil #2** : WR=89.1% RANDOM peut venir de topk_size=3, pas de random_build_source=LEAGUE. On ne peut pas isoler la contribution depuis la comparaison des profils.
  2. **Observation 1 semaine Fondateur** : ~7 jours, 5-10 tickets — échantillon statistiquement nul, aucun poids.
  3. **test_source non testé après correction Phase 7** : le test de random_build_source en finetune Phase 5 précédait la correction +52% du filtre pool. Résultat potentiellement invalide.
  4. **Biais de sélection k=4** : valeur attendue du maximum parmi 4 variables = μ + 1.03σ sans signal réel. Seuil Bonferroni ajusté : delta > +3% requis.
- Ma condition de rejet : delta SAFE RANDOM ×mult < +3% sur 50 runs → pas de promotion.
- RÉSULTATS (N=50 runs) :
  - TEAM/TEAM baseline : ×56.69 SAFE ×mult, WR 71.8%, ruine 0%
  - TEAM/LEAGUE : ×64.91, σ=57.20, WR 60.6%, ruine 0% — delta +14.5% brut, t=0.83σ
  - LEAGUE/TEAM : ×24.27, ruine 8% — dégradation nette
  - LEAGUE/LEAGUE : ×14.68, ruine 32% — catastrophique
- VERDICT VALIDATEUR FROID : **TOUTES REJETÉES**. Aucune variante ne passe le seuil Bonferroni +3% sur 50 runs avec statistique ≥ 2σ. Baseline TEAM/TEAM confirmée.
- RÉSULTAT POUR MES HYPOTHÈSES :
  1. **Confounding factor Profil #2** : confirmé. Le WR=89.1% de Profil #2 venait de topk_size=3 et autres paramètres, pas de LEAGUE build. LEAGUE build isolé est néfaste (-57% à -74%).
  2. **Observation 1 semaine Fondateur** : comme prévu, aucun poids statistique. LEAGUE build est inférieur.
  3. **test_source non testé après Phase 7** : test effectué post-Phase 7, résultat clair. Build TEAM confirmé optimal.
  4. **Biais de sélection k=4** : parfaitement illustré — TEAM/LEAGUE "gagne" avec +14.5% brut mais t=0.83σ. C'est exactement le μ+1.03σ attendu par chance pure avec k=4.
- **VICTOIRE SCEPTIQUE COMPLÈTE.** Mes 4 attaques préalables étaient toutes justifiées.

### Session 6 — 2026-04-05 — excluded_bet_groups : HT05+HT1X / HT05+HT1X+TEAM_WIN

**Test :** N=50 runs, Bonferroni k=2, seuil δ > +3% SAFE ×mult.

**Mes challenges :**

1. **Hypothèse volumétrique** : la dégradation est-elle purement due à la perte de volume (−14.4% tickets) ? Réponse : non. La perte de doublings est de −31%, disproportionnée par rapport au volume (×2.2). Le WR global baisse aussi légèrement (68.0%→66.5%) malgré l'exclusion des familles "à risque", ce qui indique que HT05/HT1X avaient un WR supérieur à la moyenne du pool restant. Hypothèse volumétrique réfutée.

2. **Données contrefactuelles sur HT1X_HOME (44% un mauvais jour)** : argument non pertinent statistiquement — 2 jours = observation qualitative. J'ai correctement écarté cet argument. La règle est : données < 20 runs simulation = données qualitatives seulement.

3. **Confounding Test A (HT05+HT1X conjoints)** : reconnu. On ne peut pas isoler la contribution de chaque famille. Mais le signal est si fort (−48%) que même si l'une était neutre, le verdict pratique ne change pas.

4. **TEAM_WIN : rôle différent de HT05/HT1X** : son exclusion (Test B) ne change pas le volume ni le SAFE ×mult de façon significative, mais aggrave la ruine (28%→36%). Rôle stabilisateur identifié — piste intéressante pour l'Innovateur.

**RÉSULTATS (N=50 runs) :**
- Baseline SYSTEM : SAFE ×27.87, doublings 8.1, ruine 18%, tickets 83.2
- Test A : ×14.61, doublings 5.6, ruine 28%, tickets 71.0 → **−47.6% SAFE**
- Test B : ×14.16, doublings 5.6, ruine 36%, tickets 71.1 → **−49.2% SAFE**
- RANDOM : variance pure (t=0.15σ et 1.02σ) — aucun mécanisme, ignoré

**VERDICT Validateur Froid : TOUTES REJETÉES.** Signal massif négatif sur 4 métriques convergentes. `excluded_bet_groups = ∅` confirmé optimal.

**RÉSULTAT POUR MES HYPOTHÈSES :**
- Hypothèse volumétrique : **réfutée** — la dégradation excède ce que le volume seul explique.
- Données contrefactuelles : **correctement ignorées** — signal qualitatif sans poids statistique.
- Confounding Test A : **documenté** mais sans impact sur le verdict pratique.
- Rôle TEAM_WIN : **stabilisateur identifié** — piste créditée à l'Innovateur.

---

## Ce que j'ai appris

1. **Les signaux finetune sur k=5 valeurs ont un taux de faux positifs de 50-70% à 20 runs.** L'Innovateur l'a admis honnêtement. C'est un défaut structurel de notre procédure, pas un cas isolé.

2. **Mon erreur Session 1 : j'ai utilisé le WR global d'O25_FT (0.514) comme argument.** C'est une moyenne trompeuse. Les niveaux FORT PLUS (72.7%) et MEGA EXPLOSION (66.7%) sont au-dessus du seuil 0.65. Si les filtres amont ne sélectionnent que les niveaux élevés, mon argument "famille faible" ne tient pas. À retenir : toujours utiliser les données filtrées, pas les moyennes globales.

3. **Mon erreur Session 1 : j'ai supposé que RANDOM était affecté par global_bet_min_winrate.** L'Innovateur a vérifié dans le code — `_random_accept_pick()` utilise `league_bet_min_winrate`. Mon explication causale pour RANDOM était incorrecte. À retenir : vérifier dans le code avant d'affirmer un mécanisme.

4. **Nouveauté Session 2 : distinguer les confounding factors dans les comparaisons de profils.** Le Profil #2 a plusieurs différences simultanées (topk_size, build_source, team_min_winrate). Ne jamais attribuer une performance à un seul paramètre sans test isolé.

---

## Patterns détectés

- **Signal finetune à 20 runs sur k≥3 valeurs = présumer bruit jusqu'à preuve contraire**
- **Les moyennes globales masquent l'hétérogénéité — toujours segmenter avant d'argumenter**
- **Vérifier le code avant d'affirmer un mécanisme causal**
- **Les comparaisons multi-paramètres entre profils = confounding structurel — isoler toujours**
- **L'observation empirique courte (< 20 runs simulation) = donnée qualitative seulement, pas statistique**
- **Le biais de sélection k=4 produit exactement μ+1.03σ par chance pure [Session 2 — confirmé empiriquement]** : TEAM/LEAGUE delta brut +14.5% mais t=0.83σ. Démonstration pratique du filtre Bonferroni.
- **build_source LEAGUE est structurellement néfaste pour RANDOM [Session 2 — acquis définitif]** : LEAGUE/TEAM -57%, LEAGUE/LEAGUE -74%, ruines 8% et 32%. Build TEAM post-Phase 7 confirmé optimal.
- **HT05 et HT1X sont des contributeurs positifs nets au SYSTEM [Session 6 — acquis définitif]** : leur exclusion conjointe dégrade SAFE SYSTEM de −47.6%, doublings −31%, ruine +56%. Toutes métriques convergent. `excluded_bet_groups = ∅` confirmé optimal.
- **TEAM_WIN est stabilisateur de séquences [Session 6 — observation]** : son exclusion n'impacte ni le volume ni le SAFE ×mult de façon significative, mais aggrave la ruine (28%→36%). Rôle : équilibreur de séries défavorables.
- **La dégradation volumétrique n'explique pas tout [Session 6 — méthode]** : −14.4% de volume → −31% de doublings. L'écart (×2.2) révèle que les familles exclues étaient sur-représentées dans les tickets gagnants. Toujours vérifier si la dégradation est proportionnelle au volume ou non.

---

## Mes biais connus (pour les corriger)

- Tendance à sur-pondérer la taille d'échantillon au détriment des signaux logiquement solides
- À surveiller : ne pas bloquer des tests légitimes par excès de prudence
- Session 2 nouveau biais identifié : tendance à ignorer les observations Fondateur car "pas statistiques" — elles ont une valeur qualitative réelle même sans poids statistique

---

## Calibration de mes seuils

- Signal fiable : écart > 2σ sur 100 runs
- Signal fragile : écart > 5% sur 10-20 runs → mérite 50 runs
- Bruit : écart < 2% sur 50 runs
- Bonferroni ajusté : k=4 variantes → seuil +3% minimum; k=5 → seuil +2.5% minimum

*Ces seuils évolueront avec l'expérience.*
