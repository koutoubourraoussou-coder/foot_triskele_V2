# services/post_analysis_core.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date as date_cls, timedelta
import re
import os
import unicodedata
import difflib

from services.post_tickets_human_report import write_post_tickets_human_report
from services.api_client import (
    _call_api,
    get_fixture_id_from_meta,
    refresh_match_meta_cache,
)

POST_MATCHES_FAILED_FILE = Path("data") / "post_matches_failed.txt"

# ✅ NEW: log “healing” des fixture_id (quand on retrouve via fallback date-based)
META_HEAL_FILE = Path("data") / "matches_meta_heal.tsv"

# ==============================
# RUN DIR helpers
# ==============================


def _get_run_dir() -> Optional[Path]:
    run_dir = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if not run_dir:
        return None
    p = Path(run_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_scoped_or_data(name: str) -> Path:
    """
    Si TRISKELE_RUN_DIR est défini : fichiers "reports" doivent vivre dans la bulle.
    Sinon : fallback dans data/.

    ✅ Crée le dossier parent du fichier retourné (robuste si name contient un sous-dossier).
    """
    rd = _get_run_dir()
    p = (rd / name) if rd is not None else (Path("data") / name)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _is_nonempty_file(p: Path) -> bool:
    try:
        return p.exists() and p.is_file() and p.stat().st_size > 0
    except Exception:
        return False


def _latest_archive_dirs(archive_root: Path) -> list[Path]:
    """
    Retourne archive/analyse_YYYY-MM-DD triés du plus récent au plus ancien.
    """
    if not archive_root.exists():
        return []
    dirs = []
    for d in archive_root.iterdir():
        if d.is_dir() and d.name.startswith("analyse_"):
            dirs.append(d)
    dirs.sort(key=lambda x: x.name, reverse=True)
    return dirs


# ==============================
# ✅ Ticket report resolver (ROBUST)
# ==============================


def resolve_tickets_report_path(
    *,
    report_kind: str,
    run_date: Optional[str] = None,
) -> Optional[Path]:
    """
    report_kind:
      - "SYSTEM" => tickets_report.txt
      - "O15_RANDOM" => tickets_o15_random_report.txt

    Stratégie robuste:
      1) data/ (canon)
      2) TRISKELE_RUN_DIR (si défini)
      3) archive/analyse_* (le plus récent d'abord, ou analyse_<run_date> si fourni)
    """
    report_kind = (report_kind or "").strip().upper()
    if report_kind == "SYSTEM":
        base = "tickets_report.txt"
    elif report_kind in ("O15_RANDOM", "O15_RANDOM_ALL", "RANDOM_O15"):
        base = "tickets_o15_random_report.txt"
    elif report_kind in ("U35_RANDOM", "U35_RANDOM_ALL", "RANDOM_U35"):
        base = "tickets_u35_random_report.txt"
    elif report_kind in ("O15_SUPER_RANDOM",):
        base = "tickets_o15_super_random_report.txt"
    elif report_kind in ("U35_SUPER_RANDOM",):
        base = "tickets_u35_super_random_report.txt"
    else:
        base = report_kind.lower()

    # 1) canon data/
    p_data = Path("data") / base
    if _is_nonempty_file(p_data):
        return p_data

    # 2) TRISKELE_RUN_DIR
    rd = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if rd:
        p_run = Path(rd) / base
        if _is_nonempty_file(p_run):
            return p_run

    # 3) archives
    archive_root = Path("archive")
    candidates_dirs: list[Path] = []

    if run_date:
        d = archive_root / f"analyse_{run_date}"
        if d.exists() and d.is_dir():
            candidates_dirs.append(d)

    candidates_dirs.extend(_latest_archive_dirs(archive_root))

    # noms possibles dans l'archive
    name_candidates = [
        base,
        # Copies “brutes” ou renommées
        f"verdict_post_analyse_{base}",
        "verdict_post_analyse_tickets_report.txt" if base == "tickets_report.txt" else None,
        "verdict_post_analyse_tickets_o15_random_report.txt" if base == "tickets_o15_random_report.txt" else None,
        "verdict_post_analyse_tickets_u35_random_report.txt" if base == "tickets_u35_random_report.txt" else None,
        "verdict_post_analyse_tickets_o15_super_random_report.txt" if base == "tickets_o15_super_random_report.txt" else None,
        "verdict_post_analyse_tickets_u35_super_random_report.txt" if base == "tickets_u35_super_random_report.txt" else None,
    ]
    name_candidates = [x for x in name_candidates if x]

    for d in candidates_dirs:
        for nm in name_candidates:
            p = d / nm
            if _is_nonempty_file(p):
                return p

    return None


# ==============================
# Tickets paths
# ==============================

# ✅ Tickets (SYSTEM) : TSV source global (historique cumulatif)
TICKETS_FILE = Path("data") / "tickets.tsv"

# ✅ Report humain (SYSTEM) : conservé pour compat IMPORT ailleurs
#    (écrit dans RUN_DIR si présent, sinon data/)
TICKETS_REPORT_FILE = _run_scoped_or_data("tickets_report.txt")

# ✅ Verdict tickets (historique cumulatif)
POST_TICKETS_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets.txt"
POST_TICKETS_FAILED_FILE = Path("data") / "post_tickets_failed.txt"

# ✅ Tickets (O15 RANDOM)
TICKETS_O15_FILE = Path("data") / "tickets_o15_random.tsv"

# ✅ Report humain (O15) : conservé pour compat IMPORT ailleurs
TICKETS_O15_REPORT_FILE = _run_scoped_or_data("tickets_o15_random_report.txt")

# ✅ Verdict tickets O15 (historique cumulatif)
POST_TICKETS_O15_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_o15_random.txt"
POST_TICKETS_O15_FAILED_FILE = Path("data") / "post_tickets_o15_random_failed.txt"

# ✅ Tickets (U35 RANDOM)
TICKETS_U35_FILE = Path("data") / "tickets_u35_random.tsv"

# ✅ Report humain (U35)
TICKETS_U35_REPORT_FILE = _run_scoped_or_data("tickets_u35_random_report.txt")

# ✅ Verdict tickets U35 (historique cumulatif)
POST_TICKETS_U35_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_u35_random.txt"
POST_TICKETS_U35_FAILED_FILE = Path("data") / "post_tickets_u35_random_failed.txt"

# ✅ Tickets (O15 SUPER RANDOM)
TICKETS_O15_SUPER_FILE = Path("data") / "tickets_o15_super_random.tsv"
TICKETS_O15_SUPER_REPORT_FILE = _run_scoped_or_data("tickets_o15_super_random_report.txt")
POST_TICKETS_O15_SUPER_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_o15_super_random.txt"
POST_TICKETS_O15_SUPER_FAILED_FILE = Path("data") / "post_tickets_o15_super_random_failed.txt"
TICKETS_O15_SUPER_REPORT_GLOBAL_FILE = Path("data") / "tickets_o15_super_random_report_global.txt"

# ✅ Tickets (U35 SUPER RANDOM)
TICKETS_U35_SUPER_FILE = Path("data") / "tickets_u35_super_random.tsv"
TICKETS_U35_SUPER_REPORT_FILE = _run_scoped_or_data("tickets_u35_super_random_report.txt")
POST_TICKETS_U35_SUPER_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_u35_super_random.txt"
POST_TICKETS_U35_SUPER_FAILED_FILE = Path("data") / "post_tickets_u35_super_random_failed.txt"
TICKETS_U35_SUPER_REPORT_GLOBAL_FILE = Path("data") / "tickets_u35_super_random_report_global.txt"

# ✅ Tickets (O25 RANDOM)
TICKETS_O25_FILE = Path("data") / "tickets_o25_random.tsv"
TICKETS_O25_REPORT_FILE = _run_scoped_or_data("tickets_o25_random_report.txt")
POST_TICKETS_O25_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_o25_random.txt"
POST_TICKETS_O25_FAILED_FILE = Path("data") / "post_tickets_o25_random_failed.txt"

# ✅ Tickets (O25 SUPER RANDOM)
TICKETS_O25_SUPER_FILE = Path("data") / "tickets_o25_super_random.tsv"
TICKETS_O25_SUPER_REPORT_FILE = _run_scoped_or_data("tickets_o25_super_random_report.txt")
POST_TICKETS_O25_SUPER_VERDICT_FILE = Path("data") / "verdict_post_analyse_tickets_o25_super_random.txt"
POST_TICKETS_O25_SUPER_FAILED_FILE = Path("data") / "post_tickets_o25_super_random_failed.txt"
TICKETS_O25_SUPER_REPORT_GLOBAL_FILE = Path("data") / "tickets_o25_super_random_report_global.txt"

# ✅ Report GLOBAL (historique) — c’est LA source whitelist tickets_id
TICKETS_REPORT_GLOBAL_FILE = Path("data") / "tickets_report_global.txt"
TICKETS_O15_REPORT_GLOBAL_FILE = Path("data") / "tickets_o15_random_report_global.txt"
TICKETS_U35_REPORT_GLOBAL_FILE = Path("data") / "tickets_u35_random_report_global.txt"
TICKETS_O25_REPORT_GLOBAL_FILE = Path("data") / "tickets_o25_random_report_global.txt"

# ==============================
# ✅ TRISKÈLE Rankings (historique cumulatif)
# ==============================

TRISKELE_RANKINGS_DIR = Path("data") / "rankings"
TRISKELE_RANKINGS_DIR.mkdir(parents=True, exist_ok=True)

TRISKELE_RANKING_LEAGUE_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_ranking_league_x_bet.tsv"
TRISKELE_RANKING_TEAM_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_ranking_team_x_bet.tsv"

# ✅ NOUVEAUX FICHIERS "GOALS"
TRISKELE_GOALS_LEAGUE_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_goals_league_x_bet.tsv"
TRISKELE_GOALS_TEAM_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_goals_team_x_bet.tsv"

# ✅ NOUVEAUX FICHIERS "COMPOSITE"
TRISKELE_COMPOSITE_LEAGUE_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_composite_league_x_bet.tsv"
TRISKELE_COMPOSITE_TEAM_BET_FILE = TRISKELE_RANKINGS_DIR / "triskele_composite_team_x_bet.tsv"

# ✅ Réglages pondération COMPOSITE
COMPOSITE_BASE_WEIGHT = 0.70
COMPOSITE_GOALS_WEIGHT = 0.30

# ✅ Réglages score GOALS (normalisation)
GOALS_FT_AVG_CAP = 3.20
GOALS_HT_AVG_CAP = 1.40
GOALS_TEAM_FOR_CAP = 2.00
GOALS_TEAM_TOTAL_CAP = 3.20
GOALS_DIFF_CAP = 1.50
GOALS_HT_DIFF_CAP = 1.00

# ticket_id attendu : 2026-01-25_1300_<10hex>[_SUFFIX]
_TICKET_ID_RE = re.compile(
    r"\bid=([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}_[0-9a-fA-F]{10}(?:_[A-Za-z0-9]+)?)\b"
)


def _load_ticket_ids_from_report_text(text: str) -> set[str]:
    out: set[str] = set()
    if not text:
        return out
    for line in text.splitlines():
        m = _TICKET_ID_RE.search(line)
        if m:
            out.add(m.group(1).strip())
    return out


def _load_ticket_ids_from_tickets_report(path: Optional[Path]) -> set[str]:
    """
    Extrait les ticket_id depuis un TicketsReport humain (ou None).
    Retourne un set vide si absent/illisible.
    """
    out: set[str] = set()
    if path is None:
        return out
    if not path.exists() or path.stat().st_size == 0:
        return out
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
        out |= _load_ticket_ids_from_report_text(txt)
    except Exception as e:
        print(f"⚠️ Impossible de lire TicketsReport ({path}) : {e}")
        return set()
    return out


# Clé "match-only" interne
MatchKey = Tuple[str, str, str, str]

# ==============================
# 0) Helpers
# ==============================

NON_PLAYED_STATUSES = {"PST", "CANC", "ABD", "SUSP", "TBD"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}  # conservé (compat / lecture future)

DATE_FUZZ_DAYS = 1


def _eval_to_emoji(code: str) -> str:
    return {
        "WIN": "✅",
        "LOSS": "❌",
        "PENDING": "⏳",
        "GOOD_NO_BET": "🟢",
        "BAD_NO_BET": "🟡",
    }.get((code or "").strip().upper(), "")


def _log_post_failed_match(date: str, league: str, home: str, away: str, reason: str) -> None:
    try:
        POST_MATCHES_FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with POST_MATCHES_FAILED_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{date} | {league} | {home} vs {away} | {reason}\n")
    except Exception as e:
        print(f"⚠️ Impossible d'écrire dans {POST_MATCHES_FAILED_FILE}: {e}")


def _log_post_failed_ticket(ticket_id: str, date: str, reason: str, *, failed_file: Path) -> None:
    try:
        failed_file.parent.mkdir(parents=True, exist_ok=True)
        with failed_file.open("a", encoding="utf-8") as f:
            f.write(f"{ticket_id}\t{date}\t{reason}\n")
    except Exception as e:
        print(f"⚠️ Impossible d'écrire dans {failed_file}: {e}")


def _extract_time(cols: List[str]) -> Optional[str]:
    if not cols:
        return None
    candidate = cols[-1].strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", candidate):
        return candidate
    return None


def _is_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (s or "").strip()))


def _is_int_str(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", (s or "").strip()))


def _is_playable_label(label: str) -> bool:
    if not label:
        return False
    lab = label.strip().upper()
    playable = {"FORT PLUS", "TRÈS FORT", "EXPLOSION", "MEGA EXPLOSION", "MAX"}
    return lab in playable


def _parse_iso_date(d_iso: str) -> Optional[str]:
    if not isinstance(d_iso, str):
        return None
    return d_iso[:10]


def _extract_halftime_score(fixture: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    score = fixture.get("score", {}) or {}
    ht = score.get("halftime", {}) or {}
    gh_ht = ht.get("home")
    ga_ht = ht.get("away")
    gh = gh_ht if isinstance(gh_ht, int) else None
    ga = ga_ht if isinstance(ga_ht, int) else None
    return gh, ga


def _as_date(s: str) -> Optional[date_cls]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _time_to_minutes(t: str) -> int:
    try:
        hh, mm = (t or "").split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 0


def _weekday_fr(date_str: str) -> str:
    try:
        y, m, d = map(int, (date_str or "").split("-"))
        wd = __import__("datetime").date(y, m, d).weekday()
        return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][wd]
    except Exception:
        return ""


# ==============================
# ✅ canonisation robuste (accents / ponctuation / espaces)
# ==============================


def _strip_accents(s: str) -> str:
    s2 = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s2 if not unicodedata.combining(ch))


