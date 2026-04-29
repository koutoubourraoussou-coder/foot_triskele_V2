#!/usr/bin/env python3
"""
simulate_variants.py — Monte Carlo backtesting pour toutes les stratégies random & super random.

Structure calquée sur compare_variants.py / bcea_session15_random_threshold.py
— même infrastructure (discover_datasets, _PatchedBuilderIO, _ticket_outcome, martingale).

Étendu pour couvrir les 6 stratégies : O15R, U35R, O25R + O15SR, U35SR, O25SR.

Deux familles de variants :
  - Grille partagée (shared)  : produit cartésien des params communs aux 2 pipelines
  - Extra random              : échantillon des params spécifiques au pipeline RANDOM

Pour chaque variant × run : séquence ordonnée (is_win, odd) par stratégie
→ stats flat + martingale normale + martingale safe.

Usage :
  python -u tools/backtest/simulate_variants.py --runs 20 --jobs 8
  python -u tools/backtest/simulate_variants.py --runs 50 --jobs 8 --max-days 14
  python -u tools/backtest/simulate_variants.py --runs 10 --jobs 4 --n-shared 200

Sorties :
  tools/backtest/results/backtest_TIMESTAMP.csv
  tools/backtest/results/best_params_TIMESTAMP.json
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import date as dt_date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Path setup
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import services.ticket_builder as tb
from services.ticket_builder import BuilderTuning
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_JOBS,
    DayDataset,
    _PatchedBuilderIO,
    _parse_verdict_file,
    _ticket_outcome,
    discover_datasets,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

ALL_STRATEGIES = ["O15R", "U35R", "O25R", "O15SR", "U35SR", "O25SR"]

BANKROLL0  = 100.0
MAX_LOSSES = 4          # martingale normale & safe : 2^4 = 16 niveaux

OUTPUT_DIR = ROOT / "tools" / "backtest" / "results"

# Budget de recherche forcé en backtest (ms) — réduit sans changer la logique
# (5ms ≈ 100-200 itérations, suffisant sur des pools de 5-20 picks)
BACKTEST_SEARCH_BUDGET_MS = 5

# ─────────────────────────────────────────────────────────────────────────────
# Grilles de paramètres
# ─────────────────────────────────────────────────────────────────────────────

# Communs random + super random → grille complète testée
SHARED_GRID: Dict[str, List[Any]] = {
    "target_odd":                    [1.8, 2.0, 2.2, 2.4, 2.6],
    "min_accept_odd":                [1.4, 1.6, 1.8, 2.0],
    "random_league_bet_min_winrate": [None, 0.50, 0.55, 0.60, 0.65, 0.70],
    "rich_day_match_count":          [12, 15, 18],
    "day_max_windows_rich":          [2, 3, 4],
    "day_max_windows_poor":          [1, 2],
    "min_side_matches_for_split":    [3, 5, 7],
    "split_gap_weight":              [0.4, 0.6, 0.8],
}
# Taille : 5×4×4×3×3×2×3×3 = 6 480 combos

# Spécifiques au pipeline RANDOM → échantillonnage
RANDOM_EXTRA_GRID: Dict[str, List[Any]] = {
    "league_bet_require_data": [False, True],
    "topk_size":               [5, 10, 20],
    "topk_uniform_draw":       [True, False],
    "prefer_3legs_delta":      [0.0, 0.05, 0.10, 0.15],
    "random_build_source":     ["LEAGUE", "TEAM", "HYBRID"],
    "random_select_source":    ["LEAGUE", "TEAM"],
}


def _backtest_defaults() -> Dict[str, Any]:
    """Valeurs par défaut pour les params non variés dans un run donné."""
    return {
        # random-specific — par défaut profil champion
        "league_bet_require_data": False,
        "topk_size":               10,
        "topk_uniform_draw":       True,
        "prefer_3legs_delta":      0.08,
        "random_build_source":     "TEAM",
        "random_select_source":    "TEAM",
        # budgets forcés petits pour la vitesse
        "search_budget_ms_system": BACKTEST_SEARCH_BUDGET_MS,
        "search_budget_ms_random": BACKTEST_SEARCH_BUDGET_MS,
    }


def generate_shared_variants(n_max: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Produit cartésien sur SHARED_GRID avec params random-specific aux valeurs par défaut.
    Si n_max est fourni, échantillonne aléatoirement n_max combos.
    """
    keys = list(SHARED_GRID.keys())
    vals = [SHARED_GRID[k] for k in keys]
    defaults = _backtest_defaults()
    all_combos = list(itertools.product(*vals))
    if n_max and n_max < len(all_combos):
        rng = random.Random(42)
        all_combos = rng.sample(all_combos, n_max)
    return [{**dict(zip(keys, c)), **defaults} for c in all_combos]


