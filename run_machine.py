# run_machine.py
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import json
import os
import sys
from zoneinfo import ZoneInfo

from services.api_client import _call_api_all_pages  # utilitaires communs


# ----------------------------------------------------
# ROOTS / PATHS (robustes : basés sur le dossier projet)
# ----------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARCHIVE_ROOT = ROOT / "archive"

MATCHES_INPUT_FILE = DATA_DIR / "matches_input.txt"
MATCHES_META_FILE = DATA_DIR / "matches_meta.tsv"
ALIASES_FILE = DATA_DIR / "aliases.json"

# Timezone projet (important pour TODAY + conversions ISO)
TZ = ZoneInfo("Europe/Paris")


def _make_run_dir(target_date: str) -> Path:
    """
    Crée un dossier unique de run : archive/analyse_YYYY-MM-DD/<run_stamp>/
    et retourne ce chemin.
    """
    run_stamp = datetime.now(TZ).strftime("%Y-%m-%d__%Hh%Mm%Ss")
    run_dir = ARCHIVE_ROOT / f"analyse_{target_date}" / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run(cmd: list[str], title: str, *, env: dict | None = None) -> None:
    print("\n==============================")
    print(f"  {title}")
    print("==============================\n")
    # ✅ Robustesse long-terme : on force le cwd projet
    subprocess.run(cmd, check=True, env=env, cwd=str(ROOT))


# ----------------------------------------------------
# CONFIG DATE
# ----------------------------------------------------
# "TODAY"  -> utilise la date du jour (Europe/Paris)
# "MANUAL" -> utilise DATE_MANUAL
# "RANGE"  -> utilise une plage DATE_RANGE_START → DATE_RANGE_END (inclus)

DATE_MODE = "TODAY"          # "TODAY", "MANUAL" ou "RANGE"

# Utilisé si DATE_MODE == "MANUAL"
DATE_MANUAL = "2026-04-14"    # YYYY-MM-DD

# Utilisé si DATE_MODE == "RANGE"
DATE_RANGE_START = "2025-10-27"
DATE_RANGE_END   = "2025-10-27"


# ----------------------------------------------------
# Robustesse date / season
# ----------------------------------------------------
# On interroge l'API sur une petite fenêtre (J-1, J, J+1),
# puis on garde UNIQUEMENT les matchs dont la date locale Paris == date cible.
FETCH_DATE_WINDOW_DAYS = 1  # 0 = strict, 1 = (J-1..J+1)

# Ligues "année civile" (season = année de la date)
CIVIL_YEAR_LEAGUE_IDS: set[int] = {
    71,   # Brazil Serie A
    239,  # Colombia Primera A
    128,  # Liga Profesional Argentina
    242,  # Liga Pro Ecuador
    253,  # MLS

    # Paraguay
    250,  # Division Profesional - Apertura
    252,  # Division Profesional - Clausura
    251,  # Division Intermedia (optionnel)
    501,  # Copa Paraguay (optionnel)
    961,  # Supercopa (optionnel)

    # Compétitions internationales (saison = année civile du tournoi)
    1,    # FIFA World Cup
    5,    # UEFA Nations League
    6,    # Africa Cup of Nations
    10,   # International Friendlies
}

# Saisons FORCÉES : certaines compétitions ont une saison fixe indépendante de la date
# (ex: qualifs WC 2026 lancées en 2024 → season=2024 même en 2026)
FORCED_SEASON_LEAGUE_IDS: dict[int, int] = {
    32:  2024,  # UEFA WC Qualifiers 2026 (lancés sept. 2024)
    29:  2023,  # CONMEBOL WC Qualifiers 2026 (lancés sept. 2023)
    31:  2024,  # CONCACAF WC Qualifiers 2026
    34:  2025,  # AFC WC Qualifiers 2026
    36:  2023,  # CAF WC Qualifiers 2026
    152: 2024,  # OFC WC Qualifiers 2026
}


def get_target_dates() -> list[str]:
    """
    Retourne une LISTE de dates cibles au format YYYY-MM-DD selon DATE_MODE.
    """
    mode = DATE_MODE.upper().strip()

    if mode == "TODAY":
        return [datetime.now(TZ).strftime("%Y-%m-%d")]

    if mode == "MANUAL":
        return [DATE_MANUAL]

    if mode == "RANGE":
        start = datetime.strptime(DATE_RANGE_START, "%Y-%m-%d").date()
        end = datetime.strptime(DATE_RANGE_END, "%Y-%m-%d").date()
        if end < start:
            raise ValueError(
                f"DATE_RANGE_END ({DATE_RANGE_END}) est avant DATE_RANGE_START ({DATE_RANGE_START})."
            )

        dates: list[str] = []
        cur = start
        while cur <= end:
            dates.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return dates

    raise ValueError(f"DATE_MODE inconnu : {DATE_MODE} (attendu: TODAY, MANUAL ou RANGE)")


