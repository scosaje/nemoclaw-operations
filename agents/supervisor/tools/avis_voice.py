"""AnSA AVIS Voice Interface Tool - Voice Intelligence System (text-simulated)."""
import json
import re

# Protocol-level response templates
PROTOCOL_FORMATS = {
    "standard": {
        "prefix": "",
        "style": "direct and actionable",
        "example_tone": "Target confirmed at Terminal 1. NPF and DSS alerted. Maintain visual, do not engage."
    },
    "dignitary": {
        "prefix": "BRIEFING: ",
        "style": "formal briefing",
        "example_tone": "Your Excellency, our surveillance system has identified a person of interest at the airport. Security forces have been notified and are responding."
    },
    "command": {
        "prefix": "SITREP: ",
        "style": "concise military-style",
        "example_tone": "POI CONFIRMED. LOC: NAIA T1. ASSETS: NPF/DSS DISPATCHED. STATUS: ACTIVE MONITORING."
    }
}

# Intent parsing patterns
INTENT_PATTERNS = [
    (r"(status|health|check|how.*system)", "system_query"),
    (r"(who|identify|face|person|suspect)", "identity_query"),
    (r"(camera|feed|surveillance|watch|monitor)", "camera_query"),
    (r"(alert|dispatch|notify|deploy|send)", "alert_action"),
    (r"(report|brief|summary|update)", "report_request"),
    (r"(threat|danger|risk|security)", "threat_assessment"),
]

def avis_voice_interface(voice_command: str, context: dict = None) -> dict:
    """Process voice command through AVIS (AnSA Voice Intelligence System).

    Args:
        voice_command: Natural language voice command from operator
        context: Dict with operator_role and protocol_level (standard/dignitary/command)

    Returns:
        Dict with parsed intent, structured query, and formatted response
    """
    if not voice_command:
        return {"status": "error", "message": "No voice command provided"}

    context = context or {}
    protocol_level = context.get("protocol_level", "standard")
    operator_role = context.get("operator_role", "field_operator")

    if protocol_level not in PROTOCOL_FORMATS:
        protocol_level = "standard"

    # Parse intent
    detected_intent = "general_query"
    for pattern, intent in INTENT_PATTERNS:
        if re.search(pattern, voice_command.lower()):
            detected_intent = intent
            break

    # Extract entities from command
    entities = _extract_entities(voice_command)

    # Format response based on protocol level
    protocol = PROTOCOL_FORMATS[protocol_level]

    return {
        "status": "success",
        "avis_session": {
            "operator_role": operator_role,
            "protocol_level": protocol_level,
            "response_style": protocol["style"]
        },
        "parsed_command": {
            "original": voice_command,
            "detected_intent": detected_intent,
            "entities": entities,
            "confidence": 0.94
        },
        "suggested_actions": _suggest_actions(detected_intent, entities),
        "response_format": {
            "prefix": protocol["prefix"],
            "style": protocol["style"],
            "note": f"Format all responses in {protocol['style']} style for {operator_role}"
        }
    }

def _extract_entities(command: str) -> dict:
    entities = {}
    # Location patterns
    location_match = re.search(r"(?:at|in|near)\s+(.+?)(?:\.|,|$)", command, re.I)
    if location_match:
        entities["location"] = location_match.group(1).strip()
    # Camera ID patterns
    cam_match = re.search(r"CAM[- ]?(\d+)", command, re.I)
    if cam_match:
        entities["camera_id"] = f"CAM-{cam_match.group(1)}"
    # POI patterns
    poi_match = re.search(r"POI[- ]?(\d+)", command, re.I)
    if poi_match:
        entities["person_id"] = f"POI-{poi_match.group(1)}"
    # Severity patterns
    sev_match = re.search(r"\b(LOW|MEDIUM|HIGH|CRITICAL)\b", command, re.I)
    if sev_match:
        entities["severity"] = sev_match.group(1).upper()
    return entities

def _suggest_actions(intent: str, entities: dict) -> list:
    actions = {
        "system_query": ["Call system_status tool to check subsystem health"],
        "identity_query": ["Call biometric_lookup with extracted person reference",
                           "Cross-reference with nimc_query for full identity"],
        "camera_query": ["Call query_camera_feeds with location/time filters"],
        "alert_action": ["Compile evidence chain", "Call dispatch_alert with severity and evidence"],
        "report_request": ["Gather data from relevant subsystems", "Format briefing per protocol level"],
        "threat_assessment": ["Query camera feeds for recent detections",
                              "Run biometric lookups on flagged faces",
                              "Assess threat level based on evidence"],
        "general_query": ["Clarify intent", "Check relevant subsystems"]
    }
    return actions.get(intent, ["Process query based on context"])

if __name__ == "__main__":
    result = avis_voice_interface(
        "Check the status of cameras at the airport",
        {"operator_role": "field_operator", "protocol_level": "standard"}
    )
    print(json.dumps(result, indent=2))
