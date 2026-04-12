# 03 — Tools Reference

Every MCP tool and every REST endpoint built during the 8 stages, grouped
by tier. For each tool you get:

- **Name** — the `avis.<name>` string the agent calls via `mcporter`
- **Tier** — T1 / T2 / T3 / T4 / T5 (see [architecture.md](./01-architecture.md#tier-scheme))
- **REST equivalent** — the matching `avis-gateway` HTTP route
- **Upstream RPC** — what gRPC call it ends up making
- **Inputs / Outputs** — the shapes
- **Example** — a working `mcporter` invocation

The complete catalogue is **87 MCP tools**, spread across:

| Tier | Count | Nature |
|---|---|---|
| T1 (read-only) | 8 | No gate, audited |
| T2 (config mutation) | 6 | No gate, audited, affects avis-ml state only |
| T3-read (downstream reads, via AVIS) | 15 | No gate, audited |
| T3-gated (gated reads) | 2 | Confirmation required, for high-cost agent queries |
| T4 (central mutations) | 3 | Confirmation + operator_id + MEMORY.md log |
| T5 (physical control) | 4 | Same as T4, plus edge reachability probe first |
| T3-direct ASIAS (hybrid) | 21 | Direct HTTP to ASIAS, no gate, audited |
| T3-direct MANDATE (hybrid) | 22 | Direct HTTP to MANDATE, no gate, audited |
| T3-direct DE (hybrid) | 7 | Direct gRPC to Decision Engine, no gate, audited |

The first 37 tools (T1-T5) are **AVIS-routed** (stages 1-9). The last
50 tools are **direct** (hybrid architecture, 2026-04-12). See
[09-direct-integration.md](./09-direct-integration.md) for the hybrid
architecture rationale.

All MCP tool names are prefixed `avis.` (e.g. `avis.health`, not `health`).
REST endpoints are relative to `http://avis-gateway:8190` from the host, or
`http://avis-gateway:8090` from inside sibling containers.

---

## Calling conventions

### mcporter from the sandbox

From inside the NemoClaw sandbox (`ssh openshell-ansa-assistant`):

```bash
# Simple tools (no args)
mcporter call avis.health

# Tools with args — use --args '{json}' for typed (numeric/bool) fields
mcporter call avis.camera_pan_tilt_zoom \
  --args '{"camera_id":"LAG-001","pan":45.0,"tilt":0.0,"zoom":1.5,
           "operator_confirm":true,"operator_id":"scosaje"}'

# OR use the shorthand for string-only fields
mcporter call avis.mandate_get_incident_detail incident_id=INC-2026-001
```

**⚠️ mcporter numeric-args caveat**: mcporter's shorthand
`key=value` form passes everything as strings. For fields typed as
`f32`, `u32`, `bool`, or objects, you **must** use
`--args '{"field": value, ...}'` JSON form or rmcp will reject
the input with a type error. Stage 8 discovered this the hard way.

### REST from anywhere reachable

```bash
# Tier 1/2/3-read — no special headers
curl -s http://localhost:8190/v1/health

# Tier 3-gated / T4 / T5 — confirmation headers required
curl -s -X POST http://localhost:8190/v1/command/alert/escalate \
  -H 'content-type: application/json' \
  -H 'X-Operator-Confirm: true' \
  -H 'X-Operator-Id: scosaje' \
  -d '{"alert_id":"ALT-9999","new_priority":"HIGH","reason":"test"}'
```

The gating scheme is identical between REST and MCP — REST uses the
`X-Operator-Confirm` / `X-Operator-Id` headers; MCP uses the equivalent
fields inside the tool input object.

---

## Tier 1 — Read-only (8 tools, +1 in Stage 9)

No confirmation required. Safe to call freely. All calls are logged to
`data/avis-mcp-audit.jsonl` and `data/avis-gateway-audit.jsonl`.

### `avis.health`

Aggregated AVIS health. Calls `avis-command.CommandService.HealthCheck`.

- **REST**: `GET /v1/health`
- **Inputs**: none
- **Output**: `{"healthy": bool, "components": {"camera_controller": bool, "gateway": bool, ...}}`
- **Example**: `mcporter call avis.health`

### `avis.asr_transcribe`

Speech-to-text via `avis-ml.ASRService.Transcribe`. Audio must be base64-encoded raw PCM.

- **REST**: `POST /v1/asr/transcribe`
- **Inputs**: `{audio_base64: string, sample_rate: u32, language: string}`
- **Output**: `{text: string, confidence: f32, language: string}`

### `avis.intel_respond`

Single-shot Claude response via `avis-ml.IntelligenceService.Respond`.

- **REST**: `POST /v1/intel/respond`
- **Inputs**: `{prompt: string, temperature: f32, max_tokens: u32}`
- **Output**: `{text: string, tokens_used: u32, model: string}`

### `avis.intel_classify_intent`

Classify user intent against loaded skills. Returns type/skill_id/action/parameters/confidence.

- **REST**: `POST /v1/intel/classify-intent`
- **Inputs**: `{text: string}`
- **Output**: `{type: string, skill_id: string, action: string, parameters: object, confidence: f32}`

### `avis.dignitaries_roll_call`

Get the formal dignitary roll-call text via `DignitaryService.GetRollCall`.

- **REST**: `GET /v1/dignitaries/roll-call`
- **Inputs**: none
- **Output**: `{text: string, dignitary_count: u32, event_context: string}`

### `avis.dignitaries_find`

Fuzzy-match a spoken name against the dignitary roster.

- **REST**: `POST /v1/dignitaries/find`
- **Inputs**: `{spoken_name: string}`
- **Output**: `{matched: bool, dignitary_id: string, full_name: string, title: string, confidence: f32}`

### `avis.list_clusters` (Stage 9)

Returns the live edge-cluster registry held in `avis-command`'s memory. Lets the agent discover which clusters exist before any Tier-3/5 camera operation.

- **REST**: not exposed (MCP only)
- **Upstream**: `avis-command.CommandService.ListClusters` → `CameraController.clusters()`
- **Inputs**: none
- **Output**: `{clusters: [{id, grpc_addr, cameras}], count}`
- **Source of truth**: the `AVIS_NEMOCLAW_CLUSTERS` env var in the overlay (replaces the YAML placeholders at runtime)

```bash
mcporter call avis.list_clusters
# → {"clusters":[{"id":"edge-orin-1","grpc_addr":"192.168.200.71:30900","cameras":[]}],"count":1}
```

### `avis.events_drain` ⭐

**The Stage 7 centrepiece.** Drains the `avis-core` internal event bus of
ASIAS / SIS / AVIS events accumulated since the last call. Opens a fresh
broadcast subscription, collects events up to `limit` or until
`timeout_ms` elapses, returns them as a batch.

- **REST**: `GET /v1/events/stream` (SSE long-polling, separate protocol)
- **Upstream**: `avis-core.EventStreamService.Subscribe` (server streaming)
- **Inputs**: `{timeout_ms: u32 (default 2000), limit: u32 (default 100)}`
- **Output**: `{events: [{event_id: u64, event_kind: string, topic: string, priority: string, ts_unix_ms: i64, payload: object}], count: u32}`
- **Event kinds**: `sis.detection`, `asias.alert`, `asias.graph.association`, `mandate.workflow.*`, `mandate.incident.*`, `health_update`, `speech_detected`
- **Reasoning rules**: see [AGENTS.md](../sandbox-workspace/AGENTS.md) §SIS event reasoning loop

```bash
mcporter call avis.events_drain --args '{"timeout_ms":3000,"limit":50}'
```

---

## Tier 2 — Config mutation (6 tools)

No confirmation gate, but mutations are audited. These change `avis-ml`
state (audience mode, loaded documents, cached voice phrases). They
**do not** touch MANDATE, ASIAS, or the Decision Engine.

### `avis.intel_audience_mode`

Set Claude's audience mode: `standard` / `dignitary` / `command`.

- **REST**: `POST /v1/intel/audience-mode`
- **Inputs**: `{mode: string}` — one of `standard`, `dignitary`, `command`
- **Output**: `{accepted: bool, current_mode: string}`

### `avis.intel_objective`

Set Claude's briefing objective text.

- **REST**: `POST /v1/intel/objective`
- **Inputs**: `{objective: string}`
- **Output**: `{accepted: bool}`

### `avis.intel_load_document`

Inject a document into Claude's context for the current session.

- **REST**: `POST /v1/intel/load-document`
- **Inputs**: `{doc_id: string, content: string, content_type: string}`
- **Output**: `{accepted: bool, tokens_added: u32}`

### `avis.tts_synthesize`

Synthesize speech via `TTSService.Synthesize`. Returns base64-encoded audio.

- **REST**: `POST /v1/tts/synthesize`
- **Inputs**: `{text: string, voice_id: string, sample_rate: u32}`
- **Output**: `{audio_base64: string, duration_ms: u32, sample_rate: u32}`

### `avis.tts_preload_phrases`

Pre-cache common phrases so later calls are sub-100ms.

- **REST**: `POST /v1/tts/preload-phrases`
- **Inputs**: `{phrases: [string], voice_id: string}`
- **Output**: `{cached_count: u32}`

### `avis.voiceprint_verify`

Speaker verification via `VoicePrintService.Verify`. Returns operator identity + clearance level.

- **REST**: `POST /v1/voiceprint/verify`
- **Inputs**: `{audio_base64: string, sample_rate: u32, claimed_operator_id?: string}`
- **Output**: `{matched: bool, operator_id: string, confidence: f32, clearance: string}`

---

## Tier 3 — Downstream reads (14 tools, +1 in Stage 9)

### `avis.cluster_cameras` (Stage 9) — Camera Registry discovery

Lists cameras registered with a cluster's Camera Registry (`camreg`). Returns structured camera metadata with **credentials stripped server-side** — `user_name` and `password` are NEVER included in the response.

- **REST**: not exposed (MCP only — direct HTTP to camreg, not via avis-gateway)
- **Upstream**: HTTP `GET <camreg_url>/cameras/metadata` (camreg's FastAPI). The URL comes from the per-cluster map in `AVIS_NEMOCLAW_CAMREG_URLS`.
- **Inputs**: `{cluster_id: string, ptz_only?: bool}`
- **Output**:
  ```json
  {
    "cluster_id": "edge-orin-1",
    "cameras": [
      {
        "camera_id": "...",
        "camera_type": "PTZ|Fixed|IR|Thermal",
        "is_ptz": true,
        "latitude": 6.5244, "longitude": 3.3792,
        "geohash": null, "zone": "A",
        "status": "active|inactive",
        "ip_address": "...",
        "clan_id": "...",
        "location_description": "...",
        "cluster_id": "...",
        "timestamp": "..."
      }
    ],
    "count": 1,
    "ptz_only": true,
    "source": "camreg"
  }
  ```
- **Error variants**: `error: "camreg_unreachable"`, `error: "camreg_http_error"`, `error: "camreg_parse_error"`, or `warning: "no Camera Registry configured for this cluster"` — all return `success` shape with `cameras: []`.
- **Security invariant**: explicit field whitelist in the wrapper. Never echoes `user_name` or `password` even if camreg adds them.

```bash
mcporter call avis.cluster_cameras --args '{"cluster_id":"edge-orin-1","ptz_only":true}'
```

⚠ **Two-cameras-of-truth caveat**: each Orin cluster also runs the Decision Engine's own internal camera registry (`cameras.json` inside the DE pod) and the two are NOT synced. PTZ-capable IDs from camreg may not exist in the DE. **For PTZ to actually move a camera, use the DE's IDs (queryable via `avis.camera_status` for the cluster), not camreg's `is_ptz` flag.**

## Tier 3 — Downstream reads (existing 13 tools)

Read-only queries into MANDATE and the Decision Engine. No gate. High
information value, low blast radius. Most of these were added in Stage 5;
Decision Engine reads were added in Stage 8.

### MANDATE typed reads (10)

All wrap `avis-ml.MandateQueryService.<RPC>` which in turn wraps
MANDATE's existing voice-query REST endpoints. JSON passthrough envelope —
see discoveries.md for why we didn't map every MANDATE response into
proto.

| Tool | REST equivalent | What it returns |
|---|---|---|
| `avis.mandate_list_active_incidents` | `GET /v1/mandate/incidents/active` | Active MANDATE incidents with severity, type, state, lead agency |
| `avis.mandate_incident_metrics` | `GET /v1/mandate/incidents/metrics` | Incident counts by severity and type |
| `avis.mandate_get_incident_detail` | `GET /v1/mandate/incidents/:incident_id` | Full detail for one incident |
| `avis.mandate_list_active_workflows` | `GET /v1/mandate/workflows` | Active enforcement workflows with phase and lead agency |
| `avis.mandate_list_active_tasking` | `GET /v1/mandate/tasking/active` | Active field-unit taskings |
| `avis.mandate_dashboard_metrics` | `GET /v1/mandate/dashboard/metrics` | Top-level metrics: response times, agency workload |
| `avis.mandate_dashboard_pipeline` | `GET /v1/mandate/dashboard/pipeline` | Pipeline status (ingest → review → action → close) |
| `avis.mandate_agency_workload` | `GET /v1/mandate/dashboard/agency-workload` | Workload per Nigerian security agency (NPF, DSS, NSCDC, EFCC, NDLEA, …) |
| `avis.mandate_poi_voice_status` | `GET /v1/mandate/poi/:poi_id/status` | Workflow + approval + tasking status for a POI |
| `avis.mandate_poi_voice_incidents` | `GET /v1/mandate/poi/:poi_id/incidents` | All incidents linked to a POI |

**Inputs** for the POI / incident-detail tools: `{incident_id: string}` or
`{poi_id: string}`. All other tools take no inputs.

**Output shape** (universal envelope):
```json
{
  "payload_json": "{...raw MANDATE JSON...}",
  "count": 5,
  "http_status": 200
}
```

The agent should parse `payload_json` into a local object. The `count` is
a convenience for list-returning RPCs.

**Example**:
```bash
mcporter call avis.mandate_list_active_incidents
mcporter call avis.mandate_poi_voice_incidents poi_id=POI-2025-0042
```

### Decision Engine reads (3)

Added in Stage 8. These can return `edge_unreachable` when the edge cluster
(`192.168.200.71:9300`) isn't routable — see discoveries.md §2.

#### `avis.decision_engine_health`

Aggregated `avis-command` health including cluster reachability signals.

- **REST**: `GET /v1/decision-engine/health`
- **Upstream**: `avis-command.CommandService.HealthCheck` (cluster portion)
- **Inputs**: none
- **Output**: `{healthy: bool, clusters: [{id: string, reachable: bool}]}`

#### `avis.camera_status`

Query the Decision Engine for camera state. Either `cluster_id` or
`camera_id` is required. Returns `success:false + error:"edge_unreachable"`
when the cluster is down — this is the clean probe to run **before** any
Tier-5 call.

- **REST**: `GET /v1/decision-engine/camera/status?cluster_id=<id>&camera_id=<id>`
- **Upstream**: `avis-command.CommandService.GetCameraStatus` → `edge.CommandReceiverService.GetCameraStatus`
- **Inputs**: `{cluster_id?: string, camera_id?: string}`
- **Output** (reachable): `{success: true, cameras: [{id, state, pan, tilt, zoom, recording, retask_target}]}`
- **Output** (unreachable): `{success: false, error: "edge_unreachable", cluster_id: "<id>"}`

**Example**:
```bash
mcporter call avis.camera_status camera_id=LAG-001
```

#### `avis.tasking_status`

Query the current status of an active tasking by ID. Read-only — no gate
even though the service-name might suggest otherwise.

- **REST**: `GET /v1/command/tasking/status?tasking_id=<id>`
- **Upstream**: `avis-command.CommandService.RequestTaskingStatus`
- **Inputs**: `{tasking_id: string}`
- **Output**: `{status: string, unit_id: string, eta_seconds: u32, last_update_ts: i64}`

---

## Tier 3-gated — Gated high-cost reads (2 tools)

These tools are read-only but so expensive or side-effect-adjacent that
they use the same operator_confirm gate as Tier 4. Added in Stage 2.

### `avis.intel_agent_ask`

Query a downstream service agent through `IntelligenceService.AskAgent`.
Routes through Claude voice-synthesis for prose-formatted answers — **use
only when the operator wants a narrated answer they'll hear out loud**.
For structured data, use the typed `avis.mandate_*` tools instead
(Stage 5, cheaper and faster).

- **REST**: `POST /v1/intel/agent/ask`
- **Upstream**: `avis-ml.IntelligenceService.AskAgent`
- **Inputs**: `{agent: string, question: string, operator_confirm: bool, operator_id: string}`
  - `agent` ∈ `mandate | asias | threat`
- **Output**: `{text: string, tokens_used: u32, agent: string}`

### `avis.command_alert_create`

Dispatch a NEW alert to the AnSA Go Gateway. Creates an alert visible to
all downstream ASIAS consumers and kicks off MANDATE workflow routing.

- **REST**: `POST /v1/command/alert/create`
- **Upstream**: `avis-command.CommandService.CreateAlert` → ASIAS Go Gateway `POST /api/v1/alerts`
- **Inputs**: `{alert_type: string, severity: string, location: {...}, description: string, metadata: object, operator_confirm: bool, operator_id: string}`
- **Output**: `{alert_id: string, created_at: string, routed_to: [string]}`

---

## Tier 4 — Central mutations (3 tools)

**These tools change state in MANDATE and/or ASIAS.** They require:

1. `operator_confirm: true` AND `operator_id: <name>` in the input
2. An **explicit operator instruction in the current turn** (agent doctrine)
3. A **MEMORY.md entry** recording the call, authorisation, and outcome

If any of those three is missing, the agent must refuse. The REST/MCP
layer enforces (1); the agent enforces (2) and (3) via AGENTS.md
discipline.

### `avis.alert_escalate`

Raise an existing alert's priority. Triggers MANDATE re-routing.

- **REST**: `POST /v1/command/alert/escalate`
- **Upstream**: `avis-command.CommandService.EscalateAlert` → ASIAS Go Gateway `POST /api/v1/alerts/:id/escalate`
- **Inputs**: `{alert_id: string, new_priority: string, reason: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{success: bool, alert_id: string, previous_priority: string, new_priority: string}`

### `avis.alert_acknowledge`

Mark an alert as acknowledged (operator has seen it and taken ownership).

- **REST**: `POST /v1/command/alert/acknowledge`
- **Upstream**: `avis-command.CommandService.AcknowledgeAlert` → ASIAS Go Gateway
- **Inputs**: `{alert_id: string, operator_note: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{success: bool, alert_id: string, acknowledged_at: string}`

### `avis.tasking_dispatch` ⚠️ HIGHEST IMPACT

**The single most consequential tool in the catalogue.** Dispatches real
field units (NPF / DSS / MOPOL / NSCDC / etc.) to coordinates. Calls
ASIAS Go Gateway which puts the dispatch onto `avis.commands.tasking`
Kafka topic, which the MANDATE worker consumes.

Treat this tool like loaded weapons: only when the operator explicitly
says "dispatch", never on inference, never "to save time".

- **REST**: `POST /v1/command/tasking/dispatch`
- **Upstream**: `avis-command.CommandService.DispatchTasking` → ASIAS Go Gateway → Kafka → MANDATE worker
- **Inputs**: `{agency: string, unit_type: string, location: {lat: f64, lng: f64}, mission_type: string, priority: string, details: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{tasking_id: string, dispatched_at: string, estimated_arrival: string, agency_acknowledged: bool}`

---

## Tier 5 — Physical / edge control (4 tools)

**Moves real hardware in the physical world.** Gating is identical to
Tier 4 (same three requirements). Plus one additional rule:

- **Before calling any Tier-5 tool, run `avis.camera_status` first** to
  check if the edge cluster is even reachable. If it returns
  `edge_unreachable`, tell the operator and stop — the Tier-5 call will
  "succeed" at avis-command but be logged locally in avis-command's audit
  trail, **not actually reach the camera**. This is confusing and not
  what the operator wants.

All four Tier-5 tools wrap gRPC calls into the edge cluster's
`CommandReceiverService` running on the Jetson Orin. Only `SetPTZ` and
`GetCameraStatus` are fully implemented on the edge in v2.1.0 — the
other three return `UNIMPLEMENTED` from the edge side, and avis-command
swallows the error and returns `success: true` with a "logged locally"
message.

### `avis.camera_pan_tilt_zoom`

Pan / tilt / zoom a camera. Use `preset` OR manual `pan`/`tilt`/`zoom`,
not both.

- **REST**: `POST /v1/decision-engine/camera/ptz`
- **Upstream**: `avis-command.CommandService.PanTiltZoom` → `edge.CommandReceiverService.SetPTZ`
- **Inputs**:
  ```json
  {
    "cluster_id": "edge-1",
    "camera_id": "LAG-001",
    "preset": "",
    "pan": 45.0,
    "tilt": 0.0,
    "zoom": 1.5,
    "operator_confirm": true,
    "operator_id": "scosaje"
  }
  ```
- **Output**: `{success: bool, message: string, command_id: string}` OR `edge_unreachable` variant

### `avis.camera_start_recording`

Start recording on a camera. **Stub on edge in v2.1.0** — returns
UNIMPLEMENTED from the edge; avis-command logs locally.

- **REST**: `POST /v1/decision-engine/camera/recording/start`
- **Inputs**: `{cluster_id: string, camera_id: string, reason: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{success: bool, message: string, recording_id: string}`

### `avis.camera_stop_recording`

Stop recording on a camera. Stub on edge in v2.1.0.

- **REST**: `POST /v1/decision-engine/camera/recording/stop`
- **Inputs**: `{cluster_id: string, camera_id: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{success: bool, message: string}`

### `avis.camera_retask`

Retarget a camera to a new sector / POI / coordinates. Stub on edge in v2.1.0.

- **REST**: `POST /v1/decision-engine/camera/retask`
- **Inputs**: `{cluster_id: string, camera_id: string, target: string, reason: string, operator_confirm: bool, operator_id: string}`
- **Output**: `{success: bool, message: string}`

---

## SIS event taxonomy (from `avis.events_drain`)

When the agent calls `avis.events_drain` it receives a batch of typed
events from the AVIS internal bus. The most important class is
**SIS detections** — 17 event kinds originating on the Jetson Orin edge
cluster and routed through `ASIAS → avis-core.bridge → event_bus`.

For each SIS event type, AGENTS.md specifies the recommended reasoning
loop. Reproduced here for quick reference:

| SIS event type | Severity | Recommended reasoning loop |
|---|---|---|
| `MILITARY_THREAT` | 10 (CRITICAL) | Query `mandate_list_active_incidents` → log → notify operator. **NEVER auto-dispatch.** |
| `KIDNAPPING` | 10 | Same as MILITARY_THREAT |
| `IMMINENT_ATTACK` | 10 | Same — query, log, notify, await operator |
| `ARMED_ROBBERY` | 9 | Query `mandate_list_active_workflows` + `mandate_agency_workload` → surface with situational summary |
| `BANDITRY` | 9 | Same as ARMED_ROBBERY; also query `mandate_list_active_tasking` |
| `WEAPON_DETECTED` | 8 | Query `mandate_list_active_workflows` for POI-linked workflows near camera. Suggest escalation only on operator request. |
| `ARMS_TRAFFICKING` | 8 | Log, query `mandate_agency_workload`, surface |
| `ASSAULT` | 7 | Log. Notify only in Alert mode OR if confidence >0.9 |
| `BALLOT_BOX_SNATCHING` | 7 | Query election-security workflows. Always notify. |
| `BALLOT_BOX_STUFFING` | 7 | Same |
| `ELECTION_RIGGING` | 7 | Same |
| `ELECTION_THUGGERY` | 7 | Same; query for parallel cult activity |
| `HOME_BREAK_IN` | 5 | Log. Notify only if ≥3 within 5 km / 10 min |
| `CAR_BREAK_IN` | 5 | Same as HOME_BREAK_IN |
| `THEFT` | 4 | Log. Notify only if clustered |
| `SHOPLIFTING` | 4 | Log. Notify only if POI has active workflow |
| `SUSPICIOUS_ACTIVITY` | 4 | Buffer. Escalate only on cluster ≥3 events within 5 min / 1 km |
| `BEHAVIORAL_ANOMALY` | 4 | Same as SUSPICIOUS_ACTIVITY |

**Hard rules regardless of event type**:

1. **Gather before you speak.** Never report an event to the operator
   without first calling at least one `avis.mandate_*` read.
2. **Log everything** to MEMORY.md — event, context gathered, conclusion.
3. **Never auto-act.** Events trigger REASONING, not EXECUTION. Tier-4/5
   tools always need explicit operator instruction in the current turn.

---

---

## Direct ASIAS tools (21, Hybrid 2026-04-12)

All Tier 3 read-only. Direct HTTP via `reqwest` to ASIAS Go Gateway.
Auth: `X-Api-Key` header from `AVIS_NEMOCLAW_ASIAS_API_KEY` env var.
See [09-direct-integration.md](./09-direct-integration.md) for full details.

| Tool | Tier | Method | Endpoint | Description |
|---|---|---|---|---|
| `asias_graph_associations` | T3 | GET | `/api/v1/graph/associations` | List all graph associations |
| `asias_graph_poi_neighbors` | T3 | GET | `/api/v1/graph/poi/{poi_id}/neighbors` | POI neighbor nodes in graph |
| `asias_graph_poi_connections` | T3 | GET | `/api/v1/graph/poi/{poi_id}/connections` | All connections for a POI |
| `asias_graph_search` | T3 | GET | `/api/v1/graph/search?q={query}` | Search graph by keyword |
| `asias_graph_stats` | T3 | GET | `/api/v1/graph/stats` | Graph statistics (nodes, edges, density) |
| `asias_cross_agency_alerts` | T3 | GET | `/api/v1/cross-agency/alerts` | Cross-agency alert feed |
| `asias_cross_agency_summary` | T3 | GET | `/api/v1/cross-agency/summary` | Aggregated cross-agency summary |
| `asias_watchlist_entries` | T3 | GET | `/api/v1/watchlists` | All watchlist entries |
| `asias_watchlist_check` | T3 | GET | `/api/v1/watchlists/check/{identifier}` | Check identifier against watchlists |
| `asias_watchlist_stats` | T3 | GET | `/api/v1/watchlists/stats` | Watchlist statistics |
| `asias_poi_detail` | T3 | GET | `/api/v1/pois/{poi_id}` | Full POI detail |
| `asias_poi_timeline` | T3 | GET | `/api/v1/pois/{poi_id}/timeline` | POI event timeline |
| `asias_poi_neighbors` | T3 | GET | `/api/v1/pois/{poi_id}/neighbors` | POI neighbor entities |
| `asias_poi_risk_score` | T3 | GET | `/api/v1/pois/{poi_id}/risk` | Computed risk score for POI |
| `asias_alerts_list` | T3 | GET | `/api/v1/alerts` | List all alerts |
| `asias_alerts_detail` | T3 | GET | `/api/v1/alerts/{alert_id}` | Single alert detail |
| `asias_alerts_by_severity` | T3 | GET | `/api/v1/alerts?severity={severity}` | Alerts filtered by severity |
| `asias_health` | T3 | GET | `/health` | ASIAS Go Gateway health |
| `asias_agencies` | T3 | GET | `/api/v1/agencies` | List 14 Nigerian security agencies |
| `asias_event_types` | T3 | GET | `/api/v1/event-types` | Supported SIS event types |
| `asias_system_stats` | T3 | GET | `/api/v1/stats` | System-wide statistics |

**Example**:
```bash
mcporter call asias_graph_poi_neighbors poi_id=POI-2025-0042
mcporter call asias_watchlist_check identifier=NIN-12345678
mcporter call asias_alerts_by_severity severity=CRITICAL
```

---

## Direct MANDATE tools (22, Hybrid 2026-04-12)

All Tier 3 read-only. Direct HTTP via `reqwest` to MANDATE FastAPI.
Auth: `X-Api-Key` header from `AVIS_NEMOCLAW_MANDATE_API_KEY` env var.

| Tool | Tier | Method | Endpoint | Description |
|---|---|---|---|---|
| `mandate_incidents_active` | T3 | GET | `/api/v1/incidents?status=active` | Active incidents |
| `mandate_incidents_by_severity` | T3 | GET | `/api/v1/incidents?severity={sev}` | Incidents by severity |
| `mandate_incident_detail` | T3 | GET | `/api/v1/incidents/{incident_id}` | Full incident detail |
| `mandate_incident_timeline` | T3 | GET | `/api/v1/incidents/{incident_id}/timeline` | Incident event timeline |
| `mandate_incident_agencies` | T3 | GET | `/api/v1/incidents/{incident_id}/agencies` | Agencies on an incident |
| `mandate_workflows_active` | T3 | GET | `/api/v1/workflows?status=active` | Active enforcement workflows |
| `mandate_workflow_detail` | T3 | GET | `/api/v1/workflows/{workflow_id}` | Full workflow detail |
| `mandate_workflow_approvals` | T3 | GET | `/api/v1/workflows/{workflow_id}/approvals` | Workflow approval chain |
| `mandate_workflow_history` | T3 | GET | `/api/v1/workflows/{workflow_id}/history` | Step-by-step workflow history |
| `mandate_approvals_pending` | T3 | GET | `/api/v1/approvals?status=pending` | All pending approvals |
| `mandate_officers_on_duty` | T3 | GET | `/api/v1/officers?status=on_duty` | Officers currently on duty |
| `mandate_officer_detail` | T3 | GET | `/api/v1/officers/{officer_id}` | Officer detail |
| `mandate_officer_assignments` | T3 | GET | `/api/v1/officers/{officer_id}/assignments` | Officer assignments |
| `mandate_ews_active` | T3 | GET | `/api/v1/ews?status=active` | Active early warning signals |
| `mandate_ews_by_region` | T3 | GET | `/api/v1/ews?region={region}` | EWS by region |
| `mandate_ews_detail` | T3 | GET | `/api/v1/ews/{ews_id}` | EWS signal detail |
| `mandate_orgs_list` | T3 | GET | `/api/v1/organisations` | All MANDATE organisations |
| `mandate_org_detail` | T3 | GET | `/api/v1/organisations/{org_id}` | Organisation detail |
| `mandate_org_incidents` | T3 | GET | `/api/v1/organisations/{org_id}/incidents` | Organisation incidents |
| `mandate_dashboard_overview` | T3 | GET | `/api/v1/dashboard/overview` | Dashboard overview metrics |
| `mandate_dashboard_agency_load` | T3 | GET | `/api/v1/dashboard/agency-workload` | Per-agency workload |
| `mandate_dashboard_pipeline` | T3 | GET | `/api/v1/dashboard/pipeline` | Pipeline status |

**Example**:
```bash
mcporter call mandate_incidents_active
mcporter call mandate_incident_timeline incident_id=INC-2026-001
mcporter call mandate_approvals_pending
mcporter call mandate_ews_by_region region=North-East
mcporter call mandate_officers_on_duty
```

---

## Direct Edge DE tools (7, Hybrid 2026-04-12)

All Tier 3 read-only. Direct gRPC via `tonic` to Decision Engine on
edge clusters. Auth: unauthenticated (cluster-local). Uses the
`EdgeRegistry` component with lazy channels and async background health
probing. See [09-direct-integration.md](./09-direct-integration.md#edgeregistry)
for architecture details.

| Tool | Tier | gRPC RPC | Description |
|---|---|---|---|
| `de_health` | T3 | `CommandReceiverService.HealthCheck` | DE health per cluster |
| `de_camera_status` | T3 | `CommandReceiverService.GetCameraStatus` | Camera state (authoritative for PTZ) |
| `de_cameras_list` | T3 | `CommandReceiverService.ListCameras` | All DE-known cameras on a cluster |
| `de_detection_feed` | T3 | `CommandReceiverService.GetDetectionFeed` | Recent detection events |
| `de_cluster_health` | T3 | `CommandReceiverService.ClusterHealth` | Aggregated cluster health (GPU, memory) |
| `de_zones_list` | T3 | `CommandReceiverService.ListZones` | Security zones on cluster |
| `de_zone_cameras` | T3 | `CommandReceiverService.GetZoneCameras` | Cameras in a specific zone |

**Example**:
```bash
mcporter call de_health cluster_id=edge-orin-1
mcporter call de_camera_status --args '{"cluster_id":"edge-orin-1","camera_id":"cam64"}'
mcporter call de_detection_feed cluster_id=edge-orin-1
mcporter call de_zones_list cluster_id=edge-orin-1
```

---

## Audit trail

Every tool call — regardless of tier — writes a JSONL line to:

- **MCP side**: `~/claude-projects/ansa-voice-intelligence-system/data/avis-mcp-audit.jsonl`
- **REST side**: `~/claude-projects/ansa-voice-intelligence-system/data/avis-gateway-audit.jsonl`

Each line carries:
```json
{
  "ts": "2026-04-07T04:12:33.142Z",
  "tier": 4,
  "tool": "avis.alert_escalate",
  "operator_id": "scosaje",
  "confirm": true,
  "upstream_status": "ok",
  "latency_ms": 147,
  "request_hash": "sha256:..."
}
```

See [runbook.md](./04-runbook.md#inspecting-audit-logs) for grep and
tail commands.
