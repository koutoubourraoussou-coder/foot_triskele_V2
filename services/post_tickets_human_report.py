# services/post_tickets_human_report.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import date as date_cls, datetime
import re

# ✅ Default : si tu appelles sans out_path, ça écrit ici.
TICKETS_REPORT_FILE = Path("data") / "verdict_post_analyse_tickets_report.txt"

# --- Helpers ---
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


def _is_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (s or "").strip()))


def _as_date(s: str) -> Optional[date_cls]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _time_to_minutes(t: str) -> int:
    try:
        hh, mm = (t or "").split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 10**9


def _weekday_fr(date_str: str) -> str:
    try:
        y, m, d = map(int, (date_str or "").split("-"))
        wd = __import__("datetime").date(y, m, d).weekday()
        return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"][wd]
    except Exception:
        return ""


def _eval_to_emoji(code: str) -> str:
    c = (code or "").strip().upper()
    return {
        "WIN": "✅",
        "LOSS": "❌",
        "PENDING": "⏳",
        "GOOD_NO_BET": "🟢",
        "BAD_NO_BET": "🟡",
    }.get(c, "⏳")


def _parse_ticket_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Format attendu (tickets.tsv):
    TSV: ticket_id  date  start_time  end_time  code  total_odd  match_id  bet_key  time
         league  home  away  metric  label  odd
    """
    raw = (line or "").strip()
    if not raw or not raw.startswith("TSV:"):
        return None

    content = raw[4:].lstrip()
    parts = content.split("\t")
    if len(parts) < 15:
        return None

    ticket_id = parts[0].strip()
    d = parts[1].strip()
    if not _is_date(d):
        return None

    return {
        "ticket_id": ticket_id,
        "date": d,
        "start_time": parts[2].strip(),
        "end_time": parts[3].strip(),
        "code": parts[4].strip(),
        "total_odd": parts[5].strip(),
        "match_id": parts[6].strip(),
        "bet_key": parts[7].strip().upper(),
        "match_time": parts[8].strip(),
        "league": parts[9].strip(),
        "home": parts[10].strip(),
        "away": parts[11].strip(),
        "metric": parts[12].strip(),
        "label": parts[13].strip(),
        "odd": parts[14].strip(),
    }


def _infer_ticket_numbers(headers_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """
    Reconstruit Ticket 1 / Ticket 2 / ... par JOUR, tri :
      start_time, end_time, ticket_id
    """
    by_date: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for tid, h in headers_by_id.items():
        d = str(h.get("date") or "")
        by_date.setdefault(d, []).append((tid, h))

    out: Dict[str, int] = {}
    for d, items in by_date.items():
        items.sort(
            key=lambda it: (
                _time_to_minutes(str(it[1].get("start_time") or "")),
                _time_to_minutes(str(it[1].get("end_time") or "")),
                it[0],
            )
        )
        for i, (tid, _h) in enumerate(items, start=1):
            out[tid] = i
    return out


def write_post_tickets_human_report(
    *,
    tickets_file: Path,
    eval_index: Dict[Tuple[str, str], str],
    today: date_cls,
    out_path: Optional[Path] = None,
    title: Optional[str] = None,
    allowed_ticket_ids: Optional[set[str]] = None,  # ✅ NEW : whitelist report_global
) -> None:
    """
    Écrit un report humain LISIBLE (SNAPSHOT) dans un fichier TXT :
    - PAS d'ANSI
    - Emojis only
    - Tickets groupés, legs listés, bilan en bas

    ✅ allowed_ticket_ids : si fourni, on n'affiche QUE ces tickets (whitelist report_global)
    ✅ SNAPSHOT : le fichier est réécrit à chaque run (plus de doublons visuels)
    """
    if out_path is None:
        out_path = TICKETS_REPORT_FILE

    header_title = title or "VERDICT POST-ANALYSE — REPORT TICKETS (LISIBLE)"

    if not tickets_file.exists() or tickets_file.stat().st_size == 0:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("Aucun fichier tickets détecté.\n", encoding="utf-8")
        return

    with tickets_file.open("r", encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]

    headers: Dict[str, Dict[str, Any]] = {}
    legs_by_tid: Dict[str, List[Dict[str, Any]]] = {}

    ignored_future = 0
    ignored_not_allowed = 0

    for line in lines:
        t = _parse_ticket_line(line)
        if not t:
            continue

        d = _as_date(t.get("date", ""))
        if d is None or d >= today:
            ignored_future += 1
            continue

        tid = t["ticket_id"]

        # ✅ whitelist report_global : sinon le report montre des tickets non traités => PENDING visuels
        if allowed_ticket_ids is not None and tid not in allowed_ticket_ids:
            ignored_not_allowed += 1
            continue

        headers.setdefault(tid, t)
        legs_by_tid.setdefault(tid, []).append(t)

    if not legs_by_tid:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        msg = "Aucun ticket passé à analyser (dates futures / aujourd'hui)."
        if allowed_ticket_ids is not None:
            msg += "\n(Whitelist active : aucun ticket trouvé dans cette whitelist.)"
        out_path.write_text(msg + "\n", encoding="utf-8")
        return

    ticket_no_map = _infer_ticket_numbers(headers)

    def _ticket_sort_key(tid: str) -> Tuple[str, int, int, int, str]:
        h = headers.get(tid, {})
        d = str(h.get("date") or "")
        st = _time_to_minutes(str(h.get("start_time") or ""))
        en = _time_to_minutes(str(h.get("end_time") or ""))
        no = int(ticket_no_map.get(tid, 10**9))
        return (d, st, en, no, tid)

    def _leg_sort_key(leg: Dict[str, Any]) -> Tuple[int, str, str, str, str]:
        t = str(leg.get("match_time") or "")
        return (
            _time_to_minutes(t),
            str(leg.get("league") or ""),
            str(leg.get("home") or ""),
            str(leg.get("away") or ""),
            str(leg.get("match_id") or ""),
        )

    out: List[str] = []
    out.append(header_title)
    out.append("=" * 68)
    out.append("")
    out.append(f"Source tickets : {tickets_file}")
    out.append(f"Date run       : {today.isoformat()}")
    out.append(f"Output         : {out_path}")
    if allowed_ticket_ids is not None:
        out.append(f"Whitelist      : ON ({len(allowed_ticket_ids)} ids)")
        out.append(f"Ignorés (hors whitelist) : {ignored_not_allowed}")
    out.append(f"Ignorés (date>=today)    : {ignored_future}")
    out.append("")

    total_tickets = 0
    win_tickets = 0
    loss_tickets = 0
    pending_tickets = 0

    for tid in sorted(legs_by_tid.keys(), key=_ticket_sort_key):
        h = headers.get(tid, {})
        legs_raw = legs_by_tid.get(tid, [])
        if not legs_raw:
            continue

        # ✅ DEDUP legs : si le TSV contient 2 fois le même (match_id, bet_key), on en affiche 1
        legs_unique: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for leg in legs_raw:
            mid = (leg.get("match_id") or "").strip()
            bk = (leg.get("bet_key") or "").strip().upper()
            key = (mid or "MISSING_MID", bk or "MISSING_BK")
            legs_unique[key] = leg

        legs = list(legs_unique.values())
        legs.sort(key=_leg_sort_key)

        total_tickets += 1

        ticket_no = int(ticket_no_map.get(tid, 0) or 0)
        d = str(h.get("date") or "")
        st = str(h.get("start_time") or "")
        en = str(h.get("end_time") or "")
        code = _strip_ansi(str(h.get("code") or ""))
        total_odd = _strip_ansi(str(h.get("total_odd") or ""))

        wins = 0
        losses = 0
        pendings = 0

        leg_rows: List[str] = []
        for i, leg in enumerate(legs, start=1):
            match_id = (leg.get("match_id") or "").strip()
            bet_key = (leg.get("bet_key") or "").strip().upper()

            ev = (eval_index.get((match_id, bet_key)) or "").strip().upper()

            # ✅ alignement moteur tickets
            if ev == "BAD_NO_BET":
                ev = "WIN"
            elif ev == "GOOD_NO_BET":
                ev = "LOSS"
            elif ev not in ("WIN", "LOSS", "PENDING"):
                ev = "PENDING"

            if ev == "WIN":
                wins += 1
            elif ev == "LOSS":
                losses += 1
            else:
                pendings += 1

            league = _strip_ansi(str(leg.get("league") or ""))
            home = _strip_ansi(str(leg.get("home") or ""))
            away = _strip_ansi(str(leg.get("away") or ""))
            metric = _strip_ansi(str(leg.get("metric") or ""))
            label = _strip_ansi(str(leg.get("label") or ""))
            match_time = _strip_ansi(str(leg.get("match_time") or ""))
            odd = _strip_ansi(str(leg.get("odd") or ""))

            emoji_leg = _eval_to_emoji(ev)
            time_part = f"{match_time} | " if match_time else ""
            metric_part = f" | {metric}" if metric else ""
            label_part = f" | [{label}]" if label else ""
            odd_part = f" | odd={odd}" if odd else ""

            leg_rows.append(
                f"   {emoji_leg} Leg {i}) {time_part}{league} | {home} vs {away}{metric_part}{label_part}{odd_part}"
            )

        # Verdict ticket
        if losses >= 1:
            ev_ticket = "LOSS"
            loss_tickets += 1
        elif pendings >= 1:
            ev_ticket = "PENDING"
            pending_tickets += 1
        else:
            ev_ticket = "WIN"
            win_tickets += 1

        emoji_ticket = _eval_to_emoji(ev_ticket)
        day = _weekday_fr(d)
        day_part = f"{day} " if day else ""

        out.append("─" * 68)
        out.append(f"{emoji_ticket} Ticket {ticket_no} | {day_part}{d} {st}→{en} | code={code} | odd={total_odd}")
        out.append(f"   id={tid}")
        out.append(f"   legs={len(legs)} | WIN={wins} | LOSS={losses} | PENDING={pendings}")
        out.extend(leg_rows)
        out.append("")

    out.append("=" * 68)
    out.append(f"TOTAL tickets : {total_tickets}")
    out.append(f"✅ WIN     : {win_tickets}")
    out.append(f"❌ LOSS    : {loss_tickets}")
    out.append(f"⏳ PENDING : {pending_tickets}")
    out.append("=" * 68)
    out.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ✅ SNAPSHOT : rewrite complet (plus de doublons “visuels”)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(out))
        f.write("\n")
