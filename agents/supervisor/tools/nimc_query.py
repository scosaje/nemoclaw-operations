"""AnSA NIMC Query Tool - Simulated NIMC national identity database lookup."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "mock"

def nimc_query(nin: str = None, name: str = None, state: str = None) -> dict:
    """Query simulated NIMC (National Identity Management Commission) records.

    Args:
        nin: National Identification Number (11 digits)
        name: Name to search (partial match against surname and first_name)
        state: State of origin filter

    Returns:
        Dict with matching identity records
    """
    if not nin and not name:
        return {"status": "error", "message": "Provide nin or name for lookup"}

    with open(DATA_DIR / "nimc_records.json") as f:
        data = json.load(f)

    matches = []
    for record in data["records"]:
        if nin and record["nin"] == nin:
            matches.append({**record, "lookup_type": "nin_direct"})
        elif name:
            name_lower = name.lower()
            full_name = f"{record['surname']} {record['first_name']}".lower()
            if name_lower in full_name:
                if state and record["state_of_origin"].lower() != state.lower():
                    continue
                matches.append({**record, "lookup_type": "name_search"})

    return {
        "status": "success" if matches else "no_record",
        "total_records": len(matches),
        "records": matches,
        "query": {"nin": nin, "name": name, "state": state},
        "source": "NIMC National Identity Database (Simulated)",
        "verification_level": "NIN-verified" if nin else "name-search"
    }

if __name__ == "__main__":
    result = nimc_query(nin="28471039562")
    print(json.dumps(result, indent=2))