def load_league_ids_from_aliases() -> dict[int, str]:
    """
    Charge data/aliases.json et retourne un dict :
        { league_id: league_name_canonique }
    """
    if not ALIASES_FILE.exists():
        raise FileNotFoundError(f"Fichier d'alias introuvable : {ALIASES_FILE}")

    with ALIASES_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    leagues = data.get("leagues", {})
    league_id_to_name: dict[int, str] = {}

    # aliases.json peut contenir plusieurs noms -> même ID : on garde le 1er rencontré
    for name, lid in leagues.items():
        if isinstance(lid, int) and lid not in league_id_to_name:
            league_id_to_name[lid] = str(name)

    return league_id_to_name


def _infer_season_for_league(league_id: int, date_str: str) -> int:
    """
    Détermine la season API-FOOTBALL.
    - saison forcée (FORCED_SEASON_LEAGUE_IDS) -> valeur fixe
    - ligues CIVIL YEAR -> season = année (ex: 2026)
    - ligues EURO-like  -> season = année-1 si Jan→Jun, sinon année
    """
    if league_id in FORCED_SEASON_LEAGUE_IDS:
        return FORCED_SEASON_LEAGUE_IDS[league_id]

    y = int(date_str[:4])
    m = int(date_str[5:7])

    if league_id in CIVIL_YEAR_LEAGUE_IDS:
        return y

    return y - 1 if 1 <= m <= 6 else y


def _iso_to_local_dt(d_iso: str):
    """
    Convertit une date ISO (souvent UTC ...Z) en datetime TZ Europe/Paris.
    """
    if not isinstance(d_iso, str) or not d_iso:
        return None
    try:
        dt_utc = datetime.fromisoformat(d_iso.replace("Z", "+00:00"))
        return dt_utc.astimezone(TZ)
    except Exception:
        return None


def _date_window(target_date_str: str, window_days: int) -> list[str]:
    """
    Retourne [target - window_days, ..., target + window_days] en YYYY-MM-DD.
    """
    base = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    return [
        (base + timedelta(days=delta)).strftime("%Y-%m-%d")
        for delta in range(-window_days, window_days + 1)
    ]


def collect_fixtures_for_date(
    date_str: str,
) -> list[tuple[str, str, str, str, str, int | None, int | None, int | None, int | None]]:
    """
    Récupère tous les matchs pour date_str (Paris) pour toutes les ligues du aliases.json.

    Robustesse:
      - Requête API sur (J-1..J+1)
      - Filtre STRICT par date locale Paris == date_str
      - Saison déterminée par ligue (année civile vs saison chevauchante)

    Sortie:
      (date_str, time_str, league_name, home, away, league_id, home_id, away_id, fixture_id)
    """
    league_id_to_name = load_league_ids_from_aliases()
    league_ids_set = set(league_id_to_name.keys())

    print(f"\n📅 Date ciblée (Paris) : {date_str}")
    print(f"🎯 Ligues dans aliases.json : {len(league_id_to_name)}")
    print(f"🪟 Fenêtre API : J-{FETCH_DATE_WINDOW_DAYS} .. J+{FETCH_DATE_WINDOW_DAYS} — 3 calls globaux (vs {len(league_id_to_name)*3} avant)")

    query_dates = _date_window(date_str, FETCH_DATE_WINDOW_DAYS)

    all_matches: list[
        tuple[str, str, str, str, str, int | None, int | None, int | None, int | None]
    ] = []

    fetched_total_fixtures = 0
    skipped_wrong_league = 0
    skipped_wrong_local_date = 0

    # OPTIMISÉ : 3 appels globaux par date au lieu de 73×3 = 219 appels
    for qd in query_dates:
        fixtures = _call_api_all_pages("/fixtures", {"date": qd, "timezone": "Europe/Paris"})
        fetched_total_fixtures += len(fixtures)

        for fx in fixtures:
            league_info = fx.get("league", {}) or {}
            league_api_id = league_info.get("id")

            # Filtre local : garder seulement les ligues suivies
            if league_api_id not in league_ids_set:
                skipped_wrong_league += 1
                continue

            league_name = league_id_to_name[league_api_id]

            fixture_info = fx.get("fixture", {}) or {}
            d_iso = fixture_info.get("date") or ""
            dt_local = _iso_to_local_dt(d_iso)

            if not dt_local or dt_local.strftime("%Y-%m-%d") != date_str:
                skipped_wrong_local_date += 1
                continue

            teams = fx.get("teams", {}) or {}
            home_info = (teams.get("home", {}) or {})
            away_info = (teams.get("away", {}) or {})

            home = (home_info.get("name") or "").strip()
            away = (away_info.get("name") or "").strip()
            if not home or not away:
                continue

            home_id = home_info.get("id")
            away_id = away_info.get("id")
            fixture_id = fixture_info.get("id")
            time_str = dt_local.strftime("%H:%M")

            all_matches.append(
                (
                    date_str,
                    time_str,
                    league_name,
                    home,
                    away,
                    league_api_id if isinstance(league_api_id, int) else None,
                    home_id if isinstance(home_id, int) else None,
                    away_id if isinstance(away_id, int) else None,
                    fixture_id if isinstance(fixture_id, int) else None,
                )
            )

    # ------------------------------------------------
    # Dédup robuste (fenêtre multi-jours)
    # ------------------------------------------------
    dedup: dict[tuple, tuple] = {}
    for m in all_matches:
        _d, t, _lg, h, a, lid, _hid, _aid, fid = m
        if fid is not None:
            key = ("FID", int(fid))
        else:
            key = ("NOFID", lid, t or "", h, a)
        if key not in dedup:
            dedup[key] = m

    all_matches = list(dedup.values())

    def _sort_key(x):
        _date, t, lg, h, a, *_ = x
        tt = t if t else "99:99"
        return (lg.lower(), tt, h.lower(), a.lower())

    all_matches.sort(key=_sort_key)

    print(f"📦 Fixtures API bruts (toutes ligues)     : {fetched_total_fixtures}")
    print(f"🧹 Hors suivi (ligues non suivies)        : {skipped_wrong_league}")
    print(f"🧹 Skipped (date Paris != {date_str})     : {skipped_wrong_local_date}")
    print(f"✅ Matchs retenus (final)                 : {len(all_matches)}")

    return all_matches


