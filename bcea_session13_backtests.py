"""
bcea_session13_backtests.py
---------------------------
Backtests demandés par la Session 12 :
  1. Win rate par tranche de cote système sur 88 jours (archive complète)
  2. Flat betting + Kelly sur picks à cote système ≥1.72 sur 88 jours
  3. Décote réelle estimée par type de pari (HT05, HT1X, O15, TEAM1_SCORE, etc.)
  4. Flat betting SAFE uniquement (HT05 + O15_FT) sur 88 jours

Résultats dans :
  data/optimizer/bcea_session13_backtests.txt
  equipe/reunions/BCEA_2026-04-08_session_13_table.md
"""

from __future__ import annotations
import sys, random, tempfile
from pathlib import Path
from collections import defaultdict
import statistics

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT_TXT = ROOT / "data/optimizer/bcea_session13_backtests.txt"
OUT_MD  = ROOT / "equipe/reunions/BCEA_2026-04-08_session_13_table.md"
OUT_TXT.parent.mkdir(parents=True, exist_ok=True)

lines_out: list[str] = []

def pr(*args):
    s = " ".join(str(a) for a in args)
    print(s, flush=True)
    lines_out.append(s)

def sep(title=""):
    bar = "=" * 70
    pr(f"\n{bar}\n  {title}\n{bar}")


# ─── Charger picks avec cote + résultat depuis l'archive complète (88 jours) ─

pr("Chargement des données sur 88 jours...")

from services.ticket_optimizer import (
    DEFAULT_ARCHIVE_DIR, discover_datasets,
    _parse_verdict_file, _enrich_verdict_map_with_results,
)

datasets = discover_datasets(DEFAULT_ARCHIVE_DIR, max_days=None)
pr(f"  {len(datasets)} jours dans l'archive")

# Pour chaque jour : charger predictions.tsv (cotes) + verdict (résultats)
# Un pick = (date, match_id, label, cote_système, result WIN/LOSS, label_type)

# Étape 1 : charger le verdict global (match_id_str, label) → result
verdict_global: dict[tuple, str] = {}
verdict_path = ROOT / "data/verdict_post_analyse.txt"
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

pr(f"  Verdict global : {len(verdict_global)} picks avec résultat")

# Étape 2 : parcourir les predictions.tsv de l'archive et joindre
all_picks: list[dict] = []

for ds in datasets:
    if not ds.predictions_tsv.exists():
        continue
    for line in ds.predictions_tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("TSV:"):
            continue
        # Format : TSV:\tmatch_id\tdate\tleague\thome\taway\tlabel_type\tlabel_name\tscore\tverdict_label\tis_selected\todd=X fixture=Y\ttime
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

        all_picks.append({
            "date":     date,
            "mid":      mid_str,
            "label":    label,
            "odd_sys":  odd,
            "selected": selected == "1",
            "result":   result,
        })

pr(f"  {len(all_picks)} picks avec cote + résultat chargés\n")

# Filtrer uniquement les picks sélectionnés pour les backtests financiers
selected_picks = [p for p in all_picks if p["selected"]]
pr(f"  dont {len(selected_picks)} sélectionnés pour ticket\n")

MISE  = 7.0
DECOTE = 0.80
P_EST = 0.73


# ─── 1. WIN RATE PAR TRANCHE DE COTE SYSTÈME ─────────────────────────────────

sep("BACKTEST 1 — WIN RATE PAR TRANCHE DE COTE SYSTÈME (tous picks sélectionnés)")

tranches = [(1.0, 1.10), (1.10, 1.20), (1.20, 1.30), (1.30, 1.40),
            (1.40, 1.55), (1.55, 1.80), (1.80, 9.99)]

pr(f"{'Tranche cote sys':>20} {'Cote réelle':>12} {'Picks':>7} {'Win%':>7} {'EV/€':>8} {'P&L 7€':>10}")
pr("-" * 72)

tranche_data = []
for lo, hi in tranches:
    subset = [p for p in selected_picks if lo <= p["odd_sys"] < hi]
    if not subset:
        continue
    wins   = sum(1 for p in subset if p["result"] == "WIN")
    w_pct  = wins / len(subset)
    avg_odd_real = statistics.mean(p["odd_sys"] * DECOTE for p in subset)
    ev     = w_pct * avg_odd_real - 1  # EV par € misé
    pnl    = sum(((p["odd_sys"] * DECOTE - 1) * MISE if p["result"] == "WIN" else -MISE) for p in subset)
    label  = f"{lo:.2f} – {hi:.2f}" if hi < 9 else f"≥ {lo:.2f}"
    cote_r = f"~{avg_odd_real:.2f}"
    pr(f"{label:>20} {cote_r:>12} {len(subset):>7} {w_pct*100:>6.0f}% {ev:>+8.3f} {pnl:>+10.0f}€")
    tranche_data.append({"label": label, "n": len(subset), "w_pct": w_pct,
                         "avg_odd_real": avg_odd_real, "ev": ev, "pnl": pnl})