def generate_extra_variants(n_sample: int = 300, seed: int = 42) -> List[Dict[str, Any]]:
    """Échantillonne l'espace SHARED × RANDOM_EXTRA pour explorer les params spécifiques."""
    combined = {**SHARED_GRID, **RANDOM_EXTRA_GRID}
    keys = list(combined.keys())
    vals = [combined[k] for k in keys]
    rng = random.Random(seed)
    seen: set = set()
    variants: List[Dict[str, Any]] = []
    budget = _backtest_defaults()
    for _ in range(n_sample * 50):
        if len(variants) >= n_sample:
            break
        combo = tuple(rng.choice(v) for v in vals)
        if combo not in seen:
            seen.add(combo)
            d = dict(zip(keys, combo))
            d["search_budget_ms_system"] = BACKTEST_SEARCH_BUDGET_MS
            d["search_budget_ms_random"] = BACKTEST_SEARCH_BUDGET_MS
            variants.append(d)
    return variants


# ─────────────────────────────────────────────────────────────────────────────
# Extraction de la cote cumulée d'un ticket
# ─────────────────────────────────────────────────────────────────────────────

def _ticket_odd(ticket) -> float:
    result = 1.0
    for p in ticket.picks:
        result *= (p.odd or 1.0)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Martingale (copié de compare_variants.py / validate_profiles.py)
# ─────────────────────────────────────────────────────────────────────────────

Seq = List[Tuple[bool, float]]  # (is_win, odd)


def _simulate_martingale_normal(sequence: Seq) -> Dict[str, Any]:
    bankroll = BANKROLL0; loss_streak = 0; prev_stake = 0.0
    n_wins = n_losses = 0; max_ls = max_ws = cur_ws = 0
    denom = float((2 ** MAX_LOSSES) - 1)
    for is_win, odd in sequence:
        if bankroll <= 0:
            break
        stake = (bankroll / denom) if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll)
        if stake <= 0:
            break
        if is_win:
            bankroll += stake * (odd - 1.0); n_wins += 1
            loss_streak = 0; cur_ws += 1; max_ws = max(max_ws, cur_ws)
        else:
            bankroll -= stake; n_losses += 1
            loss_streak += 1; cur_ws = 0; max_ls = max(max_ls, loss_streak)
        prev_stake = stake
    return {
        "multiple":         round(bankroll / BANKROLL0, 3),
        "profit":           round(bankroll - BANKROLL0, 2),
        "max_loss_streak":  max_ls,
        "max_win_streak":   max_ws,
        "ruined":           bankroll <= 0,
    }


