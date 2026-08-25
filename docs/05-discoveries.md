# 05 — Discoveries

Twelve non-obvious things we learned during the eight stages. Each entry
is structured as **Symptom → Investigation → Root cause → Fix → Lesson**
so the next person hitting the same wall can walk straight to the fix.

The order is roughly chronological, not by importance. The ones marked
⭐ cost the most hours.

---

## 1. The `allowed_ips` SSRF bypass ⭐

**Symptom**. From inside the NemoClaw sandbox, every curl / mcporter /
node fetch to `avis-gateway:8090` or any RFC 1918 address returned
`HTTP 403 forbidden`. The sandbox could reach the public internet but
not the Docker network the AVIS containers lived on. Logs from the
OpenShell egress proxy showed `SSRF_BLOCKED: destination in private range`.

**Investigation**. First hypothesis: missing DNS entry. Added
`host.openshell.internal` explicitly — still blocked. Second hypothesis:
missing `binaries` in the policy preset — added curl, node, mcporter —
still blocked. Third: `access: tls` vs `access: full` — tried both, still
blocked. Finally WebSearch found a GitHub issue on NVIDIA/OpenShell
referencing `allowed_ips` as a CIDR allowlist field that overrides the
SSRF safety check. Total time: ~4 hours.

**Root cause**. OpenShell's egress proxy has a **hardcoded RFC 1918 SSRF
block** that cannot be overridden by `access`, `binaries`, or any
allowlist field **except** `allowed_ips`. The field is intended as a
narrow escape hatch for developers with private-network backends and is
not documented in the default policy schema — only in an example file
at `examples/private-ip-routing.yaml`.

**Fix**. Add the AVIS Docker network CIDR to both policy presets:

```yaml
# ~/NemoClaw/nemoclaw-blueprint/policies/presets/avis.yaml
hosts:
  avis-gateway:
    address: avis-gateway:8090
    access: full
    allowed_ips: ["172.23.0.0/16"]  # ← the key line
    binaries: [/usr/local/bin/node, /usr/local/bin/openclaw, /usr/bin/curl]
```

The `172.23.0.0/16` value is the `ansa-voice-intelligence-system_default`
Docker network CIDR. Check yours with
`docker network inspect ansa-voice-intelligence-system_default | jq '.[0].IPAM.Config'`.

**Lesson**. When an OSS tool has an undocumented escape hatch, it's
usually in `examples/`. Search the repo, not the docs. Second lesson:
the SSRF block in proxies like OpenShell is not bypassable via policy
hierarchy — it's a separate code path, and you need the explicit allowlist.

---

## 2. `host.docker.internal` is still the cleanest cross-compose bridge

**Symptom**. Stage 4 needed `avis-command` to reach `mandate-api`
(running in a different docker compose project) and `asias-go-gateway`
(yet another project). Direct Docker DNS (`mandate-api:8001`) doesn't
work across compose projects.

**Investigation**. Three options considered:

- **A. `extra_hosts: ["host.docker.internal:host-gateway"]`** plus
  `host.docker.internal:<host-port>`. Zero compose file edits in the
  other projects. avis-* talks over the host's published ports.
- **B. `docker network connect mandate_default`** for each avis-* service.
  Containers gain extra interfaces. More surgery.
- **C. Shared external network** across all four projects. Cleanest
  architecture but requires editing everyone else's compose file.

**Root cause** (of why we picked A). The isolation invariant says "don't
touch other projects' compose files". Pattern B still has some risk
(duplicate network interface ordering bugs) and requires shell steps
not captured in any file. Pattern A is one YAML stanza in an overlay.

**Fix**. In `docker-compose.nemoclaw.yml`:

```yaml
avis-command:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

Plus env var overrides pointing at the host ports
(`http://host.docker.internal:8001`, `:8010`).

**Lesson**. `host.docker.internal:host-gateway` is the universal "I
don't want to care about your network topology" bridge. It's ugly (you
route container-to-container traffic via the host) but it's immune to
anything happening in the other projects.

---

## 3. `[::1]` vs `[::]` — the IPv6 loopback gotcha ⭐

**Symptom**. `avis-gateway` inside one container couldn't reach
`avis-command` in a sibling container despite them being on the same
Docker network. Error: `tonic::transport::Error { source: Connection refused }`.
`docker exec avis-gateway telnet avis-command 50052` → connection refused.
Meanwhile, `docker exec avis-command netstat -tln | grep 50052` showed
it listening.

