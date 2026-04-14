import streamlit as st
import pandas as pd
import subprocess
import os
import re
import sys
import inspect
import json
import copy
from pathlib import Path
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

# Racine du projet: remonte de tools/audit -> projet
ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "archive"
APP_VERSION = "BUILD_2026_02_27_V1"

# ── Helpers rankings (inline, pas d'import externe) ──────────────────────────

def _pct(x) -> str:
    try:
        return f"{100.0 * float(x):.1f}%"
    except Exception:
        return ""

def _to_int_s(s) -> int:
    try:
        return int(float(str(s).strip())) if str(s).strip() else 0
    except Exception:
        return 0

def _to_float_s(s) -> float:
    try:
        return float(str(s).strip().replace(",", ".")) if str(s).strip() else 0.0
    except Exception:
        return 0.0

def _render_table(df: pd.DataFrame, percent_cols=None, height: int = 520):
    if df.empty:
        st.info("Aucune donnée.")
        return
    view = df.copy()
    for c in (percent_cols or []):
        if c in view.columns:
            view[c] = view[c].apply(lambda x: _pct(x) if not isinstance(x, str) else x)
    st.dataframe(view, use_container_width=True, height=height)

def _standardize_baseline_league_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])
    if df is None or df.empty:
        return empty
    cols = {str(c).strip().lstrip("#").strip().lower(): c for c in df.columns}
    # format A : samples/success/fail
    if {"league", "bet_key", "samples", "success", "fail"}.issubset(cols):
        out = pd.DataFrame()
        out["league"]   = df[cols["league"]].astype(str).str.strip()
        out["bet_key"]  = df[cols["bet_key"]].astype(str).str.strip().str.upper()
        out["decided"]  = df[cols["samples"]].apply(_to_int_s)
        out["wins"]     = df[cols["success"]].apply(_to_int_s)
        out["losses"]   = df[cols["fail"]].apply(_to_int_s)
        sr = df[cols["success_rate"]].apply(_to_float_s) if "success_rate" in cols else None
        out["win_rate"] = sr.apply(lambda x: x / 100.0 if x > 1.00001 else x) if sr is not None \
                          else out.apply(lambda r: r["wins"] / r["decided"] if r["decided"] > 0 else 0.0, axis=1)
        return out
    # format B : decided/wins/losses
    if {"league", "bet_key", "decided", "wins", "losses"}.issubset(cols):
        out = pd.DataFrame()
        out["league"]   = df[cols["league"]].astype(str).str.strip()
        out["bet_key"]  = df[cols["bet_key"]].astype(str).str.strip().str.upper()
        out["decided"]  = df[cols["decided"]].apply(_to_int_s)
        out["wins"]     = df[cols["wins"]].apply(_to_int_s)
        out["losses"]   = df[cols["losses"]].apply(_to_int_s)
        out["win_rate"] = df[cols["win_rate"]].apply(_to_float_s) if "win_rate" in cols \
                          else out.apply(lambda r: r["wins"] / r["decided"] if r["decided"] > 0 else 0.0, axis=1)
        return out
    return empty

def _standardize_baseline_team_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"])
    if df is None or df.empty:
        return empty
    cols = {str(c).strip().lstrip("#").strip().lower(): c for c in df.columns}
    # format A
    if {"league", "team", "bet_key", "samples", "success", "fail"}.issubset(cols):
        out = pd.DataFrame()
        out["league"]   = df[cols["league"]].astype(str).str.strip()
        out["team"]     = df[cols["team"]].astype(str).str.strip()
        out["bet_key"]  = df[cols["bet_key"]].astype(str).str.strip().str.upper()
        out["decided"]  = df[cols["samples"]].apply(_to_int_s)
        out["wins"]     = df[cols["success"]].apply(_to_int_s)
        out["losses"]   = df[cols["fail"]].apply(_to_int_s)
        sr = df[cols["success_rate"]].apply(_to_float_s) if "success_rate" in cols else None
        out["win_rate"] = sr.apply(lambda x: x / 100.0 if x > 1.00001 else x) if sr is not None \
                          else out.apply(lambda r: r["wins"] / r["decided"] if r["decided"] > 0 else 0.0, axis=1)
        return out
    # format B
    if {"team", "bet_key", "decided", "wins", "losses"}.issubset(cols):
        out = pd.DataFrame()
        out["league"]   = df[cols["league"]].astype(str).str.strip() if "league" in cols else ""
        out["team"]     = df[cols["team"]].astype(str).str.strip()
        out["bet_key"]  = df[cols["bet_key"]].astype(str).str.strip().str.upper()
        out["decided"]  = df[cols["decided"]].apply(_to_int_s)
        out["wins"]     = df[cols["wins"]].apply(_to_int_s)
        out["losses"]   = df[cols["losses"]].apply(_to_int_s)
        out["win_rate"] = df[cols["win_rate"]].apply(_to_float_s) if "win_rate" in cols \
                          else out.apply(lambda r: r["wins"] / r["decided"] if r["decided"] > 0 else 0.0, axis=1)
        return out
    return empty

st.set_page_config(page_title="⚡️🤖 Machine TreeSkale", page_icon="⚡️", layout="wide")

st.title("⚡️ Machine TreeSkale")
st.markdown("Interface pour générer et consulter les tickets (System & Random) avec statut ✅/❌/⏳ quand dispo.")


