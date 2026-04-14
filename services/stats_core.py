# services/stats_core.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# =====================================================
# PATHS (utilisés par le dashboard)
# =====================================================

DEFAULT_VERDICT_PATH = Path("data/verdict_post_analyse.txt")

DEFAULT_TICKETS_SYSTEM_VERDICT_PATH = Path("data/verdict_post_analyse_tickets.txt")
DEFAULT_TICKETS_O15_VERDICT_PATH = Path("data/verdict_post_analyse_tickets_o15_random.txt")
DEFAULT_TICKETS_U35_VERDICT_PATH = Path("data/verdict_post_analyse_tickets_u35_random.txt")

# Fichiers “classements” (legacy, recalculés à chaque lecture)
TRISKELE_RANK_LEAGUES_PATH = Path("data/triskele_rank_leagues_x_bet.tsv")
TRISKELE_RANK_TEAMS_PATH = Path("data/triskele_rank_teams_x_bet.tsv")

# ✅ NOUVEAU: classements "baseline" (data/rankings/…)
BASELINE_RANK_LEAGUES_X_BET_PATH = Path("data/rankings/triskele_ranking_league_x_bet.tsv")
BASELINE_RANK_TEAMS_X_BET_PATH   = Path("data/rankings/triskele_ranking_team_x_bet.tsv")

# =====================================================
# FILTERS
# =====================================================

@dataclass
class VerdictFilters:
    leagues: Optional[List[str]] = None
    bet_keys: Optional[List[str]] = None
    labels: Optional[List[str]] = None
    evals: Optional[List[str]] = None
    date_min: Optional[pd.Timestamp] = None
    date_max: Optional[pd.Timestamp] = None


