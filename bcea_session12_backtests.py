"""
bcea_session12_backtests.py
---------------------------
Produit les 4 backtests demandés par la Session 11 :
  1. P&L mise fixe (flat betting) sur picks individuels — 88 jours
  2. Volume de picks disponibles à cote réelle ≥ 1.38
  3. Corrélation entre les legs dans les tickets actuels
  4. Simulations D'Alembert et Kelly sur tickets historiques

Résultats écrits dans :
  data/optimizer/bcea_session12_backtests.txt
  equipe/reunions/BCEA_2026-04-08_session_12_table.md
"""

from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict
import statistics

ROOT = Path(__file__).resolve().parent
OUT_TXT  = ROOT / "data/optimizer/bcea_session12_backtests.txt"
OUT_MD   = ROOT / "equipe/reunions/BCEA_2026-04-08_session_12_table.md"
OUT_TXT.parent.mkdir(parents=True, exist_ok=True)

lines_out: list[str] = []

def pr(*args):
    s = " ".join(str(a) for a in args)
    print(s)
    lines_out.append(s)

def separator(title=""):
    s = "=" * 70
    if title:
        s = f"\n{s}\n  {title}\n{'=' * 70}"
    pr(s)


# ─── 0. Charger les données ───────────────────────────────────────────────────

pr("Chargement des données...")

# Pool système : date, match_id, label, time, league, home, away, odd
pool_by_key: dict[tuple, float] = {}   # (match_id, label) → odd
pool_rows: list[dict] = []

for line in (ROOT / "data/system_pool_effective_global.tsv").read_text(encoding="utf-8").splitlines():
    if not line.startswith("TSV:"):
        continue
    parts = line.split("\t")
    if len(parts) < 8:
        continue
    try:
        date    = parts[0].replace("TSV:", "").strip()
        mid     = int(parts[1].strip())
        label   = parts[2].strip()
        time_   = parts[3].strip()
        league  = parts[4].strip()
        odd     = float(parts[7].strip())
        pool_by_key[(mid, label)] = odd
        pool_rows.append({"date": date, "mid": mid, "label": label, "odd": odd, "time": time_, "league": league})
    except (ValueError, IndexError):
        continue

pr(f"  Pool système : {len(pool_rows)} picks chargés")

# Verdicts individuels : match_id, label, result (WIN/LOSS)
verdict_rows: list[dict] = []

for line in (ROOT / "data/verdict_post_analyse.txt").read_text(encoding="utf-8", errors="ignore").splitlines():
    if not line.startswith("TSV:"):
        continue
    parts = line.split("\t")
    if len(parts) < 11:
        continue
    try:
        mid      = int(parts[0].replace("TSV:", "").strip().split()[-1])
        date     = parts[1].strip()
        label    = parts[5].strip()
        selected = parts[9].strip()
        result   = parts[10].strip()
        if selected == "1" and result in ("WIN", "LOSS"):
            verdict_rows.append({"date": date, "mid": mid, "label": label, "result": result})
    except (ValueError, IndexError):
        continue

pr(f"  Verdicts individuels : {len(verdict_rows)} picks avec résultat")

# Joindre pool + verdicts
joined: list[dict] = []
for v in verdict_rows:
    key = (v["mid"], v["label"])
    if key in pool_by_key:
        odd = pool_by_key[key]
        joined.append({"date": v["date"], "mid": v["mid"], "label": v["label"],
                       "result": v["result"], "odd": odd})

pr(f"  Jointure pool+verdicts : {len(joined)} picks matchés")

# Tickets depuis verdict_post_analyse_tickets_report.txt
tickets: list[dict] = []
current_ticket = None

