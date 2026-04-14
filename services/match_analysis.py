# services/match_analysis.py
# ----------------------------------------------------
# TRISKÈLE — Match Analysis (MULTI-PARIS)
# Paris actuels :
#   1) HT_OVER_0_5                 (+0.5 but à la mi-temps)
#   2) HOME_HT_DOUBLE_CHANCE       (1X à la mi-temps pour l'équipe à domicile)
#   3) TEAM_TO_SCORE               (TEAM1 marque / TEAM2 marque)
#   4) FT_OVER_1_5                 (Plus de 1.5 buts dans le match)
#   5) TEAM_WIN                    (TEAM1 gagne / TEAM2 gagne)
#   6) FT_OVER_2_5                 (Plus de 2.5 buts dans le match)
# ----------------------------------------------------

import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from services.utils import (
    make_match_id,
    build_prediction_tsv_line,
)

# ----------------------------------------------------
# Bet keys CANONIQUES (unifiés partout)
# ----------------------------------------------------
BETKEY_HT05 = "HT05"
BETKEY_HT1X_HOME = "HT1X_HOME"
BETKEY_TEAM1_SCORE_FT = "TEAM1_SCORE_FT"
BETKEY_TEAM2_SCORE_FT = "TEAM2_SCORE_FT"
BETKEY_O15_FT = "O15_FT"
BETKEY_O25_FT = "O25_FT"
BETKEY_TEAM1_WIN_FT = "TEAM1_WIN_FT"
BETKEY_TEAM2_WIN_FT = "TEAM2_WIN_FT"
BETKEY_U35_FT = "U35_FT"

