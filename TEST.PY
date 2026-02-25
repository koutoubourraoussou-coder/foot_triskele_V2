from services.api_client import get_match_ids_from_meta, get_fixture_id_from_meta

print("Brest - Monaco :")
print("IDs ligue/équipes  ->", get_match_ids_from_meta("ligue 1", "2025-12-05", "Stade Brestois 29", "Monaco"))
print("fixture_id         ->", get_fixture_id_from_meta("ligue 1", "2025-12-05", "Stade Brestois 29", "Monaco"))

print("\nLille - Marseille :")
print("IDs ligue/équipes  ->", get_match_ids_from_meta("ligue 1", "2025-12-05", "Lille", "Marseille"))
print("fixture_id         ->", get_fixture_id_from_meta("ligue 1", "2025-12-05", "Lille", "Marseille"))