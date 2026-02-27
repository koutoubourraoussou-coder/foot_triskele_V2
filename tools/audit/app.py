import streamlit as st
import pandas as pd
import subprocess
import os
import re
import sys
from pathlib import Path
from datetime import date, timedelta, datetime

# Racine du projet: remonte de tools/audit -> projet
ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "archive"

st.set_page_config(page_title="⚡️🤖 Machine TreeSkale", page_icon="⚡️", layout="wide")

st.title("⚡️ Machine TreeSkale — Audit")


# -----------------------------
# Helpers: archives / fichiers
# -----------------------------
def list_analyse_dirs():
    if not ARCHIVE_DIR.exists():
        return []
    dirs = [d for d in ARCHIVE_DIR.iterdir() if d.is_dir() and d.name.startswith("analyse_")]
    # tri par date dans le nom si possible (sinon tri alpha)
    def sort_key(p: Path):
        m = re.search(r"analyse_(\d{4}-\d{2}-\d{2})", p.name)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d")
            except Exception:
                return p.name
        return p.name

    return sorted(dirs, key=sort_key)


def latest_analyse_dir():
    dirs = list_analyse_dirs()
    return dirs[-1] if dirs else None


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Erreur lecture fichier {path}]\n{e}"


# -----------------------------
# Parsing: tickets_report
# -----------------------------
def parse_tickets_report(txt: str) -> pd.DataFrame:
    """
    Format attendu (exemple):
    Day: 2026-01-25
    Ticket 1 | Odds: 2.34 | Window: 13:30-16:00 | Matches: 3 | id=ABC123
    - League | Home vs Away | Market | Odds | fixture_id=...
    ...
    """
    lines = txt.splitlines()
    rows = []
    current_day = None
    current_ticket = None
    current_odds = None
    current_window = None
    current_matches = None
    current_id = None
    detail_lines = []

    ticket_header_re = re.compile(
        r"^Ticket\s+(?P<num>\d+)\s+\|\s+Odds:\s+(?P<odds>[\d\.]+)\s+\|\s+Window:\s+(?P<window>[^|]+)\|\s+Matches:\s+(?P<matches>\d+)\s+\|\s+id=(?P<id>.+)$"
    )

    for line in lines + ["__END__"]:
        if line.startswith("Day:"):
            # flush éventuel ticket en cours
            if current_ticket is not None:
                rows.append(
                    {
                        "Jour": current_day,
                        "Ticket": current_ticket,
                        "Cote": current_odds,
                        "Fenêtre de jeu": current_window,
                        "Nb Matchs": current_matches,
                        "Id": current_id,
                        "Détail": "\n".join(detail_lines).strip(),
                    }
                )
                current_ticket = None
                detail_lines = []

            day_str = line.replace("Day:", "").strip()
            try:
                current_day = datetime.strptime(day_str, "%Y-%m-%d").date()
            except Exception:
                current_day = None

        m = ticket_header_re.match(line.strip())
        if m:
            # flush précédent ticket
            if current_ticket is not None:
                rows.append(
                    {
                        "Jour": current_day,
                        "Ticket": current_ticket,
                        "Cote": float(current_odds) if current_odds is not None else None,
                        "Fenêtre de jeu": current_window,
                        "Nb Matchs": int(current_matches) if current_matches is not None else None,
                        "Id": current_id,
                        "Détail": "\n".join(detail_lines).strip(),
                    }
                )
                detail_lines = []

            current_ticket = f"Ticket {m.group('num')}"
            current_odds = m.group("odds")
            current_window = m.group("window").strip()
            current_matches = m.group("matches")
            current_id = m.group("id").strip()
            continue

        # fin
        if line == "__END__":
            if current_ticket is not None:
                rows.append(
                    {
                        "Jour": current_day,
                        "Ticket": current_ticket,
                        "Cote": float(current_odds) if current_odds is not None else None,
                        "Fenêtre de jeu": current_window,
                        "Nb Matchs": int(current_matches) if current_matches is not None else None,
                        "Id": current_id,
                        "Détail": "\n".join(detail_lines).strip(),
                    }
                )
            break

        # détail ticket
        if current_ticket is not None and line.strip():
            detail_lines.append(line)

    df = pd.DataFrame(rows)
    return df


