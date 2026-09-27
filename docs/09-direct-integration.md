# 09 — Direct ASIAS / MANDATE / DE Integration (Hybrid Architecture)

**Date**: 2026-04-12
**What changed**: 50 new MCP tools added via a hybrid architecture that
bypasses AVIS for Tier-3 reads while keeping Tier-4 mutations routed
through AVIS. Total tool count: **87 MCP tools**.

---

## Why direct?

The original Stages 1-8 architecture routed **every** call through AVIS:
agent -> avis-mcp -> avis-gateway -> avis-command -> downstream service.
This was correct for Tier-4/5 mutations (data sovereignty, audit trail,
operator gating) but added unnecessary latency for read-only Tier-3
queries.

The hybrid architecture introduced on 2026-04-12 adds a second path:

- **Tier-3 reads** go directly from `avis-mcp` to the downstream
  service (ASIAS, MANDATE, or Decision Engine). Faster, fewer hops,
  same audit trail.
- **Tier-4 mutations** continue through AVIS. No change to the gating
  protocol, no change to the sovereignty invariant for writes.

This gives the agent sub-100ms reads on ASIAS graph queries and
MANDATE incident lookups, while keeping every mutation under the same
operator-confirm gating as before.

---

## Hybrid architecture diagram

```
                    NemoClaw Sandbox (ansa-assistant)
                    ┌─────────────────────────────┐
                    │  mcporter call avis.<tool>   │
                    └─────────────┬───────────────┘
                                  │
                           avis-mcp:8091
                    ┌─────────────┴───────────────┐
                    │         avis-mcp (Rust)       │
                    │                               │
                    │  ┌─────────┐  ┌────────────┐ │
                    │  │ T3 reads│  │T4 mutations │ │
                    │  │ (direct)│  │(via AVIS)   │ │
                    │  └────┬────┘  └──────┬─────┘ │
                    └───────┼──────────────┼───────┘
                            │              │
               ┌────────────┼──────┐       │
               │            │      │       │
               ▼            ▼      ▼       ▼
         ┌──────────┐ ┌────────┐ ┌───┐ ┌────────────┐
         │  ASIAS   │ │MANDATE │ │ DE│ │avis-gateway │
         │ Go GW    │ │  API   │ │gRPC│ │  → avis-   │
         │ :8010    │ │ :8001  │ │:309│ │  command    │
         └──────────┘ └────────┘ │00  │ └────────────┘
                                 └───┘

  Legend:
    ─── T3 direct path (reqwest HTTP / tonic gRPC)
    ─── T4 path through AVIS (unchanged from stages 1-8)
```

### What each path carries

| Path | Tools | Transport | Auth | Audit |
|---|---|---|---|---|
| Direct ASIAS | 21 `asias_*` tools | HTTP (reqwest) to Go Gateway `:8010` | `X-Api-Key: <key>` header | avis-mcp audit log |
| Direct MANDATE | 22 `mandate_*` tools | HTTP (reqwest) to mandate-api `:8001` | `X-Api-Key: <key>` header | avis-mcp audit log |
| Direct DE | 7 `de_*` tools | gRPC (tonic) to edge NodePort `:30900` | Unauthenticated (cluster-local) | avis-mcp audit log |
| Via AVIS (T4) | Existing 37 `avis.*` tools | MCP -> gateway -> command -> downstream | operator_confirm + operator_id | Both MCP + gateway logs |

---

## Direct ASIAS tools (21 tools)

All tools are **Tier 3** (read-only, no gate, audited). They query the
ASIAS Go Gateway directly via HTTP using the `reqwest` client inside
`avis-mcp`.

### Auth

Every request carries `X-Api-Key: <key>` where the key comes from
`AVIS_NEMOCLAW_ASIAS_API_KEY` env var. Default in dev: `devkey`.

### Graph & association tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_graph_associations` | GET | `/api/v1/graph/associations` | List all graph associations in ASIAS |
| `asias_graph_poi_neighbors` | GET | `/api/v1/graph/poi/{poi_id}/neighbors` | Get POI neighbor nodes in the ASIAS graph |
| `asias_graph_poi_connections` | GET | `/api/v1/graph/poi/{poi_id}/connections` | Get all connections for a POI in the graph |
| `asias_graph_search` | GET | `/api/v1/graph/search?q={query}` | Search the ASIAS graph by keyword |
| `asias_graph_stats` | GET | `/api/v1/graph/stats` | Graph statistics (node/edge counts, density) |

