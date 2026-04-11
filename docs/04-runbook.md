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

This creates the sandbox container `openshell-ansa-assistant`, applies
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
ssh openshell-ansa-assistant
# You are now root inside /sandbox
```

### Re-attach sandbox to AVIS network

The sandbox and AVIS containers are on separate networks by default.
OpenShell's egress proxy bridges them, BUT the sandbox also needs to
be reachable via Docker DNS for gRPC calls. On a cold onboard, run:

```bash
docker network connect \
  ansa-voice-intelligence-system_default \
  openshell-ansa-assistant
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
ssh openshell-ansa-assistant
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
`/sandbox/.openclaw-data/workspace/`. There is **no** `nemoclaw sandbox
upload` subcommand — push via SSH redirect:

```bash
# Edit on the host (source of truth)
$EDITOR ~/claude-projects/nemoclaw_operations/sandbox-workspace/AGENTS.md

# Push into the sandbox
cat ~/claude-projects/nemoclaw_operations/sandbox-workspace/AGENTS.md \
  | ssh openshell-ansa-assistant 'cat > /sandbox/.openclaw-data/workspace/AGENTS.md'
cat ~/claude-projects/nemoclaw_operations/sandbox-workspace/TOOLS.md \
  | ssh openshell-ansa-assistant 'cat > /sandbox/.openclaw-data/workspace/TOOLS.md'

# Verify
ssh openshell-ansa-assistant 'wc -l /sandbox/.openclaw-data/workspace/{AGENTS,TOOLS}.md'
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

ssh openshell-ansa-assistant '/sandbox/.npm-global/bin/mcporter call avis.list_clusters'
# expect: count = number of clusters in the env var

ssh openshell-ansa-assistant \
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
ssh openshell-ansa-assistant 'mcporter list avis | head -40'
```

---

## 14. Switching inference models

NemoClaw supports multiple inference providers and models. The active
model can be switched at runtime without rebuilding or restarting the
sandbox.

### Available models

| Model | Provider | Model ID | Context |
|---|---|---|---|
| Nemotron 3 Super 120B | nvidia-prod | `nvidia/nemotron-3-super-120b-a12b` | 131K |
| Gemma 4 31B (Google) | nvidia-prod | `google/gemma-4-31b-it` | 128K |

### Switch at runtime (no restart)

```bash
# Switch to Gemma 4 31B
docker exec openshell-cluster-openshell \
  openshell inference set \
    --provider nvidia-prod \
    --model google/gemma-4-31b-it

# Switch back to Nemotron (default)
docker exec openshell-cluster-openshell \
  openshell inference set \
    --provider nvidia-prod \
    --model nvidia/nemotron-3-super-120b-a12b
```

### Verify current model

```bash
nemoclaw ansa-assistant status
# Shows active provider + model in the inference section
```

### Override via env var (persistent, requires restart)

Post-upgrade (v0.0.12+), NemoClaw supports `NEMOCLAW_MODEL_OVERRIDE`:

```bash
# Set override on the sandbox container
docker exec openshell-cluster-openshell \
  sh -c 'echo "NEMOCLAW_MODEL_OVERRIDE=google/gemma-4-31b-it" >> /etc/environment'

# Restart the sandbox entrypoint to apply
nemoclaw ansa-assistant destroy --yes && nemoclaw onboard
```

The env var approach survives reboots but requires a sandbox restart.
The `openshell inference set` approach is instant but resets on restart.

### Adding a new model

To add any model available on NVIDIA's API (`build.nvidia.com`):

1. Verify the model is accessible with your API key:
   ```bash
   curl -s https://integrate.api.nvidia.com/v1/models \
     -H "Authorization: Bearer $NVIDIA_API_KEY" | jq '.data[].id' | grep <model>
   ```
2. Switch at runtime:
   ```bash
   docker exec openshell-cluster-openshell \
     openshell inference set --provider nvidia-prod --model <model-id>
   ```
3. Test from the sandbox:
   ```bash
   ssh openshell-ansa-assistant 'curl -s http://inference.local/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d "{\"model\":\"<model-id>\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":50}"'
   ```