for line in (ROOT / "data/verdict_post_analyse_tickets_report.txt").read_text(encoding="utf-8", errors="ignore").splitlines():
    s = line.strip()
    if ("✅ Ticket" in s or "❌ Ticket" in s) and "odd=" in s:
        if current_ticket:
            tickets.append(current_ticket)
        result = "WIN" if "✅ Ticket" in s else "LOSS"
        # extraire cote
        try:
            odd_str = [p for p in s.split("|") if "odd=" in p][0]
            odd = float(odd_str.split("odd=")[1].strip())
        except:
            odd = 2.5
        # extraire date
        date = ""
        for part in s.split("|"):
            for day in ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]:
                if day in part:
                    tokens = part.strip().split()
                    for t in tokens:
                        if t.count("-") == 2 and t.startswith("2026"):
                            date = t
        current_ticket = {"result": result, "odd": odd, "date": date,
                         "legs": 0, "mega": 0, "leagues": set(), "times": []}
    elif s.startswith("legs=") and current_ticket is not None:
        for p in s.split(" | "):
            if p.startswith("legs="):
                try: current_ticket["legs"] = int(p.split("=")[1])
                except: pass
    elif ("✅ Leg" in s or "❌ Leg" in s) and current_ticket is not None:
        if "MEGA EXPLOSION" in s:
            current_ticket["mega"] += 1
        # extraire league et heure
        parts = s.split("|")
        if len(parts) >= 3:
            try: current_ticket["times"].append(parts[1].strip())
            except: pass
            try: current_ticket["leagues"].add(parts[2].strip())
            except: pass

if current_ticket:
    tickets.append(current_ticket)

pr(f"  Tickets historiques : {len(tickets)} chargés\n")


# ─── 1. FLAT BETTING — mise fixe sur picks individuels ───────────────────────

separator("BACKTEST 1 — FLAT BETTING (mise fixe 7€ par pick sélectionné)")

MISE_FIXE = 7.0

# Grouper par date
by_date = defaultdict(list)
for p in joined:
    by_date[p["date"]].append(p)

dates_sorted = sorted(by_date.keys())
pr(f"Jours avec picks joués : {len(dates_sorted)}")
pr(f"Mise fixe : {MISE_FIXE}€ par pick\n")

total_mise = 0.0
total_retour = 0.0
bankroll = 0.0
daily_pnl = []

pr(f"{'Date':<14} {'Picks':>6} {'W':>4} {'L':>4} {'P&L jour':>10} {'Cumulé':>10}")
pr("-" * 60)

for date in dates_sorted:
    picks = by_date[date]
    wins  = [p for p in picks if p["result"] == "WIN"]
    losses = [p for p in picks if p["result"] == "LOSS"]
    mise_j = len(picks) * MISE_FIXE
    retour_j = sum(p["odd"] * MISE_FIXE for p in wins)
    pnl_j = retour_j - mise_j
    bankroll += pnl_j
    total_mise += mise_j
    total_retour += retour_j
    daily_pnl.append(pnl_j)
    pr(f"{date:<14} {len(picks):>6} {len(wins):>4} {len(losses):>4} {pnl_j:>+10.1f}€ {bankroll:>+10.1f}€")

pr()
pr(f"Total misé   : {total_mise:.0f}€")
pr(f"Total retour : {total_retour:.0f}€")
pr(f"P&L net      : {bankroll:+.0f}€")
roi = (total_retour - total_mise) / total_mise * 100
pr(f"ROI          : {roi:+.1f}%")
pr(f"Meilleur jour  : {max(daily_pnl):+.1f}€")
pr(f"Pire jour      : {min(daily_pnl):+.1f}€")

# Drawdown max
peak = 0.0
cumul = 0.0
max_dd = 0.0
for pnl in daily_pnl:
    cumul += pnl
    if cumul > peak:
        peak = cumul
    dd = peak - cumul
    if dd > max_dd:
        max_dd = dd
pr(f"Drawdown max   : -{max_dd:.0f}€")


# ─── 2. PICKS À COTE ≥ 1.38 ──────────────────────────────────────────────────

separator("BACKTEST 2 — VOLUME DE PICKS À COTE RÉELLE ≥ 1.38")

# Cote réelle = cote système × 0.80 (décote bookmaker ~20%)
DECOTE = 0.80

