"""
Portfolio 4 stratégies — suivi détaillé ticket par ticket
RUN_IDX : numéro du run à afficher (0=Run1, 1=Run2, ...)
"""
from __future__ import annotations
import random, sys, tempfile
from pathlib import Path

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, _PatchedBuilderIO,
    _enrich_verdict_map_with_results, _parse_verdict_file,
    discover_datasets,
)
from show_sequence import _load_profile_1, _ticket_to_detail

BANKROLL0     = 100.0
RESERVES_INIT = 200.0
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
RUN_IDX = 0   # Run 1


class SharedReserves:
    def __init__(self, init):
        self.amount = init
    def cycle_base(self):
        return BANKROLL0 + 0.20 * self.amount
    def add(self, p):
        self.amount += p
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


def main():
    print("[detail] Chargement...")
    tuning   = _load_profile_1()
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    vmap_list = []
    for ds in datasets:
        vm = _parse_verdict_file(ds.verdict_file)
        vm = _enrich_verdict_map_with_results(vm, ds.predictions_tsv)
        vmap_list.append((ds, vm))

    seed = RUN_IDX * 137 + 42
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

    print(f"[detail] Run {RUN_IDX+1} | RANDOM={len(rnd_details)} tickets | SYSTEM={len(sys_details)} tickets\n")

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
    total = rs.total() + rn.total() + ss.total() + sn.total() + shared.amount
    print(f"\n  RÉSULTAT FINAL (Run {RUN_IDX+1})")
    pause_tag = lambda s: f"  ⏸{s.n_pauses}tours" if s.n_pauses > 0 else ""
    print(f"  RANDOM SAFE    : {rs.total():>10.2f}€  (×{rs.total()/BANKROLL0:.1f})  dbl={rs.n_doublings}  rst={rs.n_restarts}{pause_tag(rs)}")
    print(f"  RANDOM NORMALE : {rn.total():>10.2f}€  (×{rn.total()/BANKROLL0:.1f})  rst={rn.n_restarts}{pause_tag(rn)}")
    print(f"  SYSTEM SAFE    : {ss.total():>10.2f}€  (×{ss.total()/BANKROLL0:.1f})  dbl={ss.n_doublings}  rst={ss.n_restarts}{pause_tag(ss)}")
    print(f"  SYSTEM NORMALE : {sn.total():>10.2f}€  (×{sn.total()/BANKROLL0:.1f})  rst={sn.n_restarts}{pause_tag(sn)}")
    print(f"  Réserves       : {shared.amount:>10.2f}€")
    print(f"  ─────────────────────────────────────")
    print(f"  TOTAL          : {total:>10.2f}€  (×{total/600:.2f} sur 600€ investis)")

    # Sauvegarde
    out_path = Path(f"data/optimizer/portfolio_detail_run{RUN_IDX+1}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for l in lines:
            f.write(l + "\n")
    print(f"\n  Sauvegardé → {out_path}")


if __name__ == "__main__":
    main()