# =====================================================
# LOADERS
# =====================================================

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def load_bet_verdicts(path: Path = DEFAULT_VERDICT_PATH) -> pd.DataFrame:
    """
    Charge data/verdict_post_analyse.txt

    Format attendu (post_analysis_core.format_post_verdict_tsv):
    TSV: match_id  date  league  home  away  bet_key  metric  score  label  played  eval  status  fixture_id  FT  HT  time

    IMPORTANT (dashboard):
    - On garde tout, mais dans les calculs “taux de réussite”, on ne prend QUE eval in (WIN, LOSS).
    """
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue

            # match_id col0, date col1, league col2, home col3, away col4, bet_key col5
            match_id = parts[0].strip()
            date_str = parts[1].strip()
            league = parts[2].strip()
            home = parts[3].strip()
            away = parts[4].strip()
            bet_key = parts[5].strip().upper()

            metric = parts[6].strip() if len(parts) > 6 else ""
            score = _safe_float(parts[7].strip(), 0.0) if len(parts) > 7 else 0.0
            label = parts[8].strip() if len(parts) > 8 else ""
            played = _safe_int(parts[9].strip(), 0) if len(parts) > 9 else 0
            ev = parts[10].strip().upper() if len(parts) > 10 else ""

            status = parts[11].strip() if len(parts) > 11 else ""
            fixture_id = parts[12].strip() if len(parts) > 12 else ""
            time_str = parts[15].strip() if len(parts) > 15 else ""

            rows.append(
                {
                    "match_id": match_id,
                    "date": date_str,
                    "time": time_str,
                    "league": league,
                    "home": home,
                    "away": away,
                    "bet_key": bet_key,
                    "metric": metric,
                    "score": score,
                    "label": label,
                    "played": int(played),
                    "eval": ev,
                    "status": status,
                    "fixture_id": fixture_id,
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["_date"] = pd.to_datetime(df["date"], errors="coerce")

    # normalisation légère
    df["league"] = df["league"].fillna("").astype(str)
    df["home"] = df["home"].fillna("").astype(str)
    df["away"] = df["away"].fillna("").astype(str)
    df["bet_key"] = df["bet_key"].fillna("").astype(str).str.upper()
    df["label"] = df["label"].fillna("").astype(str)
    df["eval"] = df["eval"].fillna("").astype(str).str.upper()

    return df


def load_ticket_verdicts() -> pd.DataFrame:
    """
    Charge:
      - data/verdict_post_analyse_tickets.txt
      - data/verdict_post_analyse_tickets_o15_random.txt

    Format (post_analysis_core._format_ticket_verdict_tsv):
      TSV: ticket_id  ticket_no  date  start_time  end_time  code  total_odd  legs  wins  losses  eval
    """
    rows: List[Dict[str, Any]] = []

    def _load_one(path: Path, source: str) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = (raw or "").strip()
                if not line.startswith("TSV:"):
                    continue
                parts = line[4:].lstrip().split("\t")
                if len(parts) < 11:
                    continue
                rows.append(
                    {
                        "source": source,
                        "ticket_id": parts[0].strip(),
                        "ticket_no": _safe_int(parts[1].strip(), 0),
                        "date": parts[2].strip(),
                        "start_time": parts[3].strip(),
                        "end_time": parts[4].strip(),
                        "code": parts[5].strip(),
                        "total_odd": parts[6].strip(),
                        "legs": _safe_int(parts[7].strip(), 0),
                        "wins": _safe_int(parts[8].strip(), 0),
                        "losses": _safe_int(parts[9].strip(), 0),
                        "eval": parts[10].strip().upper(),
                    }
                )

    _load_one(DEFAULT_TICKETS_SYSTEM_VERDICT_PATH, "SYSTEM")
    _load_one(DEFAULT_TICKETS_O15_VERDICT_PATH, "O15_RANDOM")
    _load_one(DEFAULT_TICKETS_U35_VERDICT_PATH, "U35_RANDOM")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["_date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


# =====================================================
# FILTERS APPLY
# =====================================================

def apply_filters(df: pd.DataFrame, f: VerdictFilters) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()

    if f.leagues:
        out = out[out["league"].astype(str).isin([str(x) for x in f.leagues])]
    if f.bet_keys:
        out = out[out["bet_key"].astype(str).str.upper().isin([str(x).upper() for x in f.bet_keys])]
    if f.labels:
        out = out[out["label"].astype(str).isin([str(x) for x in f.labels])]
    if f.evals:
        out = out[out["eval"].astype(str).str.upper().isin([str(x).upper() for x in f.evals])]

    if f.date_min is not None:
        out = out[out["_date"].notna() & (out["_date"] >= f.date_min)]
    if f.date_max is not None:
        out = out[out["_date"].notna() & (out["_date"] <= f.date_max)]

    return out


# =====================================================
# KPIs (ultra simples et lisibles)
# =====================================================

def _decided_only(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    # “Joué” + verdict final exploitable
    return df[(df["played"] == 1) & (df["eval"].isin(["WIN", "LOSS"]))].copy()


def kpi_success(df: pd.DataFrame) -> Dict[str, Any]:
    decided = _decided_only(df)
    played = int((df["played"] == 1).sum()) if df is not None and not df.empty else 0
    wins = int((decided["eval"] == "WIN").sum()) if not decided.empty else 0
    losses = int((decided["eval"] == "LOSS").sum()) if not decided.empty else 0
    decided_n = wins + losses
    win_rate = (wins / decided_n) if decided_n > 0 else None

    return {
        "played": played,
        "decided": decided_n,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
    }


# =====================================================
# TABLES (league / bet_key / matrices)
# =====================================================

def league_table(df: pd.DataFrame) -> pd.DataFrame:
    decided = _decided_only(df)
    if decided.empty:
        return pd.DataFrame(columns=["league", "played", "decided", "wins", "losses", "win_rate"])

    g = decided.groupby("league", dropna=False)
    out = pd.DataFrame(
        {
            "league": g.size().index,
            "decided": g.size().values,
            "wins": g.apply(lambda x: int((x["eval"] == "WIN").sum())).values,
            "losses": g.apply(lambda x: int((x["eval"] == "LOSS").sum())).values,
        }
    )
    out["win_rate"] = out["wins"] / out["decided"]

    # played total (inclut pending/no_bet etc si played=1)
    played = df[df["played"] == 1].groupby("league").size()
    out["played"] = out["league"].map(played).fillna(0).astype(int)

    out = out.sort_values(by=["win_rate", "decided"], ascending=[False, False]).reset_index(drop=True)
    return out


def bet_key_table(df: pd.DataFrame) -> pd.DataFrame:
    decided = _decided_only(df)
    if decided.empty:
        return pd.DataFrame(columns=["bet_key", "decided", "wins", "losses", "win_rate"])

    g = decided.groupby("bet_key", dropna=False)
    out = pd.DataFrame(
        {
            "bet_key": g.size().index,
            "decided": g.size().values,
            "wins": g.apply(lambda x: int((x["eval"] == "WIN").sum())).values,
            "losses": g.apply(lambda x: int((x["eval"] == "LOSS").sum())).values,
        }
    )
    out["win_rate"] = out["wins"] / out["decided"]
    out = out.sort_values(by=["win_rate", "decided"], ascending=[False, False]).reset_index(drop=True)
    return out


def league_x_bet_table(df: pd.DataFrame) -> pd.DataFrame:
    decided = _decided_only(df)
    if decided.empty:
        return pd.DataFrame()

    # table “plate”
    g = decided.groupby(["league", "bet_key"])
    t = g["eval"].agg(
        decided="count",
        wins=lambda s: int((s == "WIN").sum()),
        losses=lambda s: int((s == "LOSS").sum()),
    ).reset_index()
    t["win_rate"] = t["wins"] / t["decided"]

    # pivot “lisible”
    # colonnes: <bet>| n, <bet>| win%
    bet_keys = sorted(t["bet_key"].unique().tolist())
    leagues = sorted(t["league"].unique().tolist())

    rows = []
    for lg in leagues:
        row: Dict[str, Any] = {"league": lg}
        sub = t[t["league"] == lg]
        for bk in bet_keys:
            s2 = sub[sub["bet_key"] == bk]
            if s2.empty:
                row[f"{bk} | n"] = 0
                row[f"{bk} | win%"] = None
            else:
                row[f"{bk} | n"] = int(s2["decided"].iloc[0])
                row[f"{bk} | win%"] = float(s2["win_rate"].iloc[0] * 100.0)
        rows.append(row)

    m = pd.DataFrame(rows)
    return m


# =====================================================
# TICKETS KPIs
# =====================================================

def tickets_kpis(tickets_df: pd.DataFrame) -> pd.DataFrame:
    if tickets_df is None or tickets_df.empty:
        return pd.DataFrame()

    df = tickets_df.copy()
    df = df[df["eval"].isin(["WIN", "LOSS"])].copy()
    if df.empty:
        return pd.DataFrame()

    g = df.groupby("source", dropna=False)
    out = pd.DataFrame(
        {
            "source": g.size().index,
            "decided": g.size().values,
            "wins": g.apply(lambda x: int((x["eval"] == "WIN").sum())).values,
            "losses": g.apply(lambda x: int((x["eval"] == "LOSS").sum())).values,
        }
    )
    out["win_rate"] = out["wins"] / out["decided"]
    out = out.sort_values(by=["win_rate", "decided"], ascending=[False, False]).reset_index(drop=True)
    return out


# =====================================================
# RANKINGS (ligues / équipes) — PAR BET_KEY (c’est la règle clé)
# =====================================================

def _team_long(home: str, away: str) -> List[str]:
    h = (home or "").strip()
    a = (away or "").strip()
    out = []
    if h:
        out.append(h)
    if a:
        out.append(a)
    return out


def build_rankings_from_verdicts(
    bets_df: pd.DataFrame,
    *,
    min_samples: int = 12,
) -> Dict[str, pd.DataFrame]:
    """
    Construit 2 classements :
      1) league × bet_key
      2) team × bet_key  (team = home/away, on “attribue” le résultat aux deux équipes)

    Base: UNIQUEMENT eval WIN/LOSS et played=1 (donc stable).
    """
    decided = _decided_only(bets_df)
    if decided.empty:
        empty_lg = pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])
        empty_tm = pd.DataFrame(columns=["team", "bet_key", "decided", "wins", "losses", "win_rate"])
        return {"leagues": empty_lg, "teams": empty_tm}

    # --- LEAGUES x BET
    g1 = decided.groupby(["league", "bet_key"], dropna=False)
    leagues = g1["eval"].agg(
        decided="count",
        wins=lambda s: int((s == "WIN").sum()),
        losses=lambda s: int((s == "LOSS").sum()),
    ).reset_index()
    leagues["win_rate"] = leagues["wins"] / leagues["decided"]
    leagues["eligible"] = leagues["decided"] >= int(min_samples)

    leagues = leagues.sort_values(
        by=["win_rate", "decided", "eligible"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    # --- TEAMS x BET
    team_rows: List[Dict[str, Any]] = []
    for _, r in decided.iterrows():
        for t in _team_long(r.get("home", ""), r.get("away", "")):
            team_rows.append(
                {
                    "team": t,
                    "bet_key": str(r.get("bet_key") or ""),
                    "eval": str(r.get("eval") or ""),
                }
            )
    tdf = pd.DataFrame(team_rows)
    g2 = tdf.groupby(["team", "bet_key"], dropna=False)
    teams = g2["eval"].agg(
        decided="count",
        wins=lambda s: int((s == "WIN").sum()),
        losses=lambda s: int((s == "LOSS").sum()),
    ).reset_index()
    teams["win_rate"] = teams["wins"] / teams["decided"]
    teams["eligible"] = teams["decided"] >= int(min_samples)

    def _cap_progressive(n: int) -> float:
        """
        Cap progressif selon decided:
        - n <= 12  => 1.5
        - 12..20   => 1.5 -> 2.0 (linéaire)
        - 20..30   => 2.0 -> 2.5 (linéaire)
        - n >= 30  => 2.5
        """
        n = int(n or 0)
        if n <= 12:
            return 1.5
        if n < 20:
            # 12 -> 1.5 ; 20 -> 2.0
            return 1.5 + (n - 12) * (0.5 / 8.0)
        if n < 30:
            # 20 -> 2.0 ; 30 -> 2.5
            return 2.0 + (n - 20) * (0.5 / 10.0)
        return 2.5


    def _weight_from_rank(n_items: int, rank0: int) -> float:
        """
        Poids "théorique" selon rang (meilleur=2.5, pire=1.0), linéaire.
        rank0 = 0 pour le meilleur, n_items-1 pour le pire.
        """
        if n_items <= 1:
            return 2.5
        t = 1.0 - (rank0 / (n_items - 1))  # 1.0 pour meilleur -> 0.0 pour pire
        return 1.0 + t * (2.5 - 1.0)


    # On calcule les poids par bet_key, car on "range par classement" à l'intérieur d'un bet.
    teams["team_weight_rank"] = 1.0
    teams["team_weight_cap"] = teams["decided"].apply(_cap_progressive)
    teams["team_weight"] = 1.0

    for bk, sub_idx in teams.groupby("bet_key", dropna=False).groups.items():
        # sub_idx = index des lignes de ce bet_key
        sub = teams.loc[sub_idx].copy()

        # classement par win_rate desc puis decided desc (c'est ton ordre)
        sub = sub.sort_values(by=["win_rate", "decided"], ascending=[False, False])

        n_items = len(sub)
        # rank0 = 0..n-1 dans cet ordre
        rank_map = {idx: i for i, idx in enumerate(sub.index.tolist())}

        # poids final = min(poids_rang, cap_progressif(decided))
        for idx in sub.index:
            rank0 = rank_map[idx]
            w_rank = _weight_from_rank(n_items, rank0)
            cap = float(teams.at[idx, "team_weight_cap"])
            teams.at[idx, "team_weight_rank"] = w_rank
            teams.at[idx, "team_weight"] = min(w_rank, cap)

    teams = teams.sort_values(
        by=["win_rate", "decided", "eligible"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return {"leagues": leagues, "teams": teams}


def write_rankings_files(
    bets_df: pd.DataFrame,
    *,
    min_samples: int = 12,
) -> Dict[str, Path]:
    """
    Écrit 2 TSV dans data/ :
      - data/triskele_rank_leagues_x_bet.tsv
      - data/triskele_rank_teams_x_bet.tsv

    Recalculés “full” à chaque appel (c’est voulu).
    """
    r = build_rankings_from_verdicts(bets_df, min_samples=min_samples)
    lg = r["leagues"].copy()
    tm = r["teams"].copy()

    TRISKELE_RANK_LEAGUES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRISKELE_RANK_TEAMS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # TSV simple, stable
    lg.to_csv(TRISKELE_RANK_LEAGUES_PATH, sep="\t", index=False, encoding="utf-8")
    tm.to_csv(TRISKELE_RANK_TEAMS_PATH, sep="\t", index=False, encoding="utf-8")

    return {"leagues": TRISKELE_RANK_LEAGUES_PATH, "teams": TRISKELE_RANK_TEAMS_PATH}

# =====================================================
# BASELINE RANKINGS (data/rankings/…) — pour dashboard
#   - On lit les TSV baseline
#   - On normalise vers: decided/wins/losses/win_rate
#   - On expose aussi des classements globaux (tous bet confondus)
# =====================================================

def _read_rank_tsv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()
    return df


def _to_int_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def _to_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0).astype(float)


def _standardize_baseline_league_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepte 2 formats:
      A) baseline: league, bet_key, samples, success, fail, success_rate
      B) legacy-like: league, bet_key, decided, wins, losses, win_rate (éventuellement eligible)
    Sortie standard:
      league, bet_key, decided, wins, losses, win_rate
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])

    cols = {c.strip(): c for c in df.columns}

    # format A
    if {"league", "bet_key", "samples", "success", "fail"}.issubset(set(cols.keys())):
        out = pd.DataFrame()
        out["league"] = df[cols["league"]].astype(str)
        out["bet_key"] = df[cols["bet_key"]].astype(str).str.upper()
        out["decided"] = _to_int_series(df[cols["samples"]])
        out["wins"] = _to_int_series(df[cols["success"]])
        out["losses"] = _to_int_series(df[cols["fail"]])

        if "success_rate" in cols:
            wr = _to_float_series(df[cols["success_rate"]])
            # on accepte 0..1 ou 0..100
            out["win_rate"] = wr.apply(lambda x: (x / 100.0) if x > 1.00001 else x)
        else:
            out["win_rate"] = out.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)

        return out

    # format B
    if {"league", "bet_key", "decided", "wins", "losses"}.issubset(set(cols.keys())):
        out = pd.DataFrame()
        out["league"] = df[cols["league"]].astype(str)
        out["bet_key"] = df[cols["bet_key"]].astype(str).str.upper()
        out["decided"] = _to_int_series(df[cols["decided"]])
        out["wins"] = _to_int_series(df[cols["wins"]])
        out["losses"] = _to_int_series(df[cols["losses"]])
        if "win_rate" in cols:
            out["win_rate"] = _to_float_series(df[cols["win_rate"]])
        else:
            out["win_rate"] = out.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)
        return out

    # inconnu
    return pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])