# ----------------------------------------------------
# Couleurs ANSI (terminal)
# ----------------------------------------------------
ANSI_RESET = "\033[0m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_CYAN = "\033[36m"
ANSI_UNDERLINE = "\033[4m"  # (gardé pour compat, mais NON utilisé dans les titres)
ANSI_BOLD = "\033[1m"


# ----------------------------------------------------
# Helpers internes (généraux)
# ----------------------------------------------------
def _average(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _count_ratio(flags: List[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for f in flags if f) / len(flags)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _format_pct(p: float) -> str:
    return f"{p:.0f}%"


def _color(label: str, kind: str = "ok") -> str:
    if kind == "ok":
        return f"{ANSI_GREEN}{label}{ANSI_RESET}"
    if kind == "warn":
        return f"{ANSI_YELLOW}{label}{ANSI_RESET}"
    if kind == "bad":
        return f"{ANSI_RED}{label}{ANSI_RESET}"
    return f"{ANSI_CYAN}{label}{ANSI_RESET}"


def _bold(text: str) -> str:
    return f"{ANSI_BOLD}{text}{ANSI_RESET}"


def _color_delta(n: int) -> str:
    """
    Bonus/Malus en couleur.
    +n => vert, -n => rouge, 0 => neutre
    """
    if n > 0:
        return _color(f"+{n}", "ok")
    if n < 0:
        return _color(f"{n}", "bad")
    return f"{n}"


def _section_title(text: str) -> str:
    """
    Titre de section lisible en terminal : GRAS + ligne unique.
    (Pas de soulignement => évite l'effet "double ligne")
    """
    line = "─" * max(32, len(text) + 2)
    return f"{ANSI_BOLD}{text}{ANSI_RESET}\n{line}"


def _line_blank() -> str:
    return ""


def _bullet(text: str) -> str:
    return f"- {text}"


# ----------------------------------------------------
# Niveaux (LANGAGE UNIQUE pour TOUS les paris)
# ----------------------------------------------------

LEVELS = [
    "KO",
    "FAIBLE",
    "MOYEN",
    "MOYEN PLUS",
    "FORT",
    "FORT PLUS",
    "TRÈS FORT",
    "EXPLOSION",
    "MEGA EXPLOSION",
]


def _level_index(name: str) -> int:
    try:
        n = (name or "").strip()
        return LEVELS.index(n)
    except Exception:
        # fallback tolérant : compare sans casse mais en gardant accents
        n2 = (name or "").strip().casefold()
        for i, lvl in enumerate(LEVELS):
            if lvl.casefold() == n2:
                return i
        return 0
    
def _base_level_ft_over15(pct_a: float, pct_b: float) -> Tuple[str, Dict[str, Any]]:
    """
    Base Over 1.5 (FT) — même logique que HT05 : on regarde lo/hi sur les 8 derniers.
    Retourne (level, info).
    """
    lo = min(pct_a, pct_b)
    hi = max(pct_a, pct_b)
    info = {"lo": lo, "hi": hi}

    if lo < 50.0 and hi < 50.0:
        return "KO", info
    if lo < 50.0 and hi < 62.5:
        return "KO", info

    if lo >= 50.0 and hi < 62.5:
        return "FAIBLE", info
    if lo >= 50.0 and hi >= 62.5 and hi < 75.0:
        return "MOYEN", info
    if lo >= 62.5 and hi < 75.0:
        return "MOYEN PLUS", info
    if lo >= 62.5 and hi >= 75.0 and hi < 87.5:
        return "FORT", info
    if lo >= 75.0 and hi < 87.5:
        return "FORT PLUS", info
    if lo >= 75.0 and hi >= 87.5:
        if (lo == 100.0 and hi >= 87.5) or (hi == 100.0 and lo >= 87.5):
            return "MEGA EXPLOSION", info
        if lo >= 87.5 and hi >= 87.5:
            return "EXPLOSION", info
        return "TRÈS FORT", info

    return "MOYEN", info


def _base_level_ft_over25(pct_a: float, pct_b: float) -> Tuple[str, Dict[str, Any]]:
    """
    Base Over 2.5 (FT) — seuils abaissés de ~12.5 pts vs O15 car le pari est plus difficile.
    """
    lo = min(pct_a, pct_b)
    hi = max(pct_a, pct_b)
    info = {"lo": lo, "hi": hi}

    if lo < 37.5 and hi < 37.5:
        return "KO", info
    if lo < 37.5 and hi < 50.0:
        return "KO", info

    if lo >= 37.5 and hi < 50.0:
        return "FAIBLE", info
    if lo >= 37.5 and hi >= 50.0 and hi < 62.5:
        return "MOYEN", info
    if lo >= 50.0 and hi < 62.5:
        return "MOYEN PLUS", info
    if lo >= 50.0 and hi >= 62.5 and hi < 75.0:
        return "FORT", info
    if lo >= 62.5 and hi < 75.0:
        return "FORT PLUS", info
    if lo >= 62.5 and hi >= 75.0:
        if (lo == 100.0 and hi >= 75.0) or (hi == 100.0 and lo >= 75.0):
            return "MEGA EXPLOSION", info
        if lo >= 75.0 and hi >= 75.0:
            return "EXPLOSION", info
        return "TRÈS FORT", info

    return "MOYEN", info


# ----------------------------------------------------
# THERMOSTAT (seuil minimal pour écrire dans les TSV "jouables")
# Seuil PAR BET KEY — calibré sur winrates réels (verdict_post_analyse.txt)
# ----------------------------------------------------
MIN_LEVEL_EXPORT = "FORT"  # fallback générique (utilisé dans les _final_verdict_* internes)

MIN_LEVEL_BY_BET: dict[str, str] = {
    # Winrate MOYEN PLUS > seuil rentabilité → on abaisse
    "HT1X_HOME":      "MOYEN PLUS",   # 73.1% à MOYEN PLUS (n=1084)
    "TEAM1_SCORE_FT": "MOYEN PLUS",   # 78.6% à MOYEN PLUS (n=770)
    "O15_FT":         "MOYEN PLUS",   # 74.5% à MOYEN PLUS (n=384)
    # Winrate MOYEN PLUS correct mais pas exceptionnel → on garde FORT
    "HT05":           "FORT",         # 65.6% à MOYEN PLUS (n=619)
    "TEAM2_SCORE_FT": "FORT",         # 68.8% à MOYEN PLUS (n=832)
    # O25_FT : pas encore de données calibrées → seuil prudent
    "O25_FT":         "FORT",
    # U35_FT : nouveau pari, seuil prudent en attendant calibration
    "U35_FT":         "FORT",
    # Paris WIN : winrate MOYEN PLUS trop faible → on monte
    "TEAM1_WIN_FT":   "FORT PLUS",    # 55.8% à MOYEN PLUS (n=54)
    "TEAM2_WIN_FT":   "FORT PLUS",    # 43.2% à MOYEN PLUS (n=155)
}

_DYNAMIC_THRESHOLDS_FILE = Path("data/min_level_by_bet.json")


def _load_dynamic_thresholds() -> None:
    """
    Charge data/min_level_by_bet.json (généré par compute_label_thresholds.py)
    et met à jour MIN_LEVEL_BY_BET avec les seuils calculés dynamiquement.
    Seuls les bet_keys avec un min_level non-null sont mis à jour.
    """
    if not _DYNAMIC_THRESHOLDS_FILE.exists():
        return
    try:
        data = json.loads(_DYNAMIC_THRESHOLDS_FILE.read_text(encoding="utf-8"))
        for bet_key, info in data.items():
            min_level = info.get("min_level")
            if min_level is not None:
                MIN_LEVEL_BY_BET[bet_key] = min_level
    except Exception:
        pass  # En cas d'erreur, on garde les valeurs codées en dur


_load_dynamic_thresholds()


def _is_exportable(level: str, bet_key: str = "") -> bool:
    threshold = MIN_LEVEL_BY_BET.get(bet_key, MIN_LEVEL_EXPORT)
    return _level_index(level) >= _level_index(threshold)


def _level_name(idx: int) -> str:
    safe_idx = int(_clamp(float(idx), 0.0, float(len(LEVELS) - 1)))
    return LEVELS[safe_idx]


def _verdict_color_name(level: str) -> str:
    lvl = (level or "").strip().upper()

    # Rouge
    if lvl in ("KO", "FAIBLE"):
        return _color(level, "bad")

    # Jaune
    if lvl in ("MOYEN", "MOYEN PLUS", "FORT"):
        return _color(level, "warn")

    # Vert : FORT PLUS et +
    return _color(level, "ok")


def _base_level_from_pct_single(pct: float) -> str:
    """
    Base sur 8 matchs => paliers 12.5 (50 / 62.5 / 75 / 87.5 / 100)
    Langage unique LEVELS.

    Choix simple :
    - < 50   => KO
    - < 62.5 => FAIBLE
    - < 75   => MOYEN
    - < 87.5 => MOYEN PLUS
    - < 100  => FORT
    - =100   => TRÈS FORT
    (les niveaux au-dessus viennent des boosts)
    """
    if pct < 50.0:
        return "KO"
    if pct < 62.5:
        return "FAIBLE"
    if pct < 75.0:
        return "MOYEN"
    if pct < 87.5:
        return "MOYEN PLUS"
    if pct < 100.0:
        return "FORT"
    return "TRÈS FORT"


def _cap_h2h_if_weak(idx: int, h2h_n: int, h2h_count_ok: int) -> Tuple[int, bool]:
    """
    CAP global demandé (tous les paris) :
    - si H2H(3) ne valide le pari que 0/3 ou 1/3 => CAP.
    Ici : on plafonne à MOYEN PLUS MAX.
    """
    applied = False
    if h2h_n >= 3 and h2h_count_ok <= 1:
        cap_idx = _level_index("MOYEN PLUS")
        idx = min(idx, cap_idx)
        applied = True
    return idx, applied


# ----------------------------------------------------
# Dates / H2H "les plus récents"
# ----------------------------------------------------
def _parse_date_to_ts(value: Any) -> Optional[int]:
    """
    Essaie d'extraire un timestamp (secondes) depuis:
    - int/float timestamp (souvent en secondes; parfois ms)
    - string ISO (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS...)
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        v = int(value)
        if v > 10_000_000_000:  # probablement ms
            v = v // 1000
        return v

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if "T" in s:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(s)
            return int(dt.timestamp())
        except Exception:
            return None

    return None


def _select_h2h_recent(h2h_mapped: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    """
    Retourne les n H2H les plus récents.
    - si timestamp/date dispo -> tri asc puis on prend les derniers n
    - sinon -> fallback: on prend les derniers n de la liste (supposée old->new)
    """
    if not h2h_mapped:
        return []

    with_ts: List[Tuple[int, Dict[str, Any]]] = []
    for m in h2h_mapped:
        ts = m.get("_ts")
        if isinstance(ts, int):
            with_ts.append((ts, m))

    if with_ts:
        with_ts.sort(key=lambda x: x[0])
        return [m for _, m in with_ts[-n:]]

    return h2h_mapped[-n:]


# ----------------------------------------------------
# Parsing / détections (HT)
# ----------------------------------------------------
def _has_goal_ht_from_match_dict(m: Dict[str, Any]) -> bool:
    """
    Détecte si au moins 1 but en 1ère mi-temps.

    Formats acceptés (ordre de priorité) :
    - has_ht_goal (bool)
    - ht_total (int/float) >= 1
    - ht_goals_total (legacy) >= 1
    - first_goal_minute <= 45
    - goals_minutes / goal_minutes / goal_times : min <= 45
    """
    if "has_ht_goal" in m and m.get("has_ht_goal") is not None:
        return bool(m.get("has_ht_goal"))

    ht_total = m.get("ht_total")
    if isinstance(ht_total, (int, float)):
        return float(ht_total) >= 1.0

    ht_total_legacy = m.get("ht_goals_total")
    if isinstance(ht_total_legacy, (int, float)):
        return float(ht_total_legacy) >= 1.0

    fg = m.get("first_goal_minute")
    if fg is not None:
        try:
            return int(fg) <= 45
        except Exception:
            pass

    mins = m.get("goals_minutes") or m.get("goal_minutes") or m.get("goal_times")
    if isinstance(mins, list) and mins:
        cleaned: List[int] = []
        for x in mins:
            try:
                cleaned.append(int(x))
            except Exception:
                continue
        if cleaned:
            return min(cleaned) <= 45

    return False


def _focus_is_home(m: Dict[str, Any]) -> Optional[bool]:
    """
    Détermine si l'équipe "focus" est à domicile pour ce match.
    - is_home True/False prioritaire
    - sinon venue "home"/"away"
    - sinon None
    """
    if m.get("is_home") is True:
        return True
    if m.get("is_home") is False:
        return False

    venue = (m.get("venue") or "").lower().strip()
    if venue == "home":
        return True
    if venue == "away":
        return False

    return None


def _get_ht_score(m: Dict[str, Any]) -> Tuple[int, int]:
    """
    Retourne (goals_for_HT, goals_against_HT) pour l'équipe 'focus' du match.

    Formats acceptés (ordre) :
    - ht_goals_for / ht_goals_against
    - ht_for / ht_against (legacy)
    - ht_home + ht_away + venue/is_home (si dispo)
    - half_time_score "1-0" ou "1:0" ou dict {home, away}
      ✅ IMPORTANT : on respecte HOME/AWAY (si focus away => inversion)
    """
    if m.get("ht_goals_for") is not None or m.get("ht_goals_against") is not None:
        return _safe_int(m.get("ht_goals_for")), _safe_int(m.get("ht_goals_against"))

    if m.get("ht_for") is not None or m.get("ht_against") is not None:
        return _safe_int(m.get("ht_for")), _safe_int(m.get("ht_against"))

    focus_home = _focus_is_home(m)

    if m.get("ht_home") is not None and m.get("ht_away") is not None:
        ht_home = _safe_int(m.get("ht_home"))
        ht_away = _safe_int(m.get("ht_away"))

        if focus_home is True:
            return ht_home, ht_away
        if focus_home is False:
            return ht_away, ht_home

        return ht_home, ht_away

    hts = m.get("half_time_score") or m.get("ht_score")
    if isinstance(hts, str):
        s = hts.replace(":", "-").strip()
        parts = s.split("-")
        if len(parts) == 2:
            home_ht = _safe_int(parts[0])
            away_ht = _safe_int(parts[1])
            if focus_home is False:
                return away_ht, home_ht
            return home_ht, away_ht

    if isinstance(hts, dict):
        if "home" in hts and "away" in hts:
            home_ht = _safe_int(hts.get("home"))
            away_ht = _safe_int(hts.get("away"))
            if focus_home is False:
                return away_ht, home_ht
            return home_ht, away_ht

    return 0, 0


def _compute_ht_goal_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_has_goal_ht_from_match_dict(m) for m in matches])


def _compute_ht_goals_avg(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    vals: List[float] = []
    for m in matches:
        if isinstance(m.get("ht_total"), (int, float)):
            vals.append(float(m["ht_total"]))
        else:
            gf, ga = _get_ht_score(m)
            vals.append(float(gf + ga))
    return _average(vals)


def _compute_ht_double_chance_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    flags: List[bool] = []
    for m in matches:
        gf, ga = _get_ht_score(m)
        flags.append(gf >= ga)
    return 100.0 * _count_ratio(flags)


def _compute_ht_not_lead_pct(matches: List[Dict[str, Any]]) -> float:
    """
    % de matchs où l'équipe focus NE mène PAS à la mi-temps (gf <= ga).
    (utile pour mesurer "danger" inverse : si l'adversaire mène rarement, c'est bon)
    """
    if not matches:
        return 0.0
    flags: List[bool] = []
    for m in matches:
        gf, ga = _get_ht_score(m)
        flags.append(gf <= ga)
    return 100.0 * _count_ratio(flags)


def _filter_by_venue(matches: List[Dict[str, Any]], want: str) -> List[Dict[str, Any]]:
    """
    want: "home" ou "away"
    Filtre sur is_home / venue.
    """
    w = (want or "").lower().strip()
    out: List[Dict[str, Any]] = []
    for m in (matches or []):
        is_home = _focus_is_home(m)
        if w == "home" and is_home is True:
            out.append(m)
        elif w == "away" and is_home is False:
            out.append(m)
    return out


# ----------------------------------------------------
# H2H mapping + inférence HOME/AWAY du focus
# ----------------------------------------------------
def _norm_team(s: Any) -> str:
    return str(s or "").strip().lower()


def _extract_team_names_from_h2h(raw: Dict[str, Any]) -> Tuple[str, str]:
    home = (
        raw.get("home_name")
        or raw.get("homeTeam")
        or (raw.get("teams", {}) or {}).get("home", {}).get("name")
        or (raw.get("home", {}) or {}).get("name")
        or ""
    )
    away = (
        raw.get("away_name")
        or raw.get("awayTeam")
        or (raw.get("teams", {}) or {}).get("away", {}).get("name")
        or (raw.get("away", {}) or {}).get("name")
        or ""
    )
    return str(home or ""), str(away or "")


def _infer_is_home_for_focus(raw: Dict[str, Any], focus_team: str) -> Optional[bool]:
    if raw.get("is_home") is True:
        return True
    if raw.get("is_home") is False:
        return False

    venue = (raw.get("venue") or "").lower().strip()
    if venue == "home":
        return True
    if venue == "away":
        return False

    if not focus_team:
        return None

    home_name, away_name = _extract_team_names_from_h2h(raw)
    f = _norm_team(focus_team)
    h = _norm_team(home_name)
    a = _norm_team(away_name)

    if f and h and (f == h or f in h or h in f):
        return True
    if f and a and (f == a or f in a or a in f):
        return False

    return None


def _map_h2h(h2h: List[Dict[str, Any]], focus_team: str = "") -> List[Dict[str, Any]]:
    mapped: List[Dict[str, Any]] = []
    for m in (h2h or []):
        raw_ts = m.get("timestamp") or m.get("ts") or m.get("time") or m.get("date")

        inferred_is_home = _infer_is_home_for_focus(m, focus_team)
        inferred_venue = None
        if inferred_is_home is True:
            inferred_venue = "home"
        elif inferred_is_home is False:
            inferred_venue = "away"

        is_home_final = m.get("is_home")
        venue_final = m.get("venue")
        if inferred_is_home is not None:
            is_home_final = inferred_is_home
            venue_final = inferred_venue

        mapped.append(
            {
                "_ts": _parse_date_to_ts(raw_ts),

                "has_ht_goal": m.get("has_ht_goal"),
                "ht_total": m.get("ht_total"),
                "ht_goals_total": m.get("ht_goals_total"),
                "first_goal_minute": m.get("first_goal_minute"),
                "goals_minutes": m.get("goals_minutes") or m.get("goal_minutes") or m.get("goal_times"),

                "ht_goals_for": m.get("ht_goals_for"),
                "ht_goals_against": m.get("ht_goals_against"),
                "ht_home": m.get("ht_home"),
                "ht_away": m.get("ht_away"),

                "half_time_score": m.get("half_time_score") or m.get("ht_score"),

                "is_home": is_home_final,
                "venue": venue_final,

                # FT goals (si dispo dans H2H)
                "goals_home": m.get("goals_home"),
                "goals_away": m.get("goals_away"),
            }
        )
    return mapped


# ----------------------------------------------------
# FT helpers (buts / victoire)
# ----------------------------------------------------
def _ft_goals_for_against(m: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """
    Essaie de sortir (gf, ga) pour l'équipe focus sur un match "last".
    Champs acceptés :
    - goals_for / goals_against
    - gf / ga
    """
    gf = m.get("goals_for")
    ga = m.get("goals_against")
    if isinstance(gf, (int, float)) and isinstance(ga, (int, float)):
        return int(gf), int(ga)

    gf2 = m.get("gf")
    ga2 = m.get("ga")
    if isinstance(gf2, (int, float)) and isinstance(ga2, (int, float)):
        return int(gf2), int(ga2)

    return None, None


def _team_won_ft(m: Dict[str, Any]) -> bool:
    gf, ga = _ft_goals_for_against(m)
    if gf is not None and ga is not None:
        return gf > ga

    # fallback: result string
    res = (m.get("result") or m.get("ft_result") or "").strip().lower()
    if res in ("w", "win", "won", "victoire"):
        return True
    if res in ("l", "loss", "lost", "défaite", "defaite"):
        return False

    return False


def _team_lost_ft(m: Dict[str, Any]) -> bool:
    gf, ga = _ft_goals_for_against(m)
    if gf is not None and ga is not None:
        return gf < ga

    res = (m.get("result") or m.get("ft_result") or "").strip().lower()
    if res in ("l", "loss", "lost", "défaite", "defaite"):
        return True
    if res in ("w", "win", "won", "victoire"):
        return False

    return False


# ----------------------------------------------------
# 1) PARI : +0.5 BUT À LA MI-TEMPS (paliers + badges)
# ----------------------------------------------------
def _base_level_ht05(pct_a: float, pct_b: float) -> Tuple[str, Dict[str, Any]]:
    lo = min(pct_a, pct_b)
    hi = max(pct_a, pct_b)
    info = {"lo": lo, "hi": hi}

    if lo < 50.0 and hi < 50.0:
        return "KO", info
    if lo < 50.0 and hi < 62.5:
        return "KO", info

    if lo >= 50.0 and hi < 62.5:
        return "FAIBLE", info
    if lo >= 50.0 and hi >= 62.5 and hi < 75.0:
        return "MOYEN", info
    if lo >= 62.5 and hi < 75.0:
        return "MOYEN PLUS", info
    if lo >= 62.5 and hi >= 75.0 and hi < 87.5:
        return "FORT", info
    if lo >= 75.0 and hi < 87.5:
        return "FORT PLUS", info
    if lo >= 75.0 and hi >= 87.5:
        if (lo == 100.0 and hi >= 87.5) or (hi == 100.0 and lo >= 87.5):
            return "MEGA EXPLOSION", info
        if lo >= 87.5 and hi >= 87.5:
            return "EXPLOSION", info
        return "TRÈS FORT", info

    return "MOYEN", info


def _ht05_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(matches_recent)
    pct = _compute_ht_goal_pct(matches_recent)
    avg_ht = _compute_ht_goals_avg(matches_recent)

    count_ht_goal = sum(1 for m in matches_recent if _has_goal_ht_from_match_dict(m))

    malus = 0
    if n >= 4 and count_ht_goal <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ht_goal >= 3)

    max_ht = 0
    for m in matches_recent:
        if isinstance(m.get("ht_total"), (int, float)):
            max_ht = max(max_ht, int(m.get("ht_total") or 0))
        else:
            gf, ga = _get_ht_score(m)
            max_ht = max(max_ht, gf + ga)

    explosive = (max_ht >= 3)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)
    if explosive:
        boost = max(boost, 2)

    return {
        "n": n,
        "pct": pct,
        "avg_ht": avg_ht,
        "count_ht_goal": count_ht_goal,
        "malus": malus,
        "regular_badge": regular_badge,
        "explosive_badge": explosive,
        "boost": boost,
        "max_ht": max_ht,
    }


def _ht05_h2h_badges(h2h_last3: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(h2h_last3)
    pct = _compute_ht_goal_pct(h2h_last3)
    count = sum(1 for m in h2h_last3 if _has_goal_ht_from_match_dict(m))

    verrou = False
    malus = 0
    boost = 0

    if n >= 3:
        if count <= 1:
            verrou = True
            malus = -1
        elif count == 3:
            boost = 1

    return {"n": n, "pct": pct, "count": count, "verrou": verrou, "malus": malus, "boost": boost}


def _final_verdict_ht05(team_a_last: List[Dict[str, Any]], team_b_last: List[Dict[str, Any]], h2h: List[Dict[str, Any]]) -> Dict[str, Any]:
    a8 = (team_a_last or [])[:8]
    b8 = (team_b_last or [])[:8]

    pct_a8 = _compute_ht_goal_pct(a8)
    pct_b8 = _compute_ht_goal_pct(b8)

    base_level, base_info = _base_level_ht05(pct_a8, pct_b8)
    idx_base = _level_index(base_level)
    idx = idx_base

    a4 = (team_a_last or [])[:4]
    b4 = (team_b_last or [])[:4]
    recent_a = _ht05_badges_recent(a4)
    recent_b = _ht05_badges_recent(b4)

    h2h_mapped = _map_h2h(h2h, focus_team="")
    h2h3 = _select_h2h_recent(h2h_mapped, 3)
    h2h_badge = _ht05_h2h_badges(h2h3)

    # malus
    malus_recent = -1 if (recent_a["malus"] < 0 or recent_b["malus"] < 0) else 0
    malus_h2h = -1 if (h2h_badge.get("malus") or 0) < 0 else 0

    idx_after_malus = idx + malus_recent + malus_h2h
    idx = idx_after_malus

    # boosts (2 meilleurs)
    boost_a = int(recent_a.get("boost") or 0)
    boost_b = int(recent_b.get("boost") or 0)
    boost_h2h = int(h2h_badge.get("boost") or 0)

    boosts = sorted([boost_a, boost_b, boost_h2h], reverse=True)
    kept1 = boosts[0] if boosts else 0
    kept2 = boosts[1] if len(boosts) >= 2 else 0
    total_boost = int(_clamp(float(kept1 + kept2), 0.0, 4.0))

    idx_before_boost = idx
    idx += total_boost
    idx_after_boost = idx

    explosivite_badge = (idx_after_boost - idx_before_boost) >= 2

    final_level = _level_name(idx)

    h2h_floor_applied = False
    if h2h_badge["n"] >= 3 and h2h_badge["count"] == 3:
        floor_idx = _level_index("MOYEN PLUS")
        if _level_index(final_level) < floor_idx:
            final_level = "MOYEN PLUS"
            h2h_floor_applied = True

    final_idx = _level_index(final_level)
    final_idx, h2h_cap_applied = _cap_h2h_if_weak(final_idx, h2h_badge["n"], h2h_badge["count"])
    final_level = _level_name(final_idx)

    keep = _is_exportable(final_level)

    return {
        "bet": "HT_OVER_0_5",
        "keep": keep,
        "base_level": base_level,
        "final_level": final_level,
        "explosivite_badge": explosivite_badge,
        "pct_a8": pct_a8,
        "pct_b8": pct_b8,
        "recent_a": recent_a,
        "recent_b": recent_b,
        "h2h": h2h_badge,
        "base_info": base_info,
        "total_boost": total_boost,
        "boost_a": boost_a,
        "boost_b": boost_b,
        "boost_h2h": boost_h2h,
        "kept_boost_1": kept1,
        "kept_boost_2": kept2,
        "malus_recent": malus_recent,
        "malus_h2h": malus_h2h,
        "idx_base": idx_base,
        "idx_after_malus": idx_after_malus,
        "idx_after_boost": idx_after_boost,
        "h2h_floor_applied": h2h_floor_applied,
        "h2h_cap_applied": h2h_cap_applied,
    }


# ----------------------------------------------------
# 2) PARI : CHANCE DOUBLE MI-TEMPS (DOMICILE) (1X HT Home)
# ----------------------------------------------------
def _dcht_adversary_badges(away_team_last: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges adversaire (AWAY, tous matchs) :
    - on calcule % où l'adversaire mène à la mi-temps (danger)
    - bonus si adversaire mène rarement, malus s'il mène souvent
    """
    last8 = (away_team_last or [])[:8]
    if not last8:
        return {"n": 0, "good": 0.0, "bad": 0.0, "bonus": 0, "malus": 0, "notes": ["Pas de données adversaire."]}

    flags_adv_leads: List[bool] = []
    for m in last8:
        gf, ga = _get_ht_score(m)
        flags_adv_leads.append(gf > ga)

    pct_adv_leads = 100.0 * _count_ratio(flags_adv_leads)
    pct_adv_not_lead = 100.0 - pct_adv_leads

    bonus = 0
    malus = 0
    notes: List[str] = []

    if pct_adv_leads <= 25.0:
        bonus = max(bonus, 2)
        notes.append("L’adversaire mène rarement à la mi-temps (≤25%).")
    elif pct_adv_leads <= 37.5:
        bonus = max(bonus, 1)
        notes.append("L’adversaire mène peu souvent à la mi-temps (≤37.5%).")

    if pct_adv_leads >= 62.5:
        malus = -2
        notes.append("⚠️ L’adversaire mène souvent à la mi-temps (≥62.5%).")
    elif pct_adv_leads >= 50.0:
        malus = -1
        notes.append("⚠️ L’adversaire mène régulièrement à la mi-temps (≥50%).")

    return {
        "n": len(last8),
        "good": pct_adv_not_lead,
        "bad": pct_adv_leads,
        "bonus": bonus,
        "malus": malus,
        "notes": notes,
    }


def _final_verdict_dcht(
    home_team_name: str,
    home_last: List[Dict[str, Any]],
    away_team_name: str,
    away_last: List[Dict[str, Any]],
    h2h: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    (inchangé)
    """
    # HOME : filtre domicile
    home_only = _filter_by_venue(home_last or [], "home")
    home8 = home_only[:8]
    home4 = home_only[:4]

    # AWAY : tous matchs
    away_all8 = (away_last or [])[:8]
    away_all4 = (away_last or [])[:4]

    pct_home8 = _compute_ht_double_chance_pct(home8)
    pct_home4 = _compute_ht_double_chance_pct(home4)

    pct_away_not_lead8 = _compute_ht_not_lead_pct(away_all8)
    pct_away_not_lead4 = _compute_ht_not_lead_pct(away_all4)

    base_avg8 = _average([pct_home8, pct_away_not_lead8]) if (home8 or away_all8) else 0.0
    base_level = _base_level_from_pct_single(base_avg8)
    idx = _level_index(base_level)

    recent_delta_home = 0
    if len(home4) >= 4:
        count_ok_home4 = int(round((pct_home4 / 100.0) * len(home4)))
        if count_ok_home4 <= 1:
            recent_delta_home = -1

    recent_delta_away = 0
    if len(away_all4) >= 4:
        if pct_away_not_lead4 <= 25.0:
            recent_delta_away = -1

    idx += recent_delta_home + recent_delta_away
    recent_delta = recent_delta_home + recent_delta_away

    adv = _dcht_adversary_badges(away_last)
    adv_bonus = int(adv.get("bonus") or 0)
    adv_malus = int(adv.get("malus") or 0)
    idx += adv_bonus + adv_malus

    h2h_mapped = _map_h2h(h2h, focus_team=home_team_name)
    h2h3 = _select_h2h_recent(h2h_mapped, 3)

    pct_h2h3 = _compute_ht_double_chance_pct(h2h3) if h2h3 else 0.0
    count_h2h3 = int(round((pct_h2h3 / 100.0) * len(h2h3))) if h2h3 else 0

    h2h_floor_applied = False
    if len(h2h3) >= 3 and count_h2h3 >= 2:
        idx = max(idx, _level_index("MOYEN PLUS"))
        h2h_floor_applied = True

    idx, h2h_cap_applied = _cap_h2h_if_weak(idx, len(h2h3), count_h2h3)

    verdict = _level_name(idx)
    keep = _is_exportable(verdict)
    return {
        "bet": "HOME_HT_DOUBLE_CHANCE",
        "keep": keep,
        "base_level": base_level,
        "final_level": verdict,
        "pct_home8": pct_home8,
        "pct_home4": pct_home4,
        "home_only_n8": len(home8),
        "home_only_n4": len(home4),
        "pct_away_not_lead8": pct_away_not_lead8,
        "pct_away_not_lead4": pct_away_not_lead4,
        "away_all_n8": len(away_all8),
        "away_all_n4": len(away_all4),
        "base_avg8": base_avg8,
        "recent_avg4": _average([pct_home4, pct_away_not_lead4]) if (home4 or away_all4) else 0.0,
        "recent_delta": recent_delta,
        "recent_delta_home": recent_delta_home,
        "recent_delta_away": recent_delta_away,
        "adv": adv,
        "adv_bonus": adv_bonus,
        "adv_malus": adv_malus,
        "pct_h2h3": pct_h2h3,
        "count_h2h3": count_h2h3,
        "h2h_n": len(h2h3),
        "h2h_floor_applied": h2h_floor_applied,
        "h2h_cap_applied": h2h_cap_applied,
    }


# ----------------------------------------------------
# 3) PARI : TELLE EQUIPE MARQUE
# ----------------------------------------------------
def _team_scored_ft(m: Dict[str, Any]) -> bool:
    gf = m.get("goals_for")
    if isinstance(gf, (int, float)):
        return int(gf) >= 1

    gf2 = m.get("gf") or m.get("goals_scored")
    if isinstance(gf2, (int, float)):
        return int(gf2) >= 1

    return False


def _team_conceded_ft(m: Dict[str, Any]) -> bool:
    ga = m.get("goals_against")
    if isinstance(ga, (int, float)):
        return int(ga) >= 1

    ga2 = m.get("ga") or m.get("goals_conceded")
    if isinstance(ga2, (int, float)):
        return int(ga2) >= 1

    return False


def _compute_team_score_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_team_scored_ft(m) for m in matches])


def _compute_team_concede_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_team_conceded_ft(m) for m in matches])


def _h2h_team_scored_pct(h2h: List[Dict[str, Any]], focus_team: str) -> Tuple[float, int, int]:
    if not h2h:
        return 0.0, 0, 0

    ok = 0
    n = 0
    f = _norm_team(focus_team)

    for m in h2h:
        home_name, away_name = _extract_team_names_from_h2h(m)
        h = _norm_team(home_name)
        a = _norm_team(away_name)

        gh = m.get("goals_home")
        ga = m.get("goals_away")

        if not isinstance(gh, (int, float)) or not isinstance(ga, (int, float)):
            continue

        gh_i = int(gh)
        ga_i = int(ga)

        is_focus_home = (f and h and (f == h or f in h or h in f))
        is_focus_away = (f and a and (f == a or f in a or a in f))

        if not (is_focus_home or is_focus_away):
            continue

        n += 1
        if is_focus_home and gh_i >= 1:
            ok += 1
        elif is_focus_away and ga_i >= 1:
            ok += 1

    pct = (100.0 * ok / n) if n > 0 else 0.0
    return pct, ok, n


def _final_verdict_team_to_score(
    team_name: str,
    team_last: List[Dict[str, Any]],
    opp_name: str,
    opp_last: List[Dict[str, Any]],
    h2h: List[Dict[str, Any]],
) -> Dict[str, Any]:
    t8 = (team_last or [])[:8]
    o8 = (opp_last or [])[:8]
    t4 = (team_last or [])[:4]
    o4 = (opp_last or [])[:4]

    pct_team_scores8 = _compute_team_score_pct(t8)
    pct_opp_concedes8 = _compute_team_concede_pct(o8)

    base_avg8 = _average([pct_team_scores8, pct_opp_concedes8]) if (t8 or o8) else 0.0
    base_level = _base_level_from_pct_single(base_avg8)
    idx = _level_index(base_level)

    pct_team_scores4 = _compute_team_score_pct(t4)
    pct_opp_concedes4 = _compute_team_concede_pct(o4)

    malus_recent = 0
    if len(t4) >= 4:
        count_ok_team4 = sum(1 for m in t4 if _team_scored_ft(m))
        if count_ok_team4 <= 1:
            malus_recent -= 1

    if len(o4) >= 4:
        count_ok_opp4 = sum(1 for m in o4 if _team_conceded_ft(m))
        if count_ok_opp4 <= 1:
            malus_recent -= 1

    idx += malus_recent

    h2h_pct, h2h_ok, h2h_n = _h2h_team_scored_pct(h2h, focus_team=team_name)

    boost_h2h = 0
    malus_h2h = 0
    if h2h_n >= 3:
        if h2h_ok <= 1:
            malus_h2h = -1
        elif h2h_ok == 3:
            boost_h2h = 1

    idx += boost_h2h + malus_h2h

    idx, h2h_cap_applied = _cap_h2h_if_weak(idx, h2h_n, h2h_ok)
    final_level = _level_name(idx)
    keep = _is_exportable(final_level)

    return {
        "bet": "TEAM_TO_SCORE",
        "keep": keep,
        "base_level": base_level,
        "final_level": final_level,
        "pct_team_scores8": pct_team_scores8,
        "pct_opp_concedes8": pct_opp_concedes8,
        "pct_team_scores4": pct_team_scores4,
        "pct_opp_concedes4": pct_opp_concedes4,
        "base_avg8": base_avg8,
        "malus_recent": malus_recent,
        "h2h_pct": h2h_pct,
        "h2h_ok": h2h_ok,
        "h2h_n": h2h_n,
        "boost_h2h": boost_h2h,
        "malus_h2h": malus_h2h,
        "h2h_cap_applied": h2h_cap_applied,
    }


def _build_human_explain_team_to_score(team: str, opp: str, verdict: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(verdict.get("base_level") or "")
    final = str(verdict.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team} marque au moins 1 but dans { _format_pct(float(verdict.get('pct_team_scores8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {opp} encaisse au moins 1 but dans { _format_pct(float(verdict.get('pct_opp_concedes8') or 0.0)) } des matchs."))

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team} marque dans { _format_pct(float(verdict.get('pct_team_scores4') or 0.0)) } des matchs."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {opp} encaisse dans { _format_pct(float(verdict.get('pct_opp_concedes4') or 0.0)) } des matchs."))

    h2h_n = int(verdict.get("h2h_n") or 0)
    if h2h_n >= 3:
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, {team} a marqué dans { _format_pct(float(verdict.get('h2h_pct') or 0.0)) } des matchs ({int(verdict.get('h2h_ok') or 0)}/3)."))

    if verdict.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H trop faible (0/3 ou 1/3) ⇒ le verdict ne peut pas dépasser MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# 4) PARI : OVER 1.5 (FT)
# ----------------------------------------------------
def _match_over15_ft(m: Dict[str, Any]) -> bool:
    """
    True si total buts FT >= 2
    - via ft_total/goals_total
    - via goals_for+goals_against (focus)
    - fallback: score "1-1"
    """
    ft_total = m.get("ft_total") or m.get("goals_total")
    if isinstance(ft_total, (int, float)):
        return float(ft_total) >= 2.0

    gf, ga = _ft_goals_for_against(m)
    if gf is not None and ga is not None:
        return (gf + ga) >= 2

    score = m.get("score") or m.get("full_time_score") or m.get("ft_score")
    if isinstance(score, str):
        s = score.replace(":", "-").strip()
        parts = s.split("-")
        if len(parts) == 2:
            a = _safe_int(parts[0])
            b = _safe_int(parts[1])
            return (a + b) >= 2

    return False


def _compute_over15_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_match_over15_ft(m) for m in matches])


def _over15_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges récents (Over 1.5) :
    - malus si 0/4 ou 1/4 en over1.5
    - regular_badge si >=3/4
    - explosive_badge si un match à 5+ buts
    - boosts = max(regular, regular&100%, explosive)
    """
    n = len(matches_recent)
    pct = _compute_over15_pct(matches_recent)
    count_ok = sum(1 for m in matches_recent if _match_over15_ft(m))

    malus = 0
    if n >= 4 and count_ok <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ok >= 3)

    max_ft = 0
    for m in matches_recent:
        gf, ga = _ft_goals_for_against(m)
        if gf is not None and ga is not None:
            max_ft = max(max_ft, gf + ga)
        else:
            ft_total = m.get("ft_total") or m.get("goals_total")
            if isinstance(ft_total, (int, float)):
                max_ft = max(max_ft, int(ft_total))

    explosive = (max_ft >= 5)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)
    if explosive:
        boost = max(boost, 2)

    return {
        "n": n,
        "pct": pct,
        "count_ok": count_ok,
        "malus": malus,
        "regular_badge": regular_badge,
        "explosive_badge": explosive,
        "boost": boost,
        "max_ft": max_ft,
    }


def _h2h_over15_pct(h2h: List[Dict[str, Any]]) -> Tuple[float, int, int]:
    """
    Over 1.5 sur H2H : goals_home + goals_away >= 2
    """
    if not h2h:
        return 0.0, 0, 0
    ok = 0
    n = 0
    for m in h2h:
        gh = m.get("goals_home")
        ga = m.get("goals_away")
        if not isinstance(gh, (int, float)) or not isinstance(ga, (int, float)):
            continue
        n += 1
        if (int(gh) + int(ga)) >= 2:
            ok += 1
    pct = (100.0 * ok / n) if n > 0 else 0.0
    return pct, ok, n


def _final_verdict_over15(team1_last: List[Dict[str, Any]], team2_last: List[Dict[str, Any]], h2h: List[Dict[str, Any]]) -> Dict[str, Any]:
    a8 = (team1_last or [])[:8]
    b8 = (team2_last or [])[:8]

    pct_a8 = _compute_over15_pct(a8)
    pct_b8 = _compute_over15_pct(b8)

    base_level, base_info = _base_level_ft_over15(pct_a8, pct_b8)
    idx_base = _level_index(base_level)
    idx = idx_base

    a4 = (team1_last or [])[:4]
    b4 = (team2_last or [])[:4]
    recent_a = _over15_badges_recent(a4)
    recent_b = _over15_badges_recent(b4)

    h2h_mapped = _map_h2h(h2h, focus_team="")
    h2h3 = _select_h2h_recent(h2h_mapped, 3)
    h2h_pct, h2h_ok, h2h_n = _h2h_over15_pct(h2h3)

    boost_h2h = 0
    malus_h2h = 0
    if h2h_n >= 3:
        if h2h_ok <= 1:
            malus_h2h = -1
        elif h2h_ok == 3:
            boost_h2h = 1

    malus_recent = -1 if (int(recent_a.get("malus") or 0) < 0 or int(recent_b.get("malus") or 0) < 0) else 0

    idx_after_malus = idx + malus_recent + malus_h2h
    idx = idx_after_malus

    boost_a = int(recent_a.get("boost") or 0)
    boost_b = int(recent_b.get("boost") or 0)

    boosts = sorted([boost_a, boost_b, boost_h2h], reverse=True)
    kept1 = boosts[0] if boosts else 0
    kept2 = boosts[1] if len(boosts) >= 2 else 0
    total_boost = int(_clamp(float(kept1 + kept2), 0.0, 4.0))

    idx_before_boost = idx
    idx += total_boost
    idx_after_boost = idx

    explosivite_badge = (idx_after_boost - idx_before_boost) >= 2

    final_level = _level_name(idx)
    final_idx = _level_index(final_level)
    final_idx, h2h_cap_applied = _cap_h2h_if_weak(final_idx, h2h_n, h2h_ok)
    final_level = _level_name(final_idx)

    keep = _is_exportable(final_level)

    return {
        "bet": "FT_OVER_1_5",
        "keep": keep,
        "base_level": base_level,
        "final_level": final_level,
        "explosivite_badge": explosivite_badge,
        "pct_a8": pct_a8,
        "pct_b8": pct_b8,
        "recent_a": recent_a,
        "recent_b": recent_b,
        "h2h_pct": h2h_pct,
        "h2h_ok": h2h_ok,
        "h2h_n": h2h_n,
        "base_info": base_info,
        "boost_a": boost_a,
        "boost_b": boost_b,
        "boost_h2h": boost_h2h,
        "kept_boost_1": kept1,
        "kept_boost_2": kept2,
        "total_boost": total_boost,
        "malus_recent": malus_recent,
        "malus_h2h": malus_h2h,
        "idx_base": idx_base,
        "idx_after_malus": idx_after_malus,
        "idx_after_boost": idx_after_boost,
        "h2h_cap_applied": h2h_cap_applied,
    }


def _build_human_explain_over15(team1: str, team2: str, v: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(v.get("base_level") or "")
    final = str(v.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team1} finit en Over 1.5 dans { _format_pct(float(v.get('pct_a8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {team2} finit en Over 1.5 dans { _format_pct(float(v.get('pct_b8') or 0.0)) } des matchs."))

    ra = v.get("recent_a") or {}
    rb = v.get("recent_b") or {}

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team1} est à { _format_pct(float(ra.get('pct') or 0.0)) } (match le plus riche : {ra.get('max_ft', 0)} buts)."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team2} est à { _format_pct(float(rb.get('pct') or 0.0)) } (match le plus riche : {rb.get('max_ft', 0)} buts)."))

    h2h_n = int(v.get("h2h_n") or 0)
    if h2h_n >= 3:
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, Over 1.5 dans { _format_pct(float(v.get('h2h_pct') or 0.0)) } des matchs ({int(v.get('h2h_ok') or 0)}/3)."))

    boost_a = int(v.get("boost_a") or 0)
    boost_b = int(v.get("boost_b") or 0)
    boost_h2h = int(v.get("boost_h2h") or 0)

    kept1 = int(v.get("kept_boost_1") or 0)
    kept2 = int(v.get("kept_boost_2") or 0)
    total_boost = int(v.get("total_boost") or 0)

    malus_recent = int(v.get("malus_recent") or 0)
    malus_h2h = int(v.get("malus_h2h") or 0)

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))
    lines.append(_bullet(f"Boosts détectés : {team1}={_color_delta(boost_a)}  |  {team2}={_color_delta(boost_b)}  |  H2H={_color_delta(boost_h2h)}."))

    if total_boost > 0:
        lines.append(_bullet(f"Boost total appliqué : { _color_delta(total_boost) } (on garde les 2 meilleurs : {kept1} et {kept2})."))
    else:
        lines.append(_bullet("Aucun boost notable sur les signaux forts."))

    if malus_recent != 0:
        lines.append(_bullet(f"Malus récents : { _color_delta(malus_recent) } (une équipe a fait 0/4 ou 1/4)."))

    if h2h_n >= 3:
        lines.append(_bullet(f"H2H (3 derniers) : { _format_pct(float(v.get('h2h_pct') or 0.0)) } = {int(v.get('h2h_ok') or 0)}/3 en Over 1.5."))

    if malus_h2h != 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(malus_h2h) } (0/3 ou 1/3)."))

    if boost_h2h > 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(boost_h2h) } (3/3)."))

    if v.get("explosivite_badge"):
        lines.append(_line_blank())
        lines.append(_color("Explosivité : saut important de niveaux (signaux très forts).", "ok"))

    if v.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H faible ⇒ verdict plafonné à MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# 4b) PARI : OVER 2.5 (FT)
