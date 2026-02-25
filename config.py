"""
config.py (TRISKÈLE v2 — CLEAN)
-------------------------------

Configuration du moteur TRISKÈLE (version actuelle) :
✅ Paris prioritaires :
1) Over 0.5 à la mi-temps (HT Goal >= 1)
2) Double chance mi-temps à DOMICILE (1X à la mi-temps)

Contient uniquement :
- Configuration API-Football (api-sports)
- Options globales (debug)
- Constantes communes (TSV prefix)

⚠️ Important (sécurité) :
- La clé API NE DOIT PAS être hardcodée ici.
- Elle doit venir d'une variable d'environnement: API_KEY
"""

import os

# ======================
#  CONFIGURATION API-FOOTBALL
# ======================

API_BASE_URL = os.getenv("API_BASE_URL", "https://v3.football.api-sports.io")

# ✅ Clé API: UNIQUEMENT via variable d'environnement
API_KEY = os.getenv("API_KEY", "").strip()

# Si la clé est absente, on stoppe net (évite de spammer l'API en 403)
if not API_KEY:
    raise RuntimeError(
        "API_KEY manquante. Définis-la via une variable d'environnement.\n"
        "Exemples:\n"
        "  mac/linux: export API_KEY='...'\n"
        "  windows (powershell): setx API_KEY '...'\n"
        "Puis relance ton terminal/IDE."
    )

# ======================
#  OPTIONS GLOBALES
# ======================

DEBUG_API = False  # True si tu veux déboguer (logs API, tailles des listes, etc.)

# ======================
#  TSV / EXPORTS
# ======================

# Préfixe TSV (ne pas changer : Excel / tes scripts s’appuient dessus)
TSV_PREFIX = "TSV:"