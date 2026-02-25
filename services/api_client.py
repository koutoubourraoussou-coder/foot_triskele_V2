"""
services/api_client.py
----------------------

Client d'accès à l'API-Football (api-sports).

VERSION "MULTI-PARIS" – renforcée (robustesse long terme)

Renforts principaux :
- _call_api : retry/backoff sur 429/5xx/timeouts + arrêt si API_KEY manquante
- détection JSON "errors" / "message" / quota -> traite comme erreur transitoire
- caches : n'enregistre pas les réponses vides suspectes
- chemins : DATA_DIR basé sur ROOT (plus dépendant du cwd)
- H2H : hard cap local
- Odds : agrège bookmakers sur tous les items de response (pas raw[0] seulement)

✅ AJOUT (cohérence chaîne RUN) :
- matches_meta.tsv lu en priorité depuis TRISKELE_RUN_DIR si présent
  (sinon fallback data/matches_meta.tsv)
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import os
import json
import requests
import unicodedata
import re
import difflib
import time

from config import API_BASE_URL, DEBUG_API


# =====================================================================
# 0. Paramètres de collecte (bases)
# =====================================================================

N_FORM_LARGE = 8       # forme large (8 derniers matchs)
N_FORM_RECENT = 4      # forme récente (4 derniers matchs)
N_H2H = 3              # H2H (3 derniers)

LAST_FIXTURES_BUFFER = 16
LAST_FIXTURES_HARD_CAP = 40

# H2H peut être énorme : hard cap local avant filtre/slice
H2H_HARD_CAP = 60

DEFAULT_SEASON = 2023
_WARNED_NO_KEY = False


def debug(msg: str) -> None:
    if DEBUG_API:
        print(msg)


# =====================================================================
# 1. Chemins robustes (ROOT/DATA_DIR) + RUN DIR
# =====================================================================

# ⚠️ IMPORTANT : on base tout sur le projet, pas sur le cwd
# services/api_client.py -> ROOT = dossier projet (parent de "services")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

ALIASES_FILE = DATA_DIR / "aliases.json"

TEAM_ALIAS_SUGGESTIONS_FILE = DATA_DIR / "missing_team_ids.tsv"
LEAGUE_ALIAS_SUGGESTIONS_FILE = DATA_DIR / "missing_league_ids.tsv"


def _get_run_dir() -> Optional[Path]:
    rd = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if not rd:
        return None
    p = Path(rd)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _resolve_matches_meta_file() -> Path:
    """
    ✅ Source de vérité (robuste long terme) :
    - Si TRISKELE_RUN_DIR/matches_meta.tsv existe -> on le prend.
    - Sinon -> data/matches_meta.tsv
    """
    run_dir = _get_run_dir()
    if run_dir is not None:
        p = run_dir / "matches_meta.tsv"
        if p.exists() and p.stat().st_size > 0:
            return p
    return DATA_DIR / "matches_meta.tsv"


MATCHES_META_FILE = _resolve_matches_meta_file()
_MATCH_META_SOURCE_PATH = str(MATCHES_META_FILE)


# =====================================================================
# 2. Caches
# =====================================================================

_MATCH_META_CACHE: Dict[
    Tuple[str, str, str, str],
    Tuple[Optional[int], Optional[int], Optional[int], Optional[int]],
] = {}

CLUB_NAME_ALIASES: Dict[str, str] = {}
LEAGUE_NAME_ALIASES: Dict[str, int] = {}

_MATCH_DATA_CACHE_BY_FIXTURE: Dict[int, Dict[str, Any]] = {}
_MATCH_DATA_CACHE_BY_KEY: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

_STANDINGS_CACHE: Dict[Tuple[int, int], Any] = {}

# Anti-poison : mémorise les caches vides uniquement si on est sûr que c'est "vraiment vide"
# (ici on fait simple : on ne cache PAS les vides)
# =====================================================================


# =====================================================================
# 3. Helpers communs de normalisation
# =====================================================================

def _strip_accents_and_non_alnum(s: Any) -> str:
    if s is None:
        return ""
    if isinstance(s, (bytes, bytearray)):
        try:
            s = s.decode("utf-8", errors="ignore")
        except Exception:
            s = str(s)
    if not isinstance(s, str):
        s = str(s)

    s = s.strip()
    if not s:
        return ""

    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split()).strip()


def _normalize_team_name_basic(name: str) -> str:
    if not name:
        return ""
    base = _strip_accents_and_non_alnum(name)
    if not base:
        return ""
    stop_words = {"fc", "cf", "sc", "afc", "cfc", "sv", "bk"}
    tokens = [t for t in base.split() if t and t not in stop_words]
    return " ".join(tokens).strip()


def _normalize_team_name(name: str) -> str:
    norm = _normalize_team_name_basic(name)
    if not norm:
        return ""
    alias = CLUB_NAME_ALIASES.get(norm)
    if alias is not None:
        return alias
    return norm


def _normalize_league_name(name: str) -> str:
    return _strip_accents_and_non_alnum(name)


# =====================================================================
# 4. Chargement aliases JSON
# =====================================================================

def _load_aliases_from_json() -> None:
    global CLUB_NAME_ALIASES, LEAGUE_NAME_ALIASES
    CLUB_NAME_ALIASES = {}
    LEAGUE_NAME_ALIASES = {}

    if not ALIASES_FILE.exists():
        print(f"ℹ️ Fichier d'aliases introuvable ({ALIASES_FILE}), on tourne en full automatique.")
        return

    try:
        with ALIASES_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ Impossible de lire {ALIASES_FILE} : {e} → aucun alias chargé.")
        return

    raw_clubs = data.get("clubs") or {}
    raw_leagues = data.get("leagues") or {}

    for raw_key, raw_val in raw_clubs.items():
        if not isinstance(raw_key, str) or not isinstance(raw_val, str):
            continue
        key_norm = _normalize_team_name_basic(raw_key)
        val_norm = _normalize_team_name_basic(raw_val)
        if key_norm and val_norm:
            CLUB_NAME_ALIASES[key_norm] = val_norm

    for raw_key, raw_val in raw_leagues.items():
        if not isinstance(raw_key, str):
            continue
        key_norm = _normalize_league_name(raw_key)
        if not key_norm:
            continue
        try:
            league_id = int(raw_val)
        except (TypeError, ValueError):
            continue
        LEAGUE_NAME_ALIASES[key_norm] = league_id

    print(
        f"ℹ️ Aliases chargés depuis {ALIASES_FILE} : "
        f"{len(CLUB_NAME_ALIASES)} clubs, {len(LEAGUE_NAME_ALIASES)} ligues."
    )


_load_aliases_from_json()


# =====================================================================
# 5. Logs auto-apprentissage
# =====================================================================

def _append_missing_team_log(
    raw_name: str,
    league_id: Optional[int],
    season: int,
    best_score: float,
    candidates: List[Tuple[str, int]],
) -> None:
    try:
        TEAM_ALIAS_SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        new_file = not TEAM_ALIAS_SUGGESTIONS_FILE.exists()
        with TEAM_ALIAS_SUGGESTIONS_FILE.open("a", encoding="utf-8") as f:
            if new_file:
                f.write("raw_name\tleague_id\tseason\tbest_score\tcandidate_norms\n")
            cand_names = ",".join(c[0] for c in candidates[:5])
            f.write(f"{raw_name}\t{league_id or ''}\t{season}\t{best_score:.2f}\t{cand_names}\n")
    except Exception as e:
        print(f"⚠️ Impossible d'écrire dans {TEAM_ALIAS_SUGGESTIONS_FILE}: {e}")


def _append_missing_league_log(raw_name: str, norm_name: str) -> None:
    try:
        LEAGUE_ALIAS_SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        new_file = not LEAGUE_ALIAS_SUGGESTIONS_FILE.exists()
        with LEAGUE_ALIAS_SUGGESTIONS_FILE.open("a", encoding="utf-8") as f:
            if new_file:
                f.write("raw_name\tnorm_name\n")
            f.write(f"{raw_name}\t{norm_name}\n")
    except Exception as e:
        print(f"⚠️ Impossible d'écrire dans {LEAGUE_ALIAS_SUGGESTIONS_FILE}: {e}")


# =====================================================================
# 6. Configuration API / headers
# =====================================================================

def _get_api_key() -> str:
    return os.getenv("API_KEY", "").strip()


def _build_headers() -> Dict[str, str]:
    key = _get_api_key()
    return {
        "x-apisports-key": key,
        "x-rapidapi-key": key,
    }


def infer_season_from_date(date_str: Optional[str]) -> int:
    if not date_str:
        return DEFAULT_SEASON
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return DEFAULT_SEASON
    return d.year if d.month >= 7 else d.year - 1


# =====================================================================
# 7. _call_api robuste
# =====================================================================

def _looks_like_transient_api_error(payload: Any) -> bool:
    """
    Détecte certains formats d'erreurs renvoyées en 200.
    """
    if not isinstance(payload, dict):
        return False

    errors = payload.get("errors")
    if isinstance(errors, dict) and errors:
        return True
    if isinstance(errors, list) and errors:
        return True

    msg = payload.get("message")
    if isinstance(msg, str) and msg.strip():
        m = msg.lower()
        if "rate" in m or "limit" in m or "quota" in m or "too many" in m:
            return True

    return False


def _call_api(endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Appel générique API-Football robuste.
    - Stop immédiat si API_KEY absente
    - Retry borné sur 429/5xx/timeouts
    - Détecte erreurs JSON même en 200
    """
    global _WARNED_NO_KEY

    url = API_BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")

    key = _get_api_key()
    if not key:
        if not _WARNED_NO_KEY:
            _WARNED_NO_KEY = True
            print("⚠️ API_KEY manquante. Définis-la via la variable d'environnement API_KEY.")
        return []

    max_attempts = 3
    backoffs = [0.6, 1.2, 2.0]

    last_err: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, headers=_build_headers(), params=params, timeout=12)
        except requests.RequestException as e:
            last_err = f"Erreur réseau: {e}"
            if attempt < max_attempts:
                time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                continue
            print(f"⚠️ {last_err}")
            return []

        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"HTTP {resp.status_code} sur {endpoint} (attempt {attempt}/{max_attempts})"
            if attempt < max_attempts:
                ra = resp.headers.get("Retry-After")
                if ra:
                    try:
                        time.sleep(float(ra))
                    except Exception:
                        time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                else:
                    time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                continue

            print(f"⚠️ {last_err}")
            return []

        if resp.status_code in (401, 403):
            print(f"⚠️ Accès refusé (HTTP {resp.status_code}). Vérifie API_KEY / plan / headers.")
            try:
                j = resp.json()
                print("Détail :", j)
            except Exception:
                print("Réponse brute :", resp.text[:300])
            return []

        if resp.status_code != 200:
            print(f"⚠️ Statut {resp.status_code} pour {url}")
            try:
                print("Détail :", resp.json())
            except Exception:
                print("Réponse brute :", resp.text[:300])
            return []

        try:
            data = resp.json()
        except Exception as e:
            last_err = f"JSON invalide: {e}"
            if attempt < max_attempts:
                time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                continue
            print(f"⚠️ {last_err}")
            return []

        if _looks_like_transient_api_error(data):
            last_err = f"Erreur API logique (200) sur {endpoint}: {data.get('message') or data.get('errors')}"
            if attempt < max_attempts:
                time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                continue
            print(f"⚠️ {last_err}")
            return []

        resp_list = data.get("response", [])
        if isinstance(resp_list, list):
            return resp_list
        return []

    if last_err:
        print(f"⚠️ {last_err}")
    return []


