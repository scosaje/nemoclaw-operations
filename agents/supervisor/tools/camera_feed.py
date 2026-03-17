"""AnSA Camera Feed Query Tool - Simulated camera stream queries."""
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "mock"

def query_camera_feeds(location: str = None, time_range: str = None, filter_type: str = None) -> dict:
    """Query simulated camera feeds for detection events.

    Args:
        location: Filter by location (partial match, case-insensitive)
        time_range: Filter by time range in format "HH:MM-HH:MM" (24h)
        filter_type: Filter by event type (face_detected, vehicle_detected, anomaly_detected)

    Returns:
        Dict with matching events and metadata
    """
    with open(DATA_DIR / "camera_events.json") as f:
        data = json.load(f)

    events = data["events"]
    filtered = []

    for event in events:
        if location and location.lower() not in event["location"].lower():
            continue
        if filter_type and event["type"] != filter_type:
            continue
        if time_range:
            try:
                start_str, end_str = time_range.split("-")
                event_time = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).strftime("%H:%M")
                if not (start_str <= event_time <= end_str):
                    continue
            except (ValueError, KeyError):
                pass
        filtered.append(event)

    return {
        "status": "success",
        "total_events": len(filtered),
        "events": filtered,
        "query": {
            "location": location,
            "time_range": time_range,
            "filter_type": filter_type
        }
    }

if __name__ == "__main__":
    result = query_camera_feeds(location="Airport")
    print(json.dumps(result, indent=2))