**Investigation**. Checked listening socket details:

```
docker exec avis-command netstat -tln | grep 50052
tcp6       0      0 ::1:50052               :::*                    LISTEN
```

`::1` not `::`. The service was bound to IPv6 loopback only, not all
interfaces. Sibling containers can reach each other via IPv4 DNS, which
doesn't resolve to `::1`.

**Root cause**. `avis-command/src/main.rs` called `Server::bind("[::1]:50052")`
— loopback-only. Either a copy/paste from a localhost-only test
deployment or a defensive default that nobody flipped. Either way it
made the service unreachable from outside its own network namespace.

**Fix**. One character:

```rust
// before
let addr = "[::1]:50052".parse().unwrap();
// after
let addr = "[::]:50052".parse().unwrap();
```

`[::]` is the IPv6 wildcard — binds to all interfaces and accepts both
v4 and v6 connections (on Linux with dual-stack).

**Lesson**. Always check the actual listening socket (`netstat -tln`
inside the container) when a connection is refused. The source code and
the runtime can disagree. Also, `[::1]:` in any `bind()` call is a
red flag unless the thing is deliberately private.

---

## 4. rmcp 0.16 has no `ServerInfo::new()` or `StreamableHttpServerConfig::with_cancellation_token()` ⭐

**Symptom**. Stage 3. Wrote `avis-mcp` based on rmcp-ecosystem example
code from a WebFetch search result. First `cargo build` failed with:

```
error[E0599]: no function or associated item named `new` found for struct
  `rmcp::model::ServerInfo` in the current scope
error[E0599]: no method named `with_cancellation_token` found for struct
  `StreamableHttpServerConfig`
```

**Investigation**. WebFetch had quoted example code from a stale blog
post (pre-0.16). Checked the actual rmcp crate in the local registry:

```
~/.cargo/registry/src/index.crates.io-*/rmcp-0.16.0/src/model.rs
~/.cargo/registry/src/index.crates.io-*/rmcp-0.16.0/src/transport/streamable_http_server/mod.rs
```

`ServerInfo` is a plain struct with public fields, not a builder.
`StreamableHttpServerConfig` is likewise a struct-literal target, not
builder.

**Root cause**. rmcp is an unstable crate. Docs.rs builds are often
behind, blog posts are pre-0.16, and WebFetch was returning an example
that had been valid 3 months ago. The crate author changed the API to
struct-literal form and the docs haven't caught up.

**Fix**. Use struct-literal syntax instead of builder calls:

```rust
// before (hallucinated from old blog)
let info = ServerInfo::new("avis", "0.1.0")
    .with_protocol_version(ProtocolVersion::LATEST);
let cfg = StreamableHttpServerConfig::default()
    .with_cancellation_token(ct.child_token());

// after (actual rmcp 0.16)
let info = ServerInfo {
    protocol_version: ProtocolVersion::LATEST,
    capabilities: ServerCapabilities::builder().enable_tools().build(),
    server_info: Implementation {
        name: "avis-mcp".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        title: None,
        ..Default::default()
    },
    instructions: None,
    ..Default::default()
};
let cfg = StreamableHttpServerConfig {
    cancellation_token: ct.child_token(),
    ..Default::default()
};
```

**Lesson**. For unstable crates, **always read the local registry
source** (`~/.cargo/registry/src/...`) instead of trusting blog posts,
WebFetch results, or even docs.rs. `cargo doc --open` on the specific
version you have installed is ground truth.

---

## 5. `httpx.AsyncClient` connection pools are loop-bound ⭐

**Symptom**. Stage 5. First iteration of `MandateQueryServicer`
(Python, inside avis-ml) worked on the first call and then blew up on
every subsequent call with:

```
RuntimeError: Event loop is closed
```

The servicer was async-on-top-of-sync: sync gRPC methods calling
`asyncio.run()` internally. Each call was creating a fresh loop.

**Investigation**. Looked at how `IntelligenceServiceServicer` in the
same file solved the same problem. It holds a `self._loop =
asyncio.new_event_loop()` created once at startup and runs all async
calls on that loop via `asyncio.run_coroutine_threadsafe`. The
`httpx.AsyncClient` inside the agent is also built on that loop — and
its connection pool is tied to it.