def _standardize_baseline_team_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepte 2 formats:
      A) baseline: league, team, bet_key, samples, success, fail, success_rate
      B) legacy-like: team, bet_key, decided, wins, losses, win_rate (+ éventuellement league)
    Sortie standard:
      league, team, bet_key, decided, wins, losses, win_rate
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"])

    cols = {c.strip(): c for c in df.columns}

    # format A
    if {"league", "team", "bet_key", "samples", "success", "fail"}.issubset(set(cols.keys())):
        out = pd.DataFrame()
        out["league"] = df[cols["league"]].astype(str)
        out["team"] = df[cols["team"]].astype(str)
        out["bet_key"] = df[cols["bet_key"]].astype(str).str.upper()
        out["decided"] = _to_int_series(df[cols["samples"]])
        out["wins"] = _to_int_series(df[cols["success"]])
        out["losses"] = _to_int_series(df[cols["fail"]])

        if "success_rate" in cols:
            wr = _to_float_series(df[cols["success_rate"]])
            out["win_rate"] = wr.apply(lambda x: (x / 100.0) if x > 1.00001 else x)
        else:
            out["win_rate"] = out.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)

        return out

    # format B (si jamais)
    if {"team", "bet_key", "decided", "wins", "losses"}.issubset(set(cols.keys())):
        out = pd.DataFrame()
        out["league"] = df[cols["league"]].astype(str) if "league" in cols else ""
        out["team"] = df[cols["team"]].astype(str)
        out["bet_key"] = df[cols["bet_key"]].astype(str).str.upper()
        out["decided"] = _to_int_series(df[cols["decided"]])
        out["wins"] = _to_int_series(df[cols["wins"]])
        out["losses"] = _to_int_series(df[cols["losses"]])
        if "win_rate" in cols:
            out["win_rate"] = _to_float_series(df[cols["win_rate"]])
        else:
            out["win_rate"] = out.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)
        return out

    return pd.DataFrame(columns=["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"])


