# 10 — NemoClaw Upgrade + Inference Model Deployment

**Date**: 2026-04-11
**What changed**: NemoClaw CLI upgraded from v0.0.6 to v0.0.12,
OpenShell from 0.0.6 to 0.0.26, Gemma 4 E4B deployed on cluster
Ollama, Ollama upgraded from 0.17.7 to 0.20.5. Currently using
Nemotron 3 Super 120B via NVIDIA Endpoints as primary model.

---

## NemoClaw CLI v0.0.6 -> v0.0.12

### Upgrade procedure

```bash
cd ~/NemoClaw
git pull origin main   # 145 commits between v0.0.6 and v0.0.12
cargo build --release
sudo cp target/release/nemoclaw /usr/local/bin/nemoclaw
nemoclaw --version     # nemoclaw 0.0.12
```

### Key changes across 145 commits

| Area | What changed |
|---|---|
| CLI | New subcommands: `nemoclaw status`, `nemoclaw logs`, `nemoclaw policy-diff` |
| Policies | Policy preset system overhauled: YAML-only, no more JSON fallback |
| Sandbox | Sandbox lifecycle improvements: faster cold-start, checkpoint/restore |
| Networking | Egress proxy stability fixes (was dropping long-lived connections) |
| Inference | `NEMOCLAW_MODEL_OVERRIDE` env var for persistent model selection |
| Auth | Service-to-service API key propagation via policy presets |
| Debugging | `nemoclaw sandbox exec` for running commands inside the sandbox |

### Breaking changes

1. **Policy format**: v0.0.12 expects `egress.allow[]` with explicit
   `host`/`port`/`protocol` fields. Old-style `allow_hosts: ["*:8090"]`
   is no longer accepted. All policy presets were already in the new
   format for this project.

