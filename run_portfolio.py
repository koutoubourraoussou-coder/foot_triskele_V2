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

Lance N_RUNS seeds et affiche un récap.
"""
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

BANKROLL0      = 100.0
RESERVES_INIT  = 600.0   # 200€ → 600€ pour couvrir crises simultanées
MAX_DRAW_RATIO = 1.00    # pas de cap (v1 pur)
N_RUNS         = 100

# max_losses par stratégie
ML = {
    "RANDOM SAFE":    3,   # denom=7
    "RANDOM NORMALE": 4,   # denom=15
    "SYSTEM SAFE":    4,   # denom=15
    "SYSTEM NORMALE": 4,   # denom=15
}

# Priorité d'accès aux réserves (1 = le plus prioritaire)
# RS (ML=3, dénominateur=7) mise moins fort → en dernier
# SS, SN, RN (ML=4, dénominateur=15) ont besoin de plus de réserves → prioritaires
PRIORITY = {
    "SYSTEM SAFE":     1,   # organe vital #1 — alimente les réserves + ML=4
    "SYSTEM NORMALE":  2,   # organe vital #2 — plus gros multiplicateur
    "RANDOM NORMALE":  3,   # ML=4
    "RANDOM SAFE":     4,   # ML=3 → mise plus petite → dernier
}


# ─── Martingale state ─────────────────────────────────────────────────────────
class Strategy:
    def __init__(self, name: str, mode: str, shared: "SharedReserves"):
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

    def _stake(self) -> float:
        s = self.ba / self.denom if self.ls == 0 else self.ps * 2.0
        return min(s, self.ba)

    def step(self, td) -> None:
        if self.ruined:
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
def run_portfolio(sys_details, rnd_details):
    shared = SharedReserves(RESERVES_INIT)

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
    print(f"\n[portfolio] {N_RUNS} runs | B0=4×{BANKROLL0:.0f}€ + réserves={RESERVES_INIT:.0f}€ | max_losses: {ml_str}\n")

    all_results = []

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

        res = run_portfolio(sys_details, rnd_details)
        all_results.append(res)

        strats = res["strategies"]
        sys.stdout.write(
            f"  Run {run_idx+1:>2} | "
            f"RS={strats[0].total():>8.2f}€ (×{strats[0].total()/BANKROLL0:.1f}) | "
            f"RN={strats[1].total():>8.2f}€ (×{strats[1].total()/BANKROLL0:.1f}) | "
            f"SS={strats[2].total():>8.2f}€ (×{strats[2].total()/BANKROLL0:.1f}) | "
            f"SN={strats[3].total():>8.2f}€ (×{strats[3].total()/BANKROLL0:.1f}) | "
            f"Réserves={res['shared']:>8.2f}€ | "
            f"TOTAL={res['total']:>9.2f}€  ×{res['mult']:.2f}\n"
        )
        sys.stdout.flush()

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