def _canon_text(s: str) -> str:
    x = _strip_accents((s or "").strip().lower())
    x = re.sub(r"[\u2019']", "", x)
    x = re.sub(r"[^a-z0-9\s\-]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _canon_text(a), _canon_text(b)).ratio()


def _date_shift(date_str: str, delta_days: int) -> Optional[str]:
    d = _as_date(date_str)
    if d is None:
        return None
    return (d + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def _write_meta_heal_line(date: str, league: str, home: str, away: str, fixture: Dict[str, Any]) -> None:
    try:
        META_HEAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        fx = fixture.get("fixture", {}) or {}
        lg = fixture.get("league", {}) or {}
        th = (fixture.get("teams", {}) or {}).get("home", {}) or {}
        ta = (fixture.get("teams", {}) or {}).get("away", {}) or {}

        fid = fx.get("id")
        league_id = lg.get("id")
        home_id = th.get("id")
        away_id = ta.get("id")

        with META_HEAL_FILE.open("a", encoding="utf-8") as f:
            if META_HEAL_FILE.stat().st_size == 0:
                f.write("# date\tleague\thome\taway\tleague_id\thome_id\taway_id\tfixture_id\tfound_via\n")
            f.write(
                f"{date}\t{league}\t{home}\t{away}\t"
                f"{league_id or ''}\t{home_id or ''}\t{away_id or ''}\t{fid or ''}\tDATE_FALLBACK\n"
            )
    except Exception as e:
        print(f"⚠️ Impossible d'écrire meta heal : {e}")


# ==============================
# META ALL (global) : lookup fixture_id
# ==============================

_META_ALL_INDEX: Optional[Dict[Tuple[str, str, str, str], int]] = None


def _canon(s: str) -> str:
    return _canon_text(s)


def _load_meta_all_index() -> Dict[Tuple[str, str, str, str], int]:
    global _META_ALL_INDEX
    if _META_ALL_INDEX is not None:
        return _META_ALL_INDEX

    path = Path("data") / "matches_meta_all.tsv"
    idx: Dict[Tuple[str, str, str, str], int] = {}

    if not path.exists() or path.stat().st_size == 0:
        _META_ALL_INDEX = idx
        return idx

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                parts = raw.split("\t")
                if len(parts) < 8:
                    continue

                d = parts[0].strip()
                lg = parts[1].strip()
                h = parts[2].strip()
                a = parts[3].strip()
                fid = parts[-1].strip()

                if not _is_date(d):
                    continue
                if not fid or not _is_int_str(fid):
                    continue

                key = (_canon(d), _canon(lg), _canon(h), _canon(a))
                idx[key] = int(fid)
    except Exception as e:
        print(f"⚠️ Impossible de charger matches_meta_all.tsv : {e}")
        idx = {}

    _META_ALL_INDEX = idx
    return idx


def _get_fixture_id_from_meta_all(league: str, date: str, home: str, away: str) -> Optional[int]:
    idx = _load_meta_all_index()
    key = (_canon(date), _canon(league), _canon(home), _canon(away))
    return idx.get(key)


def _get_fixture_id_any_strict(league: str, date: str, home: str, away: str) -> Optional[int]:
    fid = get_fixture_id_from_meta(league, date, home, away)
    if fid is not None:
        try:
            return int(fid)
        except Exception:
            return None
    return _get_fixture_id_from_meta_all(league, date, home, away)


def _get_fixture_id_any_fuzzy(league: str, date: str, home: str, away: str) -> Tuple[Optional[int], str]:
    fid = _get_fixture_id_any_strict(league, date, home, away)
    if fid is not None:
        return fid, "EXACT"

    for dd in range(1, DATE_FUZZ_DAYS + 1):
        d1 = _date_shift(date, -dd)
        if d1:
            fid = _get_fixture_id_any_strict(league, d1, home, away)
            if fid is not None:
                return fid, f"DATE-{dd}"

        d2 = _date_shift(date, +dd)
        if d2:
            fid = _get_fixture_id_any_strict(league, d2, home, away)
            if fid is not None:
                return fid, f"DATE+{dd}"

    return None, "MISS"


# ==============================
# 1) Lecture d'une ligne TSV de prédiction (MULTI-PARIS)
# ==============================


def parse_prediction_line(line: str) -> Optional[Dict[str, Any]]:
    raw = line.strip()
    if not raw or not raw.startswith("TSV:"):
        return None

    content = raw[4:].lstrip()
    parts = content.split("\t")
    if len(parts) < 5:
        return None

    match_time = _extract_time(parts)

    # A) Nouveau format
    if len(parts) >= 11 and _is_date(parts[1]):
        match_id = parts[0].strip()
        date_str = parts[1].strip()
        league = parts[2].strip()
        home = parts[3].strip()
        away = parts[4].strip()
        bet_key = parts[5].strip().upper()

        metric = parts[6].strip() if len(parts) > 6 else ""
        score_raw = parts[7].strip() if len(parts) > 7 else ""
        label = parts[8].strip() if len(parts) > 8 else ""
        is_candidate_raw = parts[9].strip() if len(parts) > 9 else "0"
        comment = parts[10].strip() if len(parts) > 10 else ""

        score_val: Optional[float]
        try:
            score_val = float(score_raw.replace(",", "."))
        except Exception:
            score_val = None

        raw_ic = (is_candidate_raw or "").strip().lower()
        if raw_ic in ("1", "true", "yes", "y", "ok"):
            is_candidate = 1
        elif raw_ic in ("0", "false", "no", "n"):
            is_candidate = 0
        else:
            try:
                is_candidate = int(raw_ic)
            except Exception:
                is_candidate = 0

        return {
            "match_id": match_id,
            "date": date_str,
            "league": league,
            "home": home,
            "away": away,
            "bet_key": bet_key,
            "metric": metric,
            "label": label,
            "score": score_val,
            "is_candidate": is_candidate,
            "comment": comment,
            "time": match_time,
        }

    # B) Ancien format
    if _is_date(parts[0]):
        match_id = ""
        date_str = parts[0].strip()
        league = parts[1].strip() if len(parts) > 1 else ""
        home = parts[2].strip() if len(parts) > 2 else ""
        away = parts[3].strip() if len(parts) > 3 else ""
        bet_key = parts[4].strip().upper() if len(parts) > 4 else ""
        rest = parts[5:-1] if match_time else parts[5:]

        score_val: Optional[float] = None
        label: str = ""

        for x in rest:
            xs = (x or "").strip()
            if not xs:
                continue
            try:
                score_val = float(xs.replace(",", "."))
                break
            except Exception:
                continue

        for x in reversed(rest):
            xs = (x or "").strip()
            if not xs:
                continue
            if _is_date(xs) or re.fullmatch(r"\d{1,2}:\d{2}", xs):
                continue
            try:
                float(xs.replace(",", "."))
                continue
            except Exception:
                label = xs
                break

        return {
            "match_id": match_id,
            "date": date_str,
            "league": league,
            "home": home,
            "away": away,
            "bet_key": bet_key,
            "label": label,
            "score": score_val,
            "is_candidate": None,
            "comment": "",
            "time": match_time,
        }

    return None


# ==============================
# 1bis) Lecture d'une ligne TSV de ticket
# ==============================


def parse_ticket_line(line: str) -> Optional[Dict[str, Any]]:
    raw = (line or "").strip()
    if not raw or not raw.startswith("TSV:"):
        return None

    content = raw[4:].lstrip()
    parts = content.split("\t")
    if len(parts) < 15:
        return None

    ticket_id = parts[0].strip()
    d = parts[1].strip()
    if not _is_date(d):
        return None

    return {
        "ticket_id": ticket_id,
        "date": d,
        "start_time": parts[2].strip(),
        "end_time": parts[3].strip(),
        "code": parts[4].strip(),
        "total_odd": parts[5].strip(),
        "match_id": parts[6].strip(),
        "bet_key": parts[7].strip().upper(),
        "match_time": parts[8].strip(),
        "league": parts[9].strip(),
        "home": parts[10].strip(),
        "away": parts[11].strip(),
        "metric": parts[12].strip(),
        "label": parts[13].strip(),
        "odd": parts[14].strip(),
    }


def _load_existing_ticket_ids(path: Path) -> set[str]:
    """
    Compat : retourne l'ensemble des ticket_id présents dans le fichier verdict tickets.
    (On ne l'utilise PLUS comme condition de skip, car on veut “heal” les PENDING.)
    """
    out: set[str] = set()
    if not path.exists() or path.stat().st_size == 0:
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw.startswith("TSV:"):
                continue
            parts = raw[4:].lstrip().split("\t")
            if not parts:
                continue
            tid = parts[0].strip()
            if tid:
                out.add(tid)
    return out


FINAL_EVALS = {"WIN", "LOSS", "GOOD_NO_BET", "BAD_NO_BET"}
FINAL_TICKET_EVALS = {"WIN", "LOSS"}  # ticket-level final


def _load_ticket_verdict_latest_state(path: Path) -> Dict[str, str]:
    """
    Retourne l'état le plus récent par ticket_id dans verdict_post_analyse_tickets*.txt

    Important :
    - si un ticket est PENDING aujourd'hui et devient WIN/LOSS demain, on doit le retraiter
      sans demander de supprimer la ligne PENDING.
    - on “skip” uniquement si état final (WIN/LOSS).
    """
    out: Dict[str, str] = {}
    if not path.exists() or path.stat().st_size == 0:
        return out

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = (line or "").strip()
                if not raw.startswith("TSV:"):
                    continue
                parts = raw[4:].lstrip().split("\t")
                # TSV: ticket_id  ticket_no  date  start  end  code  total_odd  legs  wins  losses  eval
                if len(parts) < 11:
                    continue
                tid = parts[0].strip()
                ev = parts[10].strip().upper()
                if tid and ev:
                    out[tid] = ev  # dernier gagnant
    except Exception as e:
        print(f"⚠️ Impossible de charger états verdict tickets ({path}) : {e}")
        return {}

    return out


def _load_verdict_state(path: Path) -> Dict[Tuple[str, str], str]:
    """
    Index global verdicts (match-level) depuis data/verdict_post_analyse.txt
    => sert à éviter de recalculer des verdicts déjà FINALS, tout en laissant les PENDING se “heal”.
    """
    out: Dict[Tuple[str, str], str] = {}
    if not path.exists() or path.stat().st_size == 0:
        return out

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw.startswith("TSV:"):
                continue
            parts = raw[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue
            if not _is_date(parts[1].strip()):
                continue

            match_id = parts[0].strip()
            bet_key = parts[5].strip().upper()
            ev = parts[10].strip().upper()
            if match_id and bet_key and ev:
                out[(match_id, bet_key)] = ev
    return out


def _load_eval_index_from_post_verdict(path: Path) -> Dict[Tuple[str, str], str]:
    idx: Dict[Tuple[str, str], str] = {}
    if not path.exists() or path.stat().st_size == 0:
        return idx

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw.startswith("TSV:"):
                continue
            parts = raw[4:].lstrip().split("\t")
            if len(parts) >= 11 and _is_date(parts[1].strip()):
                match_id = parts[0].strip()
                bet_key = parts[5].strip().upper()
                ev = parts[10].strip().upper()
                if match_id and bet_key and ev:
                    idx[(match_id, bet_key)] = ev
    return idx


def _infer_ticket_numbers(headers_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    by_date: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for tid, h in headers_by_id.items():
        d = str(h.get("date") or "")
        by_date.setdefault(d, []).append((tid, h))

    out: Dict[str, int] = {}
    for d, items in by_date.items():
        items.sort(
            key=lambda it: (
                _time_to_minutes(str(it[1].get("start_time") or "")),
                _time_to_minutes(str(it[1].get("end_time") or "")),
                it[0],
            )
        )
        for i, (tid, _h) in enumerate(items, start=1):
            out[tid] = i

    return out


def _format_ticket_verdict_tsv(v: Dict[str, Any]) -> str:
    return (
        f"TSV: {v['ticket_id']}\t{v['ticket_no']}\t{v['date']}\t"
        f"{v.get('start_time','')}\t{v.get('end_time','')}\t"
        f"{v.get('code','')}\t{v.get('total_odd','')}\t"
        f"{v.get('legs',0)}\t{v.get('wins',0)}\t"
        f"{v.get('losses',0)}\t{v.get('eval','')}"
    )


# ==============================
# ✅ Résolution fixture robuste (ID verify + fallback date)
# ==============================


def _fixture_matches_expected(
    fx: Dict[str, Any],
    *,
    league: str,
    date: str,
    home: str,
    away: str,
) -> bool:
    fixture_info = fx.get("fixture", {}) or {}
    teams = fx.get("teams", {}) or {}
    league_info = fx.get("league", {}) or {}

    fx_date_iso = _parse_iso_date(str(fixture_info.get("date") or ""))
    if not fx_date_iso:
        return False

    d0 = _as_date(date)
    d1 = _as_date(fx_date_iso)
    if d0 is None or d1 is None:
        return False
    if abs((d1 - d0).days) > DATE_FUZZ_DAYS:
        return False

    api_home = ((teams.get("home") or {}) or {}).get("name") or ""
    api_away = ((teams.get("away") or {}) or {}).get("name") or ""

    if _similar(home, api_home) < 0.85:
        return False
    if _similar(away, api_away) < 0.85:
        return False

    api_league = str(league_info.get("name") or "")
    if api_league:
        if _similar(league, api_league) < 0.60 and (_canon_text(league) not in _canon_text(api_league)):
            return False

    return True


def _fetch_fixture_by_id_verified(
    fixture_id: int,
    *,
    league: str,
    date: str,
    home: str,
    away: str,
) -> Optional[Dict[str, Any]]:
    fixtures = _call_api("/fixtures", {"id": int(fixture_id)}) or []
    if not fixtures:
        return None

    fx = fixtures[0]
    if not _fixture_matches_expected(fx, league=league, date=date, home=home, away=away):
        return None

    return fx


def _search_fixture_by_date_fallback(
    *,
    league: str,
    date: str,
    home: str,
    away: str,
) -> Optional[Dict[str, Any]]:
    dates_to_try: List[str] = [date]
    for dd in range(1, DATE_FUZZ_DAYS + 1):
        d1 = _date_shift(date, -dd)
        d2 = _date_shift(date, +dd)
        if d1:
            dates_to_try.append(d1)
        if d2:
            dates_to_try.append(d2)

    for dtry in dates_to_try:
        fixtures = _call_api("/fixtures", {"date": dtry}) or []
        if not fixtures:
            continue

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0

        for fx in fixtures:
            teams = fx.get("teams", {}) or {}
            league_info = fx.get("league", {}) or {}
            api_home = ((teams.get("home") or {}) or {}).get("name") or ""
            api_away = ((teams.get("away") or {}) or {}).get("name") or ""
            api_league = str(league_info.get("name") or "")

            s1 = _similar(home, api_home)
            s2 = _similar(away, api_away)
            sl = _similar(league, api_league) if api_league else 0.5
            sc = (0.45 * s1) + (0.45 * s2) + (0.10 * sl)

            if sc > best_score:
                if s1 >= 0.85 and s2 >= 0.85:
                    best = fx
                    best_score = sc

        if best is not None:
            return best

    return None


# ==============================
# 2) Récupération résultat réel via l'API
# ==============================


def fetch_match_result(
    date: str,
    league: str,
    home: str,
    away: str,
    match_time: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    approx = f"{date}±{DATE_FUZZ_DAYS}j" if DATE_FUZZ_DAYS else date
    print(f"\n🔍 Collecte RÉSULTAT (ROBUST) : {home} vs {away} ({league}, date='{date}')")

    fixture_id, how = _get_fixture_id_any_fuzzy(league, date, home, away)
    print(f"[META] key≈({approx}, {league}, {home}, {away}) -> fixture_id={fixture_id} ({how})")

    chosen_fx: Optional[Dict[str, Any]] = None

    if fixture_id is not None:
        chosen_fx = _fetch_fixture_by_id_verified(
            int(fixture_id),
            league=league,
            date=date,
            home=home,
            away=away,
        )

        if chosen_fx is None:
            fixtures_raw = _call_api("/fixtures", {"id": int(fixture_id)}) or []
            if not fixtures_raw:
                print(f"❌ /fixtures?id={fixture_id} -> vide -> fallback date.")
            else:
                fi = fixtures_raw[0].get("fixture", {}) or {}
                teams = fixtures_raw[0].get("teams", {}) or {}
                ah = ((teams.get("home") or {}) or {}).get("name") or ""
                aa = ((teams.get("away") or {}) or {}).get("name") or ""
                ad = _parse_iso_date(str(fi.get("date") or "")) or "????-??-??"
                print(f"⚠️ fixture_id={fixture_id} mismatch -> API dit : {ah} vs {aa} ({ad}) -> fallback date.")

    if chosen_fx is None:
        chosen_fx = _search_fixture_by_date_fallback(league=league, date=date, home=home, away=away)
        if chosen_fx is None:
            print("❌ Impossible de retrouver le fixture (même via date fallback).")
            _log_post_failed_match(date, league, home, away, "FIXTURE_NOT_FOUND_ROBUST")
            return None

        try:
            _write_meta_heal_line(date, league, home, away, chosen_fx)
        except Exception as e:
            print(f"⚠️ [WARN] Écriture meta_heal échouée ({home} vs {away}) : {e}")

    fixture_info = chosen_fx.get("fixture", {}) or {}
    goals = chosen_fx.get("goals", {}) or {}
    status_info = fixture_info.get("status") or {}
    status_short = (status_info.get("short") or "").upper()

    if status_short in NON_PLAYED_STATUSES:
        print(f"⏸ Match non joué (status={status_short}) -> PENDING.")
        return {
            "fixture_id": fixture_info.get("id"),
            "date": date,
            "league": league,
            "home": home,
            "away": away,
            "status": status_short,
            "goals_home": None,
            "goals_away": None,
            "goals_home_ht": None,
            "goals_away_ht": None,
            "ht_total": None,
        }

    gh = goals.get("home")
    ga = goals.get("away")
    if gh is None or ga is None:
        fid2 = fixture_info.get("id")
        print("❌ GOALS manquants.")
        _log_post_failed_match(date, league, home, away, f"GOALS_MISSING:{fid2}")
        return None

    gh_ht, ga_ht = _extract_halftime_score(chosen_fx)
    ht_total = (gh_ht + ga_ht) if (gh_ht is not None and ga_ht is not None) else None

    fid_ok = fixture_info.get("id")
    print(f"✅ Résultat : fixture_id={fid_ok} : {home} {gh}-{ga} {away} ({status_short})")

    return {
        "fixture_id": fid_ok,
        "date": date,
        "league": league,
        "home": home,
        "away": away,
        "goals_home": int(gh),
        "goals_away": int(ga),
        "status": status_short,
        "goals_home_ht": gh_ht,
        "goals_away_ht": ga_ht,
        "ht_total": ht_total,
    }


# ==============================
# 3) Verdict multi-paris
# ==============================


def build_post_verdict(pred: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    bet_key = (pred.get("bet_key") or "").strip().upper()
    label = (pred.get("label") or "").strip()

    if pred.get("is_candidate") is None:
        played = _is_playable_label(label)
    else:
        played = bool(int(pred.get("is_candidate") or 0))

    status = (res.get("status") or "").strip().upper()

    if status in NON_PLAYED_STATUSES:
        return {
            "match_id": pred.get("match_id") or "",
            "metric": pred.get("metric") or "",
            "date": pred["date"],
            "league": pred["league"],
            "home": pred["home"],
            "away": pred["away"],
            "bet_key": bet_key,
            "label": label,
            "score": pred.get("score"),
            "played": False,
            "eval": "PENDING",
            "status": status,
            "match_time": pred.get("time") or "",
            "fixture_id": res.get("fixture_id") or "",
            "goals_home": None,
            "goals_away": None,
            "goals_home_ht": None,
            "goals_away_ht": None,
            "ht_total": None,
        }

    gh_ht = res.get("goals_home_ht")
    ga_ht = res.get("goals_away_ht")
    gh_ft = res.get("goals_home")
    ga_ft = res.get("goals_away")

    real_ok: Optional[bool] = None

    if bet_key == "HT05":
        if gh_ht is not None and ga_ht is not None:
            real_ok = (gh_ht + ga_ht) >= 1

    elif bet_key in ("HT1X_HOME", "HT1X", "HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        if gh_ht is not None and ga_ht is not None:
            real_ok = gh_ht >= ga_ht

    elif bet_key in ("TEAM1_SCORE_FT", "TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE"):
        if isinstance(gh_ft, int):
            real_ok = gh_ft >= 1

    elif bet_key in ("TEAM2_SCORE_FT", "TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE"):
        if isinstance(ga_ft, int):
            real_ok = ga_ft >= 1

    elif bet_key in (
        "O15_FT",
        "FT_OVER_1_5",
        "OVER15",
        "OVER_1_5",
        "O15",
        "FT_O15",
        "FT15",
        "FT_OVER15",
        "FT_OVER_1_5",
    ):
        if isinstance(gh_ft, int) and isinstance(ga_ft, int):
            real_ok = (gh_ft + ga_ft) >= 2

    elif bet_key in (
        "O25_FT",
        "FT_OVER_2_5",
        "OVER25",
        "OVER_2_5",
        "O25",
        "FT_O25",
        "FT25",
        "FT_OVER25",
        "FT_OVER_2_5",
    ):
        if isinstance(gh_ft, int) and isinstance(ga_ft, int):
            real_ok = (gh_ft + ga_ft) >= 3

    elif bet_key in (
        "U35_FT",
        "FT_UNDER_3_5",
        "UNDER35",
        "UNDER_3_5",
        "U35",
        "FT_U35",
        "FT_UNDER35",
    ):
        if isinstance(gh_ft, int) and isinstance(ga_ft, int):
            real_ok = (gh_ft + ga_ft) <= 3

    elif bet_key in ("TEAM1_WIN_FT", "TEAM1_WIN", "HOME_WIN", "T1_WIN"):
        if isinstance(gh_ft, int) and isinstance(ga_ft, int):
            real_ok = gh_ft > ga_ft

    elif bet_key in ("TEAM2_WIN_FT", "TEAM2_WIN", "AWAY_WIN", "T2_WIN"):
        if isinstance(gh_ft, int) and isinstance(ga_ft, int):
            real_ok = ga_ft > gh_ft

    if real_ok is None:
        eval_code = "BAD_NO_BET" if played else "GOOD_NO_BET"
    else:
        if played:
            eval_code = "WIN" if real_ok else "LOSS"
        else:
            eval_code = "BAD_NO_BET" if real_ok else "GOOD_NO_BET"

    return {
        "match_id": pred.get("match_id") or "",
        "metric": pred.get("metric") or "",
        "date": pred["date"],
        "league": pred["league"],
        "home": pred["home"],
        "away": pred["away"],
        "bet_key": bet_key,
        "label": label,
        "score": pred.get("score"),
        "played": played,
        "eval": eval_code,
        "status": status,
        "match_time": pred.get("time") or "",
        "fixture_id": res.get("fixture_id") or "",
        "goals_home": res.get("goals_home"),
        "goals_away": res.get("goals_away"),
        "goals_home_ht": gh_ht,
        "goals_away_ht": ga_ht,
    }


def format_result_tsv(res: Dict[str, Any]) -> str:
    gh_ht = res.get("goals_home_ht")
    ga_ht = res.get("goals_away_ht")
    ht_score = "" if gh_ht is None or ga_ht is None else f"{gh_ht}-{ga_ht}"

    gh = res.get("goals_home")
    ga = res.get("goals_away")
    ft_score = "" if gh is None or ga is None else f"{gh}-{ga}"

    return (
        f"TSV: {res['date']}\t{res['league']}\t{res['home']}\t{res['away']}\t"
        f"{res.get('fixture_id','')}\t"
        f"{ft_score}\t"
        f"{res.get('status','')}\t"
        f"{ht_score}"
    )


def format_post_verdict_tsv(v: Dict[str, Any]) -> str:
    match_id = str(v.get("match_id") or "")
    metric = str(v.get("metric") or "")
    label = str(v.get("label") or "")
    score = "" if v.get("score") is None else str(v["score"])

    played = "1" if v.get("played") else "0"
    eval_code = str(v.get("eval") or "")
    status = str(v.get("status") or "")
    fixture_id = str(v.get("fixture_id") or "")

    gh = v.get("goals_home")
    ga = v.get("goals_away")
    ft_score = "" if gh is None or ga is None else f"{gh}-{ga}"

    gh_ht = v.get("goals_home_ht")
    ga_ht = v.get("goals_away_ht")
    ht_score = "" if gh_ht is None or ga_ht is None else f"{gh_ht}-{ga_ht}"

    time_str = str(v.get("match_time") or "")

    return (
        f"TSV: {match_id}\t{v['date']}\t{v['league']}\t{v['home']}\t{v['away']}\t"
        f"{v['bet_key']}\t{metric}\t{score}\t{label}\t{played}\t"
        f"{eval_code}\t{status}\t{fixture_id}\t{ft_score}\t{ht_score}\t{time_str}"
    )


# ==============================
# ✅ 3ter) TRISKÈLE RANKINGS — génération depuis l'historique complet
# ==============================


def _safe_div(a: float, b: float) -> float:
    return (a / b) if b else 0.0


def _iter_global_played_decided_verdicts(global_verdict_path: Path):
    """
    NOUVELLE logique "baseline réalité" (sur tous les matchs analysés, pas seulement joués).

    On utilise le verdict match-level (data/verdict_post_analyse.txt).
    On ignore PENDING et tout ce qui est inconnu.

    Mapping:
      - SUCCESS = WIN + BAD_NO_BET   (le bet était vrai)
      - FAIL    = LOSS + GOOD_NO_BET (le bet était faux)
    """
    if not global_verdict_path.exists() or global_verdict_path.stat().st_size == 0:
        return

    SUCCESS = {"WIN", "BAD_NO_BET"}
    FAIL = {"LOSS", "GOOD_NO_BET"}
    ALLOWED = SUCCESS | FAIL

    with global_verdict_path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw.startswith("TSV:"):
                continue

            parts = raw[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue
            if not _is_date(parts[1].strip()):
                continue

            date_str = parts[1].strip()
            league = parts[2].strip()
            home = parts[3].strip()
            away = parts[4].strip()
            bet_key = parts[5].strip().upper()

            ev = parts[10].strip().upper()
            if ev not in ALLOWED:
                continue

            outcome = "SUCCESS" if ev in SUCCESS else "FAIL"

            yield {
                "date": date_str,
                "league": league,
                "home": home,
                "away": away,
                "bet_key": bet_key,
                "outcome": outcome,  # "SUCCESS" ou "FAIL"
            }
            

def _team_targets_for_bet(home: str, away: str, bet_key: str) -> list[str]:
    """
    Détermine quelles équipes sont "responsables" du bet pour le ranking TEAM.

    - Bets "global match" (ex: O15_FT, HT05) -> home + away
    - Bets TEAM1_* -> home uniquement
    - Bets TEAM2_* -> away uniquement
    - HT1X_HOME -> home uniquement
    """
    bk = (bet_key or "").strip().upper()

    # Bets 2 équipes / match-level
    if bk in (
        "O15_FT",
        "FT_OVER_1_5",
        "OVER15",
        "OVER_1_5",
        "O15",
        "FT_O15",
        "FT15",
        "FT_OVER15",
        "FT_OVER_1_5",
        "O25_FT",
        "FT_OVER_2_5",
        "OVER25",
        "OVER_2_5",
        "O25",
        "FT_O25",
        "FT25",
        "FT_OVER25",
        "U35_FT",
        "FT_UNDER_3_5",
        "UNDER35",
        "UNDER_3_5",
        "U35",
        "FT_U35",
        "FT_UNDER35",
    ):
        return [home, away]

    if bk == "HT05":
        return [home, away]

    # Double chance MT sur HOME
    if bk in ("HT1X_HOME", "HT1X", "HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        return [home]

    # Team1 / Team2
    if bk in ("TEAM1_SCORE_FT", "TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE"):
        return [home]
    if bk in ("TEAM2_SCORE_FT", "TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE"):
        return [away]

    if bk in ("TEAM1_WIN_FT", "TEAM1_WIN", "HOME_WIN", "T1_WIN"):
        return [home]
    if bk in ("TEAM2_WIN_FT", "TEAM2_WIN", "AWAY_WIN", "T2_WIN"):
        return [away]

    # Par défaut (si un nouveau bet comprend 2 équipes)
    return [home, away]   


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _norm_cap(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return _clamp01(float(value) / float(cap))


def _safe_rate(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def _composite_score(base_rate: float, goals_score: float) -> float:
    return _clamp01(
        (float(COMPOSITE_BASE_WEIGHT) * float(base_rate))
        + (float(COMPOSITE_GOALS_WEIGHT) * float(goals_score))
    )


def _goal_score_league_from_stats(bet_key: str, s: Dict[str, float]) -> float:
    bk = (bet_key or "").strip().upper()

    avg_ft = _safe_rate(s.get("ft_goals_sum", 0.0), s.get("matches", 0.0))
    avg_ht = _safe_rate(s.get("ht_goals_sum", 0.0), s.get("ht_matches", 0.0))

    home_avg = _safe_rate(s.get("home_goals_sum", 0.0), s.get("matches", 0.0))
    away_avg = _safe_rate(s.get("away_goals_sum", 0.0), s.get("matches", 0.0))

    home_ht_avg = _safe_rate(s.get("home_ht_goals_sum", 0.0), s.get("ht_matches", 0.0))
    away_ht_avg = _safe_rate(s.get("away_ht_goals_sum", 0.0), s.get("ht_matches", 0.0))

    o15_rate = _safe_rate(s.get("o15_hits", 0.0), s.get("matches", 0.0))
    ht05_rate = _safe_rate(s.get("ht05_hits", 0.0), s.get("ht_matches", 0.0))

    home_scored_rate = _safe_rate(s.get("home_scored_hits", 0.0), s.get("matches", 0.0))
    away_scored_rate = _safe_rate(s.get("away_scored_hits", 0.0), s.get("matches", 0.0))

    home_win_rate = _safe_rate(s.get("home_win_hits", 0.0), s.get("matches", 0.0))
    away_win_rate = _safe_rate(s.get("away_win_hits", 0.0), s.get("matches", 0.0))

    ht1x_home_rate = _safe_rate(s.get("ht1x_home_hits", 0.0), s.get("ht_matches", 0.0))

    ft_avg_norm = _norm_cap(avg_ft, GOALS_FT_AVG_CAP)
    ht_avg_norm = _norm_cap(avg_ht, GOALS_HT_AVG_CAP)
    home_avg_norm = _norm_cap(home_avg, GOALS_TEAM_FOR_CAP)
    away_avg_norm = _norm_cap(away_avg, GOALS_TEAM_FOR_CAP)

    home_edge_norm = _clamp01((home_avg - away_avg + GOALS_DIFF_CAP) / (2.0 * GOALS_DIFF_CAP))
    away_edge_norm = _clamp01((away_avg - home_avg + GOALS_DIFF_CAP) / (2.0 * GOALS_DIFF_CAP))

    home_ht_edge_norm = _clamp01((home_ht_avg - away_ht_avg + GOALS_HT_DIFF_CAP) / (2.0 * GOALS_HT_DIFF_CAP))

    if bk == "O15_FT":
        return _clamp01((0.65 * o15_rate) + (0.35 * ft_avg_norm))

    if bk == "HT05":
        return _clamp01((0.65 * ht05_rate) + (0.35 * ht_avg_norm))

    if bk == "TEAM1_SCORE_FT":
        return _clamp01((0.60 * home_scored_rate) + (0.25 * home_avg_norm) + (0.15 * ft_avg_norm))

    if bk == "TEAM2_SCORE_FT":
        return _clamp01((0.60 * away_scored_rate) + (0.25 * away_avg_norm) + (0.15 * ft_avg_norm))

    if bk == "TEAM1_WIN_FT":
        return _clamp01((0.55 * home_win_rate) + (0.30 * home_edge_norm) + (0.15 * home_scored_rate))

    if bk == "TEAM2_WIN_FT":
        return _clamp01((0.55 * away_win_rate) + (0.30 * away_edge_norm) + (0.15 * away_scored_rate))

    if bk == "HT1X_HOME":
        return _clamp01((0.60 * ht1x_home_rate) + (0.25 * home_ht_edge_norm) + (0.15 * ht05_rate))

    return 0.50


def _goal_score_team_from_stats(bet_key: str, s: Dict[str, float]) -> float:
    bk = (bet_key or "").strip().upper()

    matches = s.get("matches", 0.0)
    ht_matches = s.get("ht_matches", 0.0)

    avg_for = _safe_rate(s.get("goals_for_sum", 0.0), matches)
    avg_against = _safe_rate(s.get("goals_against_sum", 0.0), matches)
    avg_total = _safe_rate(s.get("goals_total_sum", 0.0), matches)

    avg_ht_for = _safe_rate(s.get("ht_goals_for_sum", 0.0), ht_matches)
    avg_ht_against = _safe_rate(s.get("ht_goals_against_sum", 0.0), ht_matches)
    avg_ht_total = _safe_rate(s.get("ht_goals_total_sum", 0.0), ht_matches)

    scored_rate = _safe_rate(s.get("scored_hits", 0.0), matches)
    win_rate = _safe_rate(s.get("win_hits", 0.0), matches)
    o15_rate = _safe_rate(s.get("o15_hits", 0.0), matches)

    ht05_rate = _safe_rate(s.get("ht05_hits", 0.0), ht_matches)
    ht1x_rate = _safe_rate(s.get("ht1x_hits", 0.0), ht_matches)

    avg_for_norm = _norm_cap(avg_for, GOALS_TEAM_FOR_CAP)
    avg_total_norm = _norm_cap(avg_total, GOALS_TEAM_TOTAL_CAP)
    avg_ht_total_norm = _norm_cap(avg_ht_total, GOALS_HT_AVG_CAP)

    diff_norm = _clamp01((avg_for - avg_against + GOALS_DIFF_CAP) / (2.0 * GOALS_DIFF_CAP))
    ht_diff_norm = _clamp01((avg_ht_for - avg_ht_against + GOALS_HT_DIFF_CAP) / (2.0 * GOALS_HT_DIFF_CAP))

    if bk == "O15_FT":
        return _clamp01((0.60 * o15_rate) + (0.25 * avg_total_norm) + (0.15 * scored_rate))

    if bk == "HT05":
        return _clamp01((0.60 * ht05_rate) + (0.25 * avg_ht_total_norm) + (0.15 * ht1x_rate))

    if bk in ("TEAM1_SCORE_FT", "TEAM2_SCORE_FT"):
        return _clamp01((0.60 * scored_rate) + (0.25 * avg_for_norm) + (0.15 * o15_rate))

    if bk in ("TEAM1_WIN_FT", "TEAM2_WIN_FT"):
        return _clamp01((0.55 * win_rate) + (0.30 * diff_norm) + (0.15 * scored_rate))

    if bk == "HT1X_HOME":
        return _clamp01((0.60 * ht1x_rate) + (0.25 * ht_diff_norm) + (0.15 * ht05_rate))

    return 0.50


def _make_empty_league_goal_stats() -> Dict[str, float]:
    return {
        # volumes
        "matches": 0.0,
        "ht_matches": 0.0,

        # sommes buts
        "ft_goals_sum": 0.0,
        "ht_goals_sum": 0.0,
        "home_goals_sum": 0.0,
        "away_goals_sum": 0.0,
        "home_ht_goals_sum": 0.0,
        "away_ht_goals_sum": 0.0,

        # distributions FT total buts
        "ft_total_0": 0.0,
        "ft_total_1": 0.0,
        "ft_total_2": 0.0,
        "ft_total_3": 0.0,
        "ft_total_4_plus": 0.0,

        # distributions HT total buts
        "ht_total_0": 0.0,
        "ht_total_1": 0.0,
        "ht_total_2_plus": 0.0,

        # hits FT
        "o05_hits": 0.0,
        "o15_hits": 0.0,
        "o25_hits": 0.0,
        "o35_hits": 0.0,
        "exact_2_hits": 0.0,
        "exact_3_hits": 0.0,

        # équipes marquent / BTTS
        "home_scored_hits": 0.0,
        "away_scored_hits": 0.0,
        "btts_hits": 0.0,

        # issues FT
        "home_win_hits": 0.0,
        "draw_hits": 0.0,
        "away_win_hits": 0.0,

        # hits HT
        "ht05_hits": 0.0,
        "ht15_hits": 0.0,
        "ht_home_lead_hits": 0.0,
        "ht_draw_hits": 0.0,
        "ht_away_lead_hits": 0.0,
        "ht1x_home_hits": 0.0,
    }


def _make_empty_team_goal_stats() -> Dict[str, float]:
    return {
        # volumes
        "matches": 0.0,
        "ht_matches": 0.0,

        # sommes
        "goals_for_sum": 0.0,
        "goals_against_sum": 0.0,
        "goals_total_sum": 0.0,
        "ht_goals_for_sum": 0.0,
        "ht_goals_against_sum": 0.0,
        "ht_goals_total_sum": 0.0,

        # distributions buts marqués par l’équipe
        "gf_0": 0.0,
        "gf_1": 0.0,
        "gf_2": 0.0,
        "gf_3_plus": 0.0,

        # distributions total buts du match
        "total_0": 0.0,
        "total_1": 0.0,
        "total_2": 0.0,
        "total_3": 0.0,
        "total_4_plus": 0.0,

        # hits équipe
        "scored_hits": 0.0,
        "conceded_hits": 0.0,
        "clean_sheet_hits": 0.0,
        "failed_to_score_hits": 0.0,

        # issues FT
        "win_hits": 0.0,
        "draw_hits": 0.0,
        "loss_hits": 0.0,

        # hits match FT
        "o15_hits": 0.0,
        "o25_hits": 0.0,
        "o35_hits": 0.0,
        "exact_2_hits": 0.0,
        "exact_3_hits": 0.0,

        # hits HT
        "ht05_hits": 0.0,
        "ht15_hits": 0.0,
        "ht_lead_hits": 0.0,
        "ht_draw_hits": 0.0,
        "ht_trail_hits": 0.0,
        "ht1x_hits": 0.0,
    }


def update_triskele_rankings_from_history() -> None:
    """
    Recalcule :

    1) triskele_ranking_league_x_bet.tsv
    2) triskele_ranking_team_x_bet.tsv
    3) triskele_goals_league_x_bet.tsv
    4) triskele_goals_team_x_bet.tsv
    5) triskele_composite_league_x_bet.tsv
    6) triskele_composite_team_x_bet.tsv

    Source vérité = data/results.tsv
    """

    results_path = Path("data") / "results.tsv"
    if not results_path.exists() or results_path.stat().st_size == 0:
        print("ℹ️ [RANKINGS] Aucun results.tsv (data/results.tsv) -> rankings ignorés.")
        return

    league_bet: Dict[Tuple[str, str], Dict[str, int]] = {}
    team_bet: Dict[Tuple[str, str, str], Dict[str, int]] = {}

    league_goal_stats: Dict[str, Dict[str, float]] = {}
    team_goal_stats: Dict[Tuple[str, str, str], Dict[str, float]] = {}

    matches: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    def _parse_score(score: str) -> Tuple[Optional[int], Optional[int]]:
        s = (score or "").strip()
        if not s or "-" not in s:
            return None, None
        try:
            a, b = s.split("-", 1)
            return int(a), int(b)
        except Exception:
            return None, None

    # -------------------------------------------------
    # 1) Charger les matchs
    # -------------------------------------------------
    with results_path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw.startswith("TSV:"):
                continue

            parts = raw[4:].lstrip().split("\t")
            if len(parts) < 8:
                continue

            date_str = parts[0].strip()
            league = parts[1].strip()
            home = parts[2].strip()
            away = parts[3].strip()
            fixture_id = parts[4].strip()
            ft_score = parts[5].strip()
            status = parts[6].strip()
            ht_score = parts[7].strip() if len(parts) >= 8 else ""

            if not _is_date(date_str):
                continue

            gh, ga = _parse_score(ft_score)
            if gh is None or ga is None:
                continue

            gh_ht, ga_ht = _parse_score(ht_score) if ht_score else (None, None)

            if fixture_id and _is_int_str(fixture_id):
                key = ("FID", fixture_id, "", "")
            else:
                key = (date_str, league, home, away)

            matches[key] = {
                "date": date_str,
                "league": league,
                "home": home,
                "away": away,
                "fixture_id": fixture_id,
                "status": status,
                "gh": gh,
                "ga": ga,
                "gh_ht": gh_ht,
                "ga_ht": ga_ht,
            }

    if not matches:
        print("ℹ️ [RANKINGS] Aucun match exploitable dans results.tsv.")
        return

    # -------------------------------------------------
    # 2) Calcul baseline bet + goal stats
    # -------------------------------------------------
    for m in matches.values():
        league = m["league"]
        home = m["home"]
        away = m["away"]
        gh = m["gh"]
        ga = m["ga"]
        gh_ht = m.get("gh_ht")
        ga_ht = m.get("ga_ht")

        ft_total = gh + ga

        # ---------------- LEAGUE GOAL STATS ----------------
        lg = league_goal_stats.setdefault(league, _make_empty_league_goal_stats())

        lg["matches"] += 1
        lg["ft_goals_sum"] += ft_total
        lg["home_goals_sum"] += gh
        lg["away_goals_sum"] += ga

        # distribution FT
        if ft_total == 0:
            lg["ft_total_0"] += 1
        elif ft_total == 1:
            lg["ft_total_1"] += 1
        elif ft_total == 2:
            lg["ft_total_2"] += 1
        elif ft_total == 3:
            lg["ft_total_3"] += 1
        else:
            lg["ft_total_4_plus"] += 1

        # hits FT
        lg["o05_hits"] += 1 if ft_total >= 1 else 0
        lg["o15_hits"] += 1 if ft_total >= 2 else 0
        lg["o25_hits"] += 1 if ft_total >= 3 else 0
        lg["o35_hits"] += 1 if ft_total >= 4 else 0
        lg["exact_2_hits"] += 1 if ft_total == 2 else 0
        lg["exact_3_hits"] += 1 if ft_total == 3 else 0

        # équipes / BTTS
        lg["home_scored_hits"] += 1 if gh >= 1 else 0
        lg["away_scored_hits"] += 1 if ga >= 1 else 0
        lg["btts_hits"] += 1 if (gh >= 1 and ga >= 1) else 0

        # issues FT
        lg["home_win_hits"] += 1 if gh > ga else 0
        lg["draw_hits"] += 1 if gh == ga else 0
        lg["away_win_hits"] += 1 if ga > gh else 0

        # HT
        if gh_ht is not None and ga_ht is not None:
            ht_total = gh_ht + ga_ht

            lg["ht_matches"] += 1
            lg["ht_goals_sum"] += ht_total
            lg["home_ht_goals_sum"] += gh_ht
            lg["away_ht_goals_sum"] += ga_ht

            if ht_total == 0:
                lg["ht_total_0"] += 1
            elif ht_total == 1:
                lg["ht_total_1"] += 1
            else:
                lg["ht_total_2_plus"] += 1

            lg["ht05_hits"] += 1 if ht_total >= 1 else 0
            lg["ht15_hits"] += 1 if ht_total >= 2 else 0
            lg["ht_home_lead_hits"] += 1 if gh_ht > ga_ht else 0
            lg["ht_draw_hits"] += 1 if gh_ht == ga_ht else 0
            lg["ht_away_lead_hits"] += 1 if ga_ht > gh_ht else 0
            lg["ht1x_home_hits"] += 1 if gh_ht >= ga_ht else 0

        # ---------------- BET BASELINES ----------------
        bet_results: Dict[str, Optional[bool]] = {}

        bet_results["O15_FT"] = ft_total >= 2
        bet_results["O25_FT"] = ft_total >= 3
        bet_results["U35_FT"] = ft_total <= 3
        bet_results["TEAM1_SCORE_FT"] = gh >= 1
        bet_results["TEAM2_SCORE_FT"] = ga >= 1
        bet_results["TEAM1_WIN_FT"] = gh > ga
        bet_results["TEAM2_WIN_FT"] = ga > gh

        if gh_ht is not None and ga_ht is not None:
            bet_results["HT05"] = (gh_ht + ga_ht) >= 1
            bet_results["HT1X_HOME"] = gh_ht >= ga_ht
        else:
            bet_results["HT05"] = None
            bet_results["HT1X_HOME"] = None

        for bet_key, ok in bet_results.items():
            if ok is None:
                continue

            lk = (league, bet_key)
            league_bet.setdefault(lk, {"samples": 0, "success": 0})
            league_bet[lk]["samples"] += 1
            if ok:
                league_bet[lk]["success"] += 1

            targets = _team_targets_for_bet(home, away, bet_key)
            for team in targets:
                tk = (league, team, bet_key)
                team_bet.setdefault(tk, {"samples": 0, "success": 0})
                team_bet[tk]["samples"] += 1
                if ok:
                    team_bet[tk]["success"] += 1

        # ---------------- TEAM GOAL STATS helper ----------------
        def _update_team_goal_stats(team_name: str, bet_key: str, gf: int, ga2: int, ghf_ht: Optional[int], gaf_ht: Optional[int]) -> None:
            st = team_goal_stats.setdefault((league, team_name, bet_key), _make_empty_team_goal_stats())

            total = gf + ga2
            st["matches"] += 1
            st["goals_for_sum"] += gf
            st["goals_against_sum"] += ga2
            st["goals_total_sum"] += total

            # distribution buts marqués équipe
            if gf == 0:
                st["gf_0"] += 1
            elif gf == 1:
                st["gf_1"] += 1
            elif gf == 2:
                st["gf_2"] += 1
            else:
                st["gf_3_plus"] += 1

            # distribution total match
            if total == 0:
                st["total_0"] += 1
            elif total == 1:
                st["total_1"] += 1
            elif total == 2:
                st["total_2"] += 1
            elif total == 3:
                st["total_3"] += 1
            else:
                st["total_4_plus"] += 1

            # hits équipe / match
            st["scored_hits"] += 1 if gf >= 1 else 0
            st["conceded_hits"] += 1 if ga2 >= 1 else 0
            st["clean_sheet_hits"] += 1 if ga2 == 0 else 0
            st["failed_to_score_hits"] += 1 if gf == 0 else 0

            st["win_hits"] += 1 if gf > ga2 else 0
            st["draw_hits"] += 1 if gf == ga2 else 0
            st["loss_hits"] += 1 if gf < ga2 else 0

            st["o15_hits"] += 1 if total >= 2 else 0
            st["o25_hits"] += 1 if total >= 3 else 0
            st["o35_hits"] += 1 if total >= 4 else 0
            st["exact_2_hits"] += 1 if total == 2 else 0
            st["exact_3_hits"] += 1 if total == 3 else 0

            if ghf_ht is not None and gaf_ht is not None:
                ht_total = ghf_ht + gaf_ht
                st["ht_matches"] += 1
                st["ht_goals_for_sum"] += ghf_ht
                st["ht_goals_against_sum"] += gaf_ht
                st["ht_goals_total_sum"] += ht_total
                st["ht05_hits"] += 1 if ht_total >= 1 else 0
                st["ht15_hits"] += 1 if ht_total >= 2 else 0
                st["ht_lead_hits"] += 1 if ghf_ht > gaf_ht else 0
                st["ht_draw_hits"] += 1 if ghf_ht == gaf_ht else 0
                st["ht_trail_hits"] += 1 if ghf_ht < gaf_ht else 0
                st["ht1x_hits"] += 1 if ghf_ht >= gaf_ht else 0

        # Bets match-level => home + away
        for team_name, gf, ga2, ghf_ht, gaf_ht in [
            (home, gh, ga, gh_ht, ga_ht),
            (away, ga, gh, ga_ht, gh_ht),
        ]:
            _update_team_goal_stats(team_name, "O15_FT", gf, ga2, ghf_ht, gaf_ht)
            if ghf_ht is not None and gaf_ht is not None:
                _update_team_goal_stats(team_name, "HT05", gf, ga2, ghf_ht, gaf_ht)

        # Home-specific
        _update_team_goal_stats(home, "TEAM1_SCORE_FT", gh, ga, gh_ht, ga_ht)
        _update_team_goal_stats(home, "TEAM1_WIN_FT", gh, ga, gh_ht, ga_ht)
        if gh_ht is not None and ga_ht is not None:
            _update_team_goal_stats(home, "HT1X_HOME", gh, ga, gh_ht, ga_ht)

        # Away-specific
        _update_team_goal_stats(away, "TEAM2_SCORE_FT", ga, gh, ga_ht, gh_ht)
        _update_team_goal_stats(away, "TEAM2_WIN_FT", ga, gh, ga_ht, gh_ht)

    # -------------------------------------------------
    # 3) WRITE baseline rankings (DETAILLED)
    # -------------------------------------------------
    TRISKELE_RANKINGS_DIR.mkdir(parents=True, exist_ok=True)

    with TRISKELE_RANKING_LEAGUE_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tbet_key\tsamples\tsuccess\tfail\tsuccess_rate\t"
            "matches\tht_matches\tavg_ft_goals\tavg_ht_goals\t"
            "goals_0\tgoals_1\tgoals_2\tgoals_3\tgoals_4_plus\t"
            "rate_o05_ft\trate_o15_ft\trate_o25_ft\trate_o35_ft\t"
            "rate_exact_2\trate_exact_3\t"
            "home_scored_rate\taway_scored_rate\tbtts_rate\t"
            "home_win_rate\tdraw_rate\taway_win_rate\t"
            "rate_ht05\trate_ht15\t"
            "rate_ht_home_lead\trate_ht_draw\trate_ht_away_lead\trate_ht1x_home\n"
        )

        rows = []
        for (league, bet_key), agg in league_bet.items():
            s = agg["samples"]
            w = agg["success"]
            fail = s - w
            sr = (w / s) if s else 0.0

            lg = league_goal_stats.get(league, _make_empty_league_goal_stats())
            matches_n = int(lg.get("matches", 0))
            ht_matches_n = int(lg.get("ht_matches", 0))

            avg_ft_goals = _safe_rate(lg.get("ft_goals_sum", 0.0), matches_n)
            avg_ht_goals = _safe_rate(lg.get("ht_goals_sum", 0.0), ht_matches_n)

            rows.append((
                sr,
                s,
                league,
                bet_key,
                w,
                fail,
                matches_n,
                ht_matches_n,
                avg_ft_goals,
                avg_ht_goals,
                int(lg.get("ft_total_0", 0)),
                int(lg.get("ft_total_1", 0)),
                int(lg.get("ft_total_2", 0)),
                int(lg.get("ft_total_3", 0)),
                int(lg.get("ft_total_4_plus", 0)),
                _safe_rate(lg.get("o05_hits", 0.0), matches_n),
                _safe_rate(lg.get("o15_hits", 0.0), matches_n),
                _safe_rate(lg.get("o25_hits", 0.0), matches_n),
                _safe_rate(lg.get("o35_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("btts_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("draw_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_home_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_away_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht1x_home_hits", 0.0), ht_matches_n),
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))

        for row in rows:
            (
                sr, s, league, bet_key, w, fail,
                matches_n, ht_matches_n, avg_ft_goals, avg_ht_goals,
                g0, g1, g2, g3, g4p,
                r_o05, r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_home_sc, r_away_sc, r_btts,
                r_hw, r_dr, r_aw,
                r_ht05, r_ht15, r_ht_hlead, r_ht_draw, r_ht_alead, r_ht1x
            ) = row

            f.write(
                f"{league}\t{bet_key}\t{s}\t{w}\t{fail}\t{sr:.6f}\t"
                f"{matches_n}\t{ht_matches_n}\t{avg_ft_goals:.6f}\t{avg_ht_goals:.6f}\t"
                f"{g0}\t{g1}\t{g2}\t{g3}\t{g4p}\t"
                f"{r_o05:.6f}\t{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_home_sc:.6f}\t{r_away_sc:.6f}\t{r_btts:.6f}\t"
                f"{r_hw:.6f}\t{r_dr:.6f}\t{r_aw:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t"
                f"{r_ht_hlead:.6f}\t{r_ht_draw:.6f}\t{r_ht_alead:.6f}\t{r_ht1x:.6f}\n"
            )

    with TRISKELE_RANKING_TEAM_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tteam\tbet_key\tsamples\tsuccess\tfail\tsuccess_rate\t"
            "matches\tht_matches\t"
            "avg_goals_for\tavg_goals_against\tavg_goals_total\t"
            "avg_ht_goals_for\tavg_ht_goals_against\tavg_ht_goals_total\t"
            "goals_for_0\tgoals_for_1\tgoals_for_2\tgoals_for_3_plus\t"
            "total_0\ttotal_1\ttotal_2\ttotal_3\ttotal_4_plus\t"
            "rate_scored\trate_conceded\trate_clean_sheet\trate_failed_to_score\t"
            "rate_win\trate_draw\trate_loss\t"
            "rate_o15_match\trate_o25_match\trate_o35_match\t"
            "rate_exact_2_match\trate_exact_3_match\t"
            "rate_ht05_match\trate_ht15_match\trate_ht_lead\trate_ht_draw\trate_ht_trail\trate_ht1x\n"
        )

        rows = []
        for (league, team, bet_key), agg in team_bet.items():
            s = agg["samples"]
            w = agg["success"]
            fail = s - w
            sr = (w / s) if s else 0.0

            tg = team_goal_stats.get((league, team, bet_key), _make_empty_team_goal_stats())
            matches_n = int(tg.get("matches", 0))
            ht_matches_n = int(tg.get("ht_matches", 0))

            rows.append((
                sr,
                s,
                league,
                team,
                bet_key,
                w,
                fail,
                matches_n,
                ht_matches_n,
                _safe_rate(tg.get("goals_for_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_against_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_total_sum", 0.0), matches_n),
                _safe_rate(tg.get("ht_goals_for_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_against_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_total_sum", 0.0), ht_matches_n),
                int(tg.get("gf_0", 0)),
                int(tg.get("gf_1", 0)),
                int(tg.get("gf_2", 0)),
                int(tg.get("gf_3_plus", 0)),
                int(tg.get("total_0", 0)),
                int(tg.get("total_1", 0)),
                int(tg.get("total_2", 0)),
                int(tg.get("total_3", 0)),
                int(tg.get("total_4_plus", 0)),
                _safe_rate(tg.get("scored_hits", 0.0), matches_n),
                _safe_rate(tg.get("conceded_hits", 0.0), matches_n),
                _safe_rate(tg.get("clean_sheet_hits", 0.0), matches_n),
                _safe_rate(tg.get("failed_to_score_hits", 0.0), matches_n),
                _safe_rate(tg.get("win_hits", 0.0), matches_n),
                _safe_rate(tg.get("draw_hits", 0.0), matches_n),
                _safe_rate(tg.get("loss_hits", 0.0), matches_n),
                _safe_rate(tg.get("o15_hits", 0.0), matches_n),
                _safe_rate(tg.get("o25_hits", 0.0), matches_n),
                _safe_rate(tg.get("o35_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(tg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_lead_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_trail_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht1x_hits", 0.0), ht_matches_n),
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3], x[4]))

        for row in rows:
            (
                sr, s, league, team, bet_key, w, fail,
                matches_n, ht_matches_n,
                avg_gf, avg_ga, avg_gt,
                avg_ht_gf, avg_ht_ga, avg_ht_gt,
                gf0, gf1, gf2, gf3p,
                t0, t1, t2, t3, t4p,
                r_scored, r_conceded, r_cs, r_fts,
                r_win, r_draw, r_loss,
                r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_ht05, r_ht15, r_ht_lead, r_ht_draw, r_ht_trail, r_ht1x
            ) = row

            f.write(
                f"{league}\t{team}\t{bet_key}\t{s}\t{w}\t{fail}\t{sr:.6f}\t"
                f"{matches_n}\t{ht_matches_n}\t"
                f"{avg_gf:.6f}\t{avg_ga:.6f}\t{avg_gt:.6f}\t"
                f"{avg_ht_gf:.6f}\t{avg_ht_ga:.6f}\t{avg_ht_gt:.6f}\t"
                f"{gf0}\t{gf1}\t{gf2}\t{gf3p}\t"
                f"{t0}\t{t1}\t{t2}\t{t3}\t{t4p}\t"
                f"{r_scored:.6f}\t{r_conceded:.6f}\t{r_cs:.6f}\t{r_fts:.6f}\t"
                f"{r_win:.6f}\t{r_draw:.6f}\t{r_loss:.6f}\t"
                f"{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t{r_ht_lead:.6f}\t{r_ht_draw:.6f}\t{r_ht_trail:.6f}\t{r_ht1x:.6f}\n"
            )

    # -------------------------------------------------
    # 4) WRITE goals league (DETAILLED)
    # -------------------------------------------------
    with TRISKELE_GOALS_LEAGUE_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tbet_key\tmatches\tht_matches\t"
            "avg_ft_goals\tavg_ht_goals\t"
            "goals_0\tgoals_1\tgoals_2\tgoals_3\tgoals_4_plus\t"
            "rate_o05_ft\trate_o15_ft\trate_o25_ft\trate_o35_ft\t"
            "rate_exact_2\trate_exact_3\t"
            "home_scored_rate\taway_scored_rate\tbtts_rate\t"
            "home_win_rate\tdraw_rate\taway_win_rate\t"
            "rate_ht05\trate_ht15\t"
            "rate_ht_home_lead\trate_ht_draw\trate_ht_away_lead\trate_ht1x_home\t"
            "goals_score\n"
        )

        rows = []
        for (league, bet_key), _agg in league_bet.items():
            lg = league_goal_stats.get(league, _make_empty_league_goal_stats())
            matches_n = int(lg.get("matches", 0))
            ht_matches_n = int(lg.get("ht_matches", 0))
            score = _goal_score_league_from_stats(bet_key, lg)

            rows.append((
                score,
                matches_n,
                league,
                bet_key,
                ht_matches_n,
                _safe_rate(lg.get("ft_goals_sum", 0.0), matches_n),
                _safe_rate(lg.get("ht_goals_sum", 0.0), ht_matches_n),
                int(lg.get("ft_total_0", 0)),
                int(lg.get("ft_total_1", 0)),
                int(lg.get("ft_total_2", 0)),
                int(lg.get("ft_total_3", 0)),
                int(lg.get("ft_total_4_plus", 0)),
                _safe_rate(lg.get("o05_hits", 0.0), matches_n),
                _safe_rate(lg.get("o15_hits", 0.0), matches_n),
                _safe_rate(lg.get("o25_hits", 0.0), matches_n),
                _safe_rate(lg.get("o35_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("btts_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("draw_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_home_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_away_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht1x_home_hits", 0.0), ht_matches_n),
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))

        for row in rows:
            (
                score, matches_n, league, bet_key, ht_matches_n,
                avg_ft_goals, avg_ht_goals,
                g0, g1, g2, g3, g4p,
                r_o05, r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_home_sc, r_away_sc, r_btts,
                r_hw, r_dr, r_aw,
                r_ht05, r_ht15, r_ht_hlead, r_ht_draw, r_ht_alead, r_ht1x
            ) = row

            f.write(
                f"{league}\t{bet_key}\t{matches_n}\t{ht_matches_n}\t"
                f"{avg_ft_goals:.6f}\t{avg_ht_goals:.6f}\t"
                f"{g0}\t{g1}\t{g2}\t{g3}\t{g4p}\t"
                f"{r_o05:.6f}\t{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_home_sc:.6f}\t{r_away_sc:.6f}\t{r_btts:.6f}\t"
                f"{r_hw:.6f}\t{r_dr:.6f}\t{r_aw:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t"
                f"{r_ht_hlead:.6f}\t{r_ht_draw:.6f}\t{r_ht_alead:.6f}\t{r_ht1x:.6f}\t"
                f"{score:.6f}\n"
            )

    # -------------------------------------------------
    # 5) WRITE goals team (DETAILLED)
    # -------------------------------------------------
    with TRISKELE_GOALS_TEAM_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tteam\tbet_key\tmatches\tht_matches\t"
            "avg_goals_for\tavg_goals_against\tavg_goals_total\t"
            "avg_ht_goals_for\tavg_ht_goals_against\tavg_ht_goals_total\t"
            "goals_for_0\tgoals_for_1\tgoals_for_2\tgoals_for_3_plus\t"
            "total_0\ttotal_1\ttotal_2\ttotal_3\ttotal_4_plus\t"
            "rate_scored\trate_conceded\trate_clean_sheet\trate_failed_to_score\t"
            "rate_win\trate_draw\trate_loss\t"
            "rate_o15_match\trate_o25_match\trate_o35_match\t"
            "rate_exact_2_match\trate_exact_3_match\t"
            "rate_ht05_match\trate_ht15_match\trate_ht_lead\trate_ht_draw\trate_ht_trail\trate_ht1x\t"
            "goals_score\n"
        )

        rows = []
        for (league, team, bet_key), _agg in team_bet.items():
            tg = team_goal_stats.get((league, team, bet_key), _make_empty_team_goal_stats())
            matches_n = int(tg.get("matches", 0))
            ht_matches_n = int(tg.get("ht_matches", 0))
            score = _goal_score_team_from_stats(bet_key, tg)

            rows.append((
                score,
                matches_n,
                league,
                team,
                bet_key,
                ht_matches_n,
                _safe_rate(tg.get("goals_for_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_against_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_total_sum", 0.0), matches_n),
                _safe_rate(tg.get("ht_goals_for_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_against_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_total_sum", 0.0), ht_matches_n),
                int(tg.get("gf_0", 0)),
                int(tg.get("gf_1", 0)),
                int(tg.get("gf_2", 0)),
                int(tg.get("gf_3_plus", 0)),
                int(tg.get("total_0", 0)),
                int(tg.get("total_1", 0)),
                int(tg.get("total_2", 0)),
                int(tg.get("total_3", 0)),
                int(tg.get("total_4_plus", 0)),
                _safe_rate(tg.get("scored_hits", 0.0), matches_n),
                _safe_rate(tg.get("conceded_hits", 0.0), matches_n),
                _safe_rate(tg.get("clean_sheet_hits", 0.0), matches_n),
                _safe_rate(tg.get("failed_to_score_hits", 0.0), matches_n),
                _safe_rate(tg.get("win_hits", 0.0), matches_n),
                _safe_rate(tg.get("draw_hits", 0.0), matches_n),
                _safe_rate(tg.get("loss_hits", 0.0), matches_n),
                _safe_rate(tg.get("o15_hits", 0.0), matches_n),
                _safe_rate(tg.get("o25_hits", 0.0), matches_n),
                _safe_rate(tg.get("o35_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(tg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_lead_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_trail_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht1x_hits", 0.0), ht_matches_n),
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3], x[4]))

        for row in rows:
            (
                score, matches_n, league, team, bet_key, ht_matches_n,
                avg_gf, avg_ga, avg_gt,
                avg_ht_gf, avg_ht_ga, avg_ht_gt,
                gf0, gf1, gf2, gf3p,
                t0, t1, t2, t3, t4p,
                r_scored, r_conceded, r_cs, r_fts,
                r_win, r_draw, r_loss,
                r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_ht05, r_ht15, r_ht_lead, r_ht_draw, r_ht_trail, r_ht1x
            ) = row

            f.write(
                f"{league}\t{team}\t{bet_key}\t{matches_n}\t{ht_matches_n}\t"
                f"{avg_gf:.6f}\t{avg_ga:.6f}\t{avg_gt:.6f}\t"
                f"{avg_ht_gf:.6f}\t{avg_ht_ga:.6f}\t{avg_ht_gt:.6f}\t"
                f"{gf0}\t{gf1}\t{gf2}\t{gf3p}\t"
                f"{t0}\t{t1}\t{t2}\t{t3}\t{t4p}\t"
                f"{r_scored:.6f}\t{r_conceded:.6f}\t{r_cs:.6f}\t{r_fts:.6f}\t"
                f"{r_win:.6f}\t{r_draw:.6f}\t{r_loss:.6f}\t"
                f"{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t{r_ht_lead:.6f}\t{r_ht_draw:.6f}\t{r_ht_trail:.6f}\t{r_ht1x:.6f}\t"
                f"{score:.6f}\n"
            )

    # -------------------------------------------------
    # 6) WRITE composite league (DETAILLED)
    # -------------------------------------------------
    with TRISKELE_COMPOSITE_LEAGUE_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tbet_key\tsamples\tsuccess\tfail\tbase_rate\t"
            "matches\tht_matches\tavg_ft_goals\tavg_ht_goals\t"
            "goals_0\tgoals_1\tgoals_2\tgoals_3\tgoals_4_plus\t"
            "rate_o05_ft\trate_o15_ft\trate_o25_ft\trate_o35_ft\t"
            "rate_exact_2\trate_exact_3\t"
            "home_scored_rate\taway_scored_rate\tbtts_rate\t"
            "home_win_rate\tdraw_rate\taway_win_rate\t"
            "rate_ht05\trate_ht15\t"
            "rate_ht_home_lead\trate_ht_draw\trate_ht_away_lead\trate_ht1x_home\t"
            "goals_score\tcomposite_score\n"
        )

        rows = []
        for (league, bet_key), agg in league_bet.items():
            s = agg["samples"]
            w = agg["success"]
            fail = s - w
            base_rate = (w / s) if s else 0.0

            lg = league_goal_stats.get(league, _make_empty_league_goal_stats())
            matches_n = int(lg.get("matches", 0))
            ht_matches_n = int(lg.get("ht_matches", 0))
            goals_score = _goal_score_league_from_stats(bet_key, lg)
            composite = _composite_score(base_rate, goals_score)

            rows.append((
                composite,
                s,
                league,
                bet_key,
                w,
                fail,
                base_rate,
                matches_n,
                ht_matches_n,
                _safe_rate(lg.get("ft_goals_sum", 0.0), matches_n),
                _safe_rate(lg.get("ht_goals_sum", 0.0), ht_matches_n),
                int(lg.get("ft_total_0", 0)),
                int(lg.get("ft_total_1", 0)),
                int(lg.get("ft_total_2", 0)),
                int(lg.get("ft_total_3", 0)),
                int(lg.get("ft_total_4_plus", 0)),
                _safe_rate(lg.get("o05_hits", 0.0), matches_n),
                _safe_rate(lg.get("o15_hits", 0.0), matches_n),
                _safe_rate(lg.get("o25_hits", 0.0), matches_n),
                _safe_rate(lg.get("o35_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(lg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_scored_hits", 0.0), matches_n),
                _safe_rate(lg.get("btts_hits", 0.0), matches_n),
                _safe_rate(lg.get("home_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("draw_hits", 0.0), matches_n),
                _safe_rate(lg.get("away_win_hits", 0.0), matches_n),
                _safe_rate(lg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_home_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht_away_lead_hits", 0.0), ht_matches_n),
                _safe_rate(lg.get("ht1x_home_hits", 0.0), ht_matches_n),
                goals_score,
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))

        for row in rows:
            (
                composite, s, league, bet_key, w, fail, base_rate,
                matches_n, ht_matches_n, avg_ft_goals, avg_ht_goals,
                g0, g1, g2, g3, g4p,
                r_o05, r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_home_sc, r_away_sc, r_btts,
                r_hw, r_dr, r_aw,
                r_ht05, r_ht15, r_ht_hlead, r_ht_draw, r_ht_alead, r_ht1x,
                goals_score
            ) = row

            f.write(
                f"{league}\t{bet_key}\t{s}\t{w}\t{fail}\t{base_rate:.6f}\t"
                f"{matches_n}\t{ht_matches_n}\t{avg_ft_goals:.6f}\t{avg_ht_goals:.6f}\t"
                f"{g0}\t{g1}\t{g2}\t{g3}\t{g4p}\t"
                f"{r_o05:.6f}\t{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_home_sc:.6f}\t{r_away_sc:.6f}\t{r_btts:.6f}\t"
                f"{r_hw:.6f}\t{r_dr:.6f}\t{r_aw:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t"
                f"{r_ht_hlead:.6f}\t{r_ht_draw:.6f}\t{r_ht_alead:.6f}\t{r_ht1x:.6f}\t"
                f"{goals_score:.6f}\t{composite:.6f}\n"
            )

    # -------------------------------------------------
    # 7) WRITE composite team (DETAILLED)
    # -------------------------------------------------
    with TRISKELE_COMPOSITE_TEAM_BET_FILE.open("w", encoding="utf-8") as f:
        f.write(
            "# league\tteam\tbet_key\tsamples\tsuccess\tfail\tbase_rate\t"
            "matches\tht_matches\t"
            "avg_goals_for\tavg_goals_against\tavg_goals_total\t"
            "avg_ht_goals_for\tavg_ht_goals_against\tavg_ht_goals_total\t"
            "goals_for_0\tgoals_for_1\tgoals_for_2\tgoals_for_3_plus\t"
            "total_0\ttotal_1\ttotal_2\ttotal_3\ttotal_4_plus\t"
            "rate_scored\trate_conceded\trate_clean_sheet\trate_failed_to_score\t"
            "rate_win\trate_draw\trate_loss\t"
            "rate_o15_match\trate_o25_match\trate_o35_match\t"
            "rate_exact_2_match\trate_exact_3_match\t"
            "rate_ht05_match\trate_ht15_match\trate_ht_lead\trate_ht_draw\trate_ht_trail\trate_ht1x\t"
            "goals_score\tcomposite_score\n"
        )

        rows = []
        for (league, team, bet_key), agg in team_bet.items():
            s = agg["samples"]
            w = agg["success"]
            fail = s - w
            base_rate = (w / s) if s else 0.0

            tg = team_goal_stats.get((league, team, bet_key), _make_empty_team_goal_stats())
            matches_n = int(tg.get("matches", 0))
            ht_matches_n = int(tg.get("ht_matches", 0))
            goals_score = _goal_score_team_from_stats(bet_key, tg)
            composite = _composite_score(base_rate, goals_score)

            rows.append((
                composite,
                s,
                league,
                team,
                bet_key,
                w,
                fail,
                base_rate,
                matches_n,
                ht_matches_n,
                _safe_rate(tg.get("goals_for_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_against_sum", 0.0), matches_n),
                _safe_rate(tg.get("goals_total_sum", 0.0), matches_n),
                _safe_rate(tg.get("ht_goals_for_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_against_sum", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_goals_total_sum", 0.0), ht_matches_n),
                int(tg.get("gf_0", 0)),
                int(tg.get("gf_1", 0)),
                int(tg.get("gf_2", 0)),
                int(tg.get("gf_3_plus", 0)),
                int(tg.get("total_0", 0)),
                int(tg.get("total_1", 0)),
                int(tg.get("total_2", 0)),
                int(tg.get("total_3", 0)),
                int(tg.get("total_4_plus", 0)),
                _safe_rate(tg.get("scored_hits", 0.0), matches_n),
                _safe_rate(tg.get("conceded_hits", 0.0), matches_n),
                _safe_rate(tg.get("clean_sheet_hits", 0.0), matches_n),
                _safe_rate(tg.get("failed_to_score_hits", 0.0), matches_n),
                _safe_rate(tg.get("win_hits", 0.0), matches_n),
                _safe_rate(tg.get("draw_hits", 0.0), matches_n),
                _safe_rate(tg.get("loss_hits", 0.0), matches_n),
                _safe_rate(tg.get("o15_hits", 0.0), matches_n),
                _safe_rate(tg.get("o25_hits", 0.0), matches_n),
                _safe_rate(tg.get("o35_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_2_hits", 0.0), matches_n),
                _safe_rate(tg.get("exact_3_hits", 0.0), matches_n),
                _safe_rate(tg.get("ht05_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht15_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_lead_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_draw_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht_trail_hits", 0.0), ht_matches_n),
                _safe_rate(tg.get("ht1x_hits", 0.0), ht_matches_n),
                goals_score,
            ))

        rows.sort(key=lambda x: (-x[0], -x[1], x[2], x[3], x[4]))

        for row in rows:
            (
                composite, s, league, team, bet_key, w, fail, base_rate,
                matches_n, ht_matches_n,
                avg_gf, avg_ga, avg_gt,
                avg_ht_gf, avg_ht_ga, avg_ht_gt,
                gf0, gf1, gf2, gf3p,
                t0, t1, t2, t3, t4p,
                r_scored, r_conceded, r_cs, r_fts,
                r_win, r_draw, r_loss,
                r_o15, r_o25, r_o35, r_ex2, r_ex3,
                r_ht05, r_ht15, r_ht_lead, r_ht_draw, r_ht_trail, r_ht1x,
                goals_score
            ) = row

            f.write(
                f"{league}\t{team}\t{bet_key}\t{s}\t{w}\t{fail}\t{base_rate:.6f}\t"
                f"{matches_n}\t{ht_matches_n}\t"
                f"{avg_gf:.6f}\t{avg_ga:.6f}\t{avg_gt:.6f}\t"
                f"{avg_ht_gf:.6f}\t{avg_ht_ga:.6f}\t{avg_ht_gt:.6f}\t"
                f"{gf0}\t{gf1}\t{gf2}\t{gf3p}\t"
                f"{t0}\t{t1}\t{t2}\t{t3}\t{t4p}\t"
                f"{r_scored:.6f}\t{r_conceded:.6f}\t{r_cs:.6f}\t{r_fts:.6f}\t"
                f"{r_win:.6f}\t{r_draw:.6f}\t{r_loss:.6f}\t"
                f"{r_o15:.6f}\t{r_o25:.6f}\t{r_o35:.6f}\t"
                f"{r_ex2:.6f}\t{r_ex3:.6f}\t"
                f"{r_ht05:.6f}\t{r_ht15:.6f}\t{r_ht_lead:.6f}\t{r_ht_draw:.6f}\t{r_ht_trail:.6f}\t{r_ht1x:.6f}\t"
                f"{goals_score:.6f}\t{composite:.6f}\n"
            )

    print("🔥 BASELINE + GOALS + COMPOSITE recalculés depuis results.tsv")
    print(f"✅ Ranking LEAGUE écrit   : {TRISKELE_RANKING_LEAGUE_BET_FILE}")
    print(f"✅ Ranking TEAM écrit     : {TRISKELE_RANKING_TEAM_BET_FILE}")
    print(f"✅ Goals LEAGUE écrit     : {TRISKELE_GOALS_LEAGUE_BET_FILE}")
    print(f"✅ Goals TEAM écrit       : {TRISKELE_GOALS_TEAM_BET_FILE}")
    print(f"✅ Composite LEAGUE écrit : {TRISKELE_COMPOSITE_LEAGUE_BET_FILE}")
    print(f"✅ Composite TEAM écrit   : {TRISKELE_COMPOSITE_TEAM_BET_FILE}")


# ==============================
# 3bis) RÉCAP FINAL PAR TYPE DE PARI (WIN/LOSS uniquement)
# ==============================


def _normalize_bet_family(bet_key: str) -> str:
    bk = (bet_key or "").strip().upper()

    if bk == "HT05":
        return "HT05"

    if bk in ("HT1X_HOME", "HT1X", "HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        return "HT1X_HOME"

    if bk in (
        "O15_FT",
        "FT_OVER_1_5",
        "OVER15",
        "OVER_1_5",
        "O15",
        "FT_O15",
        "FT15",
        "FT_OVER15",
        "FT_OVER15",
        "FT_OVER_1_5",
    ):
        return "O15_FT"

    if bk in ("TEAM1_SCORE_FT", "TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE"):
        return "TEAM1_SCORE_FT"

    if bk in ("TEAM2_SCORE_FT", "TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE"):
        return "TEAM2_SCORE_FT"

    if bk in ("TEAM1_WIN_FT", "TEAM1_WIN", "HOME_WIN", "T1_WIN"):
        return "TEAM1_WIN_FT"

    if bk in ("TEAM2_WIN_FT", "TEAM2_WIN", "AWAY_WIN", "T2_WIN"):
        return "TEAM2_WIN_FT"

    return bk if bk else "UNKNOWN"


def _family_order_key(family: str) -> tuple[int, str]:
    fam = (family or "").strip().upper()
    if fam == "O15_FT":
        return (0, fam)
    if fam == "HT05":
        return (1, fam)
    if fam == "HT1X_HOME":
        return (2, fam)
    return (10, fam)


def _pick_label_for_display(v: Dict[str, Any]) -> str:
    label = (v.get("label") or "").strip()
    return f"[{label}]" if label else ""


def _pick_time_for_display(v: Dict[str, Any]) -> str:
    t = (v.get("match_time") or "").strip()
    return t


def print_final_recap_by_bet_type(match_blocks: Dict[MatchKey, List[Dict[str, Any]]]) -> None:
    by_family: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for _mk, verdicts in (match_blocks or {}).items():
        for v in (verdicts or []):
            if not v:
                continue
            if not bool(v.get("played")):
                continue
            ev = (v.get("eval") or "").strip().upper()
            if ev not in ("WIN", "LOSS"):
                continue

            fam = _normalize_bet_family(str(v.get("bet_key") or ""))
            by_family.setdefault(fam, {"WIN": [], "LOSS": []})
            by_family[fam][ev].append(v)

    print("\n📌 RÉCAP FINAL PAR TYPE DE PARI (WIN/LOSS uniquement)\n")

    if not by_family:
        print("ℹ️ Aucun pari joué WIN/LOSS à récapituler.")
        return

    for fam in sorted(by_family.keys(), key=_family_order_key):
        wins = by_family[fam]["WIN"]
        losses = by_family[fam]["LOSS"]
        total = len(wins) + len(losses)

        print("=" * 80)
        print(f"🎯 TYPE DE PARI : {fam}")
        print("=" * 80)
        print(f"Total: {total} | ✅ WIN: {len(wins)} | ❌ LOSS: {len(losses)}")
        print("-" * 80)
        print()

        if wins:
            print(f"✅ WIN — {len(wins)}")
            for v in sorted(
                wins,
                key=lambda x: (
                    str(x.get("date") or ""),
                    _time_to_minutes(_pick_time_for_display(x)),
                    str(x.get("home") or "").lower(),
                    str(x.get("away") or "").lower(),
                ),
            ):
                d = str(v.get("date") or "")
                t = _pick_time_for_display(v)
                home = str(v.get("home") or "")
                away = str(v.get("away") or "")
                lab = _pick_label_for_display(v)
                time_part = f"{t} | " if t else ""
                print(f"  - {d} {time_part}{home} vs {away} | {lab}".rstrip())
            print()

        if losses:
            print(f"❌ LOSS — {len(losses)}")
            for v in sorted(
                losses,
                key=lambda x: (
                    str(x.get("date") or ""),
                    _time_to_minutes(_pick_time_for_display(x)),
                    str(x.get("home") or "").lower(),
                    str(x.get("away") or "").lower(),
                ),
            ):
                d = str(v.get("date") or "")
                t = _pick_time_for_display(v)
                home = str(v.get("home") or "")
                away = str(v.get("away") or "")
                lab = _pick_label_for_display(v)
                time_part = f"{t} | " if t else ""
                print(f"  - {d} {time_part}{home} vs {away} | {lab}".rstrip())
            print()

        print()


# ==============================
# 4) Moteur complet post-analyse multi-paris + tickets
# ==============================


def _build_match_only_key(pred: Dict[str, Any]) -> MatchKey:
    match_id = (pred.get("match_id") or "").strip()
    if match_id:
        return ("MID", match_id, "", "")
    return (pred.get("date", ""), pred.get("league", ""), pred.get("home", ""), pred.get("away", ""))


def _resolve_allowed_ticket_ids_from_global(variant_name: str) -> Tuple[Optional[Path], set[str]]:
    """
    ✅ NOUVELLE règle : on analyse uniquement les tickets dont l'id existe dans le REPORT GLOBAL.
    (C'est précisément pour ça que tu as mis les id=... dedans.)

    - SYSTEM -> data/tickets_report_global.txt
    - O15_RANDOM -> data/tickets_o15_random_report_global.txt
    """
    vn = (variant_name or "").strip().upper()
    if vn == "SYSTEM":
        global_path = TICKETS_REPORT_GLOBAL_FILE
    elif vn == "U35_RANDOM":
        global_path = TICKETS_U35_REPORT_GLOBAL_FILE
    elif vn == "O15_SUPER_RANDOM":
        global_path = TICKETS_O15_SUPER_REPORT_GLOBAL_FILE
    elif vn == "U35_SUPER_RANDOM":
        global_path = TICKETS_U35_SUPER_REPORT_GLOBAL_FILE
    elif vn == "O25_RANDOM":
        global_path = TICKETS_O25_REPORT_GLOBAL_FILE
    elif vn == "O25_SUPER_RANDOM":
        global_path = TICKETS_O25_SUPER_REPORT_GLOBAL_FILE
    else:
        global_path = TICKETS_O15_REPORT_GLOBAL_FILE
    if not _is_nonempty_file(global_path):
        return None, set()

    try:
        txt = global_path.read_text(encoding="utf-8", errors="ignore")
        allowed = _load_ticket_ids_from_report_text(txt)
        return global_path, allowed
    except Exception as e:
        print(f"⚠️ Impossible de lire report global ({global_path}) : {e}")
        return global_path, set()


def _run_tickets_post_analysis_variant(
    *,
    today: date_cls,
    eval_index: Dict[Tuple[str, str], str],
    tickets_file: Path,
    verdict_file: Path,
    failed_file: Path,
    variant_name: str,
    write_human_report: bool = True,
) -> None:
    """
    ✅ MODE INCRÉMENTAL + SNAPSHOT SAFE
    - On ne "retraite" (recalc) que les tickets :
        * inconnus (NEW)
        * ou PENDING (potentiel HEAL)
        * ou UPDATE (rare)
      Les tickets déjà FINALS (WIN/LOSS) sont recopiés tels quels depuis verdict_file.
    - On n'affiche en console que NEW / HEAL / UPDATE (mode intelligent).
    - On n'écrase JAMAIS verdict_file si rien à écrire (anti-reset).
    """

    if not tickets_file.exists() or tickets_file.stat().st_size == 0:
        print(f"\nℹ️ [{variant_name}] Aucun {tickets_file.name} détecté, post-analyse tickets ignorée.")
        return

    # ------------------------------------------------------------------
    # 0) Whitelist (REPORT GLOBAL)
    # ------------------------------------------------------------------
    report_source_path, allowed_ids = _resolve_allowed_ticket_ids_from_global(variant_name)
    if not allowed_ids:
        src = str(report_source_path) if report_source_path is not None else "AUCUN_REPORT_GLOBAL"
        print(
            f"\nℹ️ [{variant_name}] Aucun ticket_id trouvé dans le REPORT GLOBAL "
            f"-> post-analyse tickets ignorée."
        )
        print(f"   Source : {src}")
        return

    # ------------------------------------------------------------------
    # 1) Charger l'état précédent (pour mode intelligent + recopie)
    # ------------------------------------------------------------------
    prev_state_by_tid: Dict[str, str] = _load_ticket_verdict_latest_state(verdict_file)

    prev_line_by_tid: Dict[str, str] = {}
    if verdict_file.exists() and verdict_file.stat().st_size > 0:
        try:
            with verdict_file.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = (line or "").strip()
                    if not raw.startswith("TSV:"):
                        continue
                    parts = raw[4:].lstrip().split("\t")
                    if not parts:
                        continue
                    tid = parts[0].strip()
                    if tid:
                        prev_line_by_tid[tid] = raw
        except Exception:
            prev_line_by_tid = {}

    # ------------------------------------------------------------------
    # 2) Snapshot failed/pending log (rewrite)
    # ------------------------------------------------------------------
    failed_file.parent.mkdir(parents=True, exist_ok=True)
    with failed_file.open("w", encoding="utf-8") as f:
        f.write("# ticket_id\tdate\treason\n")

    # ------------------------------------------------------------------
    # 3) Load tickets TSV + filtrage (whitelist + date<present)
    # ------------------------------------------------------------------
    with tickets_file.open("r", encoding="utf-8") as f:
        ticket_lines = [l.rstrip("\n") for l in f if l.strip()]

    tickets_header: Dict[str, Dict[str, Any]] = {}
    ticket_legs: Dict[str, List[Dict[str, Any]]] = {}

    ignored_future = 0
    ignored_not_in_global = 0
    ignored_bad_date = 0

    for line in ticket_lines:
        t = parse_ticket_line(line)
        if t is None:
            continue

        tid = t["ticket_id"]

        if tid not in allowed_ids:
            ignored_not_in_global += 1
            continue

        d = _as_date(t.get("date", ""))
        if d is None:
            ignored_bad_date += 1
            continue

        if d >= today:
            ignored_future += 1
            continue

        tickets_header.setdefault(tid, t)
        ticket_legs.setdefault(tid, []).append(t)

    if not ticket_legs:
        print(f"\nℹ️ [{variant_name}] Aucun ticket passé à analyser (whitelist report global).")
        print(f"   Ignorés (date>=today)           : {ignored_future}")
        print(f"   Ignorés (pas dans report global): {ignored_not_in_global}")
        print(f"   Ignorés (date illisible)        : {ignored_bad_date}")
        return

    # Numéro de ticket (par date + start/end)
    ticket_no_map = _infer_ticket_numbers(tickets_header)

    print(f"\n🎟️ POST-ANALYSE TICKETS [{variant_name}] (mode: INCRÉMENTAL + SNAPSHOT SAFE)\n")
    print("=" * 80)
    print(f"Report GLOBAL source (whitelist)   : {report_source_path}")
    print(f"Tickets TSV ignorés (date>=today)  : {ignored_future}")
    print(f"Lignes TSV ignorées (hors global)  : {ignored_not_in_global}")
    print(f"Lignes TSV ignorées (date illisible): {ignored_bad_date}")
    print(f"Tickets file                       : {tickets_file}")
    print(f"Verdict file (SNAPSHOT rewrite)    : {verdict_file}")
    print("=" * 80)

    def _ticket_sort_key(tid: str) -> Tuple[str, int, int, int, str]:
        h = tickets_header.get(tid, {})
        d2 = str(h.get("date") or "")
        st = _time_to_minutes(str(h.get("start_time") or ""))
        en = _time_to_minutes(str(h.get("end_time") or ""))
        no = int(ticket_no_map.get(tid, 10**9))
        return (d2, st, en, no, tid)

    def _leg_sort_key(leg: Dict[str, Any]) -> Tuple[int, str, str, str, str]:
        t2 = str(leg.get("match_time") or "")
        return (
            _time_to_minutes(t2),
            str(leg.get("league") or ""),
            str(leg.get("home") or ""),
            str(leg.get("away") or ""),
            str(leg.get("match_id") or ""),
        )

    def _normalize_leg_eval(ev: str) -> str:
        e = (ev or "").strip().upper()
        if e == "BAD_NO_BET":
            return "WIN"
        if e == "GOOD_NO_BET":
            return "LOSS"
        if e in ("WIN", "LOSS", "PENDING"):
            return e
        return "PENDING"

    def _leg_display_name(leg: Dict[str, Any]) -> str:
        t = (leg.get("match_time") or "").strip()
        league = (leg.get("league") or "").strip()
        home = (leg.get("home") or "").strip()
        away = (leg.get("away") or "").strip()
        bk = (leg.get("bet_key") or "").strip().upper()
        odd = (leg.get("odd") or "").strip()
        odd_part = f" | odd={odd}" if odd else ""
        time_part = f"{t} | " if t else ""
        return f"{time_part}{league} | {home} vs {away} | {bk}{odd_part}".strip()

    def _leg_eval_for_display(leg: Dict[str, Any]) -> Tuple[str, str]:
        match_id = (leg.get("match_id") or "").strip()
        bet_key = (leg.get("bet_key") or "").strip().upper()
        if not match_id or not bet_key:
            return "⏳", "PENDING"

        ev_raw = (eval_index.get((match_id, bet_key)) or "").strip().upper()
        ev = _normalize_leg_eval(ev_raw)

        emoji = _eval_to_emoji(ev) or ("✅" if ev == "WIN" else ("❌" if ev == "LOSS" else "⏳"))
        return emoji, ev

    # ------------------------------------------------------------------
    # 4) SNAPSHOT : on recopie les finals, on recalc seulement NEW/PENDING/UPDATE
    # ------------------------------------------------------------------
    snapshot_by_tid: Dict[str, str] = {}

    attempted = 0
    win_count = 0
    loss_count = 0
    pending_count = 0
    hard_failed = 0

    for tid in sorted(ticket_legs.keys(), key=_ticket_sort_key):
        header = tickets_header.get(tid, {})
        legs_raw = ticket_legs.get(tid, [])
        if not legs_raw:
            hard_failed += 1
            _log_post_failed_ticket(
                tid,
                header.get("date", ""),
                f"[{variant_name}] EMPTY_TICKET_LEGS",
                failed_file=failed_file,
            )
            continue

        prev_state = (prev_state_by_tid.get(tid) or "").strip().upper()

        # ✅ Si déjà FINAL (WIN/LOSS), on ne recalc pas : on recopie la ligne précédente
        if prev_state in ("WIN", "LOSS"):
            prev_line = prev_line_by_tid.get(tid)
            if prev_line:
                snapshot_by_tid[tid] = prev_line
                # compteurs (juste pour bilan cohérent)
                if prev_state == "WIN":
                    win_count += 1
                else:
                    loss_count += 1
                continue
            # si pas de ligne précédente => on recalc (cas rare)

        attempted += 1

        # dédoublonnage legs (match_id, bet_key)
        legs_unique: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for leg in legs_raw:
            mid = (leg.get("match_id") or "").strip()
            bk = (leg.get("bet_key") or "").strip().upper()
            key = (mid or "MISSING_MID", bk or "MISSING_BK")
            legs_unique.setdefault(key, leg)

        legs = list(legs_unique.values())
        legs.sort(key=_leg_sort_key)

        ticket_no = int(ticket_no_map.get(tid, 0) or 0)

        wins = 0
        losses = 0
        pending_reasons: List[str] = []

        for leg in legs:
            match_id = (leg.get("match_id") or "").strip()
            bet_key = (leg.get("bet_key") or "").strip().upper()

            if not match_id or not bet_key:
                pending_reasons.append("MISSING_MATCH_ID_OR_BET_KEY")
                continue

            ev_raw = (eval_index.get((match_id, bet_key)) or "").strip().upper()
            ev = _normalize_leg_eval(ev_raw)

            if ev == "WIN":
                wins += 1
            elif ev == "LOSS":
                losses += 1
            else:
                pending_reasons.append(f"{match_id}:{bet_key}:{ev_raw or 'NO_VERDICT'}")

        if losses >= 1:
            eval_ticket = "LOSS"
            loss_count += 1
        elif pending_reasons:
            eval_ticket = "PENDING"
            pending_count += 1
        else:
            eval_ticket = "WIN"
            win_count += 1

        # Log pending (snapshot)
        if eval_ticket == "PENDING":
            uniq: List[str] = []
            for p in pending_reasons:
                if p and p not in uniq:
                    uniq.append(p)
            _log_post_failed_ticket(
                tid,
                header.get("date", ""),
                f"[{variant_name}] PENDING_LEG_VERDICT: {', '.join(uniq[:10])}",
                failed_file=failed_file,
            )

        # -----------------------------------------------------------
        # MODE INTELLIGENT (console) : NEW / HEAL / UPDATE uniquement
        # -----------------------------------------------------------
        tag = None
        if not prev_state:
            tag = "🆕 NEW"
        elif prev_state == "PENDING" and eval_ticket in ("WIN", "LOSS"):
            tag = "♻️ HEAL"
        elif prev_state in ("WIN", "LOSS", "PENDING") and prev_state != eval_ticket:
            tag = "🔁 UPDATE"

        if tag is not None:
            emoji_ticket = _eval_to_emoji(eval_ticket) or ("✅" if eval_ticket == "WIN" else ("❌" if eval_ticket == "LOSS" else "⏳"))
            title = (
                f"{tag} [{variant_name}] "
                f"Ticket {ticket_no} | {header.get('date','')} {header.get('start_time','')} | "
                f"id={tid} -> {emoji_ticket} {eval_ticket} "
                f"(W={wins} L={losses} / legs={len(legs)})"
            )
            sep = "─" * max(30, len(title))
            print(sep)
            print(title)
            print(sep)
            for i, leg in enumerate(legs, start=1):
                emo, lev = _leg_eval_for_display(leg)
                print(f"  {i:>2}. {emo} {lev:<7} | {_leg_display_name(leg)}")
            print("")

        # Build TSV snapshot line (1 par ticket)
        v = {
            "ticket_id": tid,
            "ticket_no": ticket_no,
            "date": header.get("date", ""),
            "start_time": header.get("start_time", ""),
            "end_time": header.get("end_time", ""),
            "code": header.get("code", ""),
            "total_odd": header.get("total_odd", ""),
            "legs": len(legs),
            "wins": wins,
            "losses": losses,
            "eval": eval_ticket,
        }
        snapshot_by_tid[tid] = _format_ticket_verdict_tsv(v)

    # ------------------------------------------------------------------
    # 5) WRITE SNAPSHOT SAFE (anti-reset)
    # ------------------------------------------------------------------
    if not snapshot_by_tid:
        print(f"\nℹ️ [{variant_name}] Snapshot vide -> on n'écrit PAS {verdict_file} (anti-reset).")
        return

    verdict_file.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = verdict_file.with_suffix(verdict_file.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for tid in sorted(snapshot_by_tid.keys(), key=_ticket_sort_key):
            f.write(snapshot_by_tid[tid] + "\n")

    # remplace seulement si tmp non vide
    if tmp_path.exists() and tmp_path.stat().st_size > 0:
        tmp_path.replace(verdict_file)
    else:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"\n⚠️ [{variant_name}] tmp snapshot vide -> on n'écrase PAS {verdict_file} (anti-reset).")
        return

    print(f"\n✅ [{variant_name}] Verdicts tickets SNAPSHOT écrits : {verdict_file} ({len(snapshot_by_tid)} tickets)")

    # ------------------------------------------------------------------
    # 6) Human report
    # ------------------------------------------------------------------
    if write_human_report:
        try:
            if variant_name == "SYSTEM":
                _human_fname = "verdict_post_analyse_tickets_report.txt"
            elif variant_name == "U35_RANDOM":
                _human_fname = "verdict_post_analyse_tickets_u35_random_report.txt"
            elif variant_name == "O25_RANDOM":
                _human_fname = "verdict_post_analyse_tickets_o25_random_report.txt"
            elif variant_name == "O15_SUPER_RANDOM":
                _human_fname = "verdict_post_analyse_tickets_o15_super_random_report.txt"
            elif variant_name == "U35_SUPER_RANDOM":
                _human_fname = "verdict_post_analyse_tickets_u35_super_random_report.txt"
            elif variant_name == "O25_SUPER_RANDOM":
                _human_fname = "verdict_post_analyse_tickets_o25_super_random_report.txt"
            else:
                _human_fname = "verdict_post_analyse_tickets_o15_random_report.txt"
            human_out = _run_scoped_or_data(_human_fname)
            rd = _get_run_dir()
            mode = f"RUN_DIR={rd}" if rd is not None else "RUN_DIR=OFF (fallback data/)"
            print(f"\n🧭 [{variant_name}] Mode report : {mode}")
            print(f"🧾 [{variant_name}] out_path = {human_out.resolve()}")

            write_post_tickets_human_report(
                tickets_file=tickets_file,
                eval_index=eval_index,
                today=today,
                out_path=human_out,
                title=f"VERDICT POST-ANALYSE — REPORT TICKETS (LISIBLE) [{variant_name}]",
                allowed_ticket_ids=allowed_ids,
            )
            print(f"\n📝 [{variant_name}] Human report tickets écrit : {human_out}")
        except Exception as e:
            print(f"⚠️ [{variant_name}] Impossible d'écrire le report humain tickets : {e}")

    # ------------------------------------------------------------------
    # 7) Summary
    # ------------------------------------------------------------------
    print(f"\n=== BILAN POST-ANALYSE TICKETS [{variant_name}] ===")
    print(f"Tickets recalculés (NEW/PENDING/UPDATE) : {attempted}")
    print(f"Tickets WIN                            : {win_count}")
    print(f"Tickets LOSS                           : {loss_count}")
    print(f"Tickets PENDING                        : {pending_count}")
    print(f"Tickets hard-failed                    : {hard_failed}")
    print(f"Log tickets (pending/failed)           : {failed_file}")

def _run_tickets_post_analysis(
    today: date_cls,
    eval_index: Dict[Tuple[str, str], str],
) -> None:
    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_FILE,
        verdict_file=POST_TICKETS_VERDICT_FILE,
        failed_file=POST_TICKETS_FAILED_FILE,
        variant_name="SYSTEM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_O15_FILE,
        verdict_file=POST_TICKETS_O15_VERDICT_FILE,
        failed_file=POST_TICKETS_O15_FAILED_FILE,
        variant_name="O15_RANDOM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_U35_FILE,
        verdict_file=POST_TICKETS_U35_VERDICT_FILE,
        failed_file=POST_TICKETS_U35_FAILED_FILE,
        variant_name="U35_RANDOM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_O15_SUPER_FILE,
        verdict_file=POST_TICKETS_O15_SUPER_VERDICT_FILE,
        failed_file=POST_TICKETS_O15_SUPER_FAILED_FILE,
        variant_name="O15_SUPER_RANDOM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_U35_SUPER_FILE,
        verdict_file=POST_TICKETS_U35_SUPER_VERDICT_FILE,
        failed_file=POST_TICKETS_U35_SUPER_FAILED_FILE,
        variant_name="U35_SUPER_RANDOM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_O25_FILE,
        verdict_file=POST_TICKETS_O25_VERDICT_FILE,
        failed_file=POST_TICKETS_O25_FAILED_FILE,
        variant_name="O25_RANDOM",
        write_human_report=True,
    )

    _run_tickets_post_analysis_variant(
        today=today,
        eval_index=eval_index,
        tickets_file=TICKETS_O25_SUPER_FILE,
        verdict_file=POST_TICKETS_O25_SUPER_VERDICT_FILE,
        failed_file=POST_TICKETS_O25_SUPER_FAILED_FILE,
        variant_name="O25_SUPER_RANDOM",
        write_human_report=True,
    )


def run_post_analysis(predictions_path: Path, results_path: Path, post_verdict_path: Path) -> None:
    refresh_match_meta_cache()

    if not predictions_path.exists():
        print(f"⚠️ Fichier de prédictions introuvable : {predictions_path}")
        return

    results_tsv_lines: List[str] = []
    verdicts_tsv_lines: List[str] = []

    result_cache: Dict[MatchKey, Optional[Dict[str, Any]]] = {}
    match_blocks: Dict[MatchKey, List[Dict[str, Any]]] = {}
    processed_keys: set[Tuple[str, str]] = set()

    GLOBAL_VERDICT_FILE = Path("data") / "verdict_post_analyse.txt"
    verdict_state = _load_verdict_state(GLOBAL_VERDICT_FILE)

    attempted = 0
    success_count = 0
    fail_count = 0

    POST_MATCHES_FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with POST_MATCHES_FAILED_FILE.open("w", encoding="utf-8") as f:
        f.write("# date | league | home vs away | reason\n")

    today = datetime.today().date()

    # ------------------------------------------------------------------
    # 0) INDEX VERDICTS EXISTANTS (run courant)
    # ------------------------------------------------------------------
    existing_verdict_keys: set[Tuple[str, str]] = set()
    if post_verdict_path.exists() and post_verdict_path.stat().st_size > 0:
        with post_verdict_path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw.startswith("TSV:"):
                    continue
                parts = raw[4:].lstrip().split("\t")
                if len(parts) >= 6 and _is_date(parts[1].strip()):
                    match_id = parts[0].strip()
                    bet_key = parts[5].strip().upper()
                    if match_id and bet_key:
                        existing_verdict_keys.add((match_id, bet_key))

    # ------------------------------------------------------------------
    # 1) INDEX RESULTS EXISTANTS
    # ------------------------------------------------------------------
    existing_result_match_keys: set[MatchKey] = set()
    if results_path.exists() and results_path.stat().st_size > 0:
        with results_path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw.startswith("TSV:"):
                    continue
                parts = raw[4:].lstrip().split("\t")
                if len(parts) < 5:
                    continue
                date_str = parts[0].strip()
                league = parts[1].strip()
                home = parts[2].strip()
                away = parts[3].strip()
                fixture_id = parts[4].strip()

                if fixture_id and _is_int_str(fixture_id):
                    existing_result_match_keys.add(("FID", fixture_id, "", ""))
                else:
                    existing_result_match_keys.add((date_str, league, home, away))

    # ------------------------------------------------------------------
    # 2) LOAD PREDICTIONS
    # ------------------------------------------------------------------
    with predictions_path.open("r", encoding="utf-8") as f:
        pred_lines = [l.rstrip("\n") for l in f if l.strip()]

    if not pred_lines:
        print("⚠️ Aucun TSV de prédiction à analyser.")
        return

    results_written_this_run: set[MatchKey] = set()
    eval_index: Dict[Tuple[str, str], str] = _load_eval_index_from_post_verdict(post_verdict_path)

    # ------------------------------------------------------------------
    # 3) MAIN LOOP
    # ------------------------------------------------------------------
    for line in pred_lines:
        pred = parse_prediction_line(line)
        if pred is None:
            continue

        pred_d = _as_date(pred.get("date", ""))
        if pred_d is None or pred_d >= today:
            continue

        bet_key = (pred.get("bet_key") or "").strip().upper()
        match_id = (pred.get("match_id") or "").strip()

        # ✅ Anti-duplication forte : si déjà écrit dans post_verdict_path, on skip.
        if match_id and bet_key and (match_id, bet_key) in existing_verdict_keys:
            continue

        verdict_key = (
            (match_id, bet_key)
            if match_id
            else (f"{pred['date']}|{pred['league']}|{pred['home']}|{pred['away']}", bet_key)
        )

        match_only_key = _build_match_only_key(pred)

        # ✅ Skip uniquement si état FINAL déjà présent dans l'historique global.
        prev_eval = verdict_state.get(verdict_key, "").upper()
        if prev_eval in {"WIN", "LOSS", "GOOD_NO_BET", "BAD_NO_BET"}:
            continue

        fixture_id, _how = _get_fixture_id_any_fuzzy(pred["league"], pred["date"], pred["home"], pred["away"])
        result_key: MatchKey = ("FID", str(fixture_id), "", "") if fixture_id is not None else match_only_key

        need_verdict = verdict_key not in processed_keys
        if fixture_id is not None:
            need_result = ("FID", str(fixture_id), "", "") not in existing_result_match_keys
        else:
            fallback_key: MatchKey = (pred["date"], pred["league"], pred["home"], pred["away"])
            need_result = fallback_key not in existing_result_match_keys

        if not need_verdict and not need_result:
            continue

        attempted += 1

        if result_key in result_cache:
            res = result_cache[result_key]
        else:
            res = fetch_match_result(
                pred["date"],
                pred["league"],
                pred["home"],
                pred["away"],
                match_time=pred.get("time"),
            )
            result_cache[result_key] = res

        if res is None:
            fail_count += 1
            processed_keys.add(verdict_key)
            continue

        success_count += 1

        fid_real = str(res.get("fixture_id") or "").strip()
        if fid_real and _is_int_str(fid_real):
            result_key = ("FID", fid_real, "", "")

        if need_result and result_key not in results_written_this_run:
            results_tsv_lines.append(format_result_tsv(res))
            results_written_this_run.add(result_key)
            existing_result_match_keys.add(result_key)

            if fid_real and _is_int_str(fid_real):
                existing_result_match_keys.add(("FID", fid_real, "", ""))

        if need_verdict:
            verdict = build_post_verdict(pred, res)
            verdicts_tsv_lines.append(format_post_verdict_tsv(verdict))
            match_blocks.setdefault(result_key, []).append(verdict)

            mid = str(verdict.get("match_id") or "").strip()
            bk = str(verdict.get("bet_key") or "").strip().upper()
            ev = str(verdict.get("eval") or "").strip().upper()
            if mid and bk and ev:
                eval_index[(mid, bk)] = ev
                existing_verdict_keys.add((mid, bk))  # ✅ pour ne pas réécrire 2 fois dans le même run

            processed_keys.add(verdict_key)

    # ------------------------------------------------------------------
    # 4) WRITE FILES
    # ------------------------------------------------------------------
    if results_tsv_lines:
        results_path.parent.mkdir(parents=True, exist_ok=True)
        with results_path.open("a", encoding="utf-8") as f:
            for l in results_tsv_lines:
                f.write(l + "\n")
        print(f"✅ Résultats bruts ajoutés : {len(results_tsv_lines)}")
    else:
        print("ℹ️ Aucun nouveau résultat brut.")

    if verdicts_tsv_lines:
        post_verdict_path.parent.mkdir(parents=True, exist_ok=True)
        with post_verdict_path.open("a", encoding="utf-8") as f:
            for l in verdicts_tsv_lines:
                f.write(l + "\n")
        print(f"✅ Verdicts post-analyse ajoutés : {len(verdicts_tsv_lines)}")
    else:
        print("ℹ️ Aucun nouveau verdict.")

    if match_blocks:
        print_final_recap_by_bet_type(match_blocks)

    print("\n=== BILAN POST-ANALYSE ===")
    print(f"Nouveaux paris traités : {attempted}")
    print(f"Succès                 : {success_count}")
    print(f"Échecs                 : {fail_count}")

    # ✅ IMPORTANT : index tickets doit venir du GLOBAL (historique complet), pas du run local
    GLOBAL_VERDICT_FILE = Path("data") / "verdict_post_analyse.txt"
    eval_index_global = _load_eval_index_from_post_verdict(GLOBAL_VERDICT_FILE)

    _run_tickets_post_analysis(today=today, eval_index=eval_index_global)

    try:
        update_triskele_rankings_from_history()
    except Exception as e:
        print(f"⚠️ [RANKINGS] Impossible de recalculer les rankings : {e}")

# Ancienne génération stats_core désactivée provisoirement
# car update_triskele_rankings_from_history() écrit désormais
# les rankings classiques + goals + composite.
#
# from services.stats_core import load_bet_verdicts, write_rankings_files
# bets_df = load_bet_verdicts(Path("data/verdict_post_analyse.txt"))
# write_rankings_files(bets_df, min_samples=12)