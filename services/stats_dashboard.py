# services/stats_dashboard.py
from __future__ import annotations
from datetime import datetime, date as date_cls, timedelta

from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, date as date_cls
from typing import List, Optional, Set
import re

import pandas as pd
import streamlit as st

ODD_DISCOUNT_RATE = 0.15
ODD_MULT = 1.0 - ODD_DISCOUNT_RATE  # 0.85
ODD_MIN_EFFECTIVE = 1.01  # évite odd <= 1.0


# ============================================================
# Paths
# ============================================================

DATA_DIR = Path("data")

BETS_VERDICT_FILE = DATA_DIR / "verdict_post_analyse.txt"

TICKETS_SYSTEM_VERDICT_FILE = DATA_DIR / "verdict_post_analyse_tickets.txt"
TICKETS_RANDOM_VERDICT_FILE = DATA_DIR / "verdict_post_analyse_tickets_o15_random.txt"

# ✅ report_globaux (source de vérité : tickets réellement “sélectionnés”)
TICKETS_SYSTEM_REPORT_GLOBAL = DATA_DIR / "tickets_report_global.txt"
TICKETS_RANDOM_REPORT_GLOBAL = DATA_DIR / "tickets_o15_random_report_global.txt"

# ✅ BASELINE rankings (nouvelle vérité : data/rankings/)
BASELINE_RANK_LEAGUES_X_BET_FILE = DATA_DIR / "rankings" / "triskele_ranking_league_x_bet.tsv"
BASELINE_RANK_TEAMS_X_BET_FILE   = DATA_DIR / "rankings" / "triskele_ranking_team_x_bet.tsv"

# ✅ CORRELATIONS (baseline depuis results.tsv)
CORR_LEAGUE_BETS_FILE  = DATA_DIR / "correlations" / "triskele_baseline_league_bets.tsv"
CORR_LEAGUE_PAIRS_FILE = DATA_DIR / "correlations" / "triskele_baseline_league_pairs.tsv"


# ============================================================
# Parsing helpers
# ============================================================

