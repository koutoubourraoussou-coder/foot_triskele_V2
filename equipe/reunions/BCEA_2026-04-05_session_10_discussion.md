# DISCUSSION — Session 10 — BCEA — 2026-04-05
*Transcript vivant — les agents parlent en voix directes*

---

## Ouverture de séance

*L'Agent Principal pose le sujet sur la table.*

"Le Fondateur a lancé le système en réel aujourd'hui. Six défaites consécutives avec SYSTEM dès le premier jour. Il hésite à virer SYSTEM du portfolio, ou à repenser la structure des réserves. Je pose les données sur la table. L'équipe décide."

---

## Sceptique — Ouverture

*Le Sceptique se lève, croisant les bras.*

"Je commence par ce que les données nous disent.

Six défaites consécutives avec SYSTEM — ce n'est pas une anomalie. C'est dans notre enveloppe statistique. max_absolu=6 sur 61 jours, vu une fois sur 50 runs en Session 8. Ça arrive. La question n'est pas 'est-ce que c'est probable' — c'est 'est-ce que notre structure de bankroll est conçue pour y survivre'.

Et là, je veux qu'on soit honnêtes. Avec max_losses=4 en martingale NORMALE, 6 pertes consécutives = ruine certaine. En martingale SAFE, 6 pertes = la bankroll active tombe à zéro deux fois, on tire deux fois sur les réserves communes. Ce n'est pas la ruine, mais c'est potentiellement 200€ de réserves consommées en un seul jour. Sur 600€ de réserves initiales.

Le vrai risque n'est pas SYSTEM seul. C'est SYSTEM en crise simultanément avec une mauvaise série RANDOM. Et ça, nos simulations portfolio le montrent : le min du portfolio est ×11.86. C'est le scénario où les deux canaux souffrent en même temps."

*Un silence.*

"Ma position : avant de décider de virer SYSTEM, je veux savoir ce que le portfolio donne en mode RANDOM SAFE uniquement. Est-ce que c'est meilleur ou pire ?"

---

## Réducteur de Bruit — Premier tour

*Le Réducteur consulte ses notes.*

"Voilà ma lecture des chiffres.

SYSTEM SAFE produit moy=×28.98 en isolation. RANDOM SAFE produit moy=×53.51. RANDOM est structurellement meilleur : plus de ×mult, même ruine (0%), même pire série max (6). Et RANDOM a σ=36.87 contre σ=4.02 pour SYSTEM — mais en SAFE c'est la variance positive qui compte, pas la négative.

Le SYSTEM NORMALE est le moteur dominant du portfolio à ×218 moy — c'est SN qui génère les grands multiplicateurs. Mais SN a 14% de ruine en isolation, et dans le portfolio il partage les réserves avec SS/RN/RS. En conditions réelles avec des séries défavorables, SN peut vider les réserves communes en quelques jours.

Ce que je veux tester : portfolio RANDOM uniquement (RS + RN) vs portfolio complet (RS + RN + SS + SN). On simule les deux sur 100 runs avec run_portfolio.py. Le résultat tranchera la question sans opinion."

---

## Innovateur — Premier tour

*L'Innovateur pose son téléphone.*

"J'ai une proposition différente. Pas virer SYSTEM. Pas garder SYSTEM tel quel. **Décaler SYSTEM.**

Voilà la logique. Le problème n'est pas que SYSTEM est mauvais — 0% de ruine SAFE en 100 runs, ce n'est pas mauvais. Le problème est qu'on lance SYSTEM le jour 1, avec 600€ de réserves, alors que ces réserves n'ont pas encore été renforcées par les doublings SAFE.

Si on lance RS seul pendant 2-3 semaines, on accumule des doublings. A chaque doubling RS, les réserves communes grossissent. Quand RS a fait 3-4 doublings, les réserves sont à 1000-1500€. À ce niveau, une crise SYSTEM de 6 pertes consécutives consomme 200€ sur 1000-1500€ — c'est gérable.

