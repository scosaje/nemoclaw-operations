# 01 — Architecture

## The AnSA context

**AnSA** (Autonomous National Security Architecture) is Nigeria's
AI-driven national security platform, developed by **Inspired Technologies
Limited (ITL)** in Abuja. It is designed around five main subsystems,
four of which exist as mature codebases on this dev host. This project
integrated a fifth — a **NemoClaw-sandboxed AI agent** — as a first-class
participant in the stack.

### The five subsystems

1. **SIS — Security Intelligence System**
   `~/claude-projects/security-intelligence-system/`
   Runs on a 5-node Jetson Orin AGX edge cluster (`192.168.200.71-79`).
   Rust detection pipeline (YOLO, face embedding, military detection) +
   Go orchestrator (Claude/Ollama reasoning). Publishes **17 event
   types** (WEAPON_DETECTED, KIDNAPPING, BANDITRY, MILITARY_THREAT, …) to
   ASIAS via gRPC. One-way push with a PostgreSQL-backed retry buffer.

2. **ASIAS — AnSA Security Intelligence Aggregation Service**
   `~/claude-projects/asias-codes/`
   Multi-language central platform (Go gateway, Rust ingest, Python
   orchestrator, Neo4j graph, Temporal alerting, 14+ containers).
   Receives SIS events, runs the 13-agency routing pipeline, publishes
   via WebSocket to downstream subscribers (including `avis-core`), and
   exposes a REST API for alert CRUD.

3. **MANDATE — Mission Authority, Notification, Dispatch & Action Tracking Engine**
   `~/claude-projects/mandate/`
   Python + Temporal workflow engine. 12 Temporal workflows, 16 SIS
   event types including MILITARY_THREAT, 37 Nigerian states + 774 LGAs
   geolocation. REST API on `mandate-api:8001` with both Bearer JWT and
   `X-Api-Key` service auth. 1013+ backend tests.

4. **Decision Engine**
   `~/claude-projects/decision-service-cpu-v1.2.0-dev/`
   C++17 edge service on the Jetson cluster (`192.168.200.71:9300`).
   gRPC `CommandReceiverService` with `SetPTZ`, `GetCameraStatus`, and
   `HealthCheck` implemented. Recording and retask are stubs. NATS
   JetStream for face detection events.

5. **AVIS — AnSA Voice Intelligence System** (codename HERALD)
   `~/claude-projects/ansa-voice-intelligence-system/`
   Three services:
   - `avis-ml` — Python gRPC server on `:50051`, hosts ASR, TTS,
     Intelligence (Claude Opus 4.7, 1M context), Dignitary, Presentation, and
     VoicePrint services. Also hosts the new `MandateQueryService`
     introduced in Stage 5.
   - `avis-command` — Rust gRPC server on `:50052`, outbound action
     router: calls the Decision Engine via gRPC, the ASIAS Go Gateway
     via REST, and Kafka for tasking.
   - `avis-core` — Rust orchestrator, audio pipeline, ASIAS WebSocket
     bridge. Now also hosts the new `EventStreamService` gRPC server on
     `:50053` introduced in Stage 7.

AVIS is designed to be the **voice system** for AnSA operators: listen
to a human operator, think with Claude, act via `avis-command`, respond
with TTS. The NemoClaw integration makes AVIS also the **agent conduit**:
everything a NemoClaw agent does to drive AnSA passes through AVIS code.

## The NemoClaw bridge (what we built)

Three new services sit alongside AVIS and expose its surface to a
NemoClaw/OpenClaw sandbox agent:

