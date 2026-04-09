# ÉQUIPE BCEA — Bureau Central d'Excellence Analytique

## Organisation

```
equipe/
├── CULTURE.md           ← Lettre d'intronisation — qui on est, pourquoi on existe
├── _base.md             ← Socle commun — contexte projet + règles partagées
├── README.md            ← Ce fichier — mode d'emploi
│
├── agent_principal.md   ← Claude — architecte, coordinateur, rapporteur
│
├── cartographe.md       ← Explore et cartographie le système entier
├── questionnaire.md     ← Génère les questions depuis la carte
│
├── sceptique.md         ← Attaque les hypothèses, cherche les biais
├── innovateur.md        ← Propose l'inattendu, explore les angles morts
├── reducteur_bruit.md   ← Priorise, simplifie, garde l'essentiel
├── validateur_froid.md  ← Tranche sur les faits uniquement
└── testeur.md           ← Exécute les tests (10 → 50 → 100 runs)
```

---

## Hiérarchie

```
[Fondateur] — décision finale stratégique
      ↓
[Agent Principal] — coordination + rapport
      ↓
[Cartographe] [Questionnaire]  ← Phase d'exploration
[Sceptique] [Innovateur]       ← Phase de débat
[Réducteur] [Validateur]       ← Phase de décision
[Testeur]                      ← Phase d'exécution
```

---

## Protocole de réunion hebdomadaire

```
1. BILAN    → Agent Principal : résultats de la semaine passée
2. CARTE    → Cartographe : nouveautés / angles morts détectés
3. QUESTIONS → Questionnaire + Innovateur : nouvelles hypothèses
4. PRIORITÉS → Réducteur de Bruit : Top 3 de la semaine
5. DÉBAT    → Sceptique vs Innovateur : pour / contre chaque hypothèse
6. TESTS    → Testeur : 10 runs → signal ? → 50 → 100
7. VERDICT  → Validateur Froid : VALIDÉ / REJETÉ / EN ATTENTE
8. RAPPORT  → Agent Principal → Fondateur
```

---

## Comment utiliser ces fichiers (pour l'Agent Principal)

Quand tu lances un agent :
1. **Lis son fichier ADN** dans ce répertoire
2. **Lis _base.md** (contexte projet)
3. **Compose son prompt** = CULTURE.md (intro) + _base.md + son ADN + la tâche spécifique

Quand tu veux faire évoluer un agent :
1. **Modifie son fichier ADN** directement ici
2. **Documente dans LABORATOIRE.md** : pourquoi, quand, effet attendu
3. La prochaine invocation de l'agent utilisera l'ADN mis à jour

---

## Règles d'or du BCEA

1. **Aucune décision sur intuition seule** — toute intuition devient hypothèse, toute hypothèse est testée
2. **Rien n'est évident** — ce qui semble évident doit être questionné en premier
3. **L'historique est sacré** — LABORATOIRE.md avant toute action
4. **La contradiction est une force** — les agents pensent différemment par design
5. **Prendre des risques dans le questionnement est encouragé** — un chemin fermé est un résultat

---

*BCEA — Ordre des Analystes*
*"Ce n'est pas l'uniformité qui crée la précision. C'est la tension entre les points de vue."*
