# 04 — Runbook

Operational procedures for running, inspecting, troubleshooting, and
reverting the NemoClaw ↔ AnSA integration.

Everything in this document assumes you are on the dev host with the
layout described in [README.md](./README.md#repository-layout-cross-repo).

---

## 1. Start the stack (NemoClaw-integrated mode)

The base `docker-compose.yml` brings up AVIS alone for human operators.
The NemoClaw integration is the **overlay file**
`docker-compose.nemoclaw.yml`. Apply both to get the bridge wiring.

```bash
cd ~/claude-projects/ansa-voice-intelligence-system

# Full stack with NemoClaw bridge
docker compose \
  -f docker-compose.yml \
  -f docker-compose.nemoclaw.yml \
  up -d
```

You should see these containers come up (relevant ones):

| Container | Purpose | Host port |
|---|---|---|
| `avis-ml` | gRPC server (Python, ASR/TTS/Intel/Dignitary/VoicePrint/MandateQuery) | `:50061 → :50051` |
| `avis-command` | gRPC server (Rust, alerts/tasking/camera) | `:50052` |
| `avis-core` | Orchestrator + ASIAS bridge + EventStreamService | `:50053` |
| `avis-gateway` | REST wrapper (Rust) | `:8190 → :8090` |
| `avis-mcp` | MCP server (Rust, rmcp 0.16) | `:8091` |

And (running separately, already up from other projects):

| Container | Purpose | Host port |
|---|---|---|
| `mandate-mandate-api-1` | MANDATE HTTP API | `:8001` |
| `asias-go-gateway` | ASIAS HTTP + WebSocket | `:8010` |

## 2. Start the stack (standalone, AVIS-only)

When NemoClaw is not in play, **drop the overlay**. AVIS reverts to
exactly what it did before this integration.

```bash
cd ~/claude-projects/ansa-voice-intelligence-system
docker compose up -d
```

This is the single most important property of the isolation model. See
[06-isolation-model.md](./06-isolation-model.md) for why.

---

## 3. NemoClaw sandbox lifecycle

NemoClaw's OpenShell sandbox is a separate process that runs on the dev
host. It's controlled via the `nemoclaw` CLI from `~/NemoClaw/`.

### Onboard the sandbox (first time / after a cold reset)

```bash
cd ~/NemoClaw
./nemoclaw onboard \
  --policy nemoclaw-blueprint/policies/presets/avis.yaml \
  --policy nemoclaw-blueprint/policies/presets/avis-mcp.yaml \
  --agent ansa-assistant
```

This creates the sandbox container `openshell-default--ansa-assistant-<uuid>`
(the `default--` namespace prefix and trailing UUID were introduced by
OpenShell 0.0.106; the UUID changes on every rebuild), applies
both AVIS policy presets (REST + MCP egress), and uploads the
`sandbox-workspace/` files to `/sandbox/home/`.

### Upload fresh workspace files

After editing `sandbox-workspace/AGENTS.md` or `TOOLS.md`, push them
back into the sandbox:

```bash
cd ~/NemoClaw
./nemoclaw sandbox upload \
  --agent ansa-assistant \
  --src ~/claude-projects/nemoclaw_operations/sandbox-workspace/ \
  --dest /sandbox/home/
```

### Attach to the sandbox interactively

```bash
nemoclaw ansa-assistant connect
# You are now inside /sandbox
```

### Re-attach sandbox to AVIS network

The sandbox and AVIS containers are on separate networks by default.
OpenShell's egress proxy bridges them, BUT the sandbox also needs to
be reachable via Docker DNS for gRPC calls. On a cold onboard, run:

```bash
docker network connect ansa-voice-intelligence-system_default \
  $(docker ps --format '{{.Names}}' | grep -E '^openshell-.*ansa-assistant')
```

Run this after every `./nemoclaw onboard`. It's not needed after a
simple `docker restart`.

---

## 4. Port reference

### From the dev host (localhost)

| Port | Service | Protocol |
|---|---|---|
| 8001 | mandate-api | HTTP (REST) |
| 8010 | asias-go-gateway | HTTP + WebSocket |
| 8091 | avis-mcp | HTTP (MCP streamable) |
| 8190 | avis-gateway | HTTP (REST) |
| 50052 | avis-command | gRPC |
| 50053 | avis-core EventStreamService | gRPC |
| 50061 | avis-ml (mapped from :50051) | gRPC |

### Edge cluster NodePorts (from dev host via cluster IP)

| Port | Service | Cluster | Protocol |
|---|---|---|---|
| 30900 | Decision Engine gRPC | orin-agx-01 (192.168.200.71) | gRPC |
| 30950 | Camera Registry HTTP | orin-agx-01 (192.168.200.71) | HTTP |
| 31434 | Ollama inference | orin-agx-02 (192.168.200.72) | HTTP |

### From the NemoClaw sandbox

Inside the sandbox, AVIS services are resolved via
`host.openshell.internal` (which the OpenShell egress proxy routes):

| Host (inside sandbox) | Resolves to | Purpose |
|---|---|---|
| `avis-gateway:8090` | → avis-gateway container | REST |
| `avis-mcp:8091` | → avis-mcp container | MCP |

**The egress proxy only allows these two hosts** per the
`avis.yaml` and `avis-mcp.yaml` policy presets. Everything else is
blocked. See [discoveries.md §1](./05-discoveries.md#1-the-allowed_ips-ssrf-bypass)
for the `allowed_ips` CIDR that makes this work.

### From AVIS containers

Inside `avis-ml`, `avis-command`, `avis-core`, `avis-gateway`, `avis-mcp`:

| Target | Hostname | Resolver |
|---|---|---|
| mandate-api | `host.docker.internal:8001` | `extra_hosts: host-gateway` (overlay only) |
| asias-go-gateway | `host.docker.internal:8010` | same |
| edge cluster DE | `192.168.200.71:9300` | routed via host network |
| sibling avis-* | `avis-ml:50051`, `avis-command:50052`, etc. | Docker DNS |

---

## 5. Health checks & smoke tests

### From the host

```bash
# 1. All five AVIS services
curl -s http://localhost:8190/v1/health | jq
# → {"healthy":true,"components":{"camera_controller":true,"gateway":true,...}}

# 2. MCP server advertises its tool list
curl -s -X POST http://localhost:8091/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
# → should list 35 tool names

# 3. avis-core EventStreamService gRPC
grpcurl -plaintext localhost:50053 list 2>&1 | head -5
# → avis.events.EventStreamService
```

### From inside the sandbox

```bash
nemoclaw ansa-assistant connect
mcporter call avis.health
mcporter call avis.events_drain --args '{"timeout_ms":2000,"limit":10}'

# Test a MANDATE read — 4 of 10 MANDATE tools work (see upstream-issues.md)
mcporter call avis.mandate_list_active_workflows
mcporter call avis.mandate_agency_workload

# Test Decision Engine reachability probe
mcporter call avis.camera_status --args '{"cluster_id":"edge-1"}'
# → most likely edge_unreachable in dev unless you have a path to 192.168.200.71
```

---

## 6. Inspecting audit logs

Every tool / endpoint call appends a JSONL line. Two files:

```bash
# MCP audit
tail -f ~/claude-projects/ansa-voice-intelligence-system/data/avis-mcp-audit.jsonl \
  | jq -r '[.ts, .tier, .tool, .operator_id, .upstream_status] | @tsv'

# REST audit
tail -f ~/claude-projects/ansa-voice-intelligence-system/data/avis-gateway-audit.jsonl \
  | jq -r '[.ts, .tier, .route, .operator_id, .http_status] | @tsv'
```

**Common queries**:

```bash
# Who's been escalating alerts today?
grep '"tool":"avis.alert_escalate"' data/avis-mcp-audit.jsonl | jq -r '.operator_id'

# How many Tier 5 calls this session?
grep '"tier":5' data/avis-mcp-audit.jsonl | wc -l

# Edge_unreachable incidents
grep 'edge_unreachable' data/avis-mcp-audit.jsonl | jq -r '[.ts, .tool] | @tsv'
```

---

## 7. Troubleshooting

### Symptom: `avis.health` returns `camera_controller:false`

avis-command can't reach the edge cluster. Check:

```bash
docker compose logs --tail=50 avis-command | grep -i cluster
# Look for "Failed to connect to cluster edge-1"
```

This is expected in dev environments without a route to
`192.168.200.71:9300`. Tier 3/5 tools will return `edge_unreachable`.
Tier 1/2/4 tools still work. See
[upstream-issues.md §4](./07-upstream-issues.md#4-placeholder-edge-cluster-ips).

### Symptom: `avis.mandate_list_active_incidents` returns HTTP 500

MANDATE's dev database is missing the `incidents` table. 4 of 10 MANDATE
tools work. The affected tools all touch `incidents`:

- `mandate_list_active_incidents`
- `mandate_incident_metrics`
- `mandate_get_incident_detail`
- `mandate_poi_voice_incidents`
- `mandate_dashboard_metrics` (partially)
- `mandate_dashboard_pipeline` (partially)

Fix is on the MANDATE team — see
[upstream-issues.md §1](./07-upstream-issues.md#1-mandate-missing-incidents-table).
Working tools in the meantime:

- `mandate_list_active_workflows`
- `mandate_list_active_tasking`
- `mandate_agency_workload`
- `mandate_poi_voice_status`

### Symptom: `avis.alert_escalate` returns HTTP 401

ASIAS Go Gateway doesn't accept `devkey:dev`. The gateway expects
whatever is in ASIAS's `SERVICE_API_KEY` env var, which is NOT
`devkey:dev` in their production setup. Two fixes — pick whichever:

1. **ASIAS side**: set `SERVICE_API_KEY=devkey:dev` in
   `~/claude-projects/asias-codes/docker-compose.yml`.
2. **NemoClaw side**: change `AVIS_GATEWAY_API_KEY` in
   `docker-compose.nemoclaw.yml` to match ASIAS's current value.

See [upstream-issues.md §2](./07-upstream-issues.md#2-asias-api-key-mismatch).

### Symptom: sandbox says "proxy: 403 forbidden" on every mcporter call

The OpenShell egress proxy is blocking the traffic. Check the policy
presets:

```bash
cat ~/NemoClaw/nemoclaw-blueprint/policies/presets/avis.yaml | grep allowed_ips
# Must contain the AVIS docker network CIDR, e.g. 172.23.0.0/16
```

If missing, add it and re-onboard. This is the single most important
OpenShell SSRF override — see
[discoveries.md §1](./05-discoveries.md#1-the-allowed_ips-ssrf-bypass).

### Symptom: `avis-core` container restarts in a loop

Most likely the TTS warmup is crashing the orchestrator startup
sequence. Check:

```bash
docker compose logs --tail=100 avis-core | grep -i 'isin_mps_friendly\|warmup\|tts'
```

If you see `transformers.isin_mps_friendly` errors, this is a known
AVIS-team upstream issue. The Stage 7 fix (spawning the ASIAS bridge
directly from `main.rs` instead of through `orchestrator::startup_sequence`)
avoids it — make sure you're on the overlay. See
[upstream-issues.md §3](./07-upstream-issues.md#3-avis-tts-warmup-transformers-incompatibility).

### Symptom: `mcporter call avis.camera_pan_tilt_zoom pan=45.0 ...` returns a type error

You hit the **mcporter numeric-args caveat**. Shorthand `key=value`
form passes strings. Use JSON form:

```bash
mcporter call avis.camera_pan_tilt_zoom \
  --args '{"camera_id":"LAG-001","pan":45.0,"tilt":0.0,"zoom":1.5,
           "operator_confirm":true,"operator_id":"scosaje"}'
```

See [discoveries.md §7](./05-discoveries.md#7-mcporter-numeric-args).

### Symptom: `events_drain` returns zero events forever

Most likely the ASIAS bridge isn't actually subscribing. Check:

```bash
docker compose logs --tail=50 avis-core | grep -i 'ASIAS bridge\|bridge.*connect'
```

Should see `ASIAS bridge connected` or similar. If not:

1. Confirm the overlay is active (`env AVIS_ASIAS_ENABLED` inside the
   container should be `true`).
2. Confirm `asias-go-gateway` is reachable from inside `avis-core`:
   ```bash
   docker exec avis-core sh -c \
     'wget -qO- --timeout=3 http://host.docker.internal:8010/health 2>&1'
   ```
3. You can also pump a synthetic event into ASIAS from the host side
   to test the full chain.

---

## 8. Stop the stack

```bash
# Stop NemoClaw-integrated stack (preserves data volumes)
cd ~/claude-projects/ansa-voice-intelligence-system
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml down

# Full teardown including volumes (CAUTION — drops audit logs)
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml down -v
```

## 9. Revert the NemoClaw integration entirely

The isolation invariant says reverting should be a one-liner:

```bash
cd ~/claude-projects/ansa-voice-intelligence-system
docker compose down
docker compose up -d   # No overlay → base config → NemoClaw bridge absent
```

AVIS now behaves exactly as before. MANDATE, ASIAS, SIS, Decision Engine
untouched. Sandbox still exists but all its `mcporter` calls will
404/502 since `avis-gateway` and `avis-mcp` are running their default
config with no overlay extras (they're still up, but the `extra_hosts`
entry is gone, so their downstream connections silently fail).

To fully remove the sandbox:

```bash
cd ~/NemoClaw
./nemoclaw sandbox stop --agent ansa-assistant
./nemoclaw sandbox remove --agent ansa-assistant
```

---

## 10. Rebuild after code changes

### Rust changes (avis-gateway / avis-mcp / avis-command / avis-core)

```bash
cd ~/claude-projects/ansa-voice-intelligence-system

# Rebuild one service
docker compose build avis-gateway
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml up -d --no-deps avis-gateway

# Rebuild all Rust services
docker compose build avis-gateway avis-mcp avis-command avis-core
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml up -d --no-deps avis-gateway avis-mcp avis-command avis-core
```

### Python changes (avis-ml)

avis-ml mounts code via volume in dev mode — restart is enough:

```bash
docker compose restart avis-ml
# Then wait ~3-5 min for model warmup
docker compose logs -f avis-ml | grep -i 'ready\|listening'
```

### Proto changes

When `proto/*.proto` changes, all consumers need a rebuild:

```bash
# Python side (manual regen of _pb2.py files)
cd ~/claude-projects/ansa-voice-intelligence-system/avis-ml
python -m grpc_tools.protoc \
  -I../proto --python_out=src/avis_ml \
  --grpc_python_out=src/avis_ml \
  ../proto/mandate_query.proto

# Rust side — tonic-build runs automatically on cargo build
docker compose build avis-gateway avis-mcp avis-command avis-core
```

---

## 11. Workspace re-upload checklist

After editing files in `~/claude-projects/nemoclaw_operations/sandbox-workspace/`,
push them into the sandbox's workspace directory at
`/sandbox/.openclaw/workspace/` (OpenShell 0.0.44 consolidated the old
`/sandbox/.openclaw-data/` root into `/sandbox/.openclaw/`).

Use `nemoclaw <name> upload`. **Its final argument is a destination
DIRECTORY, not a filename** — passing a full file path makes it `mkdir`
that path, which fails with `File exists` on an existing file and, for a
new name, silently creates a *directory* containing the file:

```bash
# Edit on the host (source of truth)
$EDITOR ~/claude-projects/nemoclaw_operations/sandbox-workspace/AGENTS.md

# Push into the sandbox — note the DIRECTORY destination
for f in AGENTS.md TOOLS.md IDENTITY.md SOUL.md USER.md MEMORY.md; do
  nemoclaw ansa-assistant upload \
    ~/claude-projects/nemoclaw_operations/sandbox-workspace/$f \
    /sandbox/.openclaw/workspace
done

# Verify
nemoclaw ansa-assistant exec -- bash -lc \
  'wc -c /sandbox/.openclaw/workspace/{AGENTS,TOOLS,IDENTITY,SOUL,USER,MEMORY}.md'
```

The agent reads these files on every session startup. Changes propagate
to the **next** agent session, not the current one.

## 13. Adding a new edge cluster (Stage 9 pattern)

To register an additional Decision Engine + Camera Registry pair without
touching base config files, follow this exact sequence. The example
walks through `edge-orin-1` (the orin-agx cluster mastered at
`192.168.200.71`) — the same pattern works for any other cluster.

### 13.1 Apply NodePort sibling Services on the cluster

```bash
# DE NodePort (gRPC CommandReceiverService → 30900)
ssh sco@<cluster-master> \
    'KUBECONFIG=~/.kube/config kubectl apply -n security-intel -f -' \
    < ~/claude-projects/nemoclaw_operations/k8s/de-nodeport.yaml

# Camera Registry NodePort (HTTP /cameras/metadata → 30950)
ssh sco@<cluster-master> \
    'KUBECONFIG=~/.kube/config kubectl apply -n camreg -f -' \
    < ~/claude-projects/nemoclaw_operations/k8s/camreg-nodeport.yaml
```

**Important**: this uses the cluster-local kubectl with the cluster-local
kubeconfig (`~/.kube/config` of the sco user on the master). **No
kubeconfig is fetched to the dev box** — manifests are piped over SSH.
This is the deliberate isolation invariant from Stage 9.

### 13.2 Verify reachability from the dev box

```bash
# DE gRPC port
timeout 3 bash -c 'exec 3<>/dev/tcp/<cluster-master>/30900 && echo OPEN'
grpcurl -plaintext -import-path \
    ~/claude-projects/decision-service-cpu-v1.2.0-dev/proto \
    -proto edge_command.proto \
    <cluster-master>:30900 \
    decision_service.command.CommandReceiverService/HealthCheck

# Camera Registry HTTP
curl -s http://<cluster-master>:30950/ | jq
curl -s http://<cluster-master>:30950/cameras/metadata | jq 'length'
```

### 13.3 Register the cluster in the NemoClaw overlay

Edit `~/claude-projects/ansa-voice-intelligence-system/docker-compose.nemoclaw.yml`
and append the new cluster to the JSON arrays:

```yaml
avis-command:
  environment:
    - 'AVIS_NEMOCLAW_CLUSTERS=[
        {"id":"edge-orin-1","grpc_addr":"192.168.200.71:30900","cameras":[]},
        {"id":"edge-kano-1","grpc_addr":"192.168.201.71:30900","cameras":[]}
      ]'
    - 'AVIS_NEMOCLAW_CAMREG_URLS={
        "edge-orin-1":"http://192.168.200.71:30950",
        "edge-kano-1":"http://192.168.201.71:30950"
      }'

avis-mcp:
  environment:
    - 'AVIS_NEMOCLAW_CAMREG_URLS={
        "edge-orin-1":"http://192.168.200.71:30950",
        "edge-kano-1":"http://192.168.201.71:30950"
      }'
```

(Real syntax: single-line JSON; the multi-line is just for readability.)

### 13.4 Restart and verify

```bash
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml \
  up -d --no-deps avis-command avis-mcp

nemoclaw ansa-assistant exec -- bash -lc '/sandbox/.npm-global/bin/mcporter call avis.list_clusters'
# expect: count = number of clusters in the env var

nemoclaw ansa-assistant exec -- bash -lc \
  '/sandbox/.npm-global/bin/mcporter call avis.cluster_cameras --args "{\"cluster_id\":\"edge-kano-1\",\"ptz_only\":true}"'
```

### 13.5 Revert (drop a cluster)

Remove the cluster's entries from both JSON arrays in the overlay,
restart `avis-command` and `avis-mcp`. To remove the NodePorts:

```bash
ssh sco@<cluster-master> \
    'KUBECONFIG=~/.kube/config kubectl delete -n security-intel \
     svc decision-service-v2-nodeport'
ssh sco@<cluster-master> \
    'KUBECONFIG=~/.kube/config kubectl delete -n camreg svc cam-registry-nodeport'
```

---

## 12. Frequent commands cheat sheet

```bash
# One-liner full restart
cd ~/claude-projects/ansa-voice-intelligence-system && \
  docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml restart

# Tail all five AVIS services
docker compose logs -f avis-ml avis-command avis-core avis-gateway avis-mcp

# Audit log tails side-by-side (requires `tmux` or two terminals)
tail -f data/avis-mcp-audit.jsonl | jq -c 'select(.tier >= 3)'
tail -f data/avis-gateway-audit.jsonl | jq -c 'select(.tier >= 3)'

# Confirm MANDATE reachable from avis-ml
docker exec avis-ml sh -c \
  'curl -s -o/dev/null -w "%{http_code}\n" http://host.docker.internal:8001/health'

# Confirm ASIAS reachable from avis-command
docker exec avis-command sh -c \
  'wget -qO- --timeout=3 http://host.docker.internal:8010/health'

# Check overlay is active (look for AVIS_ASIAS_ENABLED=true)
docker exec avis-core env | grep AVIS_

# Sandbox tool discovery
nemoclaw ansa-assistant exec -- bash -lc 'mcporter list avis | head -40'
```

---

## 14. Switching inference models

NemoClaw supports multiple inference providers and models. The active
model can be switched at runtime without rebuilding or restarting the
sandbox.

### Available models

| Model | Provider | Model ID | Context |
|---|---|---|---|
| Nemotron 3 Ultra 550B | nvidia-prod | `nvidia/nemotron-3-ultra-550b-a55b` | 131K |
| Nemotron 3 Super 120B | nvidia-prod | `nvidia/nemotron-3-super-120b-a12b` | 131K |
| Nemotron 3.5 Lightning 30B | nvidia-prod | `nvidia/nemotron-3.5-lightning-30b-a3b` | 131K |
| ~~Gemma 4 31B (Google)~~ | nvidia-prod | `google/gemma-4-31b-it` | — |

**Current model: Nemotron 3 Ultra 550B.** Measured latency on a trivial
prompt is ~62 s end-to-end, against ~1.6 s for Super 120B and ~11 s for
3.5 Lightning — weigh that before using it on a latency-sensitive path.

**`google/gemma-4-31b-it` is listed in the catalog but does not serve** —
verified 2026-08-25, no response within 120 s. Do not route to it.

### Switch at runtime (no restart)

```bash
# Switch to Nemotron 3 Super 120B (fastest)
nemoclaw inference set --sandbox ansa-assistant \
  --provider nvidia-prod --model nvidia/nemotron-3-super-120b-a12b

# Switch back to Ultra 550B (current default)
nemoclaw inference set --sandbox ansa-assistant \
  --provider nvidia-prod --model nvidia/nemotron-3-ultra-550b-a55b --no-verify
```

`nemoclaw inference set` verifies the route by issuing a real completion,
and that probe times out on slow models. Ultra 550B therefore needs
`--no-verify` — confirm the route with a direct `curl` first.

### Verify current model

```bash
nemoclaw ansa-assistant status
# Shows active provider + model in the inference section
```

### Override via env var (persistent, requires restart)

Post-upgrade (v0.0.12+), NemoClaw supports `NEMOCLAW_MODEL_OVERRIDE`:

```bash
# Non-interactive onboard/rebuild reads NEMOCLAW_MODEL / NEMOCLAW_PROVIDER
NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b \
NEMOCLAW_PROVIDER=nvidia-prod \
  nemoclaw ansa-assistant rebuild --yes
```

Prefer `nemoclaw inference set` for a model change: it is instant and
persists in the sandbox registry. Reach for the env vars only during an
onboard or rebuild, and be aware that setting them to something the saved
onboarding session disagrees with can trip a registry-vs-session conflict.

> The old `docker exec openshell-cluster-openshell …` form no longer
> applies — OpenShell 0.0.44 removed the hosted-k3s cluster container.

### Adding a new model

To add any model available on NVIDIA's API (`build.nvidia.com`):

1. Verify the model is accessible with your API key:
   ```bash
   curl -s https://integrate.api.nvidia.com/v1/models \
     -H "Authorization: Bearer $NVIDIA_API_KEY" | jq '.data[].id' | grep <model>
   ```
2. Switch at runtime:
   ```bash
   nemoclaw inference set --sandbox ansa-assistant \
     --provider nvidia-prod --model <model-id>
   ```
3. Test from the sandbox — a catalog listing does **not** prove a route serves:
   ```bash
   nemoclaw ansa-assistant exec -- bash -lc 'curl -s http://inference.local/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d "{\"model\":\"<model-id>\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":50}"'
   ```

---

## 15. Direct ASIAS / MANDATE troubleshooting

The direct tools (prefixed `asias_*` and `mandate_*`) bypass AVIS and
hit the downstream services directly. This section covers issues
specific to those tools. For AVIS-routed tool issues, see sections 7-8
above.

### Symptom: `asias_*` tools return `config_error`

The `AVIS_NEMOCLAW_ASIAS_API_KEY` env var is not set in
`docker-compose.nemoclaw.yml`. Without it, all ASIAS direct tools
refuse to execute rather than sending unauthenticated requests.

```bash
# Check if the env var is set
docker exec avis-mcp env | grep AVIS_NEMOCLAW_ASIAS

# Fix: add to overlay
# AVIS_NEMOCLAW_ASIAS_API_KEY=devkey
# AVIS_NEMOCLAW_ASIAS_URL=http://host.docker.internal:8010
```

### Symptom: `asias_*` tools return HTTP 401

The API key doesn't match what ASIAS expects. ASIAS uses
`X-Api-Key` (not `Authorization: Bearer`). Verify:

```bash
# Test directly
curl -s -H "X-Api-Key: devkey" http://localhost:8010/health
# → should return 200

# If 401, check what key ASIAS expects
docker exec asias-go-gateway env | grep API_KEY
```

### Symptom: `mandate_*` tools return HTTP 401

Same issue with MANDATE. Check:

```bash
curl -s -H "X-Api-Key: devkey" http://localhost:8001/health
docker exec mandate-mandate-api-1 env | grep API_KEY
```

### Symptom: `mandate_*` tools return HTTP 500 on incident endpoints

MANDATE's database may need migrations. The direct tools hit the same
endpoints as the AVIS-routed tools, so this is the same upstream issue:

```bash
# Run MANDATE migrations
cd ~/claude-projects/mandate
docker compose exec mandate-api alembic upgrade head
```

**Known issue**: the alembic migration may fail with a duplicate index
error. If so, manually drop the duplicate index:

```bash
docker compose exec mandate-db psql -U mandate -d mandate -c \
  "DROP INDEX IF EXISTS ix_duplicate_index_name;"
docker compose exec mandate-api alembic upgrade head
```

### Symptom: `asias_graph_search` returns empty results for valid queries

Query parameters are URL-encoded by the direct tools. If the query
contains special characters (`+`, `&`, `#`), they are encoded correctly.
However, ASIAS's search endpoint may not support all query syntax.
Try simpler terms:

```bash
# Instead of complex queries
mcporter call asias_graph_search query=trafficking

# Check ASIAS logs for the actual query received
docker compose logs --tail=20 asias-go-gateway | grep search
```

### Symptom: direct tools work but AVIS-routed equivalents don't (or vice versa)

The two paths use different network routes and auth mechanisms:

| Aspect | Direct tools | AVIS-routed tools |
|---|---|---|
| Network path | avis-mcp -> host.docker.internal -> downstream | avis-mcp -> avis-gateway -> avis-command -> downstream |
| Auth to downstream | `X-Api-Key` env var | Hardcoded in avis-command config |
| Auth to agent | None (T3) | operator_confirm for T4/5 |

Check both routes independently to isolate the issue.

---

## 16. Edge Decision Engine direct gRPC

The `de_*` direct tools use gRPC channels managed by the `EdgeRegistry`
component in `avis-mcp`. This section covers troubleshooting specific
to those tools. For AVIS-routed DE tools (`avis.camera_*`), see
section 7 above.

### Symptom: `de_*` tools return `cluster_not_found`

The cluster ID doesn't match any entry in `AVIS_NEMOCLAW_CLUSTERS`:

```bash
# Check registered clusters
docker exec avis-mcp env | grep AVIS_NEMOCLAW_CLUSTERS

# The value should be a JSON array like:
# [{"id":"edge-orin-1","grpc_addr":"192.168.200.71:30900","cameras":[]}]
```

### Symptom: `de_*` tools return `cluster_unreachable` instantly

The background health probe has marked the cluster as unreachable.
This means the probe couldn't connect within the 5-second timeout on
the last check (probes run every 30 seconds).

```bash
# Check if the DE NodePort is accessible
timeout 3 bash -c 'exec 3<>/dev/tcp/192.168.200.71/30900 && echo OPEN'

# Check if the NodePort service exists
ssh sco@192.168.200.71 \
  'KUBECONFIG=~/.kube/config kubectl get svc -n security-intel decision-service-v2-nodeport'

# Test gRPC directly
grpcurl -plaintext 192.168.200.71:30900 \
  decision_service.command.CommandReceiverService/HealthCheck
```

### Symptom: `de_*` tools hang for 5+ seconds

The background probe hasn't run yet (first 30 seconds after startup)
or the probe cache is stale and the actual gRPC call is timing out.
The first call after `avis-mcp` startup may be slow. Subsequent calls
use the probe cache.

### Background probe monitoring

The EdgeRegistry logs probe results to `avis-mcp`'s stdout:

```bash
docker compose logs --tail=20 avis-mcp | grep -i 'probe\|edge\|cluster'
# → "edge-orin-1: probe OK (12ms)" or "edge-orin-1: probe FAILED (timeout)"
```

### Adding a new cluster for direct DE tools

The process is the same as section 13 (adding a new edge cluster for
AVIS-routed tools). The `AVIS_NEMOCLAW_CLUSTERS` env var is shared
between `avis-mcp` (direct DE tools) and `avis-command` (AVIS-routed
camera tools). Adding a cluster to the env var makes it available to
both paths.

```bash
# After updating AVIS_NEMOCLAW_CLUSTERS in docker-compose.nemoclaw.yml
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml \
  up -d --no-deps avis-command avis-mcp

# Verify direct path
mcporter call de_health cluster_id=edge-new-cluster

# Verify AVIS-routed path
mcporter call avis.list_clusters
```