```
┌──────────────────────────────────────────────────────────────────┐
│                    NemoClaw sandbox (ansa-assistant)              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │    AnSA Supervisor Agent (nvidia/nemotron-3-ultra-550b)    │  │
│  │    Workspace: SOUL.md, AGENTS.md, TOOLS.md, MEMORY.md      │  │
│  │                                                              │  │
│  │    Tools: 34 MCP tools via `mcporter call avis.<tool>`      │  │
│  │           + `web.fetch` / `web.search` (OpenClaw built-in) │  │
│  └──────────────────────────────────────────────────────────┬─┘  │
│                                                             │    │
│  Sandbox network policy: 2 presets (`avis`, `avis-mcp`)      │    │
│  allowed_ips: 172.23.0.0/16 (AVIS docker bridge)            │    │
│  host: avis-mcp:8091, avis-gateway:8090 (internal ports)     │    │
└─────────────────────────────────────────┬────────────────────┘    │
                                          │                         │
                            HTTP / MCP streamable-http               │
                                          ▼                         │
┌──────────────────────────────────────────────────────────────────┐
│               AVIS NemoClaw bridge services (NEW)                │
│                                                                  │
│  ┌──────────────────┐           ┌──────────────────┐            │
│  │   avis-gateway   │           │     avis-mcp     │            │
│  │   (Rust, axum)   │           │ (Rust, rmcp 0.16)│            │
│  │   host:8190      │           │   host:8091      │            │
│  │   40+ REST endpts│           │  34 MCP tools    │            │
│  └─────────┬────────┘           └─────────┬────────┘            │
│            │                              │                     │
│            │  independent tonic clients per service             │
│            └──────────────┬───────────────┘                      │
│                           │                                     │
│                ┌──────────┴──────────┐                           │
│                ▼                     ▼                           │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────┐ │
│  │     avis-ml      │   │  avis-command    │   │  avis-core   │ │
│  │ :50051 (Python)  │   │ :50052 (Rust)    │   │ :50053 (NEW) │ │
│  │                  │   │                  │   │              │ │
│  │ ASR, TTS, Intel, │   │ PTZ, Recording,  │   │ EventStream  │ │
│  │ Dignitary, ...   │   │ Alert, Tasking,  │   │ gRPC server  │ │
│  │ MandateQuery(NEW)│   │ GetCameraStatus  │   │ (NEW stage 7)│ │
│  └────────┬─────────┘   │ (NEW stage 8)    │   │              │ │
│           │             └────────┬─────────┘   └──────┬───────┘ │
└───────────┼──────────────────────┼──────────────────────┼───────┘
            │                      │                      │
            │                      │                      │ ASIAS WS bridge
            ▼                      ▼                      ▼ subscribes here
   ┌──────────────┐       ┌─────────────────┐    ┌─────────────────┐
   │ mandate-api  │       │ asias-go-gateway│    │ asias-go-gateway│
   │ :8001        │       │ :8010 (alerts,  │    │ /ws/events (WS  │
   │ 10 voice     │       │  tasking REST)  │    │  broadcast from │
   │ endpoints    │       │                 │    │  ASIAS pipeline)│
   └──────────────┘       └─────────────────┘    └─────────────────┘
            │                      │                      │
            │ MANDATE               │ Go Gateway +          │ SIS events flow
            │ PostgreSQL +          │ Kafka + Mandate       │ through this
            │ Temporal              │ workflow              │ WebSocket
            ▼                      ▼                      │
   ┌──────────────┐       ┌─────────────────┐              │
   │ 12 Temporal  │       │ Decision Engine │              │
   │ workflows    │       │ (edge cluster,  │              │
   │              │       │  192.168.200.71)│              │
   └──────────────┘       └─────────────────┘              │
                                   ▲                        │
                                   │                        │
                          gRPC (port 9300)                  │
                          PTZ, CameraStatus,                │
                          HealthCheck                       │
                                   │                        │
                          ┌─────────────────┐              │
                          │       SIS       │──────────────┘
                          │ (edge cluster,  │
                          │  Jetson Orin AGX)│  gRPC push to
                          │ Rust + Go       │  ASIAS EventService
                          │                 │
                          │ 17 event types  │
                          └─────────────────┘
```

### New components introduced by this project