def write_matches_input(matches, path: Path) -> None:
    """
    Écrit data/matches_input.txt au format attendu par main.py.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        if not matches:
            f.write("# Aucun match trouvé pour cette date.\n")
            return

        for (date_str, time_str, league_name, home, away, *_rest) in matches:
            date_part = f"{date_str} {time_str}" if time_str else date_str
            f.write(f"{date_part} | {league_name} | {home} vs {away}\n")

    print(f"📂 Input mis à jour : {path}  ({len(matches)} lignes)")


def write_matches_meta(matches, path: Path) -> None:
    """
    Écrit matches_meta.tsv + fichiers dérivés (par jour + cumulatif).

    ✅ Robustesse long terme :
    - Le cumulatif déduplique en priorité par fixture_id quand présent
      (évite les doublons dus à variations de noms/accents)
    - Sinon fallback par (date, league, home, away)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# date\tleague\thome\taway\tleague_id\thome_id\taway_id\tfixture_id\n"

    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        for (date_str, _time_str, league_name, home, away, league_id, home_id, away_id, fixture_id) in matches:
            f.write(
                f"{date_str}\t{league_name}\t{home}\t{away}\t"
                f"{'' if league_id is None else league_id}\t"
                f"{'' if home_id is None else home_id}\t"
                f"{'' if away_id is None else away_id}\t"
                f"{'' if fixture_id is None else fixture_id}\n"
            )

    print(f"📂 Meta mis à jour : {path}")

    if not matches:
        return

    day_str = matches[0][0]

    # --- par jour
    by_day_dir = DATA_DIR / "matches_meta_by_day"
    by_day_dir.mkdir(parents=True, exist_ok=True)
    day_file = by_day_dir / f"matches_meta_{day_str}.tsv"

    with day_file.open("w", encoding="utf-8") as f:
        f.write(header)
        for (date_str, _time_str, league_name, home, away, league_id, home_id, away_id, fixture_id) in matches:
            f.write(
                f"{date_str}\t{league_name}\t{home}\t{away}\t"
                f"{'' if league_id is None else league_id}\t"
                f"{'' if home_id is None else home_id}\t"
                f"{'' if away_id is None else away_id}\t"
                f"{'' if fixture_id is None else fixture_id}\n"
            )
    print(f"📂 Meta JOUR créé : {day_file}")

    # --- cumulatif (dédup fixture_id-first)
    cumul_file = DATA_DIR / "matches_meta_all.tsv"
    cumul_file.parent.mkdir(parents=True, exist_ok=True)

    existing_rows: list[str] = []
    existing_keys: set[tuple] = set()

    def _parse_existing_key(parts: list[str]) -> tuple | None:
        # attend au moins 8 colonnes (ou moins si ancien) : on gère les deux
        if len(parts) < 4:
            return None
        fixture_id = None
        if len(parts) >= 8:
            fx = (parts[7] or "").strip()
            if fx.isdigit():
                fixture_id = int(fx)

        if fixture_id is not None:
            return ("FID", fixture_id)

        # fallback legacy
        return ("KEY", parts[0], parts[1], parts[2], parts[3])

    if cumul_file.exists():
        with cumul_file.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                existing_rows.append(line)
                parts = line.split("\t")
                k = _parse_existing_key(parts)
                if k is not None:
                    existing_keys.add(k)

    new_rows: list[str] = []
    for (date_str, _time_str, league_name, home, away, league_id, home_id, away_id, fixture_id) in matches:
        row = (
            f"{date_str}\t{league_name}\t{home}\t{away}\t"
            f"{'' if league_id is None else league_id}\t"
            f"{'' if home_id is None else home_id}\t"
            f"{'' if away_id is None else away_id}\t"
            f"{'' if fixture_id is None else fixture_id}"
        )

        k = ("FID", int(fixture_id)) if isinstance(fixture_id, int) else ("KEY", date_str, league_name, home, away)
        if k in existing_keys:
            continue
        existing_keys.add(k)
        new_rows.append(row)

    all_rows = existing_rows + new_rows

    # tri lisible (date, league, home, away) — fixture_id n'est pas la clé de tri
    all_rows.sort(key=lambda l: tuple((l.split("\t") + ["", "", "", ""])[:4]))

    with cumul_file.open("w", encoding="utf-8") as f:
        f.write(header)
        for line in all_rows:
            f.write(line + "\n")

    print(f"📚 Meta CUMULATIF : {cumul_file}  (+{len(new_rows)} lignes)")