# ----------------------------------------------------
def _match_over25_ft(m: Dict[str, Any]) -> bool:
    """
    True si total buts FT >= 3
    """
    ft_total = m.get("ft_total") or m.get("goals_total")
    if isinstance(ft_total, (int, float)):
        return float(ft_total) >= 3.0

    gf, ga = _ft_goals_for_against(m)
    if gf is not None and ga is not None:
        return (gf + ga) >= 3

    score = m.get("score") or m.get("full_time_score") or m.get("ft_score")
    if isinstance(score, str):
        s = score.replace(":", "-").strip()
        parts = s.split("-")
        if len(parts) == 2:
            a = _safe_int(parts[0])
            b = _safe_int(parts[1])
            return (a + b) >= 3

    return False


def _compute_over25_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_match_over25_ft(m) for m in matches])


def _over25_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges récents (Over 2.5) :
    - malus si 0/4 ou 1/4 en over2.5
    - regular_badge si >=3/4
    - explosive_badge si un match à 5+ buts
    """
    n = len(matches_recent)
    pct = _compute_over25_pct(matches_recent)
    count_ok = sum(1 for m in matches_recent if _match_over25_ft(m))

    malus = 0
    if n >= 4 and count_ok <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ok >= 3)

    max_ft = 0
    for m in matches_recent:
        gf, ga = _ft_goals_for_against(m)
        if gf is not None and ga is not None:
            max_ft = max(max_ft, gf + ga)
        else:
            ft_total = m.get("ft_total") or m.get("goals_total")
            if isinstance(ft_total, (int, float)):
                max_ft = max(max_ft, int(ft_total))

    explosive = (max_ft >= 5)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)
    if explosive:
        boost = max(boost, 2)

    return {
        "n": n,
        "pct": pct,
        "count_ok": count_ok,
        "malus": malus,
        "regular_badge": regular_badge,
        "explosive_badge": explosive,
        "boost": boost,
        "max_ft": max_ft,
    }


def _h2h_over25_pct(h2h: List[Dict[str, Any]]) -> Tuple[float, int, int]:
    """
    Over 2.5 sur H2H : goals_home + goals_away >= 3
    """
    if not h2h:
        return 0.0, 0, 0
    ok = 0
    n = 0
    for m in h2h:
        gh = m.get("goals_home")
        ga = m.get("goals_away")
        if not isinstance(gh, (int, float)) or not isinstance(ga, (int, float)):
            continue
        n += 1
        if (int(gh) + int(ga)) >= 3:
            ok += 1
    pct = (100.0 * ok / n) if n > 0 else 0.0
    return pct, ok, n


def _final_verdict_over25(team1_last: List[Dict[str, Any]], team2_last: List[Dict[str, Any]], h2h: List[Dict[str, Any]]) -> Dict[str, Any]:
    a8 = (team1_last or [])[:8]
    b8 = (team2_last or [])[:8]

    pct_a8 = _compute_over25_pct(a8)
    pct_b8 = _compute_over25_pct(b8)

    base_level, base_info = _base_level_ft_over25(pct_a8, pct_b8)
    idx_base = _level_index(base_level)
    idx = idx_base

    a4 = (team1_last or [])[:4]
    b4 = (team2_last or [])[:4]
    recent_a = _over25_badges_recent(a4)
    recent_b = _over25_badges_recent(b4)

    h2h_mapped = _map_h2h(h2h, focus_team="")
    h2h3 = _select_h2h_recent(h2h_mapped, 3)
    h2h_pct, h2h_ok, h2h_n = _h2h_over25_pct(h2h3)

    boost_h2h = 0
    malus_h2h = 0
    if h2h_n >= 3:
        if h2h_ok <= 1:
            malus_h2h = -1
        elif h2h_ok == 3:
            boost_h2h = 1

    malus_recent = -1 if (int(recent_a.get("malus") or 0) < 0 or int(recent_b.get("malus") or 0) < 0) else 0

    idx_after_malus = idx + malus_recent + malus_h2h
    idx = idx_after_malus

    boost_a = int(recent_a.get("boost") or 0)
    boost_b = int(recent_b.get("boost") or 0)

    boosts = sorted([boost_a, boost_b, boost_h2h], reverse=True)
    kept1 = boosts[0] if boosts else 0
    kept2 = boosts[1] if len(boosts) >= 2 else 0
    total_boost = int(_clamp(float(kept1 + kept2), 0.0, 4.0))

    idx_before_boost = idx
    idx += total_boost
    idx_after_boost = idx

    explosivite_badge = (idx_after_boost - idx_before_boost) >= 2

    final_level = _level_name(idx)
    final_idx = _level_index(final_level)
    final_idx, h2h_cap_applied = _cap_h2h_if_weak(final_idx, h2h_n, h2h_ok)
    final_level = _level_name(final_idx)

    keep = _is_exportable(final_level)

    return {
        "bet": "FT_OVER_2_5",
        "keep": keep,
        "base_level": base_level,
        "final_level": final_level,
        "explosivite_badge": explosivite_badge,
        "pct_a8": pct_a8,
        "pct_b8": pct_b8,
        "recent_a": recent_a,
        "recent_b": recent_b,
        "h2h_pct": h2h_pct,
        "h2h_ok": h2h_ok,
        "h2h_n": h2h_n,
        "base_info": base_info,
        "boost_a": boost_a,
        "boost_b": boost_b,
        "boost_h2h": boost_h2h,
        "kept_boost_1": kept1,
        "kept_boost_2": kept2,
        "total_boost": total_boost,
        "malus_recent": malus_recent,
        "malus_h2h": malus_h2h,
        "idx_base": idx_base,
        "idx_after_malus": idx_after_malus,
        "idx_after_boost": idx_after_boost,
        "h2h_cap_applied": h2h_cap_applied,
    }


def _build_human_explain_over25(team1: str, team2: str, v: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(v.get("base_level") or "")
    final = str(v.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team1} finit en Over 2.5 dans { _format_pct(float(v.get('pct_a8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {team2} finit en Over 2.5 dans { _format_pct(float(v.get('pct_b8') or 0.0)) } des matchs."))

    ra = v.get("recent_a") or {}
    rb = v.get("recent_b") or {}

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team1} est à { _format_pct(float(ra.get('pct') or 0.0)) } (match le plus riche : {ra.get('max_ft', 0)} buts)."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team2} est à { _format_pct(float(rb.get('pct') or 0.0)) } (match le plus riche : {rb.get('max_ft', 0)} buts)."))

    h2h_n = int(v.get("h2h_n") or 0)
    if h2h_n >= 3:
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, Over 2.5 dans { _format_pct(float(v.get('h2h_pct') or 0.0)) } des matchs ({int(v.get('h2h_ok') or 0)}/3)."))

    boost_a = int(v.get("boost_a") or 0)
    boost_b = int(v.get("boost_b") or 0)
    boost_h2h = int(v.get("boost_h2h") or 0)

    kept1 = int(v.get("kept_boost_1") or 0)
    kept2 = int(v.get("kept_boost_2") or 0)
    total_boost = int(v.get("total_boost") or 0)

    malus_recent = int(v.get("malus_recent") or 0)
    malus_h2h = int(v.get("malus_h2h") or 0)

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))
    lines.append(_bullet(f"Boosts détectés : {team1}={_color_delta(boost_a)}  |  {team2}={_color_delta(boost_b)}  |  H2H={_color_delta(boost_h2h)}."))

    if total_boost > 0:
        lines.append(_bullet(f"Boost total appliqué : { _color_delta(total_boost) } (on garde les 2 meilleurs : {kept1} et {kept2})."))
    else:
        lines.append(_bullet("Aucun boost notable sur les signaux forts."))

    if malus_recent != 0:
        lines.append(_bullet(f"Malus récents : { _color_delta(malus_recent) } (une équipe a fait 0/4 ou 1/4)."))

    if h2h_n >= 3:
        lines.append(_bullet(f"H2H (3 derniers) : { _format_pct(float(v.get('h2h_pct') or 0.0)) } = {int(v.get('h2h_ok') or 0)}/3 en Over 2.5."))

    if malus_h2h != 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(malus_h2h) } (0/3 ou 1/3)."))

    if boost_h2h > 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(boost_h2h) } (3/3)."))

    if v.get("explosivite_badge"):
        lines.append(_line_blank())
        lines.append(_color("Explosivité : saut important de niveaux (signaux très forts).", "ok"))

    if v.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H faible ⇒ verdict plafonné à MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# UNDER 3.5 FT — Moins de 3.5 buts (total FT ≤ 3)
# ----------------------------------------------------

def _match_under35_ft(m: Dict[str, Any]) -> bool:
    """True si total buts FT <= 3"""
    ft_total = m.get("ft_total") or m.get("goals_total")
    if isinstance(ft_total, (int, float)):
        return float(ft_total) <= 3.0

    gf, ga = _ft_goals_for_against(m)
    if gf is not None and ga is not None:
        return (gf + ga) <= 3

    score = m.get("score") or m.get("full_time_score") or m.get("ft_score")
    if isinstance(score, str):
        s = score.replace(":", "-").strip()
        parts = s.split("-")
        if len(parts) == 2:
            a = _safe_int(parts[0])
            b = _safe_int(parts[1])
            return (a + b) <= 3

    return False


def _compute_under35_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_match_under35_ft(m) for m in matches])


def _under35_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges récents (Under 3.5) :
    - malus si 0/4 ou 1/4 en under3.5 (équipe très offensive récemment)
    - regular_badge si >=3/4 en under3.5
    - defensive_badge si au moins un match avait <= 1 but au total
    """
    n = len(matches_recent)
    pct = _compute_under35_pct(matches_recent)
    count_ok = sum(1 for m in matches_recent if _match_under35_ft(m))

    malus = 0
    if n >= 4 and count_ok <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ok >= 3)

    min_ft = 99
    for m in matches_recent:
        gf, ga = _ft_goals_for_against(m)
        if gf is not None and ga is not None:
            min_ft = min(min_ft, gf + ga)
        else:
            ft_total = m.get("ft_total") or m.get("goals_total")
            if isinstance(ft_total, (int, float)):
                min_ft = min(min_ft, int(ft_total))

    if min_ft == 99:
        min_ft = 0
    defensive_badge = (min_ft <= 1)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)
    if defensive_badge:
        boost = max(boost, 1)

    return {
        "n": n,
        "pct": pct,
        "count_ok": count_ok,
        "malus": malus,
        "regular_badge": regular_badge,
        "defensive_badge": defensive_badge,
        "boost": boost,
        "min_ft": min_ft,
    }


