# 07 — Upstream Issues

Issues discovered in other teams' code during the integration. We
**deliberately did not fix any of these** because fixing them would
have broken the isolation invariant (see
[isolation-model.md](./06-isolation-model.md)). They are listed here
with enough context for the respective owning team to pick up and
triage.

Each entry has: **symptom, reproduction, blast radius,
recommended fix owner, workaround NemoClaw is using in the meantime**.

---

## 1. MANDATE — missing `incidents` table in dev database

**Owner**: MANDATE team (`~/claude-projects/mandate/`)

**Symptom**. 6 of 10 typed MANDATE tools return HTTP 500:

```
mcporter call avis.mandate_list_active_incidents
# → {"error":"HTTP 500: sqlalchemy.exc.ProgrammingError:
#     (psycopg2.errors.UndefinedTable) relation "incidents" does not exist"}
```

**Reproduction**. Direct MANDATE call bypassing AVIS:

```bash
curl -s http://localhost:8001/api/v1/mandate/incidents/active \
  -u 'devkey:dev' | jq
# → same 500
```

**Affected MANDATE endpoints** (all hit a missing `incidents` table):
- `GET /api/v1/mandate/incidents/active`
- `GET /api/v1/mandate/incidents/metrics`
- `GET /api/v1/mandate/incidents/:id`
- `GET /api/v1/mandate/poi/:id/incidents`
- `GET /api/v1/mandate/dashboard/metrics` (partial — some fields)
- `GET /api/v1/mandate/dashboard/pipeline` (partial)

**Blast radius**. 6 of 10 NemoClaw MANDATE tools are effectively
non-functional. The SIS event reasoning loop for high-severity events
(MILITARY_THREAT, KIDNAPPING, IMMINENT_ATTACK) depends on
`mandate_list_active_incidents` to gather context, so those reasoning
paths are currently degraded.

**Root cause** (best guess from outside). MANDATE's dev compose uses a
fresh Postgres 16 container that gets auto-initialised from a migration
chain. The `incidents` table migration appears to be missing from that
chain, or depends on a fixture that isn't applied in dev mode. The
`workflows` and `tasking` tables ARE present (tools that only touch
them work fine).

**Recommended fix owner**. MANDATE team. Either:

1. Add the missing migration to the init chain, OR
2. Seed the dev DB with a valid `incidents` table schema via a
   fixtures script that runs in the entrypoint.

**Workaround in NemoClaw**. The agent's AGENTS.md tells it to **try
`mandate_list_active_incidents` first; if 500, fall back to
`mandate_list_active_workflows` and `mandate_list_active_tasking`**
which both work. This is documented but awkward.

**Working tools** (use these for smoke tests):
- `mandate_list_active_workflows` ✅
- `mandate_list_active_tasking` ✅
- `mandate_agency_workload` ✅
- `mandate_poi_voice_status` ✅

**Pointer for MANDATE team**: look at their `alembic/versions/` or
equivalent, find the last migration that touches `incidents`, see
whether it's run on dev init.

---

## 2. ASIAS — API key mismatch

**Owner**: ASIAS team (`~/claude-projects/asias-codes/`)

**Symptom**. All 4 Tier-4 mutation tools return HTTP 401:

```bash
mcporter call avis.alert_escalate --args '{
  "alert_id":"ALT-9999","new_priority":"HIGH","reason":"test",
  "operator_confirm":true,"operator_id":"scosaje"}'
# → {"error":"HTTP 401: {\"error\":\"invalid API key\"}"}
```

**Reproduction**. Direct ASIAS call:

```bash
curl -s -X POST http://localhost:8010/api/v1/alerts/ALT-9999/escalate \
  -H 'Authorization: Basic ZGV2a2V5OmRldg==' \
  -H 'content-type: application/json' \
  -d '{"new_priority":"HIGH","reason":"test"}'
# → HTTP 401 "invalid API key"
```

**Root cause**. ASIAS Go Gateway reads its expected API key from the
`SERVICE_API_KEY` environment variable, which in ASIAS's
`docker-compose.yml` is **not** set to `devkey:dev`. It's set to a
placeholder that only matches the production key.

The NemoClaw overlay hardcodes `AVIS_GATEWAY_API_KEY=devkey:dev` on the
assumption (mirrored from MANDATE) that dev keys are the same across
services.

**Blast radius**. All 4 central mutation tools (Tier 4) currently fail
in this dev environment:

- `avis.alert_escalate` ❌
- `avis.alert_acknowledge` ❌
- `avis.tasking_dispatch` ❌
- `avis.command_alert_create` ❌ (Tier 3-gated)

