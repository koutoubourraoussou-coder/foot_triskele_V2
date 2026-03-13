# services/ticket_builder.py
# ----------------------------------------------------
# TRISKÈLE — Ticket Builder (à partir des TSV prédictions)
#
# V12.2 — DOUBLE PIPELINE + FIX TRANCHES + MAESTROLOGUE EXPLAIN + SAFETY FIX
#   A) SYSTEM (is_candidate=1) -> data/tickets.tsv + tickets_report.txt (+ global append)
#      ✅ Filtrage + pondération par "winrate TEAM x BET" (post-analyse) selon tes règles
#      ✅ FIX: après création d’un ticket, on repart au 1er match APRÈS la fin du ticket
#      ✅ FIX: les picks d’un ticket sont triés par heure (report + id + fenêtre cohérents)
#      ✅ FIX: la "fenêtre ~Xmin" reflète la fenêtre RÉELLE du ticket (pas la fusion)
#      ✅ FIX: _final_score défini quoi qu’il arrive (bug indentation/fragilité)
#      ✅ MAESTROLOGUE: explique la décision 3 legs vs 4 legs + détail du score (niveau 3)
#
#   B) O15_RANDOM_ALL (tous matchs O15) -> data/tickets_o15_random.tsv + report (+ global append)
#      ✅ Random = tirage uniforme (hors contraintes de structure: 1 pick/match, fenêtres, etc.)
#      ✅ FIX: même logique de reprise (1er match après fin du ticket) + tri par heure
#
#   ✅ UPDATE: on accepte HT1X & HT05
#   ✅ MAESTROLOGUE: niveaux 1/2/3, défaut = 3 (détaillé), override via env
#
# ----------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Dict, Set, Callable
import re
from pathlib import Path
import hashlib
import random
from datetime import datetime
import os
import time
import math
import heapq

# ----------------------------
# Constantes (réglages rapides)
# ----------------------------
TARGET_ODD = 2.20
MIN_ODD = 1.15

# Fallback uniquement si la journée ne permet AUCUN ticket >= TARGET_ODD
MIN_ACCEPT_ODD = 1.60

MATCH_DURATION_MIN = 110

# ✅ Exclusions (SYSTEM uniquement) — vide => on n'exclut plus HT05 ni HT1X
EXCLUDED_BET_GROUPS: Set[str] = {"HT1X", "HT05"}

MAX_LEG_SIZE = 4

# ✅ recherche time-budget (au lieu de N tentatives)
SEARCH_BUDGET_MS_SYSTEM = 1200
SEARCH_BUDGET_MS_RANDOM = 1200

# garde-fou (si machine très lente ou pools énormes)
SEARCH_MAX_ITER_SYSTEM = 200000
SEARCH_MAX_ITER_RANDOM = 200000

# ----------------------------
# Gestion journalière / fenêtres
# ----------------------------
RICH_DAY_MATCH_COUNT = 20          # grosse journée = 2 tickets max
DAY_MAX_TICKETS_POOR = 1
DAY_MAX_TICKETS_RICH = 2

MIN_SIDE_MATCHES_FOR_SPLIT = 4     # évite une fenêtre vide ou ridicule
SPLIT_GAP_WEIGHT = 0.35            # bonus si la coupure tombe dans un vrai creux horaire

# Sorties SYSTEM
TICKETS_TSV_FILE = Path("data/tickets.tsv")

# Sorties HASARD O15 (tous matchs)
TICKETS_O15_RANDOM_TSV_FILE = Path("data/tickets_o15_random.tsv")

# ✅ Reports "global" (historique cumulatif)
TICKETS_REPORT_GLOBAL_FILE = Path("data/tickets_report_global.txt")
TICKETS_O15_REPORT_GLOBAL_FILE = Path("data/tickets_o15_random_report_global.txt")

# ✅ Pools exportés en global cumulatif
SYSTEM_POOL_BASE_GLOBAL_FILE = Path("data/system_pool_base_global.tsv")
SYSTEM_POOL_EFFECTIVE_GLOBAL_FILE = Path("data/system_pool_effective_global.tsv")

O15_RANDOM_POOL_BASE_GLOBAL_FILE = Path("data/o15_random_pool_base_global.tsv")
O15_RANDOM_POOL_EFFECTIVE_GLOBAL_FILE = Path("data/o15_random_pool_effective_global.tsv")

# Bet key canon pour O15
O15_CANON = "O15_FT"

# ----------------------------
# ✅ RÈGLES "SYSTÈME" : PERFORMANCE / WINRATES
# ----------------------------
GLOBAL_BET_MIN_DECIDED = 7
GLOBAL_BET_MIN_WINRATE = 0.70

LEAGUE_BET_MIN_WINRATE = 0.68
LEAGUE_BET_REQUIRE_DATA = False  # True = 0 match => rejet ; False = 0 match => passe

TEAM_MIN_DECIDED = 10
TEAM_MIN_WINRATE = 0.70

TWO_TEAM_HIGH = 0.78
TWO_TEAM_LOW = 0.66

WEIGHT_MIN = 0.9
WEIGHT_MAX = 2.2
WEIGHT_BASELINE = 0.70
WEIGHT_CEIL = 1.00

# ----------------------------
# Fichiers "rankings" issus de post-analyse (SOURCE UNIQUE — SANS FALLBACK)
# ----------------------------
ENABLE_RANKINGS = True

# ✅ Unique source : data/rankings/
RANKINGS_LEAGUE_BET_FILE = Path("data/rankings/triskele_ranking_league_x_bet.tsv")
RANKINGS_TEAM_BET_FILE   = Path("data/rankings/triskele_ranking_team_x_bet.tsv")

GLOBAL_VERDICT_HISTORY_FILE = Path("data/verdict_post_analyse.txt")

RANK_EPS = 0.05

# ====================================================
# MAESTROLOGUE — Diagnostic lisible (par niveaux)
# ====================================================
ENABLE_MAESTRO = True               # interrupteur global
MAESTRO_DEFAULT_LEVEL = 3           # 1=sobre, 2=debug tranches, 3=debug + détails
MAESTRO_LOG_FILE = Path("data/tickets_maestro_log.txt")
MAESTRO_MAX_DETAIL_LINES = 30       # limite pour niveau 3 (évite pavés)

# explication décision 3L vs 4L (pour logs)
PREFER_3LEGS_DELTA = 0.03

# ----------------------------
# ✅ TOP-K UNIFORM DRAW (cas commun SYSTEM + RANDOM)
# ----------------------------
TOPK_SIZE = 3  # réglable : 5,6,7,8,9,10...
TOPK_UNIFORM_DRAW = False  # tu veux uniforme

# ====================================================
# CONFIG PILOTABLE PAR OPTIMISEUR
# ====================================================

@dataclass(frozen=True)
class BuilderTuning:
    # Gates / seuils SYSTEM
    global_bet_min_decided: int = GLOBAL_BET_MIN_DECIDED
    global_bet_min_winrate: float = GLOBAL_BET_MIN_WINRATE
    league_bet_min_winrate: float = LEAGUE_BET_MIN_WINRATE
    league_bet_require_data: bool = LEAGUE_BET_REQUIRE_DATA
    team_min_decided: int = TEAM_MIN_DECIDED
    team_min_winrate: float = TEAM_MIN_WINRATE
    two_team_high: float = TWO_TEAM_HIGH
    two_team_low: float = TWO_TEAM_LOW

    # Pondération
    weight_min: float = WEIGHT_MIN
    weight_max: float = WEIGHT_MAX
    weight_baseline: float = WEIGHT_BASELINE
    weight_ceil: float = WEIGHT_CEIL

    # Recherche / sélection
    topk_size: int = TOPK_SIZE
    topk_uniform_draw: bool = TOPK_UNIFORM_DRAW
    prefer_3legs_delta: float = PREFER_3LEGS_DELTA
    search_budget_ms_system: int = SEARCH_BUDGET_MS_SYSTEM
    search_budget_ms_random: int = SEARCH_BUDGET_MS_RANDOM

    # Exclusions SYSTEM
    excluded_bet_groups: Set[str] = frozenset(EXCLUDED_BET_GROUPS)

    # Objectif ticket
    target_odd: float = TARGET_ODD
    min_accept_odd: float = MIN_ACCEPT_ODD


_DEFAULT_TUNING = BuilderTuning()
_ACTIVE_TUNING: Optional[BuilderTuning] = None


def T() -> BuilderTuning:
    return _ACTIVE_TUNING or _DEFAULT_TUNING


def _set_active_tuning(tuning: Optional[BuilderTuning]) -> None:
    global _ACTIVE_TUNING
    _ACTIVE_TUNING = tuning


def _clear_active_tuning() -> None:
    global _ACTIVE_TUNING
    _ACTIVE_TUNING = None

def _maestro_enabled() -> bool:
    v = os.environ.get("TRISKELE_MAESTRO", "").strip()
    if v.lower() in ("0", "false", "no", "off"):
        return False
    return bool(ENABLE_MAESTRO)

def _maestro_level() -> int:
    if not _maestro_enabled():
        return 0
    v = os.environ.get("TRISKELE_MAESTRO_LEVEL", "").strip()
    if v.isdigit():
        return max(1, min(3, int(v)))
    return int(MAESTRO_DEFAULT_LEVEL)

def _get_run_dir() -> Path | None:
    rd = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if not rd:
        return None
    p = Path(rd)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _run_scoped_or_data(name: str) -> Path:
    rd = _get_run_dir()
    p = (rd / name) if rd is not None else (Path("data") / name)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _write_report_robust(run_path: Path, data_path: Path, text: str) -> None:
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(text, encoding="utf-8")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(text, encoding="utf-8")

def _write_maestro_log(text: str, *, append: bool = True) -> None:
    if not text or not _maestro_enabled():
        return
    run_path = _run_scoped_or_data("tickets_maestro_log.txt")
    # append simple (pas de dédup)
    if append and run_path.exists():
        try:
            old = run_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            old = ""
        merged = (old + text)
        _write_report_robust(run_path=run_path, data_path=MAESTRO_LOG_FILE, text=merged)
    else:
        _write_report_robust(run_path=run_path, data_path=MAESTRO_LOG_FILE, text=text)

def _optimizer_fast_mode() -> bool:
    v = os.environ.get("TRISKELE_OPTIMIZER_FAST", "").strip().lower()
    return v in ("1", "true", "yes", "on")

# ----------------------------
# Modèle interne
# ----------------------------
@dataclass(frozen=True)
class Pick:
    match_id: str
    date: str
    league: str
    home: str
    away: str
    bet_key: str
    metric: str
    score: float
    label: str
    is_candidate: int
    comment: str
    time_str: str
    odd: Optional[float]
    fixture_id: Optional[str]

@dataclass
class Ticket:
    picks: List[Pick]
    target_reached: bool
    group_no: int = 0
    option_no: int = 0
    spread_minutes: int = 0  # fenêtre ticket (kickoff_last - kickoff_first)

    @property
    def total_odd(self) -> float:
        prod = 1.0
        for p in self.picks:
            prod *= (p.odd or 1.0)
        return prod

    @property
    def kickoff_start_time(self) -> str:
        return min((p.time_str for p in self.picks), default="--:--")

    @property
    def kickoff_end_time(self) -> str:
        return max((p.time_str for p in self.picks), default="--:--")

    @property
    def start_time(self) -> str:
        return self.kickoff_start_time

    @property
    def end_time(self) -> str:
        end_kickoff = _time_to_minutes(self.kickoff_end_time)
        if end_kickoff >= 10**8:
            return "--:--"
        return _minutes_to_time(end_kickoff + MATCH_DURATION_MIN)

    @property
    def end_time_minutes(self) -> int:
        end_kickoff = _time_to_minutes(self.kickoff_end_time)
        if end_kickoff >= 10**8:
            return 10**9
        return end_kickoff + MATCH_DURATION_MIN

# ----------------------------
# Output stable (backward-compatible)
# ----------------------------
@dataclass
class TicketBuildOutput:
    tickets_system: List[Ticket]
    report_system: str
    tickets_o15: List[Ticket]
    report_o15: str
    added_sys: int = 0
    added_o15: int = 0
    added_sys_global: int = 0
    added_o15_global: int = 0

    def __iter__(self):
        yield self.tickets_system
        yield self.report_system