**Root cause**. httpx's AsyncClient binds its connection pool (and
underlying SSL context) to the event loop that created it. When you
create a new loop per call with `asyncio.run()`, the client's internal
state references a loop that no longer exists on call #2.

**Fix**. Share `IntelligenceServiceServicer._loop` with
`MandateQueryServicer` via constructor injection:

```python
# avis-ml/serve.py
intelligence_servicer = IntelligenceServiceServicer(config)
mandate_query_servicer = MandateQueryServicer(
    mandate_agent=intelligence_servicer.mandate_agent,
    loop=intelligence_servicer._loop,   # ← share the loop
)
```

And in the servicer:

```python
def _run_coro(self, coro):
    future = asyncio.run_coroutine_threadsafe(coro, self._loop)
    return future.result(timeout=30)

def ListActiveIncidents(self, request, context):
    return self._run_coro(self._do_list_active_incidents())
```

**Lesson**. In sync Python gRPC servers that need async HTTP clients,
**never create a new event loop per call**. Create one at service
startup, park it on a background thread, and send coroutines into it
via `run_coroutine_threadsafe`.

---

## 6. tonic `.timeout()` vs `.connect_timeout()` ⭐

**Symptom**. Stage 8. `avis.camera_status cluster_id=edge-1` (Tier 3)
hung for **134 seconds** before returning `edge_unreachable`. All other
tools returned promptly. The cluster was unreachable by design (dev box
has no route to `192.168.200.71`), and we *wanted* a fast failure.

**Investigation**. Checked `avis-command/src/camera/cluster_client.rs`:

```rust
let channel = Channel::from_shared(endpoint_url)?
    .timeout(Duration::from_millis(self.timeout_ms))
    .connect().await?;
```

`.timeout()` was set (3 seconds). Yet the `.connect()` call itself was
hanging for ~130 seconds. Tracing into tonic source revealed the
distinction: `.timeout()` applies to **per-call RPCs**, not to the
initial TCP connect. The initial connect uses tokio's default, which has
**no deadline** — it waits the full Linux kernel SYN_SENT timeout
(which on this box is around 130s across 3 retries).

**Root cause**. tonic's `Endpoint::connect_timeout()` is a **separate
setter** from `.timeout()`. `.timeout()` caps RPC duration after the
channel is established. Without `.connect_timeout()`, the TCP handshake
hangs for the kernel default.

**Fix**. Add `.connect_timeout()` explicitly:

```rust
let channel = Channel::from_shared(endpoint_url)?
    .timeout(Duration::from_millis(self.timeout_ms))
    .connect_timeout(Duration::from_millis(self.timeout_ms))  // ← new
    .connect().await?;
```

With this, `avis.camera_status` returns `edge_unreachable` in under 3
seconds when the cluster is down.

**Lesson**. In tonic, **both** `.timeout()` and `.connect_timeout()`
need to be set if you want fast failure. The separation exists because
some workloads want a long connect (bursty traffic) with short per-call
timeouts — but that's an unusual default for security/ops work. Always
set both.

---

## 7. mcporter numeric-args caveat

**Symptom**. Stage 8 testing:

```bash
mcporter call avis.camera_pan_tilt_zoom \
  camera_id=LAG-001 pan=45.0 tilt=0.0 zoom=1.5 \
  operator_confirm=true operator_id=scosaje
```

→ rmcp server rejected with:

```
invalid type: string "45.0", expected f32
```

**Root cause**. mcporter's shorthand `key=value` form passes everything
as **strings**. The rmcp tool schema declares `pan`, `tilt`, `zoom` as
`f32` and `operator_confirm` as `bool`. rmcp's deserializer does not do
implicit string-to-number coercion.

**Fix** (workaround, not a code change). Use the `--args` JSON form:

```bash
mcporter call avis.camera_pan_tilt_zoom \
  --args '{"camera_id":"LAG-001","pan":45.0,"tilt":0.0,"zoom":1.5,
           "operator_confirm":true,"operator_id":"scosaje"}'
```

**Lesson**. mcporter shorthand is ergonomic for string-only tools and
broken for anything typed. If a tool has any non-string parameter,
document the `--args` form as the default. (The tools reference doc does.)

---

## 8. avis-core's orchestrator startup was too brittle to reuse

**Symptom**. Stage 7. The plan was to enable the ASIAS bridge by
setting `AVIS_ASIAS_ENABLED=true` and letting
`orchestrator::startup_sequence()` pick it up at step 3.8 like the
original design. But `avis-core` wouldn't boot — it crashed at step 2.3
(TTS warmup) with:

