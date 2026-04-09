"""
compare_portfolio.py
---------------------
Compare 5 configurations de portfolio sur les mêmes séquences (même seed).
Les séquences SYSTEM/RANDOM sont générées une seule fois par seed — le portfolio
est juste la couche financière par-dessus.

Configurations testées :
  Baseline : RS(ML=3) + RN(ML=4) + SS(ML=4) + SN(ML=4) — 4×100€ + 600€ réserves
  A        : RANDOM ONLY — RS(ML=3) + RN(ML=4)         — 2×100€ + 600€ réserves
  B        : Start-delay — RS→1d→SS→1d→RN/SN           — 4×100€ + 600€ réserves
  C        : ML SYSTEM=5 — RS(3)+RN(4)+SS(5)+SN(5)     — 4×100€ + 600€ réserves
  D        : SAFE first  — RS→2d→SS→2d→RN/SN           — 4×100€ + 600€ réserves

Critère principal : P25 (1er quartile) + min absolu — survie avant profit.
"""
from __future__ import annotations

import random
import statistics
import sys
import tempfile
from pathlib import Path

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, _PatchedBuilderIO,
    _enrich_verdict_map_with_results, _parse_verdict_file,
    discover_datasets,
)
from show_sequence import _load_profile_1, _ticket_to_detail
from run_portfolio import (
    Strategy, SharedReserves, _emergency_reset_if_needed, BANKROLL0, PRIORITY,
)

N_RUNS        = 100
RESERVES_INIT = 600.0


# ─── Simulation d'un portfolio avec config personnalisée ──────────────────────

def _sim(sys_details, rnd_details, ml: dict, strategies_factory):
    """
    ml               : dict {name: max_losses}
    strategies_factory : fonction(shared) -> (rs, rn, ss, sn) ou (rs, rn, None, None)
    """
    shared = SharedReserves(RESERVES_INIT)
    rs, rn, ss, sn = strategies_factory(shared, ml)
    active_strats = [s for s in (rs, rn, ss, sn) if s is not None]

    max_len = max(len(sys_details), len(rnd_details))
    for i in range(max_len):
        sys_td = sys_details[i] if i < len(sys_details) else None
        rnd_td = rnd_details[i] if i < len(rnd_details) else None

        _emergency_reset_if_needed(active_strats, rnd_td, sys_td, shared)

        turn_pairs = sorted(
            [(s, sys_td if s.name.startswith("SYSTEM") else rnd_td)
             for s in active_strats],
            key=lambda x: x[0].priority
        )
        for strat, td in turn_pairs:
            if td:
                strat.step(td)

    n_active = sum(1 for s in (rs, rn, ss, sn) if s is not None)
    invested  = n_active * BANKROLL0 + RESERVES_INIT
    total_active = sum(s.total() for s in active_strats)
    grand_total  = total_active + shared.amount
    return grand_total / invested


# ─── Factories par config ─────────────────────────────────────────────────────

def _factory_baseline(shared, ml):
    rs = Strategy("RANDOM SAFE",    "SAFE",    shared)
    rn = Strategy("RANDOM NORMALE", "NORMALE", shared)
    ss = Strategy("SYSTEM SAFE",    "SAFE",    shared)
    sn = Strategy("SYSTEM NORMALE", "NORMALE", shared)
    for s in (rs, rn, ss, sn):
        s.max_losses = ml[s.name]
        s.denom      = float((2 ** s.max_losses) - 1)
    return rs, rn, ss, sn


def _factory_random_only(shared, ml):
    rs = Strategy("RANDOM SAFE",    "SAFE",    shared)
    rn = Strategy("RANDOM NORMALE", "NORMALE", shared)
    for s in (rs, rn):
        s.max_losses = ml[s.name]
        s.denom      = float((2 ** s.max_losses) - 1)
    return rs, rn, None, None


def _factory_start_delay(shared, ml, rs_target=1, ss_target=1):
    rs = Strategy("RANDOM SAFE",    "SAFE",    shared, start_pivot=None)
    ss = Strategy("SYSTEM SAFE",    "SAFE",    shared, start_pivot=rs, start_after_doublings=rs_target)
    rn = Strategy("RANDOM NORMALE", "NORMALE", shared, start_pivot=ss, start_after_doublings=ss_target)
    sn = Strategy("SYSTEM NORMALE", "NORMALE", shared, start_pivot=ss, start_after_doublings=ss_target)
    for s in (rs, rn, ss, sn):
        s.max_losses = ml[s.name]
        s.denom      = float((2 ** s.max_losses) - 1)
    return rs, rn, ss, sn


def _factory_b(shared, ml):
    return _factory_start_delay(shared, ml, rs_target=1, ss_target=1)


def _factory_d(shared, ml):
    return _factory_start_delay(shared, ml, rs_target=2, ss_target=2)


# ─── Configs ─────────────────────────────────────────────────────────────────

ML_BASE = {"RANDOM SAFE": 3, "RANDOM NORMALE": 4, "SYSTEM SAFE": 4, "SYSTEM NORMALE": 4}
ML_C    = {"RANDOM SAFE": 3, "RANDOM NORMALE": 4, "SYSTEM SAFE": 5, "SYSTEM NORMALE": 5}

