# services/ticket_optimizer.py
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import tempfile
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
DEFAULT_TOP_N = 3
DEFAULT_TRIALS = 1000
DEFAULT_MAX_DAYS = 60
DEFAULT_VALID_DAYS = 12

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

    # métriques financières ajoutées
    profit_flat: float = 0.0
    yield_flat: float = 0.0
    max_drawdown: float = 0.0

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
            "profit_flat": round(self.profit_flat, 4),
            "yield_flat": round(self.yield_flat, 4),
            "max_drawdown": round(self.max_drawdown, 4),
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


# =========================================================
# HELPERS DATA DISCOVERY
# =========================================================
def _iter_day_dirs(archive_dir: Path) -> Iterable[Path]:
    if not archive_dir.exists():
        return
    for p in sorted(archive_dir.iterdir()):
        if p.is_dir() and p.name.startswith("analyse_"):
            yield p
    jan = archive_dir / "1_JANVIER"
    if jan.exists() and jan.is_dir():
        for p in sorted(jan.iterdir()):
            if p.is_dir() and p.name.startswith("analyse_"):
                yield p


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
def _parse_verdict_file(path: Path) -> Dict[Tuple[str, str], str]:
    """
    Map:
      (match_id, bet_family) -> WIN / LOSS
    """
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

        self.old_tickets_tsv = tb.TICKETS_TSV_FILE
        self.old_o15_tsv = tb.TICKETS_O15_RANDOM_TSV_FILE
        self.old_report_global = tb.TICKETS_REPORT_GLOBAL_FILE
        self.old_o15_report_global = tb.TICKETS_O15_REPORT_GLOBAL_FILE
        self.old_maestro_log = tb.MAESTRO_LOG_FILE

    def __enter__(self):
        self.workdir.mkdir(parents=True, exist_ok=True)

        os.environ["TRISKELE_MAESTRO"] = "0"
        os.environ["TRISKELE_RUN_DIR"] = str(self.workdir)

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
    """
    Essaie de récupérer la cote totale du ticket sans dépendre
    d'un seul nom d'attribut.
    """
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

    # Fallback : produit des cotes des picks si dispo
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
    equity = 0.0
    equity_curve: List[float] = [0.0]

    for idx, r in enumerate(ticket_results):
        if r is True:
            m.wins += 1
            current_loss_streak = 0
        elif r is False:
            m.losses += 1
            current_loss_streak += 1
            if current_loss_streak > m.max_loss_streak:
                m.max_loss_streak = current_loss_streak
        else:
            m.unknown += 1

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

    return m