pr()
pr("EV>0 = profitable | EV<0 = structurellement perdant même avec ce win rate")
pr(f"Seuil break-even théorique : cote réelle = 1/win_rate")


# ─── 2. FLAT BETTING + KELLY SUR PICKS À COTE SYSTÈME ≥1.72 (88 JOURS) ──────

sep("BACKTEST 2 — PICKS À COTE SYSTÈME ≥1.72 (cote réelle ≥1.38) — 88 JOURS")

high_picks = [p for p in selected_picks if p["odd_sys"] >= 1.72]
pr(f"Picks disponibles (cote sys ≥1.72) : {len(high_picks)} sur {len(selected_picks)} ({len(high_picks)/len(selected_picks)*100:.1f}%)")

by_date_high = defaultdict(list)
for p in high_picks:
    by_date_high[p["date"]].append(p)

pr(f"Jours avec au moins 1 pick : {len(by_date_high)}")
pr(f"Moy picks/jour (jours actifs) : {len(high_picks)/max(1,len(by_date_high)):.1f}")
pr()

# 2a. Flat betting
wins_h  = sum(1 for p in high_picks if p["result"] == "WIN")
losses_h = sum(1 for p in high_picks if p["result"] == "LOSS")
w_pct_h = wins_h / len(high_picks) if high_picks else 0
pnl_flat_h = sum(((p["odd_sys"] * DECOTE - 1) * MISE if p["result"] == "WIN" else -MISE) for p in high_picks)
mise_tot_h = len(high_picks) * MISE
roi_h = pnl_flat_h / mise_tot_h * 100 if mise_tot_h else 0

pr(f"--- Flat betting (7€ fixe) ---")
pr(f"Win rate : {wins_h}/{len(high_picks)} = {w_pct_h*100:.0f}%")
pr(f"P&L net  : {pnl_flat_h:+.0f}€  sur {mise_tot_h:.0f}€ misés")
pr(f"ROI      : {roi_h:+.1f}%")

# 2b. Kelly demi
pr()
pr(f"--- Kelly ×0.5 ---")
bankroll_k = 600.0
history_k  = []
for p in high_picks:
    b = p["odd_sys"] * DECOTE - 1
    if b <= 0:
        continue
    kelly = max(0, (w_pct_h * b - (1 - w_pct_h)) / b) * 0.5
    kelly = min(kelly, 0.20)
    mise_k = bankroll_k * kelly
    if mise_k < 0.5:
        continue
    if p["result"] == "WIN":
        bankroll_k += mise_k * b
    else:
        bankroll_k -= mise_k
    history_k.append(bankroll_k)
    if bankroll_k <= 0:
        pr("  → RUINE")
        break

peak_k = 600.0
max_dd_k = 0.0
for bk in history_k:
    if bk > peak_k: peak_k = bk
    if peak_k - bk > max_dd_k: max_dd_k = peak_k - bk

pr(f"Bankroll finale : {bankroll_k:.0f}€  (départ 600€)")
pr(f"P&L net Kelly   : {bankroll_k - 600:+.0f}€")
pr(f"Drawdown max    : -{max_dd_k:.0f}€")


# ─── 3. DÉCOTE RÉELLE PAR TYPE DE PARI ───────────────────────────────────────

sep("BACKTEST 3 — WIN RATE PAR TYPE DE PARI (88 JOURS, tous picks sélectionnés)")

by_label = defaultdict(list)
for p in selected_picks:
    by_label[p["label"]].append(p)

pr(f"{'Type de pari':<20} {'Picks':>7} {'Win%':>7} {'Cote sys moy':>14} {'Cote réelle':>12} {'Break-even':>12} {'EV':>8}")
pr("-" * 85)

label_data = []
for label in sorted(by_label, key=lambda l: -len(by_label[l])):
    subset = by_label[label]
    if len(subset) < 5:
        continue
    wins = sum(1 for p in subset if p["result"] == "WIN")
    w_pct = wins / len(subset)
    avg_sys  = statistics.mean(p["odd_sys"] for p in subset)
    avg_real = avg_sys * DECOTE
    breakeven = 1 / w_pct if w_pct > 0 else 99
    ev = w_pct * avg_real - 1
    pr(f"{label:<20} {len(subset):>7} {w_pct*100:>6.0f}% {avg_sys:>14.2f} {avg_real:>12.2f} {breakeven:>12.2f} {ev:>+8.3f}")
    label_data.append({"label": label, "n": len(subset), "w_pct": w_pct,
                        "avg_real": avg_real, "breakeven": breakeven, "ev": ev})

