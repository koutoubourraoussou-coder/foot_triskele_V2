"""
Portfolio 4 stratégies — réserves communes + règles de protection
-----------------------------------------------------------------
  RANDOM SAFE    : 100€ actif  (max_losses=3)
  RANDOM NORMALE : 100€ actif  (max_losses=4)
  SYSTEM SAFE    : 100€ actif  (max_losses=4)
  SYSTEM NORMALE : 100€ actif  (max_losses=4)
  Réserves communes : 600€ (+ doublings SAFE)  → total investi 1000€

Règles de protection :
  1. Cap 50% : une stratégie ne peut tirer que ≤ 50% des réserves actuelles
     → si elle a besoin de plus, elle se met en PAUSE
  2. Reset d'urgence : si toutes les stratégies actives sont en pause
     et que même la moins gourmande a besoin de > 50% des réserves
     → elle prend 50% des réserves et repart sur une mise revue à la baisse
     (ls=0, ps=0, nouvelle bankroll = 50% des réserves)
  3. Priorité SS > SN > RN > RS pour l'accès aux réserves

Lancement décalé (start_delay) :
  Permet de simuler un démarrage progressif des stratégies.
  Chaque stratégie démarre seulement quand une stratégie pivot a atteint
  un certain nombre de doublings. Exemple :
    RS démarre immédiatement (start_delay=None)
    SS démarre après le 1er doubling de RS (pivot=RS, target_doublings=1)
    RN/SN démarrent après le 1er doubling de SS (pivot=SS, target_doublings=1)
  Usage : passer start_delay=True à run_portfolio() ou lancer avec --start-delay

Lance N_RUNS seeds et affiche un récap.
"""
from __future__ import annotations
import random, statistics, sys, tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, DEFAULT_JOBS, _PatchedBuilderIO,
    _evaluate_profile_with_seqs_job,
    _enrich_verdict_map_with_results, _parse_verdict_file,
    discover_datasets,
)
from show_sequence import _load_profile_1, _ticket_to_detail


@dataclass
class _SimpleTicket:
    """Proxy léger pour TicketDetail — contient uniquement ce que Strategy.step() utilise."""
    is_win:    Optional[bool]
    total_odd: float

BANKROLL0      = 100.0
RESERVES_INIT  = 6514.0  # TEST : 4 pertes extra par stratégie (ML=4: 1600€×3, ML=3: 1714€)
MAX_DRAW_RATIO = 1.00    # pas de cap (v1 pur)
N_RUNS         = 200

# max_losses par stratégie
ML = {
    "RANDOM SAFE":    3,   # denom=7
    "RANDOM NORMALE": 3,   # denom=7
    "SYSTEM SAFE":    3,   # denom=7
    "SYSTEM NORMALE": 3,   # denom=7
}

# Priorité d'accès aux réserves (1 = le plus prioritaire)
# Toutes à ML=3 → mises équivalentes → priorité par type (SYSTEM > RANDOM, NORMALE > SAFE)
PRIORITY = {
    "SYSTEM NORMALE":  1,   # organe vital #1 — plus gros multiplicateur
    "SYSTEM SAFE":     2,   # organe vital #2 — alimente les réserves
    "RANDOM NORMALE":  3,   # ML=3
    "RANDOM SAFE":     4,   # ML=3 → dernier
}