def _is_date(s: str) -> bool:
    s = (s or "").strip()
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _to_float(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip().replace(",", ".")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _to_int(x, default=0):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default


def _read_tsv_lines(path: Path) -> List[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [
        l.rstrip("\n")
        for l in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if l.strip()
    ]


def _time_to_minutes(t: str) -> int:
    t = (t or "").strip()
    try:
        hh, mm = t.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 10**9


def _parse_bets_verdict(path: Path) -> pd.DataFrame:
    """
    Expected:
    TSV: match_id  date  league  home  away  bet_key  metric  score  label  played  eval  status  fixture_id  ft_score  ht_score  time
    """
    rows = []
    for line in _read_tsv_lines(path):
        if not line.startswith("TSV:"):
            continue
        parts = line[4:].lstrip().split("\t")
        if len(parts) < 12:
            continue
        match_id = parts[0].strip()
        d = parts[1].strip()
        if not _is_date(d):
            continue

        league = parts[2].strip()
        home = parts[3].strip()
        away = parts[4].strip()
        bet_key = parts[5].strip().upper()
        metric = parts[6].strip() if len(parts) > 6 else ""
        score = _to_float(parts[7] if len(parts) > 7 else "", default=None)
        label = parts[8].strip() if len(parts) > 8 else ""
        played = _to_int(parts[9] if len(parts) > 9 else "0", default=0)
        ev = (parts[10] if len(parts) > 10 else "").strip().upper()
        status = (parts[11] if len(parts) > 11 else "").strip().upper()
        fixture_id = parts[12].strip() if len(parts) > 12 else ""
        ft_score = parts[13].strip() if len(parts) > 13 else ""
        ht_score = parts[14].strip() if len(parts) > 14 else ""
        time_str = parts[15].strip() if len(parts) > 15 else ""

        rows.append(
            dict(
                match_id=match_id,
                date=d,
                league=league,
                home=home,
                away=away,
                bet_key=bet_key,
                metric=metric,
                score=score,
                label=label,
                played=int(played == 1),
                eval=ev,
                status=status,
                fixture_id=fixture_id,
                ft_score=ft_score,
                ht_score=ht_score,
                time=time_str,
            )
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["_date"] = df["date"]
    df["time"] = df["time"].fillna("").astype(str)
    df["_time_sort"] = df["time"].apply(_time_to_minutes)

    for c in ["league", "home", "away", "bet_key", "label", "eval"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("").astype(str)

    return df


def _parse_tickets_verdict(path: Path) -> pd.DataFrame:
    """
    Expected:
    TSV: ticket_id  ticket_no  date  start_time  end_time  code  total_odd  legs  wins  losses  eval
    """
    rows = []
    for line in _read_tsv_lines(path):
        if not line.startswith("TSV:"):
            continue
        parts = line[4:].lstrip().split("\t")
        if len(parts) < 11:
            continue

        ticket_id = parts[0].strip()
        ticket_no = _to_int(parts[1], default=0)
        d = parts[2].strip()
        if not _is_date(d):
            continue

        start_time = parts[3].strip()
        end_time = parts[4].strip()
        code = parts[5].strip()
        total_odd = _to_float(parts[6], default=None)
        
        # ✅ Correction cotes (-15%)
        if total_odd is not None:
            total_odd = max(ODD_MIN_EFFECTIVE, float(total_odd) * ODD_MULT)

        legs = _to_int(parts[7], default=0)
        wins = _to_int(parts[8], default=0)
        losses = _to_int(parts[9], default=0)
        ev = (parts[10] or "").strip().upper()

        rows.append(
            dict(
                ticket_id=ticket_id,
                ticket_no=ticket_no,
                date=d,
                start_time=start_time,
                end_time=end_time,
                code=code,
                total_odd=total_odd,
                legs=legs,
                wins=wins,
                losses=losses,
                eval=ev,
            )
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["_date"] = df["date"]
    df["_start_sort"] = df["start_time"].fillna("").astype(str).apply(_time_to_minutes)
    df["_end_sort"] = df["end_time"].fillna("").astype(str).apply(_time_to_minutes)

    for c in ["eval", "code", "ticket_id"]:
        df[c] = df[c].fillna("").astype(str)

    return df

def _read_corr_tsv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _tab_correlations():
    st.subheader("📈 Corrélations (Baseline results.tsv)")

    df_bets = _read_corr_tsv(CORR_LEAGUE_BETS_FILE)
    df_pairs = _read_corr_tsv(CORR_LEAGUE_PAIRS_FILE)

    if df_bets.empty and df_pairs.empty:
        st.info(
            "Aucun fichier de corrélation trouvé.\n\n"
            "➡️ Génère-les via `services/correlation_core.py` (build_baseline_correlation_files)\n"
            f"- attendu: {CORR_LEAGUE_BETS_FILE}\n"
            f"- attendu: {CORR_LEAGUE_PAIRS_FILE}"
        )
        return

    # --------- Normalisation types (lisible)
    def _to_int_col(df: pd.DataFrame, col: str):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    def _to_float_col(df: pd.DataFrame, col: str):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

    for c in ["samples", "success", "fail"]:
        _to_int_col(df_bets, c)
    _to_float_col(df_bets, "success_rate")

    _to_int_col(df_pairs, "n_pair")
    for c in ["phi", "p_b_given_a", "p_b", "lift", "joint_rate"]:
        _to_float_col(df_pairs, c)

    # --------- filtres simples
    leagues = sorted(set([x for x in df_bets.get("league", pd.Series([])).tolist() if str(x).strip()] +
                         [x for x in df_pairs.get("league", pd.Series([])).tolist() if str(x).strip()]))

    sel_league = st.selectbox("Championnat", options=(["ALL"] + leagues), index=0)

    st.divider()

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### ✅ Baseline par bet (dans la ligue)")
        view = df_bets.copy()
        if sel_league != "ALL":
            view = view[view["league"] == sel_league]
        if not view.empty:
            view = view.sort_values(by=["success_rate", "samples"], ascending=[False, False])
            view = view.rename(
                columns={
                    "league": "Championnat",
                    "bet_key": "Bet",
                    "samples": "samples",
                    "success": "success",
                    "fail": "fail",
                    "success_rate": "success_rate",
                }
            )



            _render_table(view, percent_cols=["success_rate"], height=520)
        else:
            st.info("Aucune ligne baseline (filtre trop restrictif).")

    with c2:
        st.markdown("### 🔗 Corrélations (paires de bets)")

        min_n = st.slider("Min n_pair", min_value=0, max_value=200, value=25, step=1)
        mode = st.radio("Afficher", ["TOP +", "TOP -"], horizontal=True)

        pv = df_pairs.copy()
        if sel_league != "ALL":
            pv = pv[pv["league"] == sel_league]
        pv = pv[pv["n_pair"] >= int(min_n)]

        if not pv.empty:
            # TOP+ = phi desc, TOP- = phi asc
            pv = pv.sort_values(by=["phi", "n_pair"], ascending=[(mode == "TOP -"), False])

            pv = pv.rename(
                columns={
                    "league": "Championnat",
                    "bet_a": "Bet A",
                    "bet_b": "Bet B",
                    "n_pair": "n_pair",
                    "phi": "phi",
                    "p_b_given_a": "P(B|A)",
                    "p_b": "P(B)",
                    "lift": "lift",
                    "joint_rate": "P(A&B)",
                }
            )
            _render_table(pv, percent_cols=["P(B|A)", "P(B)", "P(A&B)"], height=520)
        else:
            st.info("Aucune paire (augmente la ligue ou baisse min n_pair).")

# ============================================================
# Report-global ticket_id extraction + filtering
# ============================================================

_ID_RE = re.compile(r"\bid=([^\s\]\)>,;]+)")


def _extract_ticket_ids_from_report(path: Path) -> Set[str]:
    """
    Lit un report_global et extrait tous les ticket_id via le motif: id=<ticket_id>
    """
    ids: Set[str] = set()
    for line in _read_tsv_lines(path):
        m = _ID_RE.search(line)
        if not m:
            continue
        tid = (m.group(1) or "").strip()
        # nettoyage léger
        tid = tid.strip().strip('"').strip("'")
        if tid:
            ids.add(tid)
    return ids


def _filter_tickets_by_report_global(df_tickets: pd.DataFrame, report_path: Path, label: str) -> pd.DataFrame:
    """
    Filtre df_tickets pour ne garder QUE les tickets présents dans le report_global.
    Si le report est absent/vide => on ne filtre pas, mais on avertit.
    """
    if df_tickets.empty:
        return df_tickets

    ids = _extract_ticket_ids_from_report(report_path)
    if not ids:
        st.warning(
            f"[{label}] Aucun ticket_id trouvé dans {report_path.name}. "
            f"➡️ Je n'applique pas le filtre (affichage complet)."
        )
        return df_tickets

    out = df_tickets[df_tickets["ticket_id"].isin(list(ids))].copy()
    return out


# ============================================================
# Aggregations + formatting
# ============================================================

def _pct(x: float) -> str:
    if x is None or pd.isna(x):
        return ""
    return f"{100.0 * float(x):.1f}%"


def _safe_div(a: float, b: float) -> float:
    return (a / b) if b else 0.0


def _win_loss_played(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    """
    df: bets verdicts.
    Uses played==True and eval in {WIN, LOSS}.
    """
    if df.empty:
        return pd.DataFrame()

    d = df[(df["played"] == True) & (df["eval"].isin(["WIN", "LOSS"]))].copy()
    if d.empty:
        return pd.DataFrame()

    g = d.groupby(group_cols, dropna=False)["eval"].value_counts().unstack(fill_value=0)
    if "WIN" not in g.columns:
        g["WIN"] = 0
    if "LOSS" not in g.columns:
        g["LOSS"] = 0

    g = g.reset_index()
    g["played"] = g["WIN"] + g["LOSS"]
    g["win_rate"] = g.apply(lambda r: _safe_div(r["WIN"], r["played"]), axis=1)

    cols = list(group_cols) + ["LOSS", "WIN", "played", "win_rate"]
    g = g[cols]
    return g


# ============================================================
# Martingale simulation (dynamic base stake)
# ============================================================

@dataclass
class MartingaleParams:
    bankroll0: float
    max_losses: int


def _base_stake(bankroll: float, max_losses: int) -> float:
    """
    Base stake recalculée avec bankroll COURANTE (dynamique).
    Survie à max_losses défaites d'affilée en doublant:

      stake * (2^max_losses - 1) <= bankroll
      => stake = bankroll / (2^max_losses - 1)

    Si max_losses == 0: stake = bankroll (un seul coup).
    """
    b = max(0.0, float(bankroll))
    n = int(max(0, max_losses))
    if b <= 0:
        return 0.0
    if n == 0:
        return b
    denom = (2 ** n) - 1
    if denom <= 0:
        return b
    return b / float(denom)


def simulate_martingale(tickets_df: pd.DataFrame, params: MartingaleParams) -> pd.DataFrame:
    """
    tickets_df attendu avec colonnes: date, ticket_no, total_odd, eval (+ ticket_id, code, _start_sort, _end_sort)

    Règles:
    - mise de base recalculée à CHAQUE ticket selon bankroll actuelle (ta demande)
    - si on est en série de défaites: on double la mise précédente
    - WIN: profit = stake*(odd-1)
    - LOSS: bankroll -= stake
    - stop naturel si bankroll <= 0 ou stake <= 0
    """
    if tickets_df.empty:
        return pd.DataFrame()

    df = tickets_df.copy()
    df = df[df["eval"].isin(["WIN", "LOSS"])].copy()
    if df.empty:
        return pd.DataFrame()

    df = df.sort_values(
        by=["_date", "_start_sort", "_end_sort", "ticket_no"],
        ascending=[True, True, True, True],
    )

    bankroll = float(params.bankroll0)
    max_losses = int(params.max_losses)

    out_rows = []
    prev_stake = 0.0
    win_streak = 0
    loss_streak = 0
    max_win_streak = 0
    max_loss_streak = 0

    for _, r in df.iterrows():
        if bankroll <= 0:
            break

        odd = _to_float(r.get("total_odd"), default=2.0)
        odd = odd if (odd is not None and odd > 1.0) else 2.0

        base = _base_stake(bankroll, max_losses)

        if loss_streak == 0:
            stake = base
        else:
            stake = prev_stake * 2.0

        # ne jamais miser plus que bankroll
        stake = min(stake, bankroll)
        stake = float(round(stake, 2))

        if stake <= 0 or bankroll <= 0:
            break

        bankroll_before = float(round(bankroll, 2))
        ev = str(r.get("eval") or "").strip().upper()

        if ev == "WIN":
            profit = stake * (odd - 1.0)
            bankroll = bankroll + profit
            win_streak += 1
            loss_streak = 0
        else:
            bankroll = bankroll - stake
            loss_streak += 1
            win_streak = 0

        bankroll_after = float(round(bankroll, 2))
        prev_stake = stake

        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)

        out_rows.append(
            dict(
                date=r.get("date"),
                ticket_no=int(r.get("ticket_no") or 0),
                ticket_id=str(r.get("ticket_id") or ""),
                code=str(r.get("code") or ""),
                total_odd=float(round(odd, 3)),
                eval=ev,
                stake=stake,
                bankroll_before=bankroll_before,
                bankroll_after=bankroll_after,
                win_streak=win_streak,
                loss_streak=loss_streak,
                max_win_streak=max_win_streak,
                max_loss_streak=max_loss_streak,
            )
        )

    return pd.DataFrame(out_rows)


# ============================================================
# BASELINE RANKINGS (data/rankings/…) — affichage dashboard
# ============================================================

def _read_baseline_tsv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _baseline_to_int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def _baseline_to_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0).astype(float)


def _standardize_baseline_league_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepte:
      A) baseline: league, bet_key, samples, success, fail, success_rate
      B) compatible: league, bet_key, decided, wins, losses, win_rate

    ⚠️ Gère aussi les headers commentés type "# league".
    Sortie:
      league, bet_key, decided, wins, losses, win_rate
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])

    # normalise les noms de colonnes: enlève '#' + espaces + lowercase
    norm_map = {}
    for c in df.columns:
        n = str(c).strip()
        n = n.lstrip("#").strip().lower()
        norm_map[n] = c  # colonne réelle

    # format A
    if {"league", "bet_key", "samples", "success", "fail"}.issubset(set(norm_map.keys())):
        out = pd.DataFrame()
        out["league"] = df[norm_map["league"]].astype(str).fillna("")
        out["bet_key"] = df[norm_map["bet_key"]].astype(str).fillna("").str.upper()
        out["decided"] = _baseline_to_int(df[norm_map["samples"]])
        out["wins"] = _baseline_to_int(df[norm_map["success"]])
        out["losses"] = _baseline_to_int(df[norm_map["fail"]])

        if "success_rate" in norm_map:
            wr = _baseline_to_float(df[norm_map["success_rate"]])
            # accepte 0..1 ou 0..100
            out["win_rate"] = wr.apply(lambda x: (x / 100.0) if x > 1.00001 else x)
        else:
            out["win_rate"] = out.apply(
                lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1
            )

        return out

    # format B
    if {"league", "bet_key", "decided", "wins", "losses"}.issubset(set(norm_map.keys())):
        out = pd.DataFrame()
        out["league"] = df[norm_map["league"]].astype(str).fillna("")
        out["bet_key"] = df[norm_map["bet_key"]].astype(str).fillna("").str.upper()
        out["decided"] = _baseline_to_int(df[norm_map["decided"]])
        out["wins"] = _baseline_to_int(df[norm_map["wins"]])
        out["losses"] = _baseline_to_int(df[norm_map["losses"]])

        if "win_rate" in norm_map:
            out["win_rate"] = _baseline_to_float(df[norm_map["win_rate"]])
        else:
            out["win_rate"] = out.apply(
                lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1
            )

        return out

    return pd.DataFrame(columns=["league", "bet_key", "decided", "wins", "losses", "win_rate"])


