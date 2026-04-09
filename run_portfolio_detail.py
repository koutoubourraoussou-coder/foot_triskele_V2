"""
Portfolio 4 stratégies — suivi détaillé ticket par ticket
RUN_IDX : numéro du run à afficher (0=Run1, 1=Run2, ...)
Flags : --find-worst  → trouve le pire run sur N_SEARCH seeds puis l'affiche
        --run N       → affiche le run N (1-based)
"""
from __future__ import annotations
import random, sys, tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, _PatchedBuilderIO,
    _enrich_verdict_map_with_results, _parse_verdict_file,
    discover_datasets,
)
from show_sequence import _load_profile_1, _ticket_to_detail

BANKROLL0     = 100.0
RESERVES_INIT = 6514.0
N_SEARCH      = 100   # nombre de seeds à tester pour --find-worst
ML = {
    "RANDOM SAFE":    3,
    "RANDOM NORMALE": 4,
    "SYSTEM SAFE":    4,
    "SYSTEM NORMALE": 4,
}
PRIORITY = {
    "SYSTEM SAFE":     1,   # organe vital #1 — alimente les réserves + ML=4
    "SYSTEM NORMALE":  2,   # organe vital #2 — plus gros multiplicateur
    "RANDOM NORMALE":  3,   # ML=4
    "RANDOM SAFE":     4,   # ML=3 → mise plus petite → dernier
}
RUN_IDX = 0   # Run 1 (écrasé par --run ou --find-worst)


class SharedReserves:
    def __init__(self, init):
        self.amount = init
    def cycle_base(self):
        return BANKROLL0 + 0.20 * self.amount
    def add(self, p):
        self.amount += p
    def can_draw(self, need):
        return self.amount > 0 and need <= self.amount
    def draw(self, need):
        d = min(need, self.amount)
        self.amount -= d
        return d


class Strategy:
    def __init__(self, name, mode, shared):
        self.name = name; self.mode = mode; self.shared = shared
        self.priority = PRIORITY[name]
        self.ml   = ML[name]
        self.den  = float((2 ** self.ml) - 1)
        self.ba   = BANKROLL0; self.cb = BANKROLL0
        self.ls   = 0; self.ps = 0.0
        self.ruined = False
        self.paused = False; self.pending_bet = 0.0
        self.n_doublings = self.n_restarts = self.n_pauses = 0

    def step(self, td):
        """Joue un ticket. Retourne un dict avec les infos pour l'affichage."""
        if self.ruined:
            return {"stake": 0, "result": "—", "odd": 0, "ba": 0, "note": "RUINÉ"}

        note = ""

        # ── Reprise après pause ──
        if self.paused:
            if self.shared.can_draw(self.pending_bet):
                drawn = self.shared.draw(self.pending_bet)
                self.ba = drawn
                self.paused = False
                self.n_restarts += 1
                note = f"🏦RST#{self.n_restarts}({drawn:.0f}€)"
            else:
                self.n_pauses += 1
                return {"stake": 0, "result": "⏸", "odd": 0, "ba": self.ba, "note": f"⏸PAUSE({self.pending_bet:.0f}€)"}

        # ── Banque de secours ──
        if self.ba <= 0:
            next_bet = self.ps * 2.0 if self.ps > 0 else self.ba / self.den
            if self.shared.can_draw(next_bet):
                drawn = self.shared.draw(next_bet)
                self.ba = drawn
                self.n_restarts += 1
                note = f"🏦RST#{self.n_restarts}({drawn:.0f}€)"
            else:
                # Réserves insuffisantes → pause (pas de ruine)
                self.paused = True
                self.pending_bet = next_bet
                self.n_pauses += 1
                return {"stake": 0, "result": "⏸", "odd": 0, "ba": 0, "note": f"⏸PAUSE({next_bet:.0f}€)"}

        stake  = self.ba / self.den if self.ls == 0 else self.ps * 2.0
        stake  = min(stake, self.ba)
        result = "WIN" if td.is_win else "LOSS"

        if td.is_win:
            self.ba += stake * (td.total_odd - 1.0)
            self.ls = 0
            if self.mode == "SAFE" and self.ba >= self.cb * 2.0:
                profit = self.ba - self.cb
                self.shared.add(profit)
                self.ba = self.shared.cycle_base(); self.cb = self.ba; self.ps = 0.0
                self.n_doublings += 1
                note = f"💰DBL#{self.n_doublings}"
        else:
            self.ba -= stake
            self.ls += 1

        self.ps = stake
        return {"stake": stake, "result": result, "odd": td.total_odd, "ba": self.ba, "note": note}

    def total(self):
        return self.ba if not self.ruined else 0.0


