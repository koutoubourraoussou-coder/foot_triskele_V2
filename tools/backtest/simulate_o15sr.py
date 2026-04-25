#!/usr/bin/env python3
"""
simulate_o15sr.py — Backtest Monte Carlo ciblé O15SR (phase 2).

Grille resserrée autour des meilleurs params O15SR trouvés au run #1 :
  target_odd=2.6 · min_accept_odd=2.0 · wr_min=0.70
  rich_day=12 · max_windows_rich=4 · max_windows_poor=1
  min_side=5 · split_gap=0.4

Ne score QUE O15SR. 100 runs par variant pour stats robustes.

Usage :
  python -u tools/backtest/simulate_o15sr.py
  python -u tools/backtest/simulate_o15sr.py --runs 100 --jobs 8

Sorties :
  tools/backtest/results/o15sr_TIMESTAMP.csv
  tools/backtest/results/o15sr_best_TIMESTAMP.json
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

STRATEGY    = "O15SR"
BANKROLL0   = 100.0
MAX_LOSSES  = 4
OUTPUT_DIR  = ROOT / "tools" / "backtest" / "results"
BACKTEST_SEARCH_BUDGET_MS = 5

# ─────────────────────────────────────────────────────────────────────────────
# Grille resserrée autour des meilleurs params run #1
# ─────────────────────────────────────────────────────────────────────────────

GRID: Dict[str, List[Any]] = {
    "target_odd":                    [5.0],   # meilleur variant run #6 — test robustesse 103 jours
    "min_accept_odd":                [1.8],
    "random_league_bet_min_winrate": [0.65],
    "rich_day_match_count":          [12],
    "day_max_windows_rich":          [4],
    "day_max_windows_poor":          [2],
    "min_side_matches_for_split":    [3],
    "split_gap_weight":              [0.1],
}
# Total : 1 variant — test robustesse sur archive complète


def _defaults() -> Dict[str, Any]:
    return {
        "league_bet_require_data":  False,
        "topk_size":                10,
        "topk_uniform_draw":        True,
        "prefer_3legs_delta":       0.08,
        "random_build_source":      "TEAM",
        "random_select_source":     "TEAM",
        "search_budget_ms_system":  BACKTEST_SEARCH_BUDGET_MS,
        "search_budget_ms_random":  BACKTEST_SEARCH_BUDGET_MS,
    }


def generate_variants() -> List[Dict[str, Any]]:
    keys = list(GRID.keys())
    vals = [GRID[k] for k in keys]
    defaults = _defaults()
    return [{**dict(zip(keys, c)), **defaults} for c in itertools.product(*vals)]


# ─────────────────────────────────────────────────────────────────────────────
# Extraction de la cote cumulée
# ─────────────────────────────────────────────────────────────────────────────

def _ticket_odd(ticket) -> float:
    result = 1.0
    for p in ticket.picks:
        result *= (p.odd or 1.0)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Martingale
# ─────────────────────────────────────────────────────────────────────────────

Seq = List[Tuple[bool, float]]


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
        "multiple":        round(bankroll / BANKROLL0, 3),
        "profit":          round(bankroll - BANKROLL0, 2),
        "max_loss_streak": max_ls,
        "max_win_streak":  max_ws,
        "ruined":          bankroll <= 0,
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
        "multiple":        round(total / BANKROLL0, 3),
        "profit":          round(total - BANKROLL0, 2),
        "max_loss_streak": max_ls,
        "max_win_streak":  max_ws,
        "n_doublings":     n_doublings,
        "ruined":          ba <= 0 and reserves <= 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agrégation
# ─────────────────────────────────────────────────────────────────────────────

def _agg(seqs: List[Seq]) -> Dict[str, Any]:
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

    # Détail du meilleur et pire run (par safe multiple)
    safe_mults = [s["multiple"] for s in safes]
    best_idx  = safe_mults.index(max(safe_mults))
    worst_idx = safe_mults.index(min(safe_mults))

    def _run_detail(idx: int) -> Dict[str, Any]:
        return {
            "safe_mult":   safes[idx]["multiple"],
            "nm_mult":     normals[idx]["multiple"],
            "wr":          round(win_rates[idx], 4),
            "n_tickets":   n_tickets_list[idx],
            "win_streak":  win_streaks[idx],
            "loss_streak": loss_streaks[idx],
            "n_doublings": safes[idx]["n_doublings"],
            "ruined":      safes[idx]["ruined"],
        }

    return {
        "n_runs":       n,
        "win_rate":     _d(win_rates),
        "n_tickets":    _d(n_tickets_list),
        "worst_streak": _d(loss_streaks),
        "best_streak":  _d(win_streaks),
        "normale": {
            "multiple":     _d([s["multiple"]        for s in normals]),
            "profit":       _d([s["profit"]          for s in normals]),
            "worst_streak": _d([s["max_loss_streak"] for s in normals]),
            "ruine_pct":    round(100 * sum(1 for s in normals if s["ruined"]) / n, 1),
        },
        "safe": {
            "multiple":     _d([s["multiple"]        for s in safes]),
            "profit":       _d([s["profit"]          for s in safes]),
            "worst_streak": _d([s["max_loss_streak"] for s in safes]),
            "best_streak":  _d([s["max_win_streak"]  for s in safes]),
            "doublings":    _d([s["n_doublings"]     for s in safes]),
            "ruine_pct":    round(100 * sum(1 for s in safes if s["ruined"]) / n, 1),
        },
        "best_run":  _run_detail(best_idx),
        "worst_run": _run_detail(worst_idx),
    }


def _score(agg: Dict[str, Any]) -> float:
    return (
        agg["safe"]["multiple"]["mean"] * 0.5
        + agg["win_rate"]["mean"]       * 0.3
        - agg["safe"]["ruine_pct"]      * 0.01
    )


# ─────────────────────────────────────────────────────────────────────────────
# Job multiprocessing
# ─────────────────────────────────────────────────────────────────────────────

def _run_variant_job(
    args: Tuple[int, Dict[str, Any], List[DayDataset], int],
) -> Dict[str, Any]:
    variant_idx, params, datasets, n_runs = args

    tuning = BuilderTuning(**params)
    verdict_maps = {ds.day: _parse_verdict_file(ds.verdict_file) for ds in datasets}
    seqs: List[Seq] = []

    with tempfile.TemporaryDirectory() as tmp_root:
        for run_i in range(n_runs):
            run_seq: Seq = []
            for ds in datasets:
                vm = verdict_maps[ds.day]
                run_dir = Path(tmp_root) / f"r{run_i}" / ds.day
                with _PatchedBuilderIO(run_dir):
                    out = tb.generate_tickets_from_tsv(
                        str(ds.predictions_tsv),
                        run_date=None,
                        tuning=tuning,
                    )
                for t in out.tickets_o15_super:
                    outcome = _ticket_outcome(t, vm)
                    if outcome is not None:
                        run_seq.append((outcome, _ticket_odd(t)))
            seqs.append(run_seq)

    return {
        "variant_idx": variant_idx,
        "params":      params,
        "agg":         _agg(seqs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Formatage CSV
# ─────────────────────────────────────────────────────────────────────────────

def _flatten_row(res: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"variant_idx": res["variant_idx"]}
    for k, v in res["params"].items():
        row[f"p_{k}"] = v if v is not None else "None"
    agg = res["agg"]

    def _m(path):
        d = agg
        for key in path:
            d = d.get(key, {})
        return d if not isinstance(d, dict) else 0.0

    row["wr_mean"]           = _m(["win_rate", "mean"])
    row["wr_std"]            = _m(["win_rate", "std"])
    row["n_mean"]            = _m(["n_tickets", "mean"])
    row["n_min"]             = _m(["n_tickets", "min"])
    row["n_max"]             = _m(["n_tickets", "max"])
    row["loss_streak_mean"]  = _m(["worst_streak", "mean"])
    row["loss_streak_max"]   = _m(["worst_streak", "max"])
    row["win_streak_mean"]   = _m(["best_streak", "mean"])
    row["win_streak_max"]    = _m(["best_streak", "max"])
    row["nm_mult_mean"]      = _m(["normale", "multiple", "mean"])
    row["nm_mult_min"]       = _m(["normale", "multiple", "min"])
    row["nm_ruin"]           = _m(["normale", "ruine_pct"])
    row["nm_streak"]         = _m(["normale", "worst_streak", "mean"])
    row["safe_mult_mean"]    = _m(["safe", "multiple", "mean"])
    row["safe_mult_min"]     = _m(["safe", "multiple", "min"])
    row["safe_mult_max"]     = _m(["safe", "multiple", "max"])
    row["safe_mult_std"]     = _m(["safe", "multiple", "std"])
    row["safe_ruin"]         = _m(["safe", "ruine_pct"])
    row["safe_loss_str_mean"]= _m(["safe", "worst_streak", "mean"])
    row["safe_win_str_mean"] = _m(["safe", "best_streak", "mean"])
    row["safe_dbl"]          = _m(["safe", "doublings", "mean"])
    # Détail du meilleur run (safe mult max)
    br = agg.get("best_run", {})
    row["br_safe_mult"]  = br.get("safe_mult", 0)
    row["br_nm_mult"]    = br.get("nm_mult", 0)
    row["br_wr"]         = br.get("wr", 0)
    row["br_n_tickets"]  = br.get("n_tickets", 0)
    row["br_win_streak"] = br.get("win_streak", 0)
    row["br_loss_streak"]= br.get("loss_streak", 0)
    row["br_doublings"]  = br.get("n_doublings", 0)
    # Détail du pire run (safe mult min)
    wr_ = agg.get("worst_run", {})
    row["wr_safe_mult"]  = wr_.get("safe_mult", 0)
    row["wr_nm_mult"]    = wr_.get("nm_mult", 0)
    row["wr_wr"]         = wr_.get("wr", 0)
    row["wr_n_tickets"]  = wr_.get("n_tickets", 0)
    row["wr_win_streak"] = wr_.get("win_streak", 0)
    row["wr_loss_streak"]= wr_.get("loss_streak", 0)
    row["wr_doublings"]  = wr_.get("n_doublings", 0)
    row["wr_ruined"]     = wr_.get("ruined", False)
    row["score"]         = round(_score(agg), 4)
    return row


def _write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[o15sr] → {path}  ({len(rows):,} lignes)")


# ─────────────────────────────────────────────────────────────────────────────
# Rendu console
# ─────────────────────────────────────────────────────────────────────────────

def _print_top_n(results: List[Dict[str, Any]], n: int = 15) -> None:
    top = sorted(results, key=lambda r: r["agg"]["safe"]["multiple"]["mean"], reverse=True)[:n]
    print(f"\n{'─'*90}")
    print(f"  TOP {n} O15SR — Martingale SAFE mult (mean) — {results[0]['agg']['n_runs']} runs")
    print(f"{'─'*90}")
    for rank, res in enumerate(top, 1):
        agg = res["agg"]
        sm  = agg["safe"]["multiple"]["mean"]
        wr  = agg["win_rate"]["mean"]
        ru  = agg["safe"]["ruine_pct"]
        ls  = agg["safe"]["worst_streak"]["mean"]
        dbl = agg["safe"]["doublings"]["mean"]
        p   = res["params"]
        print(
            f"  #{rank:3d} [{res['variant_idx']:4d}]"
            f"  ×{sm:.3f}  WR={wr:.1%}  ruine={ru:.0f}%  streak={ls:.1f}  dbl={dbl:.1f}"
            f"  | target={p['target_odd']}  min_acc={p['min_accept_odd']}"
            f"  wr_min={p['random_league_bet_min_winrate']}"
            f"  rich={p['rich_day_match_count']}"
            f"  wrich={p['day_max_windows_rich']}  wpoor={p['day_max_windows_poor']}"
            f"  split={p['min_side_matches_for_split']}  gap={p['split_gap_weight']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sauvegarde meilleurs params
# ─────────────────────────────────────────────────────────────────────────────

def _save_best(results: List[Dict[str, Any]], output_dir: Path, timestamp: str) -> None:
    top = max(results, key=lambda r: r["agg"]["safe"]["multiple"]["mean"])
    agg = top["agg"]
    best = {
        **top["params"],
        "_safe_mult_mean": agg["safe"]["multiple"]["mean"],
        "_safe_mult_min":  agg["safe"]["multiple"]["min"],
        "_safe_mult_max":  agg["safe"]["multiple"]["max"],
        "_win_rate":       agg["win_rate"]["mean"],
        "_ruin_pct":       agg["safe"]["ruine_pct"],
        "_worst_streak":   agg["worst_streak"]["mean"],
        "_doublings":      agg["safe"]["doublings"]["mean"],
        "_n_runs":         agg["n_runs"],
    }
    out = output_dir / f"o15sr_best_{timestamp}.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(best, fh, indent=2, ensure_ascii=False, default=str)
    print(f"[o15sr] Meilleurs params → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest Monte Carlo ciblé O15SR — phase 2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--max-days",    type=int,  default=14)
    parser.add_argument("--runs",        type=int,  default=100)
    parser.add_argument("--jobs",        type=int,  default=DEFAULT_JOBS)
    parser.add_argument("--top-n",       type=int,  default=15)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Datasets
    datasets = discover_datasets(args.archive_dir, max_days=args.max_days)
    if not datasets:
        print("[o15sr] ❌ Aucun dataset trouvé.", file=sys.stderr)
        sys.exit(1)
    print(f"\n[o15sr] {len(datasets)} jours d'archive")
    for ds in datasets:
        print(f"  {ds.day}")

    # Variants
    variants = generate_variants()
    print(f"\n[o15sr] {len(variants):,} variants  ·  {args.runs} runs/variant  ·  {args.jobs} workers")
    print(f"[o15sr] Stratégie ciblée : {STRATEGY}")
    print(f"[o15sr] Budget recherche : {BACKTEST_SEARCH_BUDGET_MS}ms")

    jobs = [(i, v, datasets, args.runs) for i, v in enumerate(variants)]

    # Exécution
    print(f"\n[o15sr] Lancement...")
    t0 = time.time()
    results: List[Dict[str, Any]] = []
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
                print(f"[o15sr] {done}/{len(jobs)} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)

    elapsed_total = time.time() - t0
    print(f"\n[o15sr] Terminé en {elapsed_total:.1f}s  ({elapsed_total/len(jobs)*1000:.1f}ms/variant)")

    # Affichage top
    _print_top_n(results, n=args.top_n)

    # Fichiers
    rows = [_flatten_row(r) for r in results]
    rows.sort(key=lambda r: -r["safe_mult_mean"])
    csv_path = OUTPUT_DIR / f"o15sr_{timestamp}.csv"
    _write_csv(rows, csv_path)
    _write_csv(rows[:50], OUTPUT_DIR / f"o15sr_top50_{timestamp}.csv")
    _save_best(results, OUTPUT_DIR, timestamp)

    print(f"\n[o15sr] ═══════════════════════════════════════════")
    print(f"[o15sr] {len(results):,} variants  ·  CSV : {csv_path}")


if __name__ == "__main__":
    main()