def _mean_pipeline_values(system_m: PipelineMetrics, random_m: PipelineMetrics) -> dict:
    return {
        "mean_win_rate": (system_m.win_rate + random_m.win_rate) / 2.0,
        "mean_tickets_per_active_day": (
            system_m.avg_tickets_per_active_day + random_m.avg_tickets_per_active_day
        ) / 2.0,
        "mean_unknown_rate": (system_m.unknown_rate + random_m.unknown_rate) / 2.0,
        "worst_max_loss_streak": max(system_m.max_loss_streak, random_m.max_loss_streak),
        "min_decided_tickets": min(system_m.decided_tickets, random_m.decided_tickets),
        "mean_profit_flat": (system_m.profit_flat + random_m.profit_flat) / 2.0,
        "mean_yield_flat": (system_m.yield_flat + random_m.yield_flat) / 2.0,
        "worst_max_drawdown": max(system_m.max_drawdown, random_m.max_drawdown),
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

    # Base
    score += ref["mean_win_rate"] * 100.0
    score += ref["mean_tickets_per_active_day"] * 10.0

    # Financier
    score += ref["mean_profit_flat"] * 2.5
    score += ref["mean_yield_flat"] * 120.0

    # Bonus équilibre SYSTEM / RANDOM
    ref_min_tickets = min(
        valid_system.avg_tickets_per_active_day if use_valid else train_system.avg_tickets_per_active_day,
        valid_random.avg_tickets_per_active_day if use_valid else train_random.avg_tickets_per_active_day,
    )
    score += ref_min_tickets * 2.0

    # Pénalité inconnus
    score -= ref["mean_unknown_rate"] * 30.0

    # Pénalité streak
    worst_streak = int(ref["worst_max_loss_streak"])
    if worst_streak >= RUIN_STREAK_LIMIT:
        score -= 1000.0
    elif worst_streak == 5:
        score -= 80.0
    elif worst_streak == 4:
        score -= 20.0

    # Pénalité drawdown
    score -= ref["worst_max_drawdown"] * 3.0

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
    excluded_options = [
        frozenset({"HT1X", "HT05"}),
        frozenset({"HT1X"}),
        frozenset({"HT05"}),
        frozenset(),
    ]

    weight_baseline = rng.choice([0.62, 0.66, 0.70, 0.74, 0.78])
    weight_ceil = rng.choice([0.92, 0.95, 0.98, 1.00])
    if weight_ceil <= weight_baseline:
        weight_ceil = min(1.00, weight_baseline + 0.15)

    two_team_low = rng.choice([0.55, 0.58, 0.60, 0.63, 0.66, 0.70])
    two_team_high = rng.choice([0.78, 0.80, 0.82, 0.85, 0.88])
    if two_team_high <= two_team_low:
        two_team_high = min(0.95, two_team_low + 0.15)

    target_odd = rng.choice([2.00, 2.10, 2.20, 2.30, 2.40])
    min_accept_odd = rng.choice([1.60, 1.70, 1.80, 1.90])
    if min_accept_odd > target_odd:
        min_accept_odd = target_odd

    return BuilderTuning(
        global_bet_min_decided=rng.choice([5, 7, 10, 12]),
        global_bet_min_winrate=rng.choice([0.62, 0.65, 0.68, 0.70, 0.72, 0.75]),
        league_bet_min_winrate=rng.choice([0.62, 0.65, 0.68, 0.70, 0.72, 0.75]),
        league_bet_require_data=rng.choice([True, False]),
        team_min_decided=rng.choice([6, 8, 10, 12, 15]),
        team_min_winrate=rng.choice([0.68, 0.70, 0.72, 0.75, 0.78, 0.80]),
        two_team_high=two_team_high,
        two_team_low=two_team_low,
        weight_min=rng.choice([0.8, 1.0, 1.2]),
        weight_max=rng.choice([1.8, 2.0, 2.2, 2.5, 3.0]),
        weight_baseline=weight_baseline,
        weight_ceil=weight_ceil,
        topk_size=rng.choice([3, 5, 8, 10]),
        topk_uniform_draw=rng.choice([True, False]),
        prefer_3legs_delta=rng.choice([0.00, 0.02, 0.03, 0.05, 0.08]),
        search_budget_ms_system=rng.choice([300, 500, 800, 1200]),
        search_budget_ms_random=rng.choice([300, 500, 800, 1200]),
        excluded_bet_groups=rng.choice(excluded_options),
        target_odd=target_odd,
        min_accept_odd=min_accept_odd,
    )


def _baseline_tuning() -> BuilderTuning:
    return BuilderTuning()


def _serialize_tuning(t: BuilderTuning) -> dict:
    d = asdict(t)
    d["excluded_bet_groups"] = sorted(list(t.excluded_bet_groups))
    return d


# =========================================================
# EVALUATION
# =========================================================
def _evaluate_dataset_slice(
    datasets: List[DayDataset],
    tuning: BuilderTuning,
    keep_temp: bool = False,
) -> Tuple[PipelineMetrics, PipelineMetrics]:
    system_results: List[Optional[bool]] = []
    random_results: List[Optional[bool]] = []

    system_profits: List[float] = []
    random_profits: List[float] = []

    system_active_days = 0
    random_active_days = 0

    tmp_root = Path(tempfile.mkdtemp(prefix="triskele_opt_"))

    try:
        for ds in datasets:
            verdict_map = _parse_verdict_file(ds.verdict_file)
            run_dir = tmp_root / ds.day

            with _PatchedBuilderIO(run_dir):
                out: TicketBuildOutput = tb.generate_tickets_from_tsv(
                    str(ds.predictions_tsv),
                    run_date=None,
                    tuning=tuning,
                )

            if out.tickets_system:
                system_active_days += 1
            if out.tickets_o15:
                random_active_days += 1

            for ticket in out.tickets_system:
                outcome = _ticket_outcome(ticket, verdict_map)
                system_results.append(outcome)
                system_profits.append(_flat_profit_for_ticket(ticket, outcome))

            for ticket in out.tickets_o15:
                outcome = _ticket_outcome(ticket, verdict_map)
                random_results.append(outcome)
                random_profits.append(_flat_profit_for_ticket(ticket, outcome))

        system_m = _finalize_metrics(system_results, system_profits, system_active_days)
        random_m = _finalize_metrics(random_results, random_profits, random_active_days)
        return system_m, random_m

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

    overall_system, overall_random = _evaluate_dataset_slice(
        datasets=datasets,
        tuning=tuning,
        keep_temp=keep_temp,
    )

    train_system, train_random = _evaluate_dataset_slice(
        datasets=train_ds,
        tuning=tuning,
        keep_temp=keep_temp,
    )

    if valid_ds:
        valid_system, valid_random = _evaluate_dataset_slice(
            datasets=valid_ds,
            tuning=tuning,
            keep_temp=keep_temp,
        )
    else:
        valid_system = PipelineMetrics()
        valid_random = PipelineMetrics()

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
            "min_decided_tickets": int(overall_c["min_decided_tickets"]),
            "mean_profit_flat": round(overall_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(overall_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(overall_c["worst_max_drawdown"], 4),
        },
        "train": {
            "days": len(train_ds),
            "mean_win_rate": round(train_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(train_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(train_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(train_c["worst_max_loss_streak"]),
            "min_decided_tickets": int(train_c["min_decided_tickets"]),
            "mean_profit_flat": round(train_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(train_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(train_c["worst_max_drawdown"], 4),
        },
        "valid": {
            "days": len(valid_ds),
            "mean_win_rate": round(valid_c["mean_win_rate"], 4),
            "mean_tickets_per_active_day": round(valid_c["mean_tickets_per_active_day"], 4),
            "mean_unknown_rate": round(valid_c["mean_unknown_rate"], 4),
            "worst_max_loss_streak": int(valid_c["worst_max_loss_streak"]),
            "min_decided_tickets": int(valid_c["min_decided_tickets"]),
            "mean_profit_flat": round(valid_c["mean_profit_flat"], 4),
            "mean_yield_flat": round(valid_c["mean_yield_flat"], 4),
            "worst_max_drawdown": round(valid_c["worst_max_drawdown"], 4),
        },
        "generalization_gap": {
            # gap signé réel
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
            # drop réellement pénalisé
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
            f"| profit={prof.system.profit_flat:.2f} | yield={prof.system.yield_flat:.3f} | max_dd={prof.system.max_drawdown:.2f}"
        )
        lines.append(
            f"RANDOM  | win_rate={prof.random_o15.win_rate:.3f} | tickets/jour={prof.random_o15.avg_tickets_per_active_day:.2f} "
            f"| decided={prof.random_o15.decided_tickets} | max_loss_streak={prof.random_o15.max_loss_streak} "
            f"| profit={prof.random_o15.profit_flat:.2f} | yield={prof.random_o15.yield_flat:.3f} | max_dd={prof.random_o15.max_drawdown:.2f}"
        )
        lines.append(
            f"COMBINÉ | mean_win_rate={overall.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={overall.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={overall.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={overall.get('mean_yield_flat', 0.0):.3f} "
            f"| worst_streak={overall.get('worst_max_loss_streak', 0)} "
            f"| worst_dd={overall.get('worst_max_drawdown', 0.0):.2f}"
        )
        lines.append("")
        lines.append(
            f"TRAIN   | jours={train.get('days', 0)} | mean_win_rate={train.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={train.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={train.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={train.get('mean_yield_flat', 0.0):.3f}"
        )
        lines.append(
            f"VALID   | jours={valid.get('days', 0)} | mean_win_rate={valid.get('mean_win_rate', 0.0):.3f} "
            f"| mean_tickets/jour={valid.get('mean_tickets_per_active_day', 0.0):.2f} "
            f"| mean_profit={valid.get('mean_profit_flat', 0.0):.2f} "
            f"| mean_yield={valid.get('mean_yield_flat', 0.0):.3f} "
            f"| min_decided={valid.get('min_decided_tickets', 0)}"
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
) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = discover_datasets(archive_dir, max_days=max_days)
    if not datasets:
        raise RuntimeError("Aucun dataset exploitable trouvé dans archive/.")

    train_ds, valid_ds = _split_datasets_chronological(datasets, valid_days=valid_days)

    print(f"[optimizer] datasets retenus: {len(datasets)}")
    print(f"[optimizer] période: {datasets[0].day} -> {datasets[-1].day}")
    print(f"[optimizer] split chrono: train={len(train_ds)} jours | valid={len(valid_ds)} jours")
    print(f"[optimizer] trials: {trials}")

    profiles: List[ProfileResult] = []

    print("[optimizer] trial 1 / {} (baseline)".format(trials))
    baseline = evaluate_profile(
        datasets,
        _baseline_tuning(),
        keep_temp=keep_temp,
        valid_days=valid_days,
    )
    profiles.append(baseline)

    for i in range(1, trials):
        tuning = _sample_tuning(rng)
        print(f"[optimizer] trial {i+1} / {trials}")
        prof = evaluate_profile(
            datasets,
            tuning,
            keep_temp=keep_temp,
            valid_days=valid_days,
        )
        profiles.append(prof)

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
    )


if __name__ == "__main__":
    main()