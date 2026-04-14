from pathlib import Path
from datetime import datetime
import re
import os

from services.post_analysis_core import (
    run_post_analysis,
    POST_TICKETS_VERDICT_FILE,
    POST_TICKETS_FAILED_FILE,
    POST_TICKETS_O15_VERDICT_FILE,
    POST_TICKETS_O15_FAILED_FILE,
    POST_TICKETS_U35_VERDICT_FILE,
    POST_TICKETS_U35_FAILED_FILE,
)

# ------------------------------
# ROOT / DATA (robuste)
# ------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARCHIVE_ROOT = ROOT / "archive"


def _get_run_dir() -> Path | None:
    run_dir = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if not run_dir:
        return None
    p = Path(run_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_scoped_or_data(name: str) -> Path:
    """
    Si TRISKELE_RUN_DIR est défini : le fichier vit dans la "bulle" (RUN_DIR).
    Sinon : fallback historique dans data/.
    """
    rd = _get_run_dir()
    if rd is not None:
        return rd / name
    return DATA_DIR / name


# ✅ Fichiers utilisés : RUN_DIR si présent, sinon data/
PREDICTIONS_FILE = _run_scoped_or_data("predictions.tsv")
RESULTS_FILE = _run_scoped_or_data("results.tsv")
POST_VERDICT_FILE = _run_scoped_or_data("verdict_post_analyse.txt")
MATCHES_INPUT_FILE = _run_scoped_or_data("matches_input.txt")

# ✅ Reports (sélection tickets) — doivent être dans la bulle si RUN_DIR est présent
TICKETS_REPORT_FILE = _run_scoped_or_data("tickets_report.txt")
TICKETS_O15_REPORT_FILE = _run_scoped_or_data("tickets_o15_random_report.txt")
TICKETS_U35_REPORT_FILE = _run_scoped_or_data("tickets_u35_random_report.txt")

# ✅ Reports lisibles (optionnels) — doivent être dans la bulle si RUN_DIR est présent
HUMAN_TICKETS_REPORT_FILE = _run_scoped_or_data("verdict_post_analyse_tickets_report.txt")
HUMAN_TICKETS_O15_REPORT_FILE = _run_scoped_or_data("verdict_post_analyse_tickets_o15_random_report.txt")
HUMAN_TICKETS_U35_REPORT_FILE = _run_scoped_or_data("verdict_post_analyse_tickets_u35_random_report.txt")


def parse_match_line(line: str):
    raw = line.strip()
    if not raw:
        raise ValueError("Ligne vide")

    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        raise ValueError(f"Format invalide (3 blocs attendus) : {raw}")

    date_block, league, teams = parts

    time_str = ""
    date_str = date_block
    if " " in date_block:
        first, rest = date_block.split(" ", 1)
        date_str = first.strip()
        time_str = rest.strip()

    teams_clean = teams.strip()

    m = re.split(r"\s+vs\s+", teams_clean, flags=re.IGNORECASE, maxsplit=1)
    if len(m) == 2:
        home, away = m[0].strip(), m[1].strip()
    elif " - " in teams_clean:
        home, away = [t.strip() for t in teams_clean.split(" - ", 1)]
    elif "-" in teams_clean:
        home, away = [t.strip() for t in teams_clean.split("-", 1)]
    else:
        raise ValueError(f"Impossible d'extraire les équipes : {teams}")

    return date_str, time_str, league, home, away


def get_run_dates_from_input() -> list[str]:
    dates: set[str] = set()

    if not MATCHES_INPUT_FILE.exists():
        print(f"⚠️ matches_input.txt introuvable pour l'archivage : {MATCHES_INPUT_FILE}")
        return []

    with MATCHES_INPUT_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            try:
                date_str, _time_str, _league, _home, _away = parse_match_line(line)
                dates.add(date_str)
            except Exception:
                continue

    return sorted(dates)


def _extract_date_and_time_from_tsv_parts(parts: list[str]) -> tuple[str, str]:
    date_str = ""
    time_str = ""

    if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1].strip()):
        date_str = parts[1].strip()
    elif len(parts) >= 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0].strip()):
        date_str = parts[0].strip()
    else:
        date_str = (parts[0].strip() if parts else "")

    if parts:
        last = parts[-1].strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", last):
            time_str = last

    if not time_str:
        for p in parts:
            p = p.strip()
            if re.fullmatch(r"\d{1,2}:\d{2}", p):
                time_str = p
                break

    return date_str, time_str


def _sort_tsv_by_date_and_time(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    rows: list[tuple[datetime, str]] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw.startswith("TSV:"):
                continue

            content = raw[4:].lstrip()
            parts = content.split("\t")
            if not parts:
                continue

            date_str, time_str = _extract_date_and_time_from_tsv_parts(parts)

            try:
                if time_str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    dt = datetime(1970, 1, 1)
            except ValueError:
                dt = datetime(1970, 1, 1)

            rows.append((dt, raw))

    if not rows:
        return

    rows.sort(key=lambda x: x[0])

    with path.open("w", encoding="utf-8") as f:
        for _, raw in rows:
            f.write(raw + "\n")

    print(f"   🔄 Tri chronologique appliqué : {path}")


def _archive_tsv_for_date(
    src: Path,
    dst: Path,
    target_date: str,
    *,
    date_col_index: int = 0,
) -> None:
    if not src.exists() or src.stat().st_size == 0:
        print(f"   ℹ️ Fichier absent ou vide, non archivé : {src}")
        return

    lines_out: list[str] = []

    with src.open("r", encoding="utf-8") as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            if not raw_line.startswith("TSV:"):
                continue

            content = raw_line[4:].lstrip()
            parts = content.split("\t")
            if not parts:
                continue

            if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1].strip()):
                d = parts[1].strip()
            elif len(parts) >= 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0].strip()):
                d = parts[0].strip()
            elif len(parts) > date_col_index:
                d = parts[date_col_index].strip()
            else:
                continue

            if d == target_date:
                lines_out.append(raw_line)

    if not lines_out:
        print(f"   ℹ️ Aucun enregistrement pour {target_date} dans {src}, rien archivé.")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        for l in lines_out:
            f.write(l + "\n")

    print(f"   ➜ {dst} ({len(lines_out)} lignes pour {target_date})")


