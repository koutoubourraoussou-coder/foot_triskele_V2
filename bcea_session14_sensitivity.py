"""
BCEA Session 14 — Backtest de sensibilité décote bookmaker
Simule le P&L avec décote 5%, 10%, 15%, 20% par type de pari et tranche de cote
Même source de données que Session 13 : archive complète (88 jours)
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "data" / "optimizer"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MISE = 7.0
DECOTES = [0.95, 0.90, 0.85, 0.80]  # décote 5%, 10%, 15%, 20%

# ---------------------------------------------------------------------------
# Chargement — même logique que bcea_session13_backtests.py
# ---------------------------------------------------------------------------

from services.ticket_optimizer import DEFAULT_ARCHIVE_DIR, discover_datasets

print("Chargement des données sur 88 jours...")

# Étape 1 : verdict global depuis data/verdict_post_analyse.txt
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
        selected = parts[9].strip()
        result   = parts[10].strip()
        if selected == "1" and result in ("WIN", "LOSS"):
            verdict_global[(mid_str, label)] = result
    except (ValueError, IndexError):
        continue

print(f"  Verdict global : {len(verdict_global)} picks avec résultat")

# Étape 2 : parcourir l'archive et joindre
datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
print(f"  {len(datasets)} jours dans l'archive")

all_picks: list[dict] = []
seen: set[tuple] = set()

for ds in datasets:
    if not ds.predictions_tsv.exists():
        continue
    for line in ds.predictions_tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("TSV:"):
            continue
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            mid_str  = parts[1].strip()
            date     = parts[2].strip()
            label    = parts[6].strip()
            selected = parts[10].strip()
            odd_raw  = parts[11].strip()
            if "odd=" not in odd_raw:
                continue
            odd = float(odd_raw.split("odd=")[1].split()[0])
        except (ValueError, IndexError):
            continue

        result = verdict_global.get((mid_str, label))
        if result is None:
            continue

        key = (mid_str, label)
        if key in seen:
            continue
        seen.add(key)

        all_picks.append({
            "date":     date,
            "mid":      mid_str,
            "label":    label,
            "odd_sys":  odd,
            "selected": selected == "1",
            "result":   result,
        })

selected_picks = [p for p in all_picks if p["selected"]]
print(f"  {len(all_picks)} picks totaux, {len(selected_picks)} sélectionnés\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bet_type(label: str) -> str:
    if "HT05" in label or "HT_OVER05" in label:
        return "HT05"
    if "O15_FT" in label or "OVER15_FT" in label:
        return "O15_FT"
    if "O25_FT" in label or "OVER25_FT" in label:
        return "O25_FT"
    if "HT1X" in label or "HT_1X" in label:
        return "HT1X_HOME"
    if "TEAM1_SCORE_FT" in label or "TEAM1_SCORE" in label:
        return "TEAM1_SCORE_FT"
    if "TEAM2_WIN" in label:
        return "TEAM2_WIN_FT"
    return "AUTRE"


def compute_stats(picks: list[dict], decote: float) -> dict:
    n = len(picks)
    if n == 0:
        return {"n": 0, "win_rate": 0, "pnl": 0, "roi": 0, "ev": 0}
    wins = sum(1 for p in picks if p["result"] == "WIN")
    win_rate = wins / n
    pnl = sum(
        (p["odd_sys"] * decote - 1) * MISE if p["result"] == "WIN" else -MISE
        for p in picks
    )
    total_mise = n * MISE
    avg_odd = sum(p["odd_sys"] for p in picks) / n
    ev = win_rate * avg_odd * decote - 1
    return {
        "n": n,
        "win_rate": win_rate,
        "pnl": pnl,
        "roi": pnl / total_mise,
        "ev": ev,
    }


def breakeven_decote_pct(picks: list[dict]) -> float | None:
    """Retourne le % de décote maximum pour EV≥0, ou None si impossible."""
    if not picks:
        return None
    n = len(picks)
    wins = sum(1 for p in picks if p["result"] == "WIN")
    win_rate = wins / n
    avg_odd = sum(p["odd_sys"] for p in picks) / n
    # EV = win_rate * avg_odd * d - 1 = 0 → d = 1/(win_rate*avg_odd)
    product = win_rate * avg_odd
    if product <= 0:
        return None
    d_needed = 1.0 / product  # facteur multiplicatif nécessaire
    # décote% = (1 - d_needed) * 100 : positif = décote bookmaker tolérée
    return (1.0 - d_needed) * 100.0


def verdict_str(be: float | None) -> str:
    if be is None:
        return "Jamais profitable"
    if be < 0:
        return "Jamais profitable (win rate × cote < 1)"
    if be <= 3:
        return f"Seuil ≤{be:.1f}% — exchange/no-vig seulement"
    if be <= 8:
        return f"Seuil ≤{be:.1f}% — bookmaker asiatique (Pinnacle)"
    if be <= 15:
        return f"Seuil ≤{be:.1f}% — possible avec line shopping"
    if be <= 20:
        return f"Seuil ≤{be:.1f}% — en limite de la décote actuelle"
    return f"Seuil ≤{be:.1f}% — confortable"


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

lines = []

def pr(*args):
    s = " ".join(str(a) for a in args)
    print(s)
    lines.append(s)

def sep(title=""):
    pr("\n" + "=" * 78)
    pr(f"  {title}")
    pr("=" * 78)

pr("=" * 78)
pr("BCEA — Session 14 — Backtest de sensibilité décote bookmaker")
pr(f"Source : archive 88 jours | Picks sélectionnés : {len(selected_picks)} | Mise : {MISE}€")
pr("=" * 78)

# ── Partie 1 : Global ──────────────────────────────────────────────────────
sep("PARTIE 1 — Sensibilité P&L global")
pr(f"\n{'Décote':>10} | {'Picks':>6} | {'Win%':>6} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8}")
pr("-" * 60)
for d in DECOTES:
    s = compute_stats(selected_picks, d)
    pr(f"{int(round((1-d)*100)):>9}% | {s['n']:>6} | {s['win_rate']*100:>5.1f}% | "
       f"{s['pnl']:>9.0f}€ | {s['roi']*100:>7.1f}% | {s['ev']:>+8.4f}")

be = breakeven_decote_pct(selected_picks)
pr(f"\n→ Seuil de rentabilité global : {verdict_str(be)}")

# ── Partie 2 : Par type de pari ────────────────────────────────────────────
sep("PARTIE 2 — Sensibilité par type de pari")

by_type: dict[str, list[dict]] = defaultdict(list)
for p in selected_picks:
    by_type[bet_type(p["label"])].append(p)

types_order = ["HT05", "O15_FT", "HT1X_HOME", "TEAM1_SCORE_FT", "O25_FT", "TEAM2_WIN_FT", "AUTRE"]

for btype in types_order:
    subset = by_type.get(btype, [])
    if not subset:
        continue
    avg_odd = sum(p["odd_sys"] for p in subset) / len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    pr(f"\n### {btype}  ({len(subset)} picks | win {wins/len(subset)*100:.0f}% | cote moy sys {avg_odd:.3f})")
    pr(f"{'Décote':>10} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8} | Profitable?")
    pr("-" * 60)
    for d in DECOTES:
        s = compute_stats(subset, d)
        ok = "OUI ✓" if s["ev"] >= 0 else "non"
        pr(f"{int(round((1-d)*100)):>9}% | {s['pnl']:>9.0f}€ | {s['roi']*100:>7.1f}% | {s['ev']:>+8.4f} | {ok}")
    be = breakeven_decote_pct(subset)
    pr(f"  → {verdict_str(be)}")

# ── Partie 3 : Par tranche de cote système ────────────────────────────────
sep("PARTIE 3 — Sensibilité par tranche de cote système")

tranches = [
    ("1.00–1.10", 1.00, 1.10),
    ("1.10–1.20", 1.10, 1.20),
    ("1.20–1.30", 1.20, 1.30),
    ("1.30–1.40", 1.30, 1.40),
    ("1.40–1.55", 1.40, 1.55),
    ("1.55–1.80", 1.55, 1.80),
    ("≥1.80",     1.80, 99.0),
]

for label, lo, hi in tranches:
    subset = [p for p in selected_picks if lo <= p["odd_sys"] < hi]
    if not subset:
        continue
    avg_odd = sum(p["odd_sys"] for p in subset) / len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    pr(f"\n### Cote sys {label}  ({len(subset)} picks | win {wins/len(subset)*100:.0f}% | cote moy {avg_odd:.3f})")
    pr(f"{'Décote':>10} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8} | Profitable?")
    pr("-" * 60)
    for d in DECOTES:
        s = compute_stats(subset, d)
        ok = "OUI ✓" if s["ev"] >= 0 else "non"
        pr(f"{int(round((1-d)*100)):>9}% | {s['pnl']:>9.0f}€ | {s['roi']*100:>7.1f}% | {s['ev']:>+8.4f} | {ok}")
    be = breakeven_decote_pct(subset)
    pr(f"  → {verdict_str(be)}")

# ── Partie 4 : Tableau récapitulatif ──────────────────────────────────────
sep("PARTIE 4 — Tableau récapitulatif des seuils de rentabilité")
pr(f"\n{'Segment':>22} | {'N':>5} | {'Win%':>5} | {'Cote moy':>8} | {'Seuil décote':>12} | Verdict")
pr("-" * 95)

segments = [("TOUS", selected_picks)]
for btype in types_order:
    if by_type.get(btype):
        segments.append((btype, by_type[btype]))
for label, lo, hi in tranches:
    subset = [p for p in selected_picks if lo <= p["odd_sys"] < hi]
    if subset:
        segments.append((f"cote {label}", subset))

for seg_label, subset in segments:
    if not subset:
        continue
    n = len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    wr = wins / n
    avg_odd = sum(p["odd_sys"] for p in subset) / n
    be = breakeven_decote_pct(subset)
    seuil = f"{be:.1f}%" if be is not None else "N/A"
    verd = verdict_str(be)
    pr(f"{seg_label:>22} | {n:>5} | {wr*100:>4.0f}% | {avg_odd:>8.3f} | {seuil:>12} | {verd}")

# Sauvegarde
output_path = OUTPUT_DIR / "bcea_session14_sensitivity.txt"
output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ Sauvegardé : {output_path}")
