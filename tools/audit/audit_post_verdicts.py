from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


# -----------------------------
# Config
# -----------------------------

DEFAULT_POST_VERDICTS = Path("data") / "verdict_post_analyse.txt"
DEFAULT_ARCHIVES_DIR = Path("archives") / "audit"

MIN_SAMPLE_DEFAULT = 30  # évite les faux patterns (trop peu de matchs)
TOP_N_EXAMPLES_DEFAULT = 120  # nb d'exemples exportés par catégorie


# -----------------------------
# Parsing
# -----------------------------

def _read_tsv_lines(path: Path) -> List[str]:
    """
    Lit un fichier TSV-like (même si extension .txt).
    Tolère aussi qu'on lui passe un nom "historique" qui n'existe pas.
    """
    if not path.exists():
        fallback_map = {
            Path("data") / "post_verdicts.tsv": Path("data") / "verdict_post_analyse.txt",
            Path("data") / "post_verdicts.txt": Path("data") / "verdict_post_analyse.txt",
        }
        fb = fallback_map.get(path)
        if fb and fb.exists():
            path = fb
        else:
            raise FileNotFoundError(f"Fichier introuvable: {path}")

    with path.open("r", encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip()]


def _parse_time_to_minutes(t: Any) -> Optional[int]:
    if not isinstance(t, str):
        return None
    s = t.strip()
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _minute_to_hour_bin(m: Optional[int]) -> str:
    if m is None:
        return "NO_TIME"
    h = m // 60
    return f"{h:02d}h"