def _standardize_baseline_team_x_bet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepte:
      A) baseline: league, team, bet_key, samples, success, fail, success_rate
      B) compatible: league?, team, bet_key, decided, wins, losses, win_rate

    ⚠️ Gère aussi les headers commentés type "# league".
    Sortie:
      league, team, bet_key, decided, wins, losses, win_rate
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"])

    # normalise les noms de colonnes: enlève '#' + espaces + lowercase
    norm_map = {}
    for c in df.columns:
        n = str(c).strip()
        n = n.lstrip("#").strip().lower()
        norm_map[n] = c  # colonne réelle

    # format A
    if {"league", "team", "bet_key", "samples", "success", "fail"}.issubset(set(norm_map.keys())):
        out = pd.DataFrame()
        out["league"] = df[norm_map["league"]].astype(str).fillna("")
        out["team"] = df[norm_map["team"]].astype(str).fillna("")
        out["bet_key"] = df[norm_map["bet_key"]].astype(str).fillna("").str.upper()
        out["decided"] = _baseline_to_int(df[norm_map["samples"]])
        out["wins"] = _baseline_to_int(df[norm_map["success"]])
        out["losses"] = _baseline_to_int(df[norm_map["fail"]])

        if "success_rate" in norm_map:
            wr = _baseline_to_float(df[norm_map["success_rate"]])
            out["win_rate"] = wr.apply(lambda x: (x / 100.0) if x > 1.00001 else x)
        else:
            out["win_rate"] = out.apply(
                lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1
            )

        return out

    # format B (league optionnel)
    if {"team", "bet_key", "decided", "wins", "losses"}.issubset(set(norm_map.keys())):
        out = pd.DataFrame()
        out["league"] = df[norm_map["league"]].astype(str).fillna("") if "league" in norm_map else ""
        out["team"] = df[norm_map["team"]].astype(str).fillna("")
        out["bet_key"] = df[norm_map["bet_key"]].astype(str).fillna("").str.upper()
        out["decided"] = _baseline_to_int(df[norm_map["decided"]])
        out["wins"] = _baseline_to_int(df[norm_map["wins"]])
        out["losses"] = _baseline_to_int(df[norm_map["losses"]])

        if "win_rate" in norm_map:
            out["win_rate"] = _baseline_to_float(df[norm_map["win_rate"]])
        else:
            out["win_rate"] = out.apply(
                lambda r: (r["wins"] / r["decided"]) if r["decided"] > 0 else 0.0, axis=1
            )

        return out

    return pd.DataFrame(columns=["league", "team", "bet_key", "decided", "wins", "losses", "win_rate"])