### Cross-agency tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_cross_agency_alerts` | GET | `/api/v1/cross-agency/alerts` | Cross-agency alert feed |
| `asias_cross_agency_summary` | GET | `/api/v1/cross-agency/summary` | Aggregated cross-agency summary |

### Watchlist tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_watchlist_entries` | GET | `/api/v1/watchlists` | List all watchlist entries |
| `asias_watchlist_check` | GET | `/api/v1/watchlists/check/{identifier}` | Check if an identifier is on any watchlist |
| `asias_watchlist_stats` | GET | `/api/v1/watchlists/stats` | Watchlist statistics |

### POI & timeline tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_poi_detail` | GET | `/api/v1/pois/{poi_id}` | Full POI detail from ASIAS |
| `asias_poi_timeline` | GET | `/api/v1/pois/{poi_id}/timeline` | Event timeline for a specific POI |
| `asias_poi_neighbors` | GET | `/api/v1/pois/{poi_id}/neighbors` | POI neighbor entities (alias of graph neighbor view) |
| `asias_poi_risk_score` | GET | `/api/v1/pois/{poi_id}/risk` | Computed risk score for a POI |

### Alert tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_alerts_list` | GET | `/api/v1/alerts` | List all alerts in ASIAS |
| `asias_alerts_detail` | GET | `/api/v1/alerts/{alert_id}` | Detail for a single alert |
| `asias_alerts_by_severity` | GET | `/api/v1/alerts?severity={severity}` | Filter alerts by severity level |

### System tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `asias_health` | GET | `/health` | ASIAS Go Gateway health check |
| `asias_agencies` | GET | `/api/v1/agencies` | List all 14 Nigerian security agencies |
| `asias_event_types` | GET | `/api/v1/event-types` | List supported SIS event types |
| `asias_system_stats` | GET | `/api/v1/stats` | System-wide statistics |

### Example calls

```bash
# Graph neighbors for a POI
mcporter call asias_graph_poi_neighbors poi_id=POI-2025-0042

# Search the graph
mcporter call asias_graph_search query=trafficking

# Check watchlist
mcporter call asias_watchlist_check identifier=NIN-12345678

# POI timeline
mcporter call asias_poi_timeline poi_id=POI-2025-0042

# Alerts by severity
mcporter call asias_alerts_by_severity severity=CRITICAL
```

---

## Direct MANDATE tools (22 tools)

All tools are **Tier 3** (read-only, no gate, audited). They query
MANDATE's FastAPI directly via HTTP using the `reqwest` client.

### Auth

Every request carries `X-Api-Key: <key>` where the key comes from
`AVIS_NEMOCLAW_MANDATE_API_KEY` env var. Default in dev: `devkey`.

**Note**: the hardcoded fallback API key was removed during the code
review on 2026-04-12. If the env var is unset, tools return an
explicit `config_error` rather than silently using a fallback.

### Incident tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_incidents_active` | GET | `/api/v1/incidents?status=active` | All active incidents |
| `mandate_incidents_by_severity` | GET | `/api/v1/incidents?severity={sev}` | Incidents filtered by severity |
| `mandate_incident_detail` | GET | `/api/v1/incidents/{incident_id}` | Full detail for one incident |
| `mandate_incident_timeline` | GET | `/api/v1/incidents/{incident_id}/timeline` | Event timeline for an incident |
| `mandate_incident_agencies` | GET | `/api/v1/incidents/{incident_id}/agencies` | Agencies assigned to an incident |

### Workflow tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_workflows_active` | GET | `/api/v1/workflows?status=active` | All active enforcement workflows |
| `mandate_workflow_detail` | GET | `/api/v1/workflows/{workflow_id}` | Full detail for one workflow |
| `mandate_workflow_approvals` | GET | `/api/v1/workflows/{workflow_id}/approvals` | Approval chain for a workflow |
| `mandate_workflow_history` | GET | `/api/v1/workflows/{workflow_id}/history` | Step-by-step workflow history |

