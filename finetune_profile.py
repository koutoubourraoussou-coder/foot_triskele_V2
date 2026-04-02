"""
finetune_profile.py
--------------------
Fine-tuning du profil #1 (champion) — one-at-a-time.

Pour chaque paramètre de la grille, teste toutes ses variantes
en gardant le reste du profil #1 fixe. Classe les variantes et
identifie la meilleure version du champion.

Usage :
    python -u finetune_profile.py
    python -u finetune_profile.py --runs 5 --jobs 6
    python -u finetune_profile.py --param hybrid_alpha --runs 10
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
# GRILLE DE FINE-TUNING
# Chaque entrée : (nom_param, [valeurs à tester])
# Le profil #1 sert de base ; une seule clé change à la fois.
# =========================================================
PARAM_GRID: List[Tuple[str, List[Any]]] = [
    # Sources & modes
    ("league_ranking_mode",       ["CLASSIC", "COMPOSITE"]),
    ("team_ranking_mode",         ["CLASSIC", "COMPOSITE"]),
    ("system_build_source",       ["LEAGUE", "TEAM", "HYBRID"]),
    ("system_select_source",      ["LEAGUE", "TEAM", "HYBRID"]),
    ("random_build_source",       ["LEAGUE", "TEAM", "HYBRID"]),
    ("random_select_source",      ["LEAGUE", "TEAM", "HYBRID"]),
    # Scoring hybride
    ("hybrid_alpha",              [0.2, 0.4, 0.6, 0.8]),
    # Pool & tirage
    ("topk_size",                 [3, 5, 8, 10, 15, 20]),
    ("topk_uniform_draw",         [True, False]),
    # Filtres équipes
    ("team_min_winrate",          [0.65, 0.70, 0.75, 0.80]),
    ("team_min_decided",          [4, 6, 8, 10]),
    ("two_team_high",             [0.75, 0.80, 0.85, 0.90]),
    ("two_team_low",              [0.60, 0.66, 0.70, 0.75]),
    # Filtres ligues
    ("global_bet_min_winrate",    [0.50, 0.55, 0.60, 0.65, 0.70]),
    ("global_bet_min_decided",    [5, 8, 10, 15]),
    ("league_bet_min_winrate",    [0.60, 0.65, 0.70]),
    ("league_bet_require_data",   [True, False]),
    # Cotes & structure
    ("target_odd",                [2.2, 2.4, 2.6, 2.8]),
    ("min_accept_odd",            [1.6, 1.7, 1.8, 1.9]),
    ("prefer_3legs_delta",        [0.0, 0.05, 0.08, 0.12]),
    # Exclusions paris
    ("excluded_bet_groups",       [
        frozenset(),
        frozenset(["HT05"]),
        frozenset(["HT1X_HOME"]),
        frozenset(["HT05", "HT1X_HOME"]),
        frozenset(["TEAM1_WIN_FT", "TEAM2_WIN_FT"]),
        frozenset(["HT05", "TEAM1_WIN_FT", "TEAM2_WIN_FT"]),
    ]),
]


# =========================================================
# CHARGEMENT PROFIL DE BASE — Amélioré #1 (champion actuel)
# Base = profil #1 JSON + 4 améliorations confirmées par Monte Carlo
# =========================================================
# Améliorations confirmées (validées le 2026-04-01, 200 runs)
_AMELIORE_OVERRIDES = {
    "two_team_high":          0.90,   # était 0.80
    "global_bet_min_winrate": 0.65,   # était 0.62
    "league_bet_require_data": False,  # était True
    "league_bet_min_winrate": 0.60,   # était 0.65
}

def _load_profile1() -> BuilderTuning:
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
    return replace(base, **_AMELIORE_OVERRIDES)


# =========================================================
# MARTINGALE
# =========================================================
def _simulate_martingale_normal(
    sequence: List[Tuple[bool, float]],
    bankroll0: float = BANKROLL0,
    max_losses: int  = MAX_LOSSES,
) -> dict:
    bankroll    = bankroll0
    loss_streak = 0
    prev_stake  = 0.0
    n_wins = n_losses = 0
    max_loss_streak = max_win_streak = cur_win_streak = 0
    denom = float((2 ** max_losses) - 1)

    for is_win, odd in sequence:
        if bankroll <= 0:
            break
        base  = bankroll / denom
        stake = base if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll)
        if stake <= 0:
            break
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
        "multiple":       round(bankroll / bankroll0, 3) if bankroll0 > 0 else 0.0,
        "profit":         round(bankroll - bankroll0, 2),
        "n_wins":         n_wins,
        "n_losses":       n_losses,
        "max_loss_streak":max_loss_streak,
        "max_win_streak": max_win_streak,
        "ruined":         bankroll <= 0,
    }


def _simulate_martingale_safe(
    sequence: List[Tuple[bool, float]],
    bankroll0: float = BANKROLL0,
    max_losses: int  = MAX_LOSSES,
) -> dict:
    reserves    = 0.0
    n_doublings = n_restarts = 0
    n_wins = n_losses = 0
    max_loss_streak = max_win_streak = cur_win_streak = 0

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

        if is_win:
            bankroll_active += stake * (odd - 1.0)
            n_wins          += 1
            loss_streak      = 0
            cur_win_streak  += 1
            max_win_streak   = max(max_win_streak, cur_win_streak)
            if bankroll_active >= cycle_base * 2.0:
                reserves       += bankroll_active - cycle_base
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
        "multiple":       round(total / bankroll0, 3) if bankroll0 > 0 else 0.0,
        "profit":         round(total - bankroll0, 2),
        "n_wins":         n_wins,
        "n_losses":       n_losses,
        "max_loss_streak":max_loss_streak,
        "max_win_streak": max_win_streak,
        "n_doublings":    n_doublings,
        "n_restarts":     n_restarts,
        "ruined":         bankroll_active <= 0 and reserves <= 0,
    }


# =========================================================
# AGRÉGATION MONTE CARLO
# =========================================================
def _aggregate_mc(seqs: List[List[Tuple[bool, float]]]) -> dict:
    n = len(seqs)
    normals, safes, win_rates = [], [], []
    loss_streaks, win_streaks, n_tickets_list = [], [], []

    for seq in seqs:
        if not seq:
            win_rates.append(0.0); n_tickets_list.append(0)
            loss_streaks.append(0); win_streaks.append(0)
            normals.append(_simulate_martingale_normal(seq))
            safes.append(_simulate_martingale_safe(seq))
            continue
        wins = sum(1 for w, _ in seq if w)
        win_rates.append(wins / len(seq))
        n_tickets_list.append(len(seq))
        ls = ws = max_ls = max_ws = 0
        for is_win, _ in seq:
            if is_win:
                ws += 1; ls = 0; max_ws = max(max_ws, ws)
            else:
                ls += 1; ws = 0; max_ls = max(max_ls, ls)
        loss_streaks.append(max_ls); win_streaks.append(max_ws)
        normals.append(_simulate_martingale_normal(seq))
        safes.append(_simulate_martingale_safe(seq))

    def _d(vals):
        return {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals),
                "std": statistics.stdev(vals) if n > 1 else 0.0}

    return {
        "n_runs":       n,
        "win_rate":     _d(win_rates),
        "n_tickets":    _d(n_tickets_list),
        "worst_streak": _d(loss_streaks),
        "best_streak":  _d(win_streaks),
        "normale": {
            "multiple":    _d([s["multiple"]        for s in normals]),
            "profit":      _d([s["profit"]           for s in normals]),
            "worst_streak":_d([s["max_loss_streak"]  for s in normals]),
            "ruine_pct":   100 * sum(1 for s in normals if s["ruined"]) / n,
            "ruine_count": sum(1 for s in normals if s["ruined"]),
        },
        "safe": {
            "multiple":    _d([s["multiple"]        for s in safes]),
            "profit":      _d([s["profit"]           for s in safes]),
            "worst_streak":_d([s["max_loss_streak"]  for s in safes]),
            "ruine_pct":   100 * sum(1 for s in safes  if s["ruined"]) / n,
            "ruine_count": sum(1 for s in safes  if s["ruined"]),
            "doublings":   _d([s["n_doublings"]     for s in safes]),
        },
    }


def _score_variant(mc_sys: dict, mc_rnd: dict) -> float:
    """Score composite pour classer les variantes (plus élevé = mieux)."""
    safe_sys = mc_sys["safe"]["multiple"]["mean"]
    safe_rnd = mc_rnd["safe"]["multiple"]["mean"]
    wr_sys   = mc_sys["win_rate"]["mean"]
    wr_rnd   = mc_rnd["win_rate"]["mean"]
    ruine    = (mc_sys["safe"]["ruine_pct"] + mc_rnd["safe"]["ruine_pct"]) / 2
    return 0.4 * safe_sys + 0.4 * safe_rnd + 0.1 * wr_sys + 0.1 * wr_rnd - 0.5 * ruine


def _fmt(d: dict, key: str, dec: int = 2) -> str:
    f = f".{dec}f"
    return f"moy={d[key]['mean']:{f}} min={d[key]['min']:{f}} max={d[key]['max']:{f}} σ={d[key]['std']:{f}}"


def _render_variant(label: str, mc_sys: dict, mc_rnd: dict, is_base: bool) -> List[str]:
    tag = "  ← BASE" if is_base else ""
    lines = [f"    {'▶' if not is_base else '○'} {label}{tag}"]
    for mode, mc in [("SYSTEM", mc_sys), ("RANDOM", mc_rnd)]:
        nm = mc["normale"]
        sm = mc["safe"]
        lines.append(
            f"      [{mode}]"
            f"  WR={mc['win_rate']['mean']:.3f}"
            f"  tickets={mc['n_tickets']['mean']:.0f}"
            f"  pire_série={mc['worst_streak']['max']:.0f}"
        )
        lines.append(
            f"             NORM x{nm['multiple']['mean']:.2f}"
            f"  (min={nm['multiple']['min']:.2f} max={nm['multiple']['max']:.2f})"
            f"  ruine={nm['ruine_pct']:.0f}%"
        )
        lines.append(
            f"             SAFE x{sm['multiple']['mean']:.2f}"
            f"  (min={sm['multiple']['min']:.2f} max={sm['multiple']['max']:.2f})"
            f"  ruine={sm['ruine_pct']:.0f}%"
            f"  doublings_moy={sm['doublings']['mean']:.1f}"
        )
    return lines


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tuning one-at-a-time du profil #1 TRISKÈLE")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--runs",  type=int, default=20,
                        help="Nombre de runs Monte Carlo par variante (défaut=2)")
    parser.add_argument("--jobs",  type=int, default=DEFAULT_JOBS)
    parser.add_argument("--param", type=str, nargs="+", default=None,
                        help="Tester un ou plusieurs paramètres (ex: --param hybrid_alpha topk_size)")
    parser.add_argument("--base-override", type=str, nargs="+", default=None,
                        help="Surcharger des valeurs de base (ex: --base-override league_bet_require_data=False two_team_high=0.9)")
    args = parser.parse_args()

    base_tuning = _load_profile1()

    # Appliquer les surcharges de base si demandé
    if args.base_override:
        overrides = {}
        fields = {f.name: f for f in dataclasses.fields(base_tuning)}
        for item in args.base_override:
            key, _, raw_val = item.partition("=")
            if key not in fields:
                raise ValueError(f"Champ inconnu dans --base-override : {key}")
            ftype = fields[key].type
            # Conversion de type simple
            if raw_val in ("True", "False"):
                val = raw_val == "True"
            else:
                try:
                    val = int(raw_val)
                except ValueError:
                    try:
                        val = float(raw_val)
                    except ValueError:
                        val = raw_val
            overrides[key] = val
        base_tuning = replace(base_tuning, **overrides)
        print(f"[finetune] Surcharges base : {overrides}")
    print(f"[finetune] Amélioré #1 chargé (base = profil #1 + 4 améliorations confirmées)")

    datasets = discover_datasets(args.archive_dir, max_days=None)
    if not datasets:
        raise RuntimeError("Aucun dataset trouvé dans archive/")
    print(f"[finetune] {len(datasets)} jours ({datasets[0].day} → {datasets[-1].day})")

    grid = PARAM_GRID
    if args.param:
        grid = [(p, vals) for p, vals in PARAM_GRID if p in args.param]
        unknown = set(args.param) - {p for p, _ in grid}
        if unknown:
            raise ValueError(f"Paramètres inconnus : {unknown}")

    # Compter total de jobs
    total_variants = sum(len(vals) for _, vals in grid)
    total_jobs     = total_variants * args.runs
    print(f"[finetune] {len(grid)} paramètres | {total_variants} variantes | {args.runs} runs each = {total_jobs} évaluations")
    print(f"[finetune] Martingale B0={BANKROLL0} | max_losses={MAX_LOSSES}")
    print()

    # Construire la liste de tous les (param, valeur, tuning)
    all_tasks: List[Tuple[str, Any, BuilderTuning]] = []
    for param_name, values in grid:
        for val in values:
            variant = replace(base_tuning, **{param_name: val})
            all_tasks.append((param_name, val, variant))

    # Lancer tous les runs
    start = time.time()
    # raw_results[(param_name, val_repr)] = [sys_seq, ...], [rnd_seq, ...]
    raw: Dict[Tuple[str, str], Tuple[List, List]] = {}
    for param_name, val, _ in all_tasks:
        key = (param_name, repr(val))
        raw[key] = ([], [])

    if args.jobs == 1:
        done = 0
        for param_name, val, tuning in all_tasks:
            key = (param_name, repr(val))
            for _ in range(args.runs):
                _, sys_seq, rnd_seq = evaluate_profile_with_sequences(
                    datasets=datasets, tuning=tuning, valid_days=1,
                )
                raw[key][0].append(sys_seq)
                raw[key][1].append(rnd_seq)
                done += 1
                print(f"[finetune] {done}/{total_jobs} | {time.time()-start:.0f}s"
                      f"  {param_name}={val}", flush=True)
    else:
        future_map: Dict = {}
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for param_name, val, tuning in all_tasks:
                key = (param_name, repr(val))
                for _ in range(args.runs):
                    fut = ex.submit(_evaluate_profile_with_seqs_job, (datasets, tuning, False, 1))
                    future_map[fut] = key
            done  = 0
            step  = max(1, total_jobs // 20)
            for fut in as_completed(future_map):
                key = future_map[fut]
                _, sys_seq, rnd_seq = fut.result()
                raw[key][0].append(sys_seq)
                raw[key][1].append(rnd_seq)
                done += 1
                if done % step == 0 or done == total_jobs:
                    elapsed = time.time() - start
                    rate = done / elapsed if elapsed > 0 else 0
                    eta  = (total_jobs - done) / rate if rate > 0 else 0
                    print(f"[finetune] {done}/{total_jobs}"
                          f" | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)

    elapsed = time.time() - start
    print(f"\n[finetune] Terminé en {elapsed/60:.1f}min\n")

    # =====================================================
    # RENDU
    # =====================================================
    lines: List[str] = [
        f"FINE-TUNING PROFIL #1 — one-at-a-time",
        f"Date : {date.today()}  |  {args.runs} runs/variante  |  {len(datasets)} jours",
        f"Martingale : B0={BANKROLL0} | max_losses={MAX_LOSSES}",
        "=" * 70,
        "",
    ]

    summary_winners: List[Tuple[str, Any, float, float]] = []  # (param, winner_val, score, base_score)

    base_fields = dataclasses.asdict(base_tuning)

    for param_name, values in grid:
        base_val    = base_fields.get(param_name)
        base_val_fs = frozenset(base_val) if isinstance(base_val, (list, set, frozenset)) else base_val

        lines.append(f"{'═'*70}")
        lines.append(f"  PARAMÈTRE : {param_name}  (valeur base profil #1 = {base_val})")
        lines.append(f"{'═'*70}")
        lines.append("")

        scored: List[Tuple[Any, float, dict, dict]] = []  # (val, score, mc_sys, mc_rnd)
        for val in values:
            key     = (param_name, repr(val))
            sys_seqs, rnd_seqs = raw[key]
            mc_sys  = _aggregate_mc(sys_seqs)
            mc_rnd  = _aggregate_mc(rnd_seqs)
            score   = _score_variant(mc_sys, mc_rnd)
            scored.append((val, score, mc_sys, mc_rnd))

        scored.sort(key=lambda x: x[1], reverse=True)

        for rank, (val, score, mc_sys, mc_rnd) in enumerate(scored, start=1):
            val_fs   = frozenset(val) if isinstance(val, (list, set, frozenset)) else val
            is_base  = (val_fs == base_val_fs)
            val_repr = f"{val}" if not isinstance(val, frozenset) else "{" + ", ".join(sorted(val)) + "}"
            label    = f"#{rank}  {param_name} = {val_repr}  [score={score:.3f}]"
            lines.extend(_render_variant(label, mc_sys, mc_rnd, is_base))
            lines.append("")

        winner_val, winner_score, _, _ = scored[0]
        base_score = next((s for v, s, _, _ in scored
                           if (frozenset(v) if isinstance(v, (list, set, frozenset)) else v) == base_val_fs), None)
        winner_repr = (f"{winner_val}" if not isinstance(winner_val, frozenset)
                       else "{" + ", ".join(sorted(winner_val)) + "}")
        delta = f"  (+{winner_score - base_score:.3f} vs base)" if base_score is not None else ""
        lines.append(f"  ★ GAGNANT : {param_name} = {winner_repr}{delta}")
        lines.append("")

        summary_winners.append((param_name, winner_val, winner_score,
                                 base_score if base_score is not None else 0.0))

    # =====================================================
    # TABLEAU RÉCAP
    # =====================================================
    lines.append("=" * 70)
    lines.append("  RÉCAPITULATIF — MEILLEURES VALEURS PAR PARAMÈTRE")
    lines.append("=" * 70)
    lines.append("")
    for param_name, winner_val, winner_score, base_score in summary_winners:
        winner_repr = (f"{winner_val}" if not isinstance(winner_val, frozenset)
                       else "{" + ", ".join(sorted(winner_val)) + "}")
        delta = winner_score - base_score
        sign  = "+" if delta >= 0 else ""
        base_fields_val = base_fields.get(param_name)
        changed = "  ← CHANGE" if winner_val != base_fields_val else "  (inchangé)"
        lines.append(
            f"  {param_name:<30}  {winner_repr:<30}  score={winner_score:.3f}  delta={sign}{delta:.3f}{changed}"
        )
    lines.append("")

    output = "\n".join(lines)
    print(output)

    today     = date.today().isoformat()
    out_path  = OUTPUT_DIR / f"finetune_results_{today}_{args.runs}runs.txt"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"\n[finetune] Résultats écrits dans {out_path}")


if __name__ == "__main__":
    main()