# ----------------------------
# Helpers parsing
# ----------------------------
_ODD_RE = re.compile(r"\bodd\s*=\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
_FIX_RE = re.compile(r"\bfixture\s*=\s*([0-9]+)\b", re.IGNORECASE)
_TICKET_ID_RE = re.compile(
    r"\bid=([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}_[0-9a-fA-F]{10}(?:_[A-Za-z0-9]+)?)\b"
)

def _parse_odd(comment: str) -> Optional[float]:
    if not comment:
        return None
    m = _ODD_RE.search(comment)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _parse_fixture(comment: str) -> Optional[str]:
    if not comment:
        return None
    m = _FIX_RE.search(comment)
    if not m:
        return None
    return m.group(1)

def _time_to_minutes(t: str) -> int:
    try:
        hh, mm = (t or "").split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 10**9

def _minutes_to_time(m: int) -> str:
    if m >= 10**8:
        return "--:--"
    h = (m // 60) % 24
    mi = m % 60
    return f"{h:02d}:{mi:02d}"

def _fmt_odd(x: Optional[float]) -> str:
    if x is None:
        return "—"
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s

def _now_perf() -> float:
    # perf_counter = horloge haute résolution
    return time.perf_counter()

def _deadline_ms(budget_ms: int) -> float:
    return _now_perf() + max(1, int(budget_ms)) / 1000.0

def _confidence_coef(n: int, *, n_full: int = 5, base: float = 0.70) -> float:
    """
    Coefficient de confiance linéaire :
      - n <= 0  -> 0.0
      - n = 1   -> base (0.70)
      - n >= n_full -> 1.0
      - entre 1 et n_full -> monte linéairement vers 1.0

    Exemple (base=0.70, n_full=5):
      1->0.70, 2->0.775, 3->0.85, 4->0.925, 5->1.00
    """
    try:
        n = int(n or 0)
    except Exception:
        n = 0

    if n <= 0:
        return 0.0
    if n >= n_full:
        return 1.0
    if n_full <= 1:
        return 1.0

    step = (1.0 - float(base)) / float(n_full - 1)
    return max(0.0, min(1.0, float(base) + float(n - 1) * step))

def _ticket_score_system(picks: List[Pick], league_bet: Optional[dict], team_bet: Optional[dict]) -> float:
    """
    SCORE SYSTEM (final, pour comparer les tickets) :

    Pour chaque pick :
      - on lit WR baseline TEAM x BET pour home et away (si dispo)
      - on applique une "sécurité statistique" via coef(n) :
          wr_adj = wr * coef(decided)
        avec coef(1)=0.70 et coef(>=5)=1.00
      - on fait la moyenne home/away (ou une seule si une seule dispo)

    Puis on moyenne les picks du ticket.

    Score final = 0 → 1 (ex: 0.82 = 82%)
    """
    if not picks:
        return -1e9

    match_means: List[float] = []

    for p in picks:
        fam = _norm_bet_family(p.bet_key)
        league = (p.league or "").strip()

        wrs: List[float] = []

        # HOME
        wr1, dec1 = _team_rate(team_bet, p.home, league, fam)
        if wr1 is not None and dec1 > 0:
            c1 = _confidence_coef(dec1, n_full=5, base=0.70)
            wrs.append(float(wr1) * c1)

        # AWAY
        wr2, dec2 = _team_rate(team_bet, p.away, league, fam)
        if wr2 is not None and dec2 > 0:
            c2 = _confidence_coef(dec2, n_full=5, base=0.70)
            wrs.append(float(wr2) * c2)

        if wrs:
            match_means.append(sum(wrs) / len(wrs))
        else:
            match_means.append(0.0)

    return sum(match_means) / len(match_means)

def _ticket_score_random(picks: List[Pick], league_bet: Optional[dict]) -> float:
    """
    SCORE RANDOM (final, pour comparer les tickets) :

    Pour chaque pick :
      - on lit WR baseline LEAGUE x BET
      - on applique la "sécurité statistique" :
          wr_adj = wr * coef(decided)
        avec coef(1)=0.70 et coef(>=5)=1.00

    Puis moyenne sur le ticket.

    Score final = 0 → 1
    """
    if not picks:
        return -1e9

    wrs: List[float] = []

    for p in picks:
        fam = _norm_bet_family(p.bet_key)
        league = (p.league or "").strip()

        wr, dec = _league_bet_rate(league_bet, league, fam)
        if wr is not None and dec > 0:
            c = _confidence_coef(dec, n_full=5, base=0.70)
            wrs.append(float(wr) * c)
        else:
            wrs.append(0.0)

    return sum(wrs) / len(wrs)

def _ticket_score_random_team(picks: List[Pick], team_bet: Optional[dict]) -> float:
    """
    SCORE RANDOM (final, pour comparer les tickets) — VERSION TEAM :

    Pour chaque pick :
      - on lit WR baseline TEAM x BET pour home et away
      - on applique la "sécurité statistique" via coef(decided):
          wr_adj = wr * coef(decided)
        avec coef(1)=0.70 et coef(>=5)=1.00
      - on prend la moyenne home/away (ou une seule si une seule dispo)

    Puis moyenne sur le ticket.

    Score final = 0 → 1
    """
    if not picks:
        return -1e9
    if team_bet is None:
        # pas de data team => score neutre (ou 0), mais on évite planter
        return 0.0

    match_means: List[float] = []

    for p in picks:
        fam = _norm_bet_family(p.bet_key)
        league = (p.league or "").strip()

        wrs: List[float] = []

        # HOME
        wr1, dec1 = _team_rate(team_bet, p.home, league, fam)
        if wr1 is not None and dec1 > 0:
            c1 = _confidence_coef(dec1, n_full=5, base=0.70)
            wrs.append(float(wr1) * c1)

        # AWAY
        wr2, dec2 = _team_rate(team_bet, p.away, league, fam)
        if wr2 is not None and dec2 > 0:
            c2 = _confidence_coef(dec2, n_full=5, base=0.70)
            wrs.append(float(wr2) * c2)

        if wrs:
            match_means.append(sum(wrs) / len(wrs))
        else:
            match_means.append(0.0)

    return sum(match_means) / len(match_means)

def _prefer_3legs_if_close(best4: Optional[List[Pick]], score4: float,
                           best3: Optional[List[Pick]], score3: float,
                           *, prefer_delta: float = PREFER_3LEGS_DELTA) -> Tuple[Optional[List[Pick]], float]:
    """
    Règle demandée :
    - si meilleur ticket = 4 legs
    - et qu'il existe un 3 legs dont le score est à <= delta d'écart
      => on préfère le 3 legs.
    """
    if not best4:
        return best3, score3
    if not best3:
        return best4, score4

    if len(best4) >= 4 and len(best3) == 3:
        thresh = score4 * (1.0 - prefer_delta)
        if score3 >= thresh:
            return best3, score3

    if score3 > score4:
        return best3, score3
    return best4, score4


@dataclass(frozen=True)
class _TopKItem:
    score: float
    picks: Tuple[Pick, ...]
    sig: str

class _TopK:
    """
    Maintient un Top-K par score (max), stockage en min-heap de taille K.
    Dédup : une combinaison (signature) ne peut exister qu'une seule fois.
    Égalités : on accepte score == min pour éviter TopK figé.
    """
    def __init__(self, k: int):
        self.k = max(1, int(k or 1))
        self._heap: List[Tuple[float, int, _TopKItem]] = []
        self._seq = 0
        self._seen: Set[str] = set()

    def push(self, score: float, picks: List[Pick]) -> None:
        if not picks:
            return

        sig = _ticket_signature(picks)
        if sig in self._seen:
            return

        self._seq += 1
        item = _TopKItem(score=float(score), picks=tuple(picks), sig=sig)

        if len(self._heap) < self.k:
            heapq.heappush(self._heap, (item.score, self._seq, item))
            self._seen.add(sig)
            return

        min_score, _, min_item = self._heap[0]

        # accepte l'égalité pour ne pas figer le topK quand beaucoup de scores sont identiques
        if item.score >= float(min_score):
            popped = heapq.heapreplace(self._heap, (item.score, self._seq, item))
            old_item = popped[2]
            self._seen.discard(old_item.sig)
            self._seen.add(item.sig)

    def items_desc(self) -> List[_TopKItem]:
        return [t[2] for t in sorted(self._heap, key=lambda x: x[0], reverse=True)]

def _uniform_draw_topk(rng: random.Random, items: List[_TopKItem]) -> Optional[_TopKItem]:
    if not items:
        return None
    return rng.choice(items)

def _weighted_order_no_replacement(pool: List[Pick], weights: List[float], rng: random.Random) -> List[Pick]:
    """
    Tirage pondéré SANS remise (weighted shuffle) plus efficace que:
      idx = rng.choices(...); pop(); etc. (O(n^2))

    Méthode Efraimidis–Spirakis: clé = -log(U)/w, tri croissant.
    - Si w <= 0, on remplace par un epsilon.
    - Retourne une permutation complète du pool.
    """
    eps = 1e-12
    keys: List[Tuple[float, Pick]] = []
    for p, w in zip(pool, weights):
        ww = float(w) if w is not None else 0.0
        if ww <= 0:
            ww = eps
        u = rng.random()
        if u <= 0.0:
            u = eps
        k = -math.log(u) / ww
        keys.append((k, p))
    keys.sort(key=lambda x: x[0])
    return [p for _, p in keys]

def _fmt_score_pct(sc: float) -> str:
    try:
        return f"{sc:.3f} ({_fmt_pct(sc)})"
    except Exception:
        return "—"

def _short_ticket_lines(picks_: Optional[List[Pick]], *, max_lines: int = 6) -> List[str]:
    if not picks_:
        return ["(aucun)"]
    out: List[str] = []
    for i, p in enumerate(sorted(picks_, key=lambda x: _time_to_minutes(x.time_str)), start=1):
        out.append(f"  {i}) {_short_pick(p)}")
        if len(out) >= max_lines:
            break
    return out

def _safe_float(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _weekday_fr(date_str: str) -> str:
    try:
        y, m, d = map(int, (date_str or "").split("-"))
        wd = __import__("datetime").date(y, m, d).weekday()
        return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][wd]
    except Exception:
        return ""

# ----------------------------
# Exclusions (SYSTEM)
# ----------------------------
def _bet_group(bet_key: str) -> str:
    bk = (bet_key or "").strip().upper()
    if bk == "HT05":
        return "HT05"
    if bk.startswith("HT1X") or bk in ("HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        return "HT1X"
    if "O15" in bk or "OVER15" in bk or "OVER_1_5" in bk:
        return "O15"
    return "OTHER"

def _is_excluded_pick_system(p: Pick) -> bool:
    return _bet_group(p.bet_key) in (T().excluded_bet_groups or set())

def _match_key(p: Pick) -> str:
    if p.fixture_id:
        return f"F:{p.fixture_id}"
    return f"M:{p.match_id}"

def _ticket_signature(picks: List[Pick]) -> str:
    """
    Signature stable d'un ticket (ordre-indépendant).
    Objectif : empêcher 2 fois la même combinaison dans un TopK.
    """
    if not picks:
        return "EMPTY"
    legs: List[str] = []
    for p in picks:
        legs.append(f"{_match_key(p)}|{_norm_bet_family(p.bet_key)}")
    legs.sort()
    base = "||".join(legs)
    return hashlib.md5(base.encode("utf-8")).hexdigest()

# ----------------------------
# Normalisation bet_key (pour global stats)
# ----------------------------
def _norm_bet_family(bet_key: str) -> str:
    bk = (bet_key or "").strip().upper()

    if bk == "HT05":
        return "HT05"

    if bk in ("HT1X_HOME", "HT1X", "HT_1X_HOME", "HOME_HT_DOUBLE_CHANCE"):
        return "HT1X_HOME"

    if bk in (
        "O15_FT",
        "FT_OVER_1_5",
        "OVER15",
        "OVER_1_5",
        "O15",
        "FT_O15",
        "FT15",
        "FT_OVER15",
        "FT_OVER_1_5",
    ):
        return "O15_FT"

    if bk in ("TEAM1_SCORE_FT", "TEAM1_SCORE", "T1_SCORE", "TEAM1_TO_SCORE"):
        return "TEAM1_SCORE_FT"

    if bk in ("TEAM2_SCORE_FT", "TEAM2_SCORE", "T2_SCORE", "TEAM2_TO_SCORE"):
        return "TEAM2_SCORE_FT"

    if bk in ("TEAM1_WIN_FT", "TEAM1_WIN", "HOME_WIN", "T1_WIN"):
        return "TEAM1_WIN_FT"

    if bk in ("TEAM2_WIN_FT", "TEAM2_WIN", "AWAY_WIN", "T2_WIN"):
        return "TEAM2_WIN_FT"

    return bk if bk else "UNKNOWN"

def _pick_primary_teams(p: Pick) -> List[str]:
    fam = _norm_bet_family(p.bet_key)

    # bets "1 équipe"
    if fam in ("TEAM1_SCORE_FT", "TEAM1_WIN_FT", "HT1X_HOME"):
        return [p.home]
    if fam in ("TEAM2_SCORE_FT", "TEAM2_WIN_FT"):
        return [p.away]

    # bets "2 équipes"
    return [p.home, p.away]

def _is_two_team_bet(p: Pick) -> bool:
    fam = _norm_bet_family(p.bet_key)
    return fam in ("O15_FT", "HT05")

# ----------------------------
# Rankings loaders (TSV robust)
# ----------------------------
def _read_tsv_rows(path: Path) -> List[List[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: List[List[str]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip("\n")
            if not line.strip():
                continue
            rows.append(line.split("\t"))
    return rows

def _detect_header_row(rows: List[List[str]], wanted: Set[str]) -> Tuple[Optional[Dict[str, int]], int]:
    for i, r in enumerate(rows[:5]):
        cols = [c.strip().lstrip("#").strip().lower() for c in r]
        if wanted.issubset(set(cols)):
            idx = {name: cols.index(name) for name in wanted}
            return idx, i + 1
    return None, 0

_rankings_cache: dict | None = None

def _load_rankings() -> Tuple[Optional[dict], Optional[dict]]:
    """
    Charge UNIQUEMENT les fichiers de data/rankings/.
    ZÉRO fallback.
    """
    global _rankings_cache
    if _rankings_cache is not None:
        return _rankings_cache.get("league_bet"), _rankings_cache.get("team_bet")

    if not ENABLE_RANKINGS:
        _rankings_cache = {"league_bet": None, "team_bet": None}
        return None, None

    league_path = RANKINGS_LEAGUE_BET_FILE
    team_path = RANKINGS_TEAM_BET_FILE

    missing = []
    if not (league_path.exists() and league_path.stat().st_size > 0):
        missing.append(str(league_path))
    if not (team_path.exists() and team_path.stat().st_size > 0):
        missing.append(str(team_path))
    if missing:
        raise FileNotFoundError(
            "Rankings introuvables ou vides (source unique, sans fallback) :\n- " + "\n- ".join(missing)
        )

    # ----------------------------
    # LEAGUE x BET
    # ----------------------------
    rows = _read_tsv_rows(league_path)
    wanted = {"league", "bet_key", "samples", "success", "fail", "success_rate"}
    idx_map, data_start = _detect_header_row(rows, wanted)

    lb: dict = {}
    for r in rows[data_start:]:
        try:
            cols = [c.strip() for c in r]
            if not cols:
                continue
            if cols[0].startswith("#"):
                continue

            if idx_map:
                league = cols[idx_map["league"]]
                bet_key = cols[idx_map["bet_key"]]
                samples = int(cols[idx_map["samples"]])
                success = int(cols[idx_map["success"]])
                fail = int(cols[idx_map["fail"]])
                success_rate = float(cols[idx_map["success_rate"]])

                decided = samples
                wins = success
                losses = fail
                win_rate = success_rate
            else:
                if len(cols) < 6:
                    continue
                league = cols[0]
                bet_key = cols[1]
                decided = int(cols[2])
                wins = int(cols[3])
                losses = int(cols[4])
                win_rate = float(cols[5])

            lb[(league, bet_key)] = {
                "decided": decided,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
            }
        except Exception:
            continue

    league_bet = lb if lb else None

    # ----------------------------
    # TEAM x BET
    # ----------------------------
    rows = _read_tsv_rows(team_path)
    wanted = {"league", "team", "bet_key", "samples", "success", "fail", "success_rate"}
    idx_map, data_start = _detect_header_row(rows, wanted)

    tb: dict = {}
    for r in rows[data_start:]:
        try:
            cols = [c.strip() for c in r]
            if not cols:
                continue
            if cols[0].startswith("#"):
                continue

            if idx_map:
                league = cols[idx_map["league"]]
                team = cols[idx_map["team"]]
                bet_key = cols[idx_map["bet_key"]]
                samples = int(cols[idx_map["samples"]])
                success = int(cols[idx_map["success"]])
                fail = int(cols[idx_map["fail"]])
                success_rate = float(cols[idx_map["success_rate"]])

                decided = samples
                wins = success
                losses = fail
                win_rate = success_rate
            else:
                if len(cols) < 7:
                    continue
                league = cols[0]
                team = cols[1]
                bet_key = cols[2]
                decided = int(cols[3])
                wins = int(cols[4])
                losses = int(cols[5])
                win_rate = float(cols[6])

            tb[(team, league, bet_key)] = {
                "decided": decided,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
            }
        except Exception:
            continue

    team_bet = tb if tb else None

    _rankings_cache = {"league_bet": league_bet, "team_bet": team_bet}
    return league_bet, team_bet

# ----------------------------
# Global bet stats (toutes ligues confondues) depuis verdict_post_analyse.txt
# ----------------------------
_global_bet_cache: Optional[Dict[str, Dict[str, float]]] = None

def _load_global_bet_stats() -> Dict[str, Dict[str, float]]:
    global _global_bet_cache
    if _global_bet_cache is not None:
        return _global_bet_cache

    out: Dict[str, Dict[str, float]] = {}
    if not GLOBAL_VERDICT_HISTORY_FILE.exists() or GLOBAL_VERDICT_HISTORY_FILE.stat().st_size == 0:
        _global_bet_cache = out
        return out

    with GLOBAL_VERDICT_HISTORY_FILE.open("r", encoding="utf-8") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line.startswith("TSV:"):
                continue
            parts = line[4:].lstrip().split("\t")
            if len(parts) < 11:
                continue
            bet_key = parts[5].strip().upper()
            played = parts[9].strip()
            ev = parts[10].strip().upper()
            if played != "1":
                continue
            if ev not in ("WIN", "LOSS"):
                continue

            fam = _norm_bet_family(bet_key)
            out.setdefault(fam, {"wins": 0.0, "losses": 0.0, "decided": 0.0, "win_rate": 0.0})
            if ev == "WIN":
                out[fam]["wins"] += 1.0
            else:
                out[fam]["losses"] += 1.0

    for fam, agg in out.items():
        decided = int(agg["wins"] + agg["losses"])
        agg["decided"] = float(decided)
        agg["win_rate"] = (agg["wins"] / decided) if decided else 0.0

    _global_bet_cache = out
    return out

# ----------------------------
# SYSTEM gating + weighting
# ----------------------------

def _global_bet_is_eligible(p: Pick) -> bool:
    cfg = T()
    fam = _norm_bet_family(p.bet_key)
    stats = _load_global_bet_stats().get(fam)
    if not stats:
        return True

    decided = int(stats.get("decided", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    if decided >= cfg.global_bet_min_decided:
        return win_rate >= cfg.global_bet_min_winrate
    return True

def _team_row(team_bet: Optional[dict], team: str, league: str, bet_key: str) -> Optional[dict]:
    if team_bet is None:
        return None
    return team_bet.get((team, league, bet_key))

def _team_rate(team_bet: Optional[dict], team: str, league: str, bet_key: str) -> Tuple[Optional[float], int]:
    row = _team_row(team_bet, team, league, bet_key)
    if not row:
        return None, 0
    decided = int(row.get("decided", 0) or 0)
    wr = float(row.get("win_rate", 0.0) or 0.0)
    return wr, decided

def _league_bet_rate(
    league_bet: Optional[dict],
    league: str,
    bet_key: str,
) -> Tuple[Optional[float], int]:
    """
    Retourne (win_rate, decided) pour (league x bet_key).
    """
    if league_bet is None:
        return None, 0

    lg = (league or "").strip()
    bk_raw = (bet_key or "").strip()
    bk_norm = _norm_bet_family(bk_raw)

    candidates = [
        (lg, bk_norm),
        (lg, bk_raw),
        (lg, bk_norm.upper()),
        (lg, bk_raw.upper()),
    ]

    row = None
    for k in candidates:
        row = league_bet.get(k)
        if row:
            break

    if not row:
        return None, 0

    decided = int(row.get("decided", 0) or 0)
    wr = float(row.get("win_rate", 0.0) or 0.0)
    return wr, decided

def _league_bet_is_eligible(
    p: Pick,
    league_bet: Optional[dict],
) -> bool:
    cfg = T()

    if not ENABLE_RANKINGS:
        return True

    league = (p.league or "").strip()
    fam = _norm_bet_family(p.bet_key)

    wr, dec = _league_bet_rate(league_bet, league, fam)

    if dec <= 0:
        return (not cfg.league_bet_require_data)

    return (wr is not None) and (wr >= cfg.league_bet_min_winrate)

def _system_accept_pick(p: Pick, league_bet: Optional[dict], team_bet: Optional[dict]) -> bool:
    cfg = T()

    if not ENABLE_RANKINGS:
        return True

    if not _global_bet_is_eligible(p):
        return False

    if not _league_bet_is_eligible(p, league_bet):
        return False

    bet_key = _norm_bet_family(p.bet_key)
    league = (p.league or "").strip()
    teams = _pick_primary_teams(p)

    if len(teams) == 1:
        wr, dec = _team_rate(team_bet, teams[0], league, bet_key)
        if dec >= cfg.team_min_decided:
            return (wr is not None) and (wr >= cfg.team_min_winrate)
        return True

    t1, t2 = teams[0], teams[1]
    wr1, dec1 = _team_rate(team_bet, t1, league, bet_key)
    wr2, dec2 = _team_rate(team_bet, t2, league, bet_key)

    if dec1 >= cfg.team_min_decided and (wr1 is None or wr1 < cfg.team_min_winrate):
        if dec2 >= cfg.team_min_decided and wr2 is not None:
            hi = max(wr1 or 0.0, wr2)
            lo = min(wr1 or 0.0, wr2)
            if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
                return True
        return False

    if dec2 >= cfg.team_min_decided and (wr2 is None or wr2 < cfg.team_min_winrate):
        if dec1 >= cfg.team_min_decided and wr1 is not None:
            hi = max(wr1, wr2 or 0.0)
            lo = min(wr1, wr2 or 0.0)
            if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
                return True
        return False

    if dec1 >= cfg.team_min_decided and dec2 >= cfg.team_min_decided and (wr1 is not None) and (wr2 is not None):
        lo = min(wr1, wr2)
        hi = max(wr1, wr2)
        if lo >= cfg.team_min_winrate:
            return True
        if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
            return True
        return False

    return True

def _system_match_mean_winrate(p: Pick, league_bet: Optional[dict], team_bet: Optional[dict]) -> float:
    """
    Moyenne WR baseline équipes du match, avec sécurité coef(n).
    """
    cfg = T()

    if not ENABLE_RANKINGS:
        return cfg.weight_baseline

    bet_key = _norm_bet_family(p.bet_key)
    league = (p.league or "").strip()

    teams = _pick_primary_teams(p)
    vals: List[float] = []

    for t in teams:
        wr, dec = _team_rate(team_bet, t, league, bet_key)
        if dec > 0 and wr is not None:
            c = _confidence_coef(dec, n_full=5, base=0.70)
            vals.append(float(wr) * c)

    if not vals:
        return cfg.weight_baseline

    m = sum(vals) / len(vals)
    if m < 0.0:
        m = 0.0
    if m > 1.0:
        m = 1.0
    return m

def _winrate_to_weight(mean_wr: float) -> float:
    cfg = T()

    wr = float(mean_wr or 0.0)
    if wr <= cfg.weight_baseline:
        return cfg.weight_min
    if wr >= cfg.weight_ceil:
        return cfg.weight_max

    span = max(1e-9, (cfg.weight_ceil - cfg.weight_baseline))
    x = (wr - cfg.weight_baseline) / span
    w = cfg.weight_min + (cfg.weight_max - cfg.weight_min) * (x ** 0.5)

    if w < cfg.weight_min:
        w = cfg.weight_min
    if w > cfg.weight_max:
        w = cfg.weight_max
    return w

def _system_priority_weight_league(p: Pick, league_bet: Optional[dict]) -> float:
    """
    Pondération de génération (SYSTEM) basée sur LEAGUE x BET (comme RANDOM),
    tout en gardant un petit bonus sur la cote.
    Objectif : explorer/générer surtout dans les ligues fortes.
    """
    if not ENABLE_RANKINGS:
        base_wr = WEIGHT_BASELINE
        w_perf = _winrate_to_weight(base_wr)
        o = float(p.odd or 1.0)
        w_odd = (0.90 + 0.10 * min(2.0, o))
        return max(RANK_EPS, w_perf) * w_odd

    fam = _norm_bet_family(p.bet_key)
    lg = (p.league or "").strip()
    wr, dec = _league_bet_rate(league_bet, lg, fam)

    # Si pas de data ligue×bet : on met un poids bas (et de toute façon le gate SYSTEM peut rejeter)
    if wr is None or (dec or 0) <= 0:
        mean_wr = 0.0
    else:
        # Même "sécurité statistique" que partout : wr_adj = wr * coef(decided)
        c = _confidence_coef(int(dec), n_full=5, base=0.70)
        mean_wr = float(wr) * float(c)

    # Conversion en poids 1.0 -> 2.5 avec vos bornes WEIGHT_*
    w_perf = _winrate_to_weight(mean_wr)

    # Petit bonus cote (identique au SYSTEM actuel)
    o = float(p.odd or 1.0)
    w_odd = (0.90 + 0.10 * min(2.0, o))

    return max(RANK_EPS, w_perf) * w_odd

# ----------------------------
# Maestrologue — explications scoring (SYSTEM)
# ----------------------------
def _fmt_pct(x: float) -> str:
    try:
        return f"{(float(x) * 100.0):.1f}%"
    except Exception:
        return "—"

def _explain_pick_system(p: Pick, league_bet: Optional[dict], team_bet: Optional[dict]) -> Dict[str, Any]:
    """
    Détail du score pour UN pick (SYSTEM) :
      - home / away : wr, decided, coef, wr_adj
      - mean : moyenne wr_adj
    """
    fam = _norm_bet_family(p.bet_key)
    league = (p.league or "").strip()

    def _team_line(team: str) -> Dict[str, Any]:
        wr, dec = _team_rate(team_bet, team, league, fam)
        if wr is None or dec <= 0:
            return {"team": team, "wr": None, "dec": 0, "coef": 0.0, "wr_adj": 0.0}
        coef = _confidence_coef(dec, n_full=5, base=0.70)
        return {"team": team, "wr": float(wr), "dec": int(dec), "coef": float(coef), "wr_adj": float(wr) * float(coef)}

    home = _team_line(p.home)
    away = _team_line(p.away)

    wrs = [home["wr_adj"], away["wr_adj"]]
    mean = (sum(wrs) / len(wrs)) if wrs else 0.0

    return {"fam": fam, "league": league, "home": home, "away": away, "mean": mean}

def _explain_ticket_system(picks: List[Pick], league_bet: Optional[dict], team_bet: Optional[dict]) -> Dict[str, Any]:
    details = [_explain_pick_system(p, league_bet, team_bet) for p in picks]
    score = _ticket_score_system(picks, league_bet, team_bet)
    return {"score": score, "details": details}

# ----------------------------
# Ticket id stable (avec suffix pipeline)
# ----------------------------
def _ticket_id(ticket: Ticket, *, suffix: str = "") -> str:
    if not ticket.picks:
        return "EMPTY"
    date = ticket.picks[0].date
    legs = sorted([f"{p.match_id}:{p.bet_key}" for p in ticket.picks])
    base = f"{suffix}|{date}|{ticket.start_time}|{ticket.end_time}|{'|'.join(legs)}"
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    suf = f"_{suffix}" if suffix else ""
    return f"{date}_{ticket.start_time.replace(':','')}_{h}{suf}"

# ----------------------------
# Lecture TSV predictions
# ----------------------------
def load_predictions_tsv(tsv_path: str) -> List[Pick]:
    p = Path(tsv_path)
    if not p.exists():
        raise FileNotFoundError(f"TSV introuvable : {tsv_path}")

    picks: List[Pick] = []
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                continue

            parts = line.split("\t")
            if parts and parts[0].strip().upper() == "TSV:":
                parts = parts[1:]

            if len(parts) < 12:
                continue

            match_id = parts[0].strip()
            date = parts[1].strip()
            league = parts[2].strip()
            home = parts[3].strip()
            away = parts[4].strip()
            bet_key = parts[5].strip()
            metric = parts[6].strip()
            score = _safe_float(parts[7].strip(), 0.0)
            label = parts[8].strip()

            try:
                is_candidate = int(parts[9].strip() or "0")
            except Exception:
                is_candidate = 0

            comment = parts[10].strip()
            time_str = parts[11].strip()

            odd = _parse_odd(comment)
            fixture_id = _parse_fixture(comment)

            picks.append(
                Pick(
                    match_id=match_id,
                    date=date,
                    league=league,
                    home=home,
                    away=away,
                    bet_key=bet_key,
                    metric=metric,
                    score=score,
                    label=label,
                    is_candidate=is_candidate,
                    comment=comment,
                    time_str=time_str,
                    odd=odd,
                    fixture_id=fixture_id,
                )
            )
    return picks

# ----------------------------
# Filtrages (SYSTEM / O15_RANDOM_ALL)
# ----------------------------
def filter_playable_system(picks: List[Pick]) -> List[Pick]:
    out: List[Pick] = []
    for p in picks:
        if p.is_candidate != 1:
            continue
        if p.odd is None:
            continue
        if p.odd < MIN_ODD:
            continue
        if _is_excluded_pick_system(p):
            continue
        out.append(p)

    out.sort(key=lambda x: (_time_to_minutes(x.time_str), -(x.odd or 0.0)))
    return out

def filter_o15_random_all(picks: List[Pick]) -> List[Pick]:
    out: List[Pick] = []
    for p in picks:
        bk = (p.bet_key or "").strip().upper()
        is_o15 = (bk == O15_CANON) or ("O15" in bk) or ("OVER15" in bk) or ("OVER_1_5" in bk)
        if not is_o15:
            continue
        if p.odd is None:
            continue
        if p.odd < MIN_ODD:
            continue
        out.append(p)

    out.sort(key=lambda x: (_time_to_minutes(x.time_str), -(x.odd or 0.0)))
    return out

def filter_effective_system_pool(
    picks: List[Pick],
    league_bet: Optional[dict],
    team_bet: Optional[dict],
) -> List[Pick]:
    """
    Pool réellement jouable par le pipeline SYSTEM :
    - déjà filtré structurellement
    - puis validé par les vrais gates perf SYSTEM
    """
    out: List[Pick] = []
    for p in picks:
        if _system_accept_pick(p, league_bet, team_bet):
            out.append(p)

    out.sort(key=lambda x: (_time_to_minutes(x.time_str), -(x.odd or 0.0)))
    return out


def filter_effective_random_pool(
    picks: List[Pick],
    league_bet: Optional[dict],
) -> List[Pick]:
    """
    Pool réellement jouable par le pipeline RANDOM :
    - déjà filtré structurellement sur O15
    - puis validé par le gate league x bet
    """
    cfg = T()
    out: List[Pick] = []

    for p in picks:
        fam = _norm_bet_family(p.bet_key)
        lg = (p.league or "").strip()
        wr, dec = _league_bet_rate(league_bet, lg, fam)

        if dec <= 0:
            if cfg.league_bet_require_data:
                continue
            out.append(p)
            continue

        if wr is not None and float(wr) >= float(cfg.league_bet_min_winrate):
            out.append(p)

    out.sort(key=lambda x: (_time_to_minutes(x.time_str), -(x.odd or 0.0)))
    return out

# ----------------------------
# Tranches "physiques"
# ----------------------------

@dataclass(frozen=True)
class Tranche:
    start_min: int
    end_min: int
    picks: List[Pick]

def _unique_match_count(picks: List[Pick]) -> int:
    return len({_match_key(p) for p in picks})

def _build_day_tranches(sorted_picks: List[Pick], *, rich_day: bool) -> List[Tranche]:
    """
    Petite journée :
      - 1 seule grande fenêtre

    Grosse journée :
      - 2 grandes fenêtres max
      - coupure déterministe entre deux groupes horaires
      - on favorise :
          1) des côtés pas trop déséquilibrés en nombre de matchs
          2) une vraie pause horaire (gap) entre les deux
      - on ne coupe jamais au milieu d'un paquet de matchs à la même heure
    """
    if not sorted_picks:
        return []

    # 1 seule fenêtre si journée normale
    if not rich_day:
        mins = [_time_to_minutes(p.time_str) for p in sorted_picks]
        mins = [m for m in mins if m < 10**8]
        if not mins:
            return []
        return [Tranche(start_min=min(mins), end_min=max(mins), picks=list(sorted_picks))]

    # Regroupement par heure exacte
    groups: List[Tuple[int, List[Pick], int]] = []
    current_tm: Optional[int] = None
    current_picks: List[Pick] = []

    for p in sorted(sorted_picks, key=lambda x: _time_to_minutes(x.time_str)):
        tm = _time_to_minutes(p.time_str)
        if tm >= 10**8:
            continue

        if current_tm is None or tm != current_tm:
            if current_picks:
                groups.append(
                    (
                        current_tm,
                        list(current_picks),
                        len({_match_key(x) for x in current_picks}),
                    )
                )
            current_tm = tm
            current_picks = [p]
        else:
            current_picks.append(p)

    if current_picks and current_tm is not None:
        groups.append(
            (
                current_tm,
                list(current_picks),
                len({_match_key(x) for x in current_picks}),
            )
        )

    if len(groups) <= 1:
        mins = [_time_to_minutes(p.time_str) for p in sorted_picks]
        mins = [m for m in mins if m < 10**8]
        if not mins:
            return []
        return [Tranche(start_min=min(mins), end_min=max(mins), picks=list(sorted_picks))]

    total_matches = sum(g[2] for g in groups)
    if total_matches < (2 * MIN_SIDE_MATCHES_FOR_SPLIT):
        mins = [_time_to_minutes(p.time_str) for p in sorted_picks]
        mins = [m for m in mins if m < 10**8]
        if not mins:
            return []
        return [Tranche(start_min=min(mins), end_min=max(mins), picks=list(sorted_picks))]

    # Choix déterministe de la coupure :
    # - équilibre gauche/droite
    # - bonus si la coupure tombe dans un gros creux horaire
    best_idx: Optional[int] = None
    best_score: Optional[float] = None
    best_gap: int = -1

    left_matches = 0
    for i in range(len(groups) - 1):
        tm_i, _, cnt_i = groups[i]
        tm_next, _, _ = groups[i + 1]

        left_matches += cnt_i
        right_matches = total_matches - left_matches

        if left_matches < MIN_SIDE_MATCHES_FOR_SPLIT:
            continue
        if right_matches < MIN_SIDE_MATCHES_FOR_SPLIT:
            continue

        gap_min = max(0, tm_next - tm_i)
        imbalance = abs(left_matches - right_matches) / max(1, total_matches)
        gap_bonus = min(gap_min, 180) / 180.0

        # plus le score est bas, mieux c'est
        score = imbalance - (gap_bonus * SPLIT_GAP_WEIGHT)

        if (
            best_score is None
            or score < best_score
            or (abs(score - best_score) < 1e-9 and gap_min > best_gap)
        ):
            best_score = score
            best_idx = i
            best_gap = gap_min

    if best_idx is None:
        mins = [_time_to_minutes(p.time_str) for p in sorted_picks]
        mins = [m for m in mins if m < 10**8]
        if not mins:
            return []
        return [Tranche(start_min=min(mins), end_min=max(mins), picks=list(sorted_picks))]

    cut_time = groups[best_idx + 1][0]

    left_picks = [p for p in sorted_picks if _time_to_minutes(p.time_str) < cut_time]
    right_picks = [p for p in sorted_picks if _time_to_minutes(p.time_str) >= cut_time]

    out: List[Tranche] = []

    if left_picks:
        left_mins = [_time_to_minutes(p.time_str) for p in left_picks if _time_to_minutes(p.time_str) < 10**8]
        out.append(
            Tranche(
                start_min=min(left_mins),
                end_min=max(left_mins),
                picks=left_picks,
            )
        )

    if right_picks:
        right_mins = [_time_to_minutes(p.time_str) for p in right_picks if _time_to_minutes(p.time_str) < 10**8]
        out.append(
            Tranche(
                start_min=min(right_mins),
                end_min=max(right_mins),
                picks=right_picks,
            )
        )

    return out

def _max_possible_odd(picks: List[Pick]) -> float:
    if not picks:
        return 1.0
    pool = sorted(picks, key=lambda p: -(p.odd or 0.0))
    used: set[str] = set()
    prod = 1.0
    k = 0
    for p in pool:
        mk = _match_key(p)
        if mk in used:
            continue
        used.add(mk)
        prod *= (p.odd or 1.0)
        k += 1
        if k >= MAX_LEG_SIZE:
            break
    return prod

def _ticket_spread_minutes(picks: List[Pick]) -> int:
    if not picks:
        return 0
    mins = [_time_to_minutes(p.time_str) for p in picks]
    mins = [m for m in mins if m < 10**8]
    if not mins:
        return 0
    return max(mins) - min(mins)

def _find_next_tranche_index(tranches: List[Tranche], *, after_min: int) -> int:
    for i, tr in enumerate(tranches):
        if tr.start_min >= after_min:
            return i
    return len(tranches)

def _short_pick(p: Pick) -> str:
    return f"{p.time_str} | {p.league} | {p.home} vs {p.away} | {_norm_bet_family(p.bet_key)} | odd={_fmt_odd(p.odd)}"

def _system_reject_reason(p: Pick, league_bet: Optional[dict], team_bet: Optional[dict]) -> Optional[str]:
    cfg = T()

    if not _global_bet_is_eligible(p):
        fam = _norm_bet_family(p.bet_key)
        s = _load_global_bet_stats().get(fam, {})
        dec = int(s.get("decided", 0) or 0)
        wr = float(s.get("win_rate", 0.0) or 0.0)
        if dec >= cfg.global_bet_min_decided:
            return f"GLOBAL_BET_LOW_SR | fam={fam} wr={wr:.2f} decided={dec} (min_wr={cfg.global_bet_min_winrate:.2f})"
        return f"GLOBAL_BET_UNKNOWN | fam={fam} decided={dec}"

    fam = _norm_bet_family(p.bet_key)
    lg = (p.league or "").strip()
    wr, dec = _league_bet_rate(league_bet, lg, fam)

    if dec <= 0:
        if cfg.league_bet_require_data:
            return f"LEAGUE_BET_NO_DATA | league={lg} bet={fam} decided=0 (require_data={cfg.league_bet_require_data})"
    else:
        if wr is not None and wr < cfg.league_bet_min_winrate:
            return f"LEAGUE_BET_LOW_SR | league={lg} bet={fam} wr={wr:.2f} decided={dec} (min_wr={cfg.league_bet_min_winrate:.2f})"

    bet_key = fam
    league = lg
    teams = _pick_primary_teams(p)

    def _team_wr(team: str) -> tuple[Optional[float], int]:
        return _team_rate(team_bet, team, league, bet_key)

    if len(teams) == 1:
        t = teams[0]
        t_wr, t_dec = _team_wr(t)
        if t_dec >= cfg.team_min_decided and (t_wr is None or t_wr < cfg.team_min_winrate):
            return f"TEAM_LOW_SR | team={t} league={league} bet={bet_key} wr={float(t_wr or 0):.2f} decided={t_dec} (min_wr={cfg.team_min_winrate:.2f})"
        return None

    t1, t2 = teams[0], teams[1]
    wr1, dec1 = _team_wr(t1)
    wr2, dec2 = _team_wr(t2)

    if dec1 >= cfg.team_min_decided and (wr1 is None or wr1 < cfg.team_min_winrate):
        if dec2 >= cfg.team_min_decided and wr2 is not None:
            hi = max(float(wr1 or 0.0), float(wr2))
            lo = min(float(wr1 or 0.0), float(wr2))
            if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
                return None
        return f"TWO_TEAM_REJECT | {t1} wr={float(wr1 or 0):.2f} dec={dec1} | {t2} wr={float(wr2 or 0):.2f} dec={dec2}"

    if dec2 >= cfg.team_min_decided and (wr2 is None or wr2 < cfg.team_min_winrate):
        if dec1 >= cfg.team_min_decided and wr1 is not None:
            hi = max(float(wr1), float(wr2 or 0.0))
            lo = min(float(wr1), float(wr2 or 0.0))
            if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
                return None
        return f"TWO_TEAM_REJECT | {t1} wr={float(wr1 or 0):.2f} dec={dec1} | {t2} wr={float(wr2 or 0):.2f} dec={dec2}"

    if dec1 >= cfg.team_min_decided and dec2 >= cfg.team_min_decided and wr1 is not None and wr2 is not None:
        lo = min(float(wr1), float(wr2))
        hi = max(float(wr1), float(wr2))
        if lo >= cfg.team_min_winrate:
            return None
        if hi >= cfg.two_team_high and lo >= cfg.two_team_low:
            return None
        return f"TWO_TEAM_REJECT | {t1} wr={float(wr1):.2f} dec={dec1} | {t2} wr={float(wr2):.2f} dec={dec2}"

    return None

def _random_reject_reason(p: Pick, league_bet: Optional[dict]) -> Optional[str]:
    cfg = T()

    fam = _norm_bet_family(p.bet_key)
    lg = (p.league or "").strip()
    wr, dec = _league_bet_rate(league_bet, lg, fam)

    if dec <= 0:
        if cfg.league_bet_require_data:
            return f"RANDOM_LEAGUE_NO_DATA | league={lg} bet={fam} decided=0 (require_data={cfg.league_bet_require_data})"
        return None

    if wr is not None and float(wr) < float(cfg.league_bet_min_winrate):
        return f"RANDOM_LEAGUE_LOW_SR | league={lg} bet={fam} wr={float(wr):.2f} decided={int(dec)} (min_wr={cfg.league_bet_min_winrate:.2f})"

    return None

def _diagnose_pool(
    pool: List[Pick],
    *,
    mode: str,
    next_allowed_start_min: int,
    league_bet: Optional[dict],
    team_bet: Optional[dict],
) -> Dict[str, Any]:
    """
    Diagnostic pool :
    - Catégories de rejet structurel (odd, fenêtre)
    - Rejets "perf gate" :
        * SYSTEM : global/league/team gates
        * RANDOM : league x bet gate
    - REASONS : dict clé->raison lisible
    """
    def _reason_key(p: Pick) -> str:
        return f"{_match_key(p)}|{_norm_bet_family(p.bet_key)}"

    res: Dict[str, Any] = {
        "OK_WINDOW": [],
        "OUT_WINDOW": [],
        "PERF_REJECT": [],
        "NO_ODD": [],
        "ODD_TOO_LOW": [],
        "REASONS": {},
    }

    mode_u = (mode or "").strip().upper()

    for p in pool:
        if p.odd is None:
            res["NO_ODD"].append(p)
            continue
        if p.odd < MIN_ODD:
            res["ODD_TOO_LOW"].append(p)
            continue

        tm = _time_to_minutes(p.time_str)
        if tm < next_allowed_start_min:
            res["OUT_WINDOW"].append(p)
            continue

        # ----------------------------
        # PERF gates selon mode
        # ----------------------------
        if mode_u == "SYSTEM" and ENABLE_RANKINGS:
            reason = _system_reject_reason(p, league_bet, team_bet)
            if reason:
                res["PERF_REJECT"].append(p)
                res["REASONS"][_reason_key(p)] = reason
                continue

        if mode_u == "RANDOM":
            # RANDOM gate = league x bet (require_data=True)
            reason = _random_reject_reason(p, league_bet)
            if reason:
                res["PERF_REJECT"].append(p)
                res["REASONS"][_reason_key(p)] = reason
                continue

        res["OK_WINDOW"].append(p)

    return res

# ----------------------------
# Ticket build — 2 modes
# ----------------------------

def _try_build_ticket_system(
    picks: List[Pick],
    rng: random.Random,
    threshold: float,
    *,
    league_bet: Optional[dict],
    team_bet: Optional[dict],
) -> Optional[List[Pick]]:
    cfg = T()

    if not picks:
        return None

    deadline = _deadline_ms(cfg.search_budget_ms_system)
    it = 0
    pool = list(picks)

    weights = [_system_priority_weight_league(p, league_bet) for p in pool]
    if not any(w > 0 for w in weights):
        weights = [1.0 for _ in pool]

    def _final_score(ticket_picks: List[Pick]) -> float:
        return _ticket_score_system(ticket_picks, league_bet, team_bet)

    def _build_exact(order: List[Pick], legs: int) -> Optional[List[Pick]]:
        chosen: List[Pick] = []
        used_matches: set[str] = set()
        total = 1.0

        for p in order:
            if not _system_accept_pick(p, league_bet, team_bet):
                continue

            mk = _match_key(p)
            if mk in used_matches:
                continue

            chosen.append(p)
            used_matches.add(mk)
            total *= (p.odd or 1.0)

            if len(chosen) == legs:
                return chosen if total >= threshold else None

        return None

    top3 = _TopK(cfg.topk_size)
    top4 = _TopK(cfg.topk_size)

    found3 = 0
    found4 = 0

    while _now_perf() < deadline and it < SEARCH_MAX_ITER_SYSTEM:
        it += 1
        order = _weighted_order_no_replacement(pool, weights, rng)

        res3 = _build_exact(order, legs=3)
        if res3:
            found3 += 1
            sc3 = _final_score(res3)
            top3.push(sc3, res3)

        res4 = _build_exact(order, legs=4)
        if res4:
            found4 += 1
            sc4 = _final_score(res4)
            top4.push(sc4, res4)

    items3 = top3.items_desc()
    items4 = top4.items_desc()

    draw3 = _uniform_draw_topk(rng, items3) if cfg.topk_uniform_draw else (items3[0] if items3 else None)
    draw4 = _uniform_draw_topk(rng, items4) if cfg.topk_uniform_draw else (items4[0] if items4 else None)

    best3_picks = draw3.picks if draw3 else None
    best3_score = draw3.score if draw3 else -1e18

    best4_picks = draw4.picks if draw4 else None
    best4_score = draw4.score if draw4 else -1e18

    chosen, chosen_score = _prefer_3legs_if_close(
        best4_picks, best4_score,
        best3_picks, best3_score,
        prefer_delta=cfg.prefer_3legs_delta,
    )

    if chosen:
        chosen = list(chosen)

    mlevel = _maestro_level()
    if mlevel >= 2:
        lines: List[str] = []
        lines.append("MAESTROLOGUE — SYSTEM — TOPK uniform draw (3L vs 4L)")
        lines.append("-" * 58)
        lines.append("- generation_weights: LEAGUE x BET (wr_adj = wr * coef(decided)) + small odd bonus")
        lines.append(f"- règle: préférer 3L si écart <= {cfg.prefer_3legs_delta*100:.2f}%")
        lines.append(f"- iterations: {it} | valid_3L_found: {found3} | valid_4L_found: {found4}")
        lines.append(f"- top3_size: {len(items3)} | top4_size: {len(items4)}")
        lines.append("")

        def _TicketOdd(picks_: List[Pick]) -> float:
            prod = 1.0
            for p in picks_:
                prod *= (p.odd or 1.0)
            return prod

        def _snap(items: List[_TopKItem], tag: str) -> None:
            lines.append(f"{tag} (desc):")
            if not items:
                lines.append("  (vide)")
                lines.append("")
                return
            for r, it_ in enumerate(items, start=1):
                lines.append(
                    f"  {tag}[{r}/{len(items)}]: score={_fmt_score_pct(it_.score)} | legs={len(it_.picks)} | odd={_fmt_odd(_TicketOdd(list(it_.picks)))}"
                )
            lines.append("")

        _snap(items3, "TOP3")
        _snap(items4, "TOP4")

        if draw3:
            rank3 = next((i for i, x in enumerate(items3, start=1) if x is draw3), None)
            lines.append(f"DRAW_3L: picked rank={rank3}/{len(items3)} | score={_fmt_score_pct(draw3.score)} | odd={_fmt_odd(_TicketOdd(list(draw3.picks)))}")
        else:
            lines.append("DRAW_3L: (aucun)")

        if draw4:
            rank4 = next((i for i, x in enumerate(items4, start=1) if x is draw4), None)
            lines.append(f"DRAW_4L: picked rank={rank4}/{len(items4)} | score={_fmt_score_pct(draw4.score)} | odd={_fmt_odd(_TicketOdd(list(draw4.picks)))}")
        else:
            lines.append("DRAW_4L: (aucun)")

        if best4_picks and best3_picks and best4_score > 0:
            delta_rel = abs(best4_score - best3_score) / best4_score
            lines.append(f"- écart relatif: {delta_rel*100:.2f}%")
        else:
            lines.append("- écart relatif: —")

        if chosen:
            lines.append(f"=> choisi: {len(chosen)} legs | score={_fmt_score_pct(chosen_score)}")
            lines.append("")
            lines.append("Ticket choisi (aperçu)")
            lines.append("-" * 22)
            lines.extend(_short_ticket_lines(chosen, max_lines=(MAESTRO_MAX_DETAIL_LINES if mlevel >= 3 else 6)))
        else:
            lines.append("=> choisi: aucun (aucune combinaison valide)")

        lines.append("")
        _write_maestro_log("\n".join(lines) + "\n", append=True)

    if mlevel >= 3 and chosen:
        chosen_sorted = sorted(chosen, key=lambda p: _time_to_minutes(p.time_str))
        score = _ticket_score_system(chosen_sorted, league_bet, team_bet)
        details = [_explain_pick_system(p, league_bet, team_bet) for p in chosen_sorted]

        lines: List[str] = []
        lines.append("MAESTROLOGUE — Détail du score (ticket choisi, SYSTEM)")
        lines.append("-" * 56)
        lines.append(f"- score ticket: {score:.3f} ({_fmt_pct(score)})")
        lines.append(f"- formule: wr_adj = wr * coef(decided), coef(1)=0.70 → coef(>=5)=1.00")
        lines.append("")

        out_lines: List[str] = []
        for i, d in enumerate(details, start=1):
            p = chosen_sorted[i - 1]
            out_lines.append(
                f"{i}) {p.time_str} | {p.league} | {p.home} vs {p.away} | bet={d['fam']} | odd={_fmt_odd(p.odd)}"
            )

            h = d["home"]
            a = d["away"]
            h_wr_str = "—" if h["wr"] is None else f"{float(h['wr']):.2f}"
            a_wr_str = "—" if a["wr"] is None else f"{float(a['wr']):.2f}"

            out_lines.append(
                f"   HOME {h['team']}: wr={h_wr_str} dec={h['dec']} coef={h['coef']:.3f} => adj={h['wr_adj']:.3f} ({_fmt_pct(h['wr_adj'])})"
            )
            out_lines.append(
                f"   AWAY {a['team']}: wr={a_wr_str} dec={a['dec']} coef={a['coef']:.3f} => adj={a['wr_adj']:.3f} ({_fmt_pct(a['wr_adj'])})"
            )
            out_lines.append(f"   MEAN match: {d['mean']:.3f} ({_fmt_pct(d['mean'])})")
            out_lines.append("")

        if len(out_lines) > MAESTRO_MAX_DETAIL_LINES:
            out_lines = out_lines[:MAESTRO_MAX_DETAIL_LINES] + ["… (détails coupés: MAESTRO_MAX_DETAIL_LINES)"]

        lines.extend(out_lines)
        lines.append("")
        _write_maestro_log("\n".join(lines) + "\n", append=True)

    return chosen

def _try_build_ticket_random(
    picks: List[Pick],
    rng: random.Random,
    threshold: float,
    *,
    league_bet: Optional[dict],
    team_bet: Optional[dict],
) -> Optional[List[Pick]]:
    cfg = T()

    if not picks:
        return None
    if league_bet is None:
        return None

    deadline = _deadline_ms(cfg.search_budget_ms_random)
    it = 0
    pool = list(picks)

    def _random_accept_pick(p: Pick) -> bool:
        fam = _norm_bet_family(p.bet_key)
        lg = (p.league or "").strip()
        wr, dec = _league_bet_rate(league_bet, lg, fam)
        if dec <= 0:
            return (not cfg.league_bet_require_data)
        return (wr is not None) and (float(wr) >= float(cfg.league_bet_min_winrate))

    wr_by_pick: List[Optional[float]] = []
    for p in pool:
        fam = _norm_bet_family(p.bet_key)
        lg = (p.league or "").strip()
        wr, dec = _league_bet_rate(league_bet, lg, fam)
        if wr is not None and dec > 0:
            c = _confidence_coef(int(dec), n_full=5, base=0.70)
            wr_by_pick.append(float(wr) * float(c))
        else:
            wr_by_pick.append(None)

    valid = [w for w in wr_by_pick if w is not None]
    mn = min(valid) if valid else None
    mx = max(valid) if valid else None

    def _weight_from_wr_adj(wr_adj: float | None, odd: Optional[float]) -> float:
        if wr_adj is None or mn is None or mx is None or mx == mn:
            w_perf = 1.0
        else:
            w_perf = 1.0 + (float(wr_adj) - float(mn)) / (float(mx) - float(mn))
            w_perf = max(1.0, min(2.0, w_perf))

        o = float(odd or 1.0)
        w_odd = (0.90 + 0.10 * min(2.0, o))
        return max(RANK_EPS, float(w_perf) * float(w_odd))

    weights = [_weight_from_wr_adj(w, p.odd) for w, p in zip(wr_by_pick, pool)]
    if not any(w > 0 for w in weights):
        weights = [1.0 for _ in pool]

    rejected_by_league_gate = 0

    def _build_exact(order: List[Pick], wanted_legs: int) -> Optional[List[Pick]]:
        nonlocal rejected_by_league_gate
        chosen: List[Pick] = []
        used_matches: set[str] = set()
        total = 1.0

        for p in order:
            mk = _match_key(p)
            if mk in used_matches:
                continue

            if not _random_accept_pick(p):
                rejected_by_league_gate += 1
                continue

            chosen.append(p)
            used_matches.add(mk)
            total *= (p.odd or 1.0)

            if len(chosen) >= wanted_legs:
                break

        if len(chosen) != wanted_legs:
            return None
        if total < threshold:
            return None
        return chosen

    def _final_score(ticket_picks: List[Pick]) -> float:
        return _ticket_score_random_team(ticket_picks, team_bet)

    top3 = _TopK(cfg.topk_size)
    top4 = _TopK(cfg.topk_size)

    found3 = 0
    found4 = 0

    while _now_perf() < deadline and it < SEARCH_MAX_ITER_RANDOM:
        it += 1
        order = _weighted_order_no_replacement(pool, weights, rng)

        res3 = _build_exact(order, wanted_legs=3)
        if res3:
            found3 += 1
            top3.push(_final_score(res3), res3)

        res4 = _build_exact(order, wanted_legs=4)
        if res4:
            found4 += 1
            top4.push(_final_score(res4), res4)

    items3 = top3.items_desc()
    items4 = top4.items_desc()

    draw3 = _uniform_draw_topk(rng, items3) if cfg.topk_uniform_draw else (items3[0] if items3 else None)
    draw4 = _uniform_draw_topk(rng, items4) if cfg.topk_uniform_draw else (items4[0] if items4 else None)

    best3_picks = draw3.picks if draw3 else None
    best3_score = draw3.score if draw3 else -1e18

    best4_picks = draw4.picks if draw4 else None
    best4_score = draw4.score if draw4 else -1e18

    chosen, chosen_score = _prefer_3legs_if_close(
        best4_picks, best4_score,
        best3_picks, best3_score,
        prefer_delta=cfg.prefer_3legs_delta,
    )

    if chosen:
        chosen = list(chosen)

    mlevel = _maestro_level()
    if mlevel >= 2:
        def _ticket_odd(picks_: List[Pick]) -> float:
            prod = 1.0
            for p in picks_:
                prod *= (p.odd or 1.0)
            return prod

        lines: List[str] = []
        lines.append("MAESTROLOGUE — RANDOM — TopK uniform draw (3L vs 4L)")
        lines.append("-" * 64)
        lines.append(f"- gate_build: LEAGUE x BET >= {cfg.league_bet_min_winrate:.2f} (require_data={cfg.league_bet_require_data})")
        lines.append("- score_select: TEAM x BET (wr_adj = wr * coef(decided), coef(1)=0.70 → coef(>=5)=1.00)")
        lines.append(f"- règle: préférer 3L si écart <= {cfg.prefer_3legs_delta*100:.2f}%")
        lines.append(f"- iterations: {it} | valid_3L_found: {found3} | valid_4L_found: {found4}")
        lines.append(f"- top3_size: {len(items3)} | top4_size: {len(items4)}")
        lines.append(f"- rejected_by_league_gate (approx): {rejected_by_league_gate}")
        lines.append("")

        def _snap(items: List[_TopKItem], tag: str) -> None:
            lines.append(f"{tag} (desc):")
            if not items:
                lines.append("  (vide)")
                lines.append("")
                return
            for r, it_ in enumerate(items, start=1):
                lines.append(
                    f"  {tag}[{r}/{len(items)}]: score={_fmt_score_pct(it_.score)} | legs={len(it_.picks)} | odd={_fmt_odd(_ticket_odd(list(it_.picks)))}"
                )
            lines.append("")

        _snap(items3, "TOP3")
        _snap(items4, "TOP4")

        if draw3:
            rank3 = next((i for i, x in enumerate(items3, start=1) if x is draw3), None)
            lines.append(
                f"DRAW_3L: picked rank={rank3}/{len(items3)} | score={_fmt_score_pct(draw3.score)} | odd={_fmt_odd(_ticket_odd(list(draw3.picks)))}"
            )
        else:
            lines.append("DRAW_3L: (aucun)")

        if draw4:
            rank4 = next((i for i, x in enumerate(items4, start=1) if x is draw4), None)
            lines.append(
                f"DRAW_4L: picked rank={rank4}/{len(items4)} | score={_fmt_score_pct(draw4.score)} | odd={_fmt_odd(_ticket_odd(list(draw4.picks)))}"
            )
        else:
            lines.append("DRAW_4L: (aucun)")

        if best4_picks and best3_picks and best4_score > 0:
            delta_rel = abs(best4_score - best3_score) / best4_score
            lines.append(f"- écart relatif: {delta_rel*100:.2f}%")
        else:
            lines.append("- écart relatif: —")

        if chosen:
            lines.append(f"=> choisi: {len(chosen)} legs | score={_fmt_score_pct(chosen_score)}")
            lines.append("")
            lines.append("Ticket choisi (aperçu)")
            lines.append("-" * 22)
            lines.extend(_short_ticket_lines(chosen, max_lines=(MAESTRO_MAX_DETAIL_LINES if mlevel >= 3 else 6)))
        else:
            lines.append("=> choisi: aucun (aucune combinaison valide)")

        lines.append("")
        _write_maestro_log("\n".join(lines) + "\n", append=True)

    if mlevel >= 3 and chosen:
        chosen_sorted = sorted(chosen, key=lambda p: _time_to_minutes(p.time_str))
        score = _ticket_score_random_team(chosen_sorted, team_bet)

        lines: List[str] = []
        lines.append("MAESTROLOGUE — RANDOM — Détail du score (ticket choisi, TEAM x BET)")
        lines.append("-" * 78)
        lines.append(f"- score ticket: {score:.3f} ({_fmt_pct(score)})")
        lines.append("- formule: wr_adj = wr(team x bet) * coef(decided), coef(1)=0.70 → coef(>=5)=1.00")
        lines.append("")

        out_lines: List[str] = []
        for i, p in enumerate(chosen_sorted, start=1):
            fam = _norm_bet_family(p.bet_key)
            lg = (p.league or "").strip()

            wr1, dec1 = _team_rate(team_bet, p.home, lg, fam)
            if wr1 is not None and dec1 > 0:
                coef1 = _confidence_coef(int(dec1), n_full=5, base=0.70)
                adj1 = float(wr1) * float(coef1)
                wr1_str = f"{float(wr1):.2f}"
                coef1_str = f"{float(coef1):.3f}"
                adj1_str = f"{float(adj1):.3f}"
                adj1_pct = _fmt_pct(adj1)
            else:
                wr1_str = "—"
                dec1 = 0
                coef1_str = "0.000"
                adj1_str = "0.000"
                adj1_pct = _fmt_pct(0.0)

            wr2, dec2 = _team_rate(team_bet, p.away, lg, fam)
            if wr2 is not None and dec2 > 0:
                coef2 = _confidence_coef(int(dec2), n_full=5, base=0.70)
                adj2 = float(wr2) * float(coef2)
                wr2_str = f"{float(wr2):.2f}"
                coef2_str = f"{float(coef2):.3f}"
                adj2_str = f"{float(adj2):.3f}"
                adj2_pct = _fmt_pct(adj2)
            else:
                wr2_str = "—"
                dec2 = 0
                coef2_str = "0.000"
                adj2_str = "0.000"
                adj2_pct = _fmt_pct(0.0)

            vals: List[float] = []
            if wr1 is not None and int(dec1 or 0) > 0:
                vals.append(float(adj1_str))
            if wr2 is not None and int(dec2 or 0) > 0:
                vals.append(float(adj2_str))
            mean = (sum(vals) / len(vals)) if vals else 0.0

            out_lines.append(
                f"{i}) {p.time_str} | {p.league} | {p.home} vs {p.away} | bet={fam} | odd={_fmt_odd(p.odd)}"
            )
            out_lines.append(
                f"   HOME {p.home}: wr={wr1_str} dec={int(dec1)} coef={coef1_str} => adj={adj1_str} ({adj1_pct})"
            )
            out_lines.append(
                f"   AWAY {p.away}: wr={wr2_str} dec={int(dec2)} coef={coef2_str} => adj={adj2_str} ({adj2_pct})"
            )
            out_lines.append(f"   MEAN match: {mean:.3f} ({_fmt_pct(mean)})")
            out_lines.append("")

        if len(out_lines) > MAESTRO_MAX_DETAIL_LINES:
            out_lines = out_lines[:MAESTRO_MAX_DETAIL_LINES] + ["… (détails coupés: MAESTRO_MAX_DETAIL_LINES)"]

        lines.extend(out_lines)
        lines.append("")
        _write_maestro_log("\n".join(lines) + "\n", append=True)

    return chosen

def _build_tickets_for_one_day(sorted_picks: List[Pick], *, mode: str) -> List[Ticket]:
    if not sorted_picks:
        return []

    league_bet, team_bet = _load_rankings()

    day_match_count = _unique_match_count(sorted_picks)
    is_rich = day_match_count >= RICH_DAY_MATCH_COUNT
    max_tickets_today = DAY_MAX_TICKETS_RICH if is_rich else DAY_MAX_TICKETS_POOR

    day_max = _max_possible_odd(sorted_picks)
    cfg = T()
    day_threshold = cfg.target_odd if day_max >= cfg.target_odd else cfg.min_accept_odd

    windows = _build_day_tranches(sorted_picks, rich_day=is_rich)

    rng = random.Random()
    used_legs: set[Tuple[str, str]] = set()

    tickets_out: List[Ticket] = []
    group_no = 0
    next_allowed_start_min = 0

    mlevel = _maestro_level()
    maestro_lines: List[str] = []

    if mlevel >= 1:
        d = sorted_picks[0].date if sorted_picks else "—"
        maestro_lines.append(f"MAESTROLOGUE — {mode.upper()} — {d}")
        maestro_lines.append("=" * 40)
        maestro_lines.append(f"- picks_total: {len(sorted_picks)}")
        maestro_lines.append(f"- unique_matches_day: {day_match_count}")
        maestro_lines.append(f"- rich_day: {is_rich}")
        maestro_lines.append(f"- max_tickets_today: {max_tickets_today}")
        maestro_lines.append(f"- windows_count: {len(windows)}")
        maestro_lines.append(f"- day_max_possible_odd: {_fmt_odd(day_max)}")
        maestro_lines.append(
            f"- threshold_used: {_fmt_odd(day_threshold)} "
            f"(target={_fmt_odd(cfg.target_odd)}, fallback={_fmt_odd(cfg.min_accept_odd)})"
        )
        maestro_lines.append(f"- replay_after_last_kickoff: {MATCH_DURATION_MIN} min")
        maestro_lines.append("")

    idx = 0
    while idx < len(windows):
        if len(tickets_out) >= max_tickets_today:
            break

        merge_start_idx = idx
        merge_end_idx = idx
        merged_picks = list(windows[idx].picks)

        combo: Optional[List[Pick]] = None
        final_ok_pool: List[Pick] = []
        final_diag: Optional[Dict[str, Any]] = None

        while True:
            merged_start = min(
                (_time_to_minutes(p.time_str) for p in merged_picks),
                default=10**9
            )
            merged_end = max(
                (_time_to_minutes(p.time_str) for p in merged_picks),
                default=-1
            )

            window_filtered = [
                p for p in merged_picks
                if (p.match_id, p.bet_key) not in used_legs
                and _time_to_minutes(p.time_str) >= next_allowed_start_min
            ]

            diag = _diagnose_pool(
                window_filtered,
                mode=mode,
                next_allowed_start_min=next_allowed_start_min,
                league_bet=league_bet,
                team_bet=team_bet,
            )
            ok_pool = diag["OK_WINDOW"]
            max_ok_odd = _max_possible_odd(ok_pool)

            if mlevel >= 2:
                label = (
                    f"WINDOW {merge_start_idx + 1}"
                    if merge_start_idx == merge_end_idx
                    else f"WINDOWS {merge_start_idx + 1}->{merge_end_idx + 1} (MERGED)"
                )
                maestro_lines.append(
                    f"{label} | {_minutes_to_time(merged_start)} -> {_minutes_to_time(merged_end)}"
                )
                maestro_lines.append(f"  - raw_window_picks: {len(merged_picks)}")
                maestro_lines.append(f"  - filtered_window_picks: {len(window_filtered)}")
                maestro_lines.append(f"  - ok_window: {len(diag['OK_WINDOW'])}")
                maestro_lines.append(f"  - perf_reject: {len(diag['PERF_REJECT'])}")
                maestro_lines.append(f"  - out_window: {len(diag['OUT_WINDOW'])}")
                maestro_lines.append(f"  - no_odd: {len(diag['NO_ODD'])} | odd_too_low: {len(diag['ODD_TOO_LOW'])}")
                maestro_lines.append(f"  - max_possible_odd(ok_window): {_fmt_odd(max_ok_odd)}")

            if max_ok_odd < day_threshold:
                if merge_end_idx + 1 < len(windows):
                    merge_end_idx += 1
                    merged_picks.extend(windows[merge_end_idx].picks)

                    if mlevel >= 2:
                        maestro_lines.append(
                            f"  -> MERGE avec WINDOW {merge_end_idx + 1} car cote max insuffisante "
                            f"({_fmt_odd(max_ok_odd)} < {_fmt_odd(day_threshold)})"
                        )
                        maestro_lines.append("")
                    continue
                else:
                    if mlevel >= 2:
                        maestro_lines.append(
                            f"  -> ABANDON: cote max insuffisante même après fusion "
                            f"({_fmt_odd(max_ok_odd)} < {_fmt_odd(day_threshold)})"
                        )
                        maestro_lines.append("")
                    final_ok_pool = ok_pool
                    final_diag = diag
                    break

            if mode.upper() == "SYSTEM":
                combo = _try_build_ticket_system(
                    ok_pool,
                    rng,
                    threshold=day_threshold,
                    league_bet=league_bet,
                    team_bet=team_bet,
                )
            else:
                combo = _try_build_ticket_random(
                    ok_pool,
                    rng,
                    threshold=day_threshold,
                    league_bet=league_bet,
                    team_bet=team_bet,
                )

            final_ok_pool = ok_pool
            final_diag = diag

            if not combo:
                if mlevel >= 2:
                    maestro_lines.append("  -> ABANDON: aucune combinaison valide")
                    maestro_lines.append("")
                break

            break

        if combo:
            combo_sorted = sorted(combo, key=lambda p: _time_to_minutes(p.time_str))

            group_no += 1
            t = Ticket(
                picks=combo_sorted,
                target_reached=(day_threshold == cfg.target_odd),
                group_no=group_no,
                option_no=1,
                spread_minutes=_ticket_spread_minutes(combo_sorted),
            )
            tickets_out.append(t)

            for p in combo_sorted:
                used_legs.add((p.match_id, p.bet_key))

            if mlevel >= 1:
                maestro_lines.append(
                    f"Ticket: tranche={group_no} | cote={_fmt_odd(t.total_odd)} "
                    f"| {t.start_time} → {t.end_time} | fenêtre={t.spread_minutes}min"
                )
                if mlevel >= 2:
                    for k, p in enumerate(combo_sorted, start=1):
                        maestro_lines.append(f"  {k}) {_short_pick(p)}")
                maestro_lines.append("")

            next_allowed_start_min = t.end_time_minutes
            idx = merge_end_idx + 1
        else:
            idx = merge_end_idx + 1

    if mlevel >= 1:
        maestro_lines.append("FIN JOURNÉE")
        maestro_lines.append("-" * 18)
        maestro_lines.append(f"- tickets_built: {len(tickets_out)} / {max_tickets_today}")
        maestro_lines.append(f"- next_window_start: {_minutes_to_time(next_allowed_start_min)}")
        maestro_lines.append("")
        _write_maestro_log("\n".join(maestro_lines).rstrip() + "\n\n", append=True)

    return tickets_out

def build_tickets(by_date_sorted: List[Pick], *, mode: str) -> List[Ticket]:
    by_date: Dict[str, List[Pick]] = {}
    for p in by_date_sorted:
        by_date.setdefault(p.date, []).append(p)

    out: List[Ticket] = []
    for d in sorted(by_date.keys()):
        day_picks = by_date[d]
        day_picks.sort(key=lambda x: (_time_to_minutes(x.time_str), -(x.odd or 0.0)))
        out.extend(_build_tickets_for_one_day(day_picks, mode=mode))

    out.sort(key=lambda t: (
        t.picks[0].date if t.picks else "",
        t.group_no,
        t.option_no,
        _time_to_minutes(t.start_time),
    ))
    return out

# ----------------------------
# Export TSV (append + dédup)
# ----------------------------
def write_tickets_tsv(tickets: List[Ticket], path: Path, *, id_suffix: str = "") -> int:
    if not tickets:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)

    existing: set[Tuple[str, str, str]] = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line.startswith("TSV:"):
                    continue
                parts = line[4:].lstrip().split("\t")
                if len(parts) < 9:
                    continue
                ticket_id = parts[0].strip()
                match_id = parts[6].strip()
                bet_key = parts[7].strip()
                if ticket_id and match_id and bet_key:
                    existing.add((ticket_id, match_id, bet_key))

    new_lines: List[str] = []

    for t in tickets:
        tid = _ticket_id(t, suffix=id_suffix)
        total = t.total_odd
        code = "A2" if total >= T().target_odd else "RESTE"
        tot = _fmt_odd(total)

        date = t.picks[0].date if t.picks else ""
        st = t.start_time
        et = t.end_time

        for p in t.picks:
            odd_s = _fmt_odd(p.odd)
            key = (tid, p.match_id, p.bet_key)
            if key in existing:
                continue
            new_lines.append(
                "TSV: " + "\t".join([
                    tid, date, st, et, code, tot,
                    p.match_id, p.bet_key, p.time_str,
                    p.league, p.home, p.away,
                    p.metric, p.label, odd_s,
                ])
            )

    if not new_lines:
        return 0

    with path.open("a", encoding="utf-8") as f:
        for l in new_lines:
            f.write(l + "\n")

    return len(new_lines)

# ----------------------------
# Report humain (run)
# ----------------------------
def render_tickets_report(tickets: List[Ticket], title: str, *, id_suffix: str = "") -> str:
    lines: List[str] = []
    lines.append(title)
    lines.append("=" * max(18, len(title)))
    lines.append("")

    if not tickets:
        lines.append("Aucun ticket.")
        return "\n".join(lines)

    by_date_group: Dict[Tuple[str, int], List[Ticket]] = {}
    for t in tickets:
        d = t.picks[0].date if t.picks else ""
        by_date_group.setdefault((d, t.group_no), []).append(t)

    for (d, gno) in sorted(by_date_group.keys()):
        group_tickets = by_date_group[(d, gno)]
        group_tickets.sort(key=lambda t: t.option_no)

        day = _weekday_fr(d)
        day_part = f"{day} " if day else ""

        spread_min = group_tickets[0].spread_minutes if group_tickets else 0
        spread_info = f" (fenêtre ~{spread_min}min)" if spread_min else ""

        lines.append(f"📅 {day_part}{d} — Tranche {gno}{spread_info}")
        lines.append("-" * (len(lines[-1])))
        lines.append("")

        for t in group_tickets:
            total_str = _fmt_odd(t.total_odd)
            code = "A2" if t.total_odd >= T().target_odd else "RESTE"
            ticket_label = f"{t.group_no}.{t.option_no}"
            tid = _ticket_id(t, suffix=id_suffix)

            title_line = (
                f"🎟️ TICKET {ticket_label} ({code}) — id={tid} — cote = {total_str} "
                f"— fenêtre {t.start_time} → {t.end_time}"
            )
            sep = "━" * (len(title_line) + 4)

            lines.append(sep)
            lines.append(f"  {title_line}  ")
            lines.append(sep)

            for j, p in enumerate(t.picks, start=1):
                odd_str = _fmt_odd(p.odd)
                lines.append(
                    f"  {j}) {p.time_str} | {p.league} | {p.home} vs {p.away} | "
                    f"{p.metric} | {p.label} | odd={odd_str}"
                )
            lines.append("")

    return "\n".join(lines)

# ----------------------------
# Report humain (GLOBAL) : append + dédup ticket_id
# ----------------------------
def _load_ticket_ids_from_text(text: str) -> Set[str]:
    out: Set[str] = set()
    if not text:
        return out
    for m in _TICKET_ID_RE.finditer(text):
        out.add(m.group(1).strip())
    return out

def _extract_ticket_blocks(report_text: str) -> Dict[str, str]:
    if not report_text:
        return {}

    lines = report_text.splitlines()
    ticket_line_idxs: List[int] = []
    ticket_ids_by_idx: Dict[int, str] = {}

    for i, line in enumerate(lines):
        m = _TICKET_ID_RE.search(line)
        if m:
            tid = m.group(1).strip()
            ticket_line_idxs.append(i)
            ticket_ids_by_idx[i] = tid

    if not ticket_line_idxs:
        return {}

    blocks: Dict[str, str] = {}
    ticket_line_idxs.sort()

    def _block_start(i: int) -> int:
        if i - 1 >= 0 and lines[i - 1].strip().startswith("━"):
            return max(i - 1, 0)
        if i - 2 >= 0 and lines[i - 2].strip().startswith("━"):
            return max(i - 2, 0)
        return i

    starts: List[int] = [_block_start(i) for i in ticket_line_idxs]
    for k, i in enumerate(ticket_line_idxs):
        tid = ticket_ids_by_idx[i]
        start = starts[k]
        end = (starts[k + 1] - 1) if (k + 1 < len(starts)) else (len(lines) - 1)
        block = "\n".join(lines[start:end + 1]).rstrip() + "\n"
        blocks[tid] = block

    return blocks

def append_report_to_global(
    *,
    report_text: str,
    global_path: Path,
    pipeline_name: str,
    run_date: Optional[str],
    source_tsv: str,
) -> int:
    if not report_text:
        return 0

    blocks = _extract_ticket_blocks(report_text)
    if not blocks:
        return 0

    global_path.parent.mkdir(parents=True, exist_ok=True)

    existing_text = ""
    if global_path.exists() and global_path.stat().st_size > 0:
        existing_text = global_path.read_text(encoding="utf-8", errors="ignore")

    existing_ids = _load_ticket_ids_from_text(existing_text)

    to_add: List[str] = []
    added = 0
    for tid, block in blocks.items():
        if tid in existing_ids:
            continue
        to_add.append(block)
        added += 1

    if not to_add:
        return 0

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rd_part = f"run_date={run_date}" if run_date else "run_date=ALL"
    header = (
        f"\n\n# ------------------------------------------------------------------\n"
        f"# APPEND {pipeline_name} | {stamp} | {rd_part} | source={Path(source_tsv).name}\n"
        f"# ------------------------------------------------------------------\n\n"
    )

    with global_path.open("a", encoding="utf-8") as f:
        if not existing_text.strip():
            f.write(f"{pipeline_name} — TICKETS REPORT GLOBAL (HISTORIQUE)\n")
            f.write("=" * 52 + "\n")
            f.write("Ce fichier s'additionne à chaque run. Ne pas effacer.\n")
            f.write("Chaque ticket contient 'id=<ticket_id>' pour post-analyse.\n\n")

        f.write(header)
        for b in to_add:
            f.write(b)
            if not b.endswith("\n"):
                f.write("\n")

    return added

def append_playable_picks_to_global(
    *,
    picks: List[Pick],
    global_path: Path,
    pipeline_name: str,
    run_date: Optional[str],
    source_tsv: str,
) -> int:
    """
    Append cumulatif des picks jouables dans data/.
    Dédup par signature métier :
      (date, match_id, bet_family, time, league, home, away)
    """
    if not picks:
        return 0

    global_path.parent.mkdir(parents=True, exist_ok=True)

    existing: Set[str] = set()
    if global_path.exists() and global_path.stat().st_size > 0:
        with global_path.open("r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = (raw or "").strip()
                if not line.startswith("TSV:"):
                    continue
                parts = line[4:].lstrip().split("\t")
                if len(parts) < 9:
                    continue
                sig = "||".join(parts[:7])  # date, match_id, bet_family, time, league, home, away
                existing.add(sig)

    new_lines: List[str] = []

    for p in picks:
        bet_family = _norm_bet_family(p.bet_key)
        sig_parts = [
            p.date or "",
            p.match_id or "",
            bet_family,
            p.time_str or "",
            p.league or "",
            p.home or "",
            p.away or "",
        ]
        sig = "||".join(sig_parts)
        if sig in existing:
            continue

        odd_s = _fmt_odd(p.odd)
        fixture_s = p.fixture_id or ""

        line = "TSV: " + "\t".join([
            p.date or "",
            p.match_id or "",
            bet_family,
            p.time_str or "",
            p.league or "",
            p.home or "",
            p.away or "",
            odd_s,
            fixture_s,
            pipeline_name,
            Path(source_tsv).name,
        ])
        new_lines.append(line)
        existing.add(sig)

    if not new_lines:
        return 0

    file_was_empty = (not global_path.exists()) or global_path.stat().st_size == 0

    with global_path.open("a", encoding="utf-8") as f:
        if file_was_empty:
            f.write(f"{pipeline_name} — PLAYABLE PICKS GLOBAL\n")
            f.write("=" * 42 + "\n")
            f.write("Format TSV:\n")
            f.write("date\tmatch_id\tbet_family\ttime\tleague\thome\taway\todd\tfixture_id\tpipeline\tsource\n\n")

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rd_part = f"run_date={run_date}" if run_date else "run_date=ALL"
        f.write(
            f"# ------------------------------------------------------------------\n"
            f"# APPEND {pipeline_name} | {stamp} | {rd_part} | source={Path(source_tsv).name}\n"
            f"# ------------------------------------------------------------------\n"
        )
        for line in new_lines:
            f.write(line + "\n")
        f.write("\n")

    return len(new_lines)

# ----------------------------
# API : 2 pipelines AUTOMATIQUES
# ----------------------------
def _filter_picks_by_run_date(picks: List[Pick], run_date: Optional[str]) -> List[Pick]:
    if not run_date:
        return picks
    return [p for p in picks if (p.date or "").strip() == run_date.strip()]

def generate_tickets_from_tsv(
    tsv_path: str,
    run_date: Optional[str] = None,
    tuning: Optional[BuilderTuning] = None,
) -> TicketBuildOutput:
    _set_active_tuning(tuning)

    try:
        if _maestro_level() >= 1:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hdr = (
                f"RUN MAESTROLOGUE — {stamp}\n"
                f"- source_tsv: {Path(tsv_path).name}\n"
                f"- run_date: {run_date or 'ALL'}\n"
                f"- maestro_level: {_maestro_level()}\n"
                f"{'='*40}\n\n"
            )
            _write_maestro_log(hdr, append=True)

        picks_all = load_predictions_tsv(tsv_path)
        picks = _filter_picks_by_run_date(picks_all, run_date)

        tickets_report_path = _run_scoped_or_data("tickets_report.txt")
        tickets_o15_report_path = _run_scoped_or_data("tickets_o15_random_report.txt")

        suffix = f" — {run_date}" if run_date else ""
        league_bet, team_bet = _load_rankings()
        fast_mode = _optimizer_fast_mode()

        system_pool_base = filter_playable_system(picks)
        system_pool_effective = filter_effective_system_pool(system_pool_base, league_bet, team_bet)

        if not fast_mode:
            added_system_pool_base = append_playable_picks_to_global(
                picks=system_pool_base,
                global_path=SYSTEM_POOL_BASE_GLOBAL_FILE,
                pipeline_name="SYSTEM_POOL_BASE",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_system_pool_base:
                print(f"📦 [SYSTEM] Pool base exporté : {SYSTEM_POOL_BASE_GLOBAL_FILE} (+{added_system_pool_base} lignes)")
            else:
                print(f"ℹ️ [SYSTEM] Pool base inchangé : {SYSTEM_POOL_BASE_GLOBAL_FILE}")

            added_system_pool_effective = append_playable_picks_to_global(
                picks=system_pool_effective,
                global_path=SYSTEM_POOL_EFFECTIVE_GLOBAL_FILE,
                pipeline_name="SYSTEM_POOL_EFFECTIVE",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_system_pool_effective:
                print(f"📦 [SYSTEM] Pool effectif exporté : {SYSTEM_POOL_EFFECTIVE_GLOBAL_FILE} (+{added_system_pool_effective} lignes)")
            else:
                print(f"ℹ️ [SYSTEM] Pool effectif inchangé : {SYSTEM_POOL_EFFECTIVE_GLOBAL_FILE}")

        tickets_system = build_tickets(system_pool_effective, mode="SYSTEM")

        if not fast_mode:
            added_sys = write_tickets_tsv(tickets_system, TICKETS_TSV_FILE, id_suffix="SYS")
            if added_sys:
                print(f"✅ [SYSTEM] Tickets TSV ajoutés : {TICKETS_TSV_FILE} (+{added_sys} lignes)")
            else:
                print("⚠️ [SYSTEM] Aucun ticket TSV écrit (tickets=0 ou dédup).")

            report_system = render_tickets_report(
                tickets_system,
                title=f"TICKETS TRISKÈLE{suffix} — SYSTEM — depuis {Path(tsv_path).name}",
                id_suffix="SYS",
            )
            _write_report_robust(
                run_path=tickets_report_path,
                data_path=Path("data/tickets_report.txt"),
                text=report_system,
            )
            print(f"📝 [SYSTEM] TicketsReport écrit : {tickets_report_path} + data/tickets_report.txt")

            added_sys_global = append_report_to_global(
                report_text=report_system,
                global_path=TICKETS_REPORT_GLOBAL_FILE,
                pipeline_name="SYSTEM",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_sys_global:
                print(f"🧾 [SYSTEM] Global report alimenté : {TICKETS_REPORT_GLOBAL_FILE} (+{added_sys_global} tickets)")
            else:
                print(f"ℹ️ [SYSTEM] Global report inchangé (0 nouveau ticket) : {TICKETS_REPORT_GLOBAL_FILE}")
        else:
            added_sys = 0
            added_sys_global = 0
            report_system = ""

        o15_random_pool_base = filter_o15_random_all(picks)
        o15_random_pool_effective = filter_effective_random_pool(o15_random_pool_base, league_bet)

        if not fast_mode:
            added_o15_random_pool_base = append_playable_picks_to_global(
                picks=o15_random_pool_base,
                global_path=O15_RANDOM_POOL_BASE_GLOBAL_FILE,
                pipeline_name="O15_RANDOM_POOL_BASE",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_o15_random_pool_base:
                print(f"📦 [O15_RANDOM_ALL] Pool base exporté : {O15_RANDOM_POOL_BASE_GLOBAL_FILE} (+{added_o15_random_pool_base} lignes)")
            else:
                print(f"ℹ️ [O15_RANDOM_ALL] Pool base inchangé : {O15_RANDOM_POOL_BASE_GLOBAL_FILE}")

            added_o15_random_pool_effective = append_playable_picks_to_global(
                picks=o15_random_pool_effective,
                global_path=O15_RANDOM_POOL_EFFECTIVE_GLOBAL_FILE,
                pipeline_name="O15_RANDOM_POOL_EFFECTIVE",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_o15_random_pool_effective:
                print(f"📦 [O15_RANDOM_ALL] Pool effectif exporté : {O15_RANDOM_POOL_EFFECTIVE_GLOBAL_FILE} (+{added_o15_random_pool_effective} lignes)")
            else:
                print(f"ℹ️ [O15_RANDOM_ALL] Pool effectif inchangé : {O15_RANDOM_POOL_EFFECTIVE_GLOBAL_FILE}")

        tickets_o15 = build_tickets(o15_random_pool_effective, mode="RANDOM")

        if not fast_mode:
            added_o15 = write_tickets_tsv(tickets_o15, TICKETS_O15_RANDOM_TSV_FILE, id_suffix="O15R")
            if added_o15:
                print(f"✅ [O15_RANDOM_ALL] Tickets TSV ajoutés : {TICKETS_O15_RANDOM_TSV_FILE} (+{added_o15} lignes)")
            else:
                print("⚠️ [O15_RANDOM_ALL] Aucun ticket TSV écrit (tickets=0 ou dédup).")

            report_o15 = render_tickets_report(
                tickets_o15,
                title=f"TICKETS TRISKÈLE{suffix} — O15_RANDOM_ALL — depuis {Path(tsv_path).name}",
                id_suffix="O15R",
            )
            _write_report_robust(
                run_path=tickets_o15_report_path,
                data_path=Path("data/tickets_o15_random_report.txt"),
                text=report_o15,
            )
            print(f"📝 [O15_RANDOM_ALL] TicketsReport écrit : {tickets_o15_report_path} + data/tickets_o15_random_report.txt")

            added_o15_global = append_report_to_global(
                report_text=report_o15,
                global_path=TICKETS_O15_REPORT_GLOBAL_FILE,
                pipeline_name="O15_RANDOM_ALL",
                run_date=run_date,
                source_tsv=tsv_path,
            )
            if added_o15_global:
                print(f"🧾 [O15_RANDOM_ALL] Global report alimenté : {TICKETS_O15_REPORT_GLOBAL_FILE} (+{added_o15_global} tickets)")
            else:
                print(f"ℹ️ [O15_RANDOM_ALL] Global report inchangé (0 nouveau ticket) : {TICKETS_O15_REPORT_GLOBAL_FILE}")
        else:
            added_o15 = 0
            added_o15_global = 0
            report_o15 = ""

        if _maestro_level() >= 1:
            foot = (
                f"RUN SUMMARY\n"
                f"- system_tickets: {len(tickets_system)} | o15_tickets: {len(tickets_o15)}\n"
                f"{'-'*40}\n\n"
            )
            _write_maestro_log(foot, append=True)

        return TicketBuildOutput(
            tickets_system=tickets_system,
            report_system=report_system,
            tickets_o15=tickets_o15,
            report_o15=report_o15,
            added_sys=added_sys,
            added_o15=added_o15,
            added_sys_global=added_sys_global,
            added_o15_global=added_o15_global,
        )

    finally:
        _clear_active_tuning()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python services/ticket_builder.py <predictions.tsv> [run_date=YYYY-MM-DD]")
        raise SystemExit(1)

    run_date = sys.argv[2] if len(sys.argv) >= 3 else None
    out = generate_tickets_from_tsv(sys.argv[1], run_date=run_date)
    print(out.report_system)
    print("\n" + ("-" * 80) + "\n")
    print(out.report_o15)