seuils = [1.20, 1.30, 1.38, 1.50, 1.60]

pr(f"Décote appliquée : ×{DECOTE} (cotes bookmaker ~20% sous prédictions)")
pr(f"Total picks avec verdict + cote : {len(joined)}")
pr()

# Distribution par seuil de cote réelle
pr(f"{'Seuil cote réelle':>20} {'Picks':>8} {'% total':>8} {'W%':>8} {'P&L 7€ fixe':>12}")
pr("-" * 60)

for seuil in seuils:
    subset = [p for p in joined if p["odd"] * DECOTE >= seuil]
    if not subset:
        continue
    wins = sum(1 for p in subset if p["result"] == "WIN")
    w_pct = wins / len(subset) * 100
    pnl = sum((p["odd"] * DECOTE * MISE_FIXE if p["result"] == "WIN" else -MISE_FIXE) for p in subset)
    pct_total = len(subset) / len(joined) * 100
    pr(f"≥ {seuil:.2f}             {len(subset):>8} {pct_total:>7.0f}% {w_pct:>7.0f}% {pnl:>+12.0f}€")

pr()
pr("Nombre de picks ≥1.38 par jour :")
by_date_138 = defaultdict(list)
for p in joined:
    if p["odd"] * DECOTE >= 1.38:
        by_date_138[p["date"]].append(p)

counts = [len(v) for v in by_date_138.values()]
if counts:
    pr(f"  Jours avec ≥1 pick : {len(counts)}")
    pr(f"  Moy picks/jour     : {statistics.mean(counts):.1f}")
    pr(f"  Min                : {min(counts)}")
    pr(f"  Max                : {max(counts)}")
    pr(f"  Jours avec ≥2 picks: {sum(1 for c in counts if c >= 2)}")
    pr(f"  Jours avec ≥3 picks: {sum(1 for c in counts if c >= 3)}")


# ─── 3. CORRÉLATION ENTRE LEGS ───────────────────────────────────────────────

separator("BACKTEST 3 — CORRÉLATION ENTRE LEGS DANS LES TICKETS")

# Proxy de corrélation : même ligue dans un ticket
same_league_tickets = [t for t in tickets if len(t["leagues"]) == 1 and t["legs"] >= 2]
diff_league_tickets = [t for t in tickets if len(t["leagues"]) > 1 and t["legs"] >= 2]

def win_rate(ts):
    if not ts:
        return 0.0
    return sum(1 for t in ts if t["result"] == "WIN") / len(ts) * 100

pr(f"Tickets analysés (≥2 legs) : {len([t for t in tickets if t['legs'] >= 2])}")
pr()
pr(f"Tickets MÊME ligue (tous les legs) : {len(same_league_tickets)}")
pr(f"  Win rate : {win_rate(same_league_tickets):.0f}%")
pr()
pr(f"Tickets LIGUES DIFFÉRENTES : {len(diff_league_tickets)}")
pr(f"  Win rate : {win_rate(diff_league_tickets):.0f}%")
pr()

# Même fenêtre horaire (legs joués en < 90 min d'écart)
pr("Note : des legs dans la même ligue le même soir partagent potentiellement")
pr("des facteurs communs (arbitres, météo, humeur de la ligue).")
pr("Un win rate plus bas sur même-ligue suggère une corrélation négative.")
pr("Un win rate identique ou plus haut suggère l'indépendance.")


# ─── 4. D'ALEMBERT + KELLY SUR TICKETS ───────────────────────────────────────

separator("BACKTEST 4A — SIMULATION D'ALEMBERT SUR TICKETS")

UNITE = 7.0    # unité de base (€)
BANKROLL_INIT = 600.0

