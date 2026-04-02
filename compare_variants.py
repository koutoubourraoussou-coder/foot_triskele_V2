"""
compare_variants.py
--------------------
Compare N variantes d'un profil en parallèle avec Monte Carlo.

Usage :
    python -u compare_variants.py --runs 100 --jobs 6
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import List

from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_JOBS,
    _evaluate_profile_with_seqs_job,
    discover_datasets,
    evaluate_profile_with_sequences,
)
from services.ticket_builder import BuilderTuning

# =========================================================
# CONFIG
# =========================================================
ALL_PROFILES_PATH = Path("data/optimizer/optimizer_top_profiles.json")
OUTPUT_DIR        = Path("data/optimizer")

BANKROLL0  = 100.0
MAX_LOSSES = 4

# =========================================================
# CHARGEMENT BASE — Amélioré #1
# =========================================================
def _load_ameliore1() -> BuilderTuning:
    raw = json.loads(ALL_PROFILES_PATH.read_text(encoding="utf-8"))
    t   = sorted(raw, key=lambda p: p.get("rank_score", -1e9), reverse=True)[0]["tuning"]
    base = BuilderTuning(
        global_bet_min_decided    = t.get("global_bet_min_decided",     10),
        global_bet_min_winrate    = t.get("global_bet_min_winrate",     0.62),
        league_bet_min_winrate    = t.get("league_bet_min_winrate",     0.65),
        league_bet_require_data   = t.get("league_bet_require_data",    True),
        team_min_decided          = t.get("team_min_decided",           6),
        team_min_winrate          = t.get("team_min_winrate",           0.75),
        two_team_high             = t.get("two_team_high",              0.80),
        two_team_low              = t.get("two_team_low",               0.66),
        weight_min                = t.get("weight_min",                 1.0),
        weight_max                = t.get("weight_max",                 2.0),
        weight_baseline           = t.get("weight_baseline",            0.74),
        weight_ceil               = t.get("weight_ceil",                0.95),
        topk_size                 = t.get("topk_size",                  10),
        topk_uniform_draw         = t.get("topk_uniform_draw",          True),
        prefer_3legs_delta        = t.get("prefer_3legs_delta",         0.08),
        search_budget_ms_system   = t.get("search_budget_ms_system",    500),
        search_budget_ms_random   = t.get("search_budget_ms_random",    500),
        excluded_bet_groups       = frozenset(t.get("excluded_bet_groups", [])),
        target_odd                = t.get("target_odd",                 2.4),
        min_accept_odd            = t.get("min_accept_odd",             1.8),
        rich_day_match_count      = t.get("rich_day_match_count",       18),
        day_max_windows_poor      = t.get("day_max_windows_poor",       1),
        day_max_windows_rich      = t.get("day_max_windows_rich",       4),
        min_side_matches_for_split= t.get("min_side_matches_for_split", 5),
        split_gap_weight          = t.get("split_gap_weight",           0.6),
        league_ranking_mode       = t.get("league_ranking_mode",        "CLASSIC"),
        team_ranking_mode         = t.get("team_ranking_mode",          "COMPOSITE"),
        system_build_source       = t.get("system_build_source",        "LEAGUE"),
        system_select_source      = t.get("system_select_source",       "HYBRID"),
        hybrid_alpha              = t.get("hybrid_alpha",               0.6),
        random_build_source       = t.get("random_build_source",        "TEAM"),
        random_select_source      = t.get("random_select_source",       "TEAM"),
    )
    # Améliorations confirmées
    return replace(base,
        two_team_high          = 0.90,
        global_bet_min_winrate = 0.65,
        league_bet_require_data= False,
        league_bet_min_winrate = 0.60,
    )


# =========================================================
# DÉFINITION DES VARIANTES
# =========================================================
def _build_variants(base: BuilderTuning):
    return [
        ("Amélioré #1  (LEAGUE build SYSTEM)",
         base),
        ("TEAM build SYSTEM",
         replace(base, system_build_source="TEAM")),
    ]


# =========================================================
# MARTINGALE
# =========================================================
def _simulate_martingale_normal(sequence, bankroll0=BANKROLL0, max_losses=MAX_LOSSES):
    bankroll = bankroll0; loss_streak = 0; prev_stake = 0.0
    n_wins = n_losses = 0; max_ls = max_ws = cur_ws = 0
    denom = float((2 ** max_losses) - 1)
    for is_win, odd in sequence:
        if bankroll <= 0: break
        stake = (bankroll / denom) if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll)
        if stake <= 0: break
        if is_win:
            bankroll += stake * (odd - 1.0); n_wins += 1
            loss_streak = 0; cur_ws += 1; max_ws = max(max_ws, cur_ws)
        else:
            bankroll -= stake; n_losses += 1
            loss_streak += 1; cur_ws = 0; max_ls = max(max_ls, loss_streak)
        prev_stake = stake
    return {"multiple": round(bankroll/bankroll0, 3), "profit": round(bankroll-bankroll0, 2),
            "n_wins": n_wins, "n_losses": n_losses, "max_loss_streak": max_ls,
            "max_win_streak": max_ws, "ruined": bankroll <= 0}


def _simulate_martingale_safe(sequence, bankroll0=BANKROLL0, max_losses=MAX_LOSSES):
    reserves = 0.0; n_doublings = n_restarts = 0
    n_wins = n_losses = 0; max_ls = max_ws = cur_ws = 0
    def _cb(): return bankroll0 + 0.20 * reserves
    ba = _cb(); cb = ba; loss_streak = 0; prev_stake = 0.0
    denom = float((2 ** max_losses) - 1)
    for is_win, odd in sequence:
        if ba <= 0:
            nb = _cb()
            if nb <= 0 or reserves <= 0: break
            ba = nb; cb = nb; loss_streak = 0; prev_stake = 0.0; n_restarts += 1
        stake = (ba / denom) if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, ba)
        if stake <= 0: break
        if is_win:
            ba += stake * (odd - 1.0); n_wins += 1
            loss_streak = 0; cur_ws += 1; max_ws = max(max_ws, cur_ws)
            if ba >= cb * 2.0:
                reserves += ba - cb; ba = _cb(); cb = ba; prev_stake = 0.0; n_doublings += 1; continue
        else:
            ba -= stake; n_losses += 1; loss_streak += 1; cur_ws = 0; max_ls = max(max_ls, loss_streak)
        prev_stake = stake
    total = ba + reserves
    return {"multiple": round(total/bankroll0, 3), "profit": round(total-bankroll0, 2),
            "n_wins": n_wins, "n_losses": n_losses, "max_loss_streak": max_ls,
            "max_win_streak": max_ws, "n_doublings": n_doublings, "n_restarts": n_restarts,
            "ruined": ba <= 0 and reserves <= 0}


def _aggregate(seqs):
    n = len(seqs)
    normals, safes, win_rates, loss_streaks, win_streaks, n_tickets_list = [], [], [], [], [], []
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

    def _d(v): return {"mean": statistics.mean(v), "min": min(v), "max": max(v),
                       "std": statistics.stdev(v) if n > 1 else 0.0}
    return {
        "n_runs": n,
        "win_rate":     _d(win_rates),
        "n_tickets":    _d(n_tickets_list),
        "worst_streak": _d(loss_streaks),
        "best_streak":  _d(win_streaks),
        "normale": {
            "multiple":    _d([s["multiple"]       for s in normals]),
            "profit":      _d([s["profit"]          for s in normals]),
            "worst_streak":_d([s["max_loss_streak"] for s in normals]),
            "ruine_pct":   100 * sum(1 for s in normals if s["ruined"]) / n,
        },
        "safe": {
            "multiple":    _d([s["multiple"]       for s in safes]),
            "profit":      _d([s["profit"]          for s in safes]),
            "worst_streak":_d([s["max_loss_streak"] for s in safes]),
            "ruine_pct":   100 * sum(1 for s in safes if s["ruined"]) / n,
            "doublings":   _d([s["n_doublings"]    for s in safes]),
        },
    }


def _score(mc):
    return mc["safe"]["multiple"]["mean"] * 0.5 + mc["win_rate"]["mean"] * 0.3 - mc["safe"]["ruine_pct"] * 0.01


def _render(mc: dict, label: str) -> List[str]:
    n  = mc["n_runs"]
    wr = mc["win_rate"]
    nm = mc["normale"]
    sm = mc["safe"]
    ws = mc["worst_streak"]
    bs = mc["best_streak"]
    tk = mc["n_tickets"]

    def f(d, k, dec=2): return f"moy={d[k]['mean']:.{dec}f}  min={d[k]['min']:.{dec}f}  max={d[k]['max']:.{dec}f}  σ={d[k]['std']:.{dec}f}"

    return [
        f"  [{label}]  {n} runs",
        f"    Tickets/run      : moy={tk['mean']:.1f}  min={tk['min']:.0f}  max={tk['max']:.0f}",
        f"    Win rate         : moy={wr['mean']:.3f}  min={wr['min']:.3f}  max={wr['max']:.3f}  σ={wr['std']:.3f}",
        f"    Pire série L     : moy={ws['mean']:.1f}  max_absolu={int(ws['max'])}  (pire run jamais vu)",
        f"    Meill. série V   : moy={bs['mean']:.1f}  max_absolu={int(bs['max'])}  (meilleur run jamais vu)",
        f"",
        f"    MARTINGALE NORMALE",
        f"      Multiplicateur : {f(nm,'multiple')}",
        f"      Profit (€)     : {f(nm,'profit')}",
        f"      Pire série L   : {f(nm,'worst_streak',1)}",
        f"      Ruine          : {nm['ruine_pct']:.0f}%  ({int(nm['ruine_pct']*n/100)}/{n} runs)",
        f"",
        f"    MARTINGALE SAFE",
        f"      Multiplicateur : {f(sm,'multiple')}",
        f"      Profit (€)     : {f(sm,'profit')}",
        f"      Pire série L   : {f(sm,'worst_streak',1)}",
        f"      Doublings/run  : moy={sm['doublings']['mean']:.1f}  min={sm['doublings']['min']:.0f}  max={sm['doublings']['max']:.0f}",
        f"      Ruine          : {sm['ruine_pct']:.0f}%  ({int(sm['ruine_pct']*n/100)}/{n} runs)",
    ]


def _verdict_ranking(mcs_indexed, mode_label) -> List[str]:
    ranked = sorted(mcs_indexed, key=lambda x: _score(x[1]), reverse=True)
    lines = [f"  VERDICT {mode_label}"]
    for rank, (name, mc) in enumerate(ranked, 1):
        s = _score(mc)
        marker = "★" if rank == 1 else f"#{rank}"
        lines.append(f"  {marker} {name}  (score={s:.3f})")
    return lines


# =========================================================
# MAIN
# =========================================================
def main():
    parser = argparse.ArgumentParser(description="Comparaison random_build/select_source : 3 variantes")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--runs",  type=int, default=100)
    parser.add_argument("--jobs",  type=int, default=DEFAULT_JOBS)
    args = parser.parse_args()

    base     = _load_ameliore1()
    variants = _build_variants(base)

    print(f"[compare] system_build_source : LEAGUE vs TEAM")
    for name, _ in variants:
        print(f"  · {name}")

    datasets = discover_datasets(args.archive_dir, max_days=None)
    print(f"[compare] {len(datasets)} jours  |  {args.runs} runs/variante  |  {args.jobs} jobs")
    print()

    total_jobs = len(variants) * args.runs
    raw = {i: ([], []) for i in range(len(variants))}

    start = time.time()
    if args.jobs == 1:
        done = 0
        for vi, (vname, tuning) in enumerate(variants):
            for _ in range(args.runs):
                _, sys_seq, rnd_seq = evaluate_profile_with_sequences(datasets=datasets, tuning=tuning, valid_days=1)
                raw[vi][0].append(sys_seq); raw[vi][1].append(rnd_seq)
                done += 1
                print(f"[compare] {done}/{total_jobs} | {time.time()-start:.0f}s  {vname[:30]}", flush=True)
    else:
        future_map = {}
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for vi, (_, tuning) in enumerate(variants):
                for _ in range(args.runs):
                    fut = ex.submit(_evaluate_profile_with_seqs_job, (datasets, tuning, False, 1))
                    future_map[fut] = vi
            done = 0; step = max(1, total_jobs // 20)
            for fut in as_completed(future_map):
                vi = future_map[fut]
                _, sys_seq, rnd_seq = fut.result()
                raw[vi][0].append(sys_seq); raw[vi][1].append(rnd_seq)
                done += 1
                if done % step == 0 or done == total_jobs:
                    elapsed = time.time() - start
                    eta = (total_jobs - done) / (done / elapsed) if elapsed > 0 else 0
                    print(f"[compare] {done}/{total_jobs} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)

    print(f"\n[compare] Terminé en {(time.time()-start)/60:.1f}min\n")

    lines = [
        f"COMPARAISON RANDOM BUILD/SELECT SOURCE",
        f"Date : {date.today()}  |  {args.runs} runs/variante  |  {len(datasets)} jours",
        f"Base : Amélioré #1  |  3 variantes RANDOM testées",
        "=" * 70, "",
    ]

    mcs_sys = []
    mcs_rnd = []

    for vi, (vname, _) in enumerate(variants):
        sys_seqs, rnd_seqs = raw[vi]
        mc_sys = _aggregate(sys_seqs)
        mc_rnd = _aggregate(rnd_seqs)
        mcs_sys.append((vname, mc_sys))
        mcs_rnd.append((vname, mc_rnd))

        lines.append(f"{'─'*70}")
        lines.append(f"  {vname}")
        lines.append(f"{'─'*70}")
        lines.extend(_render(mc_sys, "SYSTEM"))
        lines.append("")
        lines.extend(_render(mc_rnd, "RANDOM"))
        lines.append("")

    lines.append("=" * 70)
    lines.extend(_verdict_ranking(mcs_sys, "SYSTEM"))
    lines.append("")
    lines.extend(_verdict_ranking(mcs_rnd, "RANDOM"))
    lines.append("")

    output = "\n".join(lines)
    print(output)

    out_path = OUTPUT_DIR / f"compare_system_build_{date.today()}_{args.runs}runs.txt"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"\n[compare] Résultats écrits dans {out_path}")


if __name__ == "__main__":
    main()
