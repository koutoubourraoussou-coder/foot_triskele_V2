import streamlit as st
import pandas as pd
import subprocess
import os
import re

st.set_page_config(page_title="Machine à Tickets", page_icon="🎰", layout="wide")

st.title("🎰 Machine à Tickets - Football API")
st.markdown("Interface pour générer et consulter tes tickets (System & Random).")

# --- FONCTION DE PARSING ---
def parse_tickets_to_play(filepath):
    """Parse les fichiers de tickets générés (tickets_report.txt et tickets_o15_random_report.txt)"""
    if not os.path.exists(filepath):
        return None
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Regex pour capter les blocs "🎟️ TICKET X.X ..." jusqu'à la fin du bloc
    ticket_pattern = re.compile(r"🎟️ (TICKET [0-9.]+) \((.*?)\) — id=(.*?) — cote = ([0-9.]+) — fenêtre (.*?) \s*.*?\n(.*?)(?=🎟️|📅|$)", re.DOTALL)
    
    data = []
    for match in ticket_pattern.finditer(content):
        matches_text = match.group(6).strip()
        # Compter le nombre de matchs dans le ticket (lignes commençant par un chiffre et une parenthèse ex: "1)")
        nb_matches = len(re.findall(r"^\s*\d+\)", matches_text, re.MULTILINE))
        
        data.append({
            "Ticket": match.group(1),
            "Type": match.group(2),
            "Cote": float(match.group(4)),
            "Fenêtre de jeu": match.group(5).strip(),
            "Nb Matchs": nb_matches,
            "Détail": matches_text
        })
        
    if data :
        return pd.DataFrame(data)
    return None

# --- SIDEBAR (CONTRÔLES) ---
st.sidebar.header("⚙️ Lancer la Machine")

st.sidebar.markdown("### Génération des Tickets")
st.sidebar.info("Exécute run_machine.py pour récupérer les données API, faire les prédictions et construire les tickets.")

if st.sidebar.button("🚀 Lancer Run Machine", type="primary", use_container_width=True):
    with st.spinner("Exécution de run_machine.py en cours (ça peut prendre un moment)..."):
        try:
            # On remonte d'un dossier (..) car app.py est dans tools/audit/ et run_machine.py à la racine
            result = subprocess.run(["python", "../../run_machine.py"], capture_output=True, text=True)
            if result.returncode == 0:
                st.sidebar.success("Tickets générés avec succès ! ✅")
                # On force le rafraîchissement de la page pour afficher les nouveaux tickets
                st.rerun()
            else:
                st.sidebar.error(f"Erreur lors de l'exécution:\n{result.stderr}")
        except Exception as e:
            st.sidebar.error(f"Erreur système: {e}")

st.sidebar.divider()
st.sidebar.caption("Dossier actuel : " + os.getcwd())

# --- CONTENU PRINCIPAL ---
tab1, tab2 = st.tabs(["🎯 Tickets à Jouer", "📄 Fichiers Bruts"])

with tab1:
    st.header("Tes Tickets du Jour")
    
    # Bouton manuel pour rafraîchir l'affichage sans relancer la machine
    if st.button("🔄 Rafraîchir l'affichage"):
        st.rerun()
        
    st.divider()
    
    col1, col2 = st.columns(2)
    
    # Colonne 1 : Tickets Système
    with col1:
        st.subheader("🛡️ Tickets Système")
        # Le chemin remonte de deux dossiers car les rapports sont à la racine
        path_sys = "../../tickets_report.txt"
        df_sys = parse_tickets_to_play(path_sys)
        
        if df_sys is not None:
            st.dataframe(df_sys.drop(columns=["Détail"]), use_container_width=True, hide_index=True)
            with st.expander("Voir le détail des matchs (Système)"):
                for idx, row in df_sys.iterrows():
                    st.markdown(f"**{row['Ticket']} (Cote totale: {row['Cote']})**")
                    st.code(row["Détail"], language="text")
                    st.divider()
        else:
            st.warning(f"Aucun ticket système trouvé. Vérifie si le fichier existe ou lance la machine.")
            
    # Colonne 2 : Tickets Random O1.5
    with col2:
        st.subheader("🎲 Tickets O1.5 Random")
        path_rand = "../../tickets_o15_random_report.txt"
        df_rand = parse_tickets_to_play(path_rand)
        
        if df_rand is not None:
            st.dataframe(df_rand.drop(columns=["Détail"]), use_container_width=True, hide_index=True)
            with st.expander("Voir le détail des matchs (Random)"):
                for idx, row in df_rand.iterrows():
                    st.markdown(f"**{row['Ticket']} (Cote totale: {row['Cote']})**")
                    st.code(row["Détail"], language="text")
                    st.divider()
        else:
            st.warning("Aucun ticket O1.5 Random trouvé.")

with tab2:
    st.header("Visionneuse de fichiers bruts")
    report_type = st.selectbox(
        "Choisir le fichier texte à inspecter :", 
        ["tickets_report.txt", "tickets_o15_random_report.txt"]
    )
    
    file_path = f"../../{report_type}"
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            st.text_area(f"Contenu de {report_type}", f.read(), height=600)
    except FileNotFoundError:
        st.error(f"Le fichier {report_type} n'existe pas encore à la racine du projet.")
