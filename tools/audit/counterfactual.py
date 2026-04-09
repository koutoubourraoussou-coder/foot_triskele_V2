"""
tools/audit/counterfactual.py
──────────────────────────────────────────────────────────────────────
ANALYSE CONTREFACTUELLE v3 — Triskèle V2

Pour chaque journée dans l'archive, calcule :
  - Tous les picks jouables (issus des *_jouables.tsv, haute qualité)
  - Leur résultat RÉEL depuis results.tsv (scores effectifs du match)
  - Toutes les combinaisons 3-4 legs possibles (picks de matchs différents)
  - Le ticket réellement joué et son rang parmi toutes les combos
  - Un flag par journée : CATASTROPHIQUE / MALCHANCEUX / OPTIMAL / BON_CHOIX_MALCHANCEUX

Source de vérité des résultats : archive/analyse_YYYY-MM-DD/results.tsv
  Format : TSV: date \\t league \\t home \\t away \\t fixture_id \\t ft_score \\t status \\t ht_score

⚠️  predictions.tsv col 9 = is_candidate (qualité pick), PAS le résultat réel du pari.
    Ce fichier n'est pas utilisé pour les résultats.

Usage :
    python tools/audit/counterfactual.py
    python tools/audit/counterfactual.py --days 30
    python tools/audit/counterfactual.py --output data/counterfactual_report.json
    python tools/audit/counterfactual.py --days 14 --min-odd 1.5

[BCEA Session 3 — v1 : cotes proxy]
[BCEA Session 4 — v2 : is_candidate (erreur — colonne mal identifiée)]
[BCEA Session 5 — v3 : résultats réels depuis results.tsv]
"""

from __future__ import annotations

import re
import json
import random
import argparse
import itertools
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional, Dict, Tuple, Any

# ── Racine du projet ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "archive"

# ── Constantes ────────────────────────────────────────────────────────────────
MIN_ODD = 1.15          # cote minimale pour un pick candidat
MAX_CANDIDATES = 50     # si pool > 50 picks uniques, on sous-échantillonne
MAX_COMBINATIONS = 2000 # cap sur le nombre total de combinaisons calculées

# Seuils de flag
CATASTROPHIC_WIN_RATIO  = 0.50   # CATASTROPHIQUE si > 50% des combos gagnaient mais pas le nôtre
BON_CHOIX_PERCENTILE    = 75     # BON_CHOIX si ticket dans le top 25% (percentile >= 75)
MALCHANCEUX_WIN_RATIO   = 0.30   # MALCHANCEUX si < 30% des combos gagnaient (vraie malchance)

# Mapping nom de fichier jouables → bet_key
JOUABLES_TO_BET_KEY: Dict[str, str] = {
    "o15_ft_jouables":      "O15_FT",
    "o25_ft_jouables":      "O25_FT",
    "ht05_jouables":        "HT05",
    "ht1x_home_jouables":   "HT1X_HOME",
    "team1_score_jouables": "TEAM1_SCORE_FT",
    "team1_win_jouables":   "TEAM1_WIN_FT",
    "team2_score_jouables": "TEAM2_SCORE_FT",
    "team2_win_jouables":   "TEAM2_WIN_FT",
}

# Fichiers jouables utilisés par RANDOM (O15 uniquement)
RANDOM_JOUABLES = {"o15_ft_jouables"}


# ── Helpers parsing ───────────────────────────────────────────────────────────

