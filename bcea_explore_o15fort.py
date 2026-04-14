"""
Exploration rapide — O15_FT × FORT
Affiche le détail des picks O15_FT au niveau FORT sélectionnés dans l'archive 88 jours.
Objectif : comprendre qui ils sont, d'où viennent les cotes élevées, distribution temporelle.
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services.ticket_optimizer import DEFAULT_ARCHIVE_DIR, discover_datasets

# ─── Chargement verdicts ───────────────────────────────────────────────────
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

# ─── Chargement picks depuis l'archive ────────────────────────────────────
datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)

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
            league      = parts[3].strip()
            home        = parts[4].strip()
            away        = parts[5].strip()
            label       = parts[6].strip()
            score_raw   = parts[8].strip()
            verdict_lbl = parts[9].strip()
            selected    = parts[10].strip()
            odd_raw     = parts[11].strip()
            if "odd=" not in odd_raw:
                continue
            odd   = float(odd_raw.split("odd=")[1].split()[0])
            score = float(score_raw) if score_raw else 0.0
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
            "date":   date,
            "mid":    mid_str,
            "league": league,
            "home":   home,
            "away":   away,
            "label":  label,
            "score":  score,
            "odd":    odd,
            "conf":   verdict_lbl,
            "result": result,
        })

print(f"Total picks sélectionnés chargés : {len(all_picks)}")

# ─── Filtrer O15_FT × FORT ────────────────────────────────────────────────
target = [p for p in all_picks if p["label"] == "O15_FT" and p["conf"] == "FORT"]
wins   = [p for p in target if p["result"] == "WIN"]
losses = [p for p in target if p["result"] == "LOSS"]

print(f"\n{'='*70}")
print(f"  O15_FT × FORT  —  {len(target)} picks  |  WIN={len(wins)}  LOSS={len(losses)}")
if target:
    wr = len(wins) / len(target)
    avg_odd = sum(p["odd"] for p in target) / len(target)
    print(f"  Win rate : {wr:.1%}  |  Cote sys moy : {avg_odd:.3f}")
print(f"{'='*70}")

# ─── Distribution des cotes ───────────────────────────────────────────────
print("\n--- Distribution des cotes système (O15_FT × FORT) ---")
buckets = defaultdict(list)
for p in target:
    b = round(p["odd"] * 2) / 2  # arrondir au 0.5 le plus proche
    buckets[b].append(p)
for b in sorted(buckets):
    ps = buckets[b]
    wr_b = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
    print(f"  cote ~{b:.1f}  :  {len(ps):3d} picks  |  WR={wr_b:.0%}")

# ─── Distribution par date ────────────────────────────────────────────────
print("\n--- Distribution temporelle ---")
by_date = defaultdict(list)
for p in target:
    by_date[p["date"]].append(p)
for d in sorted(by_date):
    ps = by_date[d]
    wr_d = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
    flag = "✓" if wr_d >= 0.5 else "✗"
    print(f"  {d}  :  {len(ps)} picks  WR={wr_d:.0%}  {flag}")

# ─── Distribution par ligue ───────────────────────────────────────────────
print("\n--- Distribution par ligue ---")
by_league = defaultdict(list)
for p in target:
    by_league[p["league"]].append(p)
for lg, ps in sorted(by_league.items(), key=lambda x: -len(x[1])):
    wr_l = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
    print(f"  {lg:<30}  {len(ps):3d} picks  WR={wr_l:.0%}")

# ─── Distribution par score système ──────────────────────────────────────
print("\n--- Distribution par score système (confiance interne) ---")
score_buckets = defaultdict(list)
for p in target:
    b = int(p["score"])
    score_buckets[b].append(p)
for b in sorted(score_buckets):
    ps = score_buckets[b]
    wr_b = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
    avg_odd_b = sum(x["odd"] for x in ps) / len(ps)
    print(f"  score={b}  :  {len(ps):3d} picks  WR={wr_b:.0%}  cote moy={avg_odd_b:.3f}")

# ─── Liste détaillée des picks ────────────────────────────────────────────
print(f"\n--- Détail pick par pick ({len(target)} picks) ---")
print(f"  {'Date':<12} {'Ligue':<22} {'Match':<40} {'Cote':>5} {'Score':>6} {'Résultat'}")
print(f"  {'-'*100}")
for p in sorted(target, key=lambda x: (x["date"], x["odd"])):
    match_str = f"{p['home']} vs {p['away']}"
    res_icon = "WIN ✓" if p["result"] == "WIN" else "LOSS ✗"
    print(f"  {p['date']:<12} {p['league']:<22} {match_str:<40} {p['odd']:>5.2f} {p['score']:>6.1f} {res_icon}")

# ─── Comparaison O15_FT tous niveaux ─────────────────────────────────────
print(f"\n--- Référence : O15_FT par niveau de confiance ---")
conf_order = ["MEGA EXPLOSION", "TRÈS FORT", "FORT PLUS", "FORT", "MOYEN PLUS", "MOYEN", "FAIBLE", "EXPLOSION", "KO"]
o15_all = [p for p in all_picks if p["label"] == "O15_FT"]
by_conf = defaultdict(list)
for p in o15_all:
    by_conf[p["conf"]].append(p)

print(f"  {'Niveau':<20} {'N':>5} {'Win%':>6} {'Cote moy':>9}")
shown = set()
for conf in conf_order:
    if conf in by_conf:
        ps = by_conf[conf]
        wr_c = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
        avg_c = sum(x["odd"] for x in ps) / len(ps)
        print(f"  {conf:<20} {len(ps):>5} {wr_c:>6.1%} {avg_c:>9.3f}")
        shown.add(conf)
for conf, ps in sorted(by_conf.items(), key=lambda x: -len(x[1])):
    if conf not in shown:
        wr_c = sum(1 for x in ps if x["result"] == "WIN") / len(ps)
        avg_c = sum(x["odd"] for x in ps) / len(ps)
        print(f"  {conf:<20} {len(ps):>5} {wr_c:>6.1%} {avg_c:>9.3f}")