def main():
    print("=== Triskèle – RUN MACHINE (récolte des matchs) ===")
    print(f"MODE DATE : {DATE_MODE}")

    target_dates = get_target_dates()
    print(f"🗓️ Dates à traiter : {', '.join(target_dates)}")

    for idx, target_date in enumerate(target_dates, start=1):
        print("\n------------------------------")
        print(f"  JOUR {idx}/{len(target_dates)} : {target_date}")
        print("------------------------------")

        matches = collect_fixtures_for_date(target_date)
        write_matches_input(matches, MATCHES_INPUT_FILE)
        write_matches_meta(matches, MATCHES_META_FILE)

        print("\n=== RÉCAP MATCHS RÉCOLTÉS ===")
        if not matches:
            print("Aucun match à cette date pour les ligues de aliases.json.")
        else:
            for (d, t, lg, h, a, league_id, home_id, away_id, fixture_id) in matches:
                fx = f" fixture={fixture_id}" if fixture_id else ""
                print(f"{d} {t} | {lg} | {h} vs {a}{fx}")

        # ✅ Run dir unique par jour traité
        run_dir = _make_run_dir(target_date)

        env = os.environ.copy()
        env["TRISKELE_RUN_DIR"] = str(run_dir)

        # snapshot run (input + meta) dans la bulle
        try:
            (run_dir / "matches_input.txt").write_text(
                MATCHES_INPUT_FILE.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"⚠️ [WARN] Snapshot matches_input.txt échoué : {e}")

        try:
            (run_dir / "matches_meta.tsv").write_text(
                MATCHES_META_FILE.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"⚠️ [WARN] Snapshot matches_meta.tsv échoué : {e}")

        run(
            [sys.executable, str(ROOT / "main.py")],
            "Analyse principale (main.py)",
            env=env,
        )


        # ------------------------------------------------------------
        # ✅ FIX IMPORTANT :
        # On NE PASSE PAS TRISKELE_RUN_DIR à post_analysis.py
        # sinon post_analysis peut basculer ses I/O vers la bulle de run
        # au lieu de data/ (global), ce qui donne des tickets "PENDING"
        # ou "rien ajouté", alors qu'en manuel ça marche.
        # ------------------------------------------------------------
        env_post = env.copy()
        env_post.pop("TRISKELE_RUN_DIR", None)

        run(
            [sys.executable, str(ROOT / "post_analysis.py")],
            "Post-analyse (post_analysis.py)",
            env=env_post,
        )

        run(
            [sys.executable, str(ROOT / "update_martingale_state.py")],
            "Mise à jour état Martingale (update_martingale_state.py)",
            env=env_post,
        )

    print("Mission effectuée.")


if __name__ == "__main__":
    main()
