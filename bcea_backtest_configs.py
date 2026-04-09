"""
Backtest configurations ticket SYSTEM — 88 jours
Teste différentes combinaisons de :
  - Mode BUILD/SELECT : LEAGUE/HYBRID (actuel) vs TEAM/TEAM
  - Min odd par pick : 1.15 (actuel), 1.20, 1.25, 1.30
  - Structure legs : 3-4 legs (actuel) vs 3 legs forcé
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services.ticket_builder import (
    BuilderTuning,
    _set_active_tuning,
    _clear_active_tuning,
    _load_rankings,
    load_predictions_tsv,
    filter_playable_system,
    filter_effective_system_pool,
    build_tickets,
    Ticket,
)
from services.ticket_optimizer import DEFAULT_ARCHIVE_DIR, discover_datasets

OUTPUT_DIR = ROOT / "data" / "optimizer"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MISE = 7.0

# ─── Verdict global ─────────────────────────────────────────────────────
verdict_global: dict[tuple, str] = {}
verdict_path = ROOT / "data" / "verdict_post_analyse.txt"
for line in verdict_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    if not line.startswith("TSV:"):
        continue
    parts = line.split("\t")
    if len(parts) < 11:
        continue
    try:
        mid_str  = parts[0].replace("TSV:", "").strip()
        label    = parts[5].strip()
        result   = parts[10].strip()
        if result in ("WIN", "LOSS"):
            verdict_global[(mid_str, label)] = result
    except (ValueError, IndexError):
        continue

datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
print(f"Archive : {len(datasets)} jours | Verdict : {len(verdict_global)} picks")


def ticket_result(ticket: Ticket) -> str:
    for pick in ticket.picks:
        r = verdict_global.get((str(pick.match_id), pick.bet_key))
        if r is None:
            return "UNKNOWN"
        if r == "LOSS":
            return "LOSS"
    return "WIN"


def run_config(
    build_src: str,
    select_src: str,
    min_pick_odd: float,
    force_3legs: bool,
) -> dict:
    """Lance le builder sur 88 jours avec la config donnée. Retourne les stats."""

    prefer_delta = 1.0 if force_3legs else 0.08  # 1.0 = toujours préférer 3 legs

    tuning = BuilderTuning(
        system_build_source=build_src,
        system_select_source=select_src,
        prefer_3legs_delta=prefer_delta,
    )
    _set_active_tuning(tuning)
    league_bet, team_bet = _load_rankings()

    wins = losses = unknown = n_tickets = 0
    n_3legs = n_4legs = 0
    total_odd = 0.0
    pnl = 0.0
    seen_tickets: set[str] = set()

    for ds in sorted(datasets, key=lambda d: d.day):
        if not ds.predictions_tsv.exists():
            continue
        picks_all = load_predictions_tsv(str(ds.predictions_tsv))
        pool_base = filter_playable_system(picks_all)
        pool_eff  = filter_effective_system_pool(pool_base, league_bet, team_bet)

        # Filtre min_pick_odd post-pool
        if min_pick_odd > 1.15:
            pool_eff = [p for p in pool_eff if (p.odd or 0) >= min_pick_odd]

        tickets = build_tickets(pool_eff, mode="SYSTEM")

        for t in tickets:
            # Déduplication par composition (même picks = même ticket)
            sig = "|".join(sorted(f"{p.match_id}_{p.bet_key}" for p in t.picks))
            if sig in seen_tickets:
                continue
            seen_tickets.add(sig)

            res = ticket_result(t)
            n_tickets += 1
            total_odd += t.total_odd
            n_legs = len(t.picks)
            if n_legs <= 3:
                n_3legs += 1
            else:
                n_4legs += 1

            if res == "WIN":
                wins += 1
                pnl += (t.total_odd - 1) * MISE
            elif res == "LOSS":
                losses += 1
                pnl -= MISE
            else:
                unknown += 1

    _clear_active_tuning()

    decided = wins + losses
    return {
        "n_tickets": n_tickets,
        "wins": wins,
        "losses": losses,
        "unknown": unknown,
        "win_rate": wins / decided if decided else 0,
        "avg_odd": total_odd / n_tickets if n_tickets else 0,
        "pnl": pnl,
        "roi": pnl / (decided * MISE) if decided else 0,
        "n_3legs": n_3legs,
        "n_4legs": n_4legs,
    }


# ─── Configurations à tester ────────────────────────────────────────────

configs = [
    # (label, build_src, select_src, min_odd, force_3legs)
    ("ACTUEL  (LEAGUE/HYBRID, ≥1.15, 3-4L)", "LEAGUE", "HYBRID", 1.15, False),
    ("TEAM/TEAM  ≥1.15  3-4 legs",           "TEAM",   "TEAM",   1.15, False),
    ("TEAM/TEAM  ≥1.15  3 legs forcé",       "TEAM",   "TEAM",   1.15, True),
    ("TEAM/TEAM  ≥1.20  3-4 legs",           "TEAM",   "TEAM",   1.20, False),
    ("TEAM/TEAM  ≥1.20  3 legs forcé",       "TEAM",   "TEAM",   1.20, True),
    ("TEAM/TEAM  ≥1.25  3-4 legs",           "TEAM",   "TEAM",   1.25, False),
    ("TEAM/TEAM  ≥1.25  3 legs forcé",       "TEAM",   "TEAM",   1.25, True),
    ("TEAM/TEAM  ≥1.30  3-4 legs",           "TEAM",   "TEAM",   1.30, False),
    ("TEAM/TEAM  ≥1.30  3 legs forcé",       "TEAM",   "TEAM",   1.30, True),
]

results = []
for label, build, select, min_odd, force3 in configs:
    print(f"\n[{label}] ...")
    r = run_config(build, select, min_odd, force3)
    r["label"] = label
    results.append(r)
    print(f"  → {r['wins']}W / {r['losses']}L | win {r['win_rate']*100:.0f}% | "
          f"avg cote {r['avg_odd']:.2f} | P&L {r['pnl']:+.0f}€ | "
          f"3L={r['n_3legs']} 4L={r['n_4legs']}")


# ─── Rapport ─────────────────────────────────────────────────────────────

lines: list[str] = []
def pr(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)
def sep(t):
    pr("\n" + "=" * 90); pr(f"  {t}"); pr("=" * 90)

pr("=" * 90)
pr("Backtest configurations SYSTEM — 88 jours — Mise fixe 7€/ticket")
pr("=" * 90)

sep("TABLEAU COMPARATIF")
pr(f"\n{'Configuration':>42} | {'Tickets':>7} | {'W':>4} | {'L':>4} | {'Win%':>5} | {'Cote moy':>8} | {'P&L':>8} | {'ROI':>6} | 3L / 4L")
pr("-" * 110)

best_winrate = max(r["win_rate"] for r in results)
best_pnl     = max(r["pnl"] for r in results)

for r in results:
    wr_mark  = " ◄WR"  if r["win_rate"] == best_winrate else ""
    pnl_mark = " ◄P&L" if r["pnl"] == best_pnl else ""
    pr(f"{r['label']:>42} | {r['n_tickets']:>7} | {r['wins']:>4} | {r['losses']:>4} | "
       f"{r['win_rate']*100:>4.0f}% | {r['avg_odd']:>8.2f} | {r['pnl']:>+7.0f}€ | "
       f"{r['roi']*100:>5.1f}% | {r['n_3legs']} / {r['n_4legs']}"
       + wr_mark + pnl_mark)

sep("ANALYSE")

actuel = results[0]
for r in results[1:]:
    delta_wr  = (r["win_rate"] - actuel["win_rate"]) * 100
    delta_pnl = r["pnl"] - actuel["pnl"]
    arrow = "↑" if delta_pnl > 0 else "↓"
    pr(f"  {r['label']}")
    pr(f"    Win rate : {r['win_rate']*100:.0f}% ({delta_wr:+.0f}pts vs actuel) | "
       f"P&L : {r['pnl']:+.0f}€ ({arrow}{abs(delta_pnl):.0f}€ vs actuel)")
    pr("")

sep("RECOMMANDATION")

# Meilleur P&L parmi les configs TEAM/TEAM
team_configs = [r for r in results if "TEAM/TEAM" in r["label"]]
best = max(team_configs, key=lambda r: r["pnl"])
pr(f"\n  Meilleure config TEAM/TEAM : {best['label']}")
pr(f"  Win rate : {best['win_rate']*100:.0f}% | P&L : {best['pnl']:+.0f}€ | Avg cote : {best['avg_odd']:.2f}")
pr(f"  vs ACTUEL : P&L {actuel['pnl']:+.0f}€ ({best['pnl']-actuel['pnl']:+.0f}€)")

out_path = OUTPUT_DIR / "bcea_backtest_configs.txt"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ Sauvegardé : {out_path}")