def parse_analyse_dir_date(p: Path) -> Optional[date]:
    m = re.match(r"analyse_(\d{4}-\d{2}-\d{2})$", p.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def list_analyse_dirs(days: Optional[int] = None) -> List[Tuple[date, Path]]:
    """Liste tous les dossiers archive/analyse_YYYY-MM-DD triés par date (desc)."""
    if not ARCHIVE_DIR.exists():
        return []
    out = []
    for d in ARCHIVE_DIR.iterdir():
        if not d.is_dir():
            continue
        dt = parse_analyse_dir_date(d)
        if dt:
            out.append((dt, d))
    out.sort(key=lambda x: x[0], reverse=True)
    if days is not None:
        out = out[:days]
    return out


def find_run_dir(analyse_dir: Path) -> Optional[Path]:
    """Trouve le run_dir le plus récent (ex: 2026-03-01__15h38m30s) dans un dossier analyse."""
    candidates = [p for p in analyse_dir.iterdir() if p.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name, reverse=True)
    return candidates[0]


# ── Parsing des scores réels ───────────────────────────────────────────────────

def _parse_score(score_str: str) -> Tuple[int, int]:
    """Parse '2-1' → (2, 1). Retourne (-1, -1) si échec."""
    m = re.match(r"^(\d+)-(\d+)$", score_str.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return -1, -1


def parse_results_tsv(path: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Parse results.tsv et retourne un dict indexé par (home.lower(), away.lower()).

    Format TSV : TSV: date \\t league \\t home \\t away \\t fixture_id \\t ft_score \\t status \\t ht_score
    Retourne : {(home, away): {"ft_h": int, "ft_a": int, "ht_h": int, "ht_a": int, "status": str}}
    """
    if not path.exists():
        return {}

    results: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("TSV:"):
                continue
            # Enlever "TSV:" + espace(s)
            raw = re.sub(r"^TSV:\s*", "", line)
            parts = raw.split("\t")
            if len(parts) < 8:
                continue
            try:
                home    = parts[2].strip()
                away    = parts[3].strip()
                ft_str  = parts[5].strip()
                status  = parts[6].strip()
                ht_str  = parts[7].strip()

                ft_h, ft_a = _parse_score(ft_str)
                ht_h, ht_a = _parse_score(ht_str)

                if ft_h < 0:
                    continue

                key = (home.lower(), away.lower())
                if key not in results:
                    results[key] = {
                        "ft_h": ft_h, "ft_a": ft_a,
                        "ht_h": ht_h, "ht_a": ht_a,
                        "status": status,
                    }
            except (ValueError, IndexError):
                continue
    return results


def _evaluate_bet(
    bet_key: str,
    ft_h: int, ft_a: int,
    ht_h: int, ht_a: int,
) -> Optional[bool]:
    """
    Évalue si un pari est gagné en fonction du score réel.
    Retourne None si le score est inconnu (-1).
    """
    if ft_h < 0 or ft_a < 0:
        return None

    if bet_key == "O15_FT":
        return (ft_h + ft_a) >= 2
    if bet_key == "O25_FT":
        return (ft_h + ft_a) >= 3
    if bet_key == "HT05":
        if ht_h < 0 or ht_a < 0:
            return None
        return (ht_h + ht_a) >= 1
    if bet_key == "HT1X_HOME":
        if ht_h < 0:
            return None
        return ht_h >= 1
    if bet_key == "TEAM1_SCORE_FT":
        return ft_h >= 1
    if bet_key == "TEAM1_WIN_FT":
        return ft_h > ft_a
    if bet_key == "TEAM2_SCORE_FT":
        return ft_a >= 1
    if bet_key == "TEAM2_WIN_FT":
        return ft_a > ft_h

    return None  # bet_key inconnu


# ── Parsing des tickets et verdicts ───────────────────────────────────────────

def parse_tickets_report(path: Path) -> List[Dict[str, Any]]:
    """
    Parse tickets_report.txt et retourne une liste de tickets avec leurs picks.
    Chaque ticket : {"ticket_id": str, "total_odd": float, "picks": [...]}
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="ignore")
    tickets = []

    ticket_re = re.compile(
        r"TICKET\s*[\d.]+.*?id=(?P<tid>[^\s\-]+(?:-[^\s]+)*).*?cote\s*=\s*(?P<odd>[0-9.]+)"
    )
    leg_re = re.compile(
        r"^\s*\d+\)\s*(?P<time>\d{2}:\d{2})\s*\|\s*(?P<league>[^|]+)\s*\|\s*"
        r"(?P<home>[^|]+)\s*vs\s*(?P<away>[^|]+)\s*\|\s*(?P<metric>[^|]+)\s*\|\s*"
        r"(?P<label>[^|]+)\s*\|\s*odd=(?P<odd>[0-9.]+)",
        re.MULTILINE
    )

    lines = text.splitlines()
    current_ticket: Optional[Dict[str, Any]] = None

    for line in lines:
        m_ticket = ticket_re.search(line)
        if m_ticket:
            if current_ticket and current_ticket["picks"]:
                tickets.append(current_ticket)
            try:
                current_ticket = {
                    "ticket_id":  m_ticket.group("tid").strip(),
                    "total_odd":  float(m_ticket.group("odd")),
                    "picks": [],
                }
            except ValueError:
                current_ticket = None
            continue

        if current_ticket:
            m_leg = leg_re.match(line)
            if m_leg:
                try:
                    current_ticket["picks"].append({
                        "time":   m_leg.group("time").strip(),
                        "league": m_leg.group("league").strip(),
                        "home":   m_leg.group("home").strip(),
                        "away":   m_leg.group("away").strip(),
                        "metric": m_leg.group("metric").strip(),
                        "label":  m_leg.group("label").strip(),
                        "odd":    float(m_leg.group("odd")),
                    })
                except ValueError:
                    pass

    if current_ticket and current_ticket["picks"]:
        tickets.append(current_ticket)

    return tickets


def parse_verdict_legs(path: Path) -> Dict[str, str]:
    """
    Parse verdict_post_analyse_tickets_report.txt.
    Retourne un dict {ticket_id: "WIN"|"LOSS"|"PENDING"}.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    results = {}
    ticket_block_re = re.compile(
        r"(?P<status>[✅❌⏳])\s*Ticket\s+\d+.*?(?:id=|id =)(?P<id>[^\s\n]+)",
        re.DOTALL
    )
    for m in ticket_block_re.finditer(text):
        status = m.group("status").strip()
        tid = m.group("id").strip().rstrip(",;:")
        if status == "✅":
            results[tid] = "WIN"
        elif status == "❌":
            results[tid] = "LOSS"
        else:
            results[tid] = "PENDING"
    return results


# ── Pool de candidats ─────────────────────────────────────────────────────────

def _parse_jouables_match(match_str: str):
    """
    Parse 'Cruz Azul (1) vs Atletico San Luis (11)' → ('Cruz Azul', 'Atletico San Luis').
    Supporte aussi le format sans parenthèses.
    """
    m = re.match(r'^(.+?)\s*\(\d+\)\s+vs\s+(.+?)(?:\s*\(\d+\))?\s*$', match_str.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    parts = match_str.split(" vs ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None, None


def build_pool_from_jouables(
    run_dir: Path,
    results_lookup: Dict[Tuple[str, str], Dict[str, Any]],
    mode: str,  # "RANDOM" ou "SYSTEM"
    min_odd: float = MIN_ODD,
) -> List[Dict[str, Any]]:
    """
    Construit le pool de picks depuis les fichiers *_jouables.tsv.
    - mode RANDOM : uniquement o15_ft_jouables.tsv
    - mode SYSTEM : tous les *_jouables.tsv

    Cross-référencement avec results.tsv pour les résultats réels via les scores effectifs.
    Les picks dont le match n'a pas de score dans results.tsv sont exclus.
    """
    if mode == "RANDOM":
        stems_wanted = RANDOM_JOUABLES
    else:
        stems_wanted = set(JOUABLES_TO_BET_KEY.keys())

    seen: set = set()
    pool: List[Dict[str, Any]] = []

    for stem, bet_key in JOUABLES_TO_BET_KEY.items():
        if stem not in stems_wanted:
            continue
        jfile = run_dir / f"{stem}.tsv"
        if not jfile.exists():
            continue

        for line in jfile.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 8:
                continue

            match_str = parts[3].strip()
            odd_str   = parts[7].strip()

            home, away = _parse_jouables_match(match_str)
            if not home or not away:
                continue

            try:
                odd = float(odd_str)
            except ValueError:
                continue
            if odd < min_odd:
                continue

            # Cherche le résultat réel dans results_lookup
            rkey = (home.lower(), away.lower())
            match_result = results_lookup.get(rkey)
            if match_result is None:
                continue  # Match non trouvé dans results.tsv

            won = _evaluate_bet(
                bet_key,
                match_result["ft_h"], match_result["ft_a"],
                match_result["ht_h"], match_result["ht_a"],
            )
            if won is None:
                continue  # Score inconnu ou bet_key non évalué

            dedup = (home.lower(), away.lower(), bet_key)
            if dedup in seen:
                continue
            seen.add(dedup)

            pool.append({
                "home":     home,
                "away":     away,
                "bet_key":  bet_key,
                "league":   parts[2].strip(),
                "time_str": parts[1].strip(),
                "odd":      odd,
                "result":   1 if won else 0,
                "ft_score": f"{match_result['ft_h']}-{match_result['ft_a']}",
                "ht_score": f"{match_result['ht_h']}-{match_result['ht_a']}",
            })

    return pool


def _sample_pool(pool: List[Dict[str, Any]], max_picks: int, seed: int = 42) -> List[Dict[str, Any]]:
    """Si le pool est trop grand, sous-échantillonne de façon déterministe."""
    if len(pool) <= max_picks:
        return pool
    rng = random.Random(seed)
    return rng.sample(pool, max_picks)


# ── Génération des combinaisons ───────────────────────────────────────────────

def _generate_combinations(pool: List[Dict[str, Any]], seed: int = 42) -> List[Dict[str, Any]]:
    """
    Génère des combinaisons 3-4 legs depuis le pool.
    Règle : 1 pick max par match (meilleure cote).

    Si le nombre total de combos possibles dépasse MAX_COMBINATIONS,
    on sous-échantillonne aléatoirement les sélections de matchs
    (évite le biais lexicographique de itertools.combinations).

    Retourne une liste triée par total_odd desc, taille ≤ MAX_COMBINATIONS.
    """
    rng = random.Random(seed)

    # Grouper par match (home+away)
    by_match: Dict[str, List[Dict]] = {}
    for p in pool:
        mid = p.get("home", "") + "_" + p.get("away", "")
        by_match.setdefault(mid, []).append(p)

    match_ids = list(by_match.keys())
    all_match_combos: List[tuple] = []

    for n_legs in (3, 4):
        if len(match_ids) < n_legs:
            continue
        all_match_combos.extend(itertools.combinations(match_ids, n_legs))

    if not all_match_combos:
        return []

    # Sous-échantillonnage aléatoire si nécessaire
    if len(all_match_combos) > MAX_COMBINATIONS:
        all_match_combos = rng.sample(all_match_combos, MAX_COMBINATIONS)

    combos = []
    for match_combo in all_match_combos:
        best_picks = []
        for mid in match_combo:
            best = max(by_match[mid], key=lambda p: p["odd"])
            best_picks.append(best)

        total_odd = round(
            __import__("functools").reduce(lambda a, b: a * b["odd"], best_picks, 1.0),
            4,
        )
        is_won = all(p["result"] == 1 for p in best_picks)

        combos.append({
            "total_odd": total_odd,
            "is_won":    is_won,
            "picks":     [{"home": p["home"], "away": p["away"], "bet_key": p["bet_key"],
                            "odd": p["odd"], "result": p["result"],
                            "ft_score": p.get("ft_score", "?")} for p in best_picks],
        })

    combos.sort(key=lambda c: c["total_odd"], reverse=True)
    return combos


# ── Scoring / percentile ──────────────────────────────────────────────────────

def _percentile_of(value: float, distribution: List[float]) -> float:
    """Retourne le percentile de value dans la distribution (0-100).
    100% = meilleure cote, 0% = pire cote."""
    if not distribution:
        return 50.0
    n = len(distribution)
    rank = sum(1 for x in distribution if x < value)
    return round(100.0 * rank / n, 1)


def _rank_of(value: float, distribution: List[float]) -> int:
    """Rang du ticket joué (1 = meilleure cote, max = len(distribution))."""
    return min(sum(1 for x in distribution if x > value) + 1, len(distribution))


def _determine_flag(
    verdict: str,
    percentile: float,
    n_won: int,
    n_total: int,
) -> str:
    """
    Détermine le flag d'une journée.

    CATASTROPHIQUE  : LOSS + la majorité (>50%) des combos jouables gagnaient
    BON_CHOIX_MALCHANCEUX : LOSS + ticket top 25% cote + >30% des combos gagnaient
    MALCHANCEUX     : LOSS + peu d'alternatives gagnantes (win_ratio <= 30%)
    OPTIMAL         : WIN + ticket dans top 50% des cotes disponibles
    (empty)         : WIN bas de gamme ou PENDING
    """
    if n_total == 0:
        return ""

    win_ratio = n_won / n_total

    if verdict == "WIN":
        if percentile >= 50:
            return "OPTIMAL"
        return ""

    if verdict == "LOSS":
        if n_won == 0:
            return "MALCHANCEUX"
        if win_ratio >= CATASTROPHIC_WIN_RATIO:
            return "CATASTROPHIQUE"
        if percentile >= BON_CHOIX_PERCENTILE and win_ratio >= MALCHANCEUX_WIN_RATIO:
            return "BON_CHOIX_MALCHANCEUX"
        return "MALCHANCEUX"

    return ""  # PENDING


# ── Analyse par journée ───────────────────────────────────────────────────────

def _ticket_strategy(ticket_id: str) -> str:
    """Détermine la stratégie d'un ticket depuis son id. '_SYS' → SYSTEM, '_O15R' → RANDOM."""
    tid = ticket_id.upper()
    if tid.endswith("_O15R"):
        return "RANDOM"
    return "SYSTEM"


def _combos_for_pool(
    pool: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[float], int, float]:
    """
    Génère les combinaisons pour un pool donné.
    Retourne (combos, all_odds, n_won, win_ratio_pool).
    """
    if len(pool) < 3:
        return [], [], 0, 0.0
    pool_s = _sample_pool(pool, MAX_CANDIDATES)
    combos = _generate_combinations(pool_s)
    if not combos:
        return [], [], 0, 0.0
    all_odds      = [c["total_odd"] for c in combos]
    n_won         = sum(1 for c in combos if c["is_won"])
    win_ratio     = round(100.0 * n_won / len(combos), 1)
    return combos, all_odds, n_won, win_ratio


def analyze_day(
    day: date,
    analyse_dir: Path,
    min_odd: float = MIN_ODD,
) -> Optional[Dict[str, Any]]:
    """
    Analyse contrefactuelle v3 pour une journée donnée.
    Chaque ticket est comparé contre son pool propre :
      - SYSTEM tickets (_SYS)  → pool SYSTEM (tous les jouables)
      - RANDOM tickets (_O15R) → pool RANDOM (O15 uniquement)
    Retourne un dict avec les métriques ou None si données insuffisantes.
    """
    run_dir = find_run_dir(analyse_dir)

    def find_file(name: str) -> Optional[Path]:
        candidates = []
        if run_dir:
            candidates.append(run_dir / name)
        candidates.append(analyse_dir / name)
        for c in candidates:
            if c.exists():
                return c
        return None

    results_path       = find_file("results.tsv")
    tickets_sys_path   = find_file("tickets_report.txt")
    tickets_rnd_path   = find_file("tickets_o15_random_report.txt")
    verdict_sys_path   = find_file("verdict_post_analyse_tickets_report.txt")
    verdict_rnd_path   = find_file("verdict_post_analyse_tickets_o15_random_report.txt")

    if not results_path or not run_dir:
        return None

    results_lookup = parse_results_tsv(results_path)

    tickets_sys  = parse_tickets_report(tickets_sys_path)  if tickets_sys_path  else []
    tickets_rnd  = parse_tickets_report(tickets_rnd_path)  if tickets_rnd_path  else []
    verdicts_sys = parse_verdict_legs(verdict_sys_path)    if verdict_sys_path  else {}
    verdicts_rnd = parse_verdict_legs(verdict_rnd_path)    if verdict_rnd_path  else {}

    # Pools séparés
    pool_system = build_pool_from_jouables(run_dir, results_lookup, mode="SYSTEM", min_odd=min_odd)
    pool_random = build_pool_from_jouables(run_dir, results_lookup, mode="RANDOM", min_odd=min_odd)

    # Statistiques RANDOM (O15) : taux de passage réel
    random_stats = None
    if pool_random:
        n_won_r = sum(1 for p in pool_random if p["result"] == 1)
        random_stats = {
            "pool_size": len(pool_random),
            "n_won":     n_won_r,
            "win_rate":  round(100.0 * n_won_r / len(pool_random), 1),
            "losers": [
                f"{p['home']} vs {p['away']} ({p.get('ft_score','?')})"
                for p in pool_random if p["result"] == 0
            ],
        }

    # Combos précalculées par pool
    combos_sys, odds_sys, nwon_sys, wr_sys = _combos_for_pool(pool_system)
    combos_rnd, odds_rnd, nwon_rnd, wr_rnd = _combos_for_pool(pool_random)

    has_sys_combos = bool(combos_sys)
    has_rnd_combos = bool(combos_rnd)

    if not has_sys_combos and not has_rnd_combos:
        return {
            "date":          str(day),
            "status":        "POOL_TOO_SMALL",
            "pool_system":   len(pool_system),
            "pool_random":   len(pool_random),
            "random_stats":  random_stats,
            "tickets_joues": [],
        }

    best_winning_sys = next((c for c in combos_sys if c["is_won"]), None)
    best_winning_rnd = next((c for c in combos_rnd if c["is_won"]), None)

    all_tickets = (
        [(t, verdicts_sys, "SYSTEM") for t in tickets_sys]
        + [(t, verdicts_rnd, "RANDOM") for t in tickets_rnd]
    )

    if not all_tickets:
        return {
            "date":              str(day),
            "status":            "NO_TICKET",
            "pool_system":       len(pool_system),
            "pool_random":       len(pool_random),
            "random_stats":      random_stats,
            "n_combos_sys":      len(combos_sys),
            "n_won_sys":         nwon_sys,
            "win_ratio_sys":     wr_sys,
            "n_combos_rnd":      len(combos_rnd),
            "n_won_rnd":         nwon_rnd,
            "win_ratio_rnd":     wr_rnd,
            "tickets_joues":     [],
        }

    # Pour la rétrocompatibilité avec le code qui s'attend à un seul pool
    # (champs globaux = SYSTEM par défaut)
    if not combos_sys and not combos_rnd:
        return {
            "date":           str(day),
            "status":         "NO_COMBOS",
            "pool_system":    len(pool_system),
            "pool_random":    len(pool_random),
            "random_stats":   random_stats,
            "tickets_joues":  [],
        }

    # Rétrocompatibilité champs "globaux" = SYSTEM
    all_odds       = odds_sys if odds_sys else odds_rnd
    n_won_total    = nwon_sys if odds_sys else nwon_rnd
    win_ratio_pool = wr_sys   if odds_sys else wr_rnd
    best_winning   = best_winning_sys or best_winning_rnd

    day_results = []
    for ticket, verdicts_map, strategy in all_tickets:
        tid     = ticket["ticket_id"]
        t_odd   = ticket["total_odd"]
        verdict = verdicts_map.get(tid, "PENDING")

        # Pool propre selon la stratégie du ticket
        if strategy == "RANDOM":
            t_odds   = odds_rnd
            t_nwon   = nwon_rnd
            t_ncombos = len(combos_rnd)
            t_wr     = wr_rnd
        else:
            t_odds   = odds_sys
            t_nwon   = nwon_sys
            t_ncombos = len(combos_sys)
            t_wr     = wr_sys

        if not t_odds:
            continue  # Pas de pool pour ce type de ticket ce jour

        pct  = _percentile_of(t_odd, t_odds)
        rank = _rank_of(t_odd, t_odds)
        flag = _determine_flag(verdict, pct, t_nwon, t_ncombos)

        day_results.append({
            "ticket_id":      tid,
            "strategy":       strategy,
            "total_odd":      t_odd,
            "verdict":        verdict,
            "percentile_odd": pct,
            "rank":           rank,
            "n_combos":       t_ncombos,
            "n_won":          t_nwon,
            "win_ratio_pool": t_wr,
            "flag":           flag,
            "picks":          ticket.get("picks", []),
        })

    return {
        "date":              str(day),
        "status":            "OK",
        "pool_system":       len(pool_system),
        "pool_random":       len(pool_random),
        "random_stats":      random_stats,
        # Champs globaux (SYSTEM) pour rétrocompatibilité
        "n_combos":          len(combos_sys),
        "n_won":             nwon_sys,
        "win_ratio_pool":    wr_sys,
        "pool_best_odd":     odds_sys[0] if odds_sys else None,
        "best_winning_combo": best_winning_sys,
        # Champs RANDOM
        "n_combos_rnd":      len(combos_rnd),
        "n_won_rnd":         nwon_rnd,
        "win_ratio_rnd":     wr_rnd,
        "pool_best_odd_rnd": odds_rnd[0] if odds_rnd else None,
        "best_winning_combo_rnd": best_winning_rnd,
        "tickets_joues":     day_results,
    }


# ── CLI runner ────────────────────────────────────────────────────────────────

def run_counterfactual(
    days: Optional[int] = None,
    output_path: Optional[Path] = None,
    verbose: bool = True,
    min_odd: float = MIN_ODD,
) -> List[Dict[str, Any]]:
    """
    Lance l'analyse contrefactuelle v3 sur toutes (ou les N dernières) journées d'archive.
    """
    analyse_dirs = list_analyse_dirs(days=days)
    if not analyse_dirs:
        if verbose:
            print("Aucun dossier d'archive trouvé.")
        return []

    results = []
    n_catastrophic = 0
    n_malchanceux  = 0
    n_optimal      = 0
    n_bon_choix    = 0

    for day, adir in analyse_dirs:
        result = analyze_day(day, adir, min_odd=min_odd)
        if result is None:
            if verbose:
                print(f"[{day}] — données insuffisantes (pas de results.tsv ou run_dir)")
            continue

        results.append(result)

        if not verbose:
            continue

        status = result["status"]
        rs = result.get("random_stats")
        rs_str = (
            f" | O15 jouables: {rs['n_won']}/{rs['pool_size']} réels ({rs['win_rate']:.0f}%)"
            if rs else ""
        )

        if status != "OK":
            print(f"[{day}] status={status} | SYSTEM pool={result.get('pool_system', 0)}{rs_str}")
            continue

        for t in result["tickets_joues"]:
            flag      = t.get("flag", "")
            rank      = t.get("rank", "?")
            n_combos  = t.get("n_combos", 0)
            pct       = t.get("percentile_odd")
            pct_str   = f"percentile {pct:.0f}% (0%=plus basse cote, 100%=plus haute)" if pct is not None else "N/A"
            n_won     = t.get("n_won", 0)
            win_ratio = t.get("win_ratio_pool", 0)
            verdict   = t.get("verdict", "?")
            strategy  = t.get("strategy", "SYSTEM")
            picks_str = "+".join(p.get("bet_key", p.get("metric", "?")) for p in t.get("picks", [])[:4])

            flag_display = {
                "CATASTROPHIQUE":        "CATASTROPHIQUE ⚠️",
                "MALCHANCEUX":           "MALCHANCEUX",
                "OPTIMAL":               "OPTIMAL ✓",
                "BON_CHOIX_MALCHANCEUX": "BON_CHOIX_MALCHANCEUX",
            }.get(flag, flag or "")

            if flag == "CATASTROPHIQUE":
                n_catastrophic += 1
            elif flag == "MALCHANCEUX":
                n_malchanceux += 1
            elif flag == "OPTIMAL":
                n_optimal += 1
            elif flag == "BON_CHOIX_MALCHANCEUX":
                n_bon_choix += 1

            # Ligne de contexte selon la stratégie
            if strategy == "RANDOM":
                rs_cur = result.get("random_stats")
                pool_line = (
                    f"           | RANDOM pool (O15): {rs_cur['n_won']}/{rs_cur['pool_size']} réels ({rs_cur['win_rate']:.0f}%)"
                    + (f" — perdants: {', '.join(rs_cur['losers'][:3])}" if rs_cur and rs_cur.get("losers") else "")
                    + f" | Combos: {n_won}/{n_combos} gagnantes ({win_ratio:.1f}%)"
                    if rs_cur else f"           | RANDOM pool | Combos: {n_won}/{n_combos} gagnantes ({win_ratio:.1f}%)"
                )
            else:
                rs_cur = result.get("random_stats")
                o15_note = (
                    f" [O15: {rs_cur['n_won']}/{rs_cur['pool_size']} réels ({rs_cur['win_rate']:.0f}%)]"
                    if rs_cur else ""
                )
                pool_line = (
                    f"           | SYSTEM pool: {result.get('pool_system',0)} picks{o15_note}"
                    f" | Combos: {n_won}/{n_combos} gagnantes ({win_ratio:.1f}%)"
                )

            print(
                f"{day} [{strategy}] | Joué: {picks_str} | Cote: ×{t['total_odd']:.2f} | Résultat: {verdict}\n"
                f"{pool_line}\n"
                f"           | Rang: {rank}/{n_combos} | Percentile cote: {pct_str}\n"
                f"           | Flag: {flag_display}\n"
            )

    if verbose:
        n_ok = sum(1 for r in results if r["status"] == "OK")
        n_tickets = sum(len(r.get("tickets_joues", [])) for r in results if r["status"] == "OK")
        print("──── RÉSUMÉ ────")
        print(f"Jours analysés (OK) : {n_ok}")
        print(f"Tickets analysés    : {n_tickets}")
        print(f"OPTIMAL             : {n_optimal}")
        print(f"BON_CHOIX_MALCHANCEUX : {n_bon_choix}")
        print(f"MALCHANCEUX         : {n_malchanceux}")
        print(f"CATASTROPHIQUE      : {n_catastrophic}")

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        if verbose:
            print(f"\nRésultats exportés : {output_path}")

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyse contrefactuelle v3 — Triskèle V2 (résultats réels depuis results.tsv)"
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Nombre de jours à analyser (par défaut : tous)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Chemin de sortie JSON (ex: data/counterfactual_report.json)"
    )
    parser.add_argument(
        "--min-odd", type=float, default=MIN_ODD,
        help=f"Cote minimale pour un pick candidat (défaut: {MIN_ODD})"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Pas d'affichage ligne par ligne"
    )
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else None
    run_counterfactual(
        days=args.days,
        output_path=output_path,
        verbose=not args.quiet,
        min_odd=args.min_odd,
    )


if __name__ == "__main__":
    main()
