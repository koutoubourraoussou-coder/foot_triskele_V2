"""
show_sequence.py
----------------
Affiche le détail d'un run du profil #1 :
- Chaque ticket avec ses legs (home vs away, bet, cote, résultat)
- Évolution bankroll martingale NORMALE et SAFE
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import services.ticket_builder as tb
from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR,
    _PatchedBuilderIO,
    _enrich_verdict_map_with_results,
    _flat_profit_for_ticket,
    _parse_verdict_file,
    _ticket_outcome,
    discover_datasets,
)
from services.ticket_builder import BuilderTuning, Ticket

BANKROLL0  = 100.0
MAX_LOSSES = 4
ALL_PROFILES_PATH = Path("data/optimizer/optimizer_top_profiles.json")


# =========================================================
# STRUCTURES
# =========================================================
@dataclass
class LegDetail:
    home:     str
    away:     str
    league:   str
    bet_key:  str
    odd:      float
    verdict:  str  # "WIN" / "LOSS" / "?"


@dataclass
class TicketDetail:
    day:       str
    mode:      str   # "SYSTEM" ou "RANDOM"
    is_win:    Optional[bool]
    total_odd: float
    legs:      List[LegDetail]


# =========================================================
# CHARGEMENT PROFIL #1
# =========================================================
def _load_profile_1() -> BuilderTuning:
    raw = json.loads(ALL_PROFILES_PATH.read_text(encoding="utf-8"))
    raw_sorted = sorted(raw, key=lambda p: p.get("rank_score", -1e9), reverse=True)
    t = raw_sorted[0].get("tuning", {})
    return BuilderTuning(
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
    )


# =========================================================
# CONSTRUCTION SÉQUENCE DÉTAILLÉE
# =========================================================
def _ticket_to_detail(
    ticket: Ticket,
    mode: str,
    day: str,
    verdict_map: dict,
) -> TicketDetail:
    legs = []
    for p in ticket.picks:
        key = (p.match_id, tb._norm_bet_family(p.bet_key))
        v = verdict_map.get(key, "?")
        legs.append(LegDetail(
            home=p.home or "?",
            away=p.away or "?",
            league=p.league or "?",
            bet_key=p.bet_key or "?",
            odd=float(p.odd or 1.0),
            verdict=v,
        ))
    outcome = _ticket_outcome(ticket, verdict_map)
    return TicketDetail(
        day=day,
        mode=mode,
        is_win=outcome,
        total_odd=ticket.total_odd,
        legs=legs,
    )


def build_detailed_sequences(
    tuning: BuilderTuning,
) -> Tuple[List[TicketDetail], List[TicketDetail]]:
    datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
    sys_details: List[TicketDetail] = []
    rnd_details: List[TicketDetail] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for ds in datasets:
            verdict_map = _parse_verdict_file(ds.verdict_file)
            verdict_map = _enrich_verdict_map_with_results(verdict_map, ds.predictions_tsv)
            run_dir = tmp_root / ds.day

            with _PatchedBuilderIO(run_dir):
                out = tb.generate_tickets_from_tsv(
                    str(ds.predictions_tsv),
                    run_date=None,
                    tuning=tuning,
                )

            for ticket in out.tickets_system:
                d = _ticket_to_detail(ticket, "SYSTEM", ds.day, verdict_map)
                if d.is_win is not None:
                    sys_details.append(d)

            for ticket in out.tickets_o15:
                d = _ticket_to_detail(ticket, "RANDOM", ds.day, verdict_map)
                if d.is_win is not None:
                    rnd_details.append(d)

    return sys_details, rnd_details


# =========================================================
# AFFICHAGE SÉQUENCE
# =========================================================
def _print_sequence(details: List[TicketDetail], mode: str) -> None:
    print(f"\n{'='*70}")
    print(f"  SÉQUENCE {mode} — {len(details)} tickets")
    print(f"{'='*70}\n")

    for i, td in enumerate(details, start=1):
        res_icon = "✅ WIN " if td.is_win else "❌ LOSS"
        print(f"  Ticket #{i:>3} | {td.day} | {res_icon} | cote totale = {td.total_odd:.2f} | {len(td.legs)} legs")
        for j, leg in enumerate(td.legs, start=1):
            leg_icon = "✅" if leg.verdict == "WIN" else ("❌" if leg.verdict == "LOSS" else "❓")
            print(
                f"    Leg {j}: {leg_icon} {leg.home} vs {leg.away}"
                f"  |  {leg.bet_key}  |  cote={leg.odd:.2f}  |  {leg.league}"
            )
        print()


# =========================================================
# MARTINGALE NORMALE
# =========================================================
def _replay_normale(details: List[TicketDetail], label: str) -> None:
    bankroll    = BANKROLL0
    loss_streak = 0
    prev_stake  = 0.0
    denom       = float((2 ** MAX_LOSSES) - 1)
    n_wins = n_losses = 0
    cur_win_streak = 0

    print(f"\n{'='*70}")
    print(f"  MARTINGALE NORMALE — {label}")
    print(f"  Bankroll départ : {BANKROLL0:.2f}€  |  max_losses={MAX_LOSSES}")
    print(f"{'='*70}")
    print(f"  {'#':>3}  {'Résultat':<8}  {'Cote':>6}  {'Mise':>8}  {'Gain/Perte':>11}  {'Bankroll':>10}  Série")
    print(f"  {'-'*65}")

    for i, td in enumerate(details, start=1):
        if bankroll <= 0:
            break
        base  = bankroll / denom
        stake = base if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll)

        if td.is_win:
            gain = stake * (td.total_odd - 1.0)
            bankroll += gain
            n_wins += 1
            cur_win_streak += 1
            loss_streak = 0
            result = "✅ WIN"
            delta  = f"+{gain:>8.2f}€"
            serie  = f"W×{cur_win_streak}"
        else:
            bankroll -= stake
            n_losses += 1
            cur_win_streak = 0
            loss_streak += 1
            result = "❌ LOSS"
            delta  = f"-{stake:>8.2f}€"
            serie  = f"L×{loss_streak}"

        ruine = "  💀 RUINE" if bankroll <= 0 else ""
        print(f"  {i:>3}  {result:<8}  {td.total_odd:>6.2f}  {stake:>7.2f}€  {delta:>11}  {bankroll:>9.2f}€  {serie}{ruine}")
        prev_stake = stake

    print(f"  {'-'*65}")
    profit = bankroll - BANKROLL0
    sign = "+" if profit >= 0 else ""
    print(f"  RÉSULTAT : {n_wins}W / {n_losses}L  |  Bankroll : {bankroll:.2f}€  |  Profit : {sign}{profit:.2f}€  (x{bankroll/BANKROLL0:.2f})")


# =========================================================
# MARTINGALE SAFE
# =========================================================
def _replay_safe(details: List[TicketDetail], label: str) -> None:
    reserves        = 0.0
    n_doublings     = 0
    n_restarts      = 0
    n_wins = n_losses = 0
    cur_win_streak  = 0
    denom           = float((2 ** MAX_LOSSES) - 1)

    def _cycle_base():
        return BANKROLL0 + 0.20 * reserves

    bankroll_active = _cycle_base()
    cycle_base      = bankroll_active
    loss_streak     = 0
    prev_stake      = 0.0

    print(f"\n{'='*75}")
    print(f"  MARTINGALE SAFE — {label}")
    print(f"  Bankroll départ : {BANKROLL0:.2f}€  |  max_losses={MAX_LOSSES}  |  Réserves : 0€")
    print(f"{'='*75}")
    print(f"  {'#':>3}  {'Résultat':<8}  {'Cote':>6}  {'Mise':>8}  {'Gain/Perte':>11}  {'Active':>9}  {'Réserves':>9}  Note")
    print(f"  {'-'*72}")

    for i, td in enumerate(details, start=1):
        note = ""

        if bankroll_active <= 0:
            new_base = _cycle_base()
            if new_base <= 0 or reserves <= 0:
                break
            bankroll_active = new_base
            cycle_base      = new_base
            loss_streak     = 0
            prev_stake      = 0.0
            n_restarts     += 1
            note = f"↩ RESTART #{n_restarts}"

        base  = bankroll_active / denom
        stake = base if loss_streak == 0 else prev_stake * 2.0
        stake = min(stake, bankroll_active)

        if td.is_win:
            gain = stake * (td.total_odd - 1.0)
            bankroll_active += gain
            n_wins += 1
            loss_streak = 0
            cur_win_streak += 1
            result = "✅ WIN"
            delta  = f"+{gain:>8.2f}€"
            serie  = f"W×{cur_win_streak}"

            if bankroll_active >= cycle_base * 2.0:
                profit   = bankroll_active - cycle_base
                reserves += profit
                bankroll_active = _cycle_base()
                cycle_base      = bankroll_active
                prev_stake      = 0.0
                n_doublings    += 1
                note = f"💰 DOUBLING #{n_doublings}  → réserves={reserves:.2f}€  base={cycle_base:.2f}€"
                print(f"  {i:>3}  {result:<8}  {td.total_odd:>6.2f}  {stake:>7.2f}€  {delta:>11}  {bankroll_active:>8.2f}€  {reserves:>8.2f}€  {note}")
                continue
        else:
            bankroll_active -= stake
            n_losses += 1
            loss_streak += 1
            cur_win_streak = 0
            result = "❌ LOSS"
            delta  = f"-{stake:>8.2f}€"
            serie  = f"L×{loss_streak}"

        ruine = "  💀" if bankroll_active <= 0 and reserves <= 0 else ""
        print(f"  {i:>3}  {result:<8}  {td.total_odd:>6.2f}  {stake:>7.2f}€  {delta:>11}  {bankroll_active:>8.2f}€  {reserves:>8.2f}€  {note or serie}{ruine}")
        prev_stake = stake

    total  = bankroll_active + reserves
    profit = total - BANKROLL0
    sign   = "+" if profit >= 0 else ""
    print(f"  {'-'*72}")
    print(f"  RÉSULTAT : {n_wins}W / {n_losses}L  |  Active={bankroll_active:.2f}€  Réserves={reserves:.2f}€  Total={total:.2f}€")
    print(f"             Profit : {sign}{profit:.2f}€  (x{total/BANKROLL0:.2f})  |  Doublings={n_doublings}  Restarts={n_restarts}")


# =========================================================
# MAIN
# =========================================================
def main():
    print("[show] Chargement profil #1...")
    tuning = _load_profile_1()

    print("[show] Évaluation sur 60 jours...")
    sys_details, rnd_details = build_detailed_sequences(tuning)

    print(f"[show] SYSTEM : {len(sys_details)} tickets  |  RANDOM : {len(rnd_details)} tickets\n")

    # Séquences détaillées (legs)
    _print_sequence(sys_details, "SYSTEM")
    _print_sequence(rnd_details, "RANDOM")

    # Martingale
    _replay_normale(sys_details, "SYSTEM")
    _replay_safe(sys_details, "SYSTEM")
    _replay_normale(rnd_details, "RANDOM")
    _replay_safe(rnd_details, "RANDOM")


if __name__ == "__main__":
    main()
