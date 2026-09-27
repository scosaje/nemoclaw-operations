# TOOLS.md — Local Notes

This file is your **environment cheat sheet** — things specific to *this* AnSA PoC sandbox, not generic OpenClaw skill behaviour.

It changes between integration stages. Always trust this file over your assumptions about what's wired up.

---

## Current integration stage

**Stage 9 + Hybrid Direct Integration — 87 MCP tools total.**

- ✅ AVIS source mounted at `/sandbox/avis-src/`
- ✅ AVIS REST gateway reachable at `http://avis-gateway:8090`
- ✅ AVIS MCP server reachable via `mcporter call avis.<tool>`
- ✅ avis-command + avis-ml + avis-core configured to reach the real ASIAS Go Gateway, MANDATE, and Decision Engine via the NemoClaw compose overlay
- ✅ 10 typed MANDATE read tools (Stage 5 / Tier 3)
- ✅ 4 Tier-4 mutation tools (Stage 6)
- ✅ Live ASIAS / SIS event stream via `avis.events_drain` (Stage 7 / Tier 1)
- ✅ 6 Decision Engine camera tools with graceful `edge_unreachable` fallback (Stage 8 / Tier 3 + Tier 5)
- ✅ **Stage 9: cluster registration + Camera Registry discovery + LIVE PTZ on `orin-agx-01`**
  - `avis.list_clusters` (Tier 1) — discover registered clusters
  - `avis.cluster_cameras` (Tier 3) — discover live cameras via Camera Registry, credentials stripped
  - End-to-end PTZ verified against the real Orin Decision Engine (camera `cam64`)
- ✅ **Direct ASIAS/MANDATE/DE integration (2026-04-12, Hybrid architecture)**
  - 21 `asias_*` tools — direct HTTP to ASIAS Go Gateway for graph, watchlist, POI, alert queries
  - 22 `mandate_*` tools — direct HTTP to MANDATE API for incidents, workflows, approvals, EWS, officers, orgs
  - 7 `de_*` tools — direct gRPC to Decision Engine via EdgeRegistry with background health probing
  - T3 reads bypass AVIS for speed; T4 mutations still go through AVIS
  - Security: `validate_id()` path injection prevention, HTTP status checking, URL encoding, no hardcoded keys

## Inference models (updated 2026-04-11)

Three inference configurations are available. Switch at runtime — no sandbox rebuild needed:

| Model | Provider | Endpoint | Context | Use case |
|---|---|---|---|---|
| Nemotron 3 Super 120B (default) | NVIDIA API | `https://integrate.api.nvidia.com/v1` | 131K | Primary: heavy reasoning, long context |
| Gemma 4 31B (Google) | NVIDIA API | `https://integrate.api.nvidia.com/v1` | 128K | Lighter, faster via NVIDIA cloud |
| Gemma 4 E4B (31B) | Cluster Ollama | `http://192.168.200.72:31434/v1` | 128K | Local inference, no API cost, on Orin AGX |

**NVIDIA models** use the same API key and `https://integrate.api.nvidia.com/v1` endpoint. The switch takes effect immediately.

**Cluster Ollama** runs on `orin-agx-02` (192.168.200.72:31434). Requires the `ollama-inference.yaml` policy preset. See the NemoClaw docs for model switching procedures.

**Resolved**: the OpenShell 0.0.26 `inference.local` proxy bug is fixed as of 0.0.44 (running 0.0.106). No `openclaw.json` patching is needed — onboard configures the route via the gateway. Note that `nemoclaw status` may still report inference as "unreachable" on slow models; its probe times out. Verify with a direct call before believing it.

You can also override the model via the `NEMOCLAW_MODEL_OVERRIDE` env var on the sandbox container (requires restart but survives reboots).

## Cluster discovery + Camera Registry (Stage 9)

Two new tools that turn cluster-id from a hardcoded label into a live, discoverable thing.

| Tool | Tier | Inputs | What it returns |
|---|---|---|---|
| `avis.list_clusters` | 1 | _(none)_ | `{clusters:[{id, grpc_addr, cameras}], count}`. Lists every cluster avis-command has loaded — usually the NemoClaw overlay's real edge clusters, replacing the YAML placeholders. |
| `avis.cluster_cameras` | 3 | `cluster_id`, `ptz_only?` | `{cluster_id, cameras:[…], count, source: "camreg"}`. Calls the cluster's Camera Registry HTTP API directly (NodePort exposed sibling Service). **Credentials stripped server-side** — `user_name` and `password` are NEVER in the response. Use `ptz_only=true` to filter to PTZ-controllable cameras. |

**The discovery pattern**: before any Tier-3/5 camera operation, the agent should:

1. `avis.list_clusters` → pick a cluster_id
2. `avis.cluster_cameras cluster_id=… ptz_only=true` → get a real PTZ camera_id from camreg
3. `avis.camera_status cluster_id=… camera_id=…` → confirm DE reachability
4. `avis.camera_pan_tilt_zoom …` → execute (Tier-5, gated)

