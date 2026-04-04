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
        "verdict_post_analyse_tickets_report.txt",
        "verdict_post_analyse_tickets_o15_random_report.txt",
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
tab1, tab2, tab3, tab4 = st.tabs(["🎯 Tickets", "📄 Fichiers Bruts", "📊 Insights", "💰 Martingale"])

with tab1:
    st.header(f"Tickets — {period_label}")

    if st.button("🔄 Rafraîchir l'affichage"):
        st.rerun()

    st.divider()

    # Tickets multi-jours selon la période (GLOBAL)
    df_sys = load_tickets_dataset("tickets_report_global.txt", period_start, period_end)
    df_rand = load_tickets_dataset("tickets_o15_random_report_global.txt", period_start, period_end)

    # Verdicts correspondants
    df_verdict_sys = collect_verdict_mapping("verdict_post_analyse_tickets_report.txt", period_start, period_end)
    df_verdict_rand = collect_verdict_mapping("verdict_post_analyse_tickets_o15_random_report.txt", period_start, period_end)

    df_sys = attach_verdict(df_sys, df_verdict_sys)
    df_rand = attach_verdict(df_rand, df_verdict_rand)

    # Tri final forcé juste avant affichage
    df_sys = sort_tickets_for_display(df_sys)
    df_rand = sort_tickets_for_display(df_rand)

    col1, col2 = st.columns(2)

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
    st.header("💰 Martingale — Suivi en direct")

    state = _load_state()

    # ── Configuration des stratégies actives ─────────────────────────────────
    with st.expander("⚙️ Stratégies actives", expanded=False):
        new_active = []
        cols_cfg = st.columns(4)
        for i, name in enumerate(_STRAT_CONFIG.keys()):
            with cols_cfg[i]:
                if st.checkbox(name, value=(name in state["active"]), key=f"chk_{name}"):
                    new_active.append(name)
        if set(new_active) != set(state["active"]):
            state["active"] = new_active
            _save_state(state)
            st.rerun()

    st.divider()

    # ── Dashboard : état actuel ───────────────────────────────────────────────
    st.subheader("État actuel")

    if not state["active"]:
        st.info("Aucune stratégie active. Cochez-en une dans ⚙️.")
    else:
        dash_cols = st.columns(len(state["active"]) + 1)
        for i, name in enumerate(state["active"]):
            s = state["strategies"][name]
            stake = _next_stake(s["ba"], s["ls"], s["ps"], s["ml"])
            seq = f"L×{s['ls']}" if s["ls"] > 0 else "Départ"
            with dash_cols[i]:
                st.metric(name, f"{s['ba']:.0f}€", delta=None)
                st.caption(f"Séquence : {seq}")
                st.markdown(f"**Prochaine mise : {stake:.0f}€**")
        with dash_cols[-1]:
            st.metric("🏦 Réserves", f"{state['reserves']:.0f}€")
            st.caption(f"Màj : {state.get('last_updated','—')}")

    # ── Modifier l'état manuellement ─────────────────────────────────────────
    with st.expander("✏️ Modifier l'état actuel", expanded=not STATE_FILE.exists()):
        st.caption("Mets à jour ta bankroll réelle, ta séquence et les réserves.")
        edit_strat = st.selectbox("Stratégie à modifier", list(_STRAT_CONFIG.keys()), key="edit_sel")
        s_edit = state["strategies"][edit_strat]
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            new_ba = st.number_input("Bankroll (€)", min_value=0.0, value=float(s_edit["ba"]), step=1.0, key="edit_ba")
        with ec2:
            new_ls = st.number_input("Défaites en cours (L×)", min_value=0, max_value=10, value=int(s_edit["ls"]), step=1, key="edit_ls")
        with ec3:
            new_ps = st.number_input("Mise précédente (€)", min_value=0.0, value=float(s_edit["ps"]), step=1.0, key="edit_ps")
        with ec4:
            new_cb = st.number_input("Cycle base (€)", min_value=0.0, value=float(s_edit["cb"]), step=1.0, key="edit_cb")
        new_reserves = st.number_input("Réserves communes (€)", min_value=0.0, value=float(state["reserves"]), step=10.0, key="edit_res")
        if st.button("💾 Enregistrer l'état", type="primary"):
            state["strategies"][edit_strat].update({"ba": new_ba, "ls": new_ls, "ps": new_ps, "cb": new_cb})
            state["reserves"] = new_reserves
            state["last_updated"] = str(date.today())
            _save_state(state)
            st.success("État enregistré !")
            st.rerun()

    st.divider()

    # ── Simulateur du jour ────────────────────────────────────────────────────
    st.subheader("Simulateur du jour")

    if not state["active"]:
        st.info("Activez au moins une stratégie.")
    else:
        sel = st.selectbox("Stratégie à simuler", state["active"], key="sim_sel")
        n_tickets = st.number_input("Nombre de tickets aujourd'hui", min_value=1, max_value=6, value=2, step=1, key="sim_n")

        st.write("---")
        sim = copy.deepcopy(state["strategies"][sel])
        sim_reserves = state["reserves"]
        sim_log = []

        for i in range(int(n_tickets)):
            stake = _next_stake(sim["ba"], sim["ls"], sim["ps"], sim["ml"])
            st.markdown(f"#### Ticket {i+1} — mise : **{stake:.0f}€**")

            rcol1, rcol2 = st.columns(2)
            with rcol1:
                res = st.radio("Résultat", ["✅ Victoire", "❌ Défaite"],
                               key=f"sim_res_{sel}_{i}", horizontal=True)
            is_win = res == "✅ Victoire"

            odd = 1.0
            if is_win:
                with rcol2:
                    odd = st.number_input("Cote", min_value=1.01, max_value=100.0,
                                          value=2.50, step=0.05, key=f"sim_odd_{sel}_{i}")

            sim, sim_reserves = _apply_result(sim, is_win, odd, sim_reserves)
            note = sim.pop("note", "")
            if note:
                st.caption(note)
            st.caption(f"→ Bankroll : {sim['ba']:.0f}€  |  Réserves : {sim_reserves:.0f}€")
            sim_log.append({"ticket": i+1, "mise": stake, "résultat": res, "note": note})
            st.write("")

        st.divider()
        st.markdown(f"**État final simulé** : {sel} = **{sim['ba']:.0f}€** | Séquence = L×{sim['ls']} | Réserves = **{sim_reserves:.0f}€**")

        if st.button("✅ Confirmer — enregistrer ces résultats", type="primary"):
            state["strategies"][sel] = sim
            state["reserves"] = sim_reserves
            state["last_updated"] = str(date.today())
            _save_state(state)
            st.success("État mis à jour !")
            st.rerun()

    st.divider()

    # ── Reset complet ─────────────────────────────────────────────────────────
    with st.expander("🔄 Réinitialiser l'état (nouveau départ)"):
        st.warning("Remet toutes les bankrolls à 100€ et les réserves à 600€.")
        if st.button("Réinitialiser", type="secondary"):
            _save_state(_default_state())
            st.success("État réinitialisé.")
            st.rerun()