def _copy_file_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.stat().st_size > 0:
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"   ➜ {dst} (copie brute)")
        except Exception as e:
            print(f"   ⚠️ Impossible d'archiver {src}: {e}")
    else:
        print(f"   ℹ️ Fichier absent ou vide, non archivé : {src}")


def _get_archive_base_dir(run_dates: list[str]) -> Path:
    """
    ✅ Option A : on archive dans le RUN_DIR si présent.
    Sinon fallback sur l'ancien comportement (archive/analyse_YYYY-MM-DD).
    """
    run_dir = os.environ.get("TRISKELE_RUN_DIR", "").strip()
    if run_dir:
        p = Path(run_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    if len(run_dates) == 1:
        return ARCHIVE_ROOT / f"analyse_{run_dates[0]}"
    return ARCHIVE_ROOT


def archive_post_outputs() -> None:
    run_dates = get_run_dates_from_input()
    if not run_dates:
        print("ℹ️ Aucune date trouvée dans matches_input.txt pour l'archivage post-analyse.")
        return

    base_dir = _get_archive_base_dir(run_dates)

    if len(run_dates) == 1:
        per_date_dirs = {run_dates[0]: base_dir}
    else:
        per_date_dirs = {}
        for d in run_dates:
            dd = base_dir / f"analyse_{d}"
            dd.mkdir(parents=True, exist_ok=True)
            per_date_dirs[d] = dd

    for target_date in run_dates:
        archive_dir = per_date_dirs[target_date]
        archive_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n📦 Archivage post-analyse (vue JOUR {target_date}) dans {archive_dir} ...")

        _archive_tsv_for_date(RESULTS_FILE, archive_dir / "results.tsv", target_date, date_col_index=0)
        _archive_tsv_for_date(POST_VERDICT_FILE, archive_dir / "verdict_post_analyse.txt", target_date, date_col_index=0)

        _archive_tsv_for_date(
            POST_TICKETS_VERDICT_FILE,
            archive_dir / "verdict_post_analyse_tickets.txt",
            target_date,
            date_col_index=2,
        )

        _archive_tsv_for_date(
            POST_TICKETS_O15_VERDICT_FILE,
            archive_dir / "verdict_post_analyse_tickets_o15_random.txt",
            target_date,
            date_col_index=2,
        )

        _archive_tsv_for_date(
            POST_TICKETS_U35_VERDICT_FILE,
            archive_dir / "verdict_post_analyse_tickets_u35_random.txt",
            target_date,
            date_col_index=2,
        )

        _copy_file_if_exists(POST_TICKETS_FAILED_FILE, archive_dir / POST_TICKETS_FAILED_FILE.name)
        _copy_file_if_exists(POST_TICKETS_O15_FAILED_FILE, archive_dir / POST_TICKETS_O15_FAILED_FILE.name)
        _copy_file_if_exists(POST_TICKETS_U35_FAILED_FILE, archive_dir / POST_TICKETS_U35_FAILED_FILE.name)

        _copy_file_if_exists(TICKETS_REPORT_FILE, archive_dir / TICKETS_REPORT_FILE.name)
        _copy_file_if_exists(TICKETS_O15_REPORT_FILE, archive_dir / TICKETS_O15_REPORT_FILE.name)
        _copy_file_if_exists(TICKETS_U35_REPORT_FILE, archive_dir / TICKETS_U35_REPORT_FILE.name)

        _copy_file_if_exists(HUMAN_TICKETS_REPORT_FILE, archive_dir / HUMAN_TICKETS_REPORT_FILE.name)
        _copy_file_if_exists(HUMAN_TICKETS_O15_REPORT_FILE, archive_dir / HUMAN_TICKETS_O15_REPORT_FILE.name)
        _copy_file_if_exists(HUMAN_TICKETS_U35_REPORT_FILE, archive_dir / HUMAN_TICKETS_U35_REPORT_FILE.name)

    print("📁 Archivage post-analyse terminé.\n")


def main() -> None:
    print("=== POST-ANALYSE Triskèle – lancement ===")
    print("🧪 Comparaison des prédictions avec les résultats réels...\n")

    run_post_analysis(
        predictions_path=PREDICTIONS_FILE,
        results_path=RESULTS_FILE,
        post_verdict_path=POST_VERDICT_FILE,
    )

    print("\n🔧 Application du tri chronologique...")
    _sort_tsv_by_date_and_time(RESULTS_FILE)
    _sort_tsv_by_date_and_time(POST_VERDICT_FILE)
    _sort_tsv_by_date_and_time(POST_TICKETS_VERDICT_FILE)
    _sort_tsv_by_date_and_time(POST_TICKETS_O15_VERDICT_FILE)
    _sort_tsv_by_date_and_time(POST_TICKETS_U35_VERDICT_FILE)

    archive_post_outputs()


if __name__ == "__main__":
    main()
