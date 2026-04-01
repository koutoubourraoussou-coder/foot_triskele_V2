"""
compute_label_thresholds.py
----------------------------
Calcule, pour chaque bet_key, le label minimum permettant
d'atteindre >= MIN_WINRATE de taux de réussite.

Données source : data/verdict_post_analyse.txt
Sortie        : data/min_level_by_bet.json

Correspondance des commentaires :
  WIN          → aurait été / a été gagné
  BAD_NO_BET   → non joué mais aurait été WIN (mauvais de ne pas avoir joué)
  LOSS         → aurait été / a été perdu
  GOOD_NO_BET  → non joué et aurait été LOSS (bon de ne pas avoir joué)
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

MIN_WINRATE = 0.73
MIN_SAMPLE  = 20       # taille minimale pour qu'un label soit considéré fiable

VERDICT_FILE = Path("data/verdict_post_analyse.txt")
OUTPUT_FILE  = Path("data/min_level_by_bet.json")

LEVELS = [
    "KO",
    "FAIBLE",
    "MOYEN",
    "MOYEN PLUS",
    "FORT",
    "FORT PLUS",
    "TRÈS FORT",
    "EXPLOSION",
    "MEGA EXPLOSION",
]

WIN_COMMENTS  = {"WIN", "BAD_NO_BET"}
LOSS_COMMENTS = {"LOSS", "GOOD_NO_BET"}


def _parse_verdict_file() -> dict[tuple[str, str], list[bool]]:
    """(bet_key, label) -> liste de booléens (True=WIN, False=LOSS)."""
    data: dict[tuple[str, str], list[bool]] = defaultdict(list)

    with VERDICT_FILE.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue

            bet_key = parts[5].strip()
            label   = parts[8].strip()
            comment = parts[10].strip().upper()

            if comment in WIN_COMMENTS:
                data[(bet_key, label)].append(True)
            elif comment in LOSS_COMMENTS:
                data[(bet_key, label)].append(False)

    return data


def compute_thresholds() -> dict[str, dict]:
    data = _parse_verdict_file()

    # Agrégation par (bet_key, label)
    stats: dict[str, dict[str, dict]] = defaultdict(dict)
    for (bet_key, label), outcomes in data.items():
        if label not in LEVELS:
            continue
        wins  = sum(outcomes)
        total = len(outcomes)
        stats[bet_key][label] = {
            "wins":     wins,
            "total":    total,
            "winrate":  wins / total if total else 0.0,
        }

    result: dict[str, dict] = {}

    for bet_key, by_label in stats.items():
        # Cherche le label le plus bas avec winrate >= MIN_WINRATE
        chosen_label = None
        chosen_stats = None
        for level in LEVELS:
            s = by_label.get(level)
            if s is None:
                continue
            if s["total"] >= MIN_SAMPLE and s["winrate"] >= MIN_WINRATE:
                chosen_label = level
                chosen_stats = s
                break  # Premier (le plus bas) qui passe le seuil

        result[bet_key] = {
            "min_level": chosen_label,        # None si aucun label n'atteint le seuil
            "stats": {
                lv: {
                    "wins":    s["wins"],
                    "total":   s["total"],
                    "winrate": round(s["winrate"], 4),
                }
                for lv, s in sorted(
                    by_label.items(),
                    key=lambda kv: LEVELS.index(kv[0]) if kv[0] in LEVELS else 99,
                )
            },
        }

    return result


def main() -> None:
    result = compute_thresholds()

    # Affichage lisible
    print(f"\n{'='*70}")
    print(f"  SEUILS DYNAMIQUES  (MIN_WINRATE = {MIN_WINRATE:.0%})")
    print(f"{'='*70}\n")

    for bet_key in sorted(result):
        info = result[bet_key]
        ml   = info["min_level"] or "— AUCUN —"
        print(f"  {bet_key:<22}  seuil minimum : {ml}")
        for lv, s in info["stats"].items():
            marker = " ◀" if lv == info["min_level"] else ""
            pct    = s["winrate"] * 100
            bar    = "✅" if pct >= MIN_WINRATE * 100 else "❌"
            print(f"    {bar} {lv:<18} {pct:5.1f}%  ({s['wins']:>4}W / {s['total']:>4} matchs){marker}")
        print()

    # Export JSON
    # Sérialise min_level (None → null)
    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Seuils écrits dans {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