# =====================================================================
# 8. Résolution ligues
# =====================================================================

def _find_league_id(league_name: Optional[str]) -> Optional[int]:
    if not league_name:
        return None

    raw = league_name.strip()
    norm = _normalize_league_name(raw)
    if not norm:
        return None

    alias_id = LEAGUE_NAME_ALIASES.get(norm)
    if alias_id is not None:
        debug(f"[DEBUG] Ligue via alias JSON : '{league_name}' → id={alias_id}")
        return alias_id

    results = _call_api("/leagues", {"search": raw}) or []
    if not results and norm != raw.lower():
        results = _call_api("/leagues", {"search": norm}) or []

    if not results:
        print(f"⚠️ Impossible de trouver la ligue via l'API : '{league_name}'")
        _append_missing_league_log(raw, norm)
        return None

    best_id: Optional[int] = None
    best_score: float = 0.0

    for item in results:
        league_info = item.get("league", {}) or {}
        api_id = league_info.get("id")
        api_name = league_info.get("name") or ""
        if not api_id or not api_name:
            continue
        api_norm = _normalize_league_name(api_name)
        score = difflib.SequenceMatcher(None, norm, api_norm).ratio()
        if score > best_score:
            best_score = score
            best_id = api_id

    if best_id is None or best_score < 0.50:
        print(f"⚠️ Aucun match de ligue acceptable : '{league_name}' (sim max {best_score:.2f})")
        _append_missing_league_log(raw, norm)
        return None

    debug(f"[DEBUG] Ligue via API : '{league_name}' → id={best_id} (score {best_score:.2f})")
    return best_id