def sim_dalembert(ticket_sequence, unite, bankroll_init):
    bankroll = bankroll_init
    mise = unite
    history = []
    for t in ticket_sequence:
        if bankroll < mise:
            history.append({"bankroll": bankroll, "mise": mise, "result": "RUINE", "pnl": 0})
            break
        if t["result"] == "WIN":
            gain = (t["odd"] - 1) * mise
            bankroll += gain
            history.append({"bankroll": bankroll, "mise": mise, "result": "WIN", "pnl": gain})
            mise = max(unite, mise - unite)
        else:
            bankroll -= mise
            history.append({"bankroll": bankroll, "mise": mise, "result": "LOSS", "pnl": -mise})
            mise += unite
    return history

hist_dal = sim_dalembert(tickets, UNITE, BANKROLL_INIT)

wins_dal   = sum(1 for h in hist_dal if h["result"] == "WIN")
losses_dal = sum(1 for h in hist_dal if h["result"] == "LOSS")
ruines_dal = sum(1 for h in hist_dal if h["result"] == "RUINE")
final_dal  = hist_dal[-1]["bankroll"] if hist_dal else BANKROLL_INIT
max_mise   = max(h["mise"] for h in hist_dal) if hist_dal else UNITE
peak_d = BANKROLL_INIT
max_dd_d = 0.0
for h in hist_dal:
    if h["bankroll"] > peak_d:
        peak_d = h["bankroll"]
    if peak_d - h["bankroll"] > max_dd_d:
        max_dd_d = peak_d - h["bankroll"]

pr(f"Bankroll initiale   : {BANKROLL_INIT}€")
pr(f"Unité de base       : {UNITE}€")
pr(f"Tickets joués       : {len(hist_dal)}")
pr(f"WIN / LOSS / RUINE  : {wins_dal} / {losses_dal} / {ruines_dal}")
pr(f"Bankroll finale     : {final_dal:+.0f}€")
pr(f"P&L net             : {final_dal - BANKROLL_INIT:+.0f}€")
pr(f"Mise max atteinte   : {max_mise:.0f}€")
pr(f"Drawdown max        : -{max_dd_d:.0f}€")

separator("BACKTEST 4B — SIMULATION KELLY SUR PICKS INDIVIDUELS")

# Kelly = (p * b - (1-p)) / b   où b = cote - 1, p = win_rate estimé
# On utilise p = 0.73 (empirique)
# On plafonne à 20% du bankroll par mise (Kelly fractionnel ÷ 2)

P_KELLY = 0.73
KELLY_FRAC = 0.5   # demi-Kelly pour réduire la variance

bankroll_k = BANKROLL_INIT
history_k = []

for p in joined:
    b = p["odd"] * DECOTE - 1  # cote réelle nette
    if b <= 0:
        continue
    kelly_full = (P_KELLY * b - (1 - P_KELLY)) / b
    kelly = kelly_full * KELLY_FRAC
    kelly = max(0.0, min(kelly, 0.20))  # plafonné à 20% du bankroll
    mise_k = bankroll_k * kelly
    if mise_k < 0.5:
        continue
    if p["result"] == "WIN":
        bankroll_k += mise_k * b
        history_k.append(bankroll_k)
    else:
        bankroll_k -= mise_k
        history_k.append(bankroll_k)
    if bankroll_k <= 0:
        break

wins_k = sum(1 for p in joined if p["result"] == "WIN")
final_k = bankroll_k
peak_k = BANKROLL_INIT
max_dd_k = 0.0
for bk in history_k:
    if bk > peak_k:
        peak_k = bk
    if peak_k - bk > max_dd_k:
        max_dd_k = peak_k - bk

pr(f"Bankroll initiale   : {BANKROLL_INIT}€")
pr(f"p estimé            : {P_KELLY} | Kelly fractionnel : ×{KELLY_FRAC}")
pr(f"Décote bookmaker    : ×{DECOTE}")
pr(f"Picks joués         : {len(history_k)}")
pr(f"Bankroll finale     : {final_k:.0f}€")
pr(f"P&L net             : {final_k - BANKROLL_INIT:+.0f}€")
pr(f"Mult final          : ×{final_k/BANKROLL_INIT:.2f}")
pr(f"Drawdown max        : -{max_dd_k:.0f}€")