def _load_baseline_rankings() -> dict:
    lg_raw = _read_baseline_tsv(BASELINE_RANK_LEAGUES_X_BET_FILE)
    tm_raw = _read_baseline_tsv(BASELINE_RANK_TEAMS_X_BET_FILE)

    lg = _standardize_baseline_league_x_bet(lg_raw)
    tm = _standardize_baseline_team_x_bet(tm_raw)

    return {"league_x_bet": lg, "team_x_bet": tm}


def _baseline_global_leagues(df_league_x_bet: pd.DataFrame, *, min_samples: int) -> pd.DataFrame:
    if df_league_x_bet is None or df_league_x_bet.empty:
        return pd.DataFrame(columns=["league", "decided", "wins", "losses", "win_rate", "eligible"])

    g = df_league_x_bet.groupby("league", dropna=False)[["decided", "wins", "losses"]].sum().reset_index()
    g["win_rate"] = g.apply(lambda r: _safe_div(r["wins"], r["decided"]), axis=1)
    g["eligible"] = g["decided"] >= int(min_samples)
    g = g.sort_values(by=["eligible", "win_rate", "decided"], ascending=[False, False, False]).reset_index(drop=True)
    return g


def _baseline_global_teams(df_team_x_bet: pd.DataFrame, *, min_samples: int) -> pd.DataFrame:
    if df_team_x_bet is None or df_team_x_bet.empty:
        return pd.DataFrame(columns=["team", "decided", "wins", "losses", "win_rate", "eligible"])

    g = df_team_x_bet.groupby("team", dropna=False)[["decided", "wins", "losses"]].sum().reset_index()
    g["win_rate"] = g.apply(lambda r: _safe_div(r["wins"], r["decided"]), axis=1)
    g["eligible"] = g["decided"] >= int(min_samples)
    g = g.sort_values(by=["eligible", "win_rate", "decided"], ascending=[False, False, False]).reset_index(drop=True)
    return g


