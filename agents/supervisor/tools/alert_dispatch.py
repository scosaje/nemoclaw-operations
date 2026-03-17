"""AnSA Alert Dispatch Tool - Simulated security alert dispatch system."""
import json
from datetime import datetime, timezone
import uuid

def dispatch_alert(severity: str, description: str, location: str, evidence: dict = None) -> dict:
    """Dispatch a security alert to the appropriate command center.

    Args:
        severity: Alert severity level (LOW, MEDIUM, HIGH, CRITICAL)
        description: Human-readable alert description
        location: Location of the incident
        evidence: Dict containing evidence chain (camera events, biometric matches, identity records)

    Returns:
        Dict with alert confirmation and dispatch details
    """
    valid_severities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    if severity.upper() not in valid_severities:
        return {"status": "error", "message": f"Invalid severity. Must be one of: {valid_severities}"}

    severity = severity.upper()
    alert_id = f"ALT-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # Determine responding agency based on severity
    responding_agencies = {
        "LOW": ["NSCDC"],
        "MEDIUM": ["NPF"],
        "HIGH": ["NPF", "DSS"],
        "CRITICAL": ["NPF", "DSS", "Military Intelligence"]
    }

    alert = {
        "status": "dispatched",
        "alert_id": alert_id,
        "severity": severity,
        "description": description,
        "location": location,
        "timestamp": timestamp,
        "responding_agencies": responding_agencies[severity],
        "evidence_attached": evidence is not None,
        "evidence_summary": _summarize_evidence(evidence) if evidence else None,
        "acknowledgment": f"Alert {alert_id} dispatched to {', '.join(responding_agencies[severity])}. "
                          f"Estimated response time: {_response_time(severity)}."
    }

    # Log to stdout (simulates dispatch)
    print(f"\n{'='*60}")
    print(f"🚨 ALERT DISPATCHED — {severity}")
    print(f"ID: {alert_id}")
    print(f"Time: {timestamp}")
    print(f"Location: {location}")
    print(f"Agencies: {', '.join(responding_agencies[severity])}")
    print(f"Description: {description}")
    print(f"{'='*60}\n")

    return alert

def _summarize_evidence(evidence: dict) -> str:
    parts = []
    if "camera_event" in evidence:
        parts.append(f"Camera detection: {evidence['camera_event']}")
    if "biometric_match" in evidence:
        parts.append(f"Biometric match: {evidence['biometric_match']}")
    if "identity_record" in evidence:
        parts.append(f"Identity verified: {evidence['identity_record']}")
    return " | ".join(parts) if parts else "Evidence provided"

def _response_time(severity: str) -> str:
    times = {"LOW": "60 minutes", "MEDIUM": "30 minutes", "HIGH": "15 minutes", "CRITICAL": "5 minutes"}
    return times.get(severity, "Unknown")

if __name__ == "__main__":
    result = dispatch_alert(
        severity="HIGH",
        description="POI detected at airport",
        location="Nnamdi Azikiwe Intl Airport",
        evidence={"camera_event": "EVT-001", "biometric_match": "POI-2847", "identity_record": "NIN verified"}
    )
    print(json.dumps(result, indent=2))