# ─── Martingale state ─────────────────────────────────────────────────────────
class Strategy:
    def __init__(self, name: str, mode: str, shared: "SharedReserves",
                 start_pivot: "Strategy | None" = None,
                 start_after_doublings: int = 0):
        self.name         = name
        self.mode         = mode   # "SAFE" ou "NORMALE"
        self.shared       = shared
        self.priority     = PRIORITY[name]
        self.max_losses   = ML[name]
        self.denom        = float((2 ** self.max_losses) - 1)
        self.ba           = BANKROLL0      # bankroll active
        self.cb           = BANKROLL0      # cycle_base (SAFE only)
        self.ls           = 0              # loss streak
        self.ps           = 0.0           # previous stake
        self.n_wins       = 0
        self.n_losses     = 0
        self.n_doublings  = 0
        self.n_restarts   = 0
        self.n_pauses     = 0             # tours sautés (organes en attente)
        self.n_emergency  = 0             # resets d'urgence (mise revue à la baisse)
        self.max_streak   = 0
        self.ruined       = False          # ruine définitive (réserves épuisées — normalement impossible)
        self.paused       = False          # en attente de réserves suffisantes
        self.pending_bet  = 0.0           # mise nécessaire pour reprendre
        # ── Lancement décalé ──────────────────────────────────────────────────
        # La stratégie n'est "active" que si le pivot a atteint N doublings.
        # start_pivot=None → démarre immédiatement.
        self._start_pivot          = start_pivot
        self._start_after_doublings = start_after_doublings
        self._started              = (start_pivot is None)  # True si pas de pivot

    def is_ready(self) -> bool:
        """True si la stratégie peut commencer à jouer (condition start_delay remplie)."""
        if self._started:
            return True
        if self._start_pivot is not None and self._start_pivot.n_doublings >= self._start_after_doublings:
            self._started = True
            return True
        return False

    def _stake(self) -> float:
        s = self.ba / self.denom if self.ls == 0 else self.ps * 2.0
        return min(s, self.ba)

    def step(self, td) -> None:
        if self.ruined:
            return

        # ── Lancement décalé : ne pas jouer avant que le pivot ait doublé ──
        if not self.is_ready():
            self.n_pauses += 1
            return

        # ── Reprise après pause : vérifier si les réserves couvrent maintenant ──
        if self.paused:
            if self.shared.can_draw(self.pending_bet):
                drawn = self.shared.draw(self.pending_bet)
                self.ba = drawn
                self.paused = False
                self.n_restarts += 1
                # ls et ps conservés → séquence continue depuis là où on était
            else:
                self.n_pauses += 1
                return  # toujours en attente, on saute ce tour

        # ── Banque de secours : bankroll épuisée après une perte ──
        if self.ba <= 0:
            next_bet = self.ps * 2.0 if self.ps > 0 else self.ba / self.denom
            if self.shared.can_draw(next_bet):
                drawn = self.shared.draw(next_bet)
                self.ba = drawn
                self.n_restarts += 1
                # ls et ps conservés → séquence continue
            else:
                # Réserves insuffisantes → mise en pause (pas de ruine définitive)
                self.paused = True
                self.pending_bet = next_bet
                self.n_pauses += 1
                return

        stake = self._stake()

        if td.is_win:
            self.ba += stake * (td.total_odd - 1.0)
            self.n_wins += 1; self.ls = 0

            if self.mode == "SAFE" and self.ba >= self.cb * 2.0:
                profit = self.ba - self.cb
                self.shared.add(profit)
                self.ba = self.shared.cycle_base()
                self.cb = self.ba
                self.ps = 0.0; self.n_doublings += 1
                return   # ne pas mettre à jour ps en bas
        else:
            self.ba -= stake
            self.n_losses += 1; self.ls += 1
            self.max_streak = max(self.max_streak, self.ls)

        self.ps = stake

    def total(self) -> float:
        return self.ba if not self.ruined else 0.0


# ─── Réserves communes ────────────────────────────────────────────────────────
class SharedReserves:
    def __init__(self, init: float):
        self.amount = init

    def cycle_base(self) -> float:
        return BANKROLL0 + 0.20 * self.amount

    def add(self, profit: float) -> None:
        self.amount += profit

    def can_draw(self, need: float) -> bool:
        """Vrai si les réserves couvrent 'need' ET que need ≤ 50% des réserves."""
        return self.amount > 0 and need <= self.amount * MAX_DRAW_RATIO

    def draw(self, need: float) -> float:
        drawn = min(need, self.amount)
        self.amount -= drawn
        return drawn

    def draw_half(self) -> float:
        """Tirage d'urgence : prend exactement 50% des réserves actuelles."""
        drawn = self.amount * MAX_DRAW_RATIO
        self.amount -= drawn
        return drawn


# ─── Reset d'urgence ─────────────────────────────────────────────────────────
def _emergency_reset_if_needed(strategies, rnd_td, sys_td, shared):
    """
    Si TOUTES les stratégies actives sont en pause ET que même la moins gourmande
    a besoin de plus de 50% des réserves → reset d'urgence pour la moins gourmande :
    elle prend 50% des réserves et repart sur une mise revue à la baisse.
    """
    if shared.amount <= 0:
        return

    # Stratégies actives ce tour (ont un ticket)
    active = [(s, sys_td if s.name.startswith("SYSTEM") else rnd_td)
              for s in strategies
              if (sys_td if s.name.startswith("SYSTEM") else rnd_td) is not None]

    if not active:
        return

    # Vérifier que TOUTES les stratégies actives sont en pause
    paused_active = [s for s, _ in active if s.paused and s.ba <= 0]
    if len(paused_active) < len(active):
        return  # Certaines jouent encore normalement

    # Vérifier que même la moins gourmande a besoin de > 50% des réserves
    min_pending = min(s.pending_bet for s in paused_active)
    if min_pending <= shared.amount * MAX_DRAW_RATIO:
        return  # La reprise normale suffit (sera gérée dans step())

    # Reset d'urgence : la moins gourmande repart à la baisse
    target = min(paused_active, key=lambda s: s.pending_bet)
    new_ba = shared.draw_half()   # prend 50% des réserves
    target.ba          = new_ba
    target.cb          = new_ba   # nouveau cycle_base proportionnel
    target.ls          = 0
    target.ps          = 0.0
    target.paused      = False
    target.pending_bet = 0.0
    target.n_restarts += 1
    target.n_emergency += 1