def _h2h_under35_pct(h2h: List[Dict[str, Any]]) -> Tuple[float, int, int]:
    """Under 3.5 sur H2H : goals_home + goals_away <= 3"""
    if not h2h:
        return 0.0, 0, 0
    ok = 0
    n = 0
    for m in h2h:
        gh = m.get("goals_home")
        ga_h = m.get("goals_away")
        if not isinstance(gh, (int, float)) or not isinstance(ga_h, (int, float)):
            continue
        n += 1
        if (int(gh) + int(ga_h)) <= 3:
            ok += 1
    pct = (100.0 * ok / n) if n > 0 else 0.0
    return pct, ok, n


def _base_level_ft_under35(pct_a: float, pct_b: float) -> Tuple[str, Dict[str, Any]]:
    """
    Base Under 3.5 (FT) — seuils calqués sur O15_FT (taux de base similaire ~75%).
    pct_a / pct_b = % des matchs avec <= 3 buts totaux.
    """
    lo = min(pct_a, pct_b)
    hi = max(pct_a, pct_b)
    info = {"lo": lo, "hi": hi}

    if lo < 50.0 and hi < 50.0:
        return "KO", info
    if lo < 50.0 and hi < 62.5:
        return "KO", info

    if lo >= 50.0 and hi < 62.5:
        return "FAIBLE", info
    if lo >= 50.0 and hi >= 62.5 and hi < 75.0:
        return "MOYEN", info
    if lo >= 62.5 and hi < 75.0:
        return "MOYEN PLUS", info
    if lo >= 62.5 and hi >= 75.0 and hi < 87.5:
        return "FORT", info
    if lo >= 75.0 and hi < 87.5:
        return "FORT PLUS", info
    if lo >= 75.0 and hi >= 87.5:
        if (lo == 100.0 and hi >= 87.5) or (hi == 100.0 and lo >= 87.5):
            return "MEGA EXPLOSION", info
        if lo >= 87.5 and hi >= 87.5:
            return "EXPLOSION", info
        return "TRÈS FORT", info

    return "MOYEN", info