def fmt_cell(info, mode):
    """Formate une cellule compacte : mise → solde + note"""
    if not info:
        return f"{'—':^28}"
    if info["result"] == "—":
        return f"{'💀 RUINÉ':^28}"
    if info["result"] == "⏸":
        amt = info["note"].replace("⏸PAUSE(", "").replace("€)", "")
        return f"{'⏸ attente ' + amt + '€':^28}"
    r = "✅" if info["result"] == "WIN" else "❌"
    note = ""
    if info["note"]:
        n = info["note"]
        if "DBL" in n:   note = " 💰"
        elif "RST" in n: note = f" 🏦({info['stake']:.0f}€)"
    return f"{r} {info['stake']:>7.0f}€ → {info['ba']:>8.0f}€{note}"


def _search_seed_job(args):
    """Worker parallèle : génère la séquence pour un seed et retourne (run_idx, total, mult)."""
    run_idx, datasets, tuning, reserves_init = args
    sys_details, rnd_details = _generate_sequences_from_datasets(datasets, tuning, run_idx)
    total, mult = _quick_sim(sys_details, rnd_details, reserves_init)
    return run_idx, total, mult


def _generate_sequences_from_datasets(datasets_with_vmaps, tuning, run_idx):
    """Génère les séquences pour un run_idx donné à partir des datasets+vmaps."""
    seed = run_idx * 137 + 42
    random.seed(seed)
    sys_details, rnd_details = [], []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for ds, verdict_map in datasets_with_vmaps:
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
    return sys_details, rnd_details


def _quick_sim(sys_details, rnd_details):
    """Simulation rapide sans logging — retourne le total final."""
    shared = SharedReserves(RESERVES_INIT)
    rs = Strategy("RANDOM SAFE",    "SAFE",    shared)
    rn = Strategy("RANDOM NORMALE", "NORMALE", shared)
    ss = Strategy("SYSTEM SAFE",    "SAFE",    shared)
    sn = Strategy("SYSTEM NORMALE", "NORMALE", shared)
    max_len = max(len(sys_details), len(rnd_details))
    for i in range(max_len):
        sys_td = sys_details[i] if i < len(sys_details) else None
        rnd_td = rnd_details[i] if i < len(rnd_details) else None
        for strat, td in sorted(
            [(ss, sys_td), (sn, sys_td), (rn, rnd_td), (rs, rnd_td)],
            key=lambda x: x[0].priority
        ):
            if td:
                strat.step(td)
    total = rs.total() + rn.total() + ss.total() + sn.total() + shared.amount
    invested = 4 * BANKROLL0 + RESERVES_INIT
    return total, total / invested


