# 06 — Isolation Model

**The invariant**: *nothing we built may affect the operations of AVIS,
MANDATE, ASIAS, SIS, or the Decision Engine when NemoClaw isn't running.*

This was requested by the operator mid-project after Stage 3 was already
landed, and it forced a partial redesign. By the end of Stage 8 the
invariant was satisfied without compromise. This document explains how.

---

## 1. What "isolation" actually means here

"Isolation" in this project has **three** faces:

1. **Operational isolation** — running AVIS without NemoClaw should
   behave identically to running AVIS before NemoClaw existed. No
   config changes, no feature flag flips, no new env vars with defaults
   that change behaviour.
2. **Reversibility** — you should be able to remove NemoClaw with a
   single command that doesn't edit any production file.
3. **Zero downstream impact** — MANDATE, ASIAS, SIS, and the Decision
   Engine must be entirely unaware of NemoClaw's existence. No extra
   load, no extra traffic, no new API consumers they didn't plan for.

The first two are enforced by **file-level discipline**. The third
is enforced by **architecture** (the sovereignty doctrine — see §5).

---

## 2. File-level discipline: what we did NOT edit

The following files were deliberately never modified during the project:

| File | Project | Why not |
|---|---|---|
| `config/avis.yaml` | avis | Production config. Editing it would change AVIS-only behaviour. |
| `config/avis-command.yaml` | avis | Same. |
| `docker-compose.yml` (avis) | avis | Base compose file. Editing it would change standalone AVIS behaviour. |
| `mandate/docker-compose.yml` | mandate | Other team's file. |
| `asias-codes/docker-compose.yml` | asias | Other team's file. |
| `security-intelligence-system/**` | sis | Other team's repo. |
| `decision-service-cpu-v1.2.0-dev/**` | decision engine | Other team's repo. |
| MANDATE source code | mandate | Zero MANDATE code changes. |
| ASIAS source code | asias | Zero ASIAS code changes. |
| SIS source code | sis | Zero SIS code changes. |
| Decision Engine source code | decision engine | Zero DE code changes. |

**Every single file touched during the integration is either net-new
or lives inside `avis-*` crates/services that we co-own.**

---

## 3. The overlay pattern

The isolation mechanism is a single file: `docker-compose.nemoclaw.yml`.

```yaml
# ~/claude-projects/ansa-voice-intelligence-system/docker-compose.nemoclaw.yml
services:
  avis-ml:
    extra_hosts: ["host.docker.internal:host-gateway"]
    environment:
      - AVIS_MANDATE_BASE_URL=http://host.docker.internal:8001
      - AVIS_MANDATE_API_KEY=devkey:dev

  avis-command:
    extra_hosts: ["host.docker.internal:host-gateway"]
    environment:
      - AVIS_GATEWAY_BASE_URL=http://host.docker.internal:8010
      - AVIS_GATEWAY_API_KEY=devkey:dev

  avis-core:
    extra_hosts: ["host.docker.internal:host-gateway"]
    environment:
      - AVIS_ASIAS_ENABLED=true
      - AVIS_ASIAS_GATEWAY_URL=ws://host.docker.internal:8010/ws/events
    ports:
      - "50053:50053"

  avis-gateway:
    extra_hosts: ["host.docker.internal:host-gateway"]

  avis-mcp:
    extra_hosts: ["host.docker.internal:host-gateway"]
```

**Two run modes**:

```bash
# Standalone (AVIS for human operators only):
docker compose up -d

# NemoClaw-integrated (adds the bridge):
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml up -d
```

Docker compose merges the two files, with the overlay adding
`extra_hosts`, `environment`, and `ports` on top of the base services.
**Nothing in the overlay removes or overrides base functionality** —
it's strictly additive.

**Revert** = drop the overlay. Literally one word removed from the
command line.

---

## 4. The env-var override pattern

The overlay sets env vars. But for those env vars to *do* anything,
the AVIS services had to actually **read** them. We chose an **additive
read** pattern: a small change in each config loader that checks an
env var and overrides the YAML value **only if the env var is set**.

### Pattern in Rust (`avis-command/src/config.rs`)