### Approval & officer tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_approvals_pending` | GET | `/api/v1/approvals?status=pending` | All pending approvals |
| `mandate_officers_on_duty` | GET | `/api/v1/officers?status=on_duty` | Officers currently on duty |
| `mandate_officer_detail` | GET | `/api/v1/officers/{officer_id}` | Detail for one officer |
| `mandate_officer_assignments` | GET | `/api/v1/officers/{officer_id}/assignments` | Current assignments for an officer |

### Early Warning System (EWS) tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_ews_active` | GET | `/api/v1/ews?status=active` | Active early warning signals |
| `mandate_ews_by_region` | GET | `/api/v1/ews?region={region}` | EWS signals filtered by region |
| `mandate_ews_detail` | GET | `/api/v1/ews/{ews_id}` | Detail for one EWS signal |

### Organisation tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_orgs_list` | GET | `/api/v1/organisations` | List all organisations in MANDATE |
| `mandate_org_detail` | GET | `/api/v1/organisations/{org_id}` | Detail for one organisation |
| `mandate_org_incidents` | GET | `/api/v1/organisations/{org_id}/incidents` | Incidents linked to an organisation |

### Dashboard tools

| Tool | Method | Endpoint | Description |
|---|---|---|---|
| `mandate_dashboard_overview` | GET | `/api/v1/dashboard/overview` | Top-level dashboard metrics |
| `mandate_dashboard_agency_load` | GET | `/api/v1/dashboard/agency-workload` | Workload per agency |
| `mandate_dashboard_pipeline` | GET | `/api/v1/dashboard/pipeline` | Pipeline status (ingest -> action -> close) |

### Example calls

```bash
# Active incidents
mcporter call mandate_incidents_active

# Incident timeline
mcporter call mandate_incident_timeline incident_id=INC-2026-001

# Pending approvals
mcporter call mandate_approvals_pending

# Officers on duty
mcporter call mandate_officers_on_duty

# Early warning signals by region
mcporter call mandate_ews_by_region region=North-East

# Organisation detail
mcporter call mandate_org_detail org_id=NPF
```

---

## Direct Edge Decision Engine tools (7 tools)

These tools query the Decision Engine on edge clusters **directly via
gRPC** using `tonic` channels. Unlike the AVIS-routed camera tools
(which go through `avis-command`), these connect to edge NodePorts
without an intermediary.

### EdgeRegistry

The `EdgeRegistry` is a new component in `avis-mcp` that manages gRPC
channel pools to edge clusters. Key design:

- **Lazy channels**: connections are established on first use, not at
  startup. No overhead for clusters that are never queried.
- **Async background health probe**: a tokio task periodically pings
  each registered cluster (every 30 seconds). Probe results are cached
  and surfaced to callers without blocking the tool call.
- **Cluster source**: the registry reads `AVIS_NEMOCLAW_CLUSTERS` env
  var (JSON array of `{id, grpc_addr, cameras}` objects).

### Auth

Decision Engine gRPC is **unauthenticated** (cluster-local traffic on
the Kubernetes pod network, exposed via NodePort for the PoC). The
NodePort at `30900` was added by the NemoClaw k8s overlay; since
2026-09-27 it is defined in the decision-service repo
(`k8s/deployment-v2.yaml`). Caller auth (`x-api-key`) exists there but is
off unless the decision service sets `ENABLE_GRPC_AUTH=true`.

### Tool catalogue

| Tool | Tier | gRPC RPC | Description |
|---|---|---|---|
| `de_health` | T3 | `CommandReceiverService.HealthCheck` | DE health per cluster |
| `de_camera_status` | T3 | `CommandReceiverService.GetCameraStatus` | Camera state from DE (authoritative for PTZ) |
| `de_cameras_list` | T3 | `CommandReceiverService.ListCameras` | All cameras known to the DE on a cluster |
| `de_detection_feed` | T3 | `CommandReceiverService.GetDetectionFeed` | Recent detection events from DE |
| `de_cluster_health` | T3 | `CommandReceiverService.ClusterHealth` | Aggregated cluster health (GPU, memory, pipeline) |
| `de_zones_list` | T3 | `CommandReceiverService.ListZones` | Security zones configured on the cluster |
| `de_zone_cameras` | T3 | `CommandReceiverService.GetZoneCameras` | Cameras assigned to a specific zone |

