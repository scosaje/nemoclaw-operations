# AnSA Supervisor Agent — Tool Definitions

You have 6 investigation tools available as Python scripts. Call them using the `exec` tool from the `/sandbox/nemoclaw-operations` directory.

## Tool Invocation Pattern

All tools are Python scripts in `agents/supervisor/tools/`. Invoke them with `exec`:

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from <module> import <function>; import json; print(json.dumps(<function>(<args>), indent=2))"
```

## Available Tools

### 1. query_camera_feeds — Camera Surveillance Query

Query camera detection events filtered by location, time, or event type.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from camera_feed import query_camera_feeds; import json; print(json.dumps(query_camera_feeds(location='Airport'), indent=2))"
```

Parameters:
- `location` (str, optional): Location filter, partial match (e.g., "Airport", "Wuse")
- `time_range` (str, optional): Time filter in "HH:MM-HH:MM" format (e.g., "14:00-15:00")
- `filter_type` (str, optional): Event type — "face_detected", "vehicle_detected", or "anomaly_detected"

### 2. biometric_lookup — Persons of Interest Matching

Match face embeddings or person IDs against the watchlist database.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from biometric_lookup import biometric_lookup; import json; print(json.dumps(biometric_lookup(face_embedding_ref='emb_2847'), indent=2))"
```

Parameters:
- `face_embedding_ref` (str, optional): Face embedding reference (e.g., "emb_2847")
- `person_id` (str, optional): Person of interest ID (e.g., "POI-2847")

### 3. nimc_query — NIMC National Identity Lookup

Query NIMC national identity database by NIN or name.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from nimc_query import nimc_query; import json; print(json.dumps(nimc_query(nin='29384710256'), indent=2))"
```

Parameters:
- `nin` (str, optional): National Identification Number (11 digits)
- `name` (str, optional): Name search (partial match on surname/first_name)
- `state` (str, optional): State of origin filter

### 4. dispatch_alert — Security Alert Dispatch

Dispatch security alert to command centre with evidence chain. This is an ACTION — only call after verifying evidence.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from alert_dispatch import dispatch_alert; import json; print(json.dumps(dispatch_alert(severity='HIGH', description='POI detected at airport', location='Nnamdi Azikiwe Intl Airport', evidence={'camera_event': 'EVT-001', 'biometric_match': 'POI-2847', 'identity_record': 'NIN verified'}), indent=2))"
```

Parameters:
- `severity` (str, required): "LOW", "MEDIUM", "HIGH", or "CRITICAL"
- `description` (str, required): Human-readable alert description
- `location` (str, required): Incident location
- `evidence` (dict, optional): Evidence chain with camera_event, biometric_match, identity_record

Agency routing: LOW → NSCDC | MEDIUM → NPF | HIGH → NPF + DSS | CRITICAL → NPF + DSS + Military Intelligence

### 5. system_status — Subsystem Health Check

Check health of AnSA subsystems.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from system_status import system_status; import json; print(json.dumps(system_status(), indent=2))"
```

Parameters:
- `subsystem` (str, optional): Specific subsystem — "cameras", "biometric_db", "nimc_link", "avis", "network", "compute_cluster". Omit for all.

### 6. avis_voice_interface — AVIS Voice Intelligence

Process natural language voice commands. Parses intent and formats responses per protocol level.

```
exec: python3 -c "import sys; sys.path.insert(0, 'agents/supervisor/tools'); from avis_voice import avis_voice_interface; import json; print(json.dumps(avis_voice_interface(voice_command='Check cameras at airport', context={'operator_role': 'field_operator', 'protocol_level': 'standard'}), indent=2))"
```

Parameters:
- `voice_command` (str, required): Natural language command
- `context` (dict, optional): Contains `operator_role` and `protocol_level` ("standard", "dignitary", "command")

## Investigation Workflow

When investigating an alert, ALWAYS follow this sequence:

1. **query_camera_feeds** — Get detection events for the location/time
2. **biometric_lookup** — Match face embeddings against POI database
3. **nimc_query** — Verify identity via NIMC national database
4. **dispatch_alert** — Only if biometric confidence >85% AND identity verified
5. **avis_voice_interface** — Format report for operator protocol level

Never skip steps. Never dispatch an alert without completing the evidence chain.
