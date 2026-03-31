"""
validate_profiles.py
--------------------
Charge les meilleurs profils all-time (optimizer_top_profiles.json),
les ré-évalue sur l'intégralité des données (60 jours), et affiche :
  - Statistiques flat (win rate, streaks, profit)
  - Simulation martingale NORMALE et SAFE
  - Mode Monte Carlo (--runs N) : distribution sur N tirages aléatoires
    pour SYSTEM et RANDOM (les deux utilisent un rng sans seed fixe)

Usage :
    python -u validate_profiles.py
    python -u validate_profiles.py --runs 200 --jobs 6
    python -u validate_profiles.py --top-n 5 --runs 500 --jobs 8
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_JOBS,
    discover_datasets,
    evaluate_profile_with_sequences,
    _evaluate_profile_with_seqs_job,
    _serialize_tuning,
)
from services.ticket_builder import BuilderTuning

# =========================================================
# CONFIG
# =========================================================
ALL_PROFILES_PATH = Path("data/optimizer/optimizer_top_profiles.json")
OUTPUT_PATH       = Path("data/optimizer/validation_full.txt")

BANKROLL0  = 100.0
MAX_LOSSES = 4


# =========================================================
# MARTINGALE NORMALE
# =========================================================
def _simulate_martingale_normal(
    sequence: List[Tuple[bool, float]],
    bankroll0: float = BANKROLL0,
    max_losses: int = MAX_LOSSES,
) -> dict:
    bankroll    = bankroll0
    loss_streak = 0
    prev_stake  = 0.0
    n_tickets = n_wins = n_losses = 0
    max_loss_streak = max_win_streak = 0
    cur_win_streak  = 0
    denom = float((2 ** max_losses) - 1)

    for is_win, odd in sequence:
        if bankroll <= 0:
            break
        base  = bankroll / denom
        stake = base if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll)
        if stake <= 0:
            break
        n_tickets += 1
        if is_win:
            bankroll       += stake * (odd - 1.0)
            n_wins         += 1
            loss_streak     = 0
            cur_win_streak += 1
            max_win_streak  = max(max_win_streak, cur_win_streak)
        else:
            bankroll       -= stake
            n_losses       += 1
            loss_streak    += 1
            cur_win_streak  = 0
            max_loss_streak = max(max_loss_streak, loss_streak)
        prev_stake = stake

    return {
        "bankroll_final":  round(bankroll, 2),
        "profit":          round(bankroll - bankroll0, 2),
        "multiple":        round(bankroll / bankroll0, 2) if bankroll0 > 0 else 0.0,
        "n_tickets":       n_tickets,
        "n_wins":          n_wins,
        "n_losses":        n_losses,
        "max_loss_streak": max_loss_streak,
        "max_win_streak":  max_win_streak,
        "ruined":          bankroll <= 0,
    }


# =========================================================
# MARTINGALE SAFE
# =========================================================
def _simulate_martingale_safe(
    sequence: List[Tuple[bool, float]],
    bankroll0: float = BANKROLL0,
    max_losses: int = MAX_LOSSES,
) -> dict:
    reserves    = 0.0
    n_doublings = 0
    n_restarts  = 0
    n_tickets = n_wins = n_losses = 0
    max_loss_streak = max_win_streak = 0
    cur_win_streak  = 0

    def _cycle_base() -> float:
        return bankroll0 + 0.20 * reserves

    bankroll_active = _cycle_base()
    cycle_base      = bankroll_active
    loss_streak     = 0
    prev_stake      = 0.0
    denom = float((2 ** max_losses) - 1)

    for is_win, odd in sequence:
        if bankroll_active <= 0:
            new_base = _cycle_base()
            if new_base <= 0 or reserves <= 0:
                break
            bankroll_active = new_base
            cycle_base      = new_base
            loss_streak     = 0
            prev_stake      = 0.0
            n_restarts     += 1

        base  = bankroll_active / denom
        stake = base if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll_active)
        if stake <= 0:
            break
        n_tickets += 1

        if is_win:
            bankroll_active += stake * (odd - 1.0)
            n_wins          += 1
            loss_streak      = 0
            cur_win_streak  += 1
            max_win_streak   = max(max_win_streak, cur_win_streak)
            if bankroll_active >= cycle_base * 2.0:
                profit   = bankroll_active - cycle_base
                reserves += profit
                bankroll_active = _cycle_base()
                cycle_base      = bankroll_active
                prev_stake      = 0.0
                n_doublings    += 1
                continue
        else:
            bankroll_active -= stake
            n_losses        += 1
            loss_streak     += 1
            cur_win_streak   = 0
            max_loss_streak  = max(max_loss_streak, loss_streak)
        prev_stake = stake

    total = bankroll_active + reserves
    return {
        "bankroll_active": round(bankroll_active, 2),
        "reserves":        round(reserves, 2),
        "total":           round(total, 2),
        "profit":          round(total - bankroll0, 2),
        "multiple":        round(total / bankroll0, 2) if bankroll0 > 0 else 0.0,
        "n_tickets":       n_tickets,
        "n_wins":          n_wins,
        "n_losses":        n_losses,
        "max_loss_streak": max_loss_streak,
        "max_win_streak":  max_win_streak,
        "n_doublings":     n_doublings,
        "n_restarts":      n_restarts,
        "ruined":          bankroll_active <= 0 and reserves <= 0,
    }


# =========================================================
# CHARGEMENT PROFILS
# =========================================================
def _load_top_n_all_time(path: Path, top_n: int) -> List[BuilderTuning]:
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_sorted = sorted(raw, key=lambda p: p.get("rank_score", -1e9), reverse=True)
    tunings = []
    for p in raw_sorted[:top_n]:
        t = p.get("tuning", {})
        tunings.append(BuilderTuning(
            global_bet_min_decided=t.get("global_bet_min_decided", 10),
            global_bet_min_winrate=t.get("global_bet_min_winrate", 0.60),
            league_bet_min_winrate=t.get("league_bet_min_winrate", 0.60),
            league_bet_require_data=t.get("league_bet_require_data", True),
            team_min_decided=t.get("team_min_decided", 8),
            team_min_winrate=t.get("team_min_winrate", 0.70),
            two_team_high=t.get("two_team_high", 0.80),
            two_team_low=t.get("two_team_low", 0.60),
            weight_min=t.get("weight_min", 1.0),
            weight_max=t.get("weight_max", 2.0),
            weight_baseline=t.get("weight_baseline", 0.74),
            weight_ceil=t.get("weight_ceil", 1.0),
            topk_size=t.get("topk_size", 5),
            topk_uniform_draw=t.get("topk_uniform_draw", True),
            prefer_3legs_delta=t.get("prefer_3legs_delta", 0.05),
            search_budget_ms_system=t.get("search_budget_ms_system", 500),
            search_budget_ms_random=t.get("search_budget_ms_random", 300),
            excluded_bet_groups=frozenset(t.get("excluded_bet_groups", [])),
            target_odd=t.get("target_odd", 2.3),
            min_accept_odd=t.get("min_accept_odd", 1.7),
            rich_day_match_count=t.get("rich_day_match_count", 18),
            day_max_windows_poor=t.get("day_max_windows_poor", 1),
            day_max_windows_rich=t.get("day_max_windows_rich", 3),
            min_side_matches_for_split=t.get("min_side_matches_for_split", 4),
            split_gap_weight=t.get("split_gap_weight", 0.35),
            league_ranking_mode=t.get("league_ranking_mode", "CLASSIC"),
            team_ranking_mode=t.get("team_ranking_mode", "CLASSIC"),
            system_build_source=t.get("system_build_source", "LEAGUE"),
            system_select_source=t.get("system_select_source", "LEAGUE"),
            hybrid_alpha=t.get("hybrid_alpha", 0.6),
            random_build_source=t.get("random_build_source", "LEAGUE"),
            random_select_source=t.get("random_select_source", "LEAGUE"),
        ))
    return tunings


# =========================================================
# RENDU RUN UNIQUE
# =========================================================
def _render_single(seq: List[Tuple[bool, float]], label: str) -> List[str]:
    if not seq:
        return []
    norm = _simulate_martingale_normal(seq)
    safe = _simulate_martingale_safe(seq)

    def _ruin(s): return " 💀 RUINE" if s["ruined"] else ""

    lines = [
        f"  MART.NORMALE  [{label}]"
        f" | x{norm['multiple']:.2f}"
        f" | profit={norm['profit']:+.2f}"
        f" | {norm['n_wins']}W/{norm['n_losses']}L"
        f" | worst_streak={norm['max_loss_streak']}"
        f" | best_streak={norm['max_win_streak']}"
        + _ruin(norm),

        f"  MART.SAFE     [{label}]"
        f" | x{safe['multiple']:.2f}"
        f" | profit={safe['profit']:+.2f}"
        f" | {safe['n_wins']}W/{safe['n_losses']}L"
        f" | worst_streak={safe['max_loss_streak']}"
        f" | best_streak={safe['max_win_streak']}"
        f" | doublings={safe['n_doublings']}"
        f" | restarts={safe['n_restarts']}"
        + _ruin(safe),
    ]
    return lines


# =========================================================
# MONTE CARLO — agrégation N runs
# =========================================================
def _aggregate_mc(seqs: List[List[Tuple[bool, float]]]) -> dict:
    n = len(seqs)
    normals, safes = [], []
    win_rates, n_tickets_list = [], []
    loss_streaks_per_run, win_streaks_per_run = [], []

    for seq in seqs:
        if not seq:
            win_rates.append(0.0)
            n_tickets_list.append(0)
            loss_streaks_per_run.append(0)
            win_streaks_per_run.append(0)
            normals.append(_simulate_martingale_normal(seq))
            safes.append(_simulate_martingale_safe(seq))
            continue
        wins = sum(1 for w, _ in seq if w)
        win_rates.append(wins / len(seq))
        n_tickets_list.append(len(seq))
        # streaks dans la séquence flat
        loss_s = win_s = 0
        max_ls = max_ws = 0
        for is_win, _ in seq:
            if is_win:
                win_s  += 1; loss_s  = 0
                max_ws  = max(max_ws, win_s)
            else:
                loss_s += 1; win_s   = 0
                max_ls  = max(max_ls, loss_s)
        loss_streaks_per_run.append(max_ls)
        win_streaks_per_run.append(max_ws)
        normals.append(_simulate_martingale_normal(seq))
        safes.append(_simulate_martingale_safe(seq))

    def _d(vals):
        return {
            "mean": statistics.mean(vals),
            "min":  min(vals),
            "max":  max(vals),
            "std":  statistics.stdev(vals) if n > 1 else 0.0,
        }

    return {
        "n_runs":         n,
        "win_rate":       _d(win_rates),
        "n_tickets":      _d(n_tickets_list),
        "worst_streak":   _d(loss_streaks_per_run),   # pire serie défaites par run
        "best_streak":    _d(win_streaks_per_run),    # meilleure serie victoires par run
        "normale": {
            "multiple":       _d([s["multiple"]   for s in normals]),
            "profit":         _d([s["profit"]      for s in normals]),
            "worst_streak":   _d([s["max_loss_streak"] for s in normals]),
            "best_streak":    _d([s["max_win_streak"]  for s in normals]),
            "ruine_pct":      100 * sum(1 for s in normals if s["ruined"]) / n,
            "ruine_count":    sum(1 for s in normals if s["ruined"]),
        },
        "safe": {
            "multiple":       _d([s["multiple"]    for s in safes]),
            "profit":         _d([s["profit"]       for s in safes]),
            "worst_streak":   _d([s["max_loss_streak"] for s in safes]),
            "best_streak":    _d([s["max_win_streak"]  for s in safes]),
            "ruine_pct":      100 * sum(1 for s in safes if s["ruined"]) / n,
            "ruine_count":    sum(1 for s in safes if s["ruined"]),
            "doublings":      _d([s["n_doublings"] for s in safes]),
            "restarts":       _d([s["n_restarts"]  for s in safes]),
        },
    }


def _fmt(d: dict, key: str, decimals: int = 1) -> str:
    fmt = f".{decimals}f"
    return (
        f"moy={d[key]['mean']:{fmt}}"
        f" | min={d[key]['min']:{fmt}}"
        f" | max={d[key]['max']:{fmt}}"
        f" | σ={d[key]['std']:{fmt}}"
    )


def _render_mc(mc: dict, label: str) -> List[str]:
    n  = mc["n_runs"]
    wr = mc["win_rate"]
    ws = mc["worst_streak"]
    bs = mc["best_streak"]
    tk = mc["n_tickets"]
    nm = mc["normale"]
    sm = mc["safe"]

    lines = [
        f"  [{label}] Monte Carlo {n} runs",
        f"    Tickets      : {_fmt(mc, 'n_tickets', 1)}",
        f"    Win rate     : moy={wr['mean']:.3f} | min={wr['min']:.3f} | max={wr['max']:.3f} | σ={wr['std']:.3f}",
        f"    Pire serie L : {_fmt(mc, 'worst_streak', 1)}  ← pire tous runs={int(ws['max'])}",
        f"    Meil. serie W: {_fmt(mc, 'best_streak',  1)}  ← meilleure tous runs={int(bs['max'])}",
        "",
        f"    MART.NORMALE | multiplicateur : {_fmt(nm, 'multiple', 1)}",
        f"                 | profit         : {_fmt(nm, 'profit',   1)}",
        f"                 | pire serie L   : {_fmt(nm, 'worst_streak', 1)}",
        f"                 | meill. serie W : {_fmt(nm, 'best_streak',  1)}",
        f"                 | ruine          : {nm['ruine_pct']:.1f}% ({nm['ruine_count']}/{n})",
        "",
        f"    MART.SAFE    | multiplicateur : {_fmt(sm, 'multiple', 1)}",
        f"                 | profit         : {_fmt(sm, 'profit',   1)}",
        f"                 | pire serie L   : {_fmt(sm, 'worst_streak', 1)}",
        f"                 | meill. serie W : {_fmt(sm, 'best_streak',  1)}",
        f"                 | ruine          : {sm['ruine_pct']:.1f}% ({sm['ruine_count']}/{n})",
        f"                 | doublings      : {_fmt(sm, 'doublings', 1)}",
        f"                 | restarts       : {_fmt(sm, 'restarts',  1)}",
    ]
    return lines


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Validation Monte Carlo des top profils TRISKÈLE")
    parser.add_argument("--archive-dir",  type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--top-n",        type=int,  default=10)
    parser.add_argument("--jobs",         type=int,  default=DEFAULT_JOBS)
    parser.add_argument("--top-profiles", type=Path, default=ALL_PROFILES_PATH)
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Nombre de tirages par profil (1=run unique, >1=Monte Carlo SYSTEM+RANDOM)"
    )
    args = parser.parse_args()

    print(f"[validate] Chargement des {args.top_n} meilleurs profils depuis {args.top_profiles}")
    tunings = _load_top_n_all_time(args.top_profiles, args.top_n)
    tunings.append(BuilderTuning())
    print(f"[validate] {len(tunings)-1} profils optimizer + 1 profil actuel (référence score=193)")

    datasets = discover_datasets(args.archive_dir, max_days=None)
    if not datasets:
        raise RuntimeError("Aucun dataset trouvé dans archive/")

    n_profiles = len(tunings)
    n_runs     = args.runs
    mc_mode    = n_runs > 1
    total_jobs = n_profiles * n_runs

    print(f"[validate] {len(datasets)} jours ({datasets[0].day} → {datasets[-1].day})")
    print(f"[validate] Martingale : B0={BANKROLL0} | max_losses={MAX_LOSSES}")
    if mc_mode:
        print(f"[validate] Monte Carlo : {n_runs} runs × {n_profiles} profils = {total_jobs} évaluations")
    print()

    start_time = time.time()

    # results_raw[pi] = list of (prof, sys_seq, rnd_seq)
    results_raw: dict[int, list] = {pi: [] for pi in range(n_profiles)}

    if args.jobs == 1:
        for pi, tuning in enumerate(tunings):
            for ri in range(n_runs):
                prof, sys_seq, rnd_seq = evaluate_profile_with_sequences(
                    datasets=datasets, tuning=tuning, valid_days=1,
                )
                results_raw[pi].append((prof, sys_seq, rnd_seq))
                done = pi * n_runs + ri + 1
                print(f"[validate] {done}/{total_jobs} | {time.time()-start_time:.0f}s", flush=True)
    else:
        future_map = {}
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for pi, tuning in enumerate(tunings):
                for _ri in range(n_runs):
                    fut = ex.submit(_evaluate_profile_with_seqs_job, (datasets, tuning, False, 1))
                    future_map[fut] = pi
            done = 0
            step = max(1, total_jobs // 20)
            for fut in as_completed(future_map):
                pi = future_map[fut]
                results_raw[pi].append(fut.result())
                done += 1
                if done % step == 0 or done == total_jobs:
                    elapsed = time.time() - start_time
                    rate = done / elapsed if elapsed > 0 else 0
                    eta  = (total_jobs - done) / rate if rate > 0 else 0
                    print(
                        f"[validate] {done}/{total_jobs}"
                        f" | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min",
                        flush=True,
                    )

    # Construction : (prof, [sys_seqs], [rnd_seqs])
    results = []
    for pi in range(n_profiles):
        runs  = results_raw[pi]
        prof0 = runs[0][0]
        sys_seqs = [r[1] for r in runs]
        rnd_seqs = [r[2] for r in runs]
        results.append((prof0, sys_seqs, rnd_seqs))

    results.sort(
        key=lambda r: r[0].combined.get("overall", {}).get("mean_win_rate", 0.0),
        reverse=True,
    )

    current_sig = json.dumps(_serialize_tuning(BuilderTuning()), sort_keys=True)
    mode_label  = f"Monte Carlo {n_runs} runs" if mc_mode else "60 jours"

    lines = [
        f"VALIDATION COMPLÈTE — TOP PROFILS ({mode_label})",
        "=" * 60,
        f"Martingale : B0={BANKROLL0} | max_losses={MAX_LOSSES}",
        "",
    ]

    for i, (prof, sys_seqs, rnd_seqs) in enumerate(results, start=1):
        overall    = prof.combined.get("overall", {})
        t          = prof.tuning
        is_current = json.dumps(_serialize_tuning(t), sort_keys=True) == current_sig
        label      = " ⭐ ACTUEL (score=193)" if is_current else ""

        lines.append(f"#{i} | score_optimizer={prof.rank_score:.4f}{label}")
        lines.append("-" * 60)

        # Stats flat du profil (issues du 1er run, indicatives)
        lines.append(
            f"SYSTEM  | win_rate={prof.system.win_rate:.3f}"
            f" | tickets={prof.system.decided_tickets}"
            f" | tickets/jour={prof.system.avg_tickets_per_active_day:.2f}"
            f" | worst_streak={prof.system.max_loss_streak}"
            f" | best_streak={prof.system.max_win_streak}"
            f" | profit_flat={prof.system.profit_flat:.2f}"
            f" | yield={prof.system.yield_flat:.3f}"
        )
        lines.append(
            f"RANDOM  | win_rate={prof.random_o15.win_rate:.3f}"
            f" | tickets={prof.random_o15.decided_tickets}"
            f" | tickets/jour={prof.random_o15.avg_tickets_per_active_day:.2f}"
            f" | worst_streak={prof.random_o15.max_loss_streak}"
            f" | best_streak={prof.random_o15.max_win_streak}"
            f" | profit_flat={prof.random_o15.profit_flat:.2f}"
            f" | yield={prof.random_o15.yield_flat:.3f}"
        )
        lines.append(
            f"COMBINÉ | win_rate={overall.get('mean_win_rate', 0.0):.3f}"
            f" | worst_streak={overall.get('worst_max_loss_streak', 0)}"
            f" | best_streak={overall.get('best_max_win_streak', 0)}"
            f" | profit_flat={overall.get('mean_profit_flat', 0.0):.2f}"
        )
        lines.append("")

        if mc_mode:
            lines.extend(_render_mc(_aggregate_mc(sys_seqs), "SYSTEM"))
            lines.append("")
            lines.extend(_render_mc(_aggregate_mc(rnd_seqs), "RANDOM"))
        else:
            lines.extend(_render_single(sys_seqs[0], "SYSTEM"))
            lines.extend(_render_single(rnd_seqs[0], "RANDOM"))

        lines.append("")
        lines.append("TUNING")
        lines.append(json.dumps(_serialize_tuning(t), ensure_ascii=False, indent=2))
        lines.append("")

    output = "\n".join(lines)
    print(output)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"\n[validate] Résultats écrits dans {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
