# services/utils.py
# ------------------
# Utilitaires TRISKÈLE (V2 / MULTI-PARIS)
#
# ✅ Objectif :
# - Plus AUCUNE dépendance Over2.5 / BTTS
# - Utilitaires génériques (math, parsing)
# - Dataclasses + helpers pour résultats multi-paris
# - Génération de lignes TSV compatibles avec main.py
#
# ✅ Paris actuels (canoniques) :
#   - HT05               (+0.5 but à la mi-temps)
#   - HT1X_HOME          (1X à la mi-temps pour HOME)
#   - TEAM1_SCORE_FT     (TEAM1 marque)
#   - TEAM2_SCORE_FT     (TEAM2 marque)
#   - O15_FT             (Over 1.5 FT)
#   - O25_FT             (Over 2.5 FT)
#   - U35_FT             (Under 3.5 FT)
#   - TEAM1_WIN_FT       (TEAM1 gagne)
#   - TEAM2_WIN_FT       (TEAM2 gagne)
#
# Format TSV "predictions.tsv" (recommandé, compatible main.py) :
#   TSV: \t match_id \t date \t league \t home \t away \t bet_key \t metric \t score \t label \t is_candidate \t comment
#
# Format TSV sans match_id (encore toléré par main.py) :
#   TSV: \t date \t league \t home \t away \t bet_key \t metric \t score \t label \t is_candidate \t comment

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from datetime import date as _date
import re
import zlib

from config import TSV_PREFIX


# ============================================================================
# 1) Petites fonctions numériques
# ============================================================================

def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Division sécurisée : si b == 0, retourne default."""
    if b == 0:
        return default
    return a / b


def clamp(x: float, min_val: float, max_val: float) -> float:
    """Force x à rester dans [min_val, max_val]."""
    return max(min_val, min(max_val, x))


# ============================================================================
# 2) Types & dataclasses multi-paris
# ============================================================================

# ✅ BetKeys CANONIQUES (unifiés partout)
BetKey = Literal[
    "HT05",
    "HT1X_HOME",
    "TEAM1_SCORE_FT",
    "TEAM2_SCORE_FT",
    "O15_FT",
    "O25_FT",
    "U35_FT",
    "TEAM1_WIN_FT",
    "TEAM2_WIN_FT",
]


@dataclass
class BetResult:
    """
    Résultat d’un pari (un "bet").
    - key : identifiant technique (utilisé par main.py pour dispatcher jouables)
    - metric : nom humain (utilisé par tes TSV jouables dédiés)
    - score : score du pari (libre : float/int)
    - label : label de niveau (ex: "FORT", "EXPLOSION", etc.)
    - is_candidate : True => match "jouable" pour ce bet
    - comment : commentaire court (optionnel)
    - tsv : ligne TSV prête à écrire dans predictions.tsv (optionnel, souvent fourni par match_analysis)
    """
    key: str
    metric: str
    score: float
    label: str
    is_candidate: bool
    comment: str = ""
    tsv: Optional[str] = None


@dataclass
class MultiAnalysisResult:
    """Format structuré recommandé pour run_full_analysis()."""
    rapport: str
    bets: List[BetResult]


# ============================================================================
# 3) Match_id (stable) + TSV builders compatibles main.py
# ============================================================================

def make_match_id(date_str: str, league: str, home: str, away: str) -> int:
    """
    Fabrique un match_id STABLE (int) à partir des champs principaux.
    - Stable = même input => même id (utile pour dédoublonnage/trace)
    - On utilise CRC32 (zlib) : rapide, deterministic, suffisant ici.
    """
    payload = f"{date_str}|{league}|{home}|{away}".encode("utf-8", errors="ignore")
    return zlib.crc32(payload) & 0xFFFFFFFF


def build_prediction_tsv_line(
    *,
    date_str: str,
    league: str,
    home: str,
    away: str,
    bet_key: str,
    metric: str,
    score: float,
    label: str,
    is_candidate: bool,
    comment: str = "",
    match_id: Optional[int] = None,
) -> str:
    """
    Construit une ligne TSV "predictions.tsv" COMPATIBLE avec main.py (dédoublonnage + archivage).

    IMPORTANT :
    - main.py fait : raw = line[4:].lstrip(); parts = raw.split("\t")
    - donc on sort : "TSV:\t...."
    - si match_id est fourni => format "nouveau" (préféré)
    """
    comment_clean = (comment or "").replace("\t", " ").strip()
    label_clean = (label or "").replace("\t", " ").strip()

    # cast score -> str propre
    try:
        score_val = float(score)
    except Exception:
        score_val = 0.0

    fields: List[str] = []
    if match_id is not None:
        fields.append(str(int(match_id)))

    fields.extend([
        (date_str or "").strip(),
        (league or "").strip(),
        (home or "").strip(),
        (away or "").strip(),
        (bet_key or "").strip(),
        (metric or "").strip(),
        str(score_val),
        label_clean,
        "1" if bool(is_candidate) else "0",
        comment_clean,
    ])

    return f"{TSV_PREFIX}\t" + "\t".join(fields)


def build_bet_tsv_line_minimal(
    *,
    date_str: str,
    league: str,
    home: str,
    away: str,
    metric: str,
    score: float,
    label: str,
) -> str:
    """
    Construit une ligne TSV "jouables dédiés" au format attendu par main.write_sorted_bet_file() :

        TSV:  date    league  home    away    metric  score   label

    Note : main.py gère déjà l’écriture + tri. Ici c’est juste un helper.
    """
    label_clean = (label or "").replace("\t", " ").strip()
    try:
        score_val = float(score)
    except Exception:
        score_val = 0.0

    return f"{TSV_PREFIX}\t{date_str}\t{league}\t{home}\t{away}\t{metric}\t{score_val}\t{label_clean}"


# ============================================================================
# 4) Parsing matches_input.txt (optionnel, si tu veux partager la logique)
#    (Ton main.py a déjà son parse_match_line ; ici on fournit une version
#     "dict" simple, proche de l’ancien utils.py)
# ============================================================================

def split_teams(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Sépare une chaîne "Team1 vs Team2", "Team1 - Team2", etc.
    Retourne (home, away) ou (None, None) si pas trouvé.
    """
    text = (text or "").strip()
    if not text:
        return None, None

    # On ne force PAS .lower() + .title() ici : ça casse parfois les noms.
    # On fait un split robuste, puis on strip.
    lowered = text.lower().replace(" v ", " vs ")

    separators = [" vs ", " vs.", " - ", "-", "–"]
    for sep in separators:
        if sep in lowered:
            # On split sur la version originale (pas lowered) pour garder la casse
            idx = lowered.find(sep)
            left = text[:idx].strip()
            right = text[idx + len(sep):].strip()
            return left, right

    return None, None