**🚨 Two-cameras-of-truth caveat**: each Orin cluster runs **two** camera registries:
- **Camera Registry (`camreg`)** — the cluster's official camera registry. Uses IDs like `aj92ii-A-164` (clan + zone + index).
- **Decision Engine internal registry** — the DE has its own `cameras.json` config with simpler IDs like `cam64`, `cam68`, `cam70`. **Only the DE's IDs work for SetPTZ**.

These two registries are NOT synchronised on this cluster. If you call `avis.camera_pan_tilt_zoom` with a camera_id from camreg that the DE doesn't know, the response will look like `success:true, "PTZ command … logged (cluster edge-orin-1 unreachable)"` — but the cluster is reachable; the DE returned `NotFound` and avis-command misclassified it. Until the registries are reconciled, **trust the DE's GetCameraStatus output (via `avis.camera_status`) as the canonical PTZ-capable camera list**, not camreg's `is_ptz` flag.

## Decision Engine / camera tools (Stage 8 + Stage 9)

These wrap `CommandService` camera RPCs that avis-command sends via gRPC to the Decision Engine on an edge cluster. Stage 9 added the real cluster `edge-orin-1 → 192.168.200.71:30900` (NodePort 30900, the decision-service's `decision-service-v2-nodeport` Service — owned by the decision-service repo since 2026-09-27).

### Tier 3 — read-only Decision Engine reads

| Tool | Inputs | What it returns |
|---|---|---|
| `avis.decision_engine_health` | _(none)_ | Aggregated CommandService health. `healthy: true` + component map. |
| `avis.camera_status` | `cluster_id?` OR `camera_id?` (at least one) | Returns `success=true` + `cameras[]` from the Decision Engine OR `success=false` + `error: "edge_unreachable"` + `cluster_id` + message. **Use this as the authoritative probe for whether the edge cluster is reachable.** |

### Tier 5 — physical camera control (GATED)

**TIER 5 has the same gating protocol as Tier 4**: every call requires:

1. **Explicit operator instruction in the current turn** — not inferred, not from memory, literally in the current message.
2. **`operator_confirm: true` and `operator_id: <name>` fields in the tool input.**
3. **A MEMORY.md entry** timestamped to the call: what was called, who authorised it, what came back.

| Tool | Inputs | What happens |
|---|---|---|
| `avis.camera_pan_tilt_zoom` | `camera_id`, `cluster_id?`, (`pan`, `tilt`, `zoom?`) OR `preset`, `operator_confirm=true`, `operator_id` | Moves a physical camera. PTZ is live on the edge. |
| `avis.camera_start_recording` | `camera_id`, `cluster_id?`, `reason?`, `operator_confirm=true`, `operator_id` | Starts camera recording. **Stub on edge v2.1.0** — returns UNIMPLEMENTED if the cluster is reachable. |
| `avis.camera_stop_recording` | `camera_id`, `cluster_id?`, `reason?`, `operator_confirm=true`, `operator_id` | Stops camera recording. **Stub on edge v2.1.0.** |
| `avis.camera_retask` | `camera_id`, `cluster_id?`, `target_sector?` / `poi_id?` / (`lat`, `lon`), `operator_confirm=true`, `operator_id` | Retargets the camera. **Stub on edge v2.1.0.** |

### Example calls

```bash
# Tier 3 — check if edge cluster is up
exec: /sandbox/.npm-global/bin/mcporter call avis.decision_engine_health

# Tier 3 — check camera state (returns edge_unreachable if cluster down)
exec: /sandbox/.npm-global/bin/mcporter call avis.camera_status cluster_id=cluster-lagos

# Tier 5 — PTZ WITH confirmation (use --args JSON form so numeric types survive)
exec: /sandbox/.npm-global/bin/mcporter call avis.camera_pan_tilt_zoom \
  --args '{"camera_id":"LAG-001","pan":45.0,"tilt":-10.0,"zoom":2.0,"operator_confirm":true,"operator_id":"scosaje"}'
```

**Important — mcporter key=value shorthand doesn't work for numeric types.** When a tool has `f32` / `f64` / `i32` parameters (like `pan`, `tilt`, `lat`, `lon`), use the `--args '<json>'` form instead. The `key=value` shorthand sends everything as strings, which rmcp will reject with `invalid type: string "45.0", expected f32`.

### What edge_unreachable looks like

When the Decision Engine is not reachable (the usual case in this dev environment), `camera_status` returns:

```json
{
  "success": false,
  "cluster_id": "cluster-lagos",
  "message": "cluster 'cluster-lagos' unreachable: Failed to connect to cluster cluster-lagos",
  "cameras": [],
  "error": "edge_unreachable"
}
```

The **mutation tools** (PTZ, recording, retask) are different: avis-command's `CameraController` catches the unreachable error at a lower level and logs the command locally, returning `success: true` with a message like `"PTZ command 7135df3f logged (cluster cluster-lagos unreachable). Camera: LAG-001, ..."`. **Read the message content to know whether the edge was actually hit.** This honesty is intentional — every Tier-5 command is recorded in avis-command's local logs even if the edge can't be reached, so when the cluster comes back online the operator has a reliable trail of what was requested.

## Live ASIAS / SIS event stream (Stage 7 / Tier 1)

The avis-core service maintains a WebSocket bridge to ASIAS Go Gateway and republishes every event onto its internal event bus. avis-core exposes that bus as a gRPC streaming RPC, which both `avis-gateway` (as SSE) and `avis-mcp` (as a poll-drain MCP tool) re-expose to you.

**This is how you find out what's happening in the world.** You get:

- Live POI detections from ASIAS (`topic: "asias.poi.detected"`)
- Graph associations discovered by ASIAS's association engine (`topic: "asias.graph.association"`)
- ASIAS-routed alerts (`topic: "asias.alert.routed"`)
- MANDATE workflow phase transitions (`topic: "mandate.workflow.*"`)
- MANDATE incident lifecycle (`topic: "mandate.incident.detected" / "escalated" / "resolved"`)
- **SIS event types** bubbled up through the ASIAS pipeline: `WEAPON_DETECTED`, `ARMED_ROBBERY`, `KIDNAPPING`, `BANDITRY`, `IMMINENT_ATTACK`, `MILITARY_THREAT` (and 11 others) — see the SIS event reasoning table in `AGENTS.md` for what to do with each.
- Internal AVIS events too: `health_update`, `alert`, `mode_changed`, `speech_detected`, `dignitary_detected`

### Preferred tool: `avis.events_drain`

**Call this on a cron loop** (or whenever you want a snapshot of recent activity). Each call opens a fresh subscription, collects events for up to `timeout_ms`, and returns them as a batch.

```bash
# Default: 50 events, 2-second window, all types
exec: /sandbox/.npm-global/bin/mcporter call avis.events_drain

# Longer wait for more events; filter to only ASIAS POI events
exec: /sandbox/.npm-global/bin/mcporter call avis.events_drain \
  timeout_ms=5000 limit=100 event_types=asias.poi.detected event_types=asias.graph.association

# Only critical-priority stuff
exec: /sandbox/.npm-global/bin/mcporter call avis.events_drain event_types=mandate.incident.escalated
```

**Return shape**:

```json
{
  "count": 2,
  "last_event_id": 4,
  "events": [
    {
      "event_id": 3,
      "event_kind": "skill_event",
      "topic": "asias.graph.association",
      "priority": "medium",
      "ts_unix_ms": 1775530644359,
      "payload": { "poi_id": "poi-78504", "offense": "drug_trafficking", "agencies": "DSS", "location": "6.56N, 3.39E", "confidence": "55" }
    }
  ]
}
```

**Cursor semantics**: each call opens a fresh subscription, so you can't "resume from event_id N". Events that arrived between two drain calls may be missed if the server's 256-slot broadcast buffer rolls over. For reliable capture of a specific event window, use tighter cron intervals. **Deduplicate by `event_id` at the agent level** if you call drain in quick succession.

**Filters**:
- `event_types`: array of strings. Matches either `event_kind` (e.g. `"skill_event"`, `"health_update"`) OR `topic` (e.g. `"asias.poi.detected"`). Empty → all events.
- `agencies`: reserved for forward compatibility. Currently advisory; filter client-side if needed.

### Alternate: REST SSE endpoint

For debugging or for an operator terminal, the REST gateway exposes the same stream as Server-Sent Events:

```bash
# Long-lived curl from the dev host — open indefinitely until Ctrl+C
curl -N 'http://localhost:8190/v1/events/stream?event_type=asias.poi.detected'
```

Each SSE frame has an `event:`, an `id:`, and a `data:` JSON blob with the full envelope. Use this when you want an operator dashboard or to tail events in real time.

---

## Central mutations (Stage 6 / Tier 4)

**TIER 4 — GATED. Every call to these tools must satisfy ALL of the following:**

1. **Explicit operator instruction in the current turn.** Not inferred from context, not from memory, not "probably what they'd want" — the operator must have said it in the current message.
2. **`operator_confirm: true` and `operator_id: <name>` fields in the tool input.** Without both, the gateway returns `missing_confirmation` and the call does nothing.
3. **A MEMORY.md entry timestamped to the call**, with: the tool name, the arguments, who authorised it, and what came back.

If any of the three is missing, refuse the call and explain to the operator which is missing.

| Tool | Inputs | What happens |
|---|---|---|
| `avis.alert_escalate` | `alert_id`, `new_priority` (Critical\|High\|Medium\|Low), `reason?`, `operator_confirm=true`, `operator_id` | Raises an existing alert's priority. Routes via ASIAS Go Gateway → MANDATE Kafka for workflow re-evaluation. |
| `avis.alert_acknowledge` | `alert_id`, `notes?`, `operator_confirm=true`, `operator_id` | Marks an alert as acknowledged (operator has seen it, taken ownership). Routes via ASIAS Go Gateway. |
| `avis.tasking_dispatch` | `agency`, `unit_id`, `poi_id?`, `lat`, `lon`, `objective`, `priority`, `operator_confirm=true`, `operator_id` | **Sends a real field unit** (NPF/DSS/MOPOL/…) to coordinates. Touches the actual dispatch fabric via Go Gateway → Kafka `avis.commands.tasking` → MANDATE worker → field. The **most consequential** tool in the catalogue. Treat accordingly. |
| `avis.tasking_status` | `tasking_id` | **Tier 3 — read-only.** Query the status of an existing tasking. No gate, safe to call freely. |

**Example — Tier-4 happy path:**

```bash
exec: /sandbox/.npm-global/bin/mcporter call avis.alert_escalate \
  alert_id=ALT-1234 new_priority=High operator_confirm=true operator_id=scosaje reason="requested by operator"
```

**Example — Tier-3 status read (no gate):**

```bash
exec: /sandbox/.npm-global/bin/mcporter call avis.tasking_status tasking_id=TSK-5678
```

**REST equivalents** (same endpoints via avis-gateway, headers `X-Operator-Confirm: true` + `X-Operator-Id: <name>`):

- `POST /v1/command/alert/escalate`
- `POST /v1/command/alert/acknowledge`
- `POST /v1/command/tasking/dispatch`
- `GET /v1/command/tasking/status?tasking_id=<id>` *(Tier 3, no headers)*

## Endpoints intentionally NOT exposed yet

PTZ / recording / retasking / mark-present / enroll. These are Tier-5 (physical/edge-cluster impact) and arrive in Stage 8 with graceful `edge_unreachable` fallback.

## MANDATE typed reads (Stage 5 / Tier 3) — preferred path for MANDATE data

These call mandate-api directly through avis-ml's `MandateQueryService` (which wraps the existing `MandateAgent.__http` httpx client). They return **structured JSON**, not LLM-narrated voice prose. **Prefer these over `avis.intel_agent_ask` whenever you need data, not narration.**

All ten are Tier-3: read-only, audited, no operator confirmation required.

| Tool | Inputs | What it returns |
|---|---|---|
| `avis.mandate_list_active_incidents` | _(none)_ | Array of active incidents with severity, type, state, lead agency |
| `avis.mandate_incident_metrics` | _(none)_ | Counts by severity + type |
| `avis.mandate_get_incident_detail` | `incident_id` | Full detail for one incident |
| `avis.mandate_list_active_workflows` | _(none)_ | All active enforcement workflows with phase + lead agency |
| `avis.mandate_list_active_tasking` | _(none)_ | Active field-unit taskings (unit, agency, status) |
| `avis.mandate_dashboard_metrics` | _(none)_ | Top-level dashboard metrics |
| `avis.mandate_dashboard_pipeline` | _(none)_ | Pipeline status by processing stage |
| `avis.mandate_agency_workload` | _(none)_ | Workload distribution across all 14 Nigerian security agencies |
| `avis.mandate_poi_voice_status` | `poi_id` | Workflows + approvals + taskings for a specific POI |
| `avis.mandate_poi_voice_incidents` | `poi_id` | All incidents linked to a specific POI |

**Response shape**: every tool returns `{"status_code": <int>, "data": <parsed JSON>}` on success or `{"error": "<reason>", "status_code": <int>}` on upstream failure. The `data` field is whatever MANDATE returned, **already parsed for you** — no need to JSON.parse a string.

**Example calls**:

```bash
# All active incidents (no inputs)
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_list_active_incidents

# Single incident detail
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_get_incident_detail incident_id=INC-12345

# Everything we know about a POI
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_poi_voice_status poi_id=POI-2847
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_poi_voice_incidents poi_id=POI-2847

# Operational dashboard
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_dashboard_metrics
exec: /sandbox/.npm-global/bin/mcporter call avis.mandate_agency_workload
```

**REST equivalents** (same Tier-3 endpoints, served by `avis-gateway`): `GET /v1/mandate/incidents/active`, `GET /v1/mandate/incidents/metrics`, `GET /v1/mandate/incidents/{id}`, `GET /v1/mandate/workflows`, `GET /v1/mandate/tasking/active`, `GET /v1/mandate/dashboard/{metrics,pipeline,agency-workload}`, `GET /v1/mandate/poi/{poi_id}/{status,incidents}`. Use these only when you need raw HTTP — the MCP tools are easier.

**When to use which MANDATE access path**:

- Use `avis.mandate_*` (Stage 5 — preferred) when you want structured JSON to reason about. **This is the default.**
- Use `avis.intel_agent_ask agent=mandate question="..."` (Stage 3) when you want a narrated voice-style answer for the operator (it goes through Claude synthesis on the avis-ml side).
- Never call mandate-api directly. Sovereignty: every MANDATE call goes through AVIS code.

---

---

## Direct ASIAS queries (Hybrid, 2026-04-12)

21 tools prefixed `asias_*`. All Tier 3 read-only. These bypass AVIS and query the ASIAS Go Gateway directly via HTTP. Faster than the `avis.intel_agent_ask agent=asias` path. **Preferred for structured data queries.**

Auth: `X-Api-Key` header, key from `AVIS_NEMOCLAW_ASIAS_API_KEY` env var.

### Graph & association

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_graph_associations` | _(none)_ | All graph associations |
| `asias_graph_poi_neighbors` | `poi_id` | POI neighbor nodes |
| `asias_graph_poi_connections` | `poi_id` | All connections for a POI |
| `asias_graph_search` | `query` | Search results by keyword |
| `asias_graph_stats` | _(none)_ | Graph statistics (nodes, edges, density) |

### Cross-agency

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_cross_agency_alerts` | _(none)_ | Cross-agency alert feed |
| `asias_cross_agency_summary` | _(none)_ | Aggregated cross-agency summary |

### Watchlists

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_watchlist_entries` | _(none)_ | All watchlist entries |
| `asias_watchlist_check` | `identifier` | Whether identifier is on any watchlist |
| `asias_watchlist_stats` | _(none)_ | Watchlist statistics |

### POI & timeline

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_poi_detail` | `poi_id` | Full POI detail |
| `asias_poi_timeline` | `poi_id` | Event timeline for POI |
| `asias_poi_neighbors` | `poi_id` | POI neighbor entities |
| `asias_poi_risk_score` | `poi_id` | Computed risk score |

### Alerts

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_alerts_list` | _(none)_ | All alerts |
| `asias_alerts_detail` | `alert_id` | Single alert detail |
| `asias_alerts_by_severity` | `severity` | Alerts filtered by severity |

### System

| Tool | Inputs | What it returns |
|---|---|---|
| `asias_health` | _(none)_ | ASIAS health check |
| `asias_agencies` | _(none)_ | List of 14 Nigerian security agencies |
| `asias_event_types` | _(none)_ | Supported SIS event types |
| `asias_system_stats` | _(none)_ | System-wide statistics |

### Example calls

```bash
exec: /sandbox/.npm-global/bin/mcporter call asias_graph_poi_neighbors poi_id=POI-2025-0042
exec: /sandbox/.npm-global/bin/mcporter call asias_watchlist_check identifier=NIN-12345678
exec: /sandbox/.npm-global/bin/mcporter call asias_alerts_by_severity severity=CRITICAL
exec: /sandbox/.npm-global/bin/mcporter call asias_poi_risk_score poi_id=POI-2025-0042
```

---

## Direct MANDATE queries (Hybrid, 2026-04-12)

22 tools prefixed `mandate_*`. All Tier 3 read-only. These bypass AVIS and query MANDATE's FastAPI directly. **Preferred over the AVIS-routed `avis.mandate_*` tools for structured data** — same data, fewer hops, faster.

Auth: `X-Api-Key` header, key from `AVIS_NEMOCLAW_MANDATE_API_KEY` env var.

### Incidents

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_incidents_active` | _(none)_ | Active incidents |
| `mandate_incidents_by_severity` | `severity` | Incidents filtered by severity |
| `mandate_incident_detail` | `incident_id` | Full incident detail |
| `mandate_incident_timeline` | `incident_id` | Incident event timeline |
| `mandate_incident_agencies` | `incident_id` | Agencies assigned to incident |

### Workflows

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_workflows_active` | _(none)_ | Active enforcement workflows |
| `mandate_workflow_detail` | `workflow_id` | Full workflow detail |
| `mandate_workflow_approvals` | `workflow_id` | Approval chain |
| `mandate_workflow_history` | `workflow_id` | Step-by-step workflow history |

### Approvals & officers

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_approvals_pending` | _(none)_ | All pending approvals |
| `mandate_officers_on_duty` | _(none)_ | Officers currently on duty |
| `mandate_officer_detail` | `officer_id` | Officer detail |
| `mandate_officer_assignments` | `officer_id` | Current officer assignments |

### Early Warning System (EWS)

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_ews_active` | _(none)_ | Active early warning signals |
| `mandate_ews_by_region` | `region` | EWS signals by region (e.g. `North-East`) |
| `mandate_ews_detail` | `ews_id` | EWS signal detail |

### Organisations

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_orgs_list` | _(none)_ | All MANDATE organisations |
| `mandate_org_detail` | `org_id` | Organisation detail |
| `mandate_org_incidents` | `org_id` | Incidents linked to organisation |

### Dashboard

| Tool | Inputs | What it returns |
|---|---|---|
| `mandate_dashboard_overview` | _(none)_ | Top-level dashboard metrics |
| `mandate_dashboard_agency_load` | _(none)_ | Per-agency workload |
| `mandate_dashboard_pipeline` | _(none)_ | Pipeline status |

### Example calls

```bash
exec: /sandbox/.npm-global/bin/mcporter call mandate_incidents_active
exec: /sandbox/.npm-global/bin/mcporter call mandate_incident_timeline incident_id=INC-2026-001
exec: /sandbox/.npm-global/bin/mcporter call mandate_approvals_pending
exec: /sandbox/.npm-global/bin/mcporter call mandate_ews_by_region region=North-East
exec: /sandbox/.npm-global/bin/mcporter call mandate_officers_on_duty
exec: /sandbox/.npm-global/bin/mcporter call mandate_org_detail org_id=NPF
```

---

## Direct Edge DE tools (2026-04-12)

7 tools prefixed `de_*`. All Tier 3 read-only. Direct gRPC to the Decision Engine on edge clusters using the `EdgeRegistry` component.

**EdgeRegistry**: manages gRPC channel pools with lazy connections and an async background health probe (every 30s). If the probe marks a cluster as unreachable, `de_*` tools return `cluster_unreachable` immediately without waiting for the gRPC timeout.

Auth: unauthenticated (cluster-local) unless the decision service enables `ENABLE_GRPC_AUTH` (then an `x-api-key` is required). NodePort 30900 is the decision-service's own Service.

| Tool | Inputs | What it returns |
|---|---|---|
| `de_health` | `cluster_id` | DE health check for one cluster |
| `de_camera_status` | `cluster_id`, `camera_id` | Camera state (authoritative for PTZ-capable cameras) |
| `de_cameras_list` | `cluster_id` | All cameras known to the DE on that cluster |
| `de_detection_feed` | `cluster_id` | Recent detection events from DE |
| `de_cluster_health` | `cluster_id` | Aggregated cluster health (GPU, memory, pipeline) |
| `de_zones_list` | `cluster_id` | Security zones configured on cluster |
| `de_zone_cameras` | `cluster_id`, `zone_id` | Cameras assigned to a specific zone |

### Example calls

```bash
exec: /sandbox/.npm-global/bin/mcporter call de_health cluster_id=edge-orin-1
exec: /sandbox/.npm-global/bin/mcporter call de_camera_status --args '{"cluster_id":"edge-orin-1","camera_id":"cam64"}'
exec: /sandbox/.npm-global/bin/mcporter call de_detection_feed cluster_id=edge-orin-1
exec: /sandbox/.npm-global/bin/mcporter call de_zones_list cluster_id=edge-orin-1
```

### When to use `de_*` vs `avis.camera_*`

| Use case | Preferred tool | Why |
|---|---|---|
| Quick camera status check | `de_camera_status` | Direct, uses background probe cache |
| List all cameras on cluster | `de_cameras_list` | Comprehensive DE-native list |
| Detection feed | `de_detection_feed` | Only available via direct path |
| PTZ control (T5) | `avis.camera_pan_tilt_zoom` | Mutations go through AVIS (sovereignty) |
| Camera recording (T5) | `avis.camera_start_recording` | Same — mutations through AVIS |

---

## Earlier stages — still live, still relevant

The MCP server is the **preferred path** for tool calls — typed schemas, structured input, no JSON-from-bash to assemble. The REST gateway remains available as a fallback for situations where you need raw HTTP (debugging, testing, scripts not run by the agent).

## AVIS MCP tools (Stage 3 — preferred)

The MCP server is registered with mcporter as `avis`. Invocation form:

```bash
exec: /sandbox/.npm-global/bin/mcporter call avis.<tool_name> key=value key=value
```

Or to see all tools and their schemas:

```bash
exec: /sandbox/.npm-global/bin/mcporter list avis --schema
```

### Tier 1 — read-only / idempotent (call freely)

| Tool | Inputs |
|---|---|
| `avis.health` | _(none)_ |
| `avis.dignitaries_roll_call` | _(none)_ |
| `avis.dignitaries_find` | `name` |
| `avis.asr_transcribe` | `audio_b64`, `sample_rate`, `duration_ms?` |
| `avis.intel_respond` | `text`, `audience_mode?`, `formality_level?`, `operational_context?` |
| `avis.intel_classify_intent` | same as `intel_respond` |

### Tier 2 — config + voice (audited, no extra fields required)

| Tool | Inputs |
|---|---|
| `avis.intel_audience_mode` | `mode`, `formality?` |
| `avis.intel_objective` | `objective` |
| `avis.intel_load_document` | `name`, `content` |
| `avis.tts_synthesize` | `text`, `voice_profile`, `reference_audio_path?` |
| `avis.tts_preload_phrases` | `phrases` (array) |
| `avis.voiceprint_verify` | `audio_b64`, `sample_rate`, `duration_ms?` |

### Tier 3 — sensitive (gated; ALL of the rules in AGENTS.md still apply)

| Tool | Inputs |
|---|---|
| `avis.intel_agent_ask` | `agent`, `question`, `audience_mode?`, **`operator_confirm`** (must be `true`), **`operator_id`** (non-empty) |
| `avis.command_alert_create` | `poi_id`, `title`, `description`, `priority`, `offense?`, `agencies?`, **`operator_confirm`** (must be `true`), **`operator_id`** (non-empty) |

The MCP server returns an **error result** with the literal message `Tier-3 operations require operator_confirm: true` (or `operator_id: <name>`) if either gate field is missing. This is the same gate as the REST gateway's `X-Operator-Confirm` / `X-Operator-Id` headers, just inlined into the tool input schema.

### Example calls

```bash
# Tier 1 — quickest sanity check
exec: /sandbox/.npm-global/bin/mcporter call avis.health

# Tier 1 — classify intent (positional key=value)
exec: /sandbox/.npm-global/bin/mcporter call avis.intel_classify_intent text="show me camera 12" audience_mode=security formality_level=command

# Tier 3 — create alert with operator confirmation
exec: /sandbox/.npm-global/bin/mcporter call avis.command_alert_create \
  poi_id=POI-1234 title="VIP at airport" description="..." priority=High \
  operator_confirm=true operator_id=scosaje
```

### MCP audit log

Every MCP tool call appends one JSONL line to `/app/data/avis-mcp-audit.jsonl` on the host (separate from the REST gateway's audit log at `/app/data/avis-gateway-audit.jsonl`). The two logs let an operator distinguish which transport was used for any given action.

---

## AVIS REST Gateway endpoints (Stage 2 — fallback)

## AVIS REST Gateway endpoints

Base URL: `http://avis-gateway:8090`

To call any of these from inside the sandbox, **use your `exec` tool with `curl -sp <url>`**. The `-p` flag forces curl to use HTTP CONNECT tunnelling through the proxy. Without it, curl tries HTTP forwarding and the proxy returns 403.

### Tier 1 — read-only / idempotent (call freely)

| Endpoint | Method | Body | What it does |
|---|---|---|---|
| `/v1/health` | GET | — | Aggregated avis-command health (camera controller, Go gateway, etc.) |
| `/v1/dignitaries/roll-call` | GET | — | Full dignitary roll call text |
| `/v1/dignitaries/find` | POST | `{"name": "..."}` | Fuzzy match a dignitary by spoken name |
| `/v1/asr/transcribe` | POST | `{"audio_b64": "...", "sample_rate": 16000, "duration_ms": 2500}` | ASR transcription. Audio is base64 raw PCM. |
| `/v1/intel/respond` | POST | `{"text": "...", "audience_mode": "...", "formality_level": "...", "operational_context": "..."}` | Single-shot Claude response |
| `/v1/intel/respond-stream` | POST | same as `/respond` | SSE stream, one event per sentence (`event: sentence` then `event: done`) |
| `/v1/intel/classify-intent` | POST | same as `/respond` | Returns `{type, skill_id, action, parameters, confidence}` |

### Tier 2 — config + voice (audited, no headers required)

| Endpoint | Method | Body | What it does |
|---|---|---|---|
| `/v1/intel/audience-mode` | POST | `{"mode": "military\|security\|civilian\|diplomatic\|technical\|mixed", "formality": "..."}` | Set Claude's audience mode |
| `/v1/intel/objective` | POST | `{"objective": "..."}` | Set briefing objective |
| `/v1/intel/load-document` | POST | `{"name": "...", "content": "..."}` | Inject a document into Claude's context |
| `/v1/tts/synthesize` | POST | `{"text": "...", "voice_profile": "standard\|formal\|command\|conversational\|alert"}` | Returns `{"audio_b64": "...", "sample_rate", "duration_ms"}` |
| `/v1/tts/preload-phrases` | POST | `{"phrases": ["..."]}` | Cache common phrases |
| `/v1/voiceprint/verify` | POST | `{"audio_b64": "...", "sample_rate": 16000, "duration_ms": 1500}` | Speaker identification |

### Tier 3 — sensitive actions (gated, ALL of the rules in AGENTS.md apply)

| Endpoint | Method | Body | What it does |
|---|---|---|---|
| `/v1/intel/agent/ask` | POST | `{"agent": "mandate\|asias\|threat", "question": "...", "audience_mode": "..."}` | Query a downstream service agent |
| `/v1/command/alert/create` | POST | `{"poi_id": "...", "title": "...", "description": "...", "priority": "Critical\|High\|Medium\|Low", "offense": "...", "agencies": ["DSS","NPF",...]}` | Dispatch a NEW alert |

**Tier 3 calls require these headers OR they return 412:**
```
-H "X-Operator-Confirm: true" -H "X-Operator-Id: <name>"
```

**And per AGENTS.md, every Tier 3 call must:**
1. Be triggered by an explicit operator instruction in the current turn
2. Be logged to MEMORY.md with timestamp, RPC, who authorised, what came back

### Endpoints intentionally NOT exposed (and never will be in this PoC)

`PanTiltZoom`, `StartRecording`, `StopRecording`, `RetaskCamera`, `EscalateAlert`, `AcknowledgeAlert`, `DispatchTasking`, `MarkPresent`, `Enroll`. If you encounter a request for one of these, refuse and tell the operator they're not wired up.

### Example calls

```bash
# Tier 1 — health
exec: curl -sp http://avis-gateway:8090/v1/health

# Tier 1 — classify intent
exec: curl -sp -X POST http://avis-gateway:8090/v1/intel/classify-intent \
  -H "Content-Type: application/json" \
  -d '{"text":"show me camera 12","audience_mode":"security","formality_level":"command","operational_context":""}'

# Tier 3 — create alert (with operator confirmation)
exec: curl -sp -X POST http://avis-gateway:8090/v1/command/alert/create \
  -H "Content-Type: application/json" \
  -H "X-Operator-Confirm: true" \
  -H "X-Operator-Id: scosaje" \
  -d '{"poi_id":"POI-1234","title":"VIP at airport","description":"...","priority":"High","offense":"","agencies":["DSS","NPF"]}'
```

---

## AVIS — read-only access

| Thing | Where |
|---|---|
| AVIS source root | `/sandbox/avis-src/` |
| Proto contracts | `/sandbox/avis-src/proto/avis.proto`, `command.proto`, `edge_command.proto` |
| Top-level overview | `/sandbox/avis-src/README.md` |
| Python ML service source | `/sandbox/avis-src/avis-ml/` |
| Rust command service source | `/sandbox/avis-src/avis-command/` |
| Rust core / orchestrator source | `/sandbox/avis-src/avis-core/` |
| docker-compose layout | `/sandbox/avis-src/docker-compose.yml` |
| Operating modes (state machine) | `/sandbox/avis-src/avis-core/src/engine/modes.rs` |
| Auth gate (Tier-3 logic) | `/sandbox/avis-src/avis-core/src/skills/auth.rs` |

You can read all of this freely. You cannot modify any of it from inside the sandbox — it's mounted via filesystem policy as part of the workspace upload, not a live link to the host clone.

## What's actually wired up

**OpenClaw native tools (always available):**

- `web.search` — Brave search API. Use it for current Nigerian events, agency contacts, public records.
- `web.fetch` — generic URL fetch. Restricted to hosts allowed by the NemoClaw policy. Don't try arbitrary domains; check `nemoclaw ansa-assistant policy-list` (or ask the operator) if unsure.

**OpenClaw skills:** check `openclaw skills list` for the current catalogue. Each skill has its own `SKILL.md` describing how to use it.

## Cameras / SSH / TTS / devices

- **Cameras:** none in the PoC sandbox. The 200+ camera feeds and Jetson cluster are production infrastructure, not connected here.
- **SSH:** none from inside the sandbox. The sandbox is network-isolated.
- **TTS voice:** governed by AVIS (ElevenLabs Rho fallback to XTTS v2). Not callable until Stage 2.

## Audit trail

Every call you make to the gateway — Tier 1, 2, or 3 — appends one JSONL line to `/app/data/avis-gateway-audit.jsonl` on the host. The operator can review it. Don't try to be clever and skip endpoints to avoid auditing — there is no way to do that, and trying would betray the operator's trust.

## Sandbox topology — what to remember

- **Workspace files** (this folder): `/sandbox/.openclaw/workspace/`. OpenShell 0.0.44 consolidated the old `/sandbox/.openclaw-data/` root into `/sandbox/.openclaw/`; the `-data` path no longer exists.
- **AVIS source:** `/sandbox/avis-src/` — uploaded snapshot, not git-linked.
- **Tmp:** `/tmp/` — writable, ephemeral.
- **Network egress** is whitelisted. The default policy already permits NVIDIA inference, GitHub, npm, Brave search, etc. Anything else needs a NemoClaw policy preset.

## When you need more

- If you need to call AVIS and the integration stage is still 1, **stop and tell the operator**. Don't try to construct workarounds.
- If you need a new network endpoint, ask the operator to add a NemoClaw policy preset rather than hunting for proxy holes.
- If a tool you expected isn't here, check `openclaw skills list` first, then this file, then ask.

---

_Source of truth for "what's wired up right now." Updated whenever the integration stage advances._