The read-only ASIAS path is not affected because ASIAS Go Gateway
alert reads work via the WebSocket event bridge, not the authed REST
endpoints.

**Recommended fix owner**. ASIAS team. Either:

1. **ASIAS side**: set `SERVICE_API_KEY=devkey:dev` in
   `~/claude-projects/asias-codes/docker-compose.yml` to align with
   MANDATE's convention.
2. **NemoClaw side**: update `docker-compose.nemoclaw.yml` to match
   whatever ASIAS currently expects. Would need ASIAS team to tell us
   the correct dev key.

Option 1 is preferred because it aligns dev-key conventions across the
stack. Option 2 is a local fix for this dev box only.

**Workaround in NemoClaw**. None currently — the Tier-4 verification
tests are passing only the refusal path (when operator_confirm is
missing), not the success path. The agent can correctly refuse
unauthorised calls, but cannot actually dispatch anything.

---

## 3. AVIS — TTS warmup crashes on `transformers` version incompatibility

**Owner**: AVIS ML team (`~/claude-projects/ansa-voice-intelligence-system/avis-ml/`)

**Symptom**. `avis-core` orchestrator startup aborts at step 2.3
(TTS warmup) with:

```
AttributeError: module 'transformers' has no attribute 'isin_mps_friendly'
```

Then `orchestrator::startup_sequence()` returns `Err(...)` and the
container restarts in a crash loop.

**Reproduction**.

```bash
cd ~/claude-projects/ansa-voice-intelligence-system
docker compose logs --tail=200 avis-ml | grep -A 5 isin_mps_friendly
docker compose logs --tail=200 avis-core | grep -A 5 'startup.*fail'
```

**Root cause**. `avis-ml` depends on a specific `transformers` version
that exposes `isin_mps_friendly`. The Dockerfile's pip install resolves
to a newer `transformers` where this internal helper was renamed or
removed. Common issue with `coqui-tts` or similar TTS libraries that
hold hardcoded references to transformers internals.

**Blast radius**. Historically this would have prevented the Stage 7
ASIAS bridge from ever starting (because the orchestrator dies before
step 3.8 where the bridge was supposed to be spawned).

**Fix recommendation for AVIS team**. Pin `transformers==<working_version>`
in `avis-ml/pyproject.toml` or `requirements.txt`. Or update the TTS
wrapper to stop using the private `isin_mps_friendly` helper.

**Workaround in NemoClaw** ⭐. We spawn the ASIAS bridge **directly
from `avis-core/src/main.rs`** before the orchestrator runs. The bridge
lives in its own `tokio::spawn` task, so even if
`orchestrator::startup_sequence()` fails at TTS warmup, the bridge
keeps running. This is documented in
[discoveries.md §8](./05-discoveries.md#8-avis-cores-orchestrator-startup-was-too-brittle-to-reuse).

This workaround is fragile but isolation-safe. A proper fix belongs in
the AVIS team's `transformers` pin.

---

## 4. Placeholder edge cluster IPs — ✅ RESOLVED IN STAGE 9

**Status**: resolved 2026-04-07 by Stage 9 (cluster registration +
NodePort exposure pattern). Kept here as historical record.

**Original symptom**. The base `config/avis-command.yaml` shipped with
three placeholder clusters at `10.0.1.10/11/12:9300` that don't exist
on any LAN. Every Tier-5 call returned `edge_unreachable` from the
wrong target. The real Decision Engine on `192.168.200.71` was
reachable on the LAN but its gRPC port `9300` was a Kubernetes
ClusterIP — not externally reachable.

**Resolution**.

1. **NodePort sibling Service** (`k8s/de-nodeport.yaml`) exposes the
   Decision Engine's gRPC `CommandReceiverService` on `30900`. Sibling
   to the existing `decision-service-v2` ClusterIP — does NOT modify
   the Decision Engine team's manifests. *(2026-09-27: the Service
   moved to the decision-service repo, `k8s/deployment-v2.yaml`; this
   repo no longer defines it.)*
2. **NodePort sibling Service** (`k8s/camreg-nodeport.yaml`) exposes
   the Camera Registry HTTP API on `30950`.
3. **Replace-mode env var** `AVIS_NEMOCLAW_CLUSTERS` overrides the
   YAML placeholders at runtime via the NemoClaw overlay only:
   `[{"id":"edge-orin-1","grpc_addr":"192.168.200.71:30900","cameras":[]}]`.
4. End-to-end PTZ verified against real DE (`avis.camera_pan_tilt_zoom`
   on camera `cam64` returned `success:true`, audit logged at tier:5).

