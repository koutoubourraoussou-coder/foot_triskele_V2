import streamlit as st
import pandas as pd
import subprocess
import os
import re
import sys
import inspect
from pathlib import Path
from datetime import date, timedelta, datetime

# Racine du projet: remonte de tools/audit -> projet
ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "archive"
APP_VERSION = "BUILD_2026_02_27_V1"

st.set_page_config(page_title="⚡️🤖 Machine TreeSkale", page_icon="⚡️", layout="wide")

st.title("⚡️ Machine TreeSkale")
st.markdown("Interface pour générer et consulter les tickets (System & Random) avec statut ✅/❌/⏳ quand dispo.")


# -----------------------------
# Helpers: archives / périodes
# -----------------------------
def parse_analyse_dir_date(p: Path) -> date | None:
    m = re.match(r"analyse_(\d{4}-\d{2}-\d{2})$", p.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def list_analyse_dirs() -> list[tuple[date, Path]]:
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
    return out


def latest_analyse_dir() -> Path | None:
    dirs = list_analyse_dirs()
    return dirs[0][1] if dirs else None


def compute_period_range(label: str) -> tuple[date | None, date | None]:
    """Retourne (start, end) inclusifs. None/None => all time."""
    today = date.today()
    if label == "Veille":
        y = today - timedelta(days=1)
        return y, y
    if label == "10 derniers jours":
        return today - timedelta(days=9), today
    if label == "30 derniers jours":
        return today - timedelta(days=29), today
    if label == "All time":
        return None, None


def in_range(d: date, start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return True
    return start <= d <= end


def style_status_cell(val):
    if val == "✅":
        return "background-color: #1f7a1f; color: white; font-weight: 700;"
    if val == "❌":
        return "background-color: #b3261e; color: white; font-weight: 700;"
    if val == "⏳":
        return "background-color: #4b5563; color: white; font-weight: 700;"
    return ""


# -----------------------------
# Parsing tickets (reports)
# -----------------------------
def parse_tickets_to_play(filepath: Path | str, fallback_day: date | None = None):
    """Parse un fichier de tickets générés (tickets_report.txt / tickets_o15_random_report.txt)."""
    filepath = Path(filepath)
    if not filepath.exists():
        return None

    content = filepath.read_text(encoding="utf-8", errors="replace")

    ticket_pattern = re.compile(
        r"🎟️ (TICKET [0-9.]+) \((.*?)\) — id=(.*?) — cote = ([0-9.]+) — fenêtre (.*?)\s*.*?\n(.*?)(?=🎟️|📅|$)",
        re.DOTALL
    )

    data = []
    for match in ticket_pattern.finditer(content):
        ticket_id = match.group(3).strip()
        matches_text = match.group(6).strip()
        nb_matches = len(re.findall(r"^\s*\d+\)", matches_text, re.MULTILINE))

        # Jour: on essaie de le déduire de l'id (ex: 2026-01-28_....)
        day_val = None
        mday = re.match(r"(\d{4}-\d{2}-\d{2})_", ticket_id)
        if mday:
            try:
                day_val = datetime.strptime(mday.group(1), "%Y-%m-%d").date()
            except ValueError:
                day_val = None
        if day_val is None and fallback_day is not None:
            day_val = fallback_day

        data.append({
            "Jour": day_val,
            "Ticket": match.group(1),
            "Type": match.group(2),
            "Id": ticket_id,
            "Cote": float(match.group(4)),
            "Fenêtre de jeu": match.group(5).strip(),
            "Nb Matchs": nb_matches,
            "Détail": matches_text,
            "Source": str(filepath)
        })

    if data :
        return pd.DataFrame(data)

    return None


def load_tickets_dataset(report_filename: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Charge les tickets depuis (dans cet ordre) :
    1) archive/analyse_YYYY-MM-DD/<report_filename>
    2) ROOT/data/<report_filename>                 ✅ Streamlit Cloud (ton cas)
    3) ROOT/<report_filename>

    Filtre ensuite par Jour si possible.
    """
    frames: list[pd.DataFrame] = []

    # 1) Archives (multi-jours)
    for dday, dpath in list_analyse_dirs():
        if not in_range(dday, period_start, period_end):
            continue
        f = dpath / report_filename
        df = parse_tickets_to_play(f, fallback_day=dday)
        if df is not None and not df.empty:
            frames.append(df)

    # 2) data/ (important pour Streamlit Cloud)
    data_file = ROOT / "data" / report_filename
    if data_file.exists():
        df_data = parse_tickets_to_play(data_file, fallback_day=None)
        if df_data is not None and not df_data.empty:
            frames.append(df_data)

    # 3) racine
    root_file = ROOT / report_filename
    if root_file.exists():
        df_root = parse_tickets_to_play(root_file, fallback_day=None)
        if df_root is not None and not df_root.empty:
            frames.append(df_root)

    if not frames:
        return pd.DataFrame(
            columns=["Jour", "Ticket", "Type", "Id", "Cote", "Fenêtre de jeu", "Nb Matchs", "Détail", "Source"]
        )

    df_all = pd.concat(frames, ignore_index=True)

    # Dédup (si un même ticket se retrouve en root + data + archive)
    if "Id" in df_all.columns:
        df_all = df_all.drop_duplicates(subset=["Id"], keep="first")

    # Filtre par date (si Jour est dispo)
    if period_start is not None and period_end is not None:
        df_all = df_all[df_all["Jour"].notna()]
        df_all = df_all[(df_all["Jour"] >= period_start) & (df_all["Jour"] <= period_end)]

    # Tri: jour desc, puis ticket
    if "Jour" in df_all.columns:
        df_all = df_all.sort_values(by=["Jour", "Ticket"], ascending=[False, True])

    return df_all


# -----------------------------
# Parsing verdicts -> mapping id -> statut
# -----------------------------
def parse_verdict_file_to_df(path: Path, source_day: date | None = None) -> pd.DataFrame:
    """
    Parse un fichier verdict_post_analyse_*.txt et retourne un DF:
    Id | Statut | Legs WIN | Legs LOSS | Legs PENDING | VerdictJour | VerdictSource
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    # Chaque bloc ticket commence par: ✅ Ticket 1 | ... puis "id=...." puis "legs=... | WIN=... | LOSS=... | PENDING=..."
    ticket_block = re.compile(
        r"(?P<status>[✅❌⏳])\s*Ticket\s*(?P<num>\d+)\s*\|.*?\n"
        r"\s*id=(?P<id>[^\s]+)\s*\n"
        r"\s*legs=(?P<legs>\d+)\s*\|\s*WIN=(?P<win>\d+)\s*\|\s*LOSS=(?P<loss>\d+)\s*\|\s*PENDING=(?P<pending>\d+)",
        re.DOTALL
    )

    rows = []
    for m in ticket_block.finditer(text):
        rows.append({
            "Id": m.group("id").strip(),
            "Statut": m.group("status"),
            "Legs WIN": int(m.group("win")),
            "Legs LOSS": int(m.group("loss")),
            "Legs PENDING": int(m.group("pending")),
            "VerdictJour": source_day,
            "VerdictSource": str(path),
        })

    return pd.DataFrame(rows)