# -----------------------------
# Helpers: archives / périodes
# -----------------------------
def parse_analyse_dir_date(p: Path) -> date | None:
    m = re.match(r"analyse_(\d{4}-\d{2}-\d{2})$", p.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def list_analyse_dirs() -> list[tuple[date, Path]]:
    """Liste tous les dossiers archive/analyse_YYYY-MM-DD triés par date (desc)."""
    if not ARCHIVE_DIR.exists():
        return []
    out = []
    for d in ARCHIVE_DIR.iterdir():
        if not d.is_dir():
            continue
        dt = parse_analyse_dir_date(d)
        if dt:
            out.append((dt, d))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def latest_analyse_dir() -> Path | None:
    dirs = list_analyse_dirs()
    return dirs[0][1] if dirs else None


def compute_period_range(label: str) -> tuple[date | None, date | None]:
    """Retourne (start, end) inclusifs. None/None => all time."""
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    if label == "Veille":
        y = today - timedelta(days=1)
        return y, y
    if label == "10 derniers jours":
        return today - timedelta(days=9), today
    if label == "30 derniers jours":
        return today - timedelta(days=29), today
    if label == "All time":
        return None, None
    return None, None


def in_range(d: date, start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return True
    return start <= d <= end


def style_status_cell(val):
    if val == "✅":
        return "background-color: #1f7a1f; color: white; font-weight: 700;"
    if val == "❌":
        return "background-color: #b3261e; color: white; font-weight: 700;"
    if val == "⏳":
        return "background-color: #4b5563; color: white; font-weight: 700;"
    return ""


# -----------------------------
# Martingale computation
# -----------------------------
def _base_stake_mart(bankroll: float, max_losses: int) -> float:
    if bankroll <= 0:
        return 0.0
    denom = (2 ** max(0, max_losses)) - 1
    return bankroll / float(denom) if denom > 0 else bankroll


def compute_martingale_stakes(df: pd.DataFrame, bankroll0: float, max_losses: int) -> pd.DataFrame:
    """
    Ajoute Mise_NORM et Mise_SAFE à df (trié chronologiquement).
    Statut ✅ = WIN, ❌ = LOSS, ⏳ = PENDING (on affiche la mise prévue, sans avancer l'état).
    """
    if df.empty:
        return df

    out = df.copy()
    out["Mise_NORM"] = None
    out["Mise_SAFE"] = None

    # ── NORMALE ──────────────────────────────────────────────
    bk = float(bankroll0)
    prev_stake_n = 0.0
    loss_streak_n = 0
    for idx in out.index:
        if bk <= 0:
            break
        odd = float(out.at[idx, "Cote"]) if out.at[idx, "Cote"] else 2.0
        base = _base_stake_mart(bk, max_losses)
        stake = base if loss_streak_n == 0 else prev_stake_n * 2.0
        stake = round(min(stake, bk), 2)
        out.at[idx, "Mise_NORM"] = stake
        statut = str(out.at[idx, "Statut"] or "")
        if "✅" in statut:
            bk += stake * (odd - 1.0)
            loss_streak_n = 0
        elif "❌" in statut:
            bk -= stake
            loss_streak_n += 1
        # ⏳ : ne pas avancer l'état
        prev_stake_n = stake

    # ── SAFE ─────────────────────────────────────────────────
    B0 = float(bankroll0)
    reserves = 0.0

    def _cycle_base_s() -> float:
        return B0 + 0.20 * reserves

    bk_active = _cycle_base_s()
    cycle_base = bk_active
    prev_stake_s = 0.0
    loss_streak_s = 0
    denom_s = float((2 ** max(0, max_losses)) - 1) or 1.0

    for idx in out.index:
        if bk_active <= 0:
            break
        odd = float(out.at[idx, "Cote"]) if out.at[idx, "Cote"] else 2.0
        base = bk_active / denom_s
        stake = base if loss_streak_s == 0 else prev_stake_s * 2.0
        stake = round(min(stake, bk_active), 2)
        out.at[idx, "Mise_SAFE"] = stake
        statut = str(out.at[idx, "Statut"] or "")
        if "✅" in statut:
            bk_active += stake * (odd - 1.0)
            loss_streak_s = 0
            if bk_active >= cycle_base * 2.0:
                reserves += bk_active - cycle_base
                bk_active = _cycle_base_s()
                cycle_base = bk_active
        elif "❌" in statut:
            bk_active -= stake
            loss_streak_s += 1
        prev_stake_s = stake

    return out


# -----------------------------
# Parsing tickets (reports)
# -----------------------------
def parse_tickets_to_play(filepath: Path | str, fallback_day: date | None = None):
    """Parse un fichier de tickets générés (tickets_report.txt / tickets_o15_random_report.txt)."""
    filepath = Path(filepath)
    if not filepath.exists():
        return None

    content = filepath.read_text(encoding="utf-8", errors="replace")

    ticket_pattern = re.compile(
        r"🎟️ (TICKET [0-9.]+) \((.*?)\) — id=(.*?) — cote = ([0-9.]+) — fenêtre (.*?)\s*.*?\n(.*?)(?=🎟️|📅|$)",
        re.DOTALL
    )

    data = []
    for ordre_source, match in enumerate(ticket_pattern.finditer(content), start=1):
        ticket_id = match.group(3).strip()
        matches_text = match.group(6).strip()
        nb_matches = len(re.findall(r"^\s*\d+\)", matches_text, re.MULTILINE))

        # Jour: on essaie de le déduire de l'id (ex: 2026-01-28_....)
        day_val = None
        mday = re.match(r"(\d{4}-\d{2}-\d{2})_", ticket_id)
        if mday:
            try:
                day_val = datetime.strptime(mday.group(1), "%Y-%m-%d").date()
            except ValueError:
                day_val = None

        if day_val is None and fallback_day is not None:
            day_val = fallback_day

        data.append({
            "Jour": day_val,
            "OrdreSource": ordre_source,
            "Ticket": match.group(1),
            "Type": match.group(2),
            "Id": _normalize_ticket_id(ticket_id),
            "Cote": float(match.group(4)),
            "Fenêtre de jeu": match.group(5).strip(),
            "Nb Matchs": nb_matches,
            "Détail": matches_text,
            "Source": str(filepath)
        })

    if data:
        return pd.DataFrame(data)

    return None

def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Retourne le premier nom de colonne présent dans df parmi les candidats."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _normalize_ticket_id(val) -> str | None:
    """Normalise un identifiant pour merge fiable."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def _safe_read_tsv(path: Path) -> pd.DataFrame | None:
    """Lit un TSV sans casser l'app si le fichier est mal formé."""
    try:
        return pd.read_csv(path, sep="\t", dtype=str, encoding="utf-8", engine="python")
    except Exception:
        return None


def _build_datetime_from_tsv_row(row, date_col: str | None, time_col: str | None, datetime_col: str | None):
    """
    Construit un timestamp depuis :
    - une colonne datetime directe
    - ou une colonne date + une colonne heure
    Retourne pd.NaT si impossible.
    """
    if datetime_col:
        raw_dt = row.get(datetime_col)
        if pd.notna(raw_dt):
            ts = pd.to_datetime(str(raw_dt).strip(), errors="coerce", dayfirst=False)
            if pd.notna(ts):
                return ts

    if date_col and time_col:
        raw_date = row.get(date_col)
        raw_time = row.get(time_col)
        if pd.notna(raw_date) and pd.notna(raw_time):
            raw = f"{str(raw_date).strip()} {str(raw_time).strip()}"
            ts = pd.to_datetime(raw, errors="coerce", dayfirst=False)
            if pd.notna(ts):
                return ts

    return pd.NaT


def collect_ticket_datetime_mapping_from_tsv(period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Construit une table de correspondance:
    Id | DateTimeTSV

    La fonction scanne les TSV dans :
    - archive/analyse_YYYY-MM-DD/
    - ROOT/data/
    - ROOT/

    IMPORTANT :
    Adapte les listes *_CANDIDATES si tes noms de colonnes diffèrent.
    """

    TSV_FILE_CANDIDATES = [
        "matches_meta.tsv",
        "tickets_meta.tsv",
        "matches.tsv",
        "meta.tsv",
    ]

    ID_COL_CANDIDATES = [
        "Id", "id", "ticket_id", "ticketId", "ticket_id_ref", "ticket_ref"
    ]

    DATETIME_COL_CANDIDATES = [
        "DateTime", "datetime", "match_datetime", "kickoff_datetime", "event_datetime"
    ]

    DATE_COL_CANDIDATES = [
        "Jour", "jour", "Date", "date", "match_date", "event_date"
    ]

    TIME_COL_CANDIDATES = [
        "Heure", "heure", "Time", "time", "match_time", "event_time", "kickoff_time"
    ]

    frames = []

    # 1) archives
    for dday, dpath in list_analyse_dirs():
        if not in_range(dday, period_start, period_end):
            continue

        for filename in TSV_FILE_CANDIDATES:
            tsv_path = dpath / filename
            if not tsv_path.exists():
                continue

            df = _safe_read_tsv(tsv_path)
            if df is None or df.empty:
                continue

            id_col = _first_existing_col(df, ID_COL_CANDIDATES)
            dt_col = _first_existing_col(df, DATETIME_COL_CANDIDATES)
            date_col = _first_existing_col(df, DATE_COL_CANDIDATES)
            time_col = _first_existing_col(df, TIME_COL_CANDIDATES)

            if not id_col:
                continue
            if not dt_col and not (date_col and time_col):
                continue

            tmp = df.copy()
            tmp["Id"] = tmp[id_col].apply(_normalize_ticket_id)
            tmp["DateTimeTSV"] = tmp.apply(
                lambda row: _build_datetime_from_tsv_row(row, date_col, time_col, dt_col),
                axis=1
            )
            tmp = tmp[tmp["Id"].notna() & tmp["DateTimeTSV"].notna()][["Id", "DateTimeTSV"]]
            if not tmp.empty:
                frames.append(tmp)

    # 2) data/
    for filename in TSV_FILE_CANDIDATES:
        tsv_path = ROOT / "data" / filename
        if not tsv_path.exists():
            continue

        df = _safe_read_tsv(tsv_path)
        if df is None or df.empty:
            continue

        id_col = _first_existing_col(df, ID_COL_CANDIDATES)
        dt_col = _first_existing_col(df, DATETIME_COL_CANDIDATES)
        date_col = _first_existing_col(df, DATE_COL_CANDIDATES)
        time_col = _first_existing_col(df, TIME_COL_CANDIDATES)

        if not id_col:
            continue
        if not dt_col and not (date_col and time_col):
            continue

        tmp = df.copy()
        tmp["Id"] = tmp[id_col].apply(_normalize_ticket_id)
        tmp["DateTimeTSV"] = tmp.apply(
            lambda row: _build_datetime_from_tsv_row(row, date_col, time_col, dt_col),
            axis=1
        )
        tmp = tmp[tmp["Id"].notna() & tmp["DateTimeTSV"].notna()][["Id", "DateTimeTSV"]]
        if not tmp.empty:
            frames.append(tmp)

    # 3) racine
    for filename in TSV_FILE_CANDIDATES:
        tsv_path = ROOT / filename
        if not tsv_path.exists():
            continue

        df = _safe_read_tsv(tsv_path)
        if df is None or df.empty:
            continue

        id_col = _first_existing_col(df, ID_COL_CANDIDATES)
        dt_col = _first_existing_col(df, DATETIME_COL_CANDIDATES)
        date_col = _first_existing_col(df, DATE_COL_CANDIDATES)
        time_col = _first_existing_col(df, TIME_COL_CANDIDATES)

        if not id_col:
            continue
        if not dt_col and not (date_col and time_col):
            continue

        tmp = df.copy()
        tmp["Id"] = tmp[id_col].apply(_normalize_ticket_id)
        tmp["DateTimeTSV"] = tmp.apply(
            lambda row: _build_datetime_from_tsv_row(row, date_col, time_col, dt_col),
            axis=1
        )
        tmp = tmp[tmp["Id"].notna() & tmp["DateTimeTSV"].notna()][["Id", "DateTimeTSV"]]
        if not tmp.empty:
            frames.append(tmp)

    if not frames:
        return pd.DataFrame(columns=["Id", "DateTimeTSV"])

    out = pd.concat(frames, ignore_index=True)

    # si même Id trouvé plusieurs fois, on garde le timestamp le plus récent
    out["DateTimeTSV"] = pd.to_datetime(out["DateTimeTSV"], errors="coerce")
    out = out.dropna(subset=["Id", "DateTimeTSV"])
    out = out.sort_values(by=["Id", "DateTimeTSV"], ascending=[True, False], kind="mergesort")
    out = out.drop_duplicates(subset=["Id"], keep="first").reset_index(drop=True)

    return out


def load_tickets_dataset(report_filename: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Charge les tickets depuis :
    1) archive/analyse_YYYY-MM-DD/<report_filename>
    2) ROOT/data/<report_filename>
    3) ROOT/<report_filename>

    Puis trie par vraie chronologie décroissante :
    le plus récent en haut.
    """
    frames: list[pd.DataFrame] = []

    # 1) Archives
    for dday, dpath in list_analyse_dirs():
        if not in_range(dday, period_start, period_end):
            continue
        f = dpath / report_filename
        df = parse_tickets_to_play(f, fallback_day=dday)
        if df is not None and not df.empty:
            frames.append(df)

    # 2) data/
    data_file = ROOT / "data" / report_filename
    if data_file.exists():
        df_data = parse_tickets_to_play(data_file, fallback_day=None)
        if df_data is not None and not df_data.empty:
            frames.append(df_data)

    # 3) racine
    root_file = ROOT / report_filename
    if root_file.exists():
        df_root = parse_tickets_to_play(root_file, fallback_day=None)
        if df_root is not None and not df_root.empty:
            frames.append(df_root)

    if not frames:
        return pd.DataFrame(
            columns=[
                "Jour", "Ticket", "Type", "Id", "Cote", "Fenêtre de jeu",
                "Nb Matchs", "Détail", "Source", "DateTimeTri", "OrdreFichier"
            ]
        )

    df_all = pd.concat(frames, ignore_index=True)

    # Ordre naturel du fichier : utile si plusieurs tickets ont la même heure
    df_all["OrdreFichier"] = range(len(df_all))

    # Dédup
    if "Id" in df_all.columns:
        df_all = df_all.drop_duplicates(subset=["Id"], keep="first")

    # Filtre par date
    if period_start is not None and period_end is not None:
        df_all = df_all[df_all["Jour"].notna()]
        df_all = df_all[(df_all["Jour"] >= period_start) & (df_all["Jour"] <= period_end)]

    def extract_datetime_from_id(ticket_id):
        """
        Extrait un datetime depuis un ID du type :
        2026-03-03_1900_c88d2662f5_SYS
        """
        if not isinstance(ticket_id, str):
            return pd.NaT

        m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4})_", ticket_id)
        if not m:
            return pd.NaT

        date_part = m.group(1)
        time_part = m.group(2)

        try:
            return pd.to_datetime(f"{date_part} {time_part[:2]}:{time_part[2:]}", errors="coerce")
        except Exception:
            return pd.NaT

    df_all["DateTimeTri"] = df_all["Id"].apply(extract_datetime_from_id)

    # Fallback : si jamais on n'arrive pas à extraire l'heure, on garde au moins le jour
    mask_no_dt = df_all["DateTimeTri"].isna() & df_all["Jour"].notna()
    if mask_no_dt.any():
        df_all.loc[mask_no_dt, "DateTimeTri"] = pd.to_datetime(
            df_all.loc[mask_no_dt, "Jour"].astype(str),
            errors="coerce"
        )

    # Tri final :
    # - plus récent en haut
    # - si même heure, on garde le dernier du fichier en haut
    df_all = df_all.sort_values(
        by=["DateTimeTri", "OrdreFichier"],
        ascending=[False, False],
        kind="mergesort"
    ).reset_index(drop=True)

    return df_all


# -----------------------------
# Parsing verdicts -> mapping id -> statut
# -----------------------------
def parse_verdict_file_to_df(path: Path, source_day: date | None = None) -> pd.DataFrame:
    """
    Parse un fichier verdict_post_analyse_*.txt et retourne un DF:
    Id | Statut | Legs WIN | Legs LOSS | Legs PENDING | LegsDétail | VerdictJour | VerdictSource
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    header_re = re.compile(
        r"(?P<status>[✅❌⏳])\s*Ticket\s*(?P<num>\d+)\s*\|.*?\n"
        r"\s*id=(?P<id>[^\s]+)\s*\n"
        r"\s*legs=(?P<legs>\d+)\s*\|\s*WIN=(?P<win>\d+)\s*\|\s*LOSS=(?P<loss>\d+)\s*\|\s*PENDING=(?P<pending>\d+)",
        re.DOTALL
    )
    leg_re = re.compile(r"([✅❌⏳])\s*(Leg\s*\d+\).*)")

    rows = []
    for block in re.split(r"─{10,}", text):
        m = header_re.search(block)
        if not m:
            continue
        leg_lines = [
            f"{lm.group(1)} {lm.group(2).strip()}"
            for lm in leg_re.finditer(block)
        ]
        rows.append({
            "Id": m.group("id").strip(),
            "Statut": m.group("status"),
            "Legs WIN": int(m.group("win")),
            "Legs LOSS": int(m.group("loss")),
            "Legs PENDING": int(m.group("pending")),
            "LegsDétail": leg_lines,
            "VerdictJour": source_day,
            "VerdictSource": str(path),
        })

    return pd.DataFrame(rows)


def collect_verdict_mapping(report_name: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Cherche des verdicts sur la période:
    - archive/analyse_YYYY-MM-DD/report_name (day = date du dossier)
    - + fallback ROOT/data/report_name
    - + fallback ROOT/report_name
    Retourne un DF unique (dédup sur Id).
    """
    frames = []

    # Archives
    for dday, dpath in list_analyse_dirs():
        if not in_range(dday, period_start, period_end):
            continue
        f = dpath / report_name
        if f.exists():
            df = parse_verdict_file_to_df(f, source_day=dday)
            if not df.empty:
                frames.append(df)

    # data/
    f_data = ROOT / "data" / report_name
    if f_data.exists():
        df = parse_verdict_file_to_df(f_data, source_day=None)
        if not df.empty:
            frames.append(df)

    # racine
    f_root = ROOT / report_name
    if f_root.exists():
        df = parse_verdict_file_to_df(f_root, source_day=None)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING", "VerdictJour", "VerdictSource"])

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["Id"], keep="first")
    return out