def infer_date_today() -> str:
    """Retourne la date du jour (YYYY-MM-DD)."""
    return str(_date.today())


def infer_league_auto(*_teams: str) -> str:
    """Valeur neutre : ligue inconnue."""
    return "AUTO"


def parse_match_line_to_dict(line: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Parse une ligne du fichier matches_input.txt.

    Formats acceptés :
      1) DATE | LIGUE | Home vs Away
      2) DATE HH:MM | LIGUE | Home vs Away
      3) Format court : "Home vs Away"

    Retour :
      {"date", "time", "league", "home", "away"} ou None (vide/commentaire)
    """
    line = (line or "").strip()
    if not line:
        return None
    if line.lstrip().startswith("#"):
        return None

    # Format long
    if "|" in line:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            raise ValueError(f"Ligne invalide (3 blocs séparés par '|') : {line}")

        date_block, league, teams_raw = parts

        time_str: Optional[str] = None
        date_str = date_block.strip()
        if " " in date_block:
            first, rest = date_block.split(" ", 1)
            date_str = first.strip()
            rest = rest.strip()
            if rest:
                time_str = rest

        home = away = None

        # split tolérant : "vs", "VS", "Vs", avec espaces autour
        m = re.split(r"\s+vs\s+", teams_raw.strip(), flags=re.IGNORECASE, maxsplit=1)
        if len(m) == 2:
            home, away = m[0].strip(), m[1].strip()
        elif " - " in teams_raw:
            left, right = teams_raw.split(" - ", 1)
            home, away = left.strip(), right.strip()
        elif "-" in teams_raw:
            left, right = teams_raw.split("-", 1)
            home, away = left.strip(), right.strip()

        if not home or not away:
            raise ValueError(f"Impossible de trouver les deux équipes : {line}")

        return {
            "date": date_str,
            "time": time_str,
            "league": league,
            "home": home,
            "away": away,
        }

    # Format court
    home, away = split_teams(line)
    if home and away:
        return {
            "date": infer_date_today(),
            "time": None,
            "league": infer_league_auto(home, away),
            "home": home,
            "away": away,
        }

    # Une seule équipe => placeholder
    return {
        "date": infer_date_today(),
        "time": None,
        "league": infer_league_auto(line),
        "home": line.strip(),
        "away": None,
    }


def load_matches_from_file(path: str) -> List[Dict[str, Optional[str]]]:
    """Lit un fichier texte et renvoie une liste de matchs sous forme de dicts."""
    matches: List[Dict[str, Optional[str]]] = []
    p = Path(path)

    if not p.exists():
        print(f"❌ Fichier introuvable : {path}")
        return matches

    text = p.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        parsed = parse_match_line_to_dict(line)
        if parsed:
            matches.append(parsed)

    return matches