# services/correlation_core.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import math
import pandas as pd

DATA_DIR = Path("data")
RESULTS_TSV = DATA_DIR / "results.tsv"

CORR_DIR = DATA_DIR / "correlations"
LEAGUE_BETS_FILE = CORR_DIR / "triskele_baseline_league_bets.tsv"
LEAGUE_PAIRS_FILE = CORR_DIR / "triskele_baseline_league_pairs.tsv"


# ---------------------------
# Helpers
# ---------------------------

def _is_date(s: str) -> bool:
    s = (s or "").strip()
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_int_str(s: str) -> bool:
    try:
        int(str(s).strip())
        return True
    except Exception:
        return False


def _parse_score(score: str) -> Tuple[Optional[int], Optional[int]]:
    s = (score or "").strip()
    if not s or "-" not in s:
        return None, None
    try:
        a, b = s.split("-", 1)
        return int(a), int(b)
    except Exception:
        return None, None


def _phi(n11: int, n10: int, n01: int, n00: int) -> float:
    # phi = (n11*n00 - n10*n01) / sqrt((n11+n10)(n01+n00)(n11+n01)(n10+n00))
    a = float(n11)
    b = float(n10)
    c = float(n01)
    d = float(n00)
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom <= 0:
        return 0.0
    return (a * d - b * c) / math.sqrt(denom)


# ---------------------------
# Baseline bets (lisibles)
# ---------------------------

BASELINE_BETS = [
    "O15_FT",
    "HT05",
    "HT1X_HOME",
    "TEAM1_SCORE_FT",
    "TEAM2_SCORE_FT",
]


def _compute_bets_for_match(
    gh: int,
    ga: int,
    gh_ht: Optional[int],
    ga_ht: Optional[int],
) -> Dict[str, Optional[bool]]:
    """
    Retourne {bet_key: True/False/None}
    None = "non calculable" (ex: HT manquant)
    """
    out: Dict[str, Optional[bool]] = {}

    # FT (toujours calculable si FT présent)
    out["O15_FT"] = (gh + ga) >= 2
    out["TEAM1_SCORE_FT"] = gh >= 1
    out["TEAM2_SCORE_FT"] = ga >= 1

    # HT (uniquement si HT présent)
    if gh_ht is not None and ga_ht is not None:
        out["HT05"] = (gh_ht + ga_ht) >= 1
        out["HT1X_HOME"] = gh_ht >= ga_ht
    else:
        out["HT05"] = None
        out["HT1X_HOME"] = None

    return out


# ---------------------------
# Main builder
# ---------------------------

