"""10 runs RANDOM SAFE — max_losses=4"""
from __future__ import annotations
import random, statistics, sys, tempfile
from pathlib import Path

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, _PatchedBuilderIO,
    _enrich_verdict_map_with_results, _parse_verdict_file,
    discover_datasets,
)
from show_sequence import _load_profile_1, _ticket_to_detail

BANKROLL0  = 100.0
MAX_LOSSES = 4
N_RUNS     = 10


def replay_safe_quick(details, label):
    reserves = 0.0
    n_doublings = n_restarts = n_wins = n_losses = 0
    denom = float((2 ** MAX_LOSSES) - 1)

    def cb(): return BANKROLL0 + 0.20 * reserves

    ba = cb(); cycle_base = ba; ls = 0; ps = 0.0
    max_streak = cur_streak = 0

    for td in details:
        if ba <= 0:
            nb = cb()
            if nb <= 0 or reserves <= 0:
                break
            ba = nb; cycle_base = nb; ls = 0; ps = 0.0; n_restarts += 1

        stake = ba / denom if ls == 0 else ps * 2.0
        stake = min(stake, ba)

        if td.is_win:
            ba += stake * (td.total_odd - 1.0)
            n_wins += 1; ls = 0; cur_streak = 0
            if ba >= cycle_base * 2.0:
                reserves += ba - cycle_base
                ba = cb(); cycle_base = ba; ps = 0.0; n_doublings += 1
                continue
        else:
            ba -= stake
            n_losses += 1; ls += 1; cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        ps = stake

    total = ba + reserves
    return {
        "n_tickets": len(details),
        "n_wins": n_wins, "n_losses": n_losses,
        "total": total, "mult": total / BANKROLL0,
        "doublings": n_doublings, "restarts": n_restarts,
        "max_streak": max_streak,
    }


def main():
    print("[run10] Chargement profil #1...")
    tuning = _load_profile_1()

    print("[run10] Chargement datasets...")
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    print(f"[run10] {len(datasets)} jours trouvés")

    print("[run10] Pré-chargement verdict maps...")
    vmap_list = []
    for ds in datasets:
        vm = _parse_verdict_file(ds.verdict_file)
        vm = _enrich_verdict_map_with_results(vm, ds.predictions_tsv)
        vmap_list.append((ds, vm))

    print(f"[run10] Lancement {N_RUNS} runs RANDOM SAFE (max_losses={MAX_LOSSES})...\n")

    results = []
    for run_idx in range(N_RUNS):
        seed = run_idx * 137 + 42
        random.seed(seed)
        rnd_details = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for ds, verdict_map in vmap_list:
                run_dir = tmp_root / ds.day
                with _PatchedBuilderIO(run_dir):
                    out = tb.generate_tickets_from_tsv(
                        str(ds.predictions_tsv), run_date=None, tuning=tuning,
                    )
                for ticket in out.tickets_o15:
                    d = _ticket_to_detail(ticket, "RANDOM", ds.day, verdict_map)
                    if d.is_win is not None:
                        rnd_details.append(d)

        r = replay_safe_quick(rnd_details, f"Run {run_idx+1}")
        r["run"] = run_idx + 1
        results.append(r)
        sys.stdout.write(
            f"  Run {run_idx+1:>2} | {r['n_tickets']:>2} tickets | "
            f"{r['n_wins']}W/{r['n_losses']}L | "
            f"MaxL×{r['max_streak']} | Dbl={r['doublings']} | "
            f"Total={r['total']:>10.2f}€  ×{r['mult']:.2f}\n"
        )
        sys.stdout.flush()

    # Tableau récap
    totals = [r["total"] for r in results]
    mults  = [r["mult"]  for r in results]
    print()
    print("=" * 82)
    print(f"  {'Run':<5} {'Tickets':<8} {'W/L':<9} {'MaxL':<6} {'Dbl':<5} {'Rst':<5} {'Total €':>11}  {'×':>7}")
    print("-" * 82)
    for r in results:
        tag = " ← MIN" if r["total"] == min(totals) else (" ← MAX" if r["total"] == max(totals) else "")
        wl  = f"{r['n_wins']}W/{r['n_losses']}L"
        print(
            f"  {r['run']:<5} {r['n_tickets']:<8} {wl:<9} L×{r['max_streak']:<4} "
            f"{r['doublings']:<5} {r['restarts']:<5} {r['total']:>10.2f}€  ×{r['mult']:<7.2f}{tag}"
        )
    print("=" * 82)
    print(
        f"  Moyenne: ×{statistics.mean(mults):.2f}  |  "
        f"Min: ×{min(mults):.2f}  |  "
        f"Max: ×{max(mults):.2f}  |  "
        f"σ: {statistics.stdev(mults):.2f}"
    )


if __name__ == "__main__":
    main()