def collect_verdict_mapping(report_name: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Cherche des verdicts sur la période:
    - archive/analyse_YYYY-MM-DD/report_name (day = date du dossier)
    - + fallback ROOT/data/report_name
    - + fallback ROOT/report_name
    Retourne un DF unique (dédup sur Id).
    """
    frames = []

    # Archives
    for dday, dpath in list_analyse_dirs():
        if not in_range(dday, period_start, period_end):
            continue
        f = dpath / report_name
        if f.exists():
            df = parse_verdict_file_to_df(f, source_day=dday)
            if not df.empty:
                frames.append(df)

    # data/
    f_data = ROOT / "data" / report_name
    if f_data.exists():
        df = parse_verdict_file_to_df(f_data, source_day=None)
        if not df.empty:
            frames.append(df)

    # racine
    f_root = ROOT / report_name
    if f_root.exists():
        df = parse_verdict_file_to_df(f_root, source_day=None)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING", "VerdictJour", "VerdictSource"])

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["Id"], keep="first")
    return out


def attach_verdict(df_tickets: pd.DataFrame, df_verdict: pd.DataFrame) -> pd.DataFrame:
    """Merge tickets + verdict sur Id."""
    if df_tickets.empty:
        return df_tickets
    if df_verdict.empty:
        df = df_tickets.copy()
        df["Statut"] = None
        df["Legs WIN"] = None
        df["Legs LOSS"] = None
        df["Legs PENDING"] = None
        return df

    df = df_tickets.merge(df_verdict[["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING"]],
                          on="Id", how="left")
    return df


# -----------------------------
# Sidebar (contrôles)
# -----------------------------
st.sidebar.header("⚙️ Lancer la Machine")

st.sidebar.markdown("### Période d'affichage")
period_label = st.sidebar.selectbox(
    "Filtrer :",
    ["Veille", "10 derniers jours", "30 derniers jours", "All time"],
    index=1
)
period_start, period_end = compute_period_range(period_label)

st.sidebar.divider()
st.sidebar.markdown("### Génération des Tickets")
st.sidebar.info("Exécute run_machine.py pour récupérer les données API, faire les prédictions et construire les tickets.")

if st.sidebar.button("🚀 Lancer Run Machine", type="primary", width="stretch"):
    with st.spinner("Exécution de run_machine.py en cours (ça peut prendre un moment)..."):
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "run_machine.py")],
                capture_output=True,
                text=True,
                cwd=str(ROOT)
            )
            if result.returncode == 0:
                st.sidebar.success("Tickets générés avec succès ! ✅")
                st.rerun()
            else:
                st.sidebar.error("Erreur lors de l'exécution (stderr) :")
                st.sidebar.code(result.stderr or "(stderr vide)")
                st.sidebar.info("stdout :")
                st.sidebar.code(result.stdout or "(stdout vide)")
        except Exception as e:
            st.sidebar.error(f"Erreur système: {e}")

st.sidebar.divider()
st.sidebar.caption("Dossier actuel (Streamlit) : " + os.getcwd())
st.sidebar.caption(f"ROOT: {ROOT}")
st.sidebar.caption(f"Dernière archive: {latest_analyse_dir() or '—'}")

st.sidebar.caption(f"App file: {__file__}")
st.sidebar.caption(f"Version: {APP_VERSION}")

st.sidebar.caption(f"collect_verdict_mapping signature: {inspect.signature(collect_verdict_mapping)}")


# -----------------------------
# Contenu principal
# -----------------------------
tab1, tab2 = st.tabs(["🎯 Tickets", "📄 Fichiers Bruts"])

with tab1:
    st.header(f"Tickets — {period_label}")

    if st.button("🔄 Rafraîchir l'affichage"):
        st.rerun()

    st.divider()

    # Tickets multi-jours selon la période
    df_sys = load_tickets_dataset("tickets_report.txt", period_start, period_end)
    df_rand = load_tickets_dataset("tickets_o15_random_report.txt", period_start, period_end)

    # Verdicts sur la même période (mapping par Id)
    df_verdict_sys = collect_verdict_mapping("verdict_post_analyse_tickets_report.txt", period_start, period_end)
    df_verdict_rand = collect_verdict_mapping("verdict_post_analyse_tickets_o15_random_report.txt", period_start, period_end)

    df_sys = attach_verdict(df_sys, df_verdict_sys)
    df_rand = attach_verdict(df_rand, df_verdict_rand)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🛡️ Tickets Système (avec statut)")

        if not df_sys.empty:
            show_cols = ["Statut", "Jour", "Ticket", "Cote", "Fenêtre de jeu", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            st.dataframe(df_sys[show_cols], width="stretch", hide_index=True)
            with st.expander("Voir le détail des matchs (Système)"):
                for _, row in df_sys.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    st.code(row["Détail"], language="text")
                    st.divider()
        else:
            st.warning("Aucun ticket système trouvé sur cette période.")

    with col2:
        st.subheader("🎲 Tickets O1.5 Random (avec statut)")

        if not df_rand.empty:
            show_cols = ["Statut", "Jour", "Ticket", "Cote", "Fenêtre de jeu", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            st.dataframe(df_rand[show_cols], width="stretch", hide_index=True)
            with st.expander("Voir le détail des matchs (Random)"):
                for _, row in df_rand.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    st.code(row["Détail"], language="text")
                    st.divider()
        else:
            st.warning("Aucun ticket O1.5 Random trouvé sur cette période.")


with tab2:
    st.header("Visionneuse de fichiers bruts")

    report_type = st.selectbox(
        "Choisir le fichier texte à inspecter :",
        [
            "tickets_report.txt",
            "tickets_o15_random_report.txt",
            "verdict_post_analyse_tickets_report.txt",
            "verdict_post_analyse_tickets_o15_random_report.txt",
        ]
    )

    # Lecture: on essaie (1) dernière archive (2) data/ (3) racine
    analyse = latest_analyse_dir()
    candidates = []
    if analyse is not None:
        candidates.append(analyse / report_type)
    candidates.append(ROOT / "data" / report_type)
    candidates.append(ROOT / report_type)

    file_path = None
    for c in candidates:
        if c.exists():
            file_path = c
            break

    if file_path is None:
        st.error("Fichier introuvable (archive/, data/, racine).")
    else:
        st.caption(f"Lecture de: {file_path}")
        st.text_area(f"Contenu de {report_type}", file_path.read_text(encoding="utf-8", errors="replace"), height=650)