def _final_verdict_under35(
    team1_last: List[Dict[str, Any]],
    team2_last: List[Dict[str, Any]],
    h2h: List[Dict[str, Any]],
) -> Dict[str, Any]:
    a8 = (team1_last or [])[:8]
    b8 = (team2_last or [])[:8]

    pct_a8 = _compute_under35_pct(a8)
    pct_b8 = _compute_under35_pct(b8)

    base_level, base_info = _base_level_ft_under35(pct_a8, pct_b8)
    idx_base = _level_index(base_level)
    idx = idx_base

    a4 = (team1_last or [])[:4]
    b4 = (team2_last or [])[:4]
    recent_a = _under35_badges_recent(a4)
    recent_b = _under35_badges_recent(b4)

    h2h_mapped = _map_h2h(h2h, focus_team="")
    h2h3 = _select_h2h_recent(h2h_mapped, 3)
    h2h_pct, h2h_ok, h2h_n = _h2h_under35_pct(h2h3)

    boost_h2h = 0
    malus_h2h = 0
    if h2h_n >= 3:
        if h2h_ok <= 1:
            malus_h2h = -1
        elif h2h_ok == 3:
            boost_h2h = 1

    malus_recent = -1 if (int(recent_a.get("malus") or 0) < 0 or int(recent_b.get("malus") or 0) < 0) else 0

    idx_after_malus = idx + malus_recent + malus_h2h
    idx = idx_after_malus

    boost_a = int(recent_a.get("boost") or 0)
    boost_b = int(recent_b.get("boost") or 0)

    boosts = sorted([boost_a, boost_b, boost_h2h], reverse=True)
    kept1 = boosts[0] if boosts else 0
    kept2 = boosts[1] if len(boosts) >= 2 else 0
    total_boost = int(_clamp(float(kept1 + kept2), 0.0, 4.0))

    idx += total_boost
    idx_after_boost = idx

    final_level = _level_name(idx)
    final_idx = _level_index(final_level)
    final_idx, h2h_cap_applied = _cap_h2h_if_weak(final_idx, h2h_n, h2h_ok)
    final_level = _level_name(final_idx)

    keep = _is_exportable(final_level)

    return {
        "bet": "FT_UNDER_3_5",
        "keep": keep,
        "base_level": base_level,
        "final_level": final_level,
        "pct_a8": pct_a8,
        "pct_b8": pct_b8,
        "recent_a": recent_a,
        "recent_b": recent_b,
        "h2h_pct": h2h_pct,
        "h2h_ok": h2h_ok,
        "h2h_n": h2h_n,
        "base_info": base_info,
        "boost_a": boost_a,
        "boost_b": boost_b,
        "boost_h2h": boost_h2h,
        "kept_boost_1": kept1,
        "kept_boost_2": kept2,
        "total_boost": total_boost,
        "malus_recent": malus_recent,
        "malus_h2h": malus_h2h,
        "idx_base": idx_base,
        "idx_after_malus": idx_after_malus,
        "idx_after_boost": idx_after_boost,
        "h2h_cap_applied": h2h_cap_applied,
    }


