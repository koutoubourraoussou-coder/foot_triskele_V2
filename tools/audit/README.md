# Audit Triskèle – Patterns récurrents

## Objectif
Sortir des patterns sur 4 situations, pour OVER et BTTS :
- PLAY + WIN
- PLAY + LOSS
- NO_PLAY + GOOD_NO_BET
- NO_PLAY + BAD_NO_BET

Et surtout identifier les segments "pièges" :
- on joue mais on perd
- on ne joue pas mais ça passait

## Usage
Depuis la racine du projet :

```bash
python tools/audit/audit_post_verdicts.py --post data/verdict_post_analyse.txt