| Component | Repo | Lines of code | Purpose |
|---|---|---|---|
| `avis-gateway/` (new crate) | `ansa-voice-intelligence-system` | ~1500 | REST gateway (axum + tonic). 40+ endpoints across 5 tiers. |
| `avis-mcp/` (new crate) | `ansa-voice-intelligence-system` | ~1500 | MCP server (rmcp 0.16 streamable-http). 34 MCP tools. |
| `avis-core/src/grpc_server/` (new module) | `ansa-voice-intelligence-system` | ~260 | `EventStreamService.Subscribe` — exposes internal event bus. |
| `avis-ml/src/avis_ml/mandate_query_servicer.py` (new file) | `ansa-voice-intelligence-system` | ~130 | `MandateQueryService` gRPC servicer, wraps MandateAgent HTTP. |
| `proto/event_stream.proto` (new) | `ansa-voice-intelligence-system` | ~65 | Event streaming schema. |
| `proto/mandate_query.proto` (new) | `ansa-voice-intelligence-system` | ~50 | MANDATE read schema (10 RPCs). |
| `proto/command.proto` (edited additively) | `ansa-voice-intelligence-system` | +30 | Added `GetCameraStatus` RPC + 3 messages. |
| `docker-compose.nemoclaw.yml` (new overlay) | `ansa-voice-intelligence-system` | ~50 | Compose overlay for NemoClaw integration. Additive. |
| `NemoClaw/nemoclaw-blueprint/policies/presets/avis.yaml` (new) | `NemoClaw` | ~50 | Sandbox policy for REST gateway access. |
| `NemoClaw/nemoclaw-blueprint/policies/presets/avis-mcp.yaml` (new) | `NemoClaw` | ~40 | Sandbox policy for MCP server access. |
| `nemoclaw_operations/sandbox-workspace/` (new) | `nemoclaw_operations` | ~400 | 6 workspace files (SOUL, AGENTS, TOOLS, IDENTITY, USER, MEMORY). |

### Modified components (additive only)

| File | Repo | Change | Isolation note |
|---|---|---|---|
| `avis-ml/src/avis_ml/agents/mandate_agent.py` | avis | 12 lines: read `AVIS_MANDATE_BASE_URL` / `AVIS_MANDATE_API_KEY` env vars | Backward compatible — unset → identical behaviour |
| `avis-command/src/config.rs` | avis | 10 lines: read `AVIS_GATEWAY_BASE_URL` / `AVIS_GATEWAY_API_KEY` env vars | Same |
| `avis-command/src/main.rs` | avis | 6 lines: bind address `[::1]` → `[::]` | Real bugfix (sibling containers were unreachable) |
| `avis-command/src/camera/cluster_client.rs` | avis | 3 lines: add `.connect_timeout(...)` | Real bugfix (unreachable clusters hung for 60s) |
| `avis-command/src/camera/mod.rs` | avis | ~60 lines: new `get_camera_status` method propagating unreachable error | Additive — new method alongside existing ones |
| `avis-command/src/service.rs` | avis | ~25 lines: `get_camera_status` gRPC handler | Additive |
| `avis-core/src/main.rs` | avis | ~50 lines: env var reads, early ASIAS bridge spawn, gRPC server spawn | Additive |
| `avis-core/Cargo.toml` | avis | 1 line: add `tokio-stream = "0.1"` | Additive |
| `avis-core/build.rs` | avis | 10 lines: second `tonic_build::configure()` block for server proto | Additive |
| `avis-ml/serve.py` | avis | 8 lines: register new MandateQueryServicer | Additive |
| `avis-ml/docker/Dockerfile.ml` | avis | 2 lines: compile new proto + sed fix | Additive |

**Unchanged** (this is the isolation invariant):
- `config/avis.yaml`
- `config/avis-command.yaml`
- `orchestrator.rs::startup_sequence()` (the existing startup flow)
- Any file in `asias-codes/`, `mandate/`, `security-intelligence-system/`, `decision-service-cpu-v1.2.0-dev/`

## The 5-tier authorisation scheme {#tier-scheme}

We organised every exposed tool into five tiers, each with progressively
stricter gating. This is the most important conceptual idea in the
integration, and it is encoded in prose in `sandbox-workspace/AGENTS.md`
so the agent reads and respects it on every session startup.

| Tier | Name | Gate | Examples |
|---|---|---|---|
| **T1** | Read-only inference | None | `health`, `intel_classify_intent`, `dignitaries_roll_call`, `events_drain`, `decision_engine_health` |
| **T2** | Config / context mutation | None (audited) | `intel_audience_mode`, `intel_objective`, `intel_load_document`, `tts_synthesize`, `voiceprint_verify` |
| **T3** | Downstream reads | None (audited) | 10 × `mandate_*` read tools, `tasking_status`, `camera_status` |
| **T4** | Downstream central mutations | `operator_confirm: true` + `operator_id` + MEMORY.md entry + explicit operator instruction | `alert_create`, `alert_escalate`, `alert_acknowledge`, `tasking_dispatch`, `intel_agent_ask` |
| **T5** | Physical / edge control | Same as T4 | `camera_pan_tilt_zoom`, `camera_start_recording`, `camera_stop_recording`, `camera_retask` |

