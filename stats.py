from pathlib import Path

from services.stats_core import (
    load_verdicts,
    compute_league_stats,
    compute_team_stats,
    optimize_threshold_over,
    optimize_threshold_btts,
)


def main() -> None:
    print("=== STATISTIQUES Triskèle – lancement ===")

    verdicts = load_verdicts()
    if verdicts.empty:
        print("⚠️ Aucun verdict chargé, lance d'abord main.py puis post_analysis.py.")
        return

    total_matches = len(verdicts)
    total_over_bets = verdicts["over_played"].sum()
    total_over_wins = verdicts["over_win"].sum()
    total_btts_bets = verdicts["btts_played"].sum()
    total_btts_wins = verdicts["btts_win"].sum()

    winrate_over_global = (
        total_over_wins / total_over_bets * 100 if total_over_bets > 0 else 0.0
    )
    winrate_btts_global = (
        total_btts_wins / total_btts_bets * 100 if total_btts_bets > 0 else 0.0
    )

    # ===============================
    # 1) Stats globales
    # ===============================
    print("\n--- Vue globale ---")
    print(f"Nombre total de matchs analysés : {total_matches}")
    print(f"Over 2.5 : {total_over_bets} paris, winrate = {winrate_over_global:.1f} %")
    print(f"BTTS      : {total_btts_bets} paris, winrate = {winrate_btts_global:.1f} %")

    # ===============================
    # 2) Stats par championnat
    # ===============================
    league_stats = compute_league_stats(verdicts)

    if league_stats.empty:
        print("\n⚠️ Impossible de calculer les stats par championnat (données vides).")
    else:
        print("\n--- Statistiques par championnat (Top 10 par nombre de matchs) ---")
        for _, row in league_stats.head(10).iterrows():
            lg = row["league"]
            nb = row["nb_matches"]
            ov_bets = row["nb_over_bets"]
            ov_wr = row["winrate_over"]
            ov_roi = row["roi_over"]
            bt_bets = row["nb_btts_bets"]
            bt_wr = row["winrate_btts"]
            bt_roi = row["roi_btts"]

            print(
                f"[{lg}]  matchs={nb}  "
                f"Over: {ov_bets} bets, WR={ov_wr:.1f}%, ROI={ov_roi:.1f}%  |  "
                f"BTTS: {bt_bets} bets, WR={bt_wr:.1f}%, ROI={bt_roi:.1f}%"
            )

    # ===============================
    # 3) Stats par équipe (aperçu)
    # ===============================
    team_stats = compute_team_stats(verdicts)

    if not team_stats.empty:
        print("\n--- Statistiques par équipe (Top 10 par nombre de matchs, HOME + AWAY) ---")
        for _, row in team_stats.head(10).iterrows():
            team = row["team"]
            side = row["side"]
            nb = row["nb_matches"]
            ov_bets = row["nb_over_bets"]
            ov_wr = row["winrate_over"]
            bt_bets = row["nb_btts_bets"]
            bt_wr = row["winrate_btts"]

            print(
                f"{team} ({side}) : matchs={nb}  "
                f"Over: {ov_bets} bets, WR={ov_wr:.1f}%  |  "
                f"BTTS: {bt_bets} bets, WR={bt_wr:.1f}%"
            )

    # ===============================
    # 4) Optimisation des seuils Over & BTTS
    # ===============================

    print("\n--- Optimisation des seuils ---")

    # Over 2.5
    opt_over = optimize_threshold_over(verdicts)
    best_w_over = opt_over.get("best_winrate")
    best_r_over = opt_over.get("best_roi")

    if best_w_over is not None:
        print(
            f"Over 2.5 – Meilleur WINRATE : seuil={best_w_over['threshold']}, "
            f"bets={best_w_over['bets']}, winrate={best_w_over['winrate']:.1f}%, "
            f"ROI={best_w_over['roi']:.1f}%"
        )
    else:
        print("Over 2.5 – aucun seuil exploitable pour le winrate.")

    if best_r_over is not None:
        print(
            f"Over 2.5 – Meilleur ROI      : seuil={best_r_over['threshold']}, "
            f"bets={best_r_over['bets']}, winrate={best_r_over['winrate']:.1f}%, "
            f"ROI={best_r_over['roi']:.1f}%"
        )
    else:
        print("Over 2.5 – aucun seuil exploitable pour le ROI.")

    # BTTS
    opt_btts = optimize_threshold_btts(verdicts)
    best_w_btts = opt_btts.get("best_winrate")
    best_r_btts = opt_btts.get("best_roi")

    if best_w_btts is not None:
        print(
            f"BTTS – Meilleur WINRATE     : seuil={best_w_btts['threshold']:.2f}, "
            f"bets={best_w_btts['bets']}, winrate={best_w_btts['winrate']:.1f}%, "
            f"ROI={best_w_btts['roi']:.1f}%"
        )
    else:
        print("BTTS – aucun seuil exploitable pour le winrate.")

    if best_r_btts is not None:
        print(
            f"BTTS – Meilleur ROI         : seuil={best_r_btts['threshold']:.2f}, "
            f"bets={best_r_btts['bets']}, winrate={best_r_btts['winrate']:.1f}%, "
            f"ROI={best_r_btts['roi']:.1f}%"
        )
    else:
        print("BTTS – aucun seuil exploitable pour le ROI.")


if __name__ == "__main__":
    main()