def load_baseline_rankings() -> Dict[str, pd.DataFrame]:
    """
    Charge les fichiers baseline (data/rankings/…)
    Retour:
      {
        "league_x_bet": df,
        "team_x_bet": df
      }
    """
    lg_raw = _read_rank_tsv(BASELINE_RANK_LEAGUES_X_BET_PATH)
    tm_raw = _read_rank_tsv(BASELINE_RANK_TEAMS_X_BET_PATH)

    lg = _standardize_baseline_league_x_bet(lg_raw)
    tm = _standardize_baseline_team_x_bet(tm_raw)

    return {"league_x_bet": lg, "team_x_bet": tm}


def baseline_global_leagues_table(
    baseline_league_x_bet: pd.DataFrame,
    *,
    min_samples: int = 12,
) -> pd.DataFrame:
    """
    Classement global des LIGUES (tous bet_key confondus) à partir du baseline league_x_bet.
    """
    if baseline_league_x_bet is None or baseline_league_x_bet.empty:
        return pd.DataFrame(columns=["league", "decided", "wins", "losses", "win_rate", "eligible"])

    df = baseline_league_x_bet.copy()
    df["league"] = df["league"].fillna("").astype(str)

    g = df.groupby("league", dropna=False)[["decided", "wins", "losses"]].sum().reset_index()
    g["win_rate"] = g.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)
    g["eligible"] = g["decided"] >= int(min_samples)

    g = g.sort_values(by=["eligible", "win_rate", "decided"], ascending=[False, False, False]).reset_index(drop=True)
    return g


def baseline_global_teams_table(
    baseline_team_x_bet: pd.DataFrame,
    *,
    min_samples: int = 12,
) -> pd.DataFrame:
    """
    Classement global des ÉQUIPES (tous bet_key confondus) à partir du baseline team_x_bet.
    """
    if baseline_team_x_bet is None or baseline_team_x_bet.empty:
        return pd.DataFrame(columns=["team", "decided", "wins", "losses", "win_rate", "eligible"])

    df = baseline_team_x_bet.copy()
    df["team"] = df["team"].fillna("").astype(str)

    g = df.groupby("team", dropna=False)[["decided", "wins", "losses"]].sum().reset_index()
    g["win_rate"] = g.apply(lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1)
    g["eligible"] = g["decided"] >= int(min_samples)

    g = g.sort_values(by=["eligible", "win_rate", "decided"], ascending=[False, False, False]).reset_index(drop=True)
    return g