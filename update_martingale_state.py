"""
update_martingale_state.py
──────────────────────────────────────────────────────────────
Mis à jour automatique de l'état Martingale après chaque RunMachine.

Lit les verdicts des tickets (SYSTEM et RANDOM) depuis :
  data/verdict_post_analyse_tickets_report.txt
  data/verdict_post_analyse_tickets_o15_random_report.txt

Pour chaque ticket avec date > last_updated et verdict décidé (WIN/LOSS),
applique le résultat aux stratégies concernées dans martingale_dual_state.json.

Appelé automatiquement par run_machine.py après post_analysis.py.
"""

from __future__ import annotations

import re
import json
import copy
from pathlib import Path
from datetime import date

ROOT           = Path(__file__).resolve().parent
STATE_FILE     = ROOT / "data" / "optimizer" / "martingale_dual_state.json"
VERDICT_SYSTEM = ROOT / "data" / "verdict_post_analyse_tickets_report.txt"
VERDICT_RANDOM = ROOT / "data" / "verdict_post_analyse_tickets_o15_random_report.txt"

# Bankrolls initiales (pour tirage réserves si ba → 0)
_BA0 = {
    "portfolio_a": 1.0,
    "portfolio_b": 0.70,
}

# Stratégies affectées par chaque type de ticket
_STRATS_FOR = {
    "SYSTEM": ["SYSTEM SAFE", "SYSTEM NORMALE"],
    "RANDOM": ["RANDOM SAFE", "RANDOM NORMALE"],
}


# ── Martingale logic (sans dépendance Streamlit) ──────────────────────────────

def _next_stake(ba: float, ls: int, ps: float, ml: int) -> float:
    denom = float((2 ** ml) - 1)
    s = ba / denom if ls == 0 else ps * 2.0
    return min(s, ba)


def _apply_result(
    sim: dict,
    is_win: bool,
    odd: float,
    reserves: float,
    ba0: float,
) -> tuple[dict, float]:
    """Applique un résultat WIN ou LOSS à une stratégie. Retourne (sim_mis_à_jour, reserves)."""
    sim = copy.deepcopy(sim)
    ba, cb, ls, ps = sim["ba"], sim["cb"], sim["ls"], sim["ps"]
    mode, ml = sim["mode"], sim["ml"]

    # Tirage réserves si bankroll épuisée
    if ba <= 0:
        next_bet = ps * 2.0 if ps > 0 else ba0 / float((2 ** ml) - 1)
        if reserves >= next_bet:
            ba = next_bet
            reserves -= next_bet
            print(f"    🏦 Tirage réserves : {next_bet:.4f}€")
        else:
            print(f"    ⚠️  Réserves insuffisantes pour {sim.get('mode','?')}")
            return sim, reserves

    stake = _next_stake(ba, ls, ps, ml)

    if is_win:
        ba += stake * (odd - 1.0)
        ls = 0
        if mode == "SAFE" and ba >= cb * 2.0:
            profit = ba - cb
            reserves += profit
            new_base = ba0 + 0.20 * reserves
            print(f"    💰 DOUBLING ! +{profit:.2f}€ → réserves. Nouvelle base : {new_base:.4f}€")
            ba = new_base
            cb = new_base
            ps = 0.0
        else:
            ps = stake
    else:
        ba -= stake
        ls += 1
        ps = stake

    sim.update({"ba": ba, "cb": cb, "ls": ls, "ps": ps})
    return sim, reserves


# ── Parsing des fichiers de verdict ───────────────────────────────────────────

def _parse_verdict_file(path: Path) -> list[dict]:
    """
    Parse un fichier verdict_post_analyse_tickets_*.txt.
    Retourne une liste de tickets triés par date croissante :
      {"date": "YYYY-MM-DD", "status": "WIN"|"LOSS"|"PENDING", "odd": float, "ticket_id": str}
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="ignore")
    tickets = []

    # Regex pour capturer chaque bloc ticket
    block_re = re.compile(
        r"(?P<icon>[✅❌⏳])\s*Ticket\s+\d+.*?odd=(?P<odd>[0-9.]+).*?"
        r"id=(?P<tid>\d{4}-\d{2}-\d{2}_\w+)",
        re.DOTALL,
    )

    for m in block_re.finditer(text):
        icon = m.group("icon").strip()
        if icon == "✅":
            status = "WIN"
        elif icon == "❌":
            status = "LOSS"
        else:
            status = "PENDING"

        tid = m.group("tid").strip()
        day = tid[:10]  # "YYYY-MM-DD"

        try:
            odd = float(m.group("odd"))
        except ValueError:
            odd = 1.0

        tickets.append({"date": day, "status": status, "odd": odd, "ticket_id": tid})

    # Trier chronologiquement
    tickets.sort(key=lambda t: t["ticket_id"])
    return tickets


# ── Chargement / sauvegarde de l'état ────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Boucle principale ─────────────────────────────────────────────────────────

def update(ticket_type: str, verdict_path: Path, state: dict) -> dict:
    """
    Applique les tickets non encore traités (date > last_updated) aux stratégies.
    ticket_type : "SYSTEM" ou "RANDOM"
    """
    tickets = _parse_verdict_file(verdict_path)
    strat_names = _STRATS_FOR[ticket_type]

    for pkey in ["portfolio_a", "portfolio_b"]:
        pstate      = state[pkey]
        last_upd    = pstate.get("last_updated", "2000-01-01")
        ba0         = _BA0[pkey]
        reserves    = pstate["reserves"]
        new_tickets = [t for t in tickets if t["date"] > last_upd and t["status"] != "PENDING"]

        if not new_tickets:
            print(f"  [{ticket_type}] {pkey} : rien de nouveau (last_updated={last_upd})")
            continue

        for t in new_tickets:
            is_win = t["status"] == "WIN"
            print(f"  [{ticket_type}] {pkey} | {t['date']} | {'✅ WIN' if is_win else '❌ LOSS'} (cote {t['odd']})")
            for sname in strat_names:
                sim = pstate["strategies"][sname]
                sim, reserves = _apply_result(sim, is_win, t["odd"], reserves, ba0)
                pstate["strategies"][sname] = sim

        # Mise à jour last_updated = date du dernier ticket traité
        pstate["last_updated"] = new_tickets[-1]["date"]
        pstate["reserves"]     = reserves

    return state


def main():
    print("\n============================")
    print("  Mise à jour Martingale")
    print("============================")

    state = _load_state()
    if not state:
        print("  ⚠️  Fichier d'état introuvable. Aucune mise à jour effectuée.")
        print("     → Initialisez l'état depuis l'onglet Martingale de l'app.")
        return

    state = update("SYSTEM", VERDICT_SYSTEM, state)
    state = update("RANDOM", VERDICT_RANDOM, state)

    _save_state(state)
    print("\n  ✅ État sauvegardé dans", STATE_FILE)
    print("============================\n")


if __name__ == "__main__":
    main()