def _build_human_explain_under35(team1: str, team2: str, v: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(v.get("base_level") or "")
    final = str(v.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team1} finit en Under 3.5 dans { _format_pct(float(v.get('pct_a8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {team2} finit en Under 3.5 dans { _format_pct(float(v.get('pct_b8') or 0.0)) } des matchs."))

    ra = v.get("recent_a") or {}
    rb = v.get("recent_b") or {}

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team1} est à { _format_pct(float(ra.get('pct') or 0.0)) } (match le plus défensif : {ra.get('min_ft', 0)} buts)."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team2} est à { _format_pct(float(rb.get('pct') or 0.0)) } (match le plus défensif : {rb.get('min_ft', 0)} buts)."))

    h2h_n = int(v.get("h2h_n") or 0)
    if h2h_n >= 3:
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, Under 3.5 dans { _format_pct(float(v.get('h2h_pct') or 0.0)) } des matchs ({int(v.get('h2h_ok') or 0)}/3)."))

    boost_a = int(v.get("boost_a") or 0)
    boost_b = int(v.get("boost_b") or 0)
    boost_h2h = int(v.get("boost_h2h") or 0)
    kept1 = int(v.get("kept_boost_1") or 0)
    kept2 = int(v.get("kept_boost_2") or 0)
    total_boost = int(v.get("total_boost") or 0)
    malus_recent = int(v.get("malus_recent") or 0)
    malus_h2h = int(v.get("malus_h2h") or 0)

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))
    lines.append(_bullet(f"Boosts détectés : {team1}={_color_delta(boost_a)}  |  {team2}={_color_delta(boost_b)}  |  H2H={_color_delta(boost_h2h)}."))

    if total_boost > 0:
        lines.append(_bullet(f"Boost total appliqué : { _color_delta(total_boost) } (on garde les 2 meilleurs : {kept1} et {kept2})."))
    else:
        lines.append(_bullet("Aucun boost notable sur les signaux défensifs."))

    if malus_recent != 0:
        lines.append(_bullet(f"Malus récents : { _color_delta(malus_recent) } (une équipe a fait 0/4 ou 1/4 en Under 3.5)."))

    if h2h_n >= 3 and malus_h2h != 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(malus_h2h) } (0/3 ou 1/3 en Under 3.5)."))

    if h2h_n >= 3 and boost_h2h > 0:
        lines.append(_bullet(f"Signal H2H : { _color_delta(boost_h2h) } (3/3 en Under 3.5)."))

    if v.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H faible ⇒ verdict plafonné à MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# 5) PARI : TEAM WIN (TEAM1 gagne / TEAM2 gagne)
# ----------------------------------------------------
def _compute_team_win_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_team_won_ft(m) for m in matches])