def attach_verdict(df_tickets: pd.DataFrame, df_verdict: pd.DataFrame) -> pd.DataFrame:
    """Merge tickets + verdict sur Id."""
    if df_tickets.empty:
        return df_tickets
    if df_verdict.empty:
        df = df_tickets.copy()
        df["Statut"] = None
        df["Legs WIN"] = None
        df["Legs LOSS"] = None
        df["Legs PENDING"] = None
        df["LegsDétail"] = None
        return df

    merge_cols = ["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING"]
    if "LegsDétail" in df_verdict.columns:
        merge_cols.append("LegsDétail")

    df = df_tickets.merge(df_verdict[merge_cols], on="Id", how="left")
    if "LegsDétail" not in df.columns:
        df["LegsDétail"] = None
    return df


def render_ticket_legs(row):
    """Affiche les legs d'un ticket avec coloration vert/rouge/gris selon résultat."""
    legs = row.get("LegsDétail") if hasattr(row, "get") else None
    if legs and isinstance(legs, list) and len(legs) > 0:
        html_parts = []
        for leg in legs:
            s = leg.strip()
            if s.startswith("✅"):
                bg = "#1a4d1a"
            elif s.startswith("❌"):
                bg = "#4d1a1a"
            else:
                bg = "#2d3748"
            html_parts.append(
                f'<div style="background:{bg};padding:5px 10px;border-radius:4px;'
                f'margin:2px 0;font-family:monospace;font-size:13px;color:#f0f0f0">{s}</div>'
            )
        st.markdown("".join(html_parts), unsafe_allow_html=True)
    else:
        st.code(row["Détail"], language="text")