The placeholders themselves still exist in `config/avis-command.yaml`
(touching base config breaks isolation) — but they're superseded by
the env var whenever the NemoClaw overlay is active.

See [docs/04-runbook.md §13](./04-runbook.md#13-adding-a-new-edge-cluster-stage-9-pattern)
for the full pattern to register additional edge clusters.

## 4b. Two cameras-of-truth on each Orin cluster (NEW — Stage 9)

**Owner**: Camera Registry team + Decision Engine team (joint)

**Symptom**. Each Orin AGX cluster runs **two** independent camera
registries that are NOT synchronised:

| Source | Where | Camera IDs |
|---|---|---|
| **Camera Registry** (`camreg`) | `cam-registry` Deployment in the `camreg` namespace, FastAPI at port 3050, parquet-on-MinIO storage | `aj92ii-A-164`, `8qfv2f-A-64`, `aj92ii-D-83`, … (clan + zone + index) |
| **Decision Engine internal registry** | `cameras.json` config baked into the `decision-service-v2` pod | `cam64`, `cam68`, `cam70` (simple counter) |

On the orin-agx-01 cluster verified during Stage 9:
- Camera Registry reports **13 cameras** total, **1 PTZ** (`aj92ii-A-164`).
- Decision Engine HealthCheck reports **4 cameras** total, **3 PTZ**
  (`cam64`, `cam68`, `cam70`).

The intersection is **zero**: no camera_id is shared between the two.

**Impact on NemoClaw**. The agent's natural discovery flow is
`avis.cluster_cameras` → pick a PTZ camera_id → `avis.camera_pan_tilt_zoom`.
But camreg's PTZ id (`aj92ii-A-164`) is unknown to the Decision Engine,
so SetPTZ returns `NotFound: camera not found or not PTZ-capable`.
avis-command's mutation path then mis-classifies that NotFound as
"cluster unreachable" and returns `success:true` with a "logged
locally" message — confusing.

**Workaround in NemoClaw documentation**. AGENTS.md and TOOLS.md now
warn the agent about this and tell it to **trust `avis.camera_status`
(which queries the DE)** as the canonical PTZ-capable camera list,
not camreg's `is_ptz` flag. If a SetPTZ "succeeds with logged locally",
report it to the operator as a likely cross-registry mismatch, not as
unreachability.

**Fix recommendations**:

1. **Reconcile the registries** — make Camera Registry the
   single source of truth and have Decision Engine consume it on
   startup (or via a watch). Aligns IDs across both views.
2. OR **make camreg push to the DE** via the existing MQTT bus
   (`cameraRegistry` topic appears in camreg's env vars).
3. OR **expose the DE's internal registry as a separate gRPC RPC**
   so NemoClaw can query both and reconcile in the agent layer.
4. **Fix avis-command's NotFound classification** — separate
   `Unavailable` (network) from `NotFound` (camera doesn't exist).
   Return an explicit `camera_not_found` error to the agent rather
   than burying it in a "logged locally" message. Small change in
   `avis-command/src/camera/mod.rs` PTZ handler — pattern-match the
   tonic Status code rather than treating any error as unreachable.

---

## 5. Edge cluster v2.1.0 — recording/retask are stubs

**Owner**: Decision Engine team
(`~/claude-projects/decision-service-cpu-v1.2.0-dev/`)

**Symptom**. Three of the four Tier-5 camera tools return success but
don't actually do anything:

- `avis.camera_start_recording` → `success: true, message: "recording started (stub)"`
- `avis.camera_stop_recording` → same pattern
- `avis.camera_retask` → same pattern

**Reproduction**. Only reproducible against a reachable edge cluster
(see issue #4 above). The edge cluster implementation of
`CommandReceiverService.StartRecording` / `StopRecording` / `RetaskCamera`
currently returns an `UNIMPLEMENTED` gRPC status. `avis-command`
catches that and rewrites the response as "stub" success.

**Blast radius**. The agent can "call" these tools and the calls
appear to succeed, but no recording is actually started and no camera
is actually retasked. The Tier-5 gating and audit trail work correctly.
This is a **semantic** gap, not a security gap.

**Recommended fix owner**. Decision Engine team. The proto contract
(`edge_command.proto`) already defines `RecordingRequest`,
`RetaskRequest`, etc. — they just need implementations on the C++
side.

**Workaround in NemoClaw**. Tool descriptions explicitly mark these as
stubs so the agent knows not to rely on them:

```rust
// avis-mcp/src/service.rs
#[tool(description = "Start recording on a camera via the Decision Engine gRPC.
  TIER 5 — requires operator_confirm: true and operator_id.
  Note: StartRecording is a stub on the edge in v2.1.0 (returns UNIMPLEMENTED).")]
```

The agent reads the tool description and knows not to promise the
operator that recording is actually happening.

---

## 6. Minor — `mandate-api` HTTP 500 on trailing slash

**Owner**: MANDATE team

**Symptom**. `GET /api/v1/mandate/workflows/` (trailing slash) returns
HTTP 500, but `GET /api/v1/mandate/workflows` (no trailing slash) is
fine.

**Reproduction**.

```bash
curl -u devkey:dev http://localhost:8001/api/v1/mandate/workflows/
# → {"error":"Internal Server Error"}
curl -u devkey:dev http://localhost:8001/api/v1/mandate/workflows
# → {"workflows":[...]}
```

**Blast radius**. Cosmetic. NemoClaw's `MandateAgent` always calls
without the trailing slash, so the tools work. But any client that
naively appends `/` will fail.

**Fix recommendation**. MANDATE team — normalise trailing slashes in
the FastAPI router.

**Workaround**. None needed on NemoClaw side.

---

## 7. Minor — ASIAS Go Gateway WebSocket emits non-JSON ping frames

**Owner**: ASIAS team

**Symptom**. The `avis-core` ASIAS bridge occasionally logs:

```
WARN asias::bridge: failed to parse WebSocket message as JSON: ping
```

**Root cause**. Go Gateway sends text-frame `ping` keepalives as
bare `ping` strings rather than structured JSON. The bridge's
`serde_json::from_str` rejects these.

**Blast radius**. Cosmetic noise in logs. The bridge correctly
ignores these unparseable frames and continues consuming. No events
are lost.

**Fix recommendation**. ASIAS Go Gateway team — either drop the ping
frames (use proper WebSocket control frames) or wrap them as
`{"type":"ping"}` JSON.

**Workaround**. `avis-core` bridge downgrades the parse error to
`DEBUG` when the body is exactly `ping` so it doesn't spam WARN logs.

---

## 8. Minor — avis-ml model warmup takes ~3–5 minutes on first start

**Owner**: AVIS ML team

**Symptom**. On a cold container start, `avis-ml` is not ready to
serve gRPC traffic for several minutes while it warms up ASR, TTS, and
the Intelligence model. During that window, calls to
`avis-gateway`/`avis-mcp` return 5xx errors.

**Reproduction**.

```bash
docker compose up -d avis-ml
sleep 10
docker exec avis-ml python -c \
  "import grpc; ch = grpc.insecure_channel('localhost:50051'); \
   grpc.channel_ready_future(ch).result(timeout=5)"
# → grpc._channel._InactiveRpcError or timeout
```

**Blast radius**. Annoying during development. Not a correctness
issue. Affects the "quick reset" dev loop more than production.

**Fix recommendation** (optional). Cache warmup artifacts in a
persistent volume so subsequent starts skip the expensive warmup.
This is a known tradeoff between cold-start latency and disk footprint;
keep as-is unless it becomes a bottleneck.

**Workaround**. Document the warmup wait in the runbook (done — see
[runbook.md §10](./04-runbook.md#python-changes-avis-ml)).

---

## Summary table

| # | Area | Severity | Blocks NemoClaw? | Fix owner |
|---|---|---|---|---|
| 1 | MANDATE missing `incidents` table | High | 6 of 10 MANDATE tools degraded | MANDATE team |
| 2 | ASIAS API key mismatch | High | All Tier-4 mutations | ASIAS team |
| 3 | AVIS TTS warmup transformers bug | Medium | Would have blocked Stage 7; worked around | AVIS ML team |
| 4 | Placeholder edge cluster IPs | ✅ RESOLVED | Resolved in Stage 9 (NodePort + replace-mode env var) | NemoClaw |
| 4b | Two cameras-of-truth (camreg vs DE) | Medium | PTZ confusing — agent must trust DE not camreg for IDs | camreg + DE teams |
| 5 | Edge cluster v2.1.0 recording stubs | Medium | 3 of 4 Tier-5 tools semantically stubbed | Decision Engine team |
| 6 | MANDATE trailing-slash 500 | Low | None (we don't send trailing slashes) | MANDATE team |
| 7 | ASIAS WebSocket ping frames | Low | None (log noise only) | ASIAS team |
| 8 | avis-ml long warmup | Low | Dev ergonomics only | AVIS ML team |

**None of these are bugs in NemoClaw code.** They are documented here
so that when a NemoClaw user hits one of them, they can identify it
as an upstream issue and route the ticket to the right team.