def _compute_team_loss_pct(matches: List[Dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    return 100.0 * _count_ratio([_team_lost_ft(m) for m in matches])


def _h2h_team_win_pct(h2h: List[Dict[str, Any]], focus_team: str) -> Tuple[float, int, int]:
    """
    Sur H2H : focus gagne si ses buts > buts adverses (en respectant home/away).
    On s’appuie sur goals_home/goals_away + mapping focus.
    """
    if not h2h:
        return 0.0, 0, 0

    ok = 0
    n = 0
    f = _norm_team(focus_team)

    for m in h2h:
        home_name, away_name = _extract_team_names_from_h2h(m)
        h = _norm_team(home_name)
        a = _norm_team(away_name)

        gh = m.get("goals_home")
        ga = m.get("goals_away")
        if not isinstance(gh, (int, float)) or not isinstance(ga, (int, float)):
            continue

        gh_i = int(gh)
        ga_i = int(ga)

        is_focus_home = (f and h and (f == h or f in h or h in f))
        is_focus_away = (f and a and (f == a or f in a or a in f))
        if not (is_focus_home or is_focus_away):
            continue

        n += 1
        if is_focus_home and gh_i > ga_i:
            ok += 1
        elif is_focus_away and ga_i > gh_i:
            ok += 1

    pct = (100.0 * ok / n) if n > 0 else 0.0
    return pct, ok, n

def _team_win_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges récents (FT win) :
    - malus si 0/4 ou 1/4 en victoire
    - regular_badge si >=3/4
    - explosive_badge si une victoire avec marge >=3
    - boost = max(regular, regular&100%, explosive)
    """
    n = len(matches_recent)
    pct = _compute_team_win_pct(matches_recent)
    count_ok = sum(1 for m in matches_recent if _team_won_ft(m))

    malus = 0
    if n >= 4 and count_ok <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ok >= 3)

    max_margin = 0
    for m in matches_recent:
        gf, ga = _ft_goals_for_against(m)
        if gf is not None and ga is not None:
            if gf > ga:
                max_margin = max(max_margin, gf - ga)

    explosive = (max_margin >= 3)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)
    if explosive:
        boost = max(boost, 2)

    return {
        "n": n,
        "pct": pct,
        "count_ok": count_ok,
        "malus": malus,
        "regular_badge": regular_badge,
        "explosive_badge": explosive,
        "boost": boost,
        "max_margin": max_margin,
    }


def _opp_loss_badges_recent(matches_recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Badges récents (adversaire perd) :
    - malus si opp perd 0/4 ou 1/4
    - regular_badge si opp perd >=3/4
    - boost analogue
    """
    n = len(matches_recent)
    pct = _compute_team_loss_pct(matches_recent)
    count_ok = sum(1 for m in matches_recent if _team_lost_ft(m))

    malus = 0
    if n >= 4 and count_ok <= 1:
        malus = -1

    regular_badge = (n >= 4 and count_ok >= 3)

    boost = 0
    if regular_badge:
        boost = max(boost, 1)
    if regular_badge and pct >= 100.0:
        boost = max(boost, 2)

    return {
        "n": n,
        "pct": pct,
        "count_ok": count_ok,
        "malus": malus,
        "regular_badge": regular_badge,
        "boost": boost,
    }


def _final_verdict_team_win(
    team_name: str,
    team_last: List[Dict[str, Any]],
    opp_name: str,
    opp_last: List[Dict[str, Any]],
    h2h: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    TEAM WIN (focus team gagne FT) — version cohérente avec les badges/explain.
    - Base (8) = moyenne( team gagne %, opp perd % ) => base_level_from_pct_single
    - Malus récents (4) : -1 si team gagne <=1/4 ; -1 si opp perd <=1/4
    - Boosts : on garde 2 meilleurs boosts parmi (team recent, opp recent, h2h)
      (cap total_boost <= 4)
    - H2H (3 récents) : +1 si 3/3 ; -1 si 0/3 ou 1/3 ; CAP global si H2H faible
    """

    # 8 derniers
    t8 = (team_last or [])[:8]
    o8 = (opp_last or [])[:8]

    # 4 derniers
    t4 = (team_last or [])[:4]
    o4 = (opp_last or [])[:4]

    pct_team_win8 = _compute_team_win_pct(t8)
    pct_opp_loss8 = _compute_team_loss_pct(o8)

    base_avg8 = _average([pct_team_win8, pct_opp_loss8]) if (t8 or o8) else 0.0
    base_level = _base_level_from_pct_single(base_avg8)
    idx_base = _level_index(base_level)
    idx = idx_base

    # ----- RECENT badges (team wins / opp loses) -----
    recent_team = _team_win_badges_recent(t4)
    recent_opp = _opp_loss_badges_recent(o4)

    # Malus récents
    malus_recent = 0
    if int(recent_team.get("n") or 0) >= 4 and int(recent_team.get("count_ok") or 0) <= 1:
        malus_recent -= 1
    if int(recent_opp.get("n") or 0) >= 4 and int(recent_opp.get("count_ok") or 0) <= 1:
        malus_recent -= 1

    idx_after_malus = idx + malus_recent
    idx = idx_after_malus

    # ----- H2H (3 récents) -----
    # IMPORTANT : on garde les H2H raw (avec noms home/away) car _h2h_team_win_pct en a besoin.
    # On ajoute juste un _ts pour permettre le tri "récents".
    h2h_raw = (h2h or [])[:]
    h2h_raw_enriched: List[Dict[str, Any]] = []
    for m in h2h_raw:
        mm = dict(m)
        raw_ts = m.get("timestamp") or m.get("ts") or m.get("time") or m.get("date")
        mm["_ts"] = _parse_date_to_ts(raw_ts)
        h2h_raw_enriched.append(mm)

    h2h3 = _select_h2h_recent(h2h_raw_enriched, 3)

    h2h_pct, h2h_ok, h2h_n = _h2h_team_win_pct(h2h3, focus_team=team_name)

    boost_h2h = 0
    malus_h2h = 0
    if h2h_n >= 3:
        if h2h_ok <= 1:
            malus_h2h = -1
        elif h2h_ok == 3:
            boost_h2h = 1

    idx_after_malus2 = idx + malus_h2h
    idx = idx_after_malus2

    # ----- BOOSTS : on garde les 2 meilleurs (team, opp, h2h) -----
    boost_team = int(recent_team.get("boost") or 0)
    boost_opp = int(recent_opp.get("boost") or 0)

    boosts = sorted([boost_team, boost_opp, boost_h2h], reverse=True)
    kept1 = boosts[0] if boosts else 0
    kept2 = boosts[1] if len(boosts) >= 2 else 0
    total_boost = int(_clamp(float(kept1 + kept2), 0.0, 4.0))

    idx_before_boost = idx
    idx += total_boost
    idx_after_boost = idx

    explosivite_badge = (idx_after_boost - idx_before_boost) >= 2

    # Niveau brut
    final_level = _level_name(idx)

    # CAP global si H2H faible (0/3 ou 1/3)
    final_idx = _level_index(final_level)
    final_idx, h2h_cap_applied = _cap_h2h_if_weak(final_idx, h2h_n, h2h_ok)
    final_level = _level_name(final_idx)

    keep = _is_exportable(final_level)

    return {
        "bet": "TEAM_WIN",
        "keep": keep,

        "base_level": base_level,
        "final_level": final_level,

        # Base stats
        "pct_team_win8": pct_team_win8,
        "pct_opp_loss8": pct_opp_loss8,
        "base_avg8": base_avg8,

        # Recent stats
        "pct_team_win4": _compute_team_win_pct(t4),
        "pct_opp_loss4": _compute_team_loss_pct(o4),
        "malus_recent": malus_recent,

        # Badges packs (utilisés par l'explain)
        "recent_team": recent_team,
        "recent_opp": recent_opp,

        # H2H stats
        "h2h_pct": h2h_pct,
        "h2h_ok": h2h_ok,
        "h2h_n": h2h_n,

        "boost_h2h": boost_h2h,
        "malus_h2h": malus_h2h,

        # Boost summary (utilisé par l'explain)
        "boost_team": boost_team,
        "boost_opp": boost_opp,
        "kept_boost_1": kept1,
        "kept_boost_2": kept2,
        "total_boost": total_boost,

        # Indicateurs debug / cohérence
        "idx_base": idx_base,
        "idx_after_malus": idx_after_malus,
        "idx_after_malus2": idx_after_malus2,
        "idx_after_boost": idx_after_boost,
        "explosivite_badge": explosivite_badge,
        "h2h_cap_applied": h2h_cap_applied,
    }


def _build_human_explain_team_win(team: str, opp: str, v: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(v.get("base_level") or "")
    final = str(v.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team} gagne dans { _format_pct(float(v.get('pct_team_win8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {opp} perd dans { _format_pct(float(v.get('pct_opp_loss8') or 0.0)) } des matchs."))

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team} gagne dans { _format_pct(float(v.get('pct_team_win4') or 0.0)) } des matchs."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {opp} perd dans { _format_pct(float(v.get('pct_opp_loss4') or 0.0)) } des matchs."))

    h2h_n = int(v.get("h2h_n") or 0)
    if h2h_n >= 3:
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, {team} gagne dans { _format_pct(float(v.get('h2h_pct') or 0.0)) } des matchs ({int(v.get('h2h_ok') or 0)}/3)."))

    # ✅ AJOUT : bloc badges complet (même style que HT05)
    boost_team = int(v.get("boost_team") or v.get("boost_a") or 0)
    boost_opp  = int(v.get("boost_opp")  or v.get("boost_b") or 0)
    boost_h2h  = int(v.get("boost_h2h")  or 0)
    
    kept1 = int(v.get("kept_boost_1") or 0)
    kept2 = int(v.get("kept_boost_2") or 0)
    total_boost = int(v.get("total_boost") or 0)

    malus_recent = int(v.get("malus_recent") or 0)
    malus_h2h = int(v.get("malus_h2h") or 0)

    recent_team = v.get("recent_team") or {}
    recent_opp = v.get("recent_opp") or {}

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))

    lines.append(_bullet(f"Boosts détectés : {team}={_color_delta(boost_team)}  |  {opp}(perd)={_color_delta(boost_opp)}  |  H2H={_color_delta(boost_h2h)}."))
    if total_boost > 0:
        lines.append(_bullet(f"Boost total appliqué : { _color_delta(total_boost) } (on garde les 2 meilleurs : {kept1} et {kept2})."))
    else:
        lines.append(_bullet("Aucun boost notable sur les signaux forts."))

    if int(recent_team.get("n") or 0) >= 4:
        lines.append(_bullet(f"Forme {team} (4) : { _format_pct(float(recent_team.get('pct') or 0.0)) } | marge max victoire : {int(recent_team.get('max_margin') or 0)}."))
    if int(recent_opp.get("n") or 0) >= 4:
        lines.append(_bullet(f"Forme {opp} (4) : { _format_pct(float(recent_opp.get('pct') or 0.0)) } de défaites."))

    if malus_recent != 0:
        lines.append(_bullet(f"Malus récents : { _color_delta(malus_recent) } (une des 2 courbes a fait 0/4 ou 1/4)."))
    if h2h_n >= 3 and malus_h2h != 0:
        lines.append(_bullet(f"Verrou H2H : { _color_delta(malus_h2h) } (seulement 0/3 ou 1/3)."))
    if boost_h2h > 0:
        lines.append(_bullet(f"Bonus H2H : { _color_delta(boost_h2h) } (3/3)."))

    if v.get("explosivite_badge"):
        lines.append(_line_blank())
        lines.append(_color("Explosivité : saut important de niveaux (signaux très forts).", "ok"))

    if v.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H trop faible (0/3 ou 1/3) ⇒ le verdict ne peut pas dépasser MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# Helpers "rapport humain" (aéré + phrases)
# ----------------------------------------------------
def _build_human_explain_ht05(team1: str, team2: str, ht05: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(ht05.get("base_level") or "")
    final = str(ht05.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs - {team1} : au moins 1 but en 1ère mi-temps dans { _format_pct(float(ht05.get('pct_a8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs - {team2} : au moins 1 but en 1ère mi-temps dans { _format_pct(float(ht05.get('pct_b8') or 0.0)) } des matchs."))

    ra = ht05.get("recent_a") or {}
    rb = ht05.get("recent_b") or {}

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team1} est à { _format_pct(float(ra.get('pct') or 0.0)) } (HT la plus riche : {ra.get('max_ht', 0)} buts)."))
    lines.append(_bullet(f"Sur les 4 derniers matchs, {team2} est à { _format_pct(float(rb.get('pct') or 0.0)) } (HT la plus riche : {rb.get('max_ht', 0)} buts)."))

    h = ht05.get("h2h") or {}
    h_n = int(h.get("n") or 0)
    h_count = int(h.get("count") or 0)

    boost_a = int(ht05.get("boost_a") or 0)
    boost_b = int(ht05.get("boost_b") or 0)
    boost_h2h = int(ht05.get("boost_h2h") or 0)

    kept1 = int(ht05.get("kept_boost_1") or 0)
    kept2 = int(ht05.get("kept_boost_2") or 0)
    total_boost = int(ht05.get("total_boost") or 0)

    malus_recent = int(ht05.get("malus_recent") or 0)
    malus_h2h = int(ht05.get("malus_h2h") or 0)

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))

    lines.append(_bullet(f"Boosts détectés : {team1}={_color_delta(boost_a)}  |  {team2}={_color_delta(boost_b)}  |  H2H={_color_delta(boost_h2h)}."))
    if total_boost > 0:
        lines.append(_bullet(f"Boost total appliqué : { _color_delta(total_boost) } (on garde les 2 meilleurs : {kept1} et {kept2})."))
    else:
        lines.append(_bullet("Aucun boost notable sur les signaux forts."))

    if malus_recent != 0:
        lines.append(_bullet(f"Malus récents : { _color_delta(malus_recent) } (une équipe a fait 0/4 ou 1/4)."))
    if h_n >= 3:
        lines.append(_bullet(f"H2H (3 derniers) : { _format_pct(float(h.get('pct') or 0.0)) } = {h_count}/3 matchs avec au moins 1 but en 1ère mi-temps."))
    if malus_h2h != 0:
        lines.append(_bullet(f"Verrou H2H : { _color_delta(malus_h2h) } (seulement 0/3 ou 1/3)."))
    if boost_h2h > 0:
        lines.append(_bullet(f"Bonus H2H : { _color_delta(boost_h2h) } (3/3)."))

    if ht05.get("explosivite_badge"):
        lines.append(_line_blank())
        lines.append(_color("Explosivité : saut important de niveaux (signaux très forts).", "ok"))

    if ht05.get("h2h_cap_applied"):
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.append(_bullet("CAP appliqué : H2H trop faible (0/3 ou 1/3) ⇒ le verdict ne peut pas dépasser MOYEN PLUS."))

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


def _build_human_explain_dcht(team1: str, team2: str, dcht: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    base = str(dcht.get("base_level") or "")
    final = str(dcht.get("final_level") or "")

    lines.append(_bold(f"Au départ, ce pari est classé { _verdict_color_name(base) }, car :"))
    lines.append(_bullet(f"8 derniers matchs à domicile - {team1} ne perd pas à la mi-temps : { _format_pct(float(dcht.get('pct_home8') or 0.0)) } des matchs."))
    lines.append(_bullet(f"8 derniers matchs (domicile + extérieur) - {team2} ne mène pas à la mi-temps : { _format_pct(float(dcht.get('pct_away_not_lead8') or 0.0)) } des matchs."))

    lines.append(_line_blank())
    lines.append(_bold("La forme récente influence le verdict :"))
    lines.append(_bullet(f"Sur les 4 derniers matchs à domicile, {team1} ne perd pas à la mi-temps dans { _format_pct(float(dcht.get('pct_home4') or 0.0)) } des matchs."))
    lines.append(_bullet(f"Sur les 4 derniers matchs (domicile + extérieur), {team2} ne mène pas à la mi-temps dans { _format_pct(float(dcht.get('pct_away_not_lead4') or 0.0)) } des matchs."))

    adv = dcht.get("adv") or {}
    adv_bonus = int(dcht.get("adv_bonus") or 0)
    adv_malus = int(dcht.get("adv_malus") or 0)
    recent_delta = int(dcht.get("recent_delta") or 0)

    lines.append(_line_blank())
    lines.append(_bold("Les badges (bonus / malus) :"))
    if recent_delta != 0:
        parts: List[str] = []
        if int(dcht.get("recent_delta_home") or 0) < 0:
            parts.append("HOME faible (0/4 ou 1/4)")
        if int(dcht.get("recent_delta_away") or 0) < 0:
            parts.append("AWAY mène trop souvent (3/4 ou 4/4)")
        reason = " + ".join(parts) if parts else "forme récente"
        lines.append(_bullet(f"Malus récents : { _color_delta(recent_delta) } ({reason})."))
    else:
        lines.append(_bullet("Pas de malus récent notable."))

    if int(adv.get("n") or 0) > 0:
        lines.append(_bullet(f"Profil adversaire (8) : {team2} mène à la mi-temps dans { _format_pct(float(adv.get('bad') or 0.0)) } des matchs."))
        if adv_bonus != 0:
            lines.append(_bullet(f"Bonus adversaire : { _color_delta(adv_bonus) } (l’adversaire mène rarement à HT)."))
        if adv_malus != 0:
            lines.append(_bullet(f"Malus adversaire : { _color_delta(adv_malus) } (l’adversaire mène souvent à HT)."))
        if adv_bonus == 0 and adv_malus == 0:
            lines.append(_bullet("Adversaire neutre : pas de bonus/malus marqué."))

    h2h_n = int(dcht.get("h2h_n") or 0)
    if h2h_n >= 3:
        pct_h2h = float(dcht.get("pct_h2h3") or 0.0)
        count_h2h = int(dcht.get("count_h2h3") or 0)
        lines.append(_line_blank())
        lines.append(_bold("Confrontations directes (H2H) :"))
        lines.append(_bullet(f"Sur les 3 derniers H2H, {team1} ne perd pas à HT dans { _format_pct(pct_h2h) } des matchs ({count_h2h}/3)."))
        if dcht.get("h2h_floor_applied"):
            lines.append(_bullet(_color("Plancher appliqué : si ≥ 2/3, le verdict ne descend pas sous MOYEN PLUS.", "warn")))

    attention_lines: List[str] = []
    if dcht.get("h2h_cap_applied"):
        attention_lines.append(_bullet("CAP appliqué : H2H trop faible (0/3 ou 1/3) ⇒ le verdict ne peut pas dépasser MOYEN PLUS."))
    if recent_delta < 0:
        attention_lines.append(_bullet("Alerte : forme récente défavorable (au moins un signal rouge sur les 4 derniers)."))
    if adv_malus < 0:
        attention_lines.append(_bullet("Alerte : adversaire dangereux (il mène souvent à HT)."))

    if attention_lines:
        lines.append(_line_blank())
        lines.append(_color(_bold("Mais attention :"), "warn"))
        lines.extend(attention_lines)

    lines.append(_line_blank())
    lines.append(_bold(f"Verdict final : { _verdict_color_name(final) }."))
    return lines


# ----------------------------------------------------
# Odds helpers
# ----------------------------------------------------

def _pick_market_odd(bet_key: str, market_odds: Dict[str, Any]) -> Optional[float]:
    """
    Retourne la cote du marché selon bet_key.
    Accepte les clés CANONIQUES + aliases (pour compat).
    """
    k = (bet_key or "").strip().upper()
    val = None

    if k in ("HT05", "HT_OVER_0_5", "HT_OVER05", "HT_O05"):
        val = market_odds.get("ht_over05_odds")

    elif k in ("HT1X_HOME", "HT1X", "HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        val = market_odds.get("ht_1x_odds")

    elif k in ("TEAM1_SCORE_FT", "TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE"):
        val = market_odds.get("team1_score_odds")
    elif k in ("TEAM2_SCORE_FT", "TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE"):
        val = market_odds.get("team2_score_odds")

    elif k in ("O15_FT", "O15", "FT_O15", "OVER15", "OVER_1_5", "FT_OVER15", "FT_OVER_1_5"):
        val = (
            market_odds.get("ft_over15_odds")
            or market_odds.get("over15_odds")
            or market_odds.get("over_1_5_odds")
            or market_odds.get("o15_odds")
        )

    elif k in ("O25_FT", "O25", "FT_O25", "OVER25", "OVER_2_5", "FT_OVER25", "FT_OVER_2_5"):
        val = (
            market_odds.get("ft_over25_odds")
            or market_odds.get("over25_odds")
            or market_odds.get("over_2_5_odds")
            or market_odds.get("o25_odds")
        )

    elif k in ("U35_FT", "U35", "FT_U35", "UNDER35", "UNDER_3_5", "FT_UNDER35", "FT_UNDER_3_5"):
        val = (
            market_odds.get("ft_under35_odds")
            or market_odds.get("under35_odds")
            or market_odds.get("under_3_5_odds")
            or market_odds.get("u35_odds")
        )

    elif k in ("TEAM1_WIN_FT", "TEAM1_WIN", "HOME_WIN", "T1_WIN"):
        val = market_odds.get("home_win_odds") or market_odds.get("team1_win_odds")
    elif k in ("TEAM2_WIN_FT", "TEAM2_WIN", "AWAY_WIN", "T2_WIN"):
        val = market_odds.get("away_win_odds") or market_odds.get("team2_win_odds")

    if val is None:
        return None

    try:
        return float(val)
    except Exception:
        return None
    

def _build_comment_with_odds(fixture_id: Any, odd: Optional[float]) -> str:
    """
    Format final (1 seule colonne comment) :
      "odd=1.85 fixture=123456"
    """
    parts: List[str] = []

    if odd is not None:
        odd_str = f"{odd:.2f}".rstrip("0").rstrip(".")
        parts.append(f"odd={odd_str}")

    if fixture_id is not None and str(fixture_id).strip() != "":
        parts.append(f"fixture={fixture_id}")

    return " ".join(parts).strip()


# ----------------------------------------------------
# Fonction principale : run_full_analysis
# ----------------------------------------------------

def run_full_analysis(team1: str, team2: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    data attendu (compat) :
    {
        "team1_last": [...],
        "team2_last": [...],
        "h2h": [...],
        "context": {"home_standing": {...}, "away_standing": {...}, "market_odds": {...}},
        "date": "...",
        "league": "...",
        "fixture_id": ...
    }

    - team1 = équipe DOMICILE (dans ton pipeline actuel)
    - team2 = équipe EXTÉRIEUR
    """
    team1_last = data.get("team1_last") or data.get("team1") or []
    team2_last = data.get("team2_last") or data.get("team2") or []
    h2h = data.get("h2h", []) or []

    ht05 = _final_verdict_ht05(team1_last, team2_last, h2h)
    dcht = _final_verdict_dcht(team1, team1_last, team2, team2_last, h2h)

    t1_score = _final_verdict_team_to_score(team1, team1_last, team2, team2_last, h2h)
    t2_score = _final_verdict_team_to_score(team2, team2_last, team1, team1_last, h2h)

    # Team win (toujours analysé)
    t1_win = _final_verdict_team_win(team1, team1_last, team2, team2_last, h2h)
    t2_win = _final_verdict_team_win(team2, team2_last, team1, team1_last, h2h)

    # Over 1.5 (FT) (toujours analysé)
    over15 = _final_verdict_over15(team1_last, team2_last, h2h)

    # Over 2.5 (FT) (toujours analysé)
    over25 = _final_verdict_over25(team1_last, team2_last, h2h)

    # Under 3.5 (FT) (toujours analysé)
    under35 = _final_verdict_under35(team1_last, team2_last, h2h)

    rapport_lines: List[str] = []
    rapport_lines.append(f"{ANSI_BOLD}MATCH{ANSI_RESET} : {team1} – {team2} ⚽️")
    rapport_lines.append(_line_blank())

    context = data.get("context") or {}
    home_standing = (context.get("home_standing") or {})
    away_standing = (context.get("away_standing") or {})
    hr = home_standing.get("rank")
    ar = away_standing.get("rank")
    if hr is not None or ar is not None:
        rapport_lines.append(
            f"Classement : {team1} ({hr if hr is not None else '—'}) reçoit {team2} ({ar if ar is not None else '—'})"
        )
        rapport_lines.append(_line_blank())

    # ---- PARI 1 ----
    rapport_lines.append(_section_title("PARI 1 — +0.5 BUT À LA MI-TEMPS"))
    rapport_lines.extend(_build_human_explain_ht05(team1, team2, ht05))
    rapport_lines.append(_line_blank())

    rapport_lines.append("...")
    rapport_lines.append(_line_blank())

    # ---- PARI 2 ----
    rapport_lines.append(_section_title("PARI 2 — CHANCE DOUBLE MI-TEMPS (DOMICILE)"))
    rapport_lines.extend(_build_human_explain_dcht(team1, team2, dcht))
    rapport_lines.append(_line_blank())

    rapport_lines.append("...")
    rapport_lines.append(_line_blank())

    # ---- PARI 3 ----
    rapport_lines.append(_section_title("PARI 3 — TEAM TO SCORE (TEAM1 / TEAM2)"))
    rapport_lines.append(_bold(f"{team1} — MARQUE (FT)"))
    rapport_lines.extend(_build_human_explain_team_to_score(team1, team2, t1_score))
    rapport_lines.append(_line_blank())
    rapport_lines.append(_bold(f"{team2} — MARQUE (FT)"))
    rapport_lines.extend(_build_human_explain_team_to_score(team2, team1, t2_score))
    rapport_lines.append(_line_blank())

    # ---- PARI 4 ----
    rapport_lines.append("...")
    rapport_lines.append(_line_blank())
    rapport_lines.append(_section_title("PARI 4 — OVER 1.5 BUTS (FT)"))
    rapport_lines.extend(_build_human_explain_over15(team1, team2, over15))
    rapport_lines.append(_line_blank())

    # ---- PARI 6 ----
    rapport_lines.append("...")
    rapport_lines.append(_line_blank())
    rapport_lines.append(_section_title("PARI 6 — OVER 2.5 BUTS (FT)"))
    rapport_lines.extend(_build_human_explain_over25(team1, team2, over25))
    rapport_lines.append(_line_blank())

    # ---- PARI 7 ----
    rapport_lines.append("...")
    rapport_lines.append(_line_blank())
    rapport_lines.append(_section_title("PARI 7 — UNDER 3.5 BUTS (FT)"))
    rapport_lines.extend(_build_human_explain_under35(team1, team2, under35))
    rapport_lines.append(_line_blank())

    # ---- PARI 5 ----
    rapport_lines.append("...")
    rapport_lines.append(_line_blank())
    rapport_lines.append(_section_title("PARI 5 — TEAM WIN (TEAM1 / TEAM2)"))
    rapport_lines.append(_bold(f"{team1} — GAGNE (FT)"))
    rapport_lines.extend(_build_human_explain_team_win(team1, team2, t1_win))
    rapport_lines.append(_line_blank())
    rapport_lines.append(_bold(f"{team2} — GAGNE (FT)"))
    rapport_lines.extend(_build_human_explain_team_win(team2, team1, t2_win))
    rapport_lines.append(_line_blank())

    rapport = "\n".join(rapport_lines)

    # TSV (multi-paris) — format compatible main.py
    date_str = str(data.get("date", "") or "")
    league = str(data.get("league", "") or "")
    fixture_id = data.get("fixture_id")

    market_odds = (context.get("market_odds") or {})

    match_id = make_match_id(date_str, league, team1, team2)

    bets: List[Dict[str, Any]] = []

    # BET 1 — HT +0.5 (CANONIQUE)
    ht05_label = str(ht05.get("final_level") or "")
    ht05_is_candidate = _is_exportable(ht05_label, BETKEY_HT05)
    ht05_score = float(_level_index(ht05_label))
    odd_ht05 = _pick_market_odd(BETKEY_HT05, market_odds)
    ht05_comment = _build_comment_with_odds(fixture_id, odd_ht05)

    ht05_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_HT05,
        metric="HT+0.5",
        score=ht05_score,
        label=ht05_label,
        is_candidate=ht05_is_candidate,
        comment=ht05_comment,
    )
    bets.append(
        {
            "key": BETKEY_HT05,
            "metric": "HT+0.5",
            "score": ht05_score,
            "label": ht05_label,
            "is_candidate": ht05_is_candidate,
            "tsv": ht05_tsv,
        }
    )

    # BET 2 — 1X HT DOMICILE (CANONIQUE)
    dcht_label = str(dcht.get("final_level") or "")
    dcht_is_candidate = _is_exportable(dcht_label, BETKEY_HT1X_HOME)
    dcht_score = float(_level_index(dcht_label))
    odd_ht1x = _pick_market_odd(BETKEY_HT1X_HOME, market_odds)
    dcht_comment = _build_comment_with_odds(fixture_id, odd_ht1x)

    dcht_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_HT1X_HOME,
        metric="HT 1X Home",
        score=dcht_score,
        label=dcht_label,
        is_candidate=dcht_is_candidate,
        comment=dcht_comment,
    )
    bets.append(
        {
            "key": BETKEY_HT1X_HOME,
            "metric": "HT 1X Home",
            "score": dcht_score,
            "label": dcht_label,
            "is_candidate": dcht_is_candidate,
            "tsv": dcht_tsv,
        }
    )

    # BET 3 — TEAM TO SCORE (CANONIQUE FT)
    t1_label = str(t1_score.get("final_level") or "")
    t1_is_candidate = _is_exportable(t1_label, BETKEY_TEAM1_SCORE_FT)
    t1_score_idx = float(_level_index(t1_label))
    odd_t1 = _pick_market_odd(BETKEY_TEAM1_SCORE_FT, market_odds)
    t1_comment = _build_comment_with_odds(fixture_id, odd_t1)

    t1_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_TEAM1_SCORE_FT,
        metric="Team1 scores (FT)",
        score=t1_score_idx,
        label=t1_label,
        is_candidate=t1_is_candidate,
        comment=t1_comment,
    )
    bets.append(
        {
            "key": BETKEY_TEAM1_SCORE_FT,
            "metric": "Team1 scores (FT)",
            "score": t1_score_idx,
            "label": t1_label,
            "is_candidate": t1_is_candidate,
            "tsv": t1_tsv,
        }
    )

    t2_label = str(t2_score.get("final_level") or "")
    t2_is_candidate = _is_exportable(t2_label, BETKEY_TEAM2_SCORE_FT)
    t2_score_idx = float(_level_index(t2_label))
    odd_t2 = _pick_market_odd(BETKEY_TEAM2_SCORE_FT, market_odds)
    t2_comment = _build_comment_with_odds(fixture_id, odd_t2)

    t2_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_TEAM2_SCORE_FT,
        metric="Team2 scores (FT)",
        score=t2_score_idx,
        label=t2_label,
        is_candidate=t2_is_candidate,
        comment=t2_comment,
    )
    bets.append(
        {
            "key": BETKEY_TEAM2_SCORE_FT,
            "metric": "Team2 scores (FT)",
            "score": t2_score_idx,
            "label": t2_label,
            "is_candidate": t2_is_candidate,
            "tsv": t2_tsv,
        }
    )

    # BET 4 — Over 1.5 FT (CANONIQUE)
    o15_label = str(over15.get("final_level") or "")
    o15_is_candidate = _is_exportable(o15_label, BETKEY_O15_FT)
    o15_score = float(_level_index(o15_label))
    odd_o15 = _pick_market_odd(BETKEY_O15_FT, market_odds)
    o15_comment = _build_comment_with_odds(fixture_id, odd_o15)

    o15_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_O15_FT,
        metric="Over 1.5 (FT)",
        score=o15_score,
        label=o15_label,
        is_candidate=o15_is_candidate,
        comment=o15_comment,
    )
    bets.append(
        {
            "key": BETKEY_O15_FT,
            "metric": "Over 1.5 (FT)",
            "score": o15_score,
            "label": o15_label,
            "is_candidate": o15_is_candidate,
            "tsv": o15_tsv,
        }
    )

    # BET 6 — Over 2.5 FT (CANONIQUE)
    o25_label = str(over25.get("final_level") or "")
    o25_is_candidate = _is_exportable(o25_label, BETKEY_O25_FT)
    o25_score = float(_level_index(o25_label))
    odd_o25 = _pick_market_odd(BETKEY_O25_FT, market_odds)
    o25_comment = _build_comment_with_odds(fixture_id, odd_o25)

    o25_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_O25_FT,
        metric="Over 2.5 (FT)",
        score=o25_score,
        label=o25_label,
        is_candidate=o25_is_candidate,
        comment=o25_comment,
    )
    bets.append(
        {
            "key": BETKEY_O25_FT,
            "metric": "Over 2.5 (FT)",
            "score": o25_score,
            "label": o25_label,
            "is_candidate": o25_is_candidate,
            "tsv": o25_tsv,
        }
    )

    # BET 7 — Under 3.5 FT (CANONIQUE)
    u35_label = str(under35.get("final_level") or "")
    u35_is_candidate = _is_exportable(u35_label, BETKEY_U35_FT)
    u35_score = float(_level_index(u35_label))
    odd_u35 = _pick_market_odd(BETKEY_U35_FT, market_odds)
    u35_comment = _build_comment_with_odds(fixture_id, odd_u35)

    u35_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_U35_FT,
        metric="Under 3.5 (FT)",
        score=u35_score,
        label=u35_label,
        is_candidate=u35_is_candidate,
        comment=u35_comment,
    )
    bets.append(
        {
            "key": BETKEY_U35_FT,
            "metric": "Under 3.5 (FT)",
            "score": u35_score,
            "label": u35_label,
            "is_candidate": u35_is_candidate,
            "tsv": u35_tsv,
        }
    )

    # BET 5 — TEAM WIN FT (CANONIQUE)
    t1w_label = str(t1_win.get("final_level") or "")
    t1w_is_candidate = _is_exportable(t1w_label, BETKEY_TEAM1_WIN_FT)
    t1w_score = float(_level_index(t1w_label))
    odd_t1w = _pick_market_odd(BETKEY_TEAM1_WIN_FT, market_odds)
    t1w_comment = _build_comment_with_odds(fixture_id, odd_t1w)

    t1w_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_TEAM1_WIN_FT,
        metric="Team1 wins (FT)",
        score=t1w_score,
        label=t1w_label,
        is_candidate=t1w_is_candidate,
        comment=t1w_comment,
    )
    bets.append(
        {
            "key": BETKEY_TEAM1_WIN_FT,
            "metric": "Team1 wins (FT)",
            "score": t1w_score,
            "label": t1w_label,
            "is_candidate": t1w_is_candidate,
            "tsv": t1w_tsv,
        }
    )

    t2w_label = str(t2_win.get("final_level") or "")
    t2w_is_candidate = _is_exportable(t2w_label, BETKEY_TEAM2_WIN_FT)
    t2w_score = float(_level_index(t2w_label))
    odd_t2w = _pick_market_odd(BETKEY_TEAM2_WIN_FT, market_odds)
    t2w_comment = _build_comment_with_odds(fixture_id, odd_t2w)

    t2w_tsv = build_prediction_tsv_line(
        match_id=match_id,
        date_str=date_str,
        league=league,
        home=team1,
        away=team2,
        bet_key=BETKEY_TEAM2_WIN_FT,
        metric="Team2 wins (FT)",
        score=t2w_score,
        label=t2w_label,
        is_candidate=t2w_is_candidate,
        comment=t2w_comment,
    )
    bets.append(
        {
            "key": BETKEY_TEAM2_WIN_FT,
            "metric": "Team2 wins (FT)",
            "score": t2w_score,
            "label": t2w_label,
            "is_candidate": t2w_is_candidate,
            "tsv": t2w_tsv,
        }
    )

    return {
        "rapport": rapport,
        "bets": bets,
    }