def sort_tickets_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trie les tickets par vraie date/heure extraite de l'Id.
    Format attendu de l'Id :
    YYYY-MM-DD_HHMM_xxxxxxxxxx_SUFFIX
    Exemple :
    2026-03-01_1615_a762f5a29f_015R

    Résultat :
    - le plus récent en haut
    - à heure égale, on garde l'ordre d'origine
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    out["__row_order"] = range(len(out))

    extracted = out["Id"].astype(str).str.extract(
        r"(?P<d>\d{4}-\d{2}-\d{2})_(?P<t>\d{4})_"
    )

    out["DateTimeTri"] = pd.to_datetime(
        extracted["d"] + " " + extracted["t"].str.slice(0, 2) + ":" + extracted["t"].str.slice(2, 4),
        errors="coerce"
    )

    # Fallback si jamais un Id ne matche pas
    if "Jour" in out.columns:
        mask_no_dt = out["DateTimeTri"].isna() & out["Jour"].notna()
        if mask_no_dt.any():
            out.loc[mask_no_dt, "DateTimeTri"] = pd.to_datetime(
                out.loc[mask_no_dt, "Jour"].astype(str),
                errors="coerce"
            )

    out = out.sort_values(
        by=["DateTimeTri", "__row_order"],
        ascending=[False, False],
        kind="mergesort"
    ).drop(columns="__row_order").reset_index(drop=True)

    return out

# -----------------------------
# Sidebar (contrôles)
# -----------------------------
st.sidebar.header("⚙️ Paramètres")

st.sidebar.markdown("### Période d'affichage")
period_label = st.sidebar.selectbox(
    "Filtrer :",
    ["Veille", "10 derniers jours", "30 derniers jours", "All time"],
    index=1
)
period_start, period_end = compute_period_range(period_label)

st.sidebar.divider()
st.sidebar.caption("Dossier actuel (Streamlit) : " + os.getcwd())
st.sidebar.caption(f"ROOT: {ROOT}")
st.sidebar.caption(f"ARCHIVE_DIR exists: {ARCHIVE_DIR.exists()}")
st.sidebar.caption(f"Dernière archive: {latest_analyse_dir() or '—'}")

st.sidebar.caption(f"App file: {__file__}")
st.sidebar.caption(f"Version: {APP_VERSION}")

st.sidebar.caption(f"collect_verdict_mapping signature: {inspect.signature(collect_verdict_mapping)}")

# --- DIAG fichiers (pour voir exactement pourquoi "rien n'est trouvé")
with st.sidebar.expander("🧩 DIAG fichiers (existence)"):
    analyse = latest_analyse_dir()
    st.write(f"Latest analyse dir: {analyse or '—'}")
    candidates_to_check = [
        "tickets_report.txt",
        "tickets_o15_random_report.txt",
        "tickets_u35_random_report.txt",
        "verdict_post_analyse_tickets_report.txt",
        "verdict_post_analyse_tickets_o15_random_report.txt",
        "verdict_post_analyse_tickets_u35_random_report.txt",
    ]
    for fn in candidates_to_check:
        paths = []
        if analyse is not None:
            paths.append(("archive/latest", analyse / fn))
        paths.append(("data/", ROOT / "data" / fn))
        paths.append(("root", ROOT / fn))

        for label, p in paths:
            st.write(f"- {fn} | {label} | exists={p.exists()} | {p}")


# -----------------------------
# Contenu principal
# -----------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🎯 Tickets", "📄 Fichiers Bruts", "📊 Insights", "💰 Martingale", "🔍 Contrefactuel"])

