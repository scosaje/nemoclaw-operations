"""AnSA Biometric Lookup Tool - Simulated face matching against persons of interest."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "mock"

def biometric_lookup(face_embedding_ref: str = None, person_id: str = None) -> dict:
    """Look up biometric data against persons of interest database.

    Args:
        face_embedding_ref: Face embedding reference ID to match (e.g., "emb_2847")
        person_id: Direct person of interest ID lookup (e.g., "POI-2847")

    Returns:
        Dict with match results and confidence scores
    """
    if not face_embedding_ref and not person_id:
        return {"status": "error", "message": "Provide face_embedding_ref or person_id"}

    with open(DATA_DIR / "persons_of_interest.json") as f:
        data = json.load(f)

    matches = []
    persons = data.get("persons", data.get("persons_of_interest", []))
    for person in persons:
        if face_embedding_ref and person["face_embedding_ref"] == face_embedding_ref:
            matches.append({**person, "match_type": "biometric", "match_confidence": 0.92})
        elif person_id and person["id"] == person_id:
            matches.append({**person, "match_type": "id_lookup", "match_confidence": 1.0})

    return {
        "status": "success" if matches else "no_match",
        "total_matches": len(matches),
        "matches": matches,
        "query": {
            "face_embedding_ref": face_embedding_ref,
            "person_id": person_id
        },
        "database": "AnSA Persons of Interest DB",
        "database_size": len(persons)
    }

if __name__ == "__main__":
    result = biometric_lookup(face_embedding_ref="emb_2847")
    print(json.dumps(result, indent=2))
