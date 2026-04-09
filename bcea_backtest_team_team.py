"""
Backtest SYSTEM TEAM/TEAM — 4 avril au 9 avril 2026
Compare :
  - RÉEL : tickets effectivement joués (verdict_post_analyse_tickets_report.txt)
  - TEAM/TEAM : tickets simulés avec build=TEAM, select=TEAM
"""
from __future__ import annotations
import sys, re
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

DATE_FROM = "2026-04-04"
DATE_TO   = "2026-04-09"

# ─── Verdict global pick → WIN/LOSS ─────────────────────────────────────
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

print(f"Verdict picks chargé : {len(verdict_global)}")


def ticket_result_from_picks(picks) -> str:
    for pick in picks:
        mid = str(pick.match_id)
        label = pick.bet_key
        result = verdict_global.get((mid, label))
        if result is None:
            return "UNKNOWN"
        if result == "LOSS":
            return "LOSS"
    return "WIN"


# ─── RÉEL : lire les vrais tickets depuis le rapport ────────────────────
TICKETS_REPORT = ROOT / "data" / "verdict_post_analyse_tickets_report.txt"

real_tickets_by_date: dict[str, list[dict]] = defaultdict(list)

content = TICKETS_REPORT.read_text(encoding="utf-8", errors="ignore")
# Chercher les tickets entre DATE_FROM et DATE_TO
ticket_pattern = re.compile(
    r'([✅❌])\s+Ticket\s+\d+\s*\|\s*\w+\s+(\d{4}-\d{2}-\d{2})\s.*?odd=([\d.]+)',
)
for m in ticket_pattern.finditer(content):
    icon, date, odd = m.group(1), m.group(2), m.group(3)
    if DATE_FROM <= date <= DATE_TO:
        result = "WIN" if icon == "✅" else "LOSS"
        real_tickets_by_date[date].append({
            "odd": float(odd),
            "result": result,
        })

print(f"Tickets réels chargés : {sum(len(v) for v in real_tickets_by_date.values())} sur {DATE_FROM}→{DATE_TO}")


# ─── TEAM/TEAM : simuler ────────────────────────────────────────────────
def run_team_team() -> dict[str, list[dict]]:
    tuning = BuilderTuning(
        system_build_source="TEAM",
        system_select_source="TEAM",
    )
    _set_active_tuning(tuning)
    league_bet, team_bet = _load_rankings()

    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    target = [
        ds for ds in datasets
        if DATE_FROM <= ds.day <= DATE_TO and ds.predictions_tsv.exists()
    ]

    by_date: dict[str, list[dict]] = defaultdict(list)
    for ds in sorted(target, key=lambda d: d.day):
        picks_all = load_predictions_tsv(str(ds.predictions_tsv))
        pool_base = filter_playable_system(picks_all)
        pool_eff  = filter_effective_system_pool(pool_base, league_bet, team_bet)
        tickets   = build_tickets(pool_eff, mode="SYSTEM")
        for t in tickets:
            res  = ticket_result_from_picks(t.picks)
            legs = [f"{p.bet_key}@{p.odd:.2f}" for p in t.picks]
            by_date[ds.day].append({
                "odd": t.total_odd,
                "legs": legs,
                "result": res,
            })

    _clear_active_tuning()
    return by_date


print("\n[Simulation TEAM/TEAM en cours...]")
team_team = run_team_team()


# ─── Rapport ─────────────────────────────────────────────────────────────
lines: list[str] = []
def pr(*a):
    s = " ".join(str(x) for x in a)
    print(s); lines.append(s)
def sep(t):
    pr("\n" + "=" * 72); pr(f"  {t}"); pr("=" * 72)

pr("=" * 72)
pr("Backtest TEAM/TEAM vs RÉEL — 4 au 9 avril 2026")
pr("=" * 72)

all_dates = sorted(set(list(real_tickets_by_date.keys()) + list(team_team.keys())))

sep("RÉEL (tickets effectivement joués)")
for date in all_dates:
    tickets = real_tickets_by_date.get(date, [])
    pr(f"\n📅 {date} — {len(tickets)} ticket(s) réel(s)")
    for t in tickets:
        icon = "✓" if t["result"] == "WIN" else "✗"
        pr(f"   [{icon}] Cote {t['odd']:.2f} → {t['result']}")

w_real = sum(1 for d in real_tickets_by_date.values() for t in d if t["result"] == "WIN")
l_real = sum(1 for d in real_tickets_by_date.values() for t in d if t["result"] == "LOSS")
tot_real = w_real + l_real
pr(f"\n  Bilan RÉEL : {w_real}W / {l_real}L sur {tot_real} tickets" +
   (f" = {w_real/tot_real*100:.0f}% win" if tot_real else ""))

sep("SIMULÉ — TEAM/TEAM")
for date in all_dates:
    tickets = team_team.get(date, [])
    pr(f"\n📅 {date} — {len(tickets)} ticket(s) simulé(s)")
    for t in tickets:
        icon = "✓" if t["result"] == "WIN" else ("?" if t["result"] == "UNKNOWN" else "✗")
        pr(f"   [{icon}] Cote {t['odd']:.2f} — {' | '.join(t['legs'])} → {t['result']}")

w_sim = sum(1 for d in team_team.values() for t in d if t["result"] == "WIN")
l_sim = sum(1 for d in team_team.values() for t in d if t["result"] == "LOSS")
tot_sim = w_sim + l_sim
pr(f"\n  Bilan TEAM/TEAM simulé : {w_sim}W / {l_sim}L sur {tot_sim} tickets" +
   (f" = {w_sim/tot_sim*100:.0f}% win" if tot_sim else ""))

sep("COMPARAISON PAR JOUR")
pr(f"\n{'Date':>12} | {'RÉEL':>18} | {'TEAM/TEAM simulé'}")
pr("-" * 70)
for date in all_dates:
    real = real_tickets_by_date.get(date, [])
    sim  = team_team.get(date, [])
    def fmt(ts):
        if not ts: return "— (aucun)"
        return " | ".join(("✓" if t["result"]=="WIN" else ("?" if t["result"]=="UNKNOWN" else "✗")) + f" {t['odd']:.2f}" for t in ts)
    pr(f"{date:>12} | {fmt(real):>18} | {fmt(sim)}")

sep("SYNTHÈSE")
pr(f"\n  RÉEL      (LEAGUE/HYBRID) : {w_real}W / {l_real}L" + (f" = {w_real/tot_real*100:.0f}% win" if tot_real else ""))
pr(f"  SIMULÉ    (TEAM/TEAM)     : {w_sim}W / {l_sim}L" + (f" = {w_sim/tot_sim*100:.0f}% win" if tot_sim else ""))

if w_sim > w_real:
    pr(f"\n  → TEAM/TEAM aurait donné +{w_sim - w_real} victoire(s) de plus")
elif w_sim == w_real:
    pr(f"\n  → Résultats similaires (même nombre de victoires)")
else:
    pr(f"\n  → TEAM/TEAM aurait donné {w_real - w_sim} victoire(s) de moins")

out_path = OUTPUT_DIR / "bcea_backtest_team_team.txt"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ Sauvegardé : {out_path}")
