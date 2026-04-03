# services/ticket_optimizer.py
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import services.ticket_builder as tb
from services.ticket_builder import BuilderTuning, Ticket, TicketBuildOutput


# =========================================================
# CONFIG
# =========================================================
DEFAULT_ARCHIVE_DIR = Path("archive")
DEFAULT_OUTPUT_DIR = Path("data/optimizer")
DEFAULT_TOP_N = 10
DEFAULT_TRIALS = 1000
DEFAULT_MAX_DAYS = 60
DEFAULT_VALID_DAYS = 12
DEFAULT_JOBS = 1
DEFAULT_START_BANKROLL = 100.0

RUIN_STREAK_LIMIT = 6  # au-delà = profil quasi disqualifié
MIN_DECIDED_TICKETS_VALID = 8  # garde-fou contre les faux profils "parfaits" sur trop peu de tickets


# =========================================================
# DATASETS
# =========================================================
@dataclass(frozen=True)
class DayDataset:
    day: str
    predictions_tsv: Path
    verdict_file: Path


@dataclass
class PipelineMetrics:
    tickets: int = 0
    wins: int = 0
    losses: int = 0
    unknown: int = 0
    decided_tickets: int = 0
    active_days: int = 0
    avg_tickets_per_active_day: float = 0.0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    unknown_rate: float = 0.0
    max_loss_streak: int = 0
    max_win_streak: int = 0

    # métriques financières
    profit_flat: float = 0.0
    yield_flat: float = 0.0
    max_drawdown: float = 0.0
    final_bankroll_flat: float = DEFAULT_START_BANKROLL
    bankroll_multiple_flat: float = 1.0

    def to_dict(self) -> dict:
        return {
            "tickets": self.tickets,
            "wins": self.wins,
            "losses": self.losses,
            "unknown": self.unknown,
            "decided_tickets": self.decided_tickets,
            "active_days": self.active_days,
            "avg_tickets_per_active_day": round(self.avg_tickets_per_active_day, 4),
            "win_rate": round(self.win_rate, 4),
            "loss_rate": round(self.loss_rate, 4),
            "unknown_rate": round(self.unknown_rate, 4),
            "max_loss_streak": self.max_loss_streak,
            "max_win_streak": self.max_win_streak,
            "profit_flat": round(self.profit_flat, 4),
            "yield_flat": round(self.yield_flat, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "final_bankroll_flat": round(self.final_bankroll_flat, 4),
            "bankroll_multiple_flat": round(self.bankroll_multiple_flat, 4),
        }


@dataclass
class ProfileResult:
    rank_score: float
    tuning: BuilderTuning
    system: PipelineMetrics
    random_o15: PipelineMetrics
    combined: dict

    def to_dict(self) -> dict:
        return {
            "rank_score": round(self.rank_score, 6),
            "tuning": _serialize_tuning(self.tuning),
            "system": self.system.to_dict(),
            "random_o15": self.random_o15.to_dict(),
            "combined": self.combined,
        }


@dataclass
class DayPipelineEval:
    ticket_results: List[Optional[bool]]
    ticket_profits: List[float]
    active_day: bool


@dataclass
class DayEval:
    day: str
    system: DayPipelineEval
    random_o15: DayPipelineEval


# =========================================================
# HELPERS DATA DISCOVERY
# =========================================================
def _iter_day_dirs(archive_dir: Path) -> Iterable[Path]:
    if not archive_dir.exists():
        return
    all_dirs: List[Path] = []
    for p in archive_dir.iterdir():
        if p.is_dir() and p.name.startswith("analyse_"):
            all_dirs.append(p)
    for subdir in archive_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("analyse_"):
            for p in subdir.iterdir():
                if p.is_dir() and p.name.startswith("analyse_"):
                    all_dirs.append(p)
    yield from sorted(all_dirs, key=lambda p: p.name)


def _pick_run_dir(day_dir: Path) -> Optional[Path]:
    candidates = [p for p in day_dir.iterdir() if p.is_dir()]
    candidates = sorted(candidates, key=lambda p: p.name, reverse=True)
    for c in candidates:
        if (c / "predictions.tsv").exists():
            return c
    if (day_dir / "predictions.tsv").exists():
        return day_dir
    return None


def _find_verdict_file(day_dir: Path, run_dir: Path) -> Optional[Path]:
    for p in [
        day_dir / "verdict_post_analyse.txt",
        run_dir / "verdict_post_analyse.txt",
        Path("data/verdict_post_analyse.txt"),
    ]:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def discover_datasets(archive_dir: Path, max_days: Optional[int]) -> List[DayDataset]:
    out: List[DayDataset] = []

    for day_dir in _iter_day_dirs(archive_dir):
        run_dir = _pick_run_dir(day_dir)
        if run_dir is None:
            continue

        verdict = _find_verdict_file(day_dir, run_dir)
        if verdict is None:
            continue

        day = day_dir.name.replace("analyse_", "")
        pred = run_dir / "predictions.tsv"
        if not pred.exists():
            continue

        out.append(DayDataset(day=day, predictions_tsv=pred, verdict_file=verdict))

    out.sort(key=lambda x: x.day)
    if max_days is not None and max_days > 0:
        out = out[-max_days:]
    return out


def _split_datasets_chronological(
    datasets: List[DayDataset],
    valid_days: int,
) -> Tuple[List[DayDataset], List[DayDataset]]:
    if not datasets:
        return [], []

    vd = max(1, int(valid_days or 1))
    if len(datasets) <= vd:
        return list(datasets), []

    train = datasets[:-vd]
    valid = datasets[-vd:]
    return train, valid


# =========================================================
# VERDICTS
# =========================================================
_VERDICT_CACHE: Dict[str, Dict[Tuple[str, str], str]] = {}


_RESULTS_TSV_PATH = Path("data/results.tsv")
_O15_FT_FAM = "O15_FT"


def _load_o15_verdicts_from_results() -> Dict[Tuple[str, str], str]:
    """
    Calcule les verdicts O15_FT depuis results.tsv.
    Format TSV : date | league | home | away | fixture_id | score_FT | status | score_HT
    WIN si total buts FT > 1.5, LOSS sinon.
    """
    out: Dict[Tuple[str, str], str] = {}
    if not _RESULTS_TSV_PATH.exists():
        return out

    with _RESULTS_TSV_PATH.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 6:
                continue
            fixture_id = parts[4].strip()
            score_ft   = parts[5].strip()
            if not fixture_id or "-" not in score_ft:
                continue
            try:
                g1, g2 = score_ft.split("-", 1)
                total = int(g1.strip()) + int(g2.strip())
            except (ValueError, AttributeError):
                continue
            verdict = "WIN" if total > 1 else "LOSS"
            out[(fixture_id, _O15_FT_FAM)] = verdict

    return out


def _parse_verdict_file(path: Path) -> Dict[Tuple[str, str], str]:
    """
    Map:
      (match_id, bet_family) -> WIN / LOSS

    Enrichi automatiquement avec les verdicts O15_FT calculés depuis results.tsv
    pour les match_ids non couverts par le fichier verdict principal.
    """
    cache_key = str(path.resolve())
    cached = _VERDICT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    out: Dict[Tuple[str, str], str] = {}

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line.startswith("TSV:"):
                continue

            parts = line[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue

            match_id = parts[0].strip()
            bet_key = parts[5].strip()
            played = parts[9].strip()
            ev = parts[10].strip().upper()

            if played != "1":
                continue
            if ev not in ("WIN", "LOSS"):
                continue

            fam = tb._norm_bet_family(bet_key)
            out[(match_id, fam)] = ev

    # Enrichissement O15_FT depuis results.tsv (comble les match_ids manquants)
    o15_from_results = _load_o15_verdicts_from_results()
    for key, verdict in o15_from_results.items():
        if key not in out:
            out[key] = verdict

    _VERDICT_CACHE[cache_key] = out
    return out


def _ticket_outcome(ticket: Ticket, verdict_map: Dict[Tuple[str, str], str]) -> Optional[bool]:
    """
    True  = ticket win
    False = ticket loss
    None  = inconnu
    """
    statuses: List[str] = []
    for p in ticket.picks:
        key = (p.match_id, tb._norm_bet_family(p.bet_key))
        ev = verdict_map.get(key)
        if ev is None:
            return None
        statuses.append(ev)

    return all(x == "WIN" for x in statuses)


# =========================================================
# SAFE RUN TICKET BUILDER
# =========================================================
class _PatchedBuilderIO:
    def __init__(self, workdir: Path):
        self.workdir = workdir

        self.old_env_maestro = os.environ.get("TRISKELE_MAESTRO")
        self.old_env_run_dir = os.environ.get("TRISKELE_RUN_DIR")
        self.old_env_optimizer_fast = os.environ.get("TRISKELE_OPTIMIZER_FAST")

        self.old_tickets_tsv = tb.TICKETS_TSV_FILE
        self.old_o15_tsv = tb.TICKETS_O15_RANDOM_TSV_FILE
        self.old_report_global = tb.TICKETS_REPORT_GLOBAL_FILE
        self.old_o15_report_global = tb.TICKETS_O15_REPORT_GLOBAL_FILE
        self.old_maestro_log = tb.MAESTRO_LOG_FILE

    def __enter__(self):
        self.workdir.mkdir(parents=True, exist_ok=True)

        os.environ["TRISKELE_MAESTRO"] = "0"
        os.environ["TRISKELE_RUN_DIR"] = str(self.workdir)
        os.environ["TRISKELE_OPTIMIZER_FAST"] = "1"

        tb.TICKETS_TSV_FILE = self.workdir / "tickets.tsv"
        tb.TICKETS_O15_RANDOM_TSV_FILE = self.workdir / "tickets_o15_random.tsv"
        tb.TICKETS_REPORT_GLOBAL_FILE = self.workdir / "tickets_report_global.txt"
        tb.TICKETS_O15_REPORT_GLOBAL_FILE = self.workdir / "tickets_o15_random_report_global.txt"
        tb.MAESTRO_LOG_FILE = self.workdir / "tickets_maestro_log.txt"
        return self

    def __exit__(self, exc_type, exc, tb_exc):
        tb.TICKETS_TSV_FILE = self.old_tickets_tsv
        tb.TICKETS_O15_RANDOM_TSV_FILE = self.old_o15_tsv
        tb.TICKETS_REPORT_GLOBAL_FILE = self.old_report_global
        tb.TICKETS_O15_REPORT_GLOBAL_FILE = self.old_o15_report_global
        tb.MAESTRO_LOG_FILE = self.old_maestro_log

        if self.old_env_maestro is None:
            os.environ.pop("TRISKELE_MAESTRO", None)
        else:
            os.environ["TRISKELE_MAESTRO"] = self.old_env_maestro

        if self.old_env_run_dir is None:
            os.environ.pop("TRISKELE_RUN_DIR", None)
        else:
            os.environ["TRISKELE_RUN_DIR"] = self.old_env_run_dir

        if self.old_env_optimizer_fast is None:
            os.environ.pop("TRISKELE_OPTIMIZER_FAST", None)
        else:
            os.environ["TRISKELE_OPTIMIZER_FAST"] = self.old_env_optimizer_fast


# =========================================================
# HELPERS FINANCE / PROFIT
# =========================================================
def _safe_float(v: object) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _ticket_total_odd(ticket: Ticket) -> Optional[float]:
    candidate_attrs = [
        "total_odd",
        "total_odds",
        "odd",
        "odds",
        "combined_odd",
        "combo_odd",
        "ticket_odd",
    ]

    for attr in candidate_attrs:
        if hasattr(ticket, attr):
            val = _safe_float(getattr(ticket, attr))
            if val is not None and val > 0:
                return val

    picks = getattr(ticket, "picks", None)
    if picks:
        prod = 1.0
        found = False
        for p in picks:
            for attr in ("odd", "odds", "cote", "price", "decimal_odd", "decimal_odds"):
                if hasattr(p, attr):
                    val = _safe_float(getattr(p, attr))
                    if val is not None and val > 0:
                        prod *= val
                        found = True
                        break
        if found and prod > 0:
            return prod

    return None


def _flat_profit_for_ticket(ticket: Ticket, outcome: Optional[bool]) -> float:
    """
    Stake fixe = 1 unité par ticket décidé.
    WIN  => odd - 1
    LOSS => -1
    None => 0
    """
    if outcome is None:
        return 0.0
    if outcome is False:
        return -1.0

    odd = _ticket_total_odd(ticket)
    if odd is None or odd <= 1.0:
        return 0.0

    return odd - 1.0


def _compute_max_drawdown(equity_curve: List[float]) -> float:
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for v in equity_curve:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    return max_dd


# =========================================================
# SCORING
# =========================================================
def _finalize_metrics(
    ticket_results: List[Optional[bool]],
    ticket_profits: List[float],
    active_days: int,
) -> PipelineMetrics:
    m = PipelineMetrics()
    m.active_days = active_days
    m.tickets = len(ticket_results)

    current_loss_streak = 0
    current_win_streak = 0
    equity = 0.0
    equity_curve: List[float] = [0.0]

    for idx, r in enumerate(ticket_results):
        if r is True:
            m.wins += 1
            current_win_streak += 1
            current_loss_streak = 0
            if current_win_streak > m.max_win_streak:
                m.max_win_streak = current_win_streak
        elif r is False:
            m.losses += 1
            current_loss_streak += 1
            current_win_streak = 0
            if current_loss_streak > m.max_loss_streak:
                m.max_loss_streak = current_loss_streak
        else:
            m.unknown += 1
            current_win_streak = 0
            current_loss_streak = 0

        profit = ticket_profits[idx] if idx < len(ticket_profits) else 0.0
        equity += profit
        equity_curve.append(equity)

    decided = m.wins + m.losses
    m.decided_tickets = decided

    if decided > 0:
        m.win_rate = m.wins / decided
        m.loss_rate = m.losses / decided

    if m.tickets > 0:
        m.unknown_rate = m.unknown / m.tickets

    if active_days > 0:
        m.avg_tickets_per_active_day = m.tickets / active_days

    m.profit_flat = sum(ticket_profits)
    if decided > 0:
        m.yield_flat = m.profit_flat / decided

    m.max_drawdown = _compute_max_drawdown(equity_curve)
    m.final_bankroll_flat = DEFAULT_START_BANKROLL + m.profit_flat
    m.bankroll_multiple_flat = (
        m.final_bankroll_flat / DEFAULT_START_BANKROLL if DEFAULT_START_BANKROLL > 0 else 0.0
    )

    return m


def _mean_pipeline_values(system_m: PipelineMetrics, random_m: PipelineMetrics) -> dict:
    return {
        "mean_win_rate": (system_m.win_rate + random_m.win_rate) / 2.0,
        "mean_tickets_per_active_day": (
            system_m.avg_tickets_per_active_day + random_m.avg_tickets_per_active_day
        ) / 2.0,
        "mean_unknown_rate": (system_m.unknown_rate + random_m.unknown_rate) / 2.0,
        "worst_max_loss_streak": max(system_m.max_loss_streak, random_m.max_loss_streak),
        "best_max_win_streak": max(system_m.max_win_streak, random_m.max_win_streak),
        "min_decided_tickets": min(system_m.decided_tickets, random_m.decided_tickets),
        "mean_profit_flat": (system_m.profit_flat + random_m.profit_flat) / 2.0,
        "mean_yield_flat": (system_m.yield_flat + random_m.yield_flat) / 2.0,
        "worst_max_drawdown": max(system_m.max_drawdown, random_m.max_drawdown),
        "mean_final_bankroll_flat": (system_m.final_bankroll_flat + random_m.final_bankroll_flat) / 2.0,
        "mean_bankroll_multiple_flat": (
            system_m.bankroll_multiple_flat + random_m.bankroll_multiple_flat
        ) / 2.0,
    }


def _profile_rank_score(
    train_system: PipelineMetrics,
    train_random: PipelineMetrics,
    valid_system: PipelineMetrics,
    valid_random: PipelineMetrics,
) -> float:
    """
    Priorités utilisateur :
    - éviter les grosses séries de pertes
    - garder du volume
    - surtout être bon en validation chronologique
    - intégrer profit / yield / drawdown
    - pénaliser les profils trop beaux en train mais moins bons en validation
    """
    train_c = _mean_pipeline_values(train_system, train_random)
    valid_c = _mean_pipeline_values(valid_system, valid_random)

    use_valid = (valid_system.tickets + valid_random.tickets) > 0
    ref = valid_c if use_valid else train_c

    score = 0.0

    # Base — win_rate réduit car streak devient métrique dominante (martingale)
    score += ref["mean_win_rate"] * 70.0
    score += ref["mean_tickets_per_active_day"] * 10.0

    # Financier
    score += ref["mean_profit_flat"] * 2.5
    score += ref["mean_yield_flat"] * 100.0

    # Bonus équilibre SYSTEM / RANDOM
    ref_min_tickets = min(
        valid_system.avg_tickets_per_active_day if use_valid else train_system.avg_tickets_per_active_day,
        valid_random.avg_tickets_per_active_day if use_valid else train_random.avg_tickets_per_active_day,
    )
    score += ref_min_tickets * 2.0

    # Pénalité inconnus
    score -= ref["mean_unknown_rate"] * 30.0

    # Pénalité streak — continue et agressive (alignée martingale)
    # En martingale, chaque défaite supplémentaire coûte exponentiellement plus cher.
    worst_streak = int(ref["worst_max_loss_streak"])
    if worst_streak >= RUIN_STREAK_LIMIT:
        score -= 1000.0
    elif worst_streak == 5:
        score -= 250.0   # était -80
    elif worst_streak == 4:
        score -= 80.0    # était -20
    elif worst_streak == 3:
        score -= 15.0    # nouveau : série de 3 déjà pénalisée

    # Pénalité drawdown — plus élevée car martingale sensible aux creux
    score -= ref["worst_max_drawdown"] * 6.0  # était 3.0

    if use_valid:
        min_decided = int(valid_c["min_decided_tickets"])
        if min_decided < MIN_DECIDED_TICKETS_VALID:
            score -= (MIN_DECIDED_TICKETS_VALID - min_decided) * 8.0

        gap_wr = max(0.0, float(train_c["mean_win_rate"]) - float(valid_c["mean_win_rate"]))
        gap_tickets = max(
            0.0,
            float(train_c["mean_tickets_per_active_day"]) - float(valid_c["mean_tickets_per_active_day"]),
        )
        gap_profit = max(0.0, float(train_c["mean_profit_flat"]) - float(valid_c["mean_profit_flat"]))
        gap_yield = max(0.0, float(train_c["mean_yield_flat"]) - float(valid_c["mean_yield_flat"]))

        score -= gap_wr * 80.0
        score -= gap_tickets * 3.0
        score -= gap_profit * 1.5
        score -= gap_yield * 100.0

    return score


# =========================================================
# TUNING SEARCH SPACE
# =========================================================
def _sample_tuning(rng: random.Random) -> BuilderTuning:
    """Recherche aléatoire dans l'espace resserré (valeurs non présentes dans les top profils retirées)."""
    excluded_options = [
        frozenset({"HT1X", "HT05"}),
        frozenset({"HT1X"}),
        frozenset({"HT05"}),
        frozenset(),
    ]

    weight_baseline = rng.choice([0.62, 0.66, 0.70, 0.74, 0.78])
    weight_ceil = rng.choice([0.92, 0.95, 1.00])  # retiré 0.98 (absent des top profils)
    if weight_ceil <= weight_baseline:
        weight_ceil = min(1.00, weight_baseline + 0.15)

    two_team_low = rng.choice([0.55, 0.58, 0.60, 0.63, 0.66])  # retiré 0.70
    two_team_high = rng.choice([0.80, 0.82, 0.85, 0.88])  # retiré 0.78
    if two_team_high <= two_team_low:
        two_team_high = min(0.95, two_team_low + 0.15)

    target_odd = rng.choice([2.30, 2.40])  # retiré 2.00, 2.10, 2.20 (absents des top profils)
    min_accept_odd = rng.choice([1.60, 1.70, 1.80])  # retiré 1.90
    if min_accept_odd > target_odd:
        min_accept_odd = target_odd

    return BuilderTuning(
        global_bet_min_decided=rng.choice([5, 7, 10, 12]),
        global_bet_min_winrate=rng.choice([0.62, 0.65, 0.68, 0.70, 0.72]),  # retiré 0.75
        league_bet_min_winrate=rng.choice([0.62, 0.65, 0.68, 0.70, 0.72, 0.75]),
        league_bet_require_data=rng.choice([True, False]),
        team_min_decided=rng.choice([6, 8, 10, 12, 15]),
        team_min_winrate=rng.choice([0.68, 0.70, 0.72, 0.75, 0.78]),  # retiré 0.80
        two_team_high=two_team_high,
        two_team_low=two_team_low,
        weight_min=rng.choice([0.8, 1.0, 1.2]),
        weight_max=rng.choice([1.8, 2.0, 2.2, 2.5]),  # retiré 3.0
        weight_baseline=weight_baseline,
        weight_ceil=weight_ceil,
        topk_size=rng.choice([3, 5, 8, 10]),
        topk_uniform_draw=rng.choice([True, False]),
        prefer_3legs_delta=rng.choice([0.00, 0.02, 0.03, 0.05, 0.08]),
        search_budget_ms_system=rng.choice([300, 500, 800]),  # retiré 1200
        search_budget_ms_random=rng.choice([300, 500, 800]),  # retiré 1200
        excluded_bet_groups=rng.choice(excluded_options),
        target_odd=target_odd,
        min_accept_odd=min_accept_odd,
        rich_day_match_count=rng.choice([16, 18, 20]),  # retiré 22
        day_max_windows_poor=rng.choice([1, 2]),
        day_max_windows_rich=rng.choice([2, 3, 4]),
        min_side_matches_for_split=rng.choice([3, 4, 5]),
        split_gap_weight=rng.choice([0.20, 0.30, 0.35, 0.45, 0.60]),
        league_ranking_mode=rng.choice(["CLASSIC", "COMPOSITE"]),
        team_ranking_mode=rng.choice(["CLASSIC", "COMPOSITE"]),
        system_build_source=rng.choice(["LEAGUE", "TEAM"]),
        system_select_source=rng.choice(["LEAGUE", "TEAM", "HYBRID"]),
        hybrid_alpha=rng.choice([0.4, 0.5, 0.6, 0.7, 0.8]),
        random_build_source=rng.choice(["LEAGUE", "TEAM"]),
        random_select_source=rng.choice(["LEAGUE", "TEAM"]),
    )


def _load_saved_top_profiles(path: Path) -> List[BuilderTuning]:
    """Charge les top profils sauvegardés pour la recherche focalisée."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        profiles = []
        for entry in data:
            t = entry.get("tuning", {})
            if not t:
                continue
            eg = t.get("excluded_bet_groups", [])
            profiles.append(BuilderTuning(
                global_bet_min_decided=t.get("global_bet_min_decided", 12),
                global_bet_min_winrate=t.get("global_bet_min_winrate", 0.65),
                league_bet_min_winrate=t.get("league_bet_min_winrate", 0.72),
                league_bet_require_data=t.get("league_bet_require_data", True),
                team_min_decided=t.get("team_min_decided", 8),
                team_min_winrate=t.get("team_min_winrate", 0.70),
                two_team_high=t.get("two_team_high", 0.85),
                two_team_low=t.get("two_team_low", 0.58),
                weight_min=t.get("weight_min", 1.0),
                weight_max=t.get("weight_max", 2.0),
                weight_baseline=t.get("weight_baseline", 0.74),
                weight_ceil=t.get("weight_ceil", 1.0),
                topk_size=t.get("topk_size", 8),
                topk_uniform_draw=t.get("topk_uniform_draw", False),
                prefer_3legs_delta=t.get("prefer_3legs_delta", 0.0),
                search_budget_ms_system=t.get("search_budget_ms_system", 500),
                search_budget_ms_random=t.get("search_budget_ms_random", 500),
                excluded_bet_groups=frozenset(eg),
                target_odd=t.get("target_odd", 2.4),
                min_accept_odd=t.get("min_accept_odd", 1.8),
                rich_day_match_count=t.get("rich_day_match_count", 16),
                day_max_windows_poor=t.get("day_max_windows_poor", 1),
                day_max_windows_rich=t.get("day_max_windows_rich", 4),
                min_side_matches_for_split=t.get("min_side_matches_for_split", 5),
                split_gap_weight=t.get("split_gap_weight", 0.60),
                league_ranking_mode=t.get("league_ranking_mode", "CLASSIC"),
                team_ranking_mode=t.get("team_ranking_mode", "CLASSIC"),
                system_build_source=t.get("system_build_source", "LEAGUE"),
                system_select_source=t.get("system_select_source", "LEAGUE"),
                hybrid_alpha=t.get("hybrid_alpha", 0.6),
                random_build_source=t.get("random_build_source", "LEAGUE"),
                random_select_source=t.get("random_select_source", "LEAGUE"),
            ))
        return profiles
    except Exception as e:
        print(f"⚠️ [WARN] Chargement top profils échoué : {e}")
        return []


def _sample_tuning_focused(rng: random.Random, top_profiles: List[BuilderTuning]) -> BuilderTuning:
    """
    Génère un profil en mutant légèrement un top profil existant.
    Chaque paramètre a 30% de chance d'être modifié, 70% de rester identique au parent.
    Permet d'explorer le voisinage des bons profils sans repartir de zéro.
    """
    parent = rng.choice(top_profiles)
    MUTATION_RATE = 0.30

    def maybe(options, current):
        if rng.random() < MUTATION_RATE:
            return rng.choice(options)
        return current

    excluded_options = [
        frozenset({"HT1X", "HT05"}),
        frozenset({"HT1X"}),
        frozenset({"HT05"}),
        frozenset(),
    ]

    weight_baseline = maybe([0.62, 0.66, 0.70, 0.74, 0.78], parent.weight_baseline)
    weight_ceil = maybe([0.92, 0.95, 1.00], parent.weight_ceil)
    if weight_ceil <= weight_baseline:
        weight_ceil = min(1.0, weight_baseline + 0.15)

    two_team_low = maybe([0.55, 0.58, 0.60, 0.63, 0.66], parent.two_team_low)
    two_team_high = maybe([0.80, 0.82, 0.85, 0.88], parent.two_team_high)
    if two_team_high <= two_team_low:
        two_team_high = min(0.95, two_team_low + 0.15)

    target_odd = maybe([2.30, 2.40], parent.target_odd)
    min_accept_odd = maybe([1.60, 1.70, 1.80], parent.min_accept_odd)
    if min_accept_odd > target_odd:
        min_accept_odd = target_odd

    return BuilderTuning(
        global_bet_min_decided=maybe([5, 7, 10, 12], parent.global_bet_min_decided),
        global_bet_min_winrate=maybe([0.62, 0.65, 0.68, 0.70, 0.72], parent.global_bet_min_winrate),
        league_bet_min_winrate=maybe([0.62, 0.65, 0.68, 0.70, 0.72, 0.75], parent.league_bet_min_winrate),
        league_bet_require_data=maybe([True, False], parent.league_bet_require_data),
        team_min_decided=maybe([6, 8, 10, 12, 15], parent.team_min_decided),
        team_min_winrate=maybe([0.68, 0.70, 0.72, 0.75, 0.78], parent.team_min_winrate),
        two_team_high=two_team_high,
        two_team_low=two_team_low,
        weight_min=maybe([0.8, 1.0, 1.2], parent.weight_min),
        weight_max=maybe([1.8, 2.0, 2.2, 2.5], parent.weight_max),
        weight_baseline=weight_baseline,
        weight_ceil=weight_ceil,
        topk_size=maybe([3, 5, 8, 10], parent.topk_size),
        topk_uniform_draw=maybe([True, False], parent.topk_uniform_draw),
        prefer_3legs_delta=maybe([0.00, 0.02, 0.03, 0.05, 0.08], parent.prefer_3legs_delta),
        search_budget_ms_system=maybe([300, 500, 800], parent.search_budget_ms_system),
        search_budget_ms_random=maybe([300, 500, 800], parent.search_budget_ms_random),
        excluded_bet_groups=maybe(excluded_options, parent.excluded_bet_groups),
        target_odd=target_odd,
        min_accept_odd=min_accept_odd,
        rich_day_match_count=maybe([16, 18, 20], parent.rich_day_match_count),
        day_max_windows_poor=maybe([1, 2], parent.day_max_windows_poor),
        day_max_windows_rich=maybe([2, 3, 4], parent.day_max_windows_rich),
        min_side_matches_for_split=maybe([3, 4, 5], parent.min_side_matches_for_split),
        split_gap_weight=maybe([0.20, 0.30, 0.35, 0.45, 0.60], parent.split_gap_weight),
        league_ranking_mode=maybe(["CLASSIC", "COMPOSITE"], parent.league_ranking_mode),
        team_ranking_mode=maybe(["CLASSIC", "COMPOSITE"], parent.team_ranking_mode),
        system_build_source=maybe(["LEAGUE", "TEAM"], parent.system_build_source),
        system_select_source=maybe(["LEAGUE", "TEAM", "HYBRID"], parent.system_select_source),
        hybrid_alpha=maybe([0.4, 0.5, 0.6, 0.7, 0.8], parent.hybrid_alpha),
        random_build_source=maybe(["LEAGUE", "TEAM"], parent.random_build_source),
        random_select_source=maybe(["LEAGUE", "TEAM"], parent.random_select_source),
    )


def _baseline_tuning() -> BuilderTuning:
    return BuilderTuning()


def _serialize_tuning(t: BuilderTuning) -> dict:
    d = asdict(t)
    d["excluded_bet_groups"] = sorted(list(t.excluded_bet_groups))
    return d


def _tuning_signature(t: BuilderTuning) -> str:
    d = _serialize_tuning(t)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def _build_trial_plan(trials: int, seed: int) -> List[BuilderTuning]:
    """
    Construit le plan de recherche :
    - 1 baseline
    - 60% focalisé autour des top profils sauvegardés (si disponibles)
    - reste : aléatoire dans l'espace resserré
    """
    rng = random.Random(seed)

    out: List[BuilderTuning] = []
    seen: set[str] = set()

    baseline = _baseline_tuning()
    out.append(baseline)
    seen.add(_tuning_signature(baseline))

    # Charger top profils pour recherche focalisée
    top_profiles = _load_saved_top_profiles(Path("data/optimizer/optimizer_top_profiles.json"))

    n_focused = int((trials - 1) * 0.50) if top_profiles else 0
    n_random = trials - 1 - n_focused

    if top_profiles:
        print(f"[optimizer] Recherche focalisée : {n_focused} essais autour de {len(top_profiles)} top profils + {n_random} aléatoires")
    else:
        print(f"[optimizer] Aucun top profil trouvé → recherche entièrement aléatoire ({n_random} essais)")

    attempt_guard = max(trials * 30, 2000)

    # Phase 1 : focalisée (mutation des top profils)
    focused_added = 0
    while focused_added < n_focused and attempt_guard > 0:
        attempt_guard -= 1
        t = _sample_tuning_focused(rng, top_profiles)
        sig = _tuning_signature(t)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(t)
        focused_added += 1

    # Phase 2 : aléatoire dans espace resserré
    while len(out) < trials and attempt_guard > 0:
        attempt_guard -= 1
        t = _sample_tuning(rng)
        sig = _tuning_signature(t)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(t)

    return out


def _build_match_to_fixture_map(predictions_tsv: Path) -> Dict[str, str]:
    """
    Extrait le mapping match_id → fixture_id depuis predictions.tsv.
    Format colonne 11 : "odd=X fixture=YYYYYYY"
    """
    out: Dict[str, str] = {}
    if not predictions_tsv.exists():
        return out
    with predictions_tsv.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue
            match_id = parts[0].strip()
            meta = parts[10].strip()
            if "fixture=" not in meta:
                continue
            try:
                fixture_id = meta.split("fixture=")[1].strip().split()[0]
                if match_id and fixture_id:
                    out[match_id] = fixture_id
            except (IndexError, ValueError):
                continue
    return out


def _enrich_verdict_map_with_results(
    verdict_map: Dict[Tuple[str, str], str],
    predictions_tsv: Path,
) -> Dict[Tuple[str, str], str]:
    """
    Complète verdict_map avec les verdicts O15_FT calculés depuis results.tsv,
    en utilisant le mapping match_id → fixture_id extrait des predictions.
    """
    o15_by_fixture = _load_o15_verdicts_from_results()
    if not o15_by_fixture:
        return verdict_map

    match_to_fixture = _build_match_to_fixture_map(predictions_tsv)
    if not match_to_fixture:
        return verdict_map

    enriched = dict(verdict_map)
    for match_id, fixture_id in match_to_fixture.items():
        key_match   = (match_id,   _O15_FT_FAM)
        key_fixture = (fixture_id, _O15_FT_FAM)
        if key_match not in enriched and key_fixture in o15_by_fixture:
            enriched[key_match] = o15_by_fixture[key_fixture]

    return enriched


# =========================================================
# EVALUATION
# =========================================================
def _evaluate_one_day(
    ds: DayDataset,
    tuning: BuilderTuning,
    tmp_root: Path,
) -> DayEval:
    verdict_map = _parse_verdict_file(ds.verdict_file)
    verdict_map = _enrich_verdict_map_with_results(verdict_map, ds.predictions_tsv)
    run_dir = tmp_root / ds.day

    with _PatchedBuilderIO(run_dir):
        out: TicketBuildOutput = tb.generate_tickets_from_tsv(
            str(ds.predictions_tsv),
            run_date=None,
            tuning=tuning,
        )

    system_results: List[Optional[bool]] = []
    system_profits: List[float] = []
    for ticket in out.tickets_system:
        outcome = _ticket_outcome(ticket, verdict_map)
        system_results.append(outcome)
        system_profits.append(_flat_profit_for_ticket(ticket, outcome))

    random_results: List[Optional[bool]] = []
    random_profits: List[float] = []
    for ticket in out.tickets_o15:
        outcome = _ticket_outcome(ticket, verdict_map)
        random_results.append(outcome)
        random_profits.append(_flat_profit_for_ticket(ticket, outcome))

    return DayEval(
        day=ds.day,
        system=DayPipelineEval(
            ticket_results=system_results,
            ticket_profits=system_profits,
            active_day=bool(out.tickets_system),
        ),
        random_o15=DayPipelineEval(
            ticket_results=random_results,
            ticket_profits=random_profits,
            active_day=bool(out.tickets_o15),
        ),
    )


def _aggregate_pipeline_metrics(
    day_evals: List[DayEval],
    *,
    pipeline_name: str,
) -> PipelineMetrics:
    ticket_results: List[Optional[bool]] = []
    ticket_profits: List[float] = []
    active_days = 0

    for day_eval in day_evals:
        pe = day_eval.system if pipeline_name == "system" else day_eval.random_o15
        ticket_results.extend(pe.ticket_results)
        ticket_profits.extend(pe.ticket_profits)
        if pe.active_day:
            active_days += 1

    return _finalize_metrics(
        ticket_results=ticket_results,
        ticket_profits=ticket_profits,
        active_days=active_days,
    )


def _evaluate_all_days(
    datasets: List[DayDataset],
    tuning: BuilderTuning,
    keep_temp: bool = False,
) -> List[DayEval]:
    tmp_root = Path(tempfile.mkdtemp(prefix="triskele_opt_"))
    out: List[DayEval] = []

    try:
        for ds in datasets:
            out.append(_evaluate_one_day(ds, tuning, tmp_root))
        return out
    finally:
        if keep_temp:
            print(f"[optimizer] temp conservé: {tmp_root}")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)


def evaluate_profile(
    datasets: List[DayDataset],
    tuning: BuilderTuning,
    keep_temp: bool = False,
    valid_days: int = DEFAULT_VALID_DAYS,
) -> ProfileResult:
    train_ds, valid_ds = _split_datasets_chronological(datasets, valid_days=valid_days)
    train_days = {d.day for d in train_ds}
    valid_days_set = {d.day for d in valid_ds}

    all_day_evals = _evaluate_all_days(
        datasets=datasets,
        tuning=tuning,
        keep_temp=keep_temp,
    )

    train_day_evals = [x for x in all_day_evals if x.day in train_days]
    valid_day_evals = [x for x in all_day_evals if x.day in valid_days_set]

    overall_system = _aggregate_pipeline_metrics(all_day_evals, pipeline_name="system")
    overall_random = _aggregate_pipeline_metrics(all_day_evals, pipeline_name="random")

    train_system = _aggregate_pipeline_metrics(train_day_evals, pipeline_name="system")
    train_random = _aggregate_pipeline_metrics(train_day_evals, pipeline_name="random")

    valid_system = _aggregate_pipeline_metrics(valid_day_evals, pipeline_name="system")
    valid_random = _aggregate_pipeline_metrics(valid_day_evals, pipeline_name="random")

    rank_score = _profile_rank_score(
        train_system=train_system,
        train_random=train_random,
        valid_system=valid_system,
        valid_random=valid_random,
    )

    overall_c = _mean_pipeline_values(overall_system, overall_random)
    train_c = _mean_pipeline_values(train_system, train_random)
    valid_c = _mean_pipeline_values(valid_system, valid_random)

    combined = {
        "overall": {
            "mean_win_rate": round(overall_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(overall_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(overall_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(overall_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(overall_c["best_max_win_streak"]),
            "min_decided_tickets": int(overall_c["min_decided_tickets"]),
            "mean_profit_flat": round(overall_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(overall_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(overall_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(overall_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(overall_c["mean_bankroll_multiple_flat"], 4),
        },
        "train": {
            "days": len(train_ds),
            "mean_win_rate": round(train_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(train_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(train_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(train_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(train_c["best_max_win_streak"]),
            "min_decided_tickets": int(train_c["min_decided_tickets"]),
            "mean_profit_flat": round(train_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(train_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(train_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(train_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(train_c["mean_bankroll_multiple_flat"], 4),
        },
        "valid": {
            "days": len(valid_ds),
            "mean_win_rate": round(valid_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(valid_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(valid_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(valid_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(valid_c["best_max_win_streak"]),
            "min_decided_tickets": int(valid_c["min_decided_tickets"]),
            "mean_profit_flat": round(valid_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(valid_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(valid_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(valid_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(valid_c["mean_bankroll_multiple_flat"], 4),
        },
        "generalization_gap": {
            "win_rate_gap_train_minus_valid": round(
                train_c["mean_win_rate"] - valid_c["mean_win_rate"],
                4,
            ),
            "tickets_gap_train_minus_valid": round(
                train_c["mean_tickets_per_active_day"] - valid_c["mean_tickets_per_active_day"],
                4,
            ),
            "profit_gap_train_minus_valid": round(
                train_c["mean_profit_flat"] - valid_c["mean_profit_flat"],
                4,
            ),
            "yield_gap_train_minus_valid": round(
                train_c["mean_yield_flat"] - valid_c["mean_yield_flat"],
                4,
            ),
            "win_rate_drop_penalized": round(
                max(0.0, train_c["mean_win_rate"] - valid_c["mean_win_rate"]),
                4,
            ),
            "tickets_drop_penalized": round(
                max(0.0, train_c["mean_tickets_per_active_day"] - valid_c["mean_tickets_per_active_day"]),
                4,
            ),
            "profit_drop_penalized": round(
                max(0.0, train_c["mean_profit_flat"] - valid_c["mean_profit_flat"]),
                4,
            ),
            "yield_drop_penalized": round(
                max(0.0, train_c["mean_yield_flat"] - valid_c["mean_yield_flat"]),
                4,
            ),
        },
    }

    return ProfileResult(
        rank_score=rank_score,
        tuning=tuning,
        system=overall_system,
        random_o15=overall_random,
        combined=combined,
    )


def _extract_ticket_sequences(
    day_evals: List[DayEval],
) -> Tuple[List[Tuple[bool, float]], List[Tuple[bool, float]]]:
    """
    Extrait les séquences brutes (is_win, odd) pour SYSTEM et RANDOM.
    Utilisé pour la simulation martingale dans validate_profiles.py.
    """
    system_seq: List[Tuple[bool, float]] = []
    random_seq: List[Tuple[bool, float]] = []
    for de in day_evals:
        for result, profit in zip(de.system.ticket_results, de.system.ticket_profits):
            if result is None:
                continue
            is_win = result is True
            odd = float(profit + 1.0) if is_win else 2.0
            system_seq.append((is_win, odd))
        for result, profit in zip(de.random_o15.ticket_results, de.random_o15.ticket_profits):
            if result is None:
                continue
            is_win = result is True
            odd = float(profit + 1.0) if is_win else 2.0
            random_seq.append((is_win, odd))
    return system_seq, random_seq


def evaluate_profile_with_sequences(
    datasets: List[DayDataset],
    tuning: BuilderTuning,
    keep_temp: bool = False,
    valid_days: int = DEFAULT_VALID_DAYS,
) -> Tuple[ProfileResult, List[Tuple[bool, float]], List[Tuple[bool, float]]]:
    """
    Comme evaluate_profile mais retourne aussi les séquences brutes (is_win, odd)
    pour SYSTEM et RANDOM — en un seul passage sur les données.
    """
    train_ds, valid_ds = _split_datasets_chronological(datasets, valid_days=valid_days)
    train_days = {d.day for d in train_ds}
    valid_days_set = {d.day for d in valid_ds}

    all_day_evals = _evaluate_all_days(datasets=datasets, tuning=tuning, keep_temp=keep_temp)

    system_seq, random_seq = _extract_ticket_sequences(all_day_evals)

    train_day_evals = [x for x in all_day_evals if x.day in train_days]
    valid_day_evals = [x for x in all_day_evals if x.day in valid_days_set]

    overall_system = _aggregate_pipeline_metrics(all_day_evals, pipeline_name="system")
    overall_random = _aggregate_pipeline_metrics(all_day_evals, pipeline_name="random")
    train_system = _aggregate_pipeline_metrics(train_day_evals, pipeline_name="system")
    train_random = _aggregate_pipeline_metrics(train_day_evals, pipeline_name="random")
    valid_system = _aggregate_pipeline_metrics(valid_day_evals, pipeline_name="system")
    valid_random = _aggregate_pipeline_metrics(valid_day_evals, pipeline_name="random")

    rank_score = _profile_rank_score(
        train_system=train_system,
        train_random=train_random,
        valid_system=valid_system,
        valid_random=valid_random,
    )

    overall_c = _mean_pipeline_values(overall_system, overall_random)
    train_c = _mean_pipeline_values(train_system, train_random)
    valid_c = _mean_pipeline_values(valid_system, valid_random)

    combined = {
        "overall": {
            "mean_win_rate": round(overall_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(overall_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(overall_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(overall_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(overall_c["best_max_win_streak"]),
            "min_decided_tickets": int(overall_c["min_decided_tickets"]),
            "mean_profit_flat": round(overall_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(overall_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(overall_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(overall_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(overall_c["mean_bankroll_multiple_flat"], 4),
        },
        "train": {
            "days": len(train_ds),
            "mean_win_rate": round(train_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(train_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(train_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(train_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(train_c["best_max_win_streak"]),
            "min_decided_tickets": int(train_c["min_decided_tickets"]),
            "mean_profit_flat": round(train_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(train_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(train_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(train_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(train_c["mean_bankroll_multiple_flat"], 4),
        },
        "valid": {
            "days": len(valid_ds),
            "mean_win_rate": round(valid_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(valid_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(valid_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(valid_c["worst_max_loss_streak"]),
            "best_max_win_streak": int(valid_c["best_max_win_streak"]),
            "min_decided_tickets": int(valid_c["min_decided_tickets"]),
            "mean_profit_flat": round(valid_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(valid_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(valid_c["worst_max_drawdown"], 4),
            "mean_final_bankroll_flat": round(valid_c["mean_final_bankroll_flat"], 4),
            "mean_bankroll_multiple_flat": round(valid_c["mean_bankroll_multiple_flat"], 4),
        },
        "generalization_gap": {
            "win_rate_gap_train_minus_valid": round(train_c["mean_win_rate"] - valid_c["mean_win_rate"], 4),
            "tickets_gap_train_minus_valid": round(train_c["mean_tickets_per_active_day"] - valid_c["mean_tickets_per_active_day"], 4),
            "profit_gap_train_minus_valid": round(train_c["mean_profit_flat"] - valid_c["mean_profit_flat"], 4),
            "yield_gap_train_minus_valid": round(train_c["mean_yield_flat"] - valid_c["mean_yield_flat"], 4),
            "win_rate_drop_penalized": round(max(0.0, train_c["mean_win_rate"] - valid_c["mean_win_rate"]), 4),
            "tickets_drop_penalized": round(max(0.0, train_c["mean_tickets_per_active_day"] - valid_c["mean_tickets_per_active_day"]), 4),
            "profit_drop_penalized": round(max(0.0, train_c["mean_profit_flat"] - valid_c["mean_profit_flat"]), 4),
            "yield_drop_penalized": round(max(0.0, train_c["mean_yield_flat"] - valid_c["mean_yield_flat"]), 4),
        },
    }

    prof = ProfileResult(
        rank_score=rank_score,
        tuning=tuning,
        system=overall_system,
        random_o15=overall_random,
        combined=combined,
    )
    return prof, system_seq, random_seq


def _evaluate_profile_with_seqs_job(
    args: Tuple[List[DayDataset], BuilderTuning, bool, int],
) -> Tuple[ProfileResult, List[Tuple[bool, float]], List[Tuple[bool, float]]]:
    datasets, tuning, keep_temp, valid_days = args
    return evaluate_profile_with_sequences(
        datasets=datasets,
        tuning=tuning,
        keep_temp=keep_temp,
        valid_days=valid_days,
    )


def _evaluate_profile_job(args: Tuple[List[DayDataset], BuilderTuning, bool, int]) -> ProfileResult:
    datasets, tuning, keep_temp, valid_days = args
    return evaluate_profile(
        datasets=datasets,
        tuning=tuning,
        keep_temp=keep_temp,
        valid_days=valid_days,
    )


# =========================================================
# OUTPUT
# =========================================================
def _render_top_profiles(top_profiles: List[ProfileResult]) -> str:
    lines: List[str] = []
    lines.append("TOP PROFILS OPTIMISEUR")
    lines.append("=" * 22)
    lines.append("")

    for i, prof in enumerate(top_profiles, start=1):
        t = prof.tuning
        overall = prof.combined.get("overall", {})
        train = prof.combined.get("train", {})
        valid = prof.combined.get("valid", {})
        gap = prof.combined.get("generalization_gap", {})

        lines.append(f"#{i} | score={prof.rank_score:.4f}")
        lines.append("-" * 60)
        lines.append(
            f"SYSTEM  | win_rate={prof.system.win_rate:.3f} | tickets/jour={prof.system.avg_tickets_per_active_day:.2f} "
            f"| decided={prof.system.decided_tickets} | max_loss_streak={prof.system.max_loss_streak} "
            f"| max_win_streak={prof.system.max_win_streak} | profit={prof.system.profit_flat:.2f} "
            f"| yield={prof.system.yield_flat:.3f} | max_dd={prof.system.max_drawdown:.2f} "
            f"| bankroll={prof.system.final_bankroll_flat:.2f} | x{prof.system.bankroll_multiple_flat:.2f}"
        )
        lines.append(
            f"RANDOM  | win_rate={prof.random_o15.win_rate:.3f} | tickets/jour={prof.random_o15.avg_tickets_per_active_day:.2f} "
            f"| decided={prof.random_o15.decided_tickets} | max_loss_streak={prof.random_o15.max_loss_streak} "
            f"| max_win_streak={prof.random_o15.max_win_streak} | profit={prof.random_o15.profit_flat:.2f} "
            f"| yield={prof.random_o15.yield_flat:.3f} | max_dd={prof.random_o15.max_drawdown:.2f} "
            f"| bankroll={prof.random_o15.final_bankroll_flat:.2f} | x{prof.random_o15.bankroll_multiple_flat:.2f}"
        )
        lines.append(
            f"COMBINÉ | mean_win_rate={overall.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={overall.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={overall.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={overall.get('mean_yield_flat', 0.0):.3f} "
            f"| worst_streak={overall.get('worst_max_loss_streak', 0)} "
            f"| best_win_streak={overall.get('best_max_win_streak', 0)} "
            f"| worst_dd={overall.get('worst_max_drawdown', 0.0):.2f} "
            f"| bankroll={overall.get('mean_final_bankroll_flat', DEFAULT_START_BANKROLL):.2f} "
            f"| x{overall.get('mean_bankroll_multiple_flat', 1.0):.2f}"
        )
        lines.append("")
        lines.append(
            f"TRAIN   | jours={train.get('days', 0)} | mean_win_rate={train.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={train.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={train.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={train.get('mean_yield_flat', 0.0):.3f} "
            f"| best_win_streak={train.get('best_max_win_streak', 0)} "
            f"| bankroll={train.get('mean_final_bankroll_flat', DEFAULT_START_BANKROLL):.2f} "
            f"| x{train.get('mean_bankroll_multiple_flat', 1.0):.2f}"
        )
        lines.append(
            f"VALID   | jours={valid.get('days', 0)} | mean_win_rate={valid.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={valid.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={valid.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={valid.get('mean_yield_flat', 0.0):.3f} "
            f"| best_win_streak={valid.get('best_max_win_streak', 0)} "
            f"| min_decided={valid.get('min_decided_tickets', 0)} "
            f"| bankroll={valid.get('mean_final_bankroll_flat', DEFAULT_START_BANKROLL):.2f} "
            f"| x{valid.get('mean_bankroll_multiple_flat', 1.0):.2f}"
        )
        lines.append(
            f"GAP     | wr_train-valid={gap.get('win_rate_gap_train_minus_valid', 0.0):+.3f} "
            f"| tickets_train-valid={gap.get('tickets_gap_train_minus_valid', 0.0):+.2f} "
            f"| profit_train-valid={gap.get('profit_gap_train_minus_valid', 0.0):+.2f} "
            f"| yield_train-valid={gap.get('yield_gap_train_minus_valid', 0.0):+.3f}"
        )
        lines.append(
            f"DROP    | wr_penalisé={gap.get('win_rate_drop_penalized', 0.0):.3f} "
            f"| tickets_penalisé={gap.get('tickets_drop_penalized', 0.0):.2f} "
            f"| profit_penalisé={gap.get('profit_drop_penalized', 0.0):.2f} "
            f"| yield_penalisé={gap.get('yield_drop_penalized', 0.0):.3f}"
        )
        lines.append("")
        lines.append("TUNING")
        lines.append(json.dumps(_serialize_tuning(t), ensure_ascii=False, indent=2))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# =========================================================
# MAIN SEARCH
# =========================================================
def run_optimizer(
    archive_dir: Path,
    output_dir: Path,
    trials: int,
    top_n: int,
    max_days: Optional[int],
    seed: int,
    keep_temp: bool = False,
    valid_days: int = DEFAULT_VALID_DAYS,
    jobs: int = DEFAULT_JOBS,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = discover_datasets(archive_dir, max_days=max_days)
    if not datasets:
        raise RuntimeError("Aucun dataset exploitable trouvé dans archive/.")

    train_ds, valid_ds = _split_datasets_chronological(datasets, valid_days=valid_days)

    print(f"[optimizer] datasets retenus: {len(datasets)}")
    print(f"[optimizer] période: {datasets[0].day} -> {datasets[-1].day}")
    print(f"[optimizer] split chrono: train={len(train_ds)} jours | valid={len(valid_ds)} jours")
    print(f"[optimizer] trials demandés: {trials}")

    trial_plan = _build_trial_plan(trials=trials, seed=seed)
    if len(trial_plan) < trials:
        print(
            f"[optimizer] warning: seulement {len(trial_plan)} profils uniques générés "
            f"sur {trials} demandés."
        )

    effective_trials = len(trial_plan)
    effective_jobs = max(1, int(jobs or 1))

    profiles: List[ProfileResult] = []
    checkpoint_every = 100
    checkpoint_path = output_dir / "optimizer_checkpoint.json"
    start_time = time.time()

    def _print_progress(done: int, total: int, label: str = "") -> None:
        elapsed = time.time() - start_time
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        best = max((p.rank_score for p in profiles), default=0.0)
        eta_str = f"{eta / 60:.0f}min" if eta < 3600 else f"{eta / 3600:.1f}h"
        suffix = f" ({label})" if label else ""
        print(
            f"[optimizer] {done}/{total}{suffix}"
            f" | best={best:.4f}"
            f" | {elapsed / 60:.1f}min écoulées"
            f" | ETA ~{eta_str}",
            flush=True,
        )

    def _save_checkpoint(current_profiles: List[ProfileResult]) -> None:
        sorted_cp = sorted(current_profiles, key=lambda p: p.rank_score, reverse=True)
        checkpoint_path.write_text(
            json.dumps([p.to_dict() for p in sorted_cp[:top_n]], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if effective_jobs == 1:
        for idx, tuning in enumerate(trial_plan, start=1):
            prof = evaluate_profile(
                datasets=datasets,
                tuning=tuning,
                keep_temp=keep_temp,
                valid_days=valid_days,
            )
            profiles.append(prof)
            label = "baseline" if idx == 1 else ""
            _print_progress(idx, effective_trials, label)
            if idx % checkpoint_every == 0:
                _save_checkpoint(profiles)
                print(f"[optimizer] checkpoint sauvegardé ({idx} trials)", flush=True)
    else:
        print(f"[optimizer] jobs parallèles: {effective_jobs}")

        future_to_idx: Dict[object, int] = {}
        with ProcessPoolExecutor(max_workers=effective_jobs) as ex:
            for idx, tuning in enumerate(trial_plan, start=1):
                fut = ex.submit(
                    _evaluate_profile_job,
                    (datasets, tuning, keep_temp, valid_days),
                )
                future_to_idx[fut] = idx

            done_count = 0
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                prof = fut.result()
                profiles.append(prof)
                done_count += 1
                label = "baseline" if idx == 1 else ""
                _print_progress(done_count, effective_trials, label)
                if done_count % checkpoint_every == 0:
                    _save_checkpoint(profiles)
                    print(f"[optimizer] checkpoint sauvegardé ({done_count} trials)", flush=True)

    profiles.sort(key=lambda p: p.rank_score, reverse=True)
    top_profiles = profiles[:top_n]

    json_path = output_dir / "optimizer_top_profiles.json"
    txt_path = output_dir / "optimizer_top_profiles.txt"
    all_json_path = output_dir / "optimizer_all_profiles.json"

    json_path.write_text(
        json.dumps([p.to_dict() for p in top_profiles], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt_path.write_text(_render_top_profiles(top_profiles), encoding="utf-8")

    all_json_path.write_text(
        json.dumps([p.to_dict() for p in profiles], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("")
    print(_render_top_profiles(top_profiles))
    print(f"[optimizer] écrit: {json_path}")
    print(f"[optimizer] écrit: {txt_path}")
    print(f"[optimizer] écrit: {all_json_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimiseur TRISKÈLE Ticket Builder")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    parser.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    args = parser.parse_args()

    run_optimizer(
        archive_dir=args.archive_dir,
        output_dir=args.output_dir,
        trials=args.trials,
        top_n=args.top_n,
        max_days=args.max_days,
        seed=args.seed,
        keep_temp=args.keep_temp,
        valid_days=args.valid_days,
        jobs=args.jobs,
    )


if __name__ == "__main__":
    main()