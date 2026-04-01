"""
compare_all_profiles.py
-----------------------
Compare 5 profils en parallèle avec Monte Carlo :
  1. Profil #1   (rank_score=220.47, top optimizer)
  2. Profil #2   (rank_score=216.84)
  3. Profil #3   (rank_score=215.94)
  4. Actuel      (builder_config_2026-03-31_score193.json)
  5. Amélioré #1 (profil #1 + 4 améliorations confirmées)

Usage :
    python -u compare_all_profiles.py --runs 50 --jobs 6
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace, fields
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_JOBS,
    _evaluate_profile_with_seqs_job,
    discover_datasets,
    evaluate_profile_with_sequences,
)
from services.ticket_builder import BuilderTuning

# =========================================================
# CHEMINS
# =========================================================
ALL_PROFILES_PATH  = Path("data/optimizer/optimizer_top_profiles.json")
ACTUEL_CONFIG_PATH = Path("data/optimizer/builder_config_2026-03-31_score193.json")
OUTPUT_DIR         = Path("data/optimizer")

BANKROLL0  = 100.0
MAX_LOSSES = 4

# Améliorations confirmées sur profil #1
IMPROVEMENTS = {
    "two_team_high":          0.90,
    "global_bet_min_winrate": 0.65,
    "league_bet_require_data": False,
    "league_bet_min_winrate": 0.60,
}


# =========================================================
# CHARGEMENT DES PROFILS
# =========================================================
def _tuning_from_dict(t: dict) -> BuilderTuning:
    """Construit un BuilderTuning depuis un dict JSON (clés snake_case)."""
    return BuilderTuning(
        global_bet_min_decided     = t.get("global_bet_min_decided",      10),
        global_bet_min_winrate     = t.get("global_bet_min_winrate",      0.62),
        league_bet_min_winrate     = t.get("league_bet_min_winrate",      0.65),
        league_bet_require_data    = t.get("league_bet_require_data",     True),
        team_min_decided           = t.get("team_min_decided",            6),
        team_min_winrate           = t.get("team_min_winrate",            0.75),
        two_team_high              = t.get("two_team_high",               0.80),
        two_team_low               = t.get("two_team_low",                0.66),
        weight_min                 = t.get("weight_min",                  1.0),
        weight_max                 = t.get("weight_max",                  2.0),
        weight_baseline            = t.get("weight_baseline",             0.74),
        weight_ceil                = t.get("weight_ceil",                 0.95),
        topk_size                  = t.get("topk_size",                   10),
        topk_uniform_draw          = t.get("topk_uniform_draw",           True),
        prefer_3legs_delta         = t.get("prefer_3legs_delta",          0.08),
        search_budget_ms_system    = t.get("search_budget_ms_system",     500),
        search_budget_ms_random    = t.get("search_budget_ms_random",     500),
        excluded_bet_groups        = frozenset(t.get("excluded_bet_groups", [])),
        target_odd                 = t.get("target_odd",                  2.4),
        min_accept_odd             = t.get("min_accept_odd",              1.8),
        rich_day_match_count       = t.get("rich_day_match_count",        18),
        day_max_windows_poor       = t.get("day_max_windows_poor",        1),
        day_max_windows_rich       = t.get("day_max_windows_rich",        4),
        min_side_matches_for_split = t.get("min_side_matches_for_split",  5),
        split_gap_weight           = t.get("split_gap_weight",            0.6),
        league_ranking_mode        = t.get("league_ranking_mode",         "CLASSIC"),
        team_ranking_mode          = t.get("team_ranking_mode",           "COMPOSITE"),
        system_build_source        = t.get("system_build_source",         "LEAGUE"),
        system_select_source       = t.get("system_select_source",        "HYBRID"),
        hybrid_alpha               = t.get("hybrid_alpha",                0.6),
        random_build_source        = t.get("random_build_source",         "TEAM"),
        random_select_source       = t.get("random_select_source",        "TEAM"),
    )


def _load_top3() -> List[Tuple[str, BuilderTuning, float]]:
    raw = json.loads(ALL_PROFILES_PATH.read_text(encoding="utf-8"))
    top3 = sorted(raw, key=lambda p: p.get("rank_score", -1e9), reverse=True)[:3]
    result = []
    for i, p in enumerate(top3, 1):
        t = _tuning_from_dict(p["tuning"])
        result.append((f"Profil #{i}  (rank={p['rank_score']:.2f})", t, p["rank_score"]))
    return result


def _load_actuel() -> Tuple[str, BuilderTuning]:
    raw = json.loads(ACTUEL_CONFIG_PATH.read_text(encoding="utf-8"))
    # Clés en MAJUSCULE → snake_case
    def g(key, default):
        return raw.get(key, raw.get(key.upper(), default))
    t = BuilderTuning(
        global_bet_min_decided     = g("global_bet_min_decided",      12),
        global_bet_min_winrate     = g("GLOBAL_BET_MIN_WINRATE",      0.65),
        league_bet_min_winrate     = g("LEAGUE_BET_MIN_WINRATE",      0.72),
        league_bet_require_data    = g("LEAGUE_BET_REQUIRE_DATA",     True),
        team_min_decided           = g("TEAM_MIN_DECIDED",            8),
        team_min_winrate           = g("TEAM_MIN_WINRATE",            0.70),
        two_team_high              = g("TWO_TEAM_HIGH",               0.85),
        two_team_low               = g("TWO_TEAM_LOW",                0.58),
        weight_min                 = g("WEIGHT_MIN",                  1.0),
        weight_max                 = g("WEIGHT_MAX",                  2.2),
        weight_baseline            = g("WEIGHT_BASELINE",             0.74),
        weight_ceil                = g("WEIGHT_CEIL",                 1.00),
        topk_size                  = 10,   # non sauvegardé dans actuel → valeur par défaut
        topk_uniform_draw          = True,
        prefer_3legs_delta         = 0.08,
        search_budget_ms_system    = 500,
        search_budget_ms_random    = 500,
        excluded_bet_groups        = frozenset(),
        target_odd                 = 2.4,
        min_accept_odd             = 1.8,
        rich_day_match_count       = 18,
        day_max_windows_poor       = 1,
        day_max_windows_rich       = 4,
        min_side_matches_for_split = 5,
        split_gap_weight           = 0.6,
        league_ranking_mode        = g("LEAGUE_RANKING_MODE",         "COMPOSITE"),
        team_ranking_mode          = g("TEAM_RANKING_MODE",           "COMPOSITE"),
        system_build_source        = g("SYSTEM_BUILD_SOURCE",         "LEAGUE"),
        system_select_source       = g("SYSTEM_SELECT_SOURCE",        "LEAGUE"),
        hybrid_alpha               = g("HYBRID_ALPHA",                0.6),
        random_build_source        = g("RANDOM_BUILD_SOURCE",         "LEAGUE"),
        random_select_source       = g("RANDOM_SELECT_SOURCE",        "LEAGUE"),
    )
    return ("Actuel  (score=193)", t)


# =========================================================
# VÉRIFICATION — affiche les paramètres clés d'un profil
# =========================================================
PARAMS_TO_SHOW = [
    "system_select_source", "random_build_source", "random_select_source",
    "system_build_source", "hybrid_alpha",
    "two_team_high", "two_team_low", "global_bet_min_winrate",
    "league_bet_min_winrate", "league_bet_require_data",
    "topk_size", "topk_uniform_draw",
    "team_min_decided", "team_min_winrate",
    "global_bet_min_decided", "league_ranking_mode", "team_ranking_mode",
    "weight_min", "weight_max", "weight_ceil",
    "min_accept_odd", "day_max_windows_rich",
    "min_side_matches_for_split", "split_gap_weight",
    "excluded_bet_groups", "prefer_3legs_delta",
]


def _print_profile_params(name: str, t: BuilderTuning) -> None:
    print(f"  ┌─ {name}")
    td = {f.name: getattr(t, f.name) for f in fields(t)}
    for k in PARAMS_TO_SHOW:
        v = td.get(k, "?")
        if isinstance(v, frozenset):
            v = sorted(v) or "∅"
        print(f"  │  {k:<34} = {v}")
    print(f"  └──")
    print()


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


def _score(mc: dict) -> float:
    """Score composite utilisé pour le classement final."""
    return (mc["safe"]["multiple"]["mean"] * 0.5
            + mc["win_rate"]["mean"] * 0.3
            - mc["safe"]["ruine_pct"] * 0.01)


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
        f"    Pire série L     : moy={ws['mean']:.1f}  max_absolu={int(ws['max'])}",
        f"    Meill. série V   : moy={bs['mean']:.1f}  max_absolu={int(bs['max'])}",
        f"",
        f"    MARTINGALE NORMALE",
        f"      Multiplicateur : {f(nm,'multiple')}",
        f"      Pire série L   : {f(nm,'worst_streak',1)}",
        f"      Ruine          : {nm['ruine_pct']:.0f}%  ({int(round(nm['ruine_pct']*n/100))}/{n} runs)",
        f"",
        f"    MARTINGALE SAFE",
        f"      Multiplicateur : {f(sm,'multiple')}",
        f"      Doublings/run  : moy={sm['doublings']['mean']:.1f}  min={sm['doublings']['min']:.0f}  max={sm['doublings']['max']:.0f}",
        f"      Ruine          : {sm['ruine_pct']:.0f}%  ({int(round(sm['ruine_pct']*n/100))}/{n} runs)",
        f"      Score composite: {_score(mc):.3f}",
    ]


# =========================================================
# MAIN
# =========================================================
def main():
    parser = argparse.ArgumentParser(description="Comparaison de 5 profils — Monte Carlo")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--runs",  type=int, default=50, help="Runs Monte Carlo par profil")
    parser.add_argument("--jobs",  type=int, default=DEFAULT_JOBS)
    args = parser.parse_args()

    # --- Chargement des profils ---
    top3 = _load_top3()
    actuel_name, actuel_tuning = _load_actuel()

    p1_name, p1_tuning, _ = top3[0]
    ameliore_tuning = replace(p1_tuning, **IMPROVEMENTS)
    ameliore_name   = "Amélioré #1  (4 optimisations)"

    profiles: List[Tuple[str, BuilderTuning]] = [
        (top3[0][0], top3[0][1]),
        (top3[1][0], top3[1][1]),
        (top3[2][0], top3[2][1]),
        (actuel_name, actuel_tuning),
        (ameliore_name, ameliore_tuning),
    ]

    # --- Vérification des paramètres ---
    print()
    print("=" * 70)
    print("  VÉRIFICATION DES PARAMÈTRES PAR PROFIL")
    print("=" * 70)
    for name, t in profiles:
        _print_profile_params(name, t)

    # --- Sanity-check : profil #1 et #2 doivent être différents ---
    diff_fields = [f.name for f in fields(p1_tuning) if getattr(p1_tuning, f.name) != getattr(top3[1][1], f.name)]
    print(f"  Différences #1 vs #2 : {diff_fields}")
    diff_fields_ameliore = [f.name for f in fields(p1_tuning) if getattr(p1_tuning, f.name) != getattr(ameliore_tuning, f.name)]
    print(f"  Différences #1 vs Amélioré : {diff_fields_ameliore}")
    print()

    datasets = discover_datasets(args.archive_dir, max_days=None)
    n_profiles = len(profiles)
    total_jobs = n_profiles * args.runs
    print(f"[compare] {len(datasets)} jours  |  {args.runs} runs/profil  |  {n_profiles} profils  |  {total_jobs} jobs total  |  {args.jobs} workers")
    print()

    # --- Monte Carlo parallèle ---
    raw: Dict[int, Tuple[list, list]] = {i: ([], []) for i in range(n_profiles)}
    start = time.time()

    if args.jobs == 1:
        done = 0
        for vi, (vname, tuning) in enumerate(profiles):
            for _ in range(args.runs):
                _, sys_seq, rnd_seq = evaluate_profile_with_sequences(datasets=datasets, tuning=tuning, valid_days=1)
                raw[vi][0].append(sys_seq); raw[vi][1].append(rnd_seq)
                done += 1
                if done % max(1, total_jobs // 20) == 0 or done == total_jobs:
                    elapsed = time.time() - start
                    eta = (total_jobs - done) / (done / elapsed) * 1 if elapsed > 0 else 0
                    print(f"[compare] {done}/{total_jobs} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)
    else:
        future_map = {}
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for vi, (_, tuning) in enumerate(profiles):
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

    # --- Résultats ---
    lines = [
        f"COMPARAISON 5 PROFILS — MONTE CARLO",
        f"Date : {date.today()}  |  {args.runs} runs/profil  |  {len(datasets)} jours",
        f"Améliorations appliquées sur #1 : {IMPROVEMENTS}",
        "=" * 70, "",
    ]

    mcs_by_profile = []
    for vi, (vname, _) in enumerate(profiles):
        sys_seqs, rnd_seqs = raw[vi]
        mc_sys = _aggregate(sys_seqs)
        mc_rnd = _aggregate(rnd_seqs)
        mcs_by_profile.append((vname, mc_sys, mc_rnd))

        lines.append(f"{'─'*70}")
        lines.append(f"  {vname}")
        lines.append(f"{'─'*70}")
        lines.extend(_render(mc_sys, "SYSTEM"))
        lines.append("")
        lines.extend(_render(mc_rnd, "RANDOM"))
        lines.append("")

    # --- Classement ---
    lines.append("=" * 70)
    lines.append("  CLASSEMENT FINAL (score composite SYSTEM + RANDOM)")
    lines.append("  score = SAFE_mult × 0.5 + WR × 0.3 − ruine% × 0.01")
    lines.append("=" * 70)
    lines.append("")

    ranked_sys = sorted(mcs_by_profile, key=lambda x: _score(x[1]), reverse=True)
    ranked_rnd = sorted(mcs_by_profile, key=lambda x: _score(x[2]), reverse=True)

    lines.append("  CLASSEMENT SYSTEM :")
    for rank, (vname, mc_sys, _) in enumerate(ranked_sys, 1):
        sc = _score(mc_sys)
        wr = mc_sys["win_rate"]["mean"]
        mult = mc_sys["safe"]["multiple"]["mean"]
        ruine = mc_sys["safe"]["ruine_pct"]
        medal = "★" if rank == 1 else f"{rank}."
        lines.append(f"  {medal:2s} {vname:<45}  score={sc:.3f}  WR={wr:.3f}  SAFE×{mult:.2f}  ruine={ruine:.0f}%")
    lines.append("")

    lines.append("  CLASSEMENT RANDOM :")
    for rank, (vname, _, mc_rnd) in enumerate(ranked_rnd, 1):
        sc = _score(mc_rnd)
        wr = mc_rnd["win_rate"]["mean"]
        mult = mc_rnd["safe"]["multiple"]["mean"]
        ruine = mc_rnd["safe"]["ruine_pct"]
        medal = "★" if rank == 1 else f"{rank}."
        lines.append(f"  {medal:2s} {vname:<45}  score={sc:.3f}  WR={wr:.3f}  SAFE×{mult:.2f}  ruine={ruine:.0f}%")
    lines.append("")

    # Classement combiné
    combined_scores = {
        vname: (_score(mc_sys) + _score(mc_rnd)) / 2
        for vname, mc_sys, mc_rnd in mcs_by_profile
    }
    ranked_combined = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
    lines.append("  CLASSEMENT COMBINÉ (moyenne SYSTEM + RANDOM) :")
    for rank, (vname, sc) in enumerate(ranked_combined, 1):
        medal = "★" if rank == 1 else f"{rank}."
        lines.append(f"  {medal:2s} {vname:<45}  score_moy={sc:.3f}")
    lines.append("")

    output = "\n".join(lines)
    print(output)

    out_path = OUTPUT_DIR / f"compare_all_profiles_{date.today()}_{args.runs}runs.txt"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"\n[compare] Résultats écrits dans {out_path}")


if __name__ == "__main__":
    main()