Tiers 1 and 2 are the default read/write surface the agent uses
freely. Tier 3 adds downstream *reads* (agent can query MANDATE,
can probe edge cluster reachability) still without gating. Tiers 4 and
5 are **gated**: the agent refuses to call them without three
concurrent conditions:

1. Explicit operator instruction in the current turn
2. `operator_confirm: true` and `operator_id: <name>` in the tool input
3. A MEMORY.md entry timestamped to the call

The gate is enforced in **three places**:

1. **Gateway/MCP code** — `auth::require_confirm` in `avis-mcp/src/auth.rs`
   and the `OperatorConfirm` extractor in `avis-gateway/src/auth.rs`
2. **Agent doctrine** — the `AGENTS.md` red-lines section tells the
   agent to refuse Tier-4/5 calls that don't come from a current-turn
   operator instruction
3. **Audit log** — every tier is recorded with `operator_id` attribution
   so after-the-fact review can catch violations

## Isolation invariants

Three invariants were preserved through every stage. Read
[isolation-model.md](./06-isolation-model.md) for the full rationale.

1. **No edits to existing AVIS YAML configs.** `config/avis.yaml` and
   `config/avis-command.yaml` are byte-identical to pre-project state.
2. **No edits to existing AVIS codepaths reachable from standalone
   operation.** All code changes to `avis-ml`, `avis-command`, and
   `avis-core` are either (a) purely additive modules/functions, or (b)
   env-var reads that default to the old behaviour when unset.
3. **No code changes in MANDATE, ASIAS, SIS, or Decision Engine
   codebases.** Those teams' repos are untouched.

The mechanism that holds these invariants is
**`docker-compose.nemoclaw.yml`** — a compose overlay that injects env
var overrides when NemoClaw integration is wanted, and is simply absent
when it isn't. See [isolation-model.md](./06-isolation-model.md).

## Cross-repo touchpoints (by protocol)

| From | To | Protocol | Port | Used by |
|---|---|---|---|---|
| `avis-gateway` / `avis-mcp` | `avis-ml` | gRPC | 50051 | ASR, TTS, Intelligence, Dignitary, VoicePrint, **MandateQuery** |
| `avis-gateway` / `avis-mcp` | `avis-command` | gRPC | 50052 | Alerts, Tasking, PTZ, Recording, Retask, **GetCameraStatus**, HealthCheck |
| `avis-gateway` / `avis-mcp` | `avis-core` | gRPC | 50053 | **EventStreamService.Subscribe** (NEW) |
| `avis-ml` (MandateAgent) | `mandate-api` | REST | 8001 | 10 voice query endpoints — `X-Api-Key: devkey:dev` |
| `avis-command` (AlertManager, TaskingManager) | `asias-go-gateway` | REST | 8010 | Alerts CRUD, commands/tasking |
| `avis-command` (CameraController) | Decision Engine | gRPC | 9300 | PTZ, Recording, Retask, HealthCheck, GetCameraStatus |
| `avis-core` (AsiasBridge) | `asias-go-gateway` | WebSocket | 8010 | 10 event types broadcast to avis-core event bus |
| SIS (Jetson edge) | ASIAS `EventService` | gRPC | 9300 | 17 event types via `SubmitEvent` RPC |
| NemoClaw sandbox | `avis-mcp` / `avis-gateway` | HTTP | 8091 / 8090 | Agent tool calls, gated by OpenShell egress proxy + `allowed_ips` policy |

All cross-network bridging for the NemoClaw sandbox depends on three
pieces of machinery discovered during Stage 2/4/7:

1. **`docker network connect ansa-voice-intelligence-system_default <sandbox-container>`** — gives the sandbox an interface on the AVIS docker bridge so it can reach `avis-mcp` and `avis-gateway` by hostname. Since OpenShell 0.0.44 dropped the hosted-k3s `openshell-cluster-nemoclaw` container in favour of one container per sandbox, the attach target is the sandbox itself: `docker ps --format '{{.Names}}' | grep -E '^openshell-.*ansa-assistant'`.
2. **`allowed_ips: ["172.23.0.0/16"]`** in both NemoClaw policy presets — bypasses the OpenShell egress proxy's default SSRF block on RFC 1918 destinations.
3. **`extra_hosts: ["host.docker.internal:host-gateway"]`** on every avis-* service in the compose overlay — lets avis-command/avis-ml reach the MANDATE and ASIAS services via the host's published ports.

Full details in [discoveries.md](./05-discoveries.md).
