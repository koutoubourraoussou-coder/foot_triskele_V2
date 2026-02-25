# list_fav_leagues.py
from services.api_client import _call_api

# Les pays qui t'intéressent (d'après tes captures)
COUNTRIES = [
    "Argentina",
    "Belgium",
    "Brazil",
    "Colombia",
    "Czech Republic",
    "Denmark",
    "Ecuador",
    "England",
    "France",
    "Germany",
    "Italy",
    "Mexico",
    "Netherlands",
    "Paraguay",
    "Portugal",
    "Scotland",
    "Spain",
    "Switzerland",
    "Turkey",
    "USA",
]

def list_leagues_for_country(country: str):
    print(f"\n===== {country} =====")
    data = _call_api("/leagues", {"country": country}) or []

    # On dédoublonne par id de ligue
    leagues_by_id = {}

    for item in data:
        league_info = item.get("league", {}) or {}
        seasons = item.get("seasons", []) or []

        league_id = league_info.get("id")
        league_name = league_info.get("name")
        league_type = league_info.get("type")  # "League" ou "Cup"

        if league_id is None or not league_name:
            continue

        # On garde seulement les ligues qui ont une saison "current"
        has_current = any(s.get("current") for s in seasons)
        if not has_current:
            continue

        # Si on a déjà vu cette ligue, on ne la remet pas
        leagues_by_id[league_id] = {
            "name": league_name,
            "type": league_type,
        }

    # Affichage lisible
    if not leagues_by_id:
        print("  (aucune ligue trouvée)")
        return

    print("  Ligues actuelles :")
    for lid, info in sorted(leagues_by_id.items(), key=lambda x: x[0]):
        print(f"  - id={lid:4d} | {info['name']} ({info['type']})")

    # Bloc pour aliases.json
    print("\n  Bloc pour aliases.json :")
    for lid, info in sorted(leagues_by_id.items(), key=lambda x: x[0]):
        key = info["name"].lower()
        print(f'    "{key}": {lid},')


def main():
    print("🔎 Récupération des ligues par pays (API-Football)...")
    for country in COUNTRIES:
        list_leagues_for_country(country)

    # Compétitions continentales (C1 / C3 / C4) – on les traite à part
    print("\n===== Competitions UEFA (bonus) =====")
    uefa_targets = [
        "UEFA Champions League",
        "UEFA Europa League",
        "UEFA Europa Conference League",
    ]

    data = _call_api("/leagues", {}) or []
    found = {}
    for item in data:
        league_info = item.get("league", {}) or {}
        name = league_info.get("name")
        lid = league_info.get("id")
        if name in uefa_targets:
            found[name] = lid

    print("  Ligues UEFA trouvées :")
    for name, lid in found.items():
        print(f"  - id={lid} | {name}")

    print("\n  Bloc pour aliases.json :")
    for name, lid in found.items():
        key = name.lower().replace("uefa ", "")
        # ex: "champions league": 2,
        print(f'    "{key}": {lid},')


if __name__ == "__main__":
    main()