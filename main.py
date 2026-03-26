# main.py
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from datetime import date, datetime
import tempfile
import re
import shutil
from contextlib import contextmanager
import os

from services.api_client import fetch_match_data
from services.match_analysis import run_full_analysis
from services.ticket_builder import generate_tickets_from_tsv


# ============================================================================
# ROOT / DATA / ARCHIVE (robuste : basé sur le dossier projet)
# ============================================================================
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARCHIVE_ROOT = ROOT / "archive"

DATA_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)


def _get_run_dir() -> Path | None:
    """
    Retourne le dossier de run (bulle) si TRISKELE_RUN_DIR est défini.
    """
    rd = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if not rd:
        return None
    p = Path(rd)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_archive_dir_for_date(target_date: str) -> Path:
    """
    Si TRISKELE_RUN_DIR existe -> on archive dans cette bulle (et on ne recrée pas de run_stamp).
    Sinon -> fallback historique: archive/analyse_YYYY-MM-DD/<run_stamp>/
    """
    rd = _get_run_dir()
    if rd is not None:
        return rd  # ✅ la bulle est la source de vérité

    run_stamp = datetime.now().strftime("%Y-%m-%d__%Hh%Mm%Ss")
    archive_dir = ARCHIVE_ROOT / f"analyse_{target_date}" / run_stamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


# ============================================================================
# Bet keys : aliases -> canonical (défini UNE FOIS, utilisé partout)
# ============================================================================
KEY_ALIASES = {
    "HT05": {"HT05"},
    "HT1X_HOME": {"HT1X_HOME", "HT1X", "HT_1X_HOME"},
    "TEAM1_SCORE_FT": {"TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE", "TEAM1_SCORE_FT"},
    "TEAM2_SCORE_FT": {"TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE", "TEAM2_SCORE_FT"},
    "O15_FT": {"O15", "O15_FT", "FT_O15", "OVER15", "OVER_1_5", "OVER_1_5_FT"},
    "O25_FT": {"O25", "O25_FT", "FT_O25", "OVER25", "OVER_2_5", "OVER_2_5_FT"},
    "TEAM1_WIN_FT": {"TEAM1_WIN", "TEAM1_WIN_FT", "T1_WIN", "HOME_WIN", "HOME_WIN_FT"},
    "TEAM2_WIN_FT": {"TEAM2_WIN", "TEAM2_WIN_FT", "T2_WIN", "AWAY_WIN", "AWAY_WIN_FT"},
}

# alias -> canonical
CANON: Dict[str, str] = {}
for canon, aliases in KEY_ALIASES.items():
    for a in aliases:
        CANON[a.strip().upper()] = canon


# ============================================================================
# Ranks (classement) — stockés pendant le run pour pouvoir les réutiliser
# ============================================================================
RUN_RANKS: Dict[Tuple[str, str, str, str], Tuple[Any, Any]] = {}
# clé = (date, league, home, away) -> (home_rank, away_rank)


def _rank_str(x: Any) -> str:
    return str(x) if x is not None and str(x).strip() != "" else "—"


def _label_with_ranks(label: str, home_rank: Any, away_rank: Any) -> str:
    hr = _rank_str(home_rank)
    ar = _rank_str(away_rank)
    suffix = f"[R:{hr}-{ar}]"
    lab = (label or "").strip()
    if not lab:
        return suffix
    if suffix in lab:
        return lab
    return f"{lab} {suffix}"


def _fmt_team_with_rank(team: str, r: Any) -> str:
    rr = _rank_str(r)
    return f"{team} ({rr})"


# ============================================================================
# PATHS (robuste : DATA_DIR / ...)
#  - IMPORTANT : l'INPUT doit préférer la bulle si présente.
# ============================================================================
DATA_INPUT_FILE = DATA_DIR / "matches_input.txt"
RUN_DIR = _get_run_dir()
RUN_INPUT_FILE = (RUN_DIR / "matches_input.txt") if RUN_DIR else None

# ✅ Source de vérité input : bulle si présent, sinon data/
INPUT_FILE = RUN_INPUT_FILE if (RUN_INPUT_FILE and RUN_INPUT_FILE.exists()) else DATA_INPUT_FILE

# Historique global : predictions + jouables restent dans data/
OUTPUT_TSV_FILE = DATA_DIR / "predictions.tsv"

HT05_JOUABLE_FILE = DATA_DIR / "ht05_jouables.tsv"
HT1X_HOME_JOUABLE_FILE = DATA_DIR / "ht1x_home_jouables.tsv"
TEAM1_SCORE_JOUABLE_FILE = DATA_DIR / "team1_score_jouables.tsv"
TEAM2_SCORE_JOUABLE_FILE = DATA_DIR / "team2_score_jouables.tsv"

MIN_ODD_JOUABLE = 1.15

