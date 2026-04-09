"""
rebuild_archive.py
------------------
Reconstruit les entrées archive/ manquantes à partir de data/predictions.tsv.

GitHub Actions génère et commite data/predictions.tsv après chaque run.
Ce script découpe ce fichier par date et écrit chaque tranche dans
archive/analyse_YYYY-MM-DD/from_predictions/predictions.tsv.

Aucun appel API. Instantané.

Usage :
    python rebuild_archive.py [--dry-run]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GLOBAL_PREDICTIONS = ROOT / "data" / "predictions.tsv"
ARCHIVE_ROOT = ROOT / "archive"

RUN_DIRNAME = "from_predictions"  # nom fixe du sous-dossier créé par ce script


def _archive_has_predictions(day: str) -> bool:
    """True si un run valide (predictions.tsv) existe déjà pour ce jour."""
    day_dir = ARCHIVE_ROOT / f"analyse_{day}"
    if not day_dir.exists():
        return False
    for run_dir in day_dir.iterdir():
        if run_dir.is_dir() and (run_dir / "predictions.tsv").exists():
            return True
    return False


def _load_predictions_by_day() -> dict[str, list[str]]:
    """Lit data/predictions.tsv et groupe les lignes TSV par date (col 3)."""
    by_day: dict[str, list[str]] = defaultdict(list)
    if not GLOBAL_PREDICTIONS.exists():
        return by_day
    with GLOBAL_PREDICTIONS.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("TSV:"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            day = parts[2].strip()
            by_day[day].append(line.rstrip("\n"))
    return by_day


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    by_day = _load_predictions_by_day()
    if not by_day:
        print(f"[rebuild] {GLOBAL_PREDICTIONS} introuvable ou vide.")
        return

    days = sorted(by_day)
    missing = [d for d in days if not _archive_has_predictions(d)]

    print(f"[rebuild] {len(days)} jours dans predictions.tsv | {len(missing)} à ajouter dans archive/")

    if not missing:
        print("[rebuild] Archive déjà complète.")
        return

    for day in missing:
        lines = by_day[day]
        print(f"[rebuild] {day} — {len(lines)} prédictions", end="")

        if args.dry_run:
            print("  [DRY-RUN]")
            continue

        run_dir = ARCHIVE_ROOT / f"analyse_{day}" / RUN_DIRNAME
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "predictions.tsv").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        print(f"  → {run_dir}")

    if not args.dry_run:
        print(f"\n[rebuild] {len(missing)} jour(s) ajouté(s).")


if __name__ == "__main__":
    main()