def _simulate_martingale_safe(sequence: Seq) -> Dict[str, Any]:
    reserves = 0.0; n_doublings = 0
    n_wins = n_losses = 0; max_ls = max_ws = cur_ws = 0
    def _cb() -> float: return BANKROLL0 + 0.20 * reserves
    ba = _cb(); cb = ba; loss_streak = 0; prev_stake = 0.0
    denom = float((2 ** MAX_LOSSES) - 1)
    for is_win, odd in sequence:
        if ba <= 0:
            nb = _cb()
            if nb <= 0 or reserves <= 0:
                break
            ba = nb; cb = nb; loss_streak = 0; prev_stake = 0.0
        stake = (ba / denom) if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, ba)
        if stake <= 0:
            break
        if is_win:
            ba += stake * (odd - 1.0); n_wins += 1
            loss_streak = 0; cur_ws += 1; max_ws = max(max_ws, cur_ws)
            if ba >= cb * 2.0:
                reserves += ba - cb; ba = _cb(); cb = ba; prev_stake = 0.0; n_doublings += 1
                continue
        else:
            ba -= stake; n_losses += 1; loss_streak += 1; cur_ws = 0; max_ls = max(max_ls, loss_streak)
        prev_stake = stake
    total = ba + reserves
    return {
        "multiple":         round(total / BANKROLL0, 3),
        "profit":           round(total - BANKROLL0, 2),
        "max_loss_streak":  max_ls,
        "max_win_streak":   max_ws,
        "n_doublings":      n_doublings,
        "ruined":           ba <= 0 and reserves <= 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agrégation des statistiques sur N runs
# ─────────────────────────────────────────────────────────────────────────────

def _agg(seqs: List[Seq]) -> Dict[str, Any]:
    """Agrège N séquences de tickets → stats flat + martingale."""
    n = len(seqs)
    normals, safes = [], []
    win_rates, loss_streaks, win_streaks, n_tickets_list = [], [], [], []

    for seq in seqs:
        if not seq:
            win_rates.append(0.0); n_tickets_list.append(0)
            loss_streaks.append(0); win_streaks.append(0)
        else:
            wins = sum(1 for w, _ in seq if w)
            win_rates.append(wins / len(seq)); n_tickets_list.append(len(seq))
            ls = ws = mls = mws = 0
            for iw, _ in seq:
                if iw: ws += 1; ls = 0; mws = max(mws, ws)
                else:  ls += 1; ws = 0; mls = max(mls, ls)
            loss_streaks.append(mls); win_streaks.append(mws)
        normals.append(_simulate_martingale_normal(seq))
        safes.append(_simulate_martingale_safe(seq))

    def _d(v: List[float]) -> Dict[str, float]:
        return {
            "mean": round(statistics.mean(v), 4),
            "min":  round(min(v), 4),
            "max":  round(max(v), 4),
            "std":  round(statistics.stdev(v) if n > 1 else 0.0, 4),
        }

    return {
        "n_runs":       n,
        "win_rate":     _d(win_rates),
        "n_tickets":    _d(n_tickets_list),
        "worst_streak": _d(loss_streaks),
        "best_streak":  _d(win_streaks),
        "normale": {
            "multiple":     _d([s["multiple"]       for s in normals]),
            "profit":       _d([s["profit"]         for s in normals]),
            "worst_streak": _d([s["max_loss_streak"] for s in normals]),
            "ruine_pct":    round(100 * sum(1 for s in normals if s["ruined"]) / n, 1),
        },
        "safe": {
            "multiple":     _d([s["multiple"]        for s in safes]),
            "profit":       _d([s["profit"]          for s in safes]),
            "worst_streak": _d([s["max_loss_streak"] for s in safes]),
            "doublings":    _d([s["n_doublings"]     for s in safes]),
            "ruine_pct":    round(100 * sum(1 for s in safes if s["ruined"]) / n, 1),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Score d'un variant (même formule que compare_variants.py)
# ─────────────────────────────────────────────────────────────────────────────

def _score(agg: Dict[str, Any]) -> float:
    return (
        agg["safe"]["multiple"]["mean"]   * 0.5
        + agg["win_rate"]["mean"]          * 0.3
        - agg["safe"]["ruine_pct"]         * 0.01
    )


# ─────────────────────────────────────────────────────────────────────────────
# Job multiprocessing — un variant, N runs
# ─────────────────────────────────────────────────────────────────────────────

def _run_variant_job(
    args: Tuple[int, Dict[str, Any], List[DayDataset], int, List[str]],
) -> Dict[str, Any]:
    """
    Exécuté dans un process enfant.

    Retourne :
        { "variant_idx": int, "params": dict, "agg": {strat: agg_dict} }
    """
    variant_idx, params, datasets, n_runs, active_strategies = args

    tuning = BuilderTuning(**params)

    # Pré-chargement des verdict maps (une fois par dataset)
    verdict_maps = {}
    for ds in datasets:
        verdict_maps[ds.day] = _parse_verdict_file(ds.verdict_file)

    # n_runs séquences par stratégie (active seulement)
    seqs_by_strat: Dict[str, List[Seq]] = {s: [] for s in active_strategies}

    with tempfile.TemporaryDirectory() as tmp_root:
        for run_i in range(n_runs):
            run_seqs: Dict[str, Seq] = {s: [] for s in active_strategies}

            for ds in datasets:
                vm = verdict_maps[ds.day]
                run_dir = Path(tmp_root) / f"r{run_i}" / ds.day

                with _PatchedBuilderIO(run_dir):
                    out = tb.generate_tickets_from_tsv(
                        str(ds.predictions_tsv),
                        run_date=None,
                        tuning=tuning,
                    )

                mapping = {
                    "O15R":  out.tickets_o15,
                    "U35R":  out.tickets_u35,
                    "O25R":  out.tickets_o25,
                    "O15SR": out.tickets_o15_super,
                    "U35SR": out.tickets_u35_super,
                    "O25SR": out.tickets_o25_super,
                }

                for strat in active_strategies:
                    for t in mapping.get(strat, []):
                        outcome = _ticket_outcome(t, vm)
                        if outcome is not None:
                            run_seqs[strat].append((outcome, _ticket_odd(t)))

            for s in active_strategies:
                seqs_by_strat[s].append(run_seqs[s])

    return {
        "variant_idx": variant_idx,
        "params":      params,
        "agg":         {s: _agg(seqs_by_strat[s]) for s in active_strategies},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Formatage CSV
# ─────────────────────────────────────────────────────────────────────────────

def _flatten_row(res: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"variant_idx": res["variant_idx"]}
    for k, v in res["params"].items():
        row[f"p_{k}"] = v if v is not None else "None"

    total_safe_mult = 0.0
    total_n = 0

    for s in ALL_STRATEGIES:
        agg = res["agg"].get(s, {})
        if not agg:
            continue

        def _m(path: List[str], default=0.0):
            d = agg
            for key in path:
                d = d.get(key, {})
            return d if not isinstance(d, dict) else default

        # Win rate
        row[f"{s}_wr_mean"]      = _m(["win_rate", "mean"])
        row[f"{s}_wr_min"]       = _m(["win_rate", "min"])
        row[f"{s}_wr_max"]       = _m(["win_rate", "max"])
        row[f"{s}_wr_std"]       = _m(["win_rate", "std"])

        # Tickets
        row[f"{s}_n_mean"]       = _m(["n_tickets", "mean"])
        row[f"{s}_n_min"]        = _m(["n_tickets", "min"])
        row[f"{s}_n_max"]        = _m(["n_tickets", "max"])
        row[f"{s}_n_std"]        = _m(["n_tickets", "std"])

        # Séries
        row[f"{s}_worst_streak_mean"] = _m(["worst_streak", "mean"])
        row[f"{s}_worst_streak_max"]  = _m(["worst_streak", "max"])
        row[f"{s}_best_streak_mean"]  = _m(["best_streak", "mean"])
        row[f"{s}_best_streak_max"]   = _m(["best_streak", "max"])

        # Martingale normale
        row[f"{s}_nm_mult_mean"]   = _m(["normale", "multiple", "mean"])
        row[f"{s}_nm_mult_min"]    = _m(["normale", "multiple", "min"])
        row[f"{s}_nm_mult_max"]    = _m(["normale", "multiple", "max"])
        row[f"{s}_nm_mult_std"]    = _m(["normale", "multiple", "std"])
        row[f"{s}_nm_profit_mean"] = _m(["normale", "profit", "mean"])
        row[f"{s}_nm_profit_min"]  = _m(["normale", "profit", "min"])
        row[f"{s}_nm_profit_max"]  = _m(["normale", "profit", "max"])
        row[f"{s}_nm_ruin"]        = _m(["normale", "ruine_pct"])
        row[f"{s}_nm_streak_mean"] = _m(["normale", "worst_streak", "mean"])
        row[f"{s}_nm_streak_max"]  = _m(["normale", "worst_streak", "max"])

        # Martingale safe
        row[f"{s}_safe_mult_mean"]   = _m(["safe", "multiple", "mean"])
        row[f"{s}_safe_mult_min"]    = _m(["safe", "multiple", "min"])
        row[f"{s}_safe_mult_max"]    = _m(["safe", "multiple", "max"])
        row[f"{s}_safe_mult_std"]    = _m(["safe", "multiple", "std"])
        row[f"{s}_safe_profit_mean"] = _m(["safe", "profit", "mean"])
        row[f"{s}_safe_profit_min"]  = _m(["safe", "profit", "min"])
        row[f"{s}_safe_profit_max"]  = _m(["safe", "profit", "max"])
        row[f"{s}_safe_ruin"]        = _m(["safe", "ruine_pct"])
        row[f"{s}_safe_streak_mean"] = _m(["safe", "worst_streak", "mean"])
        row[f"{s}_safe_streak_max"]  = _m(["safe", "worst_streak", "max"])
        row[f"{s}_safe_dbl_mean"]    = _m(["safe", "doublings", "mean"])
        row[f"{s}_safe_dbl_max"]     = _m(["safe", "doublings", "max"])
        row[f"{s}_score"]            = round(_score(agg), 4)

        total_safe_mult += _m(["safe", "multiple", "mean"])
        total_n         += int(_m(["n_tickets", "mean"]))

    row["total_safe_mult"] = round(total_safe_mult, 4)
    row["total_n"]         = total_n
    return row


def _write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[backtest] → {path}  ({len(rows):,} lignes)")


# ─────────────────────────────────────────────────────────────────────────────
# Rendu console (style compare_variants.py)
# ─────────────────────────────────────────────────────────────────────────────

def _render_variant(res: Dict[str, Any]) -> List[str]:
    lines = [f"  [Variant #{res['variant_idx']}]"]
    for s in ALL_STRATEGIES:
        agg = res["agg"].get(s, {})
        if not agg or not agg.get("n_runs"):
            continue
        wr  = agg["win_rate"]
        nm  = agg["normale"]
        sm  = agg["safe"]
        ws  = agg["worst_streak"]
        tk  = agg["n_tickets"]

        def f(d, k, dec=2):
            return f"moy={d[k]['mean']:.{dec}f}  min={d[k]['min']:.{dec}f}  max={d[k]['max']:.{dec}f}"

        lines += [
            f"",
            f"    ── {s} ──",
            f"      Tickets/run    : moy={tk['mean']:.1f}  min={tk['min']:.0f}  max={tk['max']:.0f}",
            f"      Win rate       : moy={wr['mean']:.3f}  σ={wr['std']:.3f}",
            f"      Pire série L   : moy={ws['mean']:.1f}  max={int(ws['max'])}",
            f"      NORMALE        : mult {f(nm,'multiple')}  ruine={nm['ruine_pct']:.0f}%  streak_L moy={nm['worst_streak']['mean']:.1f}",
            f"      SAFE           : mult {f(sm,'multiple')}  ruine={sm['ruine_pct']:.0f}%  dbl={sm['doublings']['mean']:.1f}  streak_L moy={sm['worst_streak']['mean']:.1f}",
        ]
    lines.append("")
    return lines


def _print_top_n(results: List[Dict[str, Any]], sort_strat: str, n: int = 10) -> None:
    key = lambda r: r["agg"].get(sort_strat, {}).get("safe", {}).get("multiple", {}).get("mean", 0.0)
    top = sorted(results, key=key, reverse=True)[:n]
    print(f"\n{'─'*80}")
    print(f"  TOP {n} pour {sort_strat} — Martingale SAFE mult (mean)")
    print(f"{'─'*80}")
    for rank, res in enumerate(top, 1):
        v = key(res)
        wr = res["agg"].get(sort_strat, {}).get("win_rate", {}).get("mean", 0.0)
        ru = res["agg"].get(sort_strat, {}).get("safe", {}).get("ruine_pct", 0.0)
        p  = res["params"]
        print(
            f"  #{rank:3d} [{res['variant_idx']:5d}]"
            f"  ×{v:.3f}  WR={wr:.2%}  ruine={ru:.0f}%"
            f"  target={p.get('target_odd','?')}  min_acc={p.get('min_accept_odd','?')}"
            f"  wr_min={p.get('random_league_bet_min_winrate','?')}"
            f"  rich={p.get('rich_day_match_count','?')}"
            f"  wrich={p.get('day_max_windows_rich','?')}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sauvegarde des meilleurs params
# ─────────────────────────────────────────────────────────────────────────────

def _save_best_params(results: List[Dict[str, Any]], output_dir: Path, timestamp: str, active_strategies: Optional[List[str]] = None) -> None:
    best: Dict[str, Any] = {}
    for strat in (active_strategies or ALL_STRATEGIES):
        top = max(
            results,
            key=lambda r: r["agg"].get(strat, {}).get("safe", {}).get("multiple", {}).get("mean", float("-inf")),
            default=None,
        )
        if top is None:
            continue
        agg = top["agg"].get(strat, {})
        best[strat] = {
            k[2:]: v for k, v in top["params"].items()
        }
        best[strat]["_safe_mult"] = agg.get("safe", {}).get("multiple", {}).get("mean", 0.0)
        best[strat]["_win_rate"]  = agg.get("win_rate", {}).get("mean", 0.0)
        best[strat]["_ruin_pct"]  = agg.get("safe", {}).get("ruine_pct", 0.0)
        best[strat]["_worst_streak"] = agg.get("worst_streak", {}).get("mean", 0.0)

    out = output_dir / f"best_params_{timestamp}.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(best, fh, indent=2, ensure_ascii=False, default=str)
    print(f"[backtest] Meilleurs params → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo backtest — random & super random (6 stratégies + martingale)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir",  type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--max-days",     type=int,  default=14,
                        help="Nombre de jours à utiliser (défaut: 14 derniers)")
    parser.add_argument("--runs",         type=int,  default=20,
                        help="Runs par variant (défaut: 20)")
    parser.add_argument("--jobs",         type=int,  default=DEFAULT_JOBS)
    parser.add_argument("--n-shared",     type=int,  default=None,
                        help="Max variants partagés (défaut: grille complète ~6480)")
    parser.add_argument("--n-extra",      type=int,  default=300,
                        help="Variants extra random (défaut: 300)")
    parser.add_argument("--shared-only",  action="store_true")
    parser.add_argument("--top-n",        type=int,  default=10)
    parser.add_argument("--output",       type=str,  default="")
    parser.add_argument("--strategies",      type=str, default="",
                        help="Stratégies à tester, séparées par virgule (ex: O15R,U35R). Défaut: toutes.")
    parser.add_argument("--variant-indices", type=str, default="",
                        help="Indices de variants à tester uniquement, séparés par virgule (ex: 19509,13277,8527).")
    parser.add_argument("--variant-file",    type=str, default="",
                        help="Fichier JSON contenant une liste de dicts de params à tester directement.")
    args = parser.parse_args()

    active_strategies = (
        [s.strip().upper() for s in args.strategies.split(",") if s.strip()]
        if args.strategies
        else ALL_STRATEGIES
    )
    invalid = [s for s in active_strategies if s not in ALL_STRATEGIES]
    if invalid:
        print(f"[backtest] ❌ Stratégies inconnues : {invalid}. Choix : {ALL_STRATEGIES}", file=sys.stderr)
        sys.exit(1)
    print(f"[backtest] Stratégies actives : {active_strategies}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # ── Datasets ───────────────────────────────────────────────────────────────
    datasets = discover_datasets(args.archive_dir, max_days=args.max_days)
    if not datasets:
        print("[backtest] ❌ Aucun dataset trouvé.", file=sys.stderr)
        sys.exit(1)
    print(f"\n[backtest] {len(datasets)} jours  ·  archive : {args.archive_dir}")
    for ds in datasets:
        print(f"  {ds.day}")

    # ── Variants ───────────────────────────────────────────────────────────────
    if args.variant_file:
        with open(args.variant_file, "r", encoding="utf-8") as fh:
            raw_variants = json.load(fh)
        defaults = _backtest_defaults()
        all_v = [{**defaults, **v} for v in raw_variants]
        print(f"\n[backtest] Chargement --variant-file : {len(all_v)} variants depuis {args.variant_file}")
    else:
        shared_v = generate_shared_variants(n_max=args.n_shared)
        extra_v  = [] if args.shared_only else generate_extra_variants(n_sample=args.n_extra)
        all_v    = shared_v + extra_v

        # Filtre par indices si --variant-indices fourni
        if args.variant_indices:
            keep = {int(x.strip()) for x in args.variant_indices.split(",") if x.strip()}
            all_v = [v for i, v in enumerate(all_v) if i in keep]
            print(f"\n[backtest] Filtre --variant-indices : {len(all_v)} variants retenus")

    if not args.variant_file:
        print(f"\n[backtest] {len(shared_v):,} variants partagés + {len(extra_v):,} extra = {len(all_v):,} actifs")
    print(f"[backtest] {args.runs} runs/variant  ·  {args.jobs} workers")
    print(f"[backtest] Budget recherche : {BACKTEST_SEARCH_BUDGET_MS}ms (system + random)")
    est_s = len(all_v) * args.runs * len(datasets) * 0.15 / max(1, args.jobs)
    print(f"[backtest] ETA ≈ {est_s/60:.1f}min (estimation)")

    jobs: List[Tuple] = [
        (i, v, datasets, args.runs, active_strategies)
        for i, v in enumerate(all_v)
    ]

    # ── Exécution ──────────────────────────────────────────────────────────────
    print(f"\n[backtest] Lancement...")
    t0 = time.time()
    results: List[Dict[str, Any]] = []

    if args.jobs == 1:
        for job in jobs:
            results.append(_run_variant_job(job))
            if len(results) % 50 == 0 or len(results) == len(jobs):
                elapsed = time.time() - t0
                eta = (len(jobs) - len(results)) / (len(results) / elapsed) if elapsed else 0
                print(f"[backtest] {len(results)}/{len(jobs)} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)
    else:
        done = 0
        step = max(1, len(jobs) // 20)
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futures = {ex.submit(_run_variant_job, job): job[0] for job in jobs}
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if done % step == 0 or done == len(jobs):
                    elapsed = time.time() - t0
                    eta = (len(jobs) - done) / (done / elapsed) if elapsed else 0
                    print(f"[backtest] {done}/{len(jobs)} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)

    elapsed_total = time.time() - t0
    print(f"\n[backtest] Terminé en {elapsed_total:.1f}s  ({elapsed_total/len(jobs)*1000:.1f}ms/variant)")

    # ── Tops console ───────────────────────────────────────────────────────────
    for strat in active_strategies:
        _print_top_n(results, strat, n=args.top_n)

    # Top 5 variants toutes stratégies confondues — par safe mult total
    print(f"\n{'═'*80}")
    print(f"  TOP 5 variants — Martingale SAFE mult TOTAL (somme des 6 stratégies)")
    print(f"{'═'*80}")
    def _total_safe(r):
        return sum(
            r["agg"].get(s, {}).get("safe", {}).get("multiple", {}).get("mean", 0.0)
            for s in ALL_STRATEGIES
        )
    for rank, res in enumerate(sorted(results, key=_total_safe, reverse=True)[:5], 1):
        v = _total_safe(res)
        print(f"  #{rank}  [{res['variant_idx']:5d}]  total safe mult={v:.3f}")
        lines = _render_variant(res)
        print("\n".join(lines))

    # ── Fichiers ───────────────────────────────────────────────────────────────
    rows = [_flatten_row(r) for r in results]
    rows.sort(key=lambda r: -r.get("total_safe_mult", 0.0))
    main_csv = Path(args.output) if args.output else OUTPUT_DIR / f"backtest_{timestamp}.csv"
    _write_csv(rows, main_csv)

    for strat in active_strategies:
        top50 = sorted(rows, key=lambda r: -r.get(f"{strat}_safe_mult_mean", 0.0))[:50]
        _write_csv(top50, OUTPUT_DIR / f"top50_{strat}_{timestamp}.csv")

    _save_best_params(results, OUTPUT_DIR, timestamp, active_strategies)

    print(f"\n[backtest] ═══════════════════════════════════════════════════════")
    print(f"[backtest] {len(results):,} variants  ·  CSV : {main_csv}")


if __name__ == "__main__":
    main()