### Example calls

```bash
# DE health for a specific cluster
mcporter call de_health cluster_id=edge-orin-1

# Camera status (authoritative for PTZ-capable cameras)
mcporter call de_camera_status --args '{"cluster_id":"edge-orin-1","camera_id":"cam64"}'

# Recent detection feed
mcporter call de_detection_feed cluster_id=edge-orin-1

# List zones
mcporter call de_zones_list cluster_id=edge-orin-1
```

### Background health probe

The EdgeRegistry spawns a background tokio task on startup:

```
every 30s:
  for each cluster in registry:
    try gRPC HealthCheck(timeout=5s)
    update cluster.reachable = true/false
    update cluster.last_probe_ts
```

When a `de_*` tool is called, it checks `cluster.reachable` first. If
`false`, it returns a structured error immediately without attempting
the actual RPC, saving the caller the 5-second gRPC timeout.

---

## Environment variables

| Variable | Service | Purpose | Default |
|---|---|---|---|
| `AVIS_NEMOCLAW_ASIAS_URL` | avis-mcp | Base URL for direct ASIAS HTTP calls | `http://host.docker.internal:8010` |
| `AVIS_NEMOCLAW_ASIAS_API_KEY` | avis-mcp | API key for ASIAS `X-Api-Key` header | _(none, required)_ |
| `AVIS_NEMOCLAW_MANDATE_URL` | avis-mcp | Base URL for direct MANDATE HTTP calls | `http://host.docker.internal:8001` |
| `AVIS_NEMOCLAW_MANDATE_API_KEY` | avis-mcp | API key for MANDATE `X-Api-Key` header | _(none, required)_ |
| `AVIS_NEMOCLAW_CLUSTERS` | avis-mcp, avis-command | JSON array of edge cluster definitions | `[]` |

These are set in `docker-compose.nemoclaw.yml` (the overlay file). They
are only present when the NemoClaw overlay is active. Base AVIS config
has no knowledge of these variables.

---

## Policy presets

Two new NemoClaw policy presets were added to allow the sandbox to
reach ASIAS and MANDATE directly:

### `asias-direct.yaml`

```yaml
# ~/NemoClaw/nemoclaw-blueprint/policies/presets/asias-direct.yaml
egress:
  allow:
    - host: "host.docker.internal"
      port: 8010
      protocol: http
      description: "Direct ASIAS Go Gateway access for T3 reads"
```

### `mandate-direct.yaml`

```yaml
# ~/NemoClaw/nemoclaw-blueprint/policies/presets/mandate-direct.yaml
egress:
  allow:
    - host: "host.docker.internal"
      port: 8001
      protocol: http
      description: "Direct MANDATE API access for T3 reads"
```

Apply during onboard:

```bash
./nemoclaw onboard \
  --policy nemoclaw-blueprint/policies/presets/avis.yaml \
  --policy nemoclaw-blueprint/policies/presets/avis-mcp.yaml \
  --policy nemoclaw-blueprint/policies/presets/asias-direct.yaml \
  --policy nemoclaw-blueprint/policies/presets/mandate-direct.yaml \
  --agent ansa-assistant
```

### Inference policy presets

See [10-nemoclaw-upgrade.md](./10-nemoclaw-upgrade.md) for the
`nvidia-api.yaml` and `ollama-inference.yaml` presets.

---

## Security measures

### `validate_id()` — path injection prevention

All tools that accept ID parameters (e.g. `poi_id`, `incident_id`,
`workflow_id`, `officer_id`) pass the value through `validate_id()`
before constructing the URL:

```rust
fn validate_id(id: &str) -> Result<&str, ToolError> {
    if id.is_empty() {
        return Err(ToolError::InvalidInput("ID cannot be empty".into()));
    }
    if id.contains('/') || id.contains('\\') || id.contains("..") 
       || id.contains('\0') || id.contains('%') {
        return Err(ToolError::InvalidInput(
            "ID contains invalid characters".into()
        ));
    }
    Ok(id)
}
```

