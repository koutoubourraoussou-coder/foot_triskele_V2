"""
update_martingale_state.py
──────────────────────────────────────────────────────────────
Mise à jour automatique de l'état Martingale après chaque RunMachine.

Lit les verdicts des 4 pipelines :
  data/verdict_post_analyse_tickets_o15_random_report.txt
  data/verdict_post_analyse_tickets_o15_super_random_report.txt
  data/verdict_post_analyse_tickets_u35_random_report.txt
  data/verdict_post_analyse_tickets_u35_super_random_report.txt

Pour chaque ticket avec date > last_updated et verdict décidé (WIN/LOSS),
applique le résultat à la stratégie concernée dans martingale_dual_state.json.

Appelé automatiquement par run_machine.py après post_analysis.py.
"""

from __future__ import annotations

import re
import json
import copy
from pathlib import Path
from datetime import date

ROOT       = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "optimizer" / "martingale_dual_state.json"

VERDICT_FILES = {
    "O15_RANDOM":       ROOT / "data" / "verdict_post_analyse_tickets_o15_random_report.txt",
    "O15_SUPER_RANDOM": ROOT / "data" / "verdict_post_analyse_tickets_o15_super_random_report.txt",
    "U35_RANDOM":       ROOT / "data" / "verdict_post_analyse_tickets_u35_random_report.txt",
    "U35_SUPER_RANDOM": ROOT / "data" / "verdict_post_analyse_tickets_u35_super_random_report.txt",
    "O25_RANDOM":       ROOT / "data" / "verdict_post_analyse_tickets_o25_random_report.txt",
    "O25_SUPER_RANDOM": ROOT / "data" / "verdict_post_analyse_tickets_o25_super_random_report.txt",
}

# Stratégie affectée par chaque pipeline
_STRAT_FOR = {
    "O15_RANDOM":       "O15 RANDOM SAFE",
    "O15_SUPER_RANDOM": "O15 SUPER SAFE",
    "U35_RANDOM":       "U35 RANDOM SAFE",
    "U35_SUPER_RANDOM": "U35 SUPER SAFE",
    "O25_RANDOM":       "O25 RANDOM SAFE",
    "O25_SUPER_RANDOM": "O25 SUPER SAFE",
}

# Mise initiale par stratégie (pour restart réserves)
_BA0 = 1.50


# ── Martingale logic ──────────────────────────────────────────────────────────

def _next_stake(ba: float, ls: int, ps: float, ml: int) -> float:
    denom = float((2 ** ml) - 1)
    s = ba / denom if ls == 0 else ps * 2.0
    return min(s, ba)


def _apply_result(
    sim: dict,
    is_win: bool,
    odd: float,
    reserves: float,
) -> tuple[dict, float]:
    sim = copy.deepcopy(sim)
    ba, cb, ls, ps = sim["ba"], sim["cb"], sim["ls"], sim["ps"]
    mode, ml = sim["mode"], sim["ml"]

    if ba <= 0:
        next_bet = ps * 2.0 if ps > 0 else _BA0 / float((2 ** ml) - 1)
        if reserves >= next_bet:
            ba = next_bet
            reserves -= next_bet
            print(f"    🏦 Tirage réserves : {next_bet:.4f}€")
        else:
            print(f"    ⚠️  Réserves insuffisantes pour {sim.get('mode', '?')}")
            return sim, reserves

    stake = _next_stake(ba, ls, ps, ml)

    if is_win:
        ba += stake * (odd - 1.0)
        ls = 0
        if mode == "SAFE" and ba >= cb * 2.0:
            profit = ba - cb
            reserves += profit
            new_base = _BA0 + 0.20 * reserves
            print(f"    💰 DOUBLING ! +{profit:.4f}€ → réserves. Nouvelle base : {new_base:.4f}€")
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
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="ignore")
    tickets = []

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
        day = tid[:10]

        try:
            odd = float(m.group("odd"))
        except ValueError:
            odd = 1.0

        tickets.append({"date": day, "status": status, "odd": odd, "ticket_id": tid})

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

def update(pipeline: str, verdict_path: Path, state: dict) -> dict:
    tickets   = _parse_verdict_file(verdict_path)
    sname     = _STRAT_FOR[pipeline]
    pstate    = state["portfolio"]
    last_upd  = pstate.get("last_updated", "2000-01-01")
    reserves  = pstate["reserves"]

    new_tickets = [t for t in tickets if t["date"] > last_upd and t["status"] != "PENDING"]

    if not new_tickets:
        print(f"  [{pipeline}] rien de nouveau (last_updated={last_upd})")
        return state

    for t in new_tickets:
        is_win = t["status"] == "WIN"
        print(f"  [{pipeline}] {t['date']} | {'✅ WIN' if is_win else '❌ LOSS'} (cote {t['odd']})")
        sim, reserves = _apply_result(pstate["strategies"][sname], is_win, t["odd"], reserves)
        pstate["strategies"][sname] = sim

    pstate["last_updated"] = new_tickets[-1]["date"]
    pstate["reserves"]     = reserves
    return state


def main():
    print("\n============================")
    print("  Mise à jour Martingale")
    print("============================")

    state = _load_state()
    if not state or "portfolio" not in state:
        print("  ⚠️  Fichier d'état introuvable ou incompatible. Aucune mise à jour effectuée.")
        print("     → Initialisez l'état depuis l'onglet Martingale de l'app.")
        return

    for pipeline, path in VERDICT_FILES.items():
        state = update(pipeline, path, state)

    _save_state(state)
    print(f"\n  ✅ État sauvegardé dans {STATE_FILE}")
    print("============================\n")


if __name__ == "__main__":
    main()
