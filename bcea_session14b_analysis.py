"""
BCEA Session 14b — Analyses complémentaires
  A. O25_FT MEGA EXPLOSION uniquement — win rate + EV par niveau de décote
  B. Picks à cote sys ≥1.80 par niveau de confiance (MEGA EXPLOSION vs autres)
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
DECOTES = [0.95, 0.90, 0.85, 0.80]

# ─── Chargement (même logique sessions 13/14) ─────────────────────────────

from services.ticket_optimizer import DEFAULT_ARCHIVE_DIR, discover_datasets

print("Chargement des données sur 88 jours...")

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

datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
print(f"  {len(datasets)} jours, {len(verdict_global)} picks avec résultat")

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
            mid_str     = parts[1].strip()
            date        = parts[2].strip()
            label       = parts[6].strip()
            verdict_lbl = parts[9].strip()   # MEGA EXPLOSION, FORT, etc.
            selected    = parts[10].strip()
            odd_raw     = parts[11].strip()
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

        if selected != "1":
            continue

        all_picks.append({
            "date":    date,
            "mid":     mid_str,
            "label":   label,
            "odd_sys": odd,
            "conf":    verdict_lbl,   # niveau de confiance
            "result":  result,
        })

print(f"  {len(all_picks)} picks sélectionnés chargés\n")


# ─── Helpers ──────────────────────────────────────────────────────────────

def stats(picks: list[dict], decote: float) -> dict:
    n = len(picks)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": 0, "pnl": 0, "roi": 0, "ev": 0, "avg_odd": 0}
    wins = sum(1 for p in picks if p["result"] == "WIN")
    wr = wins / n
    avg_odd = sum(p["odd_sys"] for p in picks) / n
    pnl = sum(
        (p["odd_sys"] * decote - 1) * MISE if p["result"] == "WIN" else -MISE
        for p in picks
    )
    return {
        "n": n, "wins": wins, "wr": wr,
        "pnl": pnl, "roi": pnl / (n * MISE),
        "ev": wr * avg_odd * decote - 1,
        "avg_odd": avg_odd,
    }

def breakeven_pct(picks: list[dict]) -> float | None:
    if not picks:
        return None
    n = len(picks)
    wr = sum(1 for p in picks if p["result"] == "WIN") / n
    avg_odd = sum(p["odd_sys"] for p in picks) / n
    prod = wr * avg_odd
    if prod <= 0:
        return None
    return (1.0 - 1.0 / prod) * 100.0

def decote_row(d: float, s: dict) -> str:
    ok = "OUI ✓" if s["ev"] >= 0 else "non"
    pct = int(round((1 - d) * 100))
    return (f"{pct:>9}% | {s['pnl']:>9.0f}€ | {s['roi']*100:>7.1f}% | "
            f"{s['ev']:>+8.4f} | {ok}")


# ─── Output ───────────────────────────────────────────────────────────────

lines: list[str] = []

def pr(*args):
    s = " ".join(str(a) for a in args)
    print(s)
    lines.append(s)

def sep(title: str):
    pr("\n" + "=" * 78)
    pr(f"  {title}")
    pr("=" * 78)


pr("=" * 78)
pr("BCEA — Session 14b — Analyses complémentaires (88 jours)")
pr("=" * 78)


# ══════════════════════════════════════════════════════════════════════════
# ANALYSE A — O25_FT par niveau de confiance
# ══════════════════════════════════════════════════════════════════════════

sep("ANALYSE A — O25_FT — Décomposition par niveau de confiance")

o25 = [p for p in all_picks if "O25_FT" in p["label"] or "OVER25" in p["label"]]
pr(f"\nO25_FT total : {len(o25)} picks")

# Grouper par niveau de confiance
by_conf: dict[str, list[dict]] = defaultdict(list)
for p in o25:
    by_conf[p["conf"]].append(p)

pr(f"\n{'Niveau':>20} | {'N':>5} | {'Win%':>6} | {'Cote moy sys':>12} | {'Seuil décote':>13} | Verdict")
pr("-" * 85)

conf_order = ["MEGA EXPLOSION", "TRÈS FORT", "FORT", "MOYEN PLUS", "MOYEN", "FAIBLE"]
for conf in conf_order:
    subset = by_conf.get(conf, [])
    if not subset:
        continue
    n = len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    wr = wins / n
    avg_odd = sum(p["odd_sys"] for p in subset) / n
    be = breakeven_pct(subset)
    seuil = f"{be:.1f}%" if be is not None else "N/A"
    prod = wr * avg_odd
    if be is None or be < 0:
        verd = "Jamais profitable"
    elif be <= 3:
        verd = "Exchange only"
    elif be <= 10:
        verd = "Pinnacle possible"
    elif be <= 20:
        verd = "Atteignable"
    else:
        verd = "Confortable"
    pr(f"{conf:>20} | {n:>5} | {wr*100:>5.1f}% | {avg_odd:>12.3f} | {seuil:>13} | {verd}")

pr("")

# Focus MEGA EXPLOSION
mega_o25 = by_conf.get("MEGA EXPLOSION", [])
if mega_o25:
    pr(f"\n### O25_FT MEGA EXPLOSION ({len(mega_o25)} picks) — détail décote")
    pr(f"{'Décote':>10} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8} | Profitable?")
    pr("-" * 55)
    for d in DECOTES:
        s = stats(mega_o25, d)
        pr(decote_row(d, s))
    be = breakeven_pct(mega_o25)
    pr(f"\n  Win rate : {sum(1 for p in mega_o25 if p['result']=='WIN')/len(mega_o25)*100:.1f}%")
    pr(f"  Cote moy sys : {sum(p['odd_sys'] for p in mega_o25)/len(mega_o25):.3f}")
    pr(f"  Seuil décote : {be:.1f}% → {'Atteignable' if be and 0<=be<=20 else 'Hors reach' if be and be > 20 else 'Jamais profitable'}")
else:
    pr("  Aucun pick O25_FT MEGA EXPLOSION dans l'archive.")

# Toutes confiances > FORT
fort_plus = [p for p in o25 if p["conf"] in ("MEGA EXPLOSION", "TRÈS FORT", "FORT")]
if fort_plus:
    pr(f"\n### O25_FT MEGA EXPLOSION + TRÈS FORT + FORT ({len(fort_plus)} picks)")
    pr(f"{'Décote':>10} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8} | Profitable?")
    pr("-" * 55)
    for d in DECOTES:
        s = stats(fort_plus, d)
        pr(decote_row(d, s))
    be = breakeven_pct(fort_plus)
    wins = sum(1 for p in fort_plus if p["result"] == "WIN")
    avg_odd = sum(p["odd_sys"] for p in fort_plus) / len(fort_plus)
    pr(f"\n  Win rate : {wins/len(fort_plus)*100:.1f}% | Cote moy : {avg_odd:.3f}")
    pr(f"  Seuil décote : {be:.1f}%" if be is not None else "  Seuil : N/A")


# ══════════════════════════════════════════════════════════════════════════
# ANALYSE B — Picks ≥1.80 par niveau de confiance
# ══════════════════════════════════════════════════════════════════════════

sep("ANALYSE B — Picks à cote sys ≥1.80 — Décomposition par niveau de confiance")

high_odds = [p for p in all_picks if p["odd_sys"] >= 1.80]
pr(f"\nPicks ≥1.80 total : {len(high_odds)}")

# Distribution par niveau de confiance
by_conf_high: dict[str, list[dict]] = defaultdict(list)
for p in high_odds:
    by_conf_high[p["conf"]].append(p)

pr(f"\n{'Niveau':>20} | {'N':>5} | {'Win%':>6} | {'Cote moy sys':>12} | {'Seuil décote':>13} | Verdict")
pr("-" * 85)

for conf in conf_order:
    subset = by_conf_high.get(conf, [])
    if not subset:
        continue
    n = len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    wr = wins / n
    avg_odd = sum(p["odd_sys"] for p in subset) / n
    be = breakeven_pct(subset)
    seuil = f"{be:.1f}%" if be is not None else "N/A"
    if be is None or be < 0:
        verd = "Jamais profitable"
    elif be <= 3:
        verd = "Exchange only"
    elif be <= 10:
        verd = "Pinnacle possible"
    elif be <= 20:
        verd = "Atteignable"
    else:
        verd = "Confortable"
    pr(f"{conf:>20} | {n:>5} | {wr*100:>5.1f}% | {avg_odd:>12.3f} | {seuil:>13} | {verd}")

pr("")

# Détail par niveau pour MEGA EXPLOSION et TRÈS FORT
for conf in ["MEGA EXPLOSION", "TRÈS FORT", "FORT"]:
    subset = by_conf_high.get(conf, [])
    if not subset:
        continue
    pr(f"\n### ≥1.80 — {conf} ({len(subset)} picks)")
    pr(f"{'Décote':>10} | {'P&L':>10} | {'ROI':>8} | {'EV/€':>8} | Profitable?")
    pr("-" * 55)
    for d in DECOTES:
        s = stats(subset, d)
        pr(decote_row(d, s))
    be = breakeven_pct(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    avg_odd = sum(p["odd_sys"] for p in subset) / len(subset)
    pr(f"\n  Win rate : {wins/len(subset)*100:.1f}% | Cote moy : {avg_odd:.3f}")
    if be is not None:
        pr(f"  Seuil décote : {be:.1f}%")


# ══════════════════════════════════════════════════════════════════════════
# ANALYSE C — Croisement : type × confiance (tous picks)
# ══════════════════════════════════════════════════════════════════════════

sep("ANALYSE C — Segments les plus profitables (produit win_rate × cote ≥ 1)")

pr(f"\n{'Type × Confiance':>35} | {'N':>5} | {'Win%':>6} | {'Cote moy':>8} | {'WR×C':>6} | Seuil décote")
pr("-" * 90)

def label_type(label: str) -> str:
    if "HT05" in label or "HT_OVER05" in label: return "HT05"
    if "O15_FT" in label or "OVER15_FT" in label: return "O15_FT"
    if "O25_FT" in label or "OVER25" in label: return "O25_FT"
    if "HT1X" in label or "HT_1X" in label: return "HT1X_HOME"
    if "TEAM1_SCORE" in label: return "TEAM1_SCORE_FT"
    if "TEAM2_WIN" in label: return "TEAM2_WIN_FT"
    return "AUTRE"

# Grouper par (type, confiance)
combos: dict[tuple, list[dict]] = defaultdict(list)
for p in all_picks:
    combos[(label_type(p["label"]), p["conf"])].append(p)

# Trier par produit WR×C décroissant
results = []
for (ltype, conf), subset in combos.items():
    if len(subset) < 20:  # ignorer les petits échantillons
        continue
    n = len(subset)
    wins = sum(1 for p in subset if p["result"] == "WIN")
    wr = wins / n
    avg_odd = sum(p["odd_sys"] for p in subset) / n
    product = wr * avg_odd
    be = breakeven_pct(subset)
    results.append((ltype, conf, n, wr, avg_odd, product, be))

results.sort(key=lambda x: -x[5])  # tri par produit WR×C

for ltype, conf, n, wr, avg_odd, product, be in results:
    seuil = f"{be:.1f}%" if be is not None else "N/A"
    marker = " ◄" if be is not None and be >= 0 else ""
    pr(f"{ltype+' × '+conf:>35} | {n:>5} | {wr*100:>5.1f}% | {avg_odd:>8.3f} | {product:>6.3f} | {seuil}{marker}")


# Sauvegarde
output_path = OUTPUT_DIR / "bcea_session14b_analysis.txt"
output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ Sauvegardé : {output_path}")