def _tab_baseline_rankings():
    st.subheader("📚 Baseline réelle (résultats terrain uniquement)")

    baseline = _load_baseline_rankings()
    df_lxb = baseline["league_x_bet"]
    df_txb = baseline["team_x_bet"]

    if (df_lxb is None or df_lxb.empty) and (df_txb is None or df_txb.empty):
        st.info(
            "Aucune baseline trouvée.\n\n"
            f"- attendu: {BASELINE_RANK_LEAGUES_X_BET_FILE}\n"
            f"- attendu: {BASELINE_RANK_TEAMS_X_BET_FILE}"
        )
        return

    t1, t2 = st.tabs(["🏆 Ligue × Bet", "👥 Équipe × Bet"])

    with t1:
        if df_lxb is None or df_lxb.empty:
            st.info("Aucune donnée.")
        else:
            view = df_lxb.copy()
            view = view.sort_values(by=["win_rate", "decided"], ascending=[False, False])

            view = view.rename(
                columns={
                    "league": "Championnat",
                    "bet_key": "Bet",
                    "decided": "samples",
                    "wins": "success",
                    "losses": "fail",
                    "win_rate": "success_rate",
                }
            )

            _render_table(view, percent_cols=["success_rate"], height=650)

    with t2:
        if df_txb is None or df_txb.empty:
            st.info("Aucune donnée.")
        else:
            view = df_txb.copy()
            view = view.sort_values(by=["win_rate", "decided"], ascending=[False, False])

            view = view.rename(
                columns={
                    "league": "Championnat",
                    "team": "Équipe",
                    "bet_key": "Bet",
                    "decided": "samples",
                    "wins": "success",
                    "losses": "fail",
                    "win_rate": "success_rate",
                }
            )

            _render_table(view, percent_cols=["success_rate"], height=650)


# ============================================================
# UI
# ============================================================

def _page_config():
    st.set_page_config(page_title="TRISKÈLE — Dashboard", layout="wide")


def _load_all_data():
    df_bets = _parse_bets_verdict(BETS_VERDICT_FILE)

    df_tickets_sys = _parse_tickets_verdict(TICKETS_SYSTEM_VERDICT_FILE)
    df_tickets_rand = _parse_tickets_verdict(TICKETS_RANDOM_VERDICT_FILE)

    # ✅ on filtre ici, à la source, selon report_global
    df_tickets_sys = _filter_tickets_by_report_global(df_tickets_sys, TICKETS_SYSTEM_REPORT_GLOBAL, "SYSTEM")
    df_tickets_rand = _filter_tickets_by_report_global(df_tickets_rand, TICKETS_RANDOM_REPORT_GLOBAL, "RANDOM")

    return df_bets, df_tickets_sys, df_tickets_rand


def _sidebar_filters(df_bets: pd.DataFrame):
    st.sidebar.header("Filtres (paris)")

    if df_bets.empty:
        st.sidebar.info("Aucune donnée bets.")
        return dict()

    leagues = sorted([x for x in df_bets["league"].dropna().unique().tolist() if str(x).strip()])
    bet_keys = sorted([x for x in df_bets["bet_key"].dropna().unique().tolist() if str(x).strip()])
    labels = sorted([x for x in df_bets["label"].dropna().unique().tolist() if str(x).strip()])

    sel_leagues = st.sidebar.multiselect("Championnat(s)", leagues, default=[])
    sel_bet_keys = st.sidebar.multiselect("Type de pari (bet_key)", bet_keys, default=[])
    sel_labels = st.sidebar.multiselect("Tag (label)", labels, default=[])

    sel_evals = st.sidebar.multiselect("Résultat (eval)", ["WIN", "LOSS"], default=["WIN", "LOSS"])

    # ✅ Période optionnelle
    dmin = df_bets["_date"].min()
    dmax = df_bets["_date"].max()

    all_dates = st.sidebar.checkbox("Toutes dates (pas de période)", value=True)

    p0, p1 = None, None
    if not all_dates and isinstance(dmin, date_cls) and isinstance(dmax, date_cls):
        period = st.sidebar.date_input("Période", value=(dmin, dmax))
        if isinstance(period, tuple) and len(period) == 2:
            p0, p1 = period
        else:
            p0, p1 = dmin, dmax

    return dict(
        leagues=set(sel_leagues),
        bet_keys=set(sel_bet_keys),
        labels=set(sel_labels),
        evals=set(sel_evals),
        date_from=p0,
        date_to=p1,
    )


def _apply_filters(df: pd.DataFrame, flt: dict) -> pd.DataFrame:
    if df.empty or not flt:
        return df

    out = df.copy()

    if flt.get("leagues"):
        out = out[out["league"].isin(list(flt["leagues"]))]

    if flt.get("bet_keys"):
        out = out[out["bet_key"].isin(list(flt["bet_keys"]))]

    if flt.get("labels"):
        out = out[out["label"].isin(list(flt["labels"]))]

    if flt.get("evals"):
        out = out[out["eval"].isin(list(flt["evals"]))]

    df0 = flt.get("date_from")
    df1 = flt.get("date_to")
    if isinstance(df0, date_cls):
        out = out[out["_date"] >= df0]
    if isinstance(df1, date_cls):
        out = out[out["_date"] <= df1]

    return out