```
AttributeError: module 'transformers' has no attribute 'isin_mps_friendly'
```

The orchestrator uses `?` error propagation, so a step-2 failure
prevented step-3.8 from ever running, which meant the ASIAS bridge
never started.

**Root cause**. `orchestrator::startup_sequence()` is a linear chain of
`.await?` calls. A failure anywhere aborts everything. The TTS warmup
hit an upstream `transformers` library version incompatibility. We did
NOT want to fix the TTS warmup (it's not our code, and fixing it would
blow the isolation invariant — see upstream-issues.md §3) — but we
also couldn't let TTS block the ASIAS bridge.

**Fix**. Spawn the ASIAS bridge **directly from `main.rs`**, outside of
`orchestrator::startup_sequence()`:

```rust
// avis-core/src/main.rs
let nemoclaw_bridge_cfg = if std::env::var("AVIS_ASIAS_ENABLED")
    .ok()
    .map(|v| matches!(v.to_lowercase().as_str(), "true" | "1" | "yes"))
    .unwrap_or(false)
{
    let url = std::env::var("AVIS_ASIAS_GATEWAY_URL")
        .unwrap_or_else(|_| "ws://localhost:8010/ws/events".to_string());
    Some(AsiasBridgeConfig { gateway_url: url, ..Default::default() })
} else {
    None
};

// ... later, after event_bus creation, BEFORE the orchestrator starts ...

if let Some(bridge_cfg) = nemoclaw_bridge_cfg {
    let bridge_bus = event_bus.clone();
    tokio::spawn(async move {
        let bridge = crate::asias::bridge::AsiasBridge::new(bridge_cfg, bridge_bus);
        bridge.run().await;
    });
    tracing::info!("NemoClaw ASIAS bridge spawned from main");
}

// Now the orchestrator can crash and the bridge keeps running.
```

**Lesson**. Don't depend on other people's startup sequences if the
sequence is a chain of `?` calls. Isolate critical bootstraps into
their own `tokio::spawn`. The bridge now lives through TTS failures,
orchestrator restarts, and anything else step-2 might throw at it.

---

## 9. JSON passthrough envelope beats proto-mapping

**Context** (Stage 5). MANDATE's voice query endpoints return
free-form JSON that changes shape between endpoints and between
versions. We considered two options for `MandateQueryService`:

- **A. Proto-mapped response messages** — define an `Incident` proto
  message, a `Workflow` proto message, etc. Typed. Brittle. Every
  MANDATE schema change breaks the proto.
- **B. JSON passthrough envelope** — one universal response type:

  ```proto
  message JsonResponse {
    string payload_json = 1;
    int32 count = 2;
    int32 http_status = 3;
  }
  ```

**Decision**. Picked B. The `payload_json` field is the raw MANDATE
response body, the `count` is a convenience for list endpoints, and
`http_status` propagates upstream HTTP status for error diagnosis.

**Trade-off**. The agent has to parse a JSON string at the end of the
wire. But since the agent is Claude, it's incredibly good at that.
Meanwhile, the proto never has to change when MANDATE adds a field.

**Lesson**. When wrapping a REST API over gRPC for an LLM agent, **use
a JSON passthrough envelope** unless you have a strong static-typing
reason not to. LLMs eat JSON strings for breakfast; what you gain in
flexibility outweighs what you lose in static guarantees.

---

## 10. `broadcast::Receiver::Lagged` is not an error

**Context** (Stage 7). The new `EventStreamService` in `avis-core`
wraps `tokio::sync::broadcast::Receiver`. When the subscriber falls
behind (e.g., a slow client drains too slowly), tokio returns
`RecvError::Lagged(skipped)` instead of silently dropping events.

First implementation treated this as a stream termination — the agent
saw an empty buffer after the first real event and assumed the server
was broken.

**Fix**. Handle `Lagged` as a warning, not an error:

```rust
loop {
    match rx.recv().await {
        Ok(event) => {
            if matches_filter(&event, &req) {
                yield EventEnvelope::from(event);
            }
        }
        Err(broadcast::error::RecvError::Lagged(n)) => {
            tracing::warn!("event_stream: subscriber lagged, skipped {} events", n);
            continue; // keep going, don't terminate the stream
        }
        Err(broadcast::error::RecvError::Closed) => {
            tracing::info!("event_stream: broadcast channel closed, ending stream");
            break;
        }
    }
}
```