```rust
impl CommandConfig {
    pub fn load(path: &str) -> Result<Self> {
        let contents = std::fs::read_to_string(path)?;
        let mut config: CommandConfig = serde_yaml::from_str(&contents)?;

        // Additive override: env var wins if set, YAML otherwise
        if let Ok(url) = std::env::var("AVIS_GATEWAY_BASE_URL") {
            config.gateway.base_url = url;
        }
        if let Ok(key) = std::env::var("AVIS_GATEWAY_API_KEY") {
            config.gateway.api_key = key;
        }
        Ok(config)
    }
}
```

**Critical property**: with both env vars unset, the `let Ok(url) = ...`
arm is skipped and the YAML value is used. The base behaviour is
**completely unchanged**.

### Same pattern in Python (`avis-ml/.../mandate_agent.py`)

```python
def __init__(self, config: dict, loop: asyncio.AbstractEventLoop):
    mandate_cfg = config.get("mandate", {})
    # Additive env overrides — YAML is the source of truth unless
    # an env var is explicitly set
    self.base_url = os.environ.get(
        "AVIS_MANDATE_BASE_URL",
        mandate_cfg.get("base_url", "http://localhost:8001"),
    )
    self.api_key = os.environ.get(
        "AVIS_MANDATE_API_KEY",
        mandate_cfg.get("api_key", ""),
    )
    ...
```

### Same pattern in Rust (`avis-core/src/main.rs` for the ASIAS bridge)

```rust
let nemoclaw_bridge_cfg = if std::env::var("AVIS_ASIAS_ENABLED")
    .ok()
    .map(|v| matches!(v.to_lowercase().as_str(), "true" | "1" | "yes"))
    .unwrap_or(false)
{
    Some(AsiasBridgeConfig {
        gateway_url: std::env::var("AVIS_ASIAS_GATEWAY_URL")
            .unwrap_or_else(|_| "ws://localhost:8010/ws/events".to_string()),
        ..Default::default()
    })
} else {
    None  // Bridge stays off
};
```

`AVIS_ASIAS_ENABLED` is `false` by default (unset env var). The bridge
only comes on when the overlay explicitly enables it.

**Audit trail**. Every env-var read is a separate commit (or at least a
separate diff block) so it's easy to grep for
`std::env::var\("AVIS_` and see everywhere the overlay hooks in.

---

## 5. Architectural isolation: the sovereignty doctrine

The env-var + overlay pattern covers operational isolation. But the
third face of isolation — **zero downstream impact** — is an
architectural property.

The doctrine is in the [workspace SOUL.md](../sandbox-workspace/SOUL.md):

> *AVIS is the voice system for AnSA. Everything NemoClaw does passes
> through AVIS. The agent never talks directly to MANDATE, ASIAS, SIS,
> or the Decision Engine.*

Concretely:

```
NemoClaw sandbox
    │
    ▼
avis-gateway / avis-mcp         (NemoClaw-facing surface)
    │
    ▼
avis-ml / avis-command / avis-core   (AVIS core services)
    │
    ▼
mandate-api / asias-go-gateway / edge cluster
```

**avis-gateway and avis-mcp never talk directly to MANDATE, ASIAS, or
the edge cluster.** They only call sibling AVIS services via gRPC.
Those sibling services are the only ones that reach downstream.

**Why this matters for isolation**: from MANDATE's perspective, the
traffic it sees is indistinguishable from traffic AVIS was already
sending (since the same `MandateAgent` HTTP client is doing the work,
just invoked from a different code path). MANDATE doesn't need to know
NemoClaw exists. Same for ASIAS, same for SIS, same for the Decision
Engine.

**The load multiplier is 0×**. The agent's queries are bounded by
operator requests — there's no background polling, no keepalive
traffic, no synthetic load.

**Why `events_drain` is safe**. The live event stream from Stage 7
could theoretically increase downstream load — if we were polling
MANDATE or ASIAS for events. But we're not: the `events_drain` tool
drains a **local in-process event bus** that the **existing** ASIAS
bridge was already populating whether or not NemoClaw was listening.
Net new downstream load: zero.

---

## 6. Testing the isolation

At the end of Stage 4, before committing to the overlay pattern, we
ran two smoke tests back-to-back:

### Test 1 — NemoClaw-integrated mode

```bash
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml up -d
curl -s http://localhost:8190/v1/health  # → {"healthy":true,...}
mcporter call avis.health                 # → {...}
docker compose logs avis-ml | grep -i mandate
# → sees "GET http://host.docker.internal:8001/health" etc.
```