pr()
pr("Break-even = cote réelle minimale pour être profitable avec ce win rate")
pr("EV > 0 = profitable | EV < 0 = perdant")


# ─── 4. FLAT BETTING SAFE UNIQUEMENT (HT05 + O15_FT) ────────────────────────

sep("BACKTEST 4 — FLAT BETTING SAFE UNIQUEMENT (HT05 + O15_FT) — 88 JOURS")

safe_labels = {"HT05", "O15_FT"}
safe_picks = [p for p in selected_picks if p["label"] in safe_labels]

pr(f"Picks SAFE (HT05 + O15_FT) : {len(safe_picks)}")

by_date_safe = defaultdict(list)
for p in safe_picks:
    by_date_safe[p["date"]].append(p)

pr(f"Jours couverts : {len(by_date_safe)}")
pr()

# Stats par type
for lbl in ["HT05", "O15_FT"]:
    sub = [p for p in safe_picks if p["label"] == lbl]
    if not sub: continue
    wins_s = sum(1 for p in sub if p["result"] == "WIN")
    w_pct_s = wins_s / len(sub)
    avg_r = statistics.mean(p["odd_sys"] * DECOTE for p in sub)
    ev_s = w_pct_s * avg_r - 1
    pnl_s = sum(((p["odd_sys"] * DECOTE - 1) * MISE if p["result"] == "WIN" else -MISE) for p in sub)
    pr(f"{lbl}: {len(sub)} picks | win {w_pct_s*100:.0f}% | cote réelle moy {avg_r:.2f} | EV {ev_s:+.3f} | P&L {pnl_s:+.0f}€")

pr()

# Flat betting SAFE combinés, jour par jour
bankroll_safe = 600.0
daily_safe = []
cumul_safe = 0.0
wins_safe = losses_safe = 0

pr(f"{'Date':<14} {'Picks':>6} {'W':>4} {'L':>4} {'P&L jour':>10} {'Cumulé':>10}")
pr("-" * 56)

for date in sorted(by_date_safe.keys()):
    picks = by_date_safe[date]
    w = sum(1 for p in picks if p["result"] == "WIN")
    l = sum(1 for p in picks if p["result"] == "LOSS")
    pnl_j = sum(((p["odd_sys"] * DECOTE - 1) * MISE if p["result"] == "WIN" else -MISE) for p in picks)
    cumul_safe += pnl_j
    wins_safe += w
    losses_safe += l
    daily_safe.append(pnl_j)
    pr(f"{date:<14} {len(picks):>6} {w:>4} {l:>4} {pnl_j:>+10.1f}€ {cumul_safe:>+10.1f}€")

total_safe = len(safe_picks)
mise_safe  = total_safe * MISE
roi_safe   = cumul_safe / mise_safe * 100 if mise_safe else 0
peak_s = 0.0
c = 0.0
max_dd_s = 0.0
for pnl in daily_safe:
    c += pnl
    if c > peak_s: peak_s = c
    if peak_s - c > max_dd_s: max_dd_s = peak_s - c

pr()
pr(f"Total picks SAFE : {total_safe}  ({wins_safe}W / {losses_safe}L)")
pr(f"Total misé       : {mise_safe:.0f}€")
pr(f"P&L net          : {cumul_safe:+.0f}€")
pr(f"ROI              : {roi_safe:+.1f}%")
pr(f"Drawdown max     : -{max_dd_s:.0f}€")


# ─── RÉSUMÉ FINAL ────────────────────────────────────────────────────────────

sep("RÉSUMÉ — CE QUE 88 JOURS NOUS DISENT")

pr(f"{'Système / filtre':<40} {'Picks':>6} {'Win%':>7} {'P&L':>10} {'ROI':>7}")
pr("-" * 75)

all_w = sum(1 for p in selected_picks if p["result"] == "WIN")
all_pnl = sum(((p["odd_sys"]*DECOTE-1)*MISE if p["result"]=="WIN" else -MISE) for p in selected_picks)
all_roi = all_pnl / (len(selected_picks)*MISE) * 100

pr(f"{'Tous les picks sélectionnés':<40} {len(selected_picks):>6} {all_w/len(selected_picks)*100:>6.0f}% {all_pnl:>+10.0f}€ {all_roi:>+6.1f}%")
pr(f"{'Picks cote sys ≥1.72 seulement':<40} {len(high_picks):>6} {w_pct_h*100:>6.0f}% {pnl_flat_h:>+10.0f}€ {roi_h:>+6.1f}%")
pr(f"{'SAFE uniquement (HT05 + O15_FT)':<40} {total_safe:>6} {wins_safe/total_safe*100 if total_safe else 0:>6.0f}% {cumul_safe:>+10.0f}€ {roi_safe:>+6.1f}%")