# ─── Simulation ───────────────────────────────────────────────────────────────
def run_portfolio(sys_details, rnd_details, start_delay: bool = False):
    """
    Simule le portfolio sur une séquence de tickets.

    start_delay=False : toutes les stratégies démarrent simultanément (comportement historique).
    start_delay=True  : lancement progressif —
        RS démarre immédiatement
        SS démarre après le 1er doubling de RS
        RN et SN démarrent après le 1er doubling de SS
    """
    shared = SharedReserves(RESERVES_INIT)

    if start_delay:
        # RS sans pivot → démarre immédiatement
        rs = Strategy("RANDOM SAFE",    "SAFE",    shared,
                      start_pivot=None, start_after_doublings=0)
        # SS démarre après le 1er doubling de RS
        ss = Strategy("SYSTEM SAFE",    "SAFE",    shared,
                      start_pivot=rs, start_after_doublings=1)
        # RN et SN démarrent après le 1er doubling de SS
        rn = Strategy("RANDOM NORMALE", "NORMALE", shared,
                      start_pivot=ss, start_after_doublings=1)
        sn = Strategy("SYSTEM NORMALE", "NORMALE", shared,
                      start_pivot=ss, start_after_doublings=1)
    else:
        rs = Strategy("RANDOM SAFE",    "SAFE",    shared)
        rn = Strategy("RANDOM NORMALE", "NORMALE", shared)
        ss = Strategy("SYSTEM SAFE",    "SAFE",    shared)
        sn = Strategy("SYSTEM NORMALE", "NORMALE", shared)

    strategies = [rs, rn, ss, sn]

    # Aligne les séquences SYSTEM et RANDOM (longueur peut différer)
    max_len = max(len(sys_details), len(rnd_details))

    for i in range(max_len):
        sys_td = sys_details[i] if i < len(sys_details) else None
        rnd_td = rnd_details[i] if i < len(rnd_details) else None

        # Reset d'urgence avant de jouer (si tout le monde est en pause)
        _emergency_reset_if_needed(strategies, rnd_td, sys_td, shared)

        # Traitement par ordre de priorité (SS > SN > RN > RS pour les réserves)
        turn_pairs = sorted(
            [(ss, sys_td), (sn, sys_td), (rn, rnd_td), (rs, rnd_td)],
            key=lambda x: x[0].priority
        )
        for strat, td in turn_pairs:
            if td:
                strat.step(td)

    total_active = sum(s.total() for s in strategies)
    grand_total  = total_active + shared.amount
    invested     = 4 * BANKROLL0 + RESERVES_INIT   # 1000€

    return {
        "strategies": strategies,
        "shared":     shared.amount,
        "total":      grand_total,
        "mult":       grand_total / invested,
        "invested":   invested,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio 4 stratégies — Triskèle V2")
    parser.add_argument(
        "--start-delay", action="store_true", default=False,
        help="Lancement décalé : RS d'abord, SS après 1er doubling RS, RN/SN après 1er doubling SS"
    )
    parser.add_argument("--jobs", type=int, default=1, help="Nombre de workers parallèles")
    args = parser.parse_args()
    use_start_delay = args.start_delay
    n_jobs = args.jobs

    print("[portfolio] Chargement profil #1...")
    tuning = _load_profile_1()

    print("[portfolio] Chargement datasets...")
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    print(f"[portfolio] {len(datasets)} jours")

    print("[portfolio] Pré-chargement verdict maps...")
    vmap_list = []
    for ds in datasets:
        vm = _parse_verdict_file(ds.verdict_file)
        vm = _enrich_verdict_map_with_results(vm, ds.predictions_tsv)
        vmap_list.append((ds, vm))

    ml_str = " | ".join(f"{k.split()[0][0]}{k.split()[1][0]}={v}" for k, v in ML.items())
    delay_str = " | start_delay=ON (RS→SS→RN/SN)" if use_start_delay else ""
    print(f"\n[portfolio] {N_RUNS} runs | B0=4×{BANKROLL0:.0f}€ + réserves={RESERVES_INIT:.0f}€ | max_losses: {ml_str}{delay_str}\n")

    all_results = [None] * N_RUNS

    import time
    start_t = time.time()

    if n_jobs == 1:
        for run_idx in range(N_RUNS):
            _, res = _process_one(run_idx)
            all_results[run_idx] = res
            strats = res["strategies"]
            sys.stdout.write(
                f"  Run {run_idx+1:>3}/{N_RUNS} | "
                f"RS=×{strats[0].total()/BANKROLL0:.1f} | "
                f"RN=×{strats[1].total()/BANKROLL0:.1f} | "
                f"SS=×{strats[2].total()/BANKROLL0:.1f} | "
                f"SN=×{strats[3].total()/BANKROLL0:.1f} | "
                f"TOTAL=×{res['mult']:.2f}\n"
            )
            sys.stdout.flush()
    else:
        done = 0
        step = max(1, N_RUNS // 20)
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futures = {
                ex.submit(_evaluate_profile_with_seqs_job, (datasets, tuning, False, 1)): i
                for i in range(N_RUNS)
            }
            for fut in as_completed(futures):
                run_idx = futures[fut]
                _, sys_seq, rnd_seq = fut.result()
                sys_d = [_SimpleTicket(is_win=w, total_odd=o) for w, o in sys_seq]
                rnd_d = [_SimpleTicket(is_win=w, total_odd=o) for w, o in rnd_seq]
                res = run_portfolio(sys_d, rnd_d, start_delay=use_start_delay)
                all_results[run_idx] = res
                done += 1
                if done % step == 0 or done == N_RUNS:
                    elapsed = time.time() - start_t
                    eta = (N_RUNS - done) / (done / elapsed) if elapsed > 0 else 0
                    print(f"[portfolio] {done}/{N_RUNS} | {elapsed/60:.1f}min | ETA ~{eta/60:.1f}min", flush=True)

    # ─── Tableau récap ────────────────────────────────────────────────────────
    totals = [r["total"] for r in all_results]
    mults  = [r["mult"]  for r in all_results]

    print()
    print("=" * 95)
    print(f"  {'Run':<4} {'RAND SAFE':>10} {'RAND NORM':>10} {'SYS SAFE':>10} {'SYS NORM':>10} {'Réserves':>10} {'TOTAL':>10}  {'×':>6}")
    print("-" * 95)
    for i, res in enumerate(all_results):
        s = res["strategies"]
        tag = " ← MIN" if res["total"] == min(totals) else (" ← MAX" if res["total"] == max(totals) else "")
        print(
            f"  {i+1:<4} "
            f"{s[0].total():>9.2f}€ "
            f"{s[1].total():>9.2f}€ "
            f"{s[2].total():>9.2f}€ "
            f"{s[3].total():>9.2f}€ "
            f"{res['shared']:>9.2f}€ "
            f"{res['total']:>9.2f}€  ×{res['mult']:<6.2f}{tag}"
        )

    print("=" * 95)
    print(
        f"  Investi : {all_results[0]['invested']:.0f}€  |  "
        f"Moyenne : {statistics.mean(totals):.2f}€ (×{statistics.mean(mults):.2f})  |  "
        f"Min : ×{min(mults):.2f}  |  "
        f"Max : ×{max(mults):.2f}  |  "
        f"σ : {statistics.stdev(mults):.2f}"
    )

    # ─── Stats par stratégie ──────────────────────────────────────────────────
    print()
    print("  Détail par stratégie (moyenne sur 10 runs) :")
    names = ["RANDOM SAFE", "RANDOM NORMALE", "SYSTEM SAFE", "SYSTEM NORMALE"]
    for si, name in enumerate(names):
        vals   = [r["strategies"][si].total() for r in all_results]
        dbls   = [r["strategies"][si].n_doublings for r in all_results]
        ruines  = sum(1 for r in all_results if r["strategies"][si].ruined)
        pauses  = [r["strategies"][si].n_pauses    for r in all_results]
        restarts= [r["strategies"][si].n_restarts  for r in all_results]
        emerg   = [r["strategies"][si].n_emergency for r in all_results]
        print(
            f"    {name:<16} | moy={statistics.mean(vals):>8.2f}€ | "
            f"min={min(vals):>8.2f}€ | max={max(vals):>8.2f}€ | "
            f"dbl_moy={statistics.mean(dbls):.1f} | "
            f"pauses_moy={statistics.mean(pauses):.1f} | "
            f"rst_moy={statistics.mean(restarts):.1f} | "
            f"emerg_moy={statistics.mean(emerg):.1f} | ruines={ruines}/10"
        )


if __name__ == "__main__":
    main()