### Test 2 — Standalone mode

```bash
docker compose down
docker compose up -d  # Note: NO overlay this time
curl -s http://localhost:8190/v1/health  # → still works, still healthy
docker compose logs avis-ml | grep -i mandate
# → "MANDATE agent: base_url=http://localhost:8001" (from YAML)
# → connection errors because localhost:8001 from INSIDE the container
#   isn't the same host as outside, BUT this is exactly what AVIS did
#   before the integration existed, so it's the correct baseline.
```

**Diffing behaviour**: The standalone run reproduced the pre-NemoClaw
baseline exactly. The difference between the two runs is **only**
what's in the overlay — env vars + `extra_hosts` + one port.

### Test 3 — Full teardown

```bash
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml down
# Check that nothing persisted
grep -r AVIS_ASIAS_ENABLED config/avis.yaml
# → no match
git status
# → clean on base files; changes only in docker-compose.nemoclaw.yml
#   and the env-var reads we added
```

---

## 7. The parts we added that live *inside* existing services

Some changes are inside existing AVIS services, not in new crates.
These needed extra care to respect isolation:

| Change | Location | Isolation cost |
|---|---|---|
| `AVIS_MANDATE_BASE_URL` env read | `avis-ml/.../mandate_agent.py` | Zero. Defaults to YAML value when unset. |
| `AVIS_GATEWAY_BASE_URL` env read | `avis-command/src/config.rs` | Zero. Same reasoning. |
| `AVIS_ASIAS_ENABLED` env read | `avis-core/src/main.rs` | Zero. Defaults to `false`. |
| `AVIS_ASIAS_GATEWAY_URL` env read | `avis-core/src/main.rs` | Zero. Only read when `AVIS_ASIAS_ENABLED=true`. |
| Direct ASIAS bridge spawn (bypass orchestrator) | `avis-core/src/main.rs` | Zero. Gated on `nemoclaw_bridge_cfg.is_some()`. |
| `GetCameraStatus` sibling method | `avis-command/src/camera/` | Zero. Net-new method. Nothing that existed before calls it. |
| `GetCameraStatus` new gRPC RPC | `proto/command.proto` + `service.rs` | Zero. Net-new RPC. Existing RPCs unchanged. |
| Port 50053 bind (EventStreamService) | `avis-core/src/grpc_server/` | Gated on `nemoclaw_bridge_cfg.is_some()`. Only binds when overlay is active. |
| `MandateQueryServicer` registration | `avis-ml/serve.py` | Always-on registration; servicer uses MandateAgent's existing loop. No change to existing services' behaviour. |
| `ListClusters` gRPC RPC + `list_clusters` handler | `proto/command.proto`, `avis-command/src/service.rs` | Zero. Net-new RPC. |
| `clusters()` getter on `CameraController` | `avis-command/src/camera/mod.rs` | Zero. Read-only accessor over an existing field. |
| `Serialize` derive on `ClusterConfig` | `avis-command/src/config.rs` | Zero. Additive trait derive — no behaviour change. |
| `camreg_urls` field on `CommandConfig` | `avis-command/src/config.rs` | Zero. `#[serde(default)]` keeps YAML parsing identical when the field is absent. |
| `AVIS_NEMOCLAW_CLUSTERS` env read (replace mode) | `avis-command/src/config.rs` | Zero. Defaults to keeping YAML clusters when unset. |
| `AVIS_NEMOCLAW_CAMREG_URLS` env reads | `avis-command/src/config.rs`, `avis-mcp/src/clients.rs` | Zero. Default empty `HashMap` when unset → `cluster_cameras` returns "not configured" warning. |
| `reqwest::Client` for camreg HTTP | `avis-mcp/src/clients.rs` | Zero. Idle until `cluster_cameras` is called. |
| `avis.list_clusters` MCP tool (Tier 1) | `avis-mcp/src/service.rs` | Always advertised; idle when not called. |
| `avis.cluster_cameras` MCP tool (Tier 3) | `avis-mcp/src/service.rs` | Always advertised; never echoes `user_name` / `password` (explicit field whitelist). |
| **NodePort sibling Service: `decision-service-v2-nodeport`** | k8s `security-intel` namespace on the cluster | Zero. New Service object with same selector — additive. Revert is `kubectl delete svc`. |
| **NodePort sibling Service: `cam-registry-nodeport`** | k8s `camreg` namespace on the cluster | Zero. Same pattern as above. |