O15_FT_JOUABLE_FILE = DATA_DIR / "o15_ft_jouables.tsv"
O25_FT_JOUABLE_FILE = DATA_DIR / "o25_ft_jouables.tsv"
TEAM1_WIN_JOUABLE_FILE = DATA_DIR / "team1_win_jouables.tsv"
TEAM2_WIN_JOUABLE_FILE = DATA_DIR / "team2_win_jouables.tsv"

MATCHS_FAILED_FILE = DATA_DIR / "matchs_failed.txt"

TICKETS_GLOBAL_REPORT = DATA_DIR / "tickets_report_global.txt"
TICKETS_O15_GLOBAL_REPORT = DATA_DIR / "tickets_o15_random_report_global.txt"
PICKS_GLOBAL_REPORT = DATA_DIR / "picks_report_global.txt"


# ============================================================================
# Helpers généraux (temps / jour)
# ============================================================================
def _time_to_minutes(t: str) -> int:
    try:
        hh, mm = (t or "").split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 10**9


def _weekday_fr(date_str: str) -> str:
    try:
        y, m, d = map(int, (date_str or "").split("-"))
        wd = __import__("datetime").date(y, m, d).weekday()
        return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][wd]
    except Exception:
        return ""


def _extract_odd_from_text(text: str) -> Optional[float]:
    """Extrait odd=1.23 d'un texte libre (commentaire, tsv, etc.)"""
    if not text:
        return None
    m = re.search(r"\bodd\s*=\s*([0-9]+(?:\.[0-9]+)?)\b", text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _fmt_odd(odd: Optional[float]) -> str:
    if isinstance(odd, (int, float)):
        try:
            v = float(odd)
            return f"{v:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return "—"
    return "—"


# ============================================================================
# Dates du run (à partir de matches_input.txt)
# ============================================================================
def parse_match_line(line: str) -> Tuple[str, str, str, str, str]:
    """
    Parse une ligne du type :
    YYYY-MM-DD | League Name | Home Team vs Away Team
    ou
    YYYY-MM-DD HH:MM | League Name | Home Team vs Away Team

    Retourne (date_str, time_str, league, home, away)
    """
    raw = line.strip()
    if not raw:
        raise ValueError("Ligne vide")

    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        raise ValueError(f"Format invalide (3 blocs attendus) : {raw}")

    date_block, league, teams = parts

    time_str = ""
    date_str = date_block
    if " " in date_block:
        first, rest = date_block.split(" ", 1)
        date_str = first.strip()
        time_str = rest.strip()

    teams_clean = teams.strip()

    m = re.split(r"\s+vs\s+", teams_clean, flags=re.IGNORECASE, maxsplit=1)
    if len(m) == 2:
        home, away = m[0].strip(), m[1].strip()
    elif " - " in teams_clean:
        home, away = [t.strip() for t in teams_clean.split(" - ", 1)]
    elif "-" in teams_clean:
        home, away = [t.strip() for t in teams_clean.split("-", 1)]
    else:
        raise ValueError(f"Impossible d'extraire les équipes : {teams}")

    return date_str, time_str, league, home, away


def get_run_dates_from_input() -> List[str]:
    """Retourne la liste triée des dates présentes dans matches_input (bulle si présent)."""
    dates: set[str] = set()

    if not INPUT_FILE.exists():
        return []

    with INPUT_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            try:
                date_str, _time_str, _league, _home, _away = parse_match_line(line)
                dates.add(date_str)
            except Exception:
                continue

    return sorted(dates)


# ============================================================================
# Helpers I/O (reports)
# ============================================================================
def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _append_text(path: Path, content: str) -> None:
    _ensure_dir(path)
    if path.exists() and path.stat().st_size > 0:
        path.write_text(path.read_text(encoding="utf-8") + "\n\n" + content, encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    _ensure_dir(path)
    path.write_text(content, encoding="utf-8")


# ============================================================================
# Filtrage predictions.tsv par date (SANS création de fichiers data/_predictions_*.tsv)
# ============================================================================
def _filter_predictions_lines_for_date(src: Path, target_date: str) -> List[str]:
    """
    Retourne les lignes TSV (avec séparateurs vides conservés) de predictions.tsv
    correspondant STRICTEMENT à target_date.
    Ne crée AUCUN fichier.

    ✅ IMPORTANT : les lignes vides (séparateurs) ne sont conservées QUE si elles
    précèdent une ligne TSV du jour ciblé (logique buffer/flush).
    """
    if not src.exists():
        return []

    out_lines: List[str] = []
    buffer: List[str] = []

    with src.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")

            # ligne vide → buffer (pas ajout direct)
            if not raw.strip():
                buffer.append("")
                continue

            if not raw.startswith("TSV:"):
                buffer.clear()
                continue

            parts = raw[4:].lstrip("\t ").split("\t")
            if not parts:
                buffer.clear()
                continue

            d = parts[1] if len(parts) > 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]) else parts[0]

            if d == target_date:
                out_lines.extend(buffer)
                buffer.clear()
                out_lines.append(raw)
            else:
                buffer.clear()

    if not any(l.strip() for l in out_lines):
        return []

    return out_lines