2. **Sandbox paths**: workspace directory moved from
   `/sandbox/home/` to `/sandbox/.openclaw-data/workspace/` in
   OpenShell 0.0.20+. The upload procedure in
   [runbook.md](./04-runbook.md#11-workspace-re-upload-checklist)
   already uses the new path.

---

## OpenShell 0.0.6 -> 0.0.26

OpenShell (the sandbox runtime) was upgraded as part of the NemoClaw
update. Most changes are invisible, but one critical regression was
discovered:

### `inference.local` broken in OpenShell 0.0.26

**Symptom**: the `inference.local` hostname (the sandbox's built-in
reverse proxy for LLM inference) stopped resolving. The agent's
`/v1/chat/completions` calls to `http://inference.local` returned
`ECONNREFUSED`.

**Root cause**: OpenShell 0.0.26 changed the internal DNS resolver to
require explicit provider registration. The `inference.local` hostname
is registered only when the `inference` module initialises, but the
module's init order changed and it now races with the DNS setup.

**Status**: reported upstream. No fix as of 2026-04-11.

### Workaround: patch `openclaw.json`

The workaround bypasses `inference.local` entirely by pointing the
agent directly at the inference endpoint:

```bash
# Inside the sandbox
cat /sandbox/.openclaw-data/openclaw.json | jq \
  '.inference.endpoint = "https://integrate.api.nvidia.com/v1"' \
  > /tmp/openclaw-patched.json
mv /tmp/openclaw-patched.json /sandbox/.openclaw-data/openclaw.json

# Restart the agent process (not the sandbox container)
kill -HUP $(pgrep openclaw-agent)
```

Or from the host, push the patched config:

```bash
ssh openshell-ansa-assistant 'cat /sandbox/.openclaw-data/openclaw.json' \
  | jq '.inference.endpoint = "https://integrate.api.nvidia.com/v1"' \
  | ssh openshell-ansa-assistant 'cat > /sandbox/.openclaw-data/openclaw.json'
```

**Caveat**: this workaround hardcodes the NVIDIA endpoint. When
switching to Ollama (cluster-local inference), the endpoint must be
updated manually. See the "Model switching" section below.

---

## Gemma 4 E4B deployment on cluster Ollama

### Cluster topology

The Orin AGX cluster (`orin-agx-02`, `192.168.200.72`) runs an Ollama
instance for local inference. This was upgraded and Gemma 4 was deployed:

| Component | Before | After |
|---|---|---|
| Ollama version | 0.17.7 | 0.20.5 |
| Available models | llama3.2:3b | llama3.2:3b, gemma4:e4b |
| NodePort | none | 31434 |
| Init container | none | pulls `gemma4:e4b` on pod start |

### Ollama upgrade

```bash
# On orin-agx-02
ssh sco@192.168.200.72

# Upgrade Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama --version   # 0.20.5

# Pull Gemma 4 E4B
ollama pull gemma4:e4b
# ~4.7 GB, fits in 32 GB Orin AGX RAM
```

### NodePort exposure

A Kubernetes NodePort Service was created to expose Ollama from the
cluster to the dev host:

```yaml
# ~/claude-projects/nemoclaw_operations/k8s/ollama-nodeport.yaml
apiVersion: v1
kind: Service
metadata:
  name: ollama-nodeport
  namespace: ollama
spec:
  type: NodePort
  selector:
    app: ollama
  ports:
    - port: 11434
      targetPort: 11434
      nodePort: 31434
      protocol: TCP
```

```bash
# Apply
ssh sco@192.168.200.72 \
  'KUBECONFIG=~/.kube/config kubectl apply -n ollama -f -' \
  < ~/claude-projects/nemoclaw_operations/k8s/ollama-nodeport.yaml

# Verify from dev host
curl -s http://192.168.200.72:31434/api/tags | jq '.models[].name'
# → "llama3.2:3b", "gemma4:e4b"
```

### Init container patch

To ensure `gemma4:e4b` is available even after a cold cluster restart,
the Ollama Kubernetes deployment was patched with an init container
that pulls the model:

```yaml
initContainers:
  - name: pull-gemma4
    image: ollama/ollama:0.20.5
    command: ["ollama", "pull", "gemma4:e4b"]
    env:
      - name: OLLAMA_HOST
        value: "http://localhost:11434"
```

This runs before the main Ollama container starts serving. On a warm
restart (model already cached), it completes in <5 seconds.

---

## Model switching

### Available models

| Model | Provider | Endpoint | Context | Use case |
|---|---|---|---|---|
| Nemotron 3 Super 120B | NVIDIA API | `https://integrate.api.nvidia.com/v1` | 131K | Primary: heavy reasoning, long context |
| Gemma 4 E4B (31B params) | Cluster Ollama | `http://192.168.200.72:31434/v1` | 128K | Secondary: local, faster, no API cost |

### Switching at runtime (NVIDIA -> Ollama)

```bash
# 1. Patch openclaw.json to point at Ollama
ssh openshell-ansa-assistant 'cat /sandbox/.openclaw-data/openclaw.json' \
  | jq '.inference.endpoint = "http://192.168.200.72:31434/v1" | .inference.model = "gemma4:e4b"' \
  | ssh openshell-ansa-assistant 'cat > /sandbox/.openclaw-data/openclaw.json'

# 2. Restart agent
ssh openshell-ansa-assistant 'kill -HUP $(pgrep openclaw-agent)'

# 3. Verify
ssh openshell-ansa-assistant 'curl -s http://192.168.200.72:31434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"gemma4:e4b\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":50}"'
```

### Switching at runtime (Ollama -> NVIDIA)

```bash
# 1. Patch openclaw.json back to NVIDIA
ssh openshell-ansa-assistant 'cat /sandbox/.openclaw-data/openclaw.json' \
  | jq '.inference.endpoint = "https://integrate.api.nvidia.com/v1" | .inference.model = "nvidia/nemotron-3-super-120b-a12b"' \
  | ssh openshell-ansa-assistant 'cat > /sandbox/.openclaw-data/openclaw.json'

# 2. Restart agent
ssh openshell-ansa-assistant 'kill -HUP $(pgrep openclaw-agent)'
```

### Current status

**Active model**: Nemotron 3 Super 120B via NVIDIA Endpoints.

Gemma 4 E4B on cluster Ollama is deployed and verified but not the
default because:
1. The `inference.local` workaround requires manual endpoint patching
2. Nemotron 3 Super 120B has stronger reasoning for AnSA's complex
   multi-agency queries
3. Ollama on the Orin cluster is shared with SIS inference workloads

---

## Policy presets for inference

### `nvidia-api.yaml`

Allows sandbox egress to NVIDIA's inference API:

```yaml
# ~/NemoClaw/nemoclaw-blueprint/policies/presets/nvidia-api.yaml
egress:
  allow:
    - host: "integrate.api.nvidia.com"
      port: 443
      protocol: https
      description: "NVIDIA inference API for Nemotron/Gemma models"
```

This preset was already active from the original NemoClaw setup.

### `ollama-inference.yaml`

Allows sandbox egress to the cluster Ollama instance:

```yaml
# ~/NemoClaw/nemoclaw-blueprint/policies/presets/ollama-inference.yaml
egress:
  allow:
    - host: "192.168.200.72"
      port: 31434
      protocol: http
      description: "Cluster Ollama (Gemma 4 E4B) via NodePort"
```

Apply when using Ollama for inference:

```bash
./nemoclaw onboard \
  --policy nemoclaw-blueprint/policies/presets/avis.yaml \
  --policy nemoclaw-blueprint/policies/presets/avis-mcp.yaml \
  --policy nemoclaw-blueprint/policies/presets/nvidia-api.yaml \
  --policy nemoclaw-blueprint/policies/presets/ollama-inference.yaml \
  --agent ansa-assistant
```

---

## Troubleshooting

### Symptom: agent gets `ECONNREFUSED` on inference calls

1. Check if `inference.local` is the endpoint:
   ```bash
   ssh openshell-ansa-assistant 'cat /sandbox/.openclaw-data/openclaw.json | jq .inference'
   ```
2. If endpoint is `http://inference.local`, apply the workaround above
3. If endpoint is NVIDIA API, check network egress:
   ```bash
   ssh openshell-ansa-assistant 'curl -s https://integrate.api.nvidia.com/v1/models \
     -H "Authorization: Bearer $NVIDIA_API_KEY" | head -c 200'
   ```

### Symptom: Gemma 4 returns empty or garbled responses

1. Verify the model is loaded:
   ```bash
   curl -s http://192.168.200.72:31434/api/tags | jq '.models[].name'
   ```
2. Check Ollama's available memory:
   ```bash
   ssh sco@192.168.200.72 'ollama ps'
   ```
3. Gemma 4 E4B needs ~8 GB RAM. If Ollama is also running llama3.2:3b,
   unload it: `curl -X DELETE http://192.168.200.72:31434/api/delete -d '{"name":"llama3.2:3b"}'`

### Symptom: init container hangs on pod restart

The init container pulls `gemma4:e4b` (~4.7 GB). On a cold cluster
restart with no cached layers, this can take 10-15 minutes on the
Orin's network. Check progress:

```bash
ssh sco@192.168.200.72 \
  'KUBECONFIG=~/.kube/config kubectl logs -n ollama -c pull-gemma4 <pod-name>'
```

---

_Added 2026-04-11. See [04-runbook.md](./04-runbook.md#14-switching-inference-models)
for runtime model switching procedures._