def _generate_sequences(vmap_list, tuning, run_idx):
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
    return sys_details, rnd_details


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--find-worst", action="store_true", help="Cherche le pire run sur N_SEARCH seeds")
    parser.add_argument("--run", type=int, default=None, help="Numéro de run à afficher (1-based)")
    parser.add_argument("--jobs", type=int, default=1, help="Workers parallèles pour --find-worst")
    args = parser.parse_args()

    print("[detail] Chargement...", flush=True)
    tuning   = _load_profile_1()
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    vmap_list = []
    for ds in datasets:
        vm = _parse_verdict_file(ds.verdict_file)
        vm = _enrich_verdict_map_with_results(vm, ds.predictions_tsv)
        vmap_list.append((ds, vm))
    print(f"[detail] {len(datasets)} jours chargés.", flush=True)

    if args.find_worst:
        n_jobs = args.jobs
        print(f"[detail] Recherche du pire run sur {N_SEARCH} seeds | {n_jobs} worker(s)...", flush=True)
        worst_idx, worst_total, worst_mult = 0, float("inf"), float("inf")
        done = 0
        if n_jobs == 1:
            for i in range(N_SEARCH):
                sys_d, rnd_d = _generate_sequences(vmap_list, tuning, i)
                total, mult = _quick_sim(sys_d, rnd_d)
                if total < worst_total:
                    worst_total, worst_mult, worst_idx = total, mult, i
                done += 1
                if done % 10 == 0:
                    print(f"  [{done}/{N_SEARCH}] pire jusqu'ici : Run {worst_idx+1} → {worst_total:.0f}€ (×{worst_mult:.2f})", flush=True)
        else:
            job_args = [(i, vmap_list, tuning) for i in range(N_SEARCH)]
            with ProcessPoolExecutor(max_workers=n_jobs) as ex:
                futures = {ex.submit(_search_seed_job, a): a[0] for a in job_args}
                for fut in as_completed(futures):
                    run_i, total, mult = fut.result()
                    if total < worst_total:
                        worst_total, worst_mult, worst_idx = total, mult, run_i
                    done += 1
                    if done % 5 == 0:
                        print(f"  [{done}/{N_SEARCH}] pire jusqu'ici : Run {worst_idx+1} → {worst_total:.0f}€ (×{worst_mult:.2f})", flush=True)
        print(f"\n→ PIRE RUN : Run {worst_idx+1} | Total={worst_total:.0f}€ | ×{worst_mult:.2f}\n", flush=True)
        run_idx = worst_idx
    elif args.run is not None:
        run_idx = args.run - 1
    else:
        run_idx = RUN_IDX

    sys_details, rnd_details = _generate_sequences_from_datasets(vmap_list, tuning, run_idx)
    print(f"[detail] Run {run_idx+1} | RANDOM={len(rnd_details)} tickets | SYSTEM={len(sys_details)} tickets\n")

    shared = SharedReserves(RESERVES_INIT)
    rs = Strategy("RANDOM SAFE",    "SAFE",    shared)
    rn = Strategy("RANDOM NORMALE", "NORMALE", shared)
    ss = Strategy("SYSTEM SAFE",    "SAFE",    shared)
    sn = Strategy("SYSTEM NORMALE", "NORMALE", shared)

    max_len = max(len(sys_details), len(rnd_details))

    # En-tête
    sep = "─" * 120
    header = (
        f"{'#':>4} │ {'Jour':<10} │ "
        f"{'RAND SAFE(3)':^28} │ "
        f"{'RAND NORM(4)':^28} │ "
        f"{'SYS SAFE(4)':^28} │ "
        f"{'SYS NORM(4)':^28} │ "
        f"{'Rés':>8}"
    )
    print(sep)
    print(header)
    print(sep)

    lines = []

    for i in range(max_len):
        sys_td = sys_details[i] if i < len(sys_details) else None
        rnd_td = rnd_details[i] if i < len(rnd_details) else None

        rnd_day = rnd_td.day if rnd_td else (sys_td.day if sys_td else "")
        sys_day = sys_td.day if sys_td else ""
        day     = rnd_day or sys_day

        # Traitement par priorité (organes vitaux en premier pour les réserves)
        results = {}
        for strat, td in sorted(
            [(sn, sys_td), (ss, sys_td), (rn, rnd_td), (rs, rnd_td)],
            key=lambda x: x[0].priority
        ):
            results[strat.name] = strat.step(td) if td else None

        rs_info = results["RANDOM SAFE"]
        rn_info = results["RANDOM NORMALE"]
        ss_info = results["SYSTEM SAFE"]
        sn_info = results["SYSTEM NORMALE"]

        rs_cell = fmt_cell(rs_info, "SAFE")    if rs_info else f"{'—':^38}"
        rn_cell = fmt_cell(rn_info, "NORMALE") if rn_info else f"{'—':^38}"
        ss_cell = fmt_cell(ss_info, "SAFE")    if ss_info else f"{'—':^38}"
        sn_cell = fmt_cell(sn_info, "NORMALE") if sn_info else f"{'—':^38}"

        line = (
            f"{i+1:>4} │ {day[5:]:<10} │ "
            f"{rs_cell} │ "
            f"{rn_cell} │ "
            f"{ss_cell} │ "
            f"{sn_cell} │ "
            f"{shared.amount:>7.0f}€"
        )
        print(line)
        lines.append(line)

    print(sep)
    total    = rs.total() + rn.total() + ss.total() + sn.total() + shared.amount
    invested = 4 * BANKROLL0 + RESERVES_INIT
    print(f"\n  RÉSULTAT FINAL (Run {run_idx+1})")
    pause_tag = lambda s: f"  ⏸{s.n_pauses}tours" if s.n_pauses > 0 else ""
    print(f"  RANDOM SAFE    : {rs.total():>10.2f}€  (×{rs.total()/BANKROLL0:.1f})  dbl={rs.n_doublings}  rst={rs.n_restarts}{pause_tag(rs)}")
    print(f"  RANDOM NORMALE : {rn.total():>10.2f}€  (×{rn.total()/BANKROLL0:.1f})  rst={rn.n_restarts}{pause_tag(rn)}")
    print(f"  SYSTEM SAFE    : {ss.total():>10.2f}€  (×{ss.total()/BANKROLL0:.1f})  dbl={ss.n_doublings}  rst={ss.n_restarts}{pause_tag(ss)}")
    print(f"  SYSTEM NORMALE : {sn.total():>10.2f}€  (×{sn.total()/BANKROLL0:.1f})  rst={sn.n_restarts}{pause_tag(sn)}")
    print(f"  Réserves       : {shared.amount:>10.2f}€")
    print(f"  ─────────────────────────────────────")
    print(f"  TOTAL          : {total:>10.2f}€  (×{total/invested:.2f} sur {invested:.0f}€ investis)")

    # Sauvegarde
    out_path = Path(f"data/optimizer/portfolio_detail_run{run_idx+1}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for l in lines:
            f.write(l + "\n")
    print(f"\n  Sauvegardé → {out_path}")


if __name__ == "__main__":
    main()