@contextmanager
def _temp_predictions_file_for_date(src: Path, target_date: str):
    """
    Crée un fichier temporaire système (ex: /tmp/...) contenant uniquement les lignes filtrées du jour.
    Le fichier est automatiquement supprimé à la fin du bloc.
    """
    lines = _filter_predictions_lines_for_date(src, target_date)
    if not lines:
        yield None
        return

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            suffix=".tsv",
        ) as tmp:
            tmp.write("\n".join(lines) + "\n")
            tmp_path = Path(tmp.name)

        yield tmp_path

    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


# ============================================================================
# Parse 1 ligne predictions.tsv (nouveau format)
# ============================================================================
def _parse_prediction_tsv_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse une ligne predictions.tsv (nouveau format attendu) :
    TSV: match_id date league home away bet_key metric score label is_candidate comment time
    """
    raw = (line or "").strip()
    if not raw.startswith("TSV:"):
        return None

    parts = raw[4:].lstrip("\t ").split("\t")
    if len(parts) < 12:
        return None

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
        return None

    match_id = parts[0].strip()
    date_s = parts[1].strip()
    league = parts[2].strip()
    home = parts[3].strip()
    away = parts[4].strip()
    bet_key = parts[5].strip().upper()
    metric = parts[6].strip()
    score = parts[7].strip()
    label = parts[8].strip()

    try:
        is_candidate = int(parts[9].strip() or "0")
    except Exception:
        is_candidate = 0

    comment = parts[10].strip()
    time_str = parts[11].strip()

    odd = _extract_odd_from_text(comment)

    fixture = None
    m2 = re.search(r"\bfixture\s*=\s*([0-9]+)\b", comment, flags=re.IGNORECASE)
    if m2:
        fixture = m2.group(1)

    return {
        "match_id": match_id,
        "date": date_s,
        "time": time_str,
        "league": league,
        "home": home,
        "away": away,
        "bet_key": bet_key,
        "metric": metric,
        "score": score,
        "label": label,
        "is_candidate": is_candidate,
        "odd": odd,
        "fixture": fixture,
        "comment": comment,
    }


# ============================================================================
# Reports : tickets + liste chronologique des paris jouables
# ============================================================================
def _generate_global_tickets_report_from_predictions() -> None:
    """
    Génère (append) les rapports humains globaux :
    - SYSTEM  -> data/tickets_report_global.txt
    - O15     -> data/tickets_o15_random_report_global.txt

    UNIQUEMENT pour les dates du run.
    """
    if not OUTPUT_TSV_FILE.exists() or OUTPUT_TSV_FILE.stat().st_size == 0:
        print("ℹ️ predictions.tsv absent/vide -> tickets global non générés.")
        return

    run_dates = get_run_dates_from_input() or [date.today().strftime("%Y-%m-%d")]

    any_sys = False
    any_o15 = False

    for d in run_dates:
        with _temp_predictions_file_for_date(OUTPUT_TSV_FILE, d) as tmp_path:
            if tmp_path is None or not tmp_path.exists() or tmp_path.stat().st_size == 0:
                print(f"ℹ️ Aucune prédiction pour {d} -> pas de tickets global.")
                continue

            try:
                out = generate_tickets_from_tsv(str(tmp_path))
            except Exception as e:
                print(f"⚠️ Erreur génération tickets (GLOBAL jour={d}) : {e}")
                continue

            if (out.report_system or "").strip():
                _append_text(TICKETS_GLOBAL_REPORT, out.report_system)
                any_sys = True

            if (out.report_o15 or "").strip():
                _append_text(TICKETS_O15_GLOBAL_REPORT, out.report_o15)
                any_o15 = True

    if any_sys:
        print(f"✅ Tickets (GLOBAL SYSTEM filtré sur dates du run) -> {TICKETS_GLOBAL_REPORT}")
    else:
        print("ℹ️ Aucun rapport tickets GLOBAL SYSTEM écrit (aucune date exploitable).")

    if any_o15:
        print(f"✅ Tickets (GLOBAL O15 filtré sur dates du run) -> {TICKETS_O15_GLOBAL_REPORT}")
    else:
        print("ℹ️ Aucun rapport tickets GLOBAL O15 écrit (aucune date exploitable).")


def _generate_global_picks_report_from_predictions() -> None:
    """
    Génère (append) un rapport global listant TOUS les paris jouables (is_candidate=1)
    triés par ordre chronologique, pour les dates du run.
    """
    if not OUTPUT_TSV_FILE.exists() or OUTPUT_TSV_FILE.stat().st_size == 0:
        print("ℹ️ predictions.tsv absent/vide -> picks report global non généré.")
        return

    run_dates = get_run_dates_from_input() or [date.today().strftime("%Y-%m-%d")]
    any_written = False

    for d in run_dates:
        with _temp_predictions_file_for_date(OUTPUT_TSV_FILE, d) as tmp_path:
            if tmp_path is None or not tmp_path.exists() or tmp_path.stat().st_size == 0:
                continue

            picks: List[Dict[str, Any]] = []
            with tmp_path.open("r", encoding="utf-8") as f:
                for line in f:
                    p = _parse_prediction_tsv_line(line)
                    if not p:
                        continue
                    if int(p.get("is_candidate") or 0) != 1:
                        continue
                    picks.append(p)

            if not picks:
                continue

            picks.sort(
                key=lambda x: (
                    _time_to_minutes(str(x.get("time") or "")),
                    str(x.get("league") or ""),
                    str(x.get("home") or ""),
                    str(x.get("away") or ""),
                    str(x.get("bet_key") or ""),
                )
            )

            day = _weekday_fr(d)
            day_part = f"{day} " if day else ""

            lines: List[str] = []
            title = f"PARIS JOUABLES — {day_part}{d}"
            lines.append(title)
            lines.append("=" * max(24, len(title)))
            lines.append("")

            grouped: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
            order: List[Tuple[str, str, str, str]] = []

            for p in picks:
                mk = (
                    str(p.get("time") or "--:--"),
                    str(p.get("league") or ""),
                    str(p.get("home") or ""),
                    str(p.get("away") or ""),
                )
                if mk not in grouped:
                    grouped[mk] = []
                    order.append(mk)
                grouped[mk].append(p)

            for mk in order:
                t, league, home, away = mk
                rk = RUN_RANKS.get((d, league, home, away))
                hr, ar = (rk[0], rk[1]) if rk else (None, None)

                lines.append(f"{t} | {league} | {_fmt_team_with_rank(home, hr)} vs {_fmt_team_with_rank(away, ar)}")

                for p in grouped.get(mk, []):
                    odd_s = _fmt_odd(p.get("odd") if isinstance(p.get("odd"), (int, float)) else None)
                    fixture = p.get("fixture") or ""
                    fixture_part = f" fixture={fixture}" if fixture else ""
                    lines.append(
                        f"  - {p.get('bet_key','')} | {p.get('metric','')} | {p.get('label','')} | odd={odd_s}{fixture_part}"
                    )

                lines.append("")

            report = "\n".join(lines).rstrip()
            _append_text(PICKS_GLOBAL_REPORT, report)
            any_written = True

    if any_written:
        print(f"✅ Paris jouables (GLOBAL filtré sur dates du run) -> {PICKS_GLOBAL_REPORT}")
    else:
        print("ℹ️ Aucun picks report global écrit (aucun pari jouable sur ces dates).")


def _generate_picks_report_from_predictions_file(pred_path: Path, target_date: str) -> Optional[str]:
    if not pred_path.exists() or pred_path.stat().st_size == 0:
        return None

    picks: List[Dict[str, Any]] = []
    with pred_path.open("r", encoding="utf-8") as f:
        for line in f:
            p = _parse_prediction_tsv_line(line)
            if not p:
                continue
            if int(p.get("is_candidate") or 0) != 1:
                continue
            picks.append(p)

    if not picks:
        return None

    picks.sort(
        key=lambda x: (
            _time_to_minutes(str(x.get("time") or "")),
            str(x.get("league") or ""),
            str(x.get("home") or ""),
            str(x.get("away") or ""),
            str(x.get("bet_key") or ""),
        )
    )

    day = _weekday_fr(target_date)
    day_part = f"{day} " if day else ""

    lines: List[str] = []
    title = f"PARIS JOUABLES — {day_part}{target_date}"
    lines.append(title)
    lines.append("=" * max(24, len(title)))
    lines.append("")

    grouped: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    order: List[Tuple[str, str, str, str]] = []

    for p in picks:
        mk = (
            str(p.get("time") or "--:--"),
            str(p.get("league") or ""),
            str(p.get("home") or ""),
            str(p.get("away") or ""),
        )
        if mk not in grouped:
            grouped[mk] = []
            order.append(mk)
        grouped[mk].append(p)

    for mk in order:
        t, league, home, away = mk
        rk = RUN_RANKS.get((target_date, league, home, away))
        hr, ar = (rk[0], rk[1]) if rk else (None, None)

        lines.append(f"{t} | {league} | {_fmt_team_with_rank(home, hr)} vs {_fmt_team_with_rank(away, ar)}")

        for p in grouped.get(mk, []):
            odd_s = _fmt_odd(p.get("odd") if isinstance(p.get("odd"), (int, float)) else None)
            fixture = p.get("fixture") or ""
            fixture_part = f" fixture={fixture}" if fixture else ""
            lines.append(f"  - {p.get('bet_key','')} | {p.get('metric','')} | {p.get('label','')} | odd={odd_s}{fixture_part}")

        lines.append("")

    return "\n".join(lines).rstrip()


# ============================================================================
# Utilitaires archive (filtrage par date dans les TSV)
# ============================================================================
def _archive_tsv_for_date(
    src: Path,
    dst: Path,
    target_date: str,
    *,
    is_predictions: bool = False,
) -> None:
    if not src.exists():
        return

    lines_out: List[str] = []

    with src.open("r", encoding="utf-8") as f:
        buffer: List[str] = []

        for line in f:
            raw = line.rstrip("\n")

            if not raw.strip():
                buffer.append("")
                continue

            if not raw.startswith("TSV:"):
                continue

            parts = raw[4:].lstrip("\t ").split("\t")
            if not parts:
                continue

            if is_predictions:
                d = parts[1] if len(parts) > 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]) else parts[0]
            else:
                d = parts[0]

            if d == target_date:
                lines_out.extend(buffer)
                buffer.clear()
                lines_out.append(raw)
            else:
                buffer.clear()

    if not lines_out:
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def archive_main_outputs() -> None:
    run_dates = get_run_dates_from_input()
    if not run_dates:
        run_dates = [date.today().strftime("%Y-%m-%d")]

    base_dir = _resolve_archive_dir_for_date(run_dates[0])

    multiple_dates = (len(run_dates) > 1)
    if multiple_dates:
        print(f"📦 Multi-dates détectées ({len(run_dates)}). Sous-dossiers par date dans {base_dir}.")

    for target_date in run_dates:
        archive_dir = (base_dir / f"analyse_{target_date}") if multiple_dates else base_dir
        archive_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n📦 Archivage des fichiers (vue JOUR {target_date}) dans {archive_dir} ...")

        day_predictions_path = archive_dir / "predictions.tsv"
        _archive_tsv_for_date(OUTPUT_TSV_FILE, day_predictions_path, target_date, is_predictions=True)

        _archive_tsv_for_date(HT05_JOUABLE_FILE, archive_dir / "ht05_jouables.tsv", target_date)
        _archive_tsv_for_date(HT1X_HOME_JOUABLE_FILE, archive_dir / "ht1x_home_jouables.tsv", target_date)
        _archive_tsv_for_date(TEAM1_SCORE_JOUABLE_FILE, archive_dir / "team1_score_jouables.tsv", target_date)
        _archive_tsv_for_date(TEAM2_SCORE_JOUABLE_FILE, archive_dir / "team2_score_jouables.tsv", target_date)

        _archive_tsv_for_date(O15_FT_JOUABLE_FILE, archive_dir / "o15_ft_jouables.tsv", target_date)
        _archive_tsv_for_date(O25_FT_JOUABLE_FILE, archive_dir / "o25_ft_jouables.tsv", target_date)
        _archive_tsv_for_date(TEAM1_WIN_JOUABLE_FILE, archive_dir / "team1_win_jouables.tsv", target_date)
        _archive_tsv_for_date(TEAM2_WIN_JOUABLE_FILE, archive_dir / "team2_win_jouables.tsv", target_date)

        _archive_tsv_for_date(DATA_DIR / "results.tsv", archive_dir / "results.tsv", target_date)
        _archive_tsv_for_date(DATA_DIR / "verdict_post_analyse.txt", archive_dir / "verdict_post_analyse.txt", target_date)

        if day_predictions_path.exists() and day_predictions_path.stat().st_size > 0:
            try:
                out = generate_tickets_from_tsv(str(day_predictions_path))

                sys_report = (out.report_system or "").strip()
                if sys_report:
                    tickets_day_path = archive_dir / "tickets_report.txt"
                    _write_text(tickets_day_path, out.report_system)
                    print(f"   ➜ {tickets_day_path} (rapport tickets SYSTEM)")
                else:
                    print("   ⚠️ Report SYSTEM vide -> tickets_report.txt non écrit.")

                o15_report = (out.report_o15 or "").strip()
                if o15_report:
                    o15_day_path = archive_dir / "tickets_o15_random_report.txt"
                    _write_text(o15_day_path, out.report_o15)
                    print(f"   ➜ {o15_day_path} (rapport tickets O15 RANDOM)")
                else:
                    print("   ⚠️ Report O15 RANDOM vide -> tickets_o15_random_report.txt non écrit.")

            except Exception as e:
                print(f"   ⚠️ Erreur génération tickets (JOUR {target_date}) : {e}")
        else:
            print(f"   ℹ️ Pas de predictions.tsv filtré pour {target_date} -> tickets reports non générés.")

        if day_predictions_path.exists() and day_predictions_path.stat().st_size > 0:
            try:
                report_picks_day = _generate_picks_report_from_predictions_file(day_predictions_path, target_date)
                if report_picks_day:
                    picks_day_path = archive_dir / "picks_report.txt"
                    _write_text(picks_day_path, report_picks_day)
                    print(f"   ➜ {picks_day_path} (picks report)")
                else:
                    print(f"   ℹ️ Aucun pari jouable (JOUR {target_date}) -> picks_report non généré.")
            except Exception as e:
                print(f"   ⚠️ Erreur génération picks report (JOUR {target_date}) : {e}")

        raw_files = [
            INPUT_FILE,
            MATCHS_FAILED_FILE,
            DATA_DIR / "post_matches_failed.txt",
        ]

        for src in raw_files:
            if src.exists() and src.stat().st_size > 0:
                dst = archive_dir / src.name
                try:
                    shutil.copy2(src, dst)
                    print(f"   ➜ {dst} (copie brute)")
                except Exception as e:
                    print(f"   ⚠️ Impossible de copier {src} : {e}")
            else:
                print(f"   ℹ️ Fichier absent ou vide, non archivé : {src}")

    print("📁 Archivage terminé.\n")


# ============================================================================
# Parsing des matchs
# ============================================================================
def read_matches(path: Path) -> List[Tuple[str, str, str, str, str]]:
    matches: List[Tuple[str, str, str, str, str]] = []

    if not path.exists():
        print(f"⚠️ Fichier d'input introuvable : {path}")
        return matches

    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            try:
                date_str, time_str, league, home, away = parse_match_line(line)
                matches.append((date_str, time_str, league, home, away))
            except ValueError as e:
                print(f"⚠️ Ligne {idx} ignorée ({e}) : {line}")

    return matches


def build_match_input_line(date_str: str, time_str: str, league: str, home: str, away: str) -> str:
    if time_str:
        return f"{date_str} {time_str} | {league} | {home} vs {away}"
    return f"{date_str} | {league} | {home} vs {away}"


# ============================================================================
# Jouables cumulés (par pari) – tri par date puis heure, puis cote desc
# ============================================================================
BetEntry = Tuple[Tuple[str, str, str, str, str], float, str, Optional[float]]


def write_sorted_bet_file(
    filepath: Path,
    metric: str,
    entries: List[BetEntry],
) -> None:
    MIN_ODD = 1.15

    def parse_existing_line(line: str):
        line = line.rstrip("\n")
        if not line.startswith("TSV:"):
            return None

        raw = line[4:].lstrip("\t ")
        if not raw.strip():
            return None

        parts = raw.split("\t")

        if len(parts) >= 9 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
            date_str, time_str, league, home, away, met, score_str, label, odd_str = parts[:9]
            try:
                score = float(score_str)
            except Exception:
                return None

            odd = None
            try:
                odd = float(odd_str) if odd_str not in {"", "—"} else None
            except Exception:
                pass

            home = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", home).strip()
            away = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", away).strip()

            key = (date_str, league, home, away, met)
            return key, score, label, time_str, odd

        return None

    if not entries:
        return

    filepath.parent.mkdir(parents=True, exist_ok=True)

    records: Dict[Tuple[str, str, str, str, str], Tuple[float, str, str, Optional[float]]] = {}

    if filepath.exists():
        with filepath.open("r", encoding="utf-8") as f:
            for line in f:
                parsed = parse_existing_line(line)
                if parsed:
                    key, score, label, time_str, odd = parsed
                    records[key] = (score, label, time_str, odd)

    for (date_s, time_s, league, home, away), score, label, odd in entries:
        if isinstance(odd, (int, float)) and odd < MIN_ODD:
            continue

        key = (date_s, league, home, away, metric)
        old = records.get(key)

        if not old or score > old[0] or (score == old[0] and (odd or 0) > (old[3] or 0)):
            records[key] = (score, label or "", time_s or "", odd)

    rows = []
    for (date_s, league, home, away, met), (score, label, time_s, odd) in records.items():
        rk = RUN_RANKS.get((date_s, league, home, away))
        hr, ar = rk if rk else (None, None)

        home_disp = _fmt_team_with_rank(home, hr)
        away_disp = _fmt_team_with_rank(away, ar)
        odd_s = _fmt_odd(odd)

        line = (
            f"TSV:\t{date_s}\t{time_s}\t{league}\t"
            f"{home_disp} vs {away_disp}\t{met}\t{score}\t{label}\t{odd_s}"
        )

        rows.append((date_s, time_s, -(odd or 0), -score, line))

    rows.sort(key=lambda x: (x[0], _time_to_minutes(x[1]), x[2], x[3]))

    with filepath.open("w", encoding="utf-8") as f:
        last_date = last_time = None
        for d, t, *_rest, line in rows:
            if last_date is not None:
                if d != last_date:
                    f.write("\n\n")
                    last_time = None
                elif t != last_time:
                    f.write("\n")
            f.write(line + "\n")
            last_date, last_time = d, t


def _normalize_multi_bet_result(result: Dict[str, Any]) -> Dict[str, Any]:
    bets = result.get("bets")
    if isinstance(bets, list) and bets:
        return {"rapport": result.get("rapport", ""), "bets": bets}
    return {"rapport": result.get("rapport", ""), "bets": [], "single_tsv": result.get("tsv")}


def main() -> None:
    print("=== Analyse Triskèle – lancement ===")
    print(f"📄 INPUT source : {INPUT_FILE}")

    matches = read_matches(INPUT_FILE)
    if not matches:
        print("⚠️ Aucun match à analyser (fichier vide ou introuvable).")
        return

    total_matches = len(matches)
    analyzed_ok = 0

    failed_matches: List[Tuple[str, str, str, str, str, str]] = []
    tsv_records: List[Tuple[Tuple[str, str, str, str], str, str]] = []

    ht05_candidates: List[BetEntry] = []
    ht1x_home_candidates: List[BetEntry] = []
    team1_score_candidates: List[BetEntry] = []
    team2_score_candidates: List[BetEntry] = []

    o15_candidates: List[BetEntry] = []
    o25_candidates: List[BetEntry] = []
    team1_win_candidates: List[BetEntry] = []
    team2_win_candidates: List[BetEntry] = []

    LEVEL_SCORE = {
        "KO": 0,
        "FAIBLE": 1,
        "MOYEN": 2,
        "MOYEN PLUS": 3,
        "FORT": 4,
        "FORT PLUS": 5,
        "TRÈS FORT": 6,
        "EXPLOSION": 7,
        "MEGA EXPLOSION": 8,
    }

    for (date_str, time_str, league, home, away) in matches:
        print("\n" + "=" * 80)
        display_date = f"{date_str} {time_str}" if time_str else date_str
        print(f"Analyse du match : {home} vs {away} ({league}, {display_date})")
        print("=" * 80)

        data = fetch_match_data(league=league, date=date_str, home=home, away=away)
        if not data:
            print("❌ Échec de la collecte API pour ce match. Passage au suivant.")
            failed_matches.append((date_str, time_str, league, home, away, "API_COLLECT_FAILED"))
            continue

        context = data.get("context") or {}
        home_standing = context.get("home_standing") or {}
        away_standing = context.get("away_standing") or {}
        hr = home_standing.get("rank")
        ar = away_standing.get("rank")
        RUN_RANKS[(date_str, league, home, away)] = (hr, ar)

        try:
            raw_result = run_full_analysis(home, away, data)
        except Exception as e:
            print(f"❌ Erreur pendant l'analyse du match : {e}")
            failed_matches.append((date_str, time_str, league, home, away, f"ANALYSIS_ERROR: {e}"))
            continue

        normalized = _normalize_multi_bet_result(raw_result)
        rapport = (normalized.get("rapport") or "").strip()
        bets = normalized.get("bets") or []
        if not isinstance(bets, list):
            bets = []

        if not rapport:
            print("❌ Rapport vide / invalide. Passage au suivant.")
            failed_matches.append((date_str, time_str, league, home, away, "EMPTY_REPORT"))
            continue

        analyzed_ok += 1

        print("\n--- RAPPORT ---\n")
        print(rapport)

        key = (date_str, league, home, away)

        if bets:
            for b in bets:
                tsv_line = b.get("tsv")
                if isinstance(tsv_line, str) and tsv_line.strip():
                    tsv_records.append((key, tsv_line, time_str))
        else:
            single_tsv = normalized.get("single_tsv")
            if isinstance(single_tsv, str) and single_tsv.strip():
                tsv_records.append((key, single_tsv, time_str))

        for b in bets:
            raw_key = (b.get("key") or "").strip().upper()
            canon_key = CANON.get(raw_key)
            if not canon_key:
                continue

            if not bool(b.get("is_candidate")):
                continue

            label_base = (b.get("label") or "").strip()

            rk = RUN_RANKS.get((date_str, league, home, away))
            label = _label_with_ranks(label_base, rk[0], rk[1]) if rk else label_base

            try:
                score_f = float(b.get("score"))
            except Exception:
                score_f = float(LEVEL_SCORE.get(label_base, 0))

            odd_val: Optional[float] = None
            if isinstance(b.get("odd"), (int, float)):
                try:
                    odd_val = float(b.get("odd"))
                except Exception:
                    odd_val = None
            if odd_val is None:
                odd_val = _extract_odd_from_text(str(b.get("comment") or ""))
            if odd_val is None:
                odd_val = _extract_odd_from_text(str(b.get("tsv") or ""))

            if isinstance(odd_val, (int, float)) and float(odd_val) < MIN_ODD_JOUABLE:
                continue

            match_key_with_time = (date_str, (time_str or ""), league, home, away)

            if canon_key == "HT05":
                ht05_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "HT1X_HOME":
                ht1x_home_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "TEAM1_SCORE_FT":
                team1_score_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "TEAM2_SCORE_FT":
                team2_score_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "O15_FT":
                o15_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "O25_FT":
                o25_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "TEAM1_WIN_FT":
                team1_win_candidates.append((match_key_with_time, score_f, label, odd_val))
            elif canon_key == "TEAM2_WIN_FT":
                team2_win_candidates.append((match_key_with_time, score_f, label, odd_val))

    new_lines_count = 0

    if tsv_records:
        OUTPUT_TSV_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing_keys: set[Tuple[str, str, str, str, str]] = set()
        if OUTPUT_TSV_FILE.exists():
            with OUTPUT_TSV_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw.startswith("TSV:"):
                        continue

                    key_line = raw[4:].lstrip("\t ")
                    parts = key_line.split("\t")

                    bet_key = ""
                    if len(parts) >= 6 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
                        date_s, league_s, home_s, away_s, bet_key = parts[1:6]
                    elif len(parts) >= 5 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
                        date_s, league_s, home_s, away_s, bet_key = parts[0:5]
                    else:
                        continue

                    existing_keys.add((date_s, league_s, home_s, away_s, bet_key))

        new_lines: List[str] = []
        new_keys_in_this_run: set[Tuple[str, str, str, str, str]] = set()

        for (date_s, league_s, home_s, away_s), line, time_s in tsv_records:
            bet_key = ""
            if line.startswith("TSV:"):
                raw = line[4:].lstrip("\t ")
                parts = raw.split("\t")
                if len(parts) >= 6 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
                    bet_key = parts[5]
                elif len(parts) >= 5 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    bet_key = parts[4]

            dedup_key = (date_s, league_s, home_s, away_s, bet_key)

            if dedup_key in existing_keys or dedup_key in new_keys_in_this_run:
                print(f"ℹ️ Déjà présent (pas de doublon) : {dedup_key}")
                continue

            new_keys_in_this_run.add(dedup_key)

            line_with_time = f"{line}\t{time_s}" if time_s else line
            new_lines.append(line_with_time)

        new_lines_count = len(new_lines)

        if not new_lines:
            print("\nℹ️ Aucun nouveau TSV à ajouter (tous ces matchs/paris sont déjà dans l'historique).")
        else:
            with OUTPUT_TSV_FILE.open("a", encoding="utf-8") as f:
                for l in new_lines:
                    f.write(l + "\n")
            print(f"\n✅ {new_lines_count} nouveaux TSV ont été enregistrés dans {OUTPUT_TSV_FILE}")
    else:
        print("\n⚠️ Aucun TSV généré (aucun match analysé avec succès).")

    if ht05_candidates:
        write_sorted_bet_file(HT05_JOUABLE_FILE, metric="HT+0.5", entries=ht05_candidates)
    else:
        print("\nℹ️ Aucun +0.5 HT jouable détecté sur cette série.")

    if ht1x_home_candidates:
        write_sorted_bet_file(HT1X_HOME_JOUABLE_FILE, metric="HT 1X Home", entries=ht1x_home_candidates)
    else:
        print("\nℹ️ Aucun 1X HT domicile jouable détecté sur cette série.")

    if team1_score_candidates:
        write_sorted_bet_file(TEAM1_SCORE_JOUABLE_FILE, metric="Team1 scores (FT)", entries=team1_score_candidates)
    else:
        print("\nℹ️ Aucun TEAM1 marque (FT) jouable détecté sur cette série.")

    if team2_score_candidates:
        write_sorted_bet_file(TEAM2_SCORE_JOUABLE_FILE, metric="Team2 scores (FT)", entries=team2_score_candidates)
    else:
        print("\nℹ️ Aucun TEAM2 marque (FT) jouable détecté sur cette série.")

    if o15_candidates:
        write_sorted_bet_file(O15_FT_JOUABLE_FILE, metric="Over 15 (FT)", entries=o15_candidates)
    else:
        print("\nℹ️ Aucun Over 1.5 (FT) jouable détecté sur cette série.")

    if o25_candidates:
        write_sorted_bet_file(O25_FT_JOUABLE_FILE, metric="Over 25 (FT)", entries=o25_candidates)
    else:
        print("\nℹ️ Aucun Over 2.5 (FT) jouable détecté sur cette série.")

    if team1_win_candidates:
        write_sorted_bet_file(TEAM1_WIN_JOUABLE_FILE, metric="Team1 wins (FT)", entries=team1_win_candidates)
    else:
        print("\nℹ️ Aucun TEAM1 gagne (FT) jouable détecté sur cette série.")

    if team2_win_candidates:
        write_sorted_bet_file(TEAM2_WIN_JOUABLE_FILE, metric="Team2 wins (FT)", entries=team2_win_candidates)
    else:
        print("\nℹ️ Aucun TEAM2 gagne (FT) jouable détecté sur cette série.")

    MATCHS_FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MATCHS_FAILED_FILE.open("w", encoding="utf-8") as f:
        if not failed_matches:
            f.write("# Aucun match échoué sur cette série.\n")
        else:
            f.write("# Fichier relançable : copie/colle ces lignes dans matches_input.txt\n")
            f.write("# (Les lignes '# reason:' sont ignorées par le parser)\n\n")
            for date_str, time_str, league, home, away, reason in failed_matches:
                f.write(f"# reason: {reason}\n")
                f.write(build_match_input_line(date_str, time_str, league, home, away) + "\n\n")

    failed_count = len(failed_matches)
    print("\n=== BILAN GLOBAL ===")
    print(f"Matchs demandés : {total_matches}")
    print(f"Analyses réussies : {analyzed_ok}/{total_matches}")
    print(f"Matchs échoués   : {failed_count}")
    print(f"Nouveaux TSV ajoutés : {new_lines_count}")
    print(f"Fichier des matchs échoués : {MATCHS_FAILED_FILE}")

    archive_main_outputs()


if __name__ == "__main__":
    main()