def load_post_verdicts(path: Path) -> pd.DataFrame:
    """
    Attend des lignes au format:
    TSV: date\tleague\thome\taway\tverdict_over\tverdict_btts\tover_score\tprob_btts\tscore\t
         over_decision\tover_eval\tbtts_decision\tbtts_eval\tstatus\ttime
    """
    lines = _read_tsv_lines(path)
    rows: List[Dict[str, Any]] = []

    for line in lines:
        if not line.startswith("TSV:"):
            continue
        raw = line[4:].lstrip()
        parts = raw.split("\t")
        if len(parts) < 14:
            continue

        date_str = parts[0]
        league = parts[1]
        home = parts[2]
        away = parts[3]
        verdict_over = parts[4]
        verdict_btts = parts[5]

        try:
            over_score = float(parts[6])
        except Exception:
            over_score = None

        try:
            prob_btts = float(parts[7])
        except Exception:
            prob_btts = None

        score = parts[8] if len(parts) > 8 else ""
        over_decision = parts[9] if len(parts) > 9 else ""
        over_eval = parts[10] if len(parts) > 10 else ""
        btts_decision = parts[11] if len(parts) > 11 else ""
        btts_eval = parts[12] if len(parts) > 12 else ""
        status = parts[13] if len(parts) > 13 else ""
        time_str = parts[14] if len(parts) > 14 else ""

        rows.append(
            {
                "date": date_str,
                "league": league,
                "home": home,
                "away": away,
                "verdict_over": verdict_over,
                "verdict_btts": verdict_btts,
                "over_score": over_score,
                "prob_btts": prob_btts,
                "score": score,
                "over_decision": over_decision,
                "over_eval": over_eval,
                "btts_decision": btts_decision,
                "btts_eval": btts_eval,
                "status": status,
                "time": time_str,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = df["date"].astype(str).str.strip()
    df["league"] = df["league"].astype(str).str.strip()
    df["time"] = df["time"].fillna("").astype(str).str.strip()

    df["time_minutes"] = df["time"].apply(_parse_time_to_minutes)

    df["over_eval"] = df["over_eval"].astype(str).str.strip().str.upper()
    df["btts_eval"] = df["btts_eval"].astype(str).str.strip().str.upper()
    df["over_decision"] = df["over_decision"].astype(str).str.strip().str.upper()
    df["btts_decision"] = df["btts_decision"].astype(str).str.strip().str.upper()

    df["over_score_bin"] = pd.cut(
        df["over_score"],
        bins=[0, 40, 50, 55, 60, 65, 70, 75, 80, 90, 100, 10_000],
        include_lowest=True,
        right=False,
    )

    df["prob_btts_bin"] = pd.cut(
        df["prob_btts"],
        bins=[0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 1.01],
        include_lowest=True,
        right=False,
    )

    df["hour_bin"] = df["time_minutes"].apply(_minute_to_hour_bin)

    return df


# -----------------------------
# Audit logic (4 cases)
# -----------------------------

@dataclass
class BetAuditSpec:
    name: str
    decision_col: str
    eval_col: str
    score_col: str
    score_bin_col: str


OVER_SPEC = BetAuditSpec(
    name="OVER",
    decision_col="over_decision",
    eval_col="over_eval",
    score_col="over_score",
    score_bin_col="over_score_bin",
)

BTTS_SPEC = BetAuditSpec(
    name="BTTS",
    decision_col="btts_decision",
    eval_col="btts_eval",
    score_col="prob_btts",
    score_bin_col="prob_btts_bin",
)


def add_case_columns(df: pd.DataFrame, spec: BetAuditSpec) -> pd.DataFrame:
    out = df.copy()

    dec = out[spec.decision_col].fillna("").astype(str).str.upper()
    ev = out[spec.eval_col].fillna("").astype(str).str.upper()

    out[f"{spec.name}_case"] = "OTHER"

    out.loc[(dec == "PLAY") & (ev == "WIN"), f"{spec.name}_case"] = "PLAY_WIN"
    out.loc[(dec == "PLAY") & (ev == "LOSS"), f"{spec.name}_case"] = "PLAY_LOSS"
    out.loc[(dec == "NO_PLAY") & (ev == "GOOD_NO_BET"), f"{spec.name}_case"] = "NO_PLAY_GOOD"
    out.loc[(dec == "NO_PLAY") & (ev == "BAD_NO_BET"), f"{spec.name}_case"] = "NO_PLAY_BAD"

    return out


def confusion_counts(df: pd.DataFrame, spec: BetAuditSpec) -> Dict[str, int]:
    c = df[f"{spec.name}_case"].value_counts().to_dict()
    return {
        "PLAY_WIN": int(c.get("PLAY_WIN", 0)),
        "PLAY_LOSS": int(c.get("PLAY_LOSS", 0)),
        "NO_PLAY_GOOD": int(c.get("NO_PLAY_GOOD", 0)),
        "NO_PLAY_BAD": int(c.get("NO_PLAY_BAD", 0)),
    }


def build_segments(df: pd.DataFrame, spec: BetAuditSpec, min_sample: int) -> pd.DataFrame:
    case_col = f"{spec.name}_case"

    def _segment_stats(g: pd.DataFrame) -> Dict[str, Any]:
        n = len(g)
        play = g[g[spec.decision_col] == "PLAY"]
        no_play = g[g[spec.decision_col] == "NO_PLAY"]

        play_n = len(play)
        no_play_n = len(no_play)

        play_win = int((g[case_col] == "PLAY_WIN").sum())
        play_loss = int((g[case_col] == "PLAY_LOSS").sum())
        no_play_bad = int((g[case_col] == "NO_PLAY_BAD").sum())
        no_play_good = int((g[case_col] == "NO_PLAY_GOOD").sum())

        win_rate_play = (play_win / play_n * 100.0) if play_n else 0.0
        loss_rate_play = (play_loss / play_n * 100.0) if play_n else 0.0
        bad_rate_no_play = (no_play_bad / no_play_n * 100.0) if no_play_n else 0.0

        pain = play_loss + no_play_bad
        pain_rate = (pain / n * 100.0) if n else 0.0

        avg_score = None
        if spec.score_col in g.columns:
            s = pd.to_numeric(g[spec.score_col], errors="coerce")
            m = s.dropna().mean()
            avg_score = float(m) if pd.notna(m) else None

        return {
            "n": n,
            "play_n": play_n,
            "no_play_n": no_play_n,
            "play_win": play_win,
            "play_loss": play_loss,
            "no_play_bad": no_play_bad,
            "no_play_good": no_play_good,
            "play_rate_%": (play_n / n * 100.0) if n else 0.0,
            "win_rate_when_play_%": win_rate_play,
            "loss_rate_when_play_%": loss_rate_play,
            "bad_no_bet_rate_when_no_play_%": bad_rate_no_play,
            "pain_rate_%": pain_rate,
            "avg_score": avg_score,
        }

    segments: List[pd.DataFrame] = []

    def _make(group_cols: List[str], label: str) -> None:
        if not group_cols:
            return
        gdf = (
            df.groupby(group_cols, dropna=False)
              .apply(lambda g: pd.Series(_segment_stats(g)))
              .reset_index()
        )
        gdf["segment_type"] = label
        segments.append(gdf)

    _make(["league"], "league")
    _make([spec.score_bin_col], "score_bin")
    _make(["league", spec.score_bin_col], "league+score_bin")
    _make(["hour_bin"], "hour")
    _make(["league", "hour_bin"], "league+hour")

    out = pd.concat(segments, ignore_index=True) if segments else pd.DataFrame()
    if out.empty:
        return out

    out = out[out["n"] >= int(min_sample)].copy()
    out["rank_pain"] = out["pain_rate_%"].rank(method="dense", ascending=False)
    return out.sort_values(["pain_rate_%", "n"], ascending=[False, False]).reset_index(drop=True)


def extract_examples(df: pd.DataFrame, spec: BetAuditSpec, case_value: str, top_n: int) -> pd.DataFrame:
    case_col = f"{spec.name}_case"
    sub = df[df[case_col] == case_value].copy()

    score = pd.to_numeric(sub[spec.score_col], errors="coerce")
    sub["_score_num"] = score

    cols = [
        "date", "time", "league", "home", "away",
        spec.score_col,
        spec.decision_col, spec.eval_col,
        "score", "status",
        "verdict_over", "verdict_btts",
    ]
    cols = [c for c in cols if c in sub.columns]

    # Pour NO_PLAY_GOOD, on veut souvent voir les "bons NO PLAY" même si score haut,
    # donc on garde aussi tri score décroissant (utile pour repérer les zones piégeuses).
    sub = sub.sort_values("_score_num", ascending=False)[cols].head(top_n).reset_index(drop=True)
    return sub


# -----------------------------
# Reporting
# -----------------------------

def write_markdown_summary(
    out_path: Path,
    df: pd.DataFrame,
    over_counts: Dict[str, int],
    btts_counts: Dict[str, int],
    over_segments: pd.DataFrame,
    btts_segments: pd.DataFrame,
) -> None:
    def _fmt_counts(name: str, c: Dict[str, int]) -> str:
        total = sum(c.values())
        return (
            f"### {name}\n"
            f"- Total lignes: **{total}**\n"
            f"- PLAY_WIN: **{c['PLAY_WIN']}**\n"
            f"- PLAY_LOSS: **{c['PLAY_LOSS']}**\n"
            f"- NO_PLAY_GOOD: **{c['NO_PLAY_GOOD']}**\n"
            f"- NO_PLAY_BAD: **{c['NO_PLAY_BAD']}**\n"
        )

    def _top(df_seg: pd.DataFrame, title: str) -> str:
        if df_seg is None or df_seg.empty:
            return f"### {title}\nAucun segment (pas assez de volume ou fichier vide).\n"

        top10 = df_seg.head(10)
        lines = [f"### {title} – Top 10 segments (pain_rate)\n"]

        for _, r in top10.iterrows():
            seg_type = r.get("segment_type")

            ident_parts = []
            for k in ["league", OVER_SPEC.score_bin_col, BTTS_SPEC.score_bin_col, "hour_bin"]:
                if k in r and pd.notna(r[k]) and str(r[k]).strip() != "":
                    ident_parts.append(f"{k}={r[k]}")
            ident = ", ".join(ident_parts) if ident_parts else "(segment)"

            avg = r.get("avg_score")
            avg_score_str = "" if avg is None or pd.isna(avg) else f"{float(avg):.2f}"

            lines.append(
                f"- **{seg_type}** | {ident} | n={int(r['n'])} | "
                f"pain={r['pain_rate_%']:.1f}% | "
                f"win_play={r['win_rate_when_play_%']:.1f}% | "
                f"bad_no_play={r['bad_no_bet_rate_when_no_play_%']:.1f}% | "
                f"avg_score={avg_score_str}"
            )

        lines.append("")
        return "\n".join(lines)

    text = []
    text.append("# Audit Triskèle – Post-analyse\n")
    text.append(f"- Généré: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    text.append(f"- Lignes chargées: **{len(df)}**\n")

    text.append(_fmt_counts("OVER", over_counts))
    text.append(_fmt_counts("BTTS", btts_counts))

    text.append(_top(over_segments, "OVER"))
    text.append(_top(btts_segments, "BTTS"))

    out_path.write_text("\n".join(text), encoding="utf-8")


# -----------------------------
# Run
# -----------------------------

def run_audit(post_verdicts_path: Path, archives_dir: Path, min_sample: int, top_n: int) -> Path:
    df = load_post_verdicts(post_verdicts_path)
    if df.empty:
        raise RuntimeError("verdict_post_analyse.txt semble vide ou non parsable.")

    df = add_case_columns(df, OVER_SPEC)
    df = add_case_columns(df, BTTS_SPEC)

    over_counts = confusion_counts(df, OVER_SPEC)
    btts_counts = confusion_counts(df, BTTS_SPEC)

    over_segments = build_segments(df, OVER_SPEC, min_sample=min_sample)
    btts_segments = build_segments(df, BTTS_SPEC, min_sample=min_sample)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = archives_dir / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    # Exemples concrets - 4 catégories (OVER)
    extract_examples(df, OVER_SPEC, "PLAY_LOSS", top_n=top_n).to_csv(out_dir / "over_examples_play_loss.csv", index=False)
    extract_examples(df, OVER_SPEC, "NO_PLAY_BAD", top_n=top_n).to_csv(out_dir / "over_examples_no_play_bad.csv", index=False)
    extract_examples(df, OVER_SPEC, "PLAY_WIN", top_n=top_n).to_csv(out_dir / "over_examples_play_win.csv", index=False)
    extract_examples(df, OVER_SPEC, "NO_PLAY_GOOD", top_n=top_n).to_csv(out_dir / "over_examples_no_play_good.csv", index=False)

    # Exemples concrets - 4 catégories (BTTS)
    extract_examples(df, BTTS_SPEC, "PLAY_LOSS", top_n=top_n).to_csv(out_dir / "btts_examples_play_loss.csv", index=False)
    extract_examples(df, BTTS_SPEC, "NO_PLAY_BAD", top_n=top_n).to_csv(out_dir / "btts_examples_no_play_bad.csv", index=False)
    extract_examples(df, BTTS_SPEC, "PLAY_WIN", top_n=top_n).to_csv(out_dir / "btts_examples_play_win.csv", index=False)
    extract_examples(df, BTTS_SPEC, "NO_PLAY_GOOD", top_n=top_n).to_csv(out_dir / "btts_examples_no_play_good.csv", index=False)

    # Segments
    if not over_segments.empty:
        over_segments.to_csv(out_dir / "over_segments.csv", index=False)
    if not btts_segments.empty:
        btts_segments.to_csv(out_dir / "btts_segments.csv", index=False)

    # Résumé markdown
    write_markdown_summary(
        out_dir / "summary.md",
        df=df,
        over_counts=over_counts,
        btts_counts=btts_counts,
        over_segments=over_segments,
        btts_segments=btts_segments,
    )

    print(f"✅ Audit terminé. Sorties dans: {out_dir}")
    return out_dir


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Audit des post-verdicts Triskèle (patterns récurrents).")
    parser.add_argument(
        "--post",
        type=str,
        default=str(DEFAULT_POST_VERDICTS),
        help="Chemin vers data/verdict_post_analyse.txt",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(DEFAULT_ARCHIVES_DIR),
        help="Dossier de sortie archives/audit/",
    )
    parser.add_argument(
        "--min-sample",
        type=int,
        default=MIN_SAMPLE_DEFAULT,
        help="Taille mini segment pour être retenu",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=TOP_N_EXAMPLES_DEFAULT,
        help="Nb d'exemples exportés par catégorie",
    )

    args = parser.parse_args()

    run_audit(
        post_verdicts_path=Path(args.post),
        archives_dir=Path(args.out),
        min_sample=int(args.min_sample),
        top_n=int(args.top_n),
    )


if __name__ == "__main__":
    main()