C'est exactement le start-delay qu'on a implémenté. L'infra est prête. Et le Fondateur l'a fait naturellement — il a commencé par RS seul. Il faudrait juste le formaliser : RS d'abord, puis SS après le 1er doubling RS, puis SN/RN après le 1er doubling SS."

*Pause.*

"Et max_losses=5 pour SYSTEM — 5 pertes consécutives en martingale normale = denom=31, mise initiale = 100/31 ≈ 3.2€ au lieu de 6.7€. Beaucoup plus petit. On survit à 5 pertes sans tirer sur les réserves du tout. La contrepartie : gain potentiel plus faible par cycle. Ça vaut le coup de simuler."

---

## Validateur Froid — Synthèse

*Le Validateur Froid intervient, précis.*

"Je vais ordonner les propositions par coût et urgence.

**Ce qu'on sait avec certitude :**
1. La SAFE ne ruine pas (0% sur 100 runs pour SYSTEM et RANDOM). Les 6 pertes du Fondateur n'ont donc pas ruiné la SAFE — elles ont tiré sur les réserves.
2. RANDOM SAFE surpasse SYSTEM SAFE en isolation (×53 vs ×29). RANDOM est structurellement meilleur sur ce critère.
3. Le portfolio tire sa force principalement de SN (SYSTEM NORMALE) en grands gains, mais SN a 14% de ruine individuelle.

**Les trois options sur la table :**

**Option A — Virer SYSTEM (RS + RN uniquement)**
- Avantage : simplifie le portfolio, évite les crises SYSTEM
- Risque : perd le moteur SN qui génère les grands ×mult du portfolio
- Test requis : simulation run_portfolio.py RANDOM ONLY sur 100 runs

**Option B — Start-delay (déjà implémenté)**
- Avantage : protège la fenêtre de vulnérabilité initiale, infra prête
- Risque : délai avant que SN soit actif
- Test requis : run_portfolio.py --start-delay sur 100 runs (à faire)

**Option C — Augmenter max_losses SYSTEM à 5**
- Avantage : survit aux séries de 6 sans toucher les réserves
- Risque : mises initiales divisées par 2 → profit par cycle divisé par 2
- Test requis : modifier ML dans run_portfolio.py et simuler

**Décision proposée :**
1. Lancer les trois simulations (Option A, B, C vs baseline) sur 100 runs — run_portfolio.py est rapide.
2. Comparer P25 (plancher 1er quartile) comme critère principal — le Fondateur veut survivre, pas maximiser la moyenne.
3. Décider sur données."

---

## Réducteur de Bruit — Clôture

*Le Réducteur ferme son carnet.*

"D'accord avec le Validateur Froid. On simule les trois options. Critère : P25 et min — pas la moyenne.

Et je veux ajouter une option D qui n'a pas encore été mentionnée : **lancer uniquement RS et SS** (les deux SAFE) pendant 30 jours. Laisser les NORMALE dormir. Accumuler des réserves proprement, sans risque de ruine NORMALE. Puis introduire SN et RN quand les réserves dépassent un seuil (ex. 1500€). C'est une variante du start-delay mais plus conservative.

Un point final : le Fondateur a survécu à ses 6 défaites aujourd'hui — la SAFE a joué son rôle. Ce n'est pas une catastrophe. C'est le système qui fonctionne comme prévu."

---

## VERDICT DE SÉANCE

**Actions décidées :**

1. **Simuler Option A** — portfolio RANDOM uniquement (RS + RN) sur 100 runs — run_portfolio.py
2. **Simuler Option B** — start-delay actuel sur 100 runs — `run_portfolio.py --start-delay`
3. **Simuler Option C** — max_losses SYSTEM = 5 sur 100 runs
4. **Simuler Option D** — SAFE uniquement au départ (RS + SS), NORMALE ajoutées après seuil réserves

**Critère de comparaison :** P25 (1er quartile) + min absolu. Pas la moyenne.

**Statu quo en attendant :** Le Fondateur continue avec la structure actuelle. Aucune décision irréversible ce soir.