This prevents URL path traversal (e.g. `poi_id=../../admin/config`)
from reaching the downstream service.

### HTTP status checking

All direct HTTP tools check the response status before parsing:

```rust
let resp = client.get(url).header("X-Api-Key", &api_key).send().await?;
if !resp.status().is_success() {
    return Err(ToolError::UpstreamError {
        service: "asias",
        status: resp.status().as_u16(),
        body: resp.text().await.unwrap_or_default(),
    });
}
```

Non-2xx responses are returned as structured errors with the HTTP
status code and (sanitized) body, not silently swallowed.

### Shared HTTP helpers

Two shared helper functions reduce duplication and enforce consistent
patterns across all 43 HTTP-based direct tools:

- **`http_get(url, api_key)`** — GET with `X-Api-Key` header, status
  check, JSON parse, audit log entry
- **`http_mutate(method, url, api_key, body)`** — POST/PUT/PATCH with
  same checks (used only by T4 tools routed through AVIS, not direct)

### Query parameter encoding

Query parameters are encoded using `urlencoding::encode()` before
interpolation into URLs. This prevents query injection attacks:

```rust
let encoded_query = urlencoding::encode(query);
let url = format!("{}/api/v1/graph/search?q={}", base_url, encoded_query);
```

### Credential handling

- API keys are read from env vars at startup, not per-request
- No API key is logged in the audit trail
- The hardcoded MANDATE API key fallback was **removed** during code
  review. Missing env var = explicit config error, not silent fallback
- ASIAS auth header changed from `Authorization: Bearer <key>` to
  `X-Api-Key: <key>` after discovering ASIAS uses the simpler scheme

### Sanitized error messages

Error messages returned to the agent never include:
- Raw API keys or credentials
- Internal IP addresses (beyond the cluster_id label)
- Stack traces from downstream services
- Full request/response bodies (truncated to 500 chars)

---

## Code review findings and fixes (2026-04-12)

The following issues were identified during code review and fixed in
the same session:

| # | Finding | Fix |
|---|---|---|
| 1 | No URL path injection prevention | Added `validate_id()` to all tools accepting ID parameters |
| 2 | HTTP status not checked on all tools | Added `.status().is_success()` check to every HTTP call |
| 3 | Query parameters not URL-encoded | Added `urlencoding::encode()` on all query parameter values |
| 4 | Hardcoded MANDATE API key fallback | Removed fallback; missing env var returns config_error |
| 5 | Inconsistent audit status strings | Standardized to `"ok"`, `"error"`, `"upstream_error"`, `"config_error"` |
| 6 | Duplicate code across HTTP tools | Extracted `http_get()` and `http_mutate()` shared helpers |
| 7 | ASIAS auth header wrong scheme | Changed from `Authorization: Bearer` to `X-Api-Key` |

---

## Relationship to existing AVIS-routed tools

The direct tools **do not replace** the existing `avis.*` tools from
stages 1-8. Both paths coexist:

| Use case | Preferred path | Why |
|---|---|---|
| Quick ASIAS graph query | `asias_graph_*` (direct) | Faster, no AVIS hop |
| Quick MANDATE incident lookup | `mandate_incident_*` (direct) | Faster, no AVIS hop |
| Edge DE camera status | `de_camera_status` (direct) | Background probe, lazy channels |
| Alert escalation (T4) | `avis.alert_escalate` (via AVIS) | Operator gating, sovereignty |
| PTZ camera control (T5) | `avis.camera_pan_tilt_zoom` (via AVIS) | Physical control needs full audit chain |
| Narrated MANDATE answer | `avis.intel_agent_ask` (via AVIS) | Goes through Claude voice synthesis |
| Live event stream | `avis.events_drain` (via AVIS) | Centralized event bus in avis-core |

The naming convention distinguishes them:
- `avis.*` — routed through AVIS (stages 1-9)
- `asias_*` — direct to ASIAS Go Gateway
- `mandate_*` — direct to MANDATE API
- `de_*` — direct to Decision Engine gRPC

---

_Added 2026-04-12. See [03-tools-reference.md](./03-tools-reference.md) for the
complete 87-tool catalogue._