**Lesson**. `broadcast::Receiver` is a "best-effort fan-out" channel —
if a subscriber can't keep up, tokio drops events for that subscriber
and returns `Lagged(n)` on the next recv. It's a signal, not an error.
Log it, possibly surface it in metrics, and continue.

---

## 11. Propagating cluster unreachable as a typed result

**Context** (Stage 8). The existing `avis-command` camera methods
(`set_ptz`, `start_recording`, etc.) **swallow** cluster unreachable
errors. They log "cluster unreachable, storing locally" and return
`Ok(())`. Fine for a fire-and-forget mutation; terrible for a
read-your-writes Tier-3 probe.

We needed `avis.camera_status` to return a **typed unreachable signal**
so the agent could reason about it. But touching the existing mutation
methods would change their semantics and break the mutation path.

**Fix**. Added a **new method** `get_camera_status` that does NOT
swallow the error:

```rust
// avis-command/src/camera/cluster_client.rs
pub async fn get_camera_status(
    &mut self,
    camera_id: &str,
) -> Result<Vec<edge_proto::CameraInfo>> {
    let req = edge_proto::CameraStatusRequest {
        camera_id: camera_id.to_string(),
    };
    match self.ensure_connected().await {
        Ok(client) => {
            let resp = client.get_camera_status(req).await
                .context("GetCameraStatus RPC failed")?;
            Ok(resp.into_inner().cameras)
        }
        Err(e) => {
            self.reset();
            Err(e)  // ← propagated, NOT swallowed
        }
    }
}
```

`avis-command/src/camera/mod.rs` then returns an `Either<Vec<CameraInfo>, String>`
to the gRPC service handler, which translates `Err` into
`success=false + error="edge_unreachable"` on the proto response. The
gateway and MCP layers see a structured response and re-emit it
faithfully.

**Lesson**. When an existing method has the "wrong" error-handling
semantics for a new use case, **don't change the existing method**.
Add a new sibling method. The old callers keep their ergonomics, the
new callers get what they need, and nobody has to audit every existing
call site.

---

## 12. Docker network re-attachment after onboard

**Symptom**. After running `./nemoclaw onboard`, the sandbox container
couldn't reach `avis-gateway` via Docker DNS (it resolved fine via
`host.openshell.internal` through the proxy, but direct container-to-
container resolution was broken for a couple of MCP flows).

**Root cause**. `nemoclaw onboard` creates the sandbox container on
its own Docker network (`openshell_default` or similar). The sandbox
is not attached to `ansa-voice-intelligence-system_default` by default.
OpenShell's egress proxy bridges traffic at the policy layer, but
Docker DNS resolution is network-scoped.

**Fix**. Connect the sandbox to the AVIS network after onboard:

```bash
docker network connect \
  ansa-voice-intelligence-system_default \
  openshell-ansa-assistant
```

This is now in the runbook (§3.5) as a mandatory post-onboard step.

**Lesson**. If you have two docker compose projects that need
container-level DNS between them, a shell step to `docker network
connect` is unavoidable unless you share an external network. Document
the step in onboarding so it doesn't get forgotten after every cold
reset.

---

## Honourable mentions (didn't rate full write-ups)

- **`Cargo.toml` rust edition mismatch**: `schemars` + `darling`
  required a newer Rust than the `rust:1.86` base image in
  `Dockerfile.mcp`. Bumped to `rust:1.93`. One-line fix.
- **Base64 auth header formatting**: MANDATE expects
  `Authorization: Basic <b64(devkey:dev)>`. The first cut omitted the
  `Basic ` prefix. HTTP 401. Easy.
- **Port 8090 was already in use on the host** when another project
  had squatted it. Remapped host port 8090→8190 while keeping
  container port 8090 — avoids editing any AVIS code.
- **`axum::extract::FromRequestParts` lifetime**: the `OperatorConfirm`
  extractor hit a lifetime mismatch on the first write. Switched from
  `impl FromRequest` to `impl FromRequestParts` — the former takes
  ownership of the body and breaks the rest of the handler.
- **Schema generation for rmcp**: `#[derive(JsonSchema)]` required
  pulling in `schemars 0.8` with the `derive` feature, which in turn
  pulled `darling` and forced the Rust version bump above. Chain reaction.