def load_tickets_dataset(report_name: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    ad = latest_analyse_dir()
    if ad is None:
        return pd.DataFrame()

    path = ad / report_name
    if not path.exists():
        return pd.DataFrame()

    txt = read_text_file(path)
    df = parse_tickets_report(txt)

    # filtre période
    if period_start is not None:
        df = df[df["Jour"] >= period_start]
    if period_end is not None:
        df = df[df["Jour"] <= period_end]

    return df.reset_index(drop=True)


# -----------------------------
# Parsing: verdict_post_analyse
# -----------------------------
def collect_verdict_mapping(report_name: str, period_start: date | None, period_end: date | None) -> pd.DataFrame:
    """
    Construit un mapping Id -> Statut à partir d'un fichier verdict_post_analyse_*.txt
    Le fichier contient généralement des lignes du type:
    id=XYZ | status=WIN | legs: W=.. L=.. P=..
    On garde aussi W/L/P si présent.
    """
    ad = latest_analyse_dir()
    if ad is None:
        return pd.DataFrame(columns=["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING", "Jour"])

    path = ad / report_name
    if not path.exists():
        return pd.DataFrame(columns=["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING", "Jour"])

    txt = read_text_file(path)
    lines = txt.splitlines()

    rows = []
    current_day = None
    day_re = re.compile(r"^Day:\s*(\d{4}-\d{2}-\d{2})\s*$", re.IGNORECASE)

    # Exemples possibles (on reste tolérant)
    # id=ABC | status=WIN | legs: W=2 L=0 P=0
    verdict_re = re.compile(
        r"id=(?P<id>[^|]+)\s*\|\s*status=(?P<status>[^|]+)(?:\s*\|\s*legs:\s*W=(?P<w>\d+)\s*L=(?P<l>\d+)\s*P=(?P<p>\d+))?",
        re.IGNORECASE,
    )

    for line in lines:
        line = line.strip()
        if not line:
            continue

        mday = day_re.match(line)
        if mday:
            try:
                current_day = datetime.strptime(mday.group(1), "%Y-%m-%d").date()
            except Exception:
                current_day = None
            continue

        mv = verdict_re.search(line)
        if mv:
            rid = mv.group("id").strip()
            status = mv.group("status").strip().upper()
            w = mv.group("w")
            l = mv.group("l")
            p = mv.group("p")
            rows.append(
                {
                    "Jour": current_day,
                    "Id": rid,
                    "Statut": status,
                    "Legs WIN": int(w) if w is not None else None,
                    "Legs LOSS": int(l) if l is not None else None,
                    "Legs PENDING": int(p) if p is not None else None,
                }
            )

    df = pd.DataFrame(rows)

    # filtre période
    if not df.empty:
        if period_start is not None:
            df = df[df["Jour"] >= period_start]
        if period_end is not None:
            df = df[df["Jour"] <= period_end]

    # Unicité par Id (si doublons, on prend la dernière occurrence)
    if not df.empty:
        df = df.sort_values(["Jour"]).drop_duplicates(subset=["Id"], keep="last")

    return df.reset_index(drop=True)


def attach_verdict(df_tickets: pd.DataFrame, df_verdict: pd.DataFrame) -> pd.DataFrame:
    if df_tickets.empty:
        return df_tickets

    if df_verdict is None or df_verdict.empty:
        df_tickets["Statut"] = "PENDING"
        df_tickets["Legs WIN"] = None
        df_tickets["Legs LOSS"] = None
        df_tickets["Legs PENDING"] = None
        return df_tickets

    merged = df_tickets.merge(
        df_verdict[["Id", "Statut", "Legs WIN", "Legs LOSS", "Legs PENDING"]],
        on="Id",
        how="left",
    )

    merged["Statut"] = merged["Statut"].fillna("PENDING")
    return merged


# -----------------------------
# Sidebar: période + actions
# -----------------------------
st.sidebar.header("⚙️ Paramètres")

default_end = date.today()
default_start = default_end - timedelta(days=7)

period_start = st.sidebar.date_input("Début période", value=default_start)
period_end = st.sidebar.date_input("Fin période", value=default_end)

if period_start and period_end and period_start > period_end:
    st.sidebar.error("La date de début doit être <= date de fin.")

period_label = f"{period_start.isoformat()} → {period_end.isoformat()}"

st.sidebar.divider()

if st.sidebar.button("🧠 Lancer RunMachine (générer tickets)"):
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
            st.dataframe(df_sys[show_cols], use_container_width=True, hide_index=True)

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
        st.subheader("🎲 Tickets Random (avec statut)")

        if not df_rand.empty:
            show_cols = ["Statut", "Jour", "Ticket", "Cote", "Fenêtre de jeu", "Nb Matchs", "Legs WIN", "Legs LOSS", "Legs PENDING", "Id"]
            st.dataframe(df_rand[show_cols], use_container_width=True, hide_index=True)

            with st.expander("Voir le détail des matchs (Random)"):
                for _, row in df_rand.iterrows():
                    jour_str = row["Jour"].isoformat() if pd.notna(row["Jour"]) else "—"
                    status = row["Statut"] if pd.notna(row["Statut"]) else "—"
                    st.markdown(f"**{status} {row['Ticket']} — {jour_str} (Cote: {row['Cote']})**")
                    st.caption(f"id={row['Id']} | fenêtre={row['Fenêtre de jeu']} | legs: W={row.get('Legs WIN')} L={row.get('Legs LOSS')} P={row.get('Legs PENDING')}")
                    st.code(row["Détail"], language="text")
                    st.divider()
        else:
            st.warning("Aucun ticket random trouvé sur cette période.")

with tab2:
    st.header("📄 Fichiers bruts (dernier dossier analyse_)")

    ad = latest_analyse_dir()
    if ad is None:
        st.info("Aucun dossier analyse_ trouvé dans /archive.")
    else:
        st.caption(str(ad))

        files = sorted([p for p in ad.iterdir() if p.is_file()])
        if not files:
            st.info("Aucun fichier dans ce dossier.")
        else:
            file_names = [p.name for p in files]
            selected = st.selectbox("Choisir un fichier", file_names)

            sel_path = ad / selected
            st.code(read_text_file(sel_path), language="text")