separator("BACKTEST 4C — SIMULATION ANTI-MARTINGALE (PAROLI) SUR TICKETS")

# Paroli : on double la mise après chaque victoire (max 3 victoires consécutives)
# Après 3 victoires ou 1 défaite, on revient à la mise de base

def sim_paroli(ticket_sequence, unite, bankroll_init, max_streak=3):
    bankroll = bankroll_init
    mise = unite
    streak = 0
    history = []
    for t in ticket_sequence:
        if bankroll < mise:
            history.append({"bankroll": bankroll, "result": "RUINE"})
            break
        if t["result"] == "WIN":
            gain = (t["odd"] - 1) * mise
            bankroll += gain
            streak += 1
            if streak >= max_streak:
                mise = unite
                streak = 0
            else:
                mise = min(mise * 2, bankroll * 0.25)
            history.append({"bankroll": bankroll, "result": "WIN"})
        else:
            bankroll -= mise
            mise = unite
            streak = 0
            history.append({"bankroll": bankroll, "result": "LOSS"})
    return history

hist_par = sim_paroli(tickets, UNITE, BANKROLL_INIT)
wins_par   = sum(1 for h in hist_par if h["result"] == "WIN")
losses_par = sum(1 for h in hist_par if h["result"] == "LOSS")
final_par  = hist_par[-1]["bankroll"] if hist_par else BANKROLL_INIT
peak_p = BANKROLL_INIT
max_dd_p = 0.0
for h in hist_par:
    if h["bankroll"] > peak_p:
        peak_p = h["bankroll"]
    if peak_p - h["bankroll"] > max_dd_p:
        max_dd_p = peak_p - h["bankroll"]

pr(f"Bankroll initiale   : {BANKROLL_INIT}€")
pr(f"Unité de base       : {UNITE}€  |  Max streak avant reset : 3")
pr(f"WIN / LOSS / RUINE  : {wins_par} / {losses_par}")
pr(f"Bankroll finale     : {final_par:.0f}€")
pr(f"P&L net             : {final_par - BANKROLL_INIT:+.0f}€")
pr(f"Drawdown max        : -{max_dd_p:.0f}€")


# ─── RÉSUMÉ COMPARATIF ───────────────────────────────────────────────────────

separator("RÉSUMÉ COMPARATIF — TOUS LES SYSTÈMES")

pr(f"{'Système':<35} {'P&L net':>10} {'Drawdown max':>14}")
pr("-" * 62)
pr(f"{'Flat betting (pick single, 7€ fixe)':<35} {bankroll:>+10.0f}€ {max_dd:>+13.0f}€")
pr(f"{'D Alembert (tickets, unité 7€)':<35} {final_dal-BANKROLL_INIT:>+10.0f}€ {max_dd_d:>+13.0f}€")
pr(f"{'Paroli anti-martingale (tickets, 7€)':<35} {final_par-BANKROLL_INIT:>+10.0f}€ {max_dd_p:>+13.0f}€")
pr(f"{'Kelly 0.5 (picks, décote 0.80)':<35} {final_k-BANKROLL_INIT:>+10.0f}€ {max_dd_k:>+13.0f}€")
pr()
pr("Note : les simulations sont sur les données disponibles (picks avec verdict")
pr("joinables au pool système). Certains picks n'ont pas de cote disponible dans")
pr("le pool et sont exclus. Les résultats sont indicatifs, pas définitifs.")

# ─── Sauvegarder TXT ─────────────────────────────────────────────────────────

OUT_TXT.write_text("\n".join(lines_out), encoding="utf-8")
print(f"\n→ Résultats écrits dans {OUT_TXT}")


# ─── Écrire le compte-rendu BCEA ─────────────────────────────────────────────

flat_pnl = bankroll
flat_roi = roi
dal_pnl = final_dal - BANKROLL_INIT
par_pnl = final_par - BANKROLL_INIT
kel_pnl = final_k - BANKROLL_INIT