def _summary_win_loss(df: pd.DataFrame) -> dict:
    """
    Résumé simple WIN/LOSS sur paris joués (played==True) et eval in {WIN, LOSS}.
    """
    if df is None or df.empty:
        return {"played": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    d = df[(df["played"] == True) & (df["eval"].isin(["WIN", "LOSS"]))].copy()
    if d.empty:
        return {"played": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    wins = int((d["eval"] == "WIN").sum())
    losses = int((d["eval"] == "LOSS").sum())
    played = wins + losses
    wr = _safe_div(wins, played)
    return {"played": played, "wins": wins, "losses": losses, "win_rate": wr}


def _render_global_and_filtered_summary(df_all: pd.DataFrame, df_filtered: pd.DataFrame, flt: dict):
    """
    Affiche en haut :
    - GLOBAL HISTORIQUE (toujours)
    - FILTRÉ (si filtres actifs)
    """
    # GLOBAL (historique complet)
    g = _summary_win_loss(df_all)

    # Détecter si l'utilisateur a réellement appliqué un filtre "restrictif"
    filters_active = False
    if flt:
        if flt.get("leagues") or flt.get("bet_keys") or flt.get("labels"):
            filters_active = True
        # evals : par défaut WIN+LOSS -> pas restrictif ; si user enlève un des deux -> restrictif
        evs = flt.get("evals") or set()
        if evs and evs != {"WIN", "LOSS"}:
            filters_active = True
        # période : si user a une date_from/date_to qui n'est pas "tout"
        # (on considère restrictif seulement si elles sont définies ET que ça coupe l'historique)
        if isinstance(flt.get("date_from"), date_cls) or isinstance(flt.get("date_to"), date_cls):
            filters_active = True

    # Bandeau GLOBAL
    st.markdown("### 📌 Résumé (historique complet)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchs joués", g["played"])
    c2.metric("WIN", g["wins"])
    c3.metric("LOSS", g["losses"])
    c4.metric("Winrate", _pct(g["win_rate"]))

    # Bandeau FILTRÉ (uniquement si filtres actifs)
    if filters_active:
        f = _summary_win_loss(df_filtered)

        # label texte “filtres actifs”
        parts = []
        if flt.get("leagues"):
            parts.append(f"Leagues={len(flt['leagues'])}")
        if flt.get("bet_keys"):
            parts.append(f"Bet={len(flt['bet_keys'])}")
        if flt.get("labels"):
            parts.append(f"Tags={len(flt['labels'])}")
        if flt.get("evals") and flt.get("evals") != {"WIN", "LOSS"}:
            parts.append("Eval filtré")
        if isinstance(flt.get("date_from"), date_cls) or isinstance(flt.get("date_to"), date_cls):
            parts.append("Période")

        st.markdown(f"### 🎯 Résumé (filtré) — {' | '.join(parts) if parts else 'Filtres'}")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Matchs joués", f["played"])
        d2.metric("WIN", f["wins"])
        d3.metric("LOSS", f["losses"])
        d4.metric("Winrate", _pct(f["win_rate"]))

    st.divider()

def _render_table(
    df: pd.DataFrame,
    percent_cols: Optional[List[str]] = None,
    height: int = 520,
    *,
    color_win_loss: bool = False,
    eval_col: str = "eval",
    float_decimals: Optional[List[str]] = None,
):
    if df.empty:
        st.info("Aucune donnée.")
        return

    view = df.copy()
    percent_cols = percent_cols or []
    for c in percent_cols:
        if c in view.columns:
            view[c] = view[c].apply(_pct)

    styler = view.style

    # ✅ Arrondi à 2 chiffres après la virgule pour les colonnes demandées
    if float_decimals:
        format_dict = {c: "{:.2f}" for c in float_decimals if c in view.columns}
        styler = styler.format(format_dict)

    # ✅ Coloration uniquement de la cellule (case) contenant WIN/LOSS
    if color_win_loss and eval_col in view.columns:
        def _cell_style(val):
            v = str(val).strip().upper()
            if v == "WIN":
                return "background-color: #e7f6ea; color: #1b5e20; font-weight: bold;"
            if v == "LOSS":
                return "background-color: #fdecea; color: #b71c1c; font-weight: bold;"
            return ""
        
        if hasattr(styler, "map"):
            styler = styler.map(_cell_style, subset=[eval_col])
        else:
            styler = styler.applymap(_cell_style, subset=[eval_col])

    st.dataframe(styler, use_container_width=True, height=height)


def _tab_championnats(df_bets: pd.DataFrame):
    st.subheader("Championnats (WIN/LOSS sur paris joués)")
    df_lb = _win_loss_played(df_bets, ["league"])
    df_lb = df_lb.sort_values(by=["win_rate", "played"], ascending=[False, False])
    _render_table(df_lb.rename(columns={"league": "Championnat"}), percent_cols=["win_rate"], height=420)

    st.divider()
    st.subheader("Championnats × Bet (historique)")
    df_lxb = _win_loss_played(df_bets, ["league", "bet_key"])
    df_lxb = df_lxb.sort_values(by=["win_rate", "played"], ascending=[False, False])
    _render_table(
        df_lxb.rename(columns={"league": "Championnat", "bet_key": "Bet"}),
        percent_cols=["win_rate"],
        height=520,
    )


def _tab_equipes(df_bets: pd.DataFrame):
    st.subheader("Équipes × Bet (WIN/LOSS sur paris joués)")

    if df_bets.empty:
        st.info("Aucune donnée.")
        return

    d = df_bets[(df_bets["played"] == True) & (df_bets["eval"].isin(["WIN", "LOSS"]))].copy()
    if d.empty:
        st.info("Aucun pari joué WIN/LOSS.")
        return

    rows = []
    for _, r in d.iterrows():
        league = r["league"]
        bet_key = r["bet_key"]
        ev = r["eval"]
        rows.append(dict(league=league, team=r["home"], bet_key=bet_key, eval=ev, played=True))
        rows.append(dict(league=league, team=r["away"], bet_key=bet_key, eval=ev, played=True))

    tdf = pd.DataFrame(rows)
    g = _win_loss_played(tdf, ["league", "team", "bet_key"])
    if g.empty:
        st.info("Aucune donnée exploitable.")
        return

    g = g.sort_values(by=["win_rate", "played"], ascending=[False, False])
    _render_table(
        g.rename(columns={"league": "Championnat", "team": "Équipe", "bet_key": "Bet"}),
        percent_cols=["win_rate"],
        height=620,
    )


def _tab_paris_details(df_bets: pd.DataFrame):
    st.subheader("Pari par pari (détails)")

    if df_bets.empty:
        st.info("Aucune donnée.")
        return

    cols = [
        "_date",
        "time",
        "league",
        "home",
        "away",
        "bet_key",
        "label",
        "played",
        "eval",
        "ft_score",
        "ht_score",
        "fixture_id",
        "match_id",
    ]
    view = df_bets.copy()
    for c in cols:
        if c not in view.columns:
            view[c] = ""
    view = view[cols].rename(
        columns={
            "_date": "date",
            "league": "Championnat",
            "home": "Home",
            "away": "Away",
            "bet_key": "Bet",
            "label": "Label",
            "played": "Played",
            "eval": "Eval",
            "ft_score": "FT",
            "ht_score": "HT",
            "fixture_id": "Fixture",
            "match_id": "MatchID",
        }
    )

    view = view.sort_values(by=["date", "time"], ascending=[True, True])
    st.dataframe(view, use_container_width=True, height=720)

def _martingale_period_filter(df_tickets: pd.DataFrame, *, key_prefix: str) -> pd.DataFrame:
    """
    Filtre dédié à la martingale (NE TOUCHE PAS aux autres tableaux).
    Par défaut: "Ce mois-ci".
    Presets: 10 derniers jours, 30 derniers jours, Année 2020, Tout.
    + option "Plage personnalisée".
    """
    if df_tickets is None or df_tickets.empty:
        return df_tickets

    # Sécurise le type date
    ddf = df_tickets.copy()
    if "_date" in ddf.columns:
        # _date est déjà date, mais on garde safe
        ddf["_date"] = pd.to_datetime(ddf["_date"], errors="coerce").dt.date
    else:
        ddf["_date"] = pd.to_datetime(ddf["date"], errors="coerce").dt.date

    today = datetime.today().date()
    first_day_month = today.replace(day=1)

    options = [
        "Ce mois-ci (défaut)",
        "10 derniers jours",
        "30 derniers jours",
        "Année 2020",
        "Tout (historique)",
        "Plage personnalisée",
    ]

    sel = st.selectbox(
        "Période (martingale)",
        options=options,
        index=0,  # ✅ défaut = ce mois-ci
        key=f"{key_prefix}_mart_period_mode",
    )

    start: Optional[date_cls] = None
    end: Optional[date_cls] = None

    if sel.startswith("Ce mois-ci"):
        start = first_day_month
        end = today
    elif sel.startswith("10 derniers"):
        start = today - timedelta(days=9)
        end = today
    elif sel.startswith("30 derniers"):
        start = today - timedelta(days=29)
        end = today
    elif sel.startswith("Année 2020"):
        start = date_cls(2020, 1, 1)
        end = date_cls(2020, 12, 31)
    elif sel.startswith("Tout"):
        start = None
        end = None
    else:
        # Plage personnalisée
        dmin = ddf["_date"].min()
        dmax = ddf["_date"].max()
        if isinstance(dmin, date_cls) and isinstance(dmax, date_cls):
            p = st.date_input(
                "Plage personnalisée (martingale)",
                value=(dmin, dmax),
                key=f"{key_prefix}_mart_period_custom",
            )
            if isinstance(p, tuple) and len(p) == 2:
                start, end = p[0], p[1]
            else:
                start, end = dmin, dmax

    out = ddf
    if isinstance(start, date_cls):
        out = out[out["_date"] >= start]
    if isinstance(end, date_cls):
        out = out[out["_date"] <= end]

    # petit rappel visuel
    if isinstance(start, date_cls) or isinstance(end, date_cls):
        st.caption(f"Filtre martingale actif : {start or '…'} → {end or '…'} | tickets: {len(out)}")

    return out


def _martingale_block(df_tickets: pd.DataFrame, title: str, key_prefix: str):
    st.markdown(f"### {title}")

    if df_tickets.empty:
        st.info("Aucun ticket.")
        return
    
        # ✅ filtre dédié à la martingale (indépendant des autres filtres)
    df_tickets = _martingale_period_filter(df_tickets, key_prefix=key_prefix)

    if df_tickets.empty:
        st.info("Aucun ticket dans cette période (martingale).")
        return

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        bankroll0 = st.number_input(
            "Bankroll initiale",
            min_value=0.0,
            value=3000.0,
            step=100.0,
            key=f"{key_prefix}_bankroll0",
        )
    with col2:
        max_losses = st.slider(
            "Défaites max (doublage)",
            min_value=0,
            max_value=10,
            value=5,
            step=1,
            key=f"{key_prefix}_max_losses",
        )
    with col3:
        st.caption(
            "Mise de base recalculée à chaque ticket selon la bankroll actuelle. "
            "Pendant une série de défaites, la mise double."
        )

    params = MartingaleParams(bankroll0=float(bankroll0), max_losses=int(max_losses))
    sim = simulate_martingale(df_tickets, params)

    if sim.empty:
        st.info("Pas de simulation possible (aucun ticket WIN/LOSS).")
        return

    last_row = sim.iloc[-1]

    last_row = sim.iloc[-1]

    # ✅ Success rate (WIN / (WIN+LOSS)) sur les tickets simulés
    wins = int((sim["eval"] == "WIN").sum())
    losses = int((sim["eval"] == "LOSS").sum())
    decided = wins + losses
    success_rate = (wins / decided) if decided > 0 else 0.0

    st.markdown(
        f"**Bankroll finale :** `{last_row['bankroll_after']:.2f}`  |  "
        f"**Max win streak :** `{int(last_row['max_win_streak'])}`  |  "
        f"**Max loss streak :** `{int(last_row['max_loss_streak'])}`  |  "
        f"**Tickets simulés :** `{len(sim)}`  |  "
        f"**Taux de réussite :** `{success_rate*100:.2f}%` ({wins}/{decided})"
    )

    view = sim.copy()
    view["date"] = pd.to_datetime(view["date"], errors="coerce").dt.date
    view = view[
        [
            "date",
            "ticket_no",
            "ticket_id",
            "code",
            "total_odd",
            "eval",
            "stake",
            "bankroll_before",
            "bankroll_after",
            "win_streak",
            "loss_streak",
        ]
    ].rename(
        columns={
            "ticket_no": "ticket",
            "total_odd": "odd",
            "eval": "result",
            "stake": "mise",
            "bankroll_before": "bankroll_avant",
            "bankroll_after": "bankroll_apres",
            "win_streak": "serie_victoires",
            "loss_streak": "serie_defaites",
        }
    )
    
    _render_table(
        view, 
        height=560, 
        color_win_loss=True, 
        eval_col="result",
        float_decimals=["odd", "mise", "bankroll_avant", "bankroll_apres"]
    )


def _tab_tickets(df_sys: pd.DataFrame, df_rand: pd.DataFrame):
    st.subheader("Tickets")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### SYSTEM — Tickets (verdict filtré report_global)")
        if df_sys.empty:
            st.info("Aucun ticket SYSTEM (ou filtre report_global vide).")
        else:
            v = df_sys.sort_values(by=["_date", "_start_sort", "_end_sort", "ticket_no"])
            view = v[
                ["date", "ticket_no", "start_time", "end_time", "code", "total_odd", "legs", "wins", "losses", "eval", "ticket_id"]
            ].rename(
                columns={
                    "ticket_no": "ticket",
                    "total_odd": "odd",
                    "eval": "result",
                }
            )
            _render_table(view, height=360, color_win_loss=True, eval_col="result", float_decimals=["odd"])

    with c2:
        st.markdown("### RANDOM — Tickets (verdict filtré report_global)")
        if df_rand.empty:
            st.info("Aucun ticket RANDOM (ou filtre report_global vide).")
        else:
            v = df_rand.sort_values(by=["_date", "_start_sort", "_end_sort", "ticket_no"])
            view = v[
                ["date", "ticket_no", "start_time", "end_time", "code", "total_odd", "legs", "wins", "losses", "eval", "ticket_id"]
            ].rename(
                columns={
                    "ticket_no": "ticket",
                    "total_odd": "odd",
                    "eval": "result",
                }
            )
            _render_table(view, height=360, color_win_loss=True, eval_col="result", float_decimals=["odd"])
            
    st.divider()
    st.subheader("🧪 Simulation Martingale (plein écran)")
    
    sub1, sub2 = st.tabs(["SYSTEM", "RANDOM"])
    with sub1:
        _martingale_block(df_sys, "SYSTEM — Martingale", key_prefix="mart_sys")
    with sub2:
        _martingale_block(df_rand, "RANDOM — Martingale", key_prefix="mart_rand")


def main(set_page_config: bool = True):
    if set_page_config:
        _page_config()

    st.title("TRISKÈLE — Dashboard")

    df_bets, df_tickets_sys, df_tickets_rand = _load_all_data()

    flt = _sidebar_filters(df_bets)
    df_bets_f = _apply_filters(df_bets, flt)

    # ✅ Résumé global + résumé filtré
    _render_global_and_filtered_summary(df_bets, df_bets_f, flt)

    tabs = st.tabs(["🏆 Championnats", "👥 Équipes", "🎯 Paris (détails)", "🎟️ Tickets", "📚 Baseline", "📈 Corrélations"])

    with tabs[0]:
        _tab_championnats(df_bets_f)
    with tabs[1]:
        _tab_equipes(df_bets_f)
    with tabs[2]:
        _tab_paris_details(df_bets_f)
    with tabs[3]:
        _tab_tickets(df_tickets_sys, df_tickets_rand)
    with tabs[4]:
        _tab_baseline_rankings()
    with tabs[5]:
        _tab_correlations()


if __name__ == "__main__":
    main(set_page_config=True)