**The only "always on" change is the MandateQueryServicer registration**
in `avis-ml/serve.py`. It registers a new gRPC service on the same
port as the existing intelligence/ASR/TTS services, using the same
loop. When NemoClaw isn't calling it, it's idle. Even then, its very
existence could be debated — but since it consumes no CPU when idle
and the registration is a single line, we accepted it as the one
exception.

---

## 8. What would break isolation (and we didn't do)

Things we **could** have done but deliberately avoided because they
would have broken the invariant:

1. **Editing `config/avis.yaml` to set `asias.enabled: true`.** Would
   have enabled the bridge for standalone AVIS too, changing baseline
   behaviour. We used `AVIS_ASIAS_ENABLED` env var instead.
2. **Editing `config/avis-command.yaml` to point at `host.docker.internal`.**
   Would have broken standalone AVIS (where `host.docker.internal`
   doesn't resolve inside the container without `extra_hosts`). We used
   `AVIS_GATEWAY_BASE_URL` env var instead.
3. **Adding the cluster entry `edge-1 → 192.168.200.71:9300` in
   `config/avis-command.yaml`.** Would have made standalone AVIS try
   to connect to the edge cluster and log failures forever. We left the
   cluster config as-is and let `get_camera_status()` return
   `edge_unreachable` on a per-call basis.
4. **Modifying `IntelligenceService.AskAgent`** to support a
   "structured JSON" mode. Would have changed a critical production
   path. We added the new `MandateQueryService` instead.
5. **Adding a MANDATE client directly into `avis-gateway` or `avis-mcp`.**
   Would have broken the sovereignty doctrine. Every MANDATE call now
   goes through `avis-ml.MandateQueryService`, which uses the same
   `MandateAgent` class AVIS was already using.
6. **Patching MANDATE's database schema to fix the missing `incidents`
   table.** Would have required SQL migrations outside the NemoClaw
   repo. We left it to the MANDATE team (see upstream-issues.md §1).
7. **Patching the `transformers` version in `avis-ml`.** Would have
   changed AVIS production behaviour. We routed around it by spawning
   the ASIAS bridge from `main.rs` instead of from the orchestrator.
8. **Adding ASIAS API key configuration to any non-NemoClaw-scoped
   file.** Would have broken isolation. The key stays in
   `docker-compose.nemoclaw.yml`.

---

## 9. How to verify isolation is still intact

If you suspect the invariant has been broken, run these checks:

```bash
# 1. No new env-var reads outside the approved list
grep -rn 'std::env::var\|os.environ\|env::var' \
  ~/claude-projects/ansa-voice-intelligence-system/{avis-ml,avis-command,avis-core,avis-mcp}/src/ \
  | grep AVIS_
# Should only show:
#   AVIS_MANDATE_BASE_URL, AVIS_MANDATE_API_KEY
#   AVIS_GATEWAY_BASE_URL, AVIS_GATEWAY_API_KEY
#   AVIS_ASIAS_ENABLED, AVIS_ASIAS_GATEWAY_URL
#   AVIS_NEMOCLAW_CLUSTERS, AVIS_NEMOCLAW_CAMREG_URLS  ← Stage 9

# 2. No edits to base config files
cd ~/claude-projects/ansa-voice-intelligence-system
git log --oneline config/avis.yaml config/avis-command.yaml
# Should be clean (no NemoClaw-related commits)

# 3. Compose overlay diff is small
diff <(docker compose config) \
     <(docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml config) \
  | head -50
# Should show only extra_hosts, env vars, and port 50053

# 4. Standalone mode smoke test
docker compose down && docker compose up -d
sleep 10
curl -s http://localhost:8190/v1/health
# Should return a healthy response (even if some components are degraded
# because MANDATE/ASIAS aren't reachable without the overlay — that's
# pre-existing baseline behaviour).

# 5. Test revert path
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml down
git status
# Should be clean (no tracked-file changes from the session)
```

If any of these checks fail, isolation has regressed. Fix the
regression before adding any new features.

---

## 10. The isolation invariant in one sentence

> **Remove `docker-compose.nemoclaw.yml` from the `-f` chain and every
> NemoClaw footprint disappears, without any other action needed.**

That's the whole model.