# =====================================================================
# 9. Résolution équipes
# =====================================================================

_COMMON_TEAM_WORDS = {
    "fc", "sc", "ac", "cf", "afc",
    "de", "da", "do", "sd", "cd",
    "utd", "united", "city", "town",
    "club"
}

def _normalize_team_string(name: str) -> List[str]:
    if not name:
        return []
    name_norm = unicodedata.normalize("NFKD", name)
    name_norm = "".join(c for c in name_norm if not unicodedata.combining(c))
    tokens = re.split(r"[^a-z0-9]+", name_norm.lower())
    return [t for t in tokens if t and t not in _COMMON_TEAM_WORDS]


def _find_team_id(
    team_name: str,
    league_id: Optional[int] = None,
    season: int = DEFAULT_SEASON,
) -> Optional[int]:
    team_name = (team_name or "").strip()
    if not team_name:
        return None

    def _teams_query_league(search: Optional[str]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if league_id is not None:
            params["league"] = league_id
            params["season"] = season
        if search:
            params["search"] = search
        return _call_api("/teams", params) or []

    def _teams_query_global(search: Optional[str]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if search:
            params["search"] = search
        return _call_api("/teams", params) or []

    normalized_for_search = _normalize_team_name(team_name)

    results: List[Dict[str, Any]] = []
    used_global = False

    if league_id is not None:
        results = _teams_query_league(team_name)
        if not results and normalized_for_search:
            results = _teams_query_league(normalized_for_search)
        if not results:
            results = _teams_query_league(None)

    if not results:
        used_global = True
        results = _teams_query_global(team_name)
        if not results and normalized_for_search:
            results = _teams_query_global(normalized_for_search)

    if not results:
        print(f"⚠️ Impossible de trouver l'équipe : {team_name}")
        _append_missing_team_log(team_name, league_id, season, 0.0, [])
        return None

    def _pick_best_candidate(results_list: List[Dict[str, Any]]) -> Tuple[Optional[int], float, List[Tuple[str, int]]]:
        candidates: List[Tuple[str, int]] = []
        for item in results_list:
            t = item.get("team", {})
            name = t.get("name", "")
            t_id = t.get("id", None)
            if not name or not t_id:
                continue
            norm = _normalize_team_name_basic(name)
            if not norm:
                continue
            candidates.append((norm, t_id))

        target = _normalize_team_name_basic(team_name)
        best_id: Optional[int] = None
        best_score = 0.0

        for norm_name, t_id in candidates:
            score = difflib.SequenceMatcher(None, target, norm_name).ratio()
            if score > best_score:
                best_score = score
                best_id = t_id

        return best_id, best_score, candidates

    best_id, best_score, candidates = _pick_best_candidate(results)

    if best_id is None or best_score < 0.50:
        print(
            f"⚠️ Aucun match acceptable pour : {team_name} "
            f"(sim max {best_score:.2f}, mode={'global' if used_global else 'league'})"
        )
        _append_missing_team_log(team_name, league_id, season, best_score, candidates)
        return None

    debug(
        f"[DEBUG] Équipe résolue : '{team_name}' → id={best_id} "
        f"(score {best_score:.2f}, mode={'global' if used_global else 'league'})"
    )
    return best_id


# =====================================================================
# 10. Fixture snapshot (priorité fixture_id)
# =====================================================================

def _get_fixture_snapshot(fixture_id: Optional[int]) -> Dict[str, Any]:
    if fixture_id is None:
        return {}

    resp = _call_api("/fixtures", {"id": fixture_id}) or []
    if not resp:
        resp = _call_api("/fixtures", {"fixture": fixture_id}) or []

    if not resp:
        return {}

    fx = resp[0] or {}
    fixture_info = fx.get("fixture", {}) or {}
    league_info = fx.get("league", {}) or {}
    teams_info = fx.get("teams", {}) or {}

    home = teams_info.get("home", {}) or {}
    away = teams_info.get("away", {}) or {}

    d_iso = fixture_info.get("date", "")
    date_str = d_iso[:10] if isinstance(d_iso, str) and len(d_iso) >= 10 else ""

    return {
        "fixture_id": fixture_id,
        "date": date_str,
        "league_id": league_info.get("id"),
        "league_name": (league_info.get("name") or "").strip() or None,
        "home_id": home.get("id"),
        "away_id": away.get("id"),
        "home_name": (home.get("name") or "").strip() or None,
        "away_name": (away.get("name") or "").strip() or None,
    }


# =====================================================================
# 11. Last fixtures (déjà hard-cappé)
# =====================================================================

def _get_last_fixtures(
    team_id: int,
    season: int,
    before_date: Optional[str] = None,
    last: int = LAST_FIXTURES_BUFFER,
) -> List[Dict[str, Any]]:
    params = {"team": team_id, "season": season}
    if last and last > 0:
        params["last"] = int(last)

    fixtures = _call_api("/fixtures", params) or []
    debug(f"[DEBUG] Fixtures bruts team={team_id} season={season} asked_last={params.get('last')} -> {len(fixtures)}")

    fixtures_sorted = sorted(fixtures, key=lambda fx: fx.get("fixture", {}).get("date", ""), reverse=True)

    cap = LAST_FIXTURES_HARD_CAP
    if last and last > 0:
        cap = max(cap, int(last) * 2)

    if len(fixtures_sorted) > cap:
        fixtures_sorted = fixtures_sorted[:cap]
        debug(f"[DEBUG] → HARD_CAP fixtures : {len(fixtures_sorted)} (cap={cap})")

    if before_date:
        filtered: List[Dict[str, Any]] = []
        for fx in fixtures_sorted:
            fixture_info = fx.get("fixture", {}) or {}
            d_iso = fixture_info.get("date", "")
            if not isinstance(d_iso, str):
                continue
            fx_date = d_iso[:10]
            if fx_date and fx_date < before_date:
                filtered.append(fx)
        fixtures_sorted = filtered
        debug(f"[DEBUG] → after before_date={before_date}: {len(fixtures_sorted)}")

    return fixtures_sorted


def _ht_result_label(ht_gf: Optional[int], ht_ga: Optional[int]) -> Optional[str]:
    if not isinstance(ht_gf, int) or not isinstance(ht_ga, int):
        return None
    if ht_gf > ht_ga:
        return "W"
    if ht_gf == ht_ga:
        return "D"
    return "L"


def _simplify_fixture_for_team(fixture: Dict[str, Any], team_id: int) -> Optional[Dict[str, Any]]:
    fixture_info = fixture.get("fixture", {}) or {}
    teams = fixture.get("teams", {}) or {}
    goals = fixture.get("goals", {}) or {}
    score = fixture.get("score", {}) or {}
    ht = score.get("halftime", {}) or {}

    home = teams.get("home", {}) or {}
    away = teams.get("away", {}) or {}

    home_id = home.get("id")
    away_id = away.get("id")

    if team_id not in (home_id, away_id):
        return None

    home_goals = goals.get("home")
    away_goals = goals.get("away")

    if home_goals is None or away_goals is None:
        return None
    try:
        home_goals = int(home_goals)
        away_goals = int(away_goals)
    except Exception:
        return None

    ht_home = ht.get("home")
    ht_away = ht.get("away")

    ht_total: Optional[int] = None
    has_ht_goal: Optional[bool] = None

    if isinstance(ht_home, int) and isinstance(ht_away, int):
        ht_total = ht_home + ht_away
        has_ht_goal = (ht_total >= 1)

    is_home = team_id == home_id

    if is_home:
        gf = home_goals
        ga = away_goals
        opp_id = away_id
        opp_name = (away.get("name") or "").strip() or None
        ht_gf = ht_home if isinstance(ht_home, int) else None
        ht_ga = ht_away if isinstance(ht_away, int) else None
    else:
        gf = away_goals
        ga = home_goals
        opp_id = home_id
        opp_name = (home.get("name") or "").strip() or None
        ht_gf = ht_away if isinstance(ht_away, int) else None
        ht_ga = ht_home if isinstance(ht_home, int) else None

    is_00 = (home_goals == 0 and away_goals == 0)
    ht_result = _ht_result_label(ht_gf, ht_ga)
    ht_not_losing = (ht_result in ("W", "D")) if ht_result is not None else None

    date_iso = fixture_info.get("date", "")
    date_str = date_iso[:10] if isinstance(date_iso, str) and len(date_iso) >= 10 else ""

    return {
        "date": date_str,
        "is_home": is_home,
        "opponent_id": int(opp_id) if isinstance(opp_id, int) else None,
        "opponent_name": opp_name,
        "goals_for": gf,
        "goals_against": ga,
        "ft_total": gf + ga,
        "is_00": is_00,
        "ht_goals_for": ht_gf,
        "ht_goals_against": ht_ga,
        "ht_total": ht_total,
        "has_ht_goal": has_ht_goal,
        "ht_result": ht_result,
        "ht_not_losing": ht_not_losing,
    }


def _build_team_last_matches(
    team_id: int,
    n: int,
    season: int,
    before_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    simplified: List[Dict[str, Any]] = []
    max_seasons_back = 7
    seasons_checked = 0
    current_season = season

    while len(simplified) < n and seasons_checked < max_seasons_back:
        fixtures = _get_last_fixtures(team_id, season=current_season, before_date=before_date)

        for fx in fixtures:
            if len(simplified) >= n:
                break
            simp = _simplify_fixture_for_team(fx, team_id)
            if simp:
                simplified.append(simp)

        seasons_checked += 1
        if len(simplified) >= n:
            break
        current_season -= 1

    return simplified


# =====================================================================
# 12. H2H (hard cap)
# =====================================================================

def _get_h2h_fixtures(
    team_home_id: int,
    team_away_id: int,
    league_id: Optional[int],
    n: int,
    before_date: Optional[str],
) -> List[Dict[str, Any]]:
    h2h_param = f"{team_home_id}-{team_away_id}"
    fixtures = _call_api("/fixtures/headtohead", {"h2h": h2h_param}) or []
    if not fixtures:
        return []

    fixtures_sorted = sorted(fixtures, key=lambda fx: fx.get("fixture", {}).get("date", ""), reverse=True)

    if len(fixtures_sorted) > H2H_HARD_CAP:
        fixtures_sorted = fixtures_sorted[:H2H_HARD_CAP]

    if before_date:
        filtered: List[Dict[str, Any]] = []
        for fx in fixtures_sorted:
            fixture_info = fx.get("fixture", {}) or {}
            d_iso = fixture_info.get("date", "")
            if not isinstance(d_iso, str):
                continue
            fx_date = d_iso[:10]
            if fx_date < before_date:
                filtered.append(fx)
        fixtures_sorted = filtered
        if not fixtures_sorted:
            return []

    simplified: List[Dict[str, Any]] = []

    def _fill_from(fixtures_list: List[Dict[str, Any]], filter_league: bool) -> None:
        nonlocal simplified
        for fx in fixtures_list:
            if len(simplified) >= n:
                break

            if filter_league and league_id is not None:
                if fx.get("league", {}).get("id") != league_id:
                    continue

            fixture_info = fx.get("fixture", {}) or {}
            teams_info = fx.get("teams", {}) or {}
            goals = fx.get("goals", {}) or {}
            score = fx.get("score", {}) or {}
            ht = score.get("halftime", {}) or {}

            home_team = teams_info.get("home", {}) or {}
            away_team = teams_info.get("away", {}) or {}

            home_goals = goals.get("home")
            away_goals = goals.get("away")

            try:
                home_goals = int(home_goals)
                away_goals = int(away_goals)
            except Exception:
                continue

            ht_home = ht.get("home")
            ht_away = ht.get("away")

            ht_total: Optional[int] = None
            has_ht_goal: Optional[bool] = None
            if isinstance(ht_home, int) and isinstance(ht_away, int):
                ht_total = ht_home + ht_away
                has_ht_goal = (ht_total >= 1)

            date_iso = fixture_info.get("date", "")
            date_str = date_iso[:10] if isinstance(date_iso, str) and len(date_iso) >= 10 else ""

            simplified.append(
                {
                    "date": date_str,
                    "home_name": (home_team.get("name") or "").strip() or None,
                    "away_name": (away_team.get("name") or "").strip() or None,
                    "goals_home": home_goals,
                    "goals_away": away_goals,
                    "ft_total": home_goals + away_goals,
                    "is_00": (home_goals == 0 and away_goals == 0),
                    "ht_home": ht_home if isinstance(ht_home, int) else None,
                    "ht_away": ht_away if isinstance(ht_away, int) else None,
                    "ht_total": ht_total,
                    "has_ht_goal": has_ht_goal,
                }
            )

    _fill_from(fixtures_sorted, filter_league=True)
    if not simplified:
        _fill_from(fixtures_sorted, filter_league=False)

    return simplified

# =====================================================================
# 13bis. Wrappers rétro-compat (post_analysis_core)
# =====================================================================

def get_match_ids_from_meta(
    league: Optional[str],
    date: Optional[str],
    home: str,
    away: str,
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Compat : renvoie (league_id, home_id, away_id) depuis matches_meta.tsv.
    Évite les variables 'non utilisées' (warnings IDE).
    """
    info = get_match_meta_ids(league, date, home, away)  # (league_id, home_id, away_id, fixture_id)
    return info[0], info[1], info[2]


def get_fixture_id_from_meta(
    league: Optional[str],
    date: Optional[str],
    home: str,
    away: str,
) -> Optional[int]:
    """
    Compat : renvoie fixture_id depuis matches_meta.tsv.
    """
    info = get_match_meta_ids(league, date, home, away)
    return info[3]

# =====================================================================
# 13. matches_meta.tsv
# =====================================================================

_MATCH_META_LOADED = False

def _meta_key(date: Optional[str], league: Optional[str], home: str, away: str) -> Tuple[str, str, str, str]:
    def _canon_date(s: Optional[str]) -> str:
        return (s or "").strip()

    def _canon_league(s: Optional[str]) -> str:
        return _strip_accents_and_non_alnum(s or "")

    def _canon_team(s: Optional[str]) -> str:
        return _normalize_team_name_basic(s or "")

    return (
        _canon_date(date),
        _canon_league(league),
        _canon_team(home),
        _canon_team(away),
    )


def _load_match_meta_cache(force: bool = False) -> None:
    global _MATCH_META_CACHE, _MATCH_META_LOADED, MATCHES_META_FILE, _MATCH_META_SOURCE_PATH

    # ✅ Si la source a changé (bulle différente), on force le reload
    current_meta = _resolve_matches_meta_file()
    current_meta_s = str(current_meta)
    if current_meta_s != _MATCH_META_SOURCE_PATH:
        MATCHES_META_FILE = current_meta
        _MATCH_META_SOURCE_PATH = current_meta_s
        force = True

    if _MATCH_META_LOADED and not force:
        return

    _MATCH_META_LOADED = True
    _MATCH_META_CACHE = {}

    if not MATCHES_META_FILE.exists():
        return

    try:
        with MATCHES_META_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue

                date_str, league, home, away, league_id_str, home_id_str, away_id_str = parts[:7]
                fixture_id_str = parts[7] if len(parts) >= 8 else ""

                def _parse_int(x: str) -> Optional[int]:
                    x = (x or "").strip()
                    if not x:
                        return None
                    try:
                        return int(x)
                    except ValueError:
                        return None

                league_id = _parse_int(league_id_str)
                home_id = _parse_int(home_id_str)
                away_id = _parse_int(away_id_str)
                fixture_id = _parse_int(fixture_id_str)

                key = _meta_key(date_str, league, home, away)
                _MATCH_META_CACHE[key] = (league_id, home_id, away_id, fixture_id)

        debug(f"[DEBUG] matches_meta chargé : {MATCHES_META_FILE} ({len(_MATCH_META_CACHE)} lignes)")
    except Exception as e:
        print(f"⚠️ Impossible de charger {MATCHES_META_FILE} : {e}")


def refresh_match_meta_cache() -> None:
    _load_match_meta_cache(force=True)


def _get_ids_from_meta(
    league: Optional[str],
    date: Optional[str],
    home: str,
    away: str,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    _load_match_meta_cache()
    key = _meta_key(date, league, home, away)
    info = _MATCH_META_CACHE.get(key)
    if not info:
        return (None, None, None, None)
    return info


def get_match_meta_ids(
    league: Optional[str],
    date: Optional[str],
    home: str,
    away: str,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    return _get_ids_from_meta(league, date, home, away)


# =====================================================================
# 14. Standings (anti-poison cache)
# =====================================================================

def _get_team_standing_snapshot(
    league_id: Optional[int],
    season: Optional[int],
    team_id: Optional[int],
) -> Dict[str, Optional[int]]:
    if league_id is None or season is None or team_id is None:
        return {"rank": None, "points": None, "goals_for": None, "goals_against": None}

    key = (league_id, season)
    if key not in _STANDINGS_CACHE:
        raw = _call_api("/standings", {"league": league_id, "season": season}) or []
        if raw:
            _STANDINGS_CACHE[key] = raw
        else:
            return {"rank": None, "points": None, "goals_for": None, "goals_against": None}

    data = _STANDINGS_CACHE.get(key) or []
    info = {"rank": None, "points": None, "goals_for": None, "goals_against": None}

    for entry in data:
        league_block = entry.get("league") or {}
        standings_groups = league_block.get("standings") or []
        for group in standings_groups:
            for row in group:
                t = row.get("team") or {}
                if t.get("id") == team_id:
                    info["rank"] = row.get("rank")
                    info["points"] = row.get("points")
                    all_stats = row.get("all") or {}
                    goals = all_stats.get("goals") or {}
                    info["goals_for"] = goals.get("for")
                    info["goals_against"] = goals.get("against")
                    return info

    return info


# =====================================================================
# 15. Odds (agrégation bookmakers sur tous les items)
# =====================================================================

def _norm_value(s: Any) -> str:
    if s is None:
        return ""
    if isinstance(s, (bytes, bytearray)):
        try:
            s = s.decode("utf-8", errors="ignore")
        except Exception:
            s = str(s)
    if not isinstance(s, str):
        s = str(s)
    return s.strip().upper().replace(" ", "")


def _get_market_odds_for_fixture(
    fixture_id: Optional[int],
    *,
    league_id: Optional[int] = None,
    season: Optional[int] = None,
    date: Optional[str] = None,
) -> Dict[str, Optional[float]]:

    odds_info: Dict[str, Optional[float]] = {
        "bookmaker": None,
        "home_win_odds": None,
        "draw_odds": None,
        "away_win_odds": None,
        "ht_over05_odds": None,
        "ht_1x_odds": None,
        "ft_over15_odds": None,
        "team1_score_odds": None,
        "team2_score_odds": None,
    }

    if fixture_id is None:
        return odds_info

    raw: List[Dict[str, Any]] = []
    raw = _call_api("/odds", {"fixture": fixture_id}) or []
    if not raw:
        raw = _call_api("/odds", {"id": fixture_id}) or []

    if not raw and date:
        params3: Dict[str, Any] = {"date": date}
        if league_id is not None:
            params3["league"] = league_id
        if season is not None:
            params3["season"] = season
        raw = _call_api("/odds", params3) or []

    if not raw:
        return odds_info

    all_bookmakers: List[Dict[str, Any]] = []
    for item in raw:
        bks = (item or {}).get("bookmakers") or []
        if isinstance(bks, list) and bks:
            all_bookmakers.extend(bks)

    if not all_bookmakers:
        return odds_info

    def _as_float(x: Any) -> Optional[float]:
        try:
            if x is None:
                return None
            return float(x)
        except (TypeError, ValueError):
            return None

    def _norm_free(s: Any) -> str:
        return _strip_accents_and_non_alnum(s or "")

    def _norm_compact(s: Any) -> str:
        return _strip_accents_and_non_alnum(s or "").replace(" ", "")

    def _is_yes(v_raw: Any) -> bool:
        v = _norm_free(v_raw)
        return ("yes" in v) or ("oui" in v) or (v.strip() == "y")

    def _is_over_05(v_raw: Any) -> bool:
        v = _norm_free(v_raw)
        raw_s = str(v_raw or "")
        return ("over" in v) and (("0 5" in v) or ("0.5" in raw_s) or ("0,5" in raw_s))

    def _is_over_15(v_raw: Any) -> bool:
        v = _norm_free(v_raw)
        raw_s = str(v_raw or "")
        return ("over" in v) and (("1 5" in v) or ("1.5" in raw_s) or ("1,5" in raw_s))

    def _is_first_half_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        return ("1sthalf" in n) or ("firsthalf" in n) or ("halftime" in n) or ("1st" in n and "half" in n)

    def _is_second_half_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        return ("2ndhalf" in n) or ("secondhalf" in n) or ("2nd" in n and "half" in n)

    def _looks_like_ou_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        return ("overunder" in n) or ("totalgoals" in n) or ("goalsoverunder" in n) or ("total" in n and "goals" in n)

    def _is_double_chance_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        return "doublechance" in n

    def _is_match_winner_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        if "doublechance" in n:
            return False
        return ("matchwinner" in n) or ("1x2" in n) or ("winner" in n)

    def _contains_team_specific_marker(name_raw: str) -> bool:
        n = _norm_free(name_raw)
        if ("home" in n) or ("away" in n):
            return True
        if ("team1" in n) or ("team2" in n):
            return True
        if ("team" in n and "total" in n):
            return True
        if ("team" in n and "goals" in n):
            return True
        return False

    def _looks_like_team_to_score_market(name_raw: str) -> bool:
        n = _norm_compact(name_raw)
        n_free = _norm_free(name_raw)
        if ("both" in n_free) and ("team" in n_free) and ("score" in n_free):
            return False
        return (
            ("teamtoscore" in n) or
            ("team" in n_free and "to" in n_free and "score" in n_free) or
            ("team" in n_free and "score" in n_free)
        )

    def _is_home_market(name_raw: str) -> bool:
        nf = _norm_free(name_raw)
        return ("home" in nf) and ("away" not in nf)

    def _is_away_market(name_raw: str) -> bool:
        nf = _norm_free(name_raw)
        return ("away" in nf) and ("home" not in nf)

    def _has_target_ht_markets(book: Dict[str, Any]) -> bool:
        bets_local = book.get("bets") or []
        has_ht_ou = False
        has_ht_dc = False
        for b in bets_local:
            name_raw = b.get("name") or ""
            if _is_first_half_market(name_raw) and _looks_like_ou_market(name_raw):
                has_ht_ou = True
            if _is_first_half_market(name_raw) and _is_double_chance_market(name_raw):
                has_ht_dc = True
            if has_ht_ou and has_ht_dc:
                return True
        return False

    best_book = None
    for bk in all_bookmakers:
        if _has_target_ht_markets(bk):
            best_book = bk
            break
    if best_book is None:
        best_book = max(all_bookmakers, key=lambda b: len(b.get("bets") or []))

    def _fill(book: Dict[str, Any], out: Dict[str, Optional[float]]) -> None:
        bets_local = book.get("bets") or []
        for bet in bets_local:
            bet_name_raw = bet.get("name") or ""
            values = bet.get("values") or []

            if _is_match_winner_market(bet_name_raw):
                for v in values:
                    val = _norm_value(v.get("value") or "")
                    odd = _as_float(v.get("odd"))
                    if odd is None:
                        continue
                    if val in {"1", "HOME"} and out.get("home_win_odds") is None:
                        out["home_win_odds"] = odd
                    elif val in {"X", "DRAW"} and out.get("draw_odds") is None:
                        out["draw_odds"] = odd
                    elif val in {"2", "AWAY"} and out.get("away_win_odds") is None:
                        out["away_win_odds"] = odd

            if out.get("ht_over05_odds") is None:
                if _is_first_half_market(bet_name_raw) and _looks_like_ou_market(bet_name_raw):
                    for v in values:
                        odd = _as_float(v.get("odd"))
                        if odd is None:
                            continue
                        if _is_over_05(v.get("value") or ""):
                            out["ht_over05_odds"] = odd
                            break

            if out.get("ht_1x_odds") is None:
                if _is_first_half_market(bet_name_raw) and _is_double_chance_market(bet_name_raw):
                    for v in values:
                        val = _norm_value(v.get("value") or "")
                        odd = _as_float(v.get("odd"))
                        if odd is None:
                            continue
                        if val in {"1X", "1/X", "HOME/DRAW", "DRAW/HOME", "HOMEDRAW", "DRAWHOME"}:
                            out["ht_1x_odds"] = odd
                            break

            if out.get("ft_over15_odds") is None:
                if (not _is_first_half_market(bet_name_raw)) and (not _is_second_half_market(bet_name_raw)) and _looks_like_ou_market(bet_name_raw):
                    if _contains_team_specific_marker(bet_name_raw):
                        continue
                    for v in values:
                        odd = _as_float(v.get("odd"))
                        if odd is None:
                            continue
                        if _is_over_15(v.get("value") or ""):
                            out["ft_over15_odds"] = odd
                            break

            if (out.get("team1_score_odds") is None) or (out.get("team2_score_odds") is None):
                if _is_first_half_market(bet_name_raw) or _is_second_half_market(bet_name_raw):
                    continue
                if not _looks_like_team_to_score_market(bet_name_raw):
                    continue

                is_home_mkt = _is_home_market(bet_name_raw)
                is_away_mkt = _is_away_market(bet_name_raw)

                for v in values:
                    odd = _as_float(v.get("odd"))
                    if odd is None:
                        continue
                    if not _is_yes(v.get("value") or ""):
                        continue

                    if is_home_mkt and out.get("team1_score_odds") is None:
                        out["team1_score_odds"] = odd
                        continue
                    if is_away_mkt and out.get("team2_score_odds") is None:
                        out["team2_score_odds"] = odd
                        continue

    odds_info["bookmaker"] = best_book.get("name")
    _fill(best_book, odds_info)

    def _missing_any(out: Dict[str, Optional[float]]) -> bool:
        needed = [
            "home_win_odds", "draw_odds", "away_win_odds",
            "ht_over05_odds", "ht_1x_odds",
            "ft_over15_odds",
            "team1_score_odds", "team2_score_odds",
        ]
        return any(out.get(k) is None for k in needed)

    if _missing_any(odds_info):
        for bk in all_bookmakers:
            if bk is best_book:
                continue
            _fill(bk, odds_info)
            if not _missing_any(odds_info):
                break

    return odds_info


# =====================================================================
# 16. Fonction principale : fetch_match_data
# =====================================================================

def fetch_match_data(league: Optional[str], date: Optional[str], home: str, away: str) -> Dict[str, Any]:
    key_cache = _meta_key(date, league, home, away)

    league_id_meta, home_id_meta, away_id_meta, fixture_id_meta = get_match_meta_ids(league, date, home, away)

    if isinstance(fixture_id_meta, int) and fixture_id_meta > 0 and fixture_id_meta in _MATCH_DATA_CACHE_BY_FIXTURE:
        return _MATCH_DATA_CACHE_BY_FIXTURE[fixture_id_meta]

    if fixture_id_meta is None and key_cache in _MATCH_DATA_CACHE_BY_KEY:
        return _MATCH_DATA_CACHE_BY_KEY[key_cache]

    print(f"\n🔍 Collecte API pour : {home} vs {away} (league='{league}', date='{date}')")

    has_fixture_id = isinstance(fixture_id_meta, int) and fixture_id_meta > 0

    fixture_snapshot = _get_fixture_snapshot(fixture_id_meta) if has_fixture_id else {}
    fixture_id = fixture_id_meta if has_fixture_id else None

    date_canon = fixture_snapshot.get("date") if fixture_snapshot else ""
    if not date_canon:
        date_canon = date or ""

    season = infer_season_from_date(date_canon)

    league_id: Optional[int] = None
    home_id: Optional[int] = None
    away_id: Optional[int] = None

    if isinstance(fixture_snapshot.get("league_id"), int):
        league_id = int(fixture_snapshot["league_id"])
    elif league_id_meta is not None:
        league_id = league_id_meta
    else:
        league_id = _find_league_id(league)

    if isinstance(fixture_snapshot.get("home_id"), int) and isinstance(fixture_snapshot.get("away_id"), int):
        home_id = int(fixture_snapshot["home_id"])
        away_id = int(fixture_snapshot["away_id"])
    else:
        if home_id_meta is not None:
            home_id = home_id_meta
        if away_id_meta is not None:
            away_id = away_id_meta

        if home_id is None:
            home_id = _find_team_id(home, league_id=league_id, season=season)
        if away_id is None:
            away_id = _find_team_id(away, league_id=league_id, season=season)

    if home_id is None or away_id is None:
        print("❌ Impossible de résoudre les IDs d'équipes → abandon pour ce match.")
        return {}

    home_canon = fixture_snapshot.get("home_name") if fixture_snapshot else None
    away_canon = fixture_snapshot.get("away_name") if fixture_snapshot else None
    if not home_canon:
        home_canon = home
    if not away_canon:
        away_canon = away

    home_last_8 = _build_team_last_matches(home_id, n=N_FORM_LARGE, season=season, before_date=date_canon or None)
    away_last_8 = _build_team_last_matches(away_id, n=N_FORM_LARGE, season=season, before_date=date_canon or None)

    home_recent_4 = home_last_8[:N_FORM_RECENT] if home_last_8 else []
    away_recent_4 = away_last_8[:N_FORM_RECENT] if away_last_8 else []

    h2h_3 = _get_h2h_fixtures(
        home_id,
        away_id,
        league_id=league_id,
        n=N_H2H,
        before_date=date_canon or None,
    )

    home_standing = _get_team_standing_snapshot(league_id, season, home_id)
    away_standing = _get_team_standing_snapshot(league_id, season, away_id)

    market_odds = _get_market_odds_for_fixture(
        fixture_id,
        league_id=league_id,
        season=season,
        date=date_canon or date or None,
    )

    context: Dict[str, Any] = {
        "home_standing": home_standing,
        "away_standing": away_standing,
        "market_odds": market_odds,
    }

    data: Dict[str, Any] = {
        "league": league or "",
        "league_id": league_id,
        "date": date_canon or "",
        "season": season,
        "home": home_canon,
        "away": away_canon,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "fixture_id": fixture_id,
        "home_last_8": home_last_8,
        "away_last_8": away_last_8,
        "home_recent_4": home_recent_4,
        "away_recent_4": away_recent_4,
        "h2h_3": h2h_3,
        "team1_last": home_last_8,
        "team2_last": away_last_8,
        "h2h": h2h_3,
        "context": context,
        "xg_info": {},
        "corners_info": {},
    }

    if isinstance(fixture_id, int):
        _MATCH_DATA_CACHE_BY_FIXTURE[fixture_id] = data
    else:
        _MATCH_DATA_CACHE_BY_KEY[key_cache] = data

    return data