def build_baseline_correlation_files(
    *,
    results_path: Path = RESULTS_TSV,
    out_league_bets_path: Path = LEAGUE_BETS_FILE,
    out_pairs_path: Path = LEAGUE_PAIRS_FILE,
) -> Dict[str, Path]:
    """
    Lit data/results.tsv (source vérité), calcule:
      A) baseline league x bet (samples/success/fail/success_rate)
      B) corrélations par ligue entre bets (phi + lift + stats simples)
    Écrit 2 TSV dans data/correlations/
    """
    if not results_path.exists() or results_path.stat().st_size == 0:
        raise FileNotFoundError(f"Aucun results.tsv exploitable: {results_path}")

    # On reconstruit une liste de matchs exploitables (FT obligatoire)
    matches: List[Dict[str, Any]] = []

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
                continue  # FT absent => on ignore (baseline FT impossible)

            gh_ht, ga_ht = _parse_score(ht_score) if ht_score else (None, None)

            # clé unique (pas indispensable ici, mais stable)
            if fixture_id and _is_int_str(fixture_id):
                key = f"FID:{fixture_id}"
            else:
                key = f"{date_str}|{league}|{home}|{away}"

            matches.append(
                {
                    "key": key,
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
            )

    if not matches:
        raise RuntimeError("Aucun match exploitable dans results.tsv (FT manquant partout ?).")

    # -----------------------
    # A) League x bet rates
    # -----------------------
    agg_league_bet: Dict[Tuple[str, str], Dict[str, int]] = {}

    # Pour les corrélations: on va stocker, par ligue et par match, les valeurs (0/1/None) des bets
    league_match_bets: Dict[str, List[Dict[str, Optional[int]]]] = {}

    for m in matches:
        league = m["league"]
        bets = _compute_bets_for_match(m["gh"], m["ga"], m["gh_ht"], m["ga_ht"])

        # construit ligne binaire lisible pour correlations
        bin_row: Dict[str, Optional[int]] = {}
        for bk in BASELINE_BETS:
            v = bets.get(bk, None)
            if v is None:
                bin_row[bk] = None
            else:
                bin_row[bk] = 1 if v else 0

                # agrégation league x bet
                lk = (league, bk)
                agg_league_bet.setdefault(lk, {"samples": 0, "success": 0})
                agg_league_bet[lk]["samples"] += 1
                if v:
                    agg_league_bet[lk]["success"] += 1

        league_match_bets.setdefault(league, []).append(bin_row)

    # écrit league_bets.tsv
    CORR_DIR.mkdir(parents=True, exist_ok=True)
    rows_a = []
    for (league, bet_key), a in agg_league_bet.items():
        s = int(a["samples"])
        w = int(a["success"])
        fail = s - w
        sr = (w / s) if s else 0.0
        rows_a.append(
            {
                "league": league,
                "bet_key": bet_key,
                "samples": s,
                "success": w,
                "fail": fail,
                "success_rate": round(sr, 6),
            }
        )

    df_a = pd.DataFrame(rows_a)
    if not df_a.empty:
        df_a = df_a.sort_values(by=["success_rate", "samples"], ascending=[False, False]).reset_index(drop=True)
    df_a.to_csv(out_league_bets_path, sep="\t", index=False, encoding="utf-8")

    # -----------------------
    # B) Pairwise correlations per league
    # -----------------------
    pair_rows: List[Dict[str, Any]] = []

    bet_list = BASELINE_BETS[:]

    for league, rows in league_match_bets.items():
        # rows: list of dict {bet: 0/1/None}
        for i in range(len(bet_list)):
            for j in range(i + 1, len(bet_list)):
                a = bet_list[i]
                b = bet_list[j]

                n11 = n10 = n01 = n00 = 0
                # n_pair = matches where both calculable
                for r in rows:
                    va = r.get(a, None)
                    vb = r.get(b, None)
                    if va is None or vb is None:
                        continue
                    if va == 1 and vb == 1:
                        n11 += 1
                    elif va == 1 and vb == 0:
                        n10 += 1
                    elif va == 0 and vb == 1:
                        n01 += 1
                    else:
                        n00 += 1

                n_pair = n11 + n10 + n01 + n00
                if n_pair <= 0:
                    continue

                phi = _phi(n11, n10, n01, n00)

                # P(B=1|A=1)
                denom_a1 = n11 + n10
                p_b_given_a = (n11 / denom_a1) if denom_a1 else 0.0

                # P(B=1)
                p_b = ((n11 + n01) / n_pair) if n_pair else 0.0

                lift = (p_b_given_a / p_b) if p_b > 0 else 0.0
                joint_rate = (n11 / n_pair) if n_pair else 0.0

                pair_rows.append(
                    {
                        "league": league,
                        "bet_a": a,
                        "bet_b": b,
                        "n_pair": int(n_pair),
                        "phi": round(float(phi), 6),
                        "p_b_given_a": round(float(p_b_given_a), 6),
                        "p_b": round(float(p_b), 6),
                        "lift": round(float(lift), 6),
                        "joint_rate": round(float(joint_rate), 6),
                    }
                )

    df_pairs = pd.DataFrame(pair_rows)
    if not df_pairs.empty:
        # tri “beau”: d'abord par ligue, puis par |phi| desc, puis n_pair desc
        df_pairs["_abs_phi"] = df_pairs["phi"].abs()
        df_pairs = df_pairs.sort_values(by=["league", "_abs_phi", "n_pair"], ascending=[True, False, False]).drop(columns=["_abs_phi"])
        df_pairs = df_pairs.reset_index(drop=True)

    df_pairs.to_csv(out_pairs_path, sep="\t", index=False, encoding="utf-8")

    return {"league_bets": out_league_bets_path, "league_pairs": out_pairs_path}


if __name__ == "__main__":
    out = build_baseline_correlation_files()
    print("✅ Correlations écrites :")
    print(" -", out["league_bets"])
    print(" -", out["league_pairs"])