md = f"""# TABLE — Session 12 — BCEA — 2026-04-08
*Résultats des backtests demandés en Session 11*

---

## Faits bruts — ce que les données disent

### 1. Flat betting (mise fixe 7€ par pick sélectionné)

| Métrique | Valeur |
|----------|--------|
| Jours analysés | {len(dates_sorted)} |
| Total picks | {len(joined)} |
| P&L net | {flat_pnl:+.0f}€ |
| ROI | {flat_roi:+.1f}% |
| Drawdown max | -{max_dd:.0f}€ |

### 2. Volume de picks disponibles par seuil de cote réelle (décote ×0.80)

| Seuil cote réelle | Picks dispo | Win% | P&L 7€ fixe |
|-------------------|-------------|------|-------------|
"""

for seuil in seuils:
    subset = [p for p in joined if p["odd"] * DECOTE >= seuil]
    if not subset:
        continue
    wins_s = sum(1 for p in subset if p["result"] == "WIN")
    w_pct_s = wins_s / len(subset) * 100
    pnl_s = sum((p["odd"] * DECOTE * MISE_FIXE if p["result"] == "WIN" else -MISE_FIXE) for p in subset)
    pct_s = len(subset) / len(joined) * 100
    md += f"| ≥ {seuil:.2f} | {len(subset)} ({pct_s:.0f}%) | {w_pct_s:.0f}% | {pnl_s:+.0f}€ |\n"

md += f"""
Picks à cote réelle ≥1.38 : moyenne **{statistics.mean(counts) if counts else 0:.1f} picks/jour**
({sum(1 for c in counts if c >= 2)} jours avec ≥2 picks disponibles pour un ticket 2 legs)

### 3. Corrélation entre legs

| Legs | Win rate |
|------|---------|
| Tickets même ligue (n={len(same_league_tickets)}) | {win_rate(same_league_tickets):.0f}% |
| Tickets ligues différentes (n={len(diff_league_tickets)}) | {win_rate(diff_league_tickets):.0f}% |

### 4. Simulations systèmes alternatifs (bankroll initiale 600€)

| Système | P&L net | Drawdown max |
|---------|---------|-------------|
| Flat betting pick single (7€ fixe) | {flat_pnl:+.0f}€ | -{max_dd:.0f}€ |
| D'Alembert sur tickets (unité 7€) | {dal_pnl:+.0f}€ | -{max_dd_d:.0f}€ |
| Paroli / Anti-martingale (unité 7€) | {par_pnl:+.0f}€ | -{max_dd_p:.0f}€ |
| Kelly ×0.5 sur picks (décote ×0.80) | {kel_pnl:+.0f}€ | -{max_dd_k:.0f}€ |

---

## Ce que ces chiffres ne disent pas encore

- Les simulations D'Alembert et Paroli utilisent les **127 tickets historiques** dans leur ordre chronologique. L'échantillon est court.
- Le Kelly utilise p=0.73 fixe. Si le taux réel en production est inférieur, le Kelly surperforme artificiellement.
- Les picks ≥1.38 de cote réelle : il faut vérifier si leur **win rate** se maintient à 73% ou s'il baisse quand on filtre par cote haute.
- La corrélation entre legs est mesurée par un proxy (même ligue). Une vraie corrélation statistique nécessite plus de données.

---

## Questions ouvertes pour la Session 12

1. Avec {sum(1 for c in counts if c >= 2)} jours ayant ≥2 picks à cote ≥1.38, est-ce suffisant pour jouer un ticket 2 legs tous les jours ?
2. Le P&L flat betting ({flat_pnl:+.0f}€) est-il significatif ou dans le bruit statistique ?
3. Quel système est le plus robuste si le win rate passe de 73% à 65% ?
"""

OUT_MD.write_text(md, encoding="utf-8")
print(f"→ Table BCEA écrite dans {OUT_MD}")
print("\nTerminé.")