CONFIGS = [
    ("Baseline (RS+RN+SS+SN, ML std)",         ML_BASE, _factory_baseline),
    ("A — RANDOM ONLY (RS+RN, pas de SYSTEM)", ML_BASE, _factory_random_only),
    ("B — Start-delay RS→1d→SS→1d→RN/SN",     ML_BASE, _factory_b),
    ("C — ML SYSTEM=5 (résiste aux séries 6)", ML_C,    _factory_baseline),
    ("D — SAFE first RS→2d→SS→2d→RN/SN",      ML_BASE, _factory_d),
]


# ─── Affichage ────────────────────────────────────────────────────────────────

def _pct(vals, p):
    """Percentile p (0-100) sans dépendance externe."""
    s = sorted(vals)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (idx - lo) * (s[hi] - s[lo])


def _render_config(name, mults):
    n = len(mults)
    mean = statistics.mean(mults)
    p10  = _pct(mults, 10)
    p25  = _pct(mults, 25)
    p75  = _pct(mults, 75)
    mn   = min(mults)
    mx   = max(mults)
    std  = statistics.stdev(mults)
    lines = [
        f"  {name}",
        f"    N={n} | Moy=×{mean:.2f} | σ=×{std:.2f}",
        f"    ★ P10=×{p10:.2f} | P25=×{p25:.2f} | P75=×{p75:.2f}",
        f"    Min=×{mn:.2f} | Max=×{mx:.2f}",
        "",
    ]
    return lines, p25


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("[portfolio-cmp] Chargement profil #1...")
    tuning = _load_profile_1()

    print("[portfolio-cmp] Chargement datasets...")
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    print(f"[portfolio-cmp] {len(datasets)} jours | {N_RUNS} runs | {len(CONFIGS)} configs\n")

    print("[portfolio-cmp] Pré-chargement verdict maps...")
    vmap_list = []
    for ds in datasets:
        vm = _parse_verdict_file(ds.verdict_file)
        vm = _enrich_verdict_map_with_results(vm, ds.predictions_tsv)
        vmap_list.append((ds, vm))

    # ── Génération des séquences (une fois par seed) ──────────────────────────
    print("[portfolio-cmp] Génération des séquences...\n")
    all_sequences = []
    for run_idx in range(N_RUNS):
        seed = run_idx * 137 + 42
        random.seed(seed)
        sys_details, rnd_details = [], []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for ds, verdict_map in vmap_list:
                run_dir = tmp_root / ds.day
                with _PatchedBuilderIO(run_dir):
                    out = tb.generate_tickets_from_tsv(
                        str(ds.predictions_tsv), run_date=None, tuning=tuning,
                    )
                for t in out.tickets_system:
                    d = _ticket_to_detail(t, "SYSTEM", ds.day, verdict_map)
                    if d.is_win is not None:
                        sys_details.append(d)
                for t in out.tickets_o15:
                    d = _ticket_to_detail(t, "RANDOM", ds.day, verdict_map)
                    if d.is_win is not None:
                        rnd_details.append(d)
        all_sequences.append((sys_details, rnd_details))
        if (run_idx + 1) % 10 == 0 or run_idx == 0:
            print(f"  [{run_idx+1}/{N_RUNS}] séquences générées", flush=True)

    # ── Simulation de chaque config sur les mêmes séquences ───────────────────
    print()
    results = {name: [] for name, _, _ in CONFIGS}
    for run_idx, (sys_det, rnd_det) in enumerate(all_sequences):
        for name, ml, factory in CONFIGS:
            mult = _sim(sys_det, rnd_det, ml, factory)
            results[name].append(mult)
        if (run_idx + 1) % 10 == 0 or run_idx == 0:
            print(f"  [{run_idx+1}/{N_RUNS}] simulations", flush=True)

    # ── Rapport ───────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  COMPARAISON PORTFOLIO — BCEA Session 10 — 2026-04-05")
    print(f"  {N_RUNS} runs | {len(datasets)} jours | Critère principal : P25")
    print("=" * 70)
    print()

    ranked = []
    for name, _, _ in CONFIGS:
        lines, p25 = _render_config(name, results[name])
        for l in lines:
            print(l)
        ranked.append((name, p25))

    print("=" * 70)
    print("  CLASSEMENT PAR P25 :")
    for rank, (name, p25) in enumerate(sorted(ranked, key=lambda x: -x[1]), 1):
        marker = "★" if rank == 1 else f"#{rank}"
        print(f"  {marker} {name}  (P25=×{p25:.2f})")
    print()

    out_path = Path("data/optimizer/compare_portfolio_2026-04-05.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Sauvegarde simple
    lines_out = []
    for name, _, _ in CONFIGS:
        ls, _ = _render_config(name, results[name])
        lines_out.extend(ls)
    out_path.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"[portfolio-cmp] Résultats écrits dans {out_path}")


if __name__ == "__main__":
    main()