pr()
# Trouver les types de paris avec EV positif
positifs = [d for d in label_data if d["ev"] > 0]
negatifs = [d for d in label_data if d["ev"] <= 0]
pr(f"Types de paris à EV POSITIF : {len(positifs)}")
for d in sorted(positifs, key=lambda x: -x["ev"]):
    pr(f"  {d['label']:<20} EV={d['ev']:+.3f}  win={d['w_pct']*100:.0f}%  n={d['n']}")
pr(f"Types de paris à EV NÉGATIF : {len(negatifs)}")
for d in sorted(negatifs, key=lambda x: x["ev"])[:5]:
    pr(f"  {d['label']:<20} EV={d['ev']:+.3f}  win={d['w_pct']*100:.0f}%  n={d['n']}")


# ─── Sauvegarder ─────────────────────────────────────────────────────────────

OUT_TXT.write_text("\n".join(lines_out), encoding="utf-8")
pr(f"\n→ Résultats : {OUT_TXT}")


# ─── Table BCEA session 13 ───────────────────────────────────────────────────

md_lines = [
    "# TABLE — Session 13 — BCEA — 2026-04-08",
    "*Résultats backtests Session 12 — 88 jours d'archive*\n",
    "---\n",
    "## 1. Win rate par tranche de cote système\n",
    "| Tranche cote sys | Cote réelle | Picks | Win% | EV/€ | P&L 7€ |",
    "|------------------|-------------|-------|------|------|--------|",
]
for d in tranche_data:
    md_lines.append(f"| {d['label']} | ~{d['avg_odd_real']:.2f} | {d['n']} | {d['w_pct']*100:.0f}% | {d['ev']:+.3f} | {d['pnl']:+.0f}€ |")

md_lines += [
    "",
    "## 2. Picks à cote système ≥1.72 (cote réelle ≥1.38)\n",
    f"- Volume : **{len(high_picks)} picks** sur {len(selected_picks)} ({len(high_picks)/len(selected_picks)*100:.1f}%)",
    f"- Jours actifs : {len(by_date_high)} / {len(datasets)}",
    f"- Win rate : **{w_pct_h*100:.0f}%**",
    f"- Flat betting 7€ : **{pnl_flat_h:+.0f}€** (ROI {roi_h:+.1f}%)",
    f"- Kelly ×0.5 : **{bankroll_k-600:+.0f}€** | Drawdown max : -{max_dd_k:.0f}€\n",
    "## 3. Win rate et EV par type de pari\n",
    "| Type de pari | Picks | Win% | Cote sys moy | Cote réelle | Break-even | EV |",
    "|--------------|-------|------|-------------|------------|-----------|-----|",
]
for d in label_data:
    flag = "✅" if d["ev"] > 0 else "❌"
    md_lines.append(f"| {d['label']} {flag} | {d['n']} | {d['w_pct']*100:.0f}% | — | {d['avg_real']:.2f} | {d['breakeven']:.2f} | {d['ev']:+.3f} |")

md_lines += [
    "",
    "## 4. SAFE uniquement (HT05 + O15_FT)\n",
    f"- Picks : **{total_safe}** ({wins_safe}W / {losses_safe}L)",
    f"- Win rate : **{wins_safe/total_safe*100 if total_safe else 0:.0f}%**",
    f"- P&L flat betting 7€ : **{cumul_safe:+.0f}€** (ROI {roi_safe:+.1f}%)",
    f"- Drawdown max : -{max_dd_s:.0f}€\n",
    "## Synthèse\n",
    f"| Filtre | Picks | Win% | P&L | ROI |",
    f"|--------|-------|------|-----|-----|",
    f"| Tous picks sélectionnés | {len(selected_picks)} | {all_w/len(selected_picks)*100:.0f}% | {all_pnl:+.0f}€ | {all_roi:+.1f}% |",
    f"| Cote sys ≥1.72 | {len(high_picks)} | {w_pct_h*100:.0f}% | {pnl_flat_h:+.0f}€ | {roi_h:+.1f}% |",
    f"| SAFE (HT05+O15) | {total_safe} | {wins_safe/total_safe*100 if total_safe else 0:.0f}% | {cumul_safe:+.0f}€ | {roi_safe:+.1f}% |",
    "",
    "**Types de paris à EV positif :**",
]
for d in sorted(positifs, key=lambda x: -x["ev"]):
    md_lines.append(f"- **{d['label']}** : EV={d['ev']:+.3f}, win={d['w_pct']*100:.0f}%, n={d['n']}")

OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")
pr(f"→ Table BCEA : {OUT_MD}")
pr("\nTerminé.")