with tab1:
    st.header(f"Tickets — {period_label}")

    if st.button("🔄 Rafraîchir l'affichage"):
        st.rerun()

    st.divider()

    # Tickets multi-jours selon la période (GLOBAL)
    df_sys = load_tickets_dataset("tickets_report_global.txt", period_start, period_end)
    df_rand = load_tickets_dataset("tickets_o15_random_report_global.txt", period_start, period_end)
    df_u35 = load_tickets_dataset("tickets_u35_random_report_global.txt", period_start, period_end)

    # Verdicts correspondants
    df_verdict_sys = collect_verdict_mapping("verdict_post_analyse_tickets_report.txt", period_start, period_end)
    df_verdict_rand = collect_verdict_mapping("verdict_post_analyse_tickets_o15_random_report.txt", period_start, period_end)
    df_verdict_u35 = collect_verdict_mapping("verdict_post_analyse_tickets_u35_random_report.txt", period_start, period_end)

    df_sys = attach_verdict(df_sys, df_verdict_sys)
    df_rand = attach_verdict(df_rand, df_verdict_rand)
    df_u35 = attach_verdict(df_u35, df_verdict_u35)

    # Tri final forcé juste avant affichage
    df_sys = sort_tickets_for_display(df_sys)
    df_rand = sort_tickets_for_display(df_rand)
    df_u35 = sort_tickets_for_display(df_u35)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("🛡️ Tickets Système (avec statut)")

        if not df_sys.empty:
            df_sys["Heure"] = df_sys["DateTimeTri"].dt.strftime("%H:%M")
            df_sys["Heure"] = df_sys["Heure"].fillna("—")
            show_cols = ["Statut", "Jour", "Heure", "Ticket", "Cote", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            show_cols = [c for c in show_cols if c in df_sys.columns]
            st.dataframe(df_sys[show_cols], use_container_width=True, hide_index=True)

            with st.expander("Voir le détail des matchs (Système)"):
                for _, row in df_sys.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    render_ticket_legs(row)
                    st.divider()
        else:
            st.warning("Aucun ticket système trouvé sur cette période.")

    with col2:
        st.subheader("🎲 Tickets O1.5 Random (avec statut)")

        if not df_rand.empty:
            df_rand["Heure"] = df_rand["DateTimeTri"].dt.strftime("%H:%M")
            df_rand["Heure"] = df_rand["Heure"].fillna("—")
            show_cols = ["Statut", "Jour", "Heure", "Ticket", "Cote", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            show_cols = [c for c in show_cols if c in df_rand.columns]
            st.dataframe(df_rand[show_cols], use_container_width=True, hide_index=True)

            with st.expander("Voir le détail des matchs (Random)"):
                for _, row in df_rand.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    render_ticket_legs(row)
                    st.divider()
        else:
            st.warning("Aucun ticket O1.5 Random trouvé sur cette période.")

    with col3:
        st.subheader("🔒 Tickets -3.5 Random (avec statut)")

        if not df_u35.empty:
            df_u35["Heure"] = df_u35["DateTimeTri"].dt.strftime("%H:%M")
            df_u35["Heure"] = df_u35["Heure"].fillna("—")
            show_cols = ["Statut", "Jour", "Heure", "Ticket", "Cote", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            show_cols = [c for c in show_cols if c in df_u35.columns]
            st.dataframe(df_u35[show_cols], use_container_width=True, hide_index=True)

            with st.expander("Voir le détail des matchs (-3.5 Random)"):
                for _, row in df_u35.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    render_ticket_legs(row)
                    st.divider()
        else:
            st.warning("Aucun ticket -3.5 Random trouvé sur cette période.")


with tab2:
    st.header("Visionneuse de fichiers bruts")

    report_type = st.selectbox(
        "Choisir le fichier texte à inspecter :",
        [
            "tickets_report.txt",
            "tickets_o15_random_report.txt",
            "verdict_post_analyse_tickets_report.txt",
            "verdict_post_analyse_tickets_o15_random_report.txt",
        ]
    )

    # Lecture: on essaie (1) dernière archive (2) data/ (3) racine
    analyse = latest_analyse_dir()
    candidates = []
    if analyse is not None:
        candidates.append(analyse / report_type)
    candidates.append(ROOT / "data" / report_type)
    candidates.append(ROOT / report_type)

    file_path = None
    for c in candidates:
        if c.exists():
            file_path = c
            break

    if file_path is None:
        st.error("Fichier introuvable (archive/, data/, racine).")
        with st.expander("Détails chemins testés"):
            for c in candidates:
                st.write(f"- exists={c.exists()} | {c}")
    else:
        st.caption(f"Lecture de: {file_path}")
        st.text_area(
            f"Contenu de {report_type}",
            file_path.read_text(encoding="utf-8", errors="replace"),
            height=650
        )


# ============================================================
# TAB 3 — INSIGHTS (Rankings ligues & équipes — base complète)
# ============================================================

RANKINGS_DIR = ROOT / "data" / "rankings"
RANK_LEAGUE_FILE = RANKINGS_DIR / "triskele_ranking_league_x_bet.tsv"
RANK_TEAM_FILE   = RANKINGS_DIR / "triskele_ranking_team_x_bet.tsv"

BET_LABELS_MAP = {
    "HT05":           "HT +0.5 (but à la MT)",
    "HT1X_HOME":      "HT 1X Home (DC MT domicile)",
    "O15_FT":         "Over 1.5 (FT)",
    "O25_FT":         "Over 2.5 (FT)",
    "TEAM1_SCORE_FT": "Équipe 1 marque (FT)",
    "TEAM2_SCORE_FT": "Équipe 2 marque (FT)",
    "TEAM1_WIN_FT":   "Victoire Équipe 1 (FT)",
    "TEAM2_WIN_FT":   "Victoire Équipe 2 (FT)",
}

# Colonnes stats enrichies présentes dans triskele_ranking_*

@st.cache_data(ttl=60)
def _load_ranking_tsv(path_str: str) -> pd.DataFrame:
    p = Path(path_str)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p, sep="\t", dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


with tab3:
    st.header("Insights — Rankings Triskèle")
    st.caption(f"Source : {RANKINGS_DIR}")

    df_lg_raw = _load_ranking_tsv(str(RANK_LEAGUE_FILE))
    df_tm_raw = _load_ranking_tsv(str(RANK_TEAM_FILE))

    df_lg_std = _standardize_baseline_league_x_bet(df_lg_raw)
    df_tm_std = _standardize_baseline_team_x_bet(df_tm_raw)

    if df_lg_std.empty and df_tm_std.empty:
        st.warning(f"Fichiers de ranking introuvables dans {RANKINGS_DIR}")
    else:
        # ── Filtres globaux ──
        fcol1, fcol2, fcol3, fcol4 = st.columns([2, 2, 2, 1])

        with fcol1:
            all_bets = sorted(df_lg_std["bet_key"].dropna().unique().tolist()) if not df_lg_std.empty else []
            sel_bets = st.multiselect(
                "Type(s) de pari",
                options=all_bets,
                default=[],
                format_func=lambda k: f"{k} — {BET_LABELS_MAP.get(k, k)}",
                key="ins_bets"
            )

        with fcol2:
            all_leagues = sorted(df_lg_std["league"].dropna().unique().tolist()) if not df_lg_std.empty else []
            sel_leagues_ins = st.multiselect("Championnat(s)", options=all_leagues, default=[], key="ins_leagues")

        with fcol3:
            all_teams = sorted(df_tm_std["team"].dropna().unique().tolist()) if not df_tm_std.empty else []
            sel_teams_ins = st.multiselect("Équipe(s)", options=all_teams, default=[], key="ins_teams")

        with fcol4:
            min_samples = st.number_input("Min matchs", min_value=1, value=5, step=1, key="ins_min")

        st.divider()

        sub_lg, sub_tm = st.tabs(["🌍 Ligues × Bet", "👥 Équipes × Bet"])

        # ─────────────────────────────────────────────
        # ONGLET LIGUES
        # ─────────────────────────────────────────────
        with sub_lg:
            if df_lg_std.empty:
                st.info(f"Fichier introuvable : {RANK_LEAGUE_FILE}")
            else:
                df_lg = df_lg_std.copy()
                if sel_bets:
                    df_lg = df_lg[df_lg["bet_key"].isin(sel_bets)]
                if sel_leagues_ins:
                    df_lg = df_lg[df_lg["league"].isin(sel_leagues_ins)]
                df_lg = df_lg[df_lg["decided"] >= int(min_samples)]
                df_lg = df_lg.sort_values(by=["win_rate", "decided"], ascending=[False, False]).reset_index(drop=True)

                if df_lg.empty:
                    st.info("Aucune ligue avec ces filtres.")
                else:
                    view = df_lg[["league", "bet_key", "decided", "wins", "losses", "win_rate"]].copy()
                    view = view.rename(columns={
                        "league": "Championnat", "bet_key": "Bet",
                        "decided": "Matchs", "wins": "✅ Wins",
                        "losses": "❌ Losses", "win_rate": "Taux"
                    })
                    _render_table(view, percent_cols=["Taux"], height=600)
                    st.caption(f"{len(df_lg)} ligues affichées")

        # ─────────────────────────────────────────────
        # ONGLET ÉQUIPES
        # ─────────────────────────────────────────────
        with sub_tm:
            if df_tm_std.empty:
                st.info(f"Fichier introuvable : {RANK_TEAM_FILE}")
            else:
                df_tm = df_tm_std.copy()
                if sel_bets:
                    df_tm = df_tm[df_tm["bet_key"].isin(sel_bets)]
                if sel_leagues_ins and "league" in df_tm.columns:
                    df_tm = df_tm[df_tm["league"].isin(sel_leagues_ins)]
                if sel_teams_ins:
                    df_tm = df_tm[df_tm["team"].isin(sel_teams_ins)]
                df_tm = df_tm[df_tm["decided"] >= int(min_samples)]
                df_tm = df_tm.sort_values(by=["win_rate", "decided"], ascending=[False, False]).reset_index(drop=True)

                if df_tm.empty:
                    st.info("Aucune équipe avec ces filtres.")
                else:
                    cols_t = ["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"]
                    view_t = df_tm[[c for c in cols_t if c in df_tm.columns]].copy()
                    view_t = view_t.rename(columns={
                        "league": "Championnat", "team": "Équipe", "bet_key": "Bet",
                        "decided": "Matchs", "wins": "✅ Wins",
                        "losses": "❌ Losses", "win_rate": "Taux"
                    })
                    _render_table(view_t, percent_cols=["Taux"], height=600)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — MARTINGALE
# ─────────────────────────────────────────────────────────────────────────────
STATE_FILE = ROOT / "data" / "optimizer" / "martingale_state.json"

_STRAT_CONFIG = {
    "RANDOM SAFE":    {"mode": "SAFE",    "ml": 3},
    "RANDOM NORMALE": {"mode": "NORMALE", "ml": 4},
    "SYSTEM SAFE":    {"mode": "SAFE",    "ml": 4},
    "SYSTEM NORMALE": {"mode": "NORMALE", "ml": 4},
}
_BANKROLL0 = 100.0

def _default_state():
    strats = {}
    for name, cfg in _STRAT_CONFIG.items():
        strats[name] = {"ba": _BANKROLL0, "cb": _BANKROLL0, "ls": 0, "ps": 0.0,
                        "mode": cfg["mode"], "ml": cfg["ml"]}
    return {"strategies": strats, "reserves": 600.0,
            "active": ["RANDOM SAFE"], "last_updated": str(date.today())}

def _load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return _default_state()

def _save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))


# ── Dual portfolio (A + B) ─────────────────────────────────────────────────
STATE_FILE_DUAL = ROOT / "data" / "optimizer" / "martingale_dual_state.json"

_PORTFOLIO_CONFIGS = {
    "portfolio_a": {
        "label": "A — ML mix (70€)",
        "reserves0": 65.0,
        "strategies": {
            "RANDOM SAFE":    {"mode": "SAFE",    "ml": 3, "ba": 1.0},
            "RANDOM NORMALE": {"mode": "NORMALE", "ml": 4, "ba": 1.0},
            "SYSTEM SAFE":    {"mode": "SAFE",    "ml": 4, "ba": 1.0},
            "SYSTEM NORMALE": {"mode": "NORMALE", "ml": 4, "ba": 1.0},
        },
    },
    "portfolio_b": {
        "label": "B — ML=3 universel (7€)",
        "reserves0": 4.20,
        "strategies": {
            "RANDOM SAFE":    {"mode": "SAFE",    "ml": 3, "ba": 0.70},
            "RANDOM NORMALE": {"mode": "NORMALE", "ml": 3, "ba": 0.70},
            "SYSTEM SAFE":    {"mode": "SAFE",    "ml": 3, "ba": 0.70},
            "SYSTEM NORMALE": {"mode": "NORMALE", "ml": 3, "ba": 0.70},
        },
    },
}

def _default_dual_state():
    state = {}
    for pkey, pcfg in _PORTFOLIO_CONFIGS.items():
        strats = {}
        for sname, scfg in pcfg["strategies"].items():
            b = scfg["ba"]
            strats[sname] = {"ba": b, "cb": b, "ls": 0, "ps": 0.0,
                             "mode": scfg["mode"], "ml": scfg["ml"]}
        state[pkey] = {"strategies": strats, "reserves": pcfg["reserves0"],
                       "last_updated": str(date.today())}
    return state

def _load_dual_state():
    if STATE_FILE_DUAL.exists():
        return json.loads(STATE_FILE_DUAL.read_text())
    return _default_dual_state()

def _save_dual_state(s):
    STATE_FILE_DUAL.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE_DUAL.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def _read_tickets_today(filepath: Path) -> list[float]:
    """Retourne la liste des cotes des tickets du jour (ordre de jeu)."""
    if not filepath.exists():
        return []
    content = filepath.read_text(encoding="utf-8", errors="replace")
    return [float(m) for m in re.findall(r"cote = ([0-9.]+)", content)]


def _next_stake(ba, ls, ps, ml):
    denom = float((2 ** ml) - 1)
    s = ba / denom if ls == 0 else ps * 2.0
    return min(s, ba)

def _apply_result(sim, is_win, odd, reserves):
    sim = copy.deepcopy(sim)
    note = ""
    ba, cb, ls, ps, mode, ml = sim["ba"], sim["cb"], sim["ls"], sim["ps"], sim["mode"], sim["ml"]

    if ba <= 0:
        # tirage réserves
        next_bet = ps * 2.0 if ps > 0 else _BANKROLL0 / float((2**ml)-1)
        if reserves >= next_bet:
            ba = next_bet
            reserves -= next_bet
            note = f"🏦 Tirage réserves ({next_bet:.0f}€)"
        else:
            note = "⚠️ Réserves insuffisantes"
            sim.update({"ba": 0, "cb": cb, "ls": ls, "ps": ps, "note": note})
            return sim, reserves

    stake = _next_stake(ba, ls, ps, ml)

    if is_win:
        ba += stake * (odd - 1.0)
        ls = 0
        if mode == "SAFE" and ba >= cb * 2.0:
            profit = ba - cb
            reserves += profit
            new_base = _BANKROLL0 + 0.20 * reserves
            ba = new_base
            cb = new_base
            ps = 0.0
            note = f"💰 DOUBLING ! +{profit:.0f}€ → réserves"
        else:
            ps = stake
    else:
        ba -= stake
        ls += 1
        ps = stake
        note = f"❌ Défaite (L×{ls})"

    sim.update({"ba": ba, "cb": cb, "ls": ls, "ps": ps, "note": note})
    return sim, reserves


with tab4:
    st.header("💰 Martingale")

    TICKET_FILES_MART = {
        "RANDOM": ROOT / "data" / "tickets_o15_random_report.txt",
        "SYSTEM": ROOT / "data" / "tickets_report.txt",
    }
    TICKET_STRATS = {
        "RANDOM": ["RANDOM SAFE", "RANDOM NORMALE"],
        "SYSTEM": ["SYSTEM SAFE", "SYSTEM NORMALE"],
    }

    dual_state = _load_dual_state()

    # ── Sélecteur de vue ───────────────────────────────────────────────────
    mart_view = st.radio(
        "Vue",
        ["📊 Dashboard", "🅰️ Portfolio A", "🅱️ Portfolio B"],
        horizontal=True,
        key="mart_view",
    )

    st.divider()
    st.subheader(f"📅 {date.today()}")

    # ══════════════════════════════════════════════════════════════════════
    # DASHBOARD — vue combinée A + B
    # ══════════════════════════════════════════════════════════════════════
    if mart_view == "📊 Dashboard":

        # ── Mises du jour par type de ticket ──────────────────────────────
        for ttype, strat_names in TICKET_STRATS.items():
            cotes = _read_tickets_today(TICKET_FILES_MART[ttype])
            st.markdown(f"### 🎟️ {ttype}")

            if not cotes:
                st.info(f"Pas de ticket {ttype} aujourd'hui.")
                st.divider()
                continue

            n_tranches = len(cotes)
            st.caption(
                f"{n_tranches} tranche(s) aujourd'hui  —  "
                + "  |  ".join(f"T{i+1}: cote ×{c:.2f}" for i, c in enumerate(cotes))
            )

            # Table : une ligne par tranche, colonnes = portfolios + total
            rows_dash = []
            for t_idx, cote in enumerate(cotes):
                label = f"T{t_idx+1} (×{cote:.2f})"
                row   = {"Tranche": label}
                total_ab = 0.0
                for pkey, pcfg in _PORTFOLIO_CONFIGS.items():
                    pstate = dual_state[pkey]
                    # Simuler les tranches précédentes (tout WIN) pour avoir l'état courant
                    strats_sim = {sn: copy.deepcopy(pstate["strategies"][sn]) for sn in strat_names}
                    res_sim    = pstate["reserves"]
                    for prev_cote in cotes[:t_idx]:
                        for sn in strat_names:
                            strats_sim[sn], res_sim = _apply_result(strats_sim[sn], True, prev_cote, res_sim)
                    mise_t = sum(
                        _next_stake(strats_sim[sn]["ba"], strats_sim[sn]["ls"],
                                    strats_sim[sn]["ps"], strats_sim[sn]["ml"])
                        for sn in strat_names
                    )
                    lbl = "Portfolio A (70€)" if pkey == "portfolio_a" else "Portfolio B (7€)"
                    row[lbl] = f"{mise_t:.2f}€"
                    total_ab += mise_t
                row["Total A+B"] = f"{total_ab:.2f}€"
                rows_dash.append(row)

            df_dash = pd.DataFrame(rows_dash).set_index("Tranche")
            st.dataframe(df_dash, use_container_width=True)
            st.caption("ℹ️ Les tranches T2, T3… supposent que les tranches précédentes ont été gagnées.")
            st.divider()

        # ── État par portfolio ─────────────────────────────────────────────
        st.subheader("🏦 État des portfolios")
        col_a, col_b = st.columns(2)

        for col, pkey in zip([col_a, col_b], ["portfolio_a", "portfolio_b"]):
            pstate = dual_state[pkey]
            pcfg   = _PORTFOLIO_CONFIGS[pkey]
            with col:
                st.markdown(f"**{pcfg['label']}**  |  Réserves : {pstate['reserves']:.2f}€")
                for sname, s in pstate["strategies"].items():
                    mise      = _next_stake(s["ba"], s["ls"], s["ps"], s["ml"])
                    coups_avt = s["ml"] - s["ls"]
                    serie_str = f"L×{s['ls']}" if s["ls"] > 0 else "✓"
                    short     = sname.replace("RANDOM ", "R·").replace("SYSTEM ", "S·")
                    if s["mode"] == "SAFE":
                        manque = max(0.0, s["cb"] * 2.0 - s["ba"])
                        extra  = f"  |  manque doubling : {manque:.2f}€" if manque > 0 else "  |  doubling ✅"
                    else:
                        extra = ""
                    st.caption(
                        f"**{short}** — BK {s['ba']:.3f}€ — {serie_str}"
                        f"  |  mise : {mise:.2f}€  |  si perdu → {mise*2:.2f}€"
                        f"  |  encore {coups_avt} coup(s) avant réserves"
                        + extra
                    )
                st.caption(f"_Màj : {pstate.get('last_updated', '—')}_")

    # ══════════════════════════════════════════════════════════════════════
    # VUE PORTFOLIO A ou B — tableau par scénario
    # ══════════════════════════════════════════════════════════════════════
    else:
        pkey   = "portfolio_a" if mart_view == "🅰️ Portfolio A" else "portfolio_b"
        pstate = dual_state[pkey]
        pcfg   = _PORTFOLIO_CONFIGS[pkey]

        st.markdown(f"**{pcfg['label']}** — Réserves : **{pstate['reserves']:.2f}€**")

        for ttype, strat_names in TICKET_STRATS.items():
            cotes = _read_tickets_today(TICKET_FILES_MART[ttype])
            st.markdown(f"### 🎟️ {ttype}")

            if not cotes:
                st.info(f"Pas de ticket {ttype} aujourd'hui.")
                st.divider()
                continue

            # Tableau : Mise T1 | Après G1 | Après G2 | ... (chemin tout-win)
            rows = []
            for sname in strat_names:
                s = copy.deepcopy(pstate["strategies"][sname])
                r = pstate["reserves"]
                row = {"Stratégie": sname}
                mise = _next_stake(s["ba"], s["ls"], s["ps"], s["ml"])
                row["Mise T1"] = f"{mise:.3f}€"
                for t_idx, cote in enumerate(cotes):
                    s, r = _apply_result(s, True, cote, r)
                    mise = _next_stake(s["ba"], s["ls"], s["ps"], s["ml"])
                    row[f"Après G{t_idx+1}"] = f"{mise:.3f}€"
                rows.append(row)

            if rows:
                df_pf = pd.DataFrame(rows)
                st.dataframe(df_pf, use_container_width=True, hide_index=True)
                st.caption("  |  ".join(f"T{i+1}: ×{c:.2f}" for i, c in enumerate(cotes)))
            st.divider()

        # ── État détaillé ──────────────────────────────────────────────────
        with st.expander("📊 État détaillé des stratégies"):
            for sname, s in pstate["strategies"].items():
                mise      = _next_stake(s["ba"], s["ls"], s["ps"], s["ml"])
                coups_avt = s["ml"] - s["ls"]
                serie_str = f"L×{s['ls']}" if s["ls"] > 0 else "✓"
                if s["mode"] == "SAFE":
                    manque = max(0.0, s["cb"] * 2.0 - s["ba"])
                    extra  = f"  |  manque doubling : {manque:.2f}€" if manque > 0 else "  |  doubling atteint ✅"
                else:
                    extra = ""
                st.caption(
                    f"**{sname}** — BK {s['ba']:.3f}€ — {serie_str}"
                    f"  |  mise : {mise:.3f}€  |  si perdu → {mise*2:.3f}€"
                    f"  |  encore {coups_avt} coup(s) avant réserves"
                    + extra
                )


# ──────────────────────────────────────────────────────────────────────────────
# TAB 5 — ANALYSE CONTREFACTUELLE v2
# ──────────────────────────────────────────────────────────────────────────────
with tab5:
    st.header("🔍 Analyse Contrefactuelle v2")
    st.markdown(
        "Pour chaque journée, le ticket joué est positionné parmi **tous les tickets 3-4 legs possibles** "
        "dans le pool effectif de ce jour. "
        "**v2 :** comparaison sur les **résultats réels** (colonne 9 de predictions.tsv) — "
        "chaque combo est marquée WIN ou LOSS selon que tous ses picks ont result=1."
    )
    st.success(
        "**v2 — résultats réels disponibles.** "
        "Les picks non joués ont leur résultat réel dans predictions.tsv (1=gagné, 0=perdu). "
        "Le flag CATASTROPHIQUE signifie : ticket perdu alors que des alternatives gagnantes existaient."
    )

    # Importer le script contrefactuel (chemin relatif au fichier app.py)
    import importlib.util
    _cf_path = Path(__file__).parent / "counterfactual.py"

    if not _cf_path.exists():
        st.error(f"Script counterfactual.py introuvable : {_cf_path}")
    else:
        spec = importlib.util.spec_from_file_location("counterfactual", _cf_path)
        _cf_mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(_cf_mod)
            _cf_available = True
        except Exception as e:
            st.error(f"Erreur au chargement du script : {e}")
            _cf_available = False

        if _cf_available:
            cf_ctrl1, cf_ctrl2, cf_ctrl3 = st.columns([1, 1, 2])
            with cf_ctrl1:
                cf_days = st.number_input(
                    "Derniers N jours",
                    min_value=1, max_value=200, value=30, step=1,
                    key="cf_days"
                )
            with cf_ctrl2:
                cf_min_odd = st.number_input(
                    "Cote min pick",
                    min_value=1.0, max_value=3.0, value=1.15, step=0.05,
                    key="cf_min_odd"
                )

            # Filtre par flag
            _FLAG_OPTIONS = ["Tous", "CATASTROPHIQUE", "MALCHANCEUX", "OPTIMAL", "BON_CHOIX_MALCHANCEUX"]
            with cf_ctrl3:
                cf_flag_filter = st.selectbox("Filtrer par flag", _FLAG_OPTIONS, key="cf_flag_filter")

            cf_run = st.button("▶ Lancer l'analyse", type="primary", key="cf_run")

            if cf_run:
                with st.spinner("Calcul en cours…"):
                    try:
                        cf_results = _cf_mod.run_counterfactual(
                            days=int(cf_days),
                            output_path=None,
                            verbose=False,
                            min_odd=float(cf_min_odd),
                        )
                    except Exception as e:
                        st.error(f"Erreur lors de l'analyse : {e}")
                        cf_results = []

                if not cf_results:
                    st.warning("Aucun résultat. Vérifiez que les archives existent.")
                else:
                    # ── Construire le DataFrame ──────────────────────────────────
                    rows = []
                    for day_res in cf_results:
                        if day_res.get("status") != "OK":
                            continue
                        n_won = day_res.get("n_won", 0)
                        n_combos = day_res.get("n_combos", 0)
                        win_ratio = day_res.get("win_ratio_pool", 0)
                        for t in day_res.get("tickets_joues", []):
                            pct  = t.get("percentile_odd")
                            rank = t.get("rank", "?")
                            flag = t.get("flag", "")
                            verdict = t.get("verdict", "?")
                            picks_str = "+".join(
                                p.get("bet_key", "?") for p in t.get("picks", [])[:4]
                            )
                            rows.append({
                                "Date":         day_res["date"],
                                "Ticket":       picks_str or t["ticket_id"][:30],
                                "Cote jouée":   round(t["total_odd"], 2),
                                "Résultat":     verdict,
                                "Rang":         f"{rank}/{n_combos}",
                                "Percentile":   f"{pct:.0f}%" if pct is not None else "N/A",
                                "Combos gagnantes": f"{n_won}/{n_combos} ({win_ratio:.1f}%)",
                                "Flag":         flag,
                                # valeurs numériques pour filtre/stats
                                "_pct_num":     pct,
                                "_flag_raw":    flag,
                                "_verdict":     verdict,
                            })

                    if not rows:
                        st.info("Aucun ticket joué avec statut décidé sur la période.")
                    else:
                        df_cf_full = pd.DataFrame(rows)

                        # Appliquer le filtre par flag
                        if cf_flag_filter != "Tous":
                            df_cf = df_cf_full[df_cf_full["_flag_raw"] == cf_flag_filter].copy()
                        else:
                            df_cf = df_cf_full.copy()

                        # ── Métriques globales (sur toutes les données, pas filtrées) ──
                        n_total    = len(df_cf_full)
                        n_catastro = (df_cf_full["_flag_raw"] == "CATASTROPHIQUE").sum()
                        n_malch    = (df_cf_full["_flag_raw"] == "MALCHANCEUX").sum()
                        n_optimal  = (df_cf_full["_flag_raw"] == "OPTIMAL").sum()
                        n_bon      = (df_cf_full["_flag_raw"] == "BON_CHOIX_MALCHANCEUX").sum()
                        # % du temps dans le top 25%
                        pcts_all = df_cf_full["_pct_num"].dropna()
                        pct_top25 = round(100.0 * (pcts_all >= 75).sum() / len(pcts_all), 1) if len(pcts_all) > 0 else 0

                        m1, m2, m3, m4, m5 = st.columns(5)
                        m1.metric("Tickets analysés", n_total)
                        m2.metric("CATASTROPHIQUE", n_catastro,
                                  help="LOSS + alternatives gagnantes disponibles + ticket bas percentile")
                        m3.metric("MALCHANCEUX", n_malch,
                                  help="LOSS + peu d'alternatives gagnantes (vraie malchance)")
                        m4.metric("OPTIMAL", n_optimal,
                                  help="WIN + ticket dans le top 50% des cotes disponibles")
                        m5.metric("Top 25% des cotes", f"{pct_top25}% du temps",
                                  help="Fréquence à laquelle le ticket joué était dans le top 25% du pool")

                        st.divider()

                        # ── Tableau interactif ───────────────────────────────────
                        st.subheader(f"Détail par ticket {'— filtre: ' + cf_flag_filter if cf_flag_filter != 'Tous' else ''}")

                        def _style_flag_v2(val):
                            v = str(val)
                            if v == "CATASTROPHIQUE":
                                return "background-color: #6b1a1a; color: white; font-weight: bold;"
                            if v == "MALCHANCEUX":
                                return "background-color: #4d3500; color: #ffcc44;"
                            if v == "OPTIMAL":
                                return "background-color: #1a4d1a; color: #aaffaa; font-weight: bold;"
                            if v == "BON_CHOIX_MALCHANCEUX":
                                return "background-color: #2a3a5a; color: #aaccff;"
                            return ""

                        def _style_verdict(val):
                            if val == "WIN":
                                return "color: #4dff88; font-weight: bold;"
                            if val == "LOSS":
                                return "color: #ff6666;"
                            return ""

                        display_cols = ["Date", "Ticket", "Cote jouée", "Résultat",
                                        "Rang", "Percentile", "Combos gagnantes", "Flag"]
                        df_display = df_cf[display_cols].copy()

                        styled = (
                            df_display.style
                            .applymap(_style_flag_v2, subset=["Flag"])
                            .applymap(_style_verdict, subset=["Résultat"])
                        )
                        st.dataframe(styled, use_container_width=True, height=450)

                        st.divider()

                        # ── Distribution des percentiles ─────────────────────────
                        st.subheader("Distribution des percentiles de cote sur l'historique")
                        st.markdown(
                            "**Lecture :** 100% = meilleure cote disponible ce jour. "
                            "La zone verte (75-100%) représente le top 25% — "
                            f"vous y êtes **{pct_top25}% du temps**."
                        )

                        pcts_num = df_cf_full["_pct_num"].dropna().tolist()
                        if pcts_num:
                            df_pct = pd.DataFrame({"Percentile": pcts_num})
                            hist_data = df_pct["Percentile"].value_counts(bins=10).sort_index()
                            st.bar_chart(hist_data, height=260)

                        st.divider()

                        # ── Statistique globale clé ──────────────────────────────
                        with st.expander("Statistiques avancées"):
                            # Win ratio moyen du pool
                            win_ratios = [
                                day_res.get("win_ratio_pool", 0)
                                for day_res in cf_results
                                if day_res.get("status") == "OK"
                            ]
                            if win_ratios:
                                avg_wr = sum(win_ratios) / len(win_ratios)
                                st.metric(
                                    "Win ratio moyen du pool (toutes combos)",
                                    f"{avg_wr:.1f}%",
                                    help="En moyenne, X% des combinaisons possibles auraient gagné."
                                )
                            st.caption(
                                f"Méthode : picks filtrés odd >= {cf_min_odd} | "
                                "max 50 picks uniques / jour | max 2000 combinaisons | "
                                "1 pick/match | legs 3 ou 4"
                            )

                        # Export JSON
                        st.divider()
                        with st.expander("Export JSON"):
                            json_str = json.dumps(cf_results, ensure_ascii=False, indent=2)
                            st.download_button(
                                "Télécharger les résultats JSON",
                                data=json_str,
                                file_name=f"counterfactual_v2_{date.today()}.json",
                                mime="application/json",
                            )