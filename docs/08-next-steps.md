# 08 — Next Steps

Optional enhancements that would strengthen the NemoClaw ↔ AnSA
integration beyond the Stage-8 baseline. Nothing here is required for
the PoC. Each item is scoped, justified, and labelled by effort
(S / M / L) and risk (low / med / high).

Ordering reflects what would give the biggest operational uplift for
the least work — not architectural purity.

---

## Category 1 — Hardening (security & correctness)

### 1.1 Replace `devkey:dev` with real service keys [S, low]

**Why**. Every downstream API currently trusts the hardcoded
`devkey:dev` shared secret. Fine for PoC, embarrassing for anything
touching real operators.

**What**. Introduce a `docker-compose.nemoclaw.yml` sibling
`.secrets` file (gitignored) that carries `AVIS_MANDATE_API_KEY`,
`AVIS_GATEWAY_API_KEY`, and any future keys. Load via:

```yaml
# docker-compose.nemoclaw.yml
services:
  avis-command:
    env_file:
      - .secrets.nemoclaw
```

Also addresses [upstream-issues.md §2](./07-upstream-issues.md#2-asias-api-key-mismatch)
by making the key configurable per environment.

**Risk**. Low. No protocol changes. Keys stay scoped to the overlay.

### 1.2 Rate-limit Tier-4 / Tier-5 tools at the MCP boundary [S, low]

**Why**. Agent doctrine says "never auto-act", but a prompt-injection
or runaway loop could still burn through the operator_confirm gate.
A rate limiter at the MCP server adds a cheap defence in depth.

**What**. Token-bucket rate limiter in `avis-mcp` keyed on
`operator_id`. Configurable per tier:

- Tier 4: 10 calls / 5 min per operator
- Tier 5: 3 calls / 5 min per operator

Exceeded → tool returns a structured error with `retry_after_seconds`.
Audit log captures the throttled attempt.

**Risk**. Low. Rate limits cost little and fail open (current
behaviour) if the bucket store is unavailable.

### 1.3 Sign audit log lines [M, low]

**Why**. The current audit logs (`data/avis-mcp-audit.jsonl` and
`data/avis-gateway-audit.jsonl`) are plain JSONL files. An attacker
with write access to the host could edit history silently.

**What**. HMAC-sign each line with a key rotated daily:

```json
{
  "ts": "2026-04-07T04:12:33.142Z",
  "tier": 4,
  "tool": "avis.alert_escalate",
  "operator_id": "scosaje",
  "upstream_status": "ok",
  "prev_hash": "sha256:...",
  "hmac": "hmac-sha256:..."
}
```

Chained by `prev_hash` so edits anywhere break the chain. Verification
script at `tools/audit-verify.py`.

**Risk**. Low. Additive to existing log lines. Verification is
off-path.

### 1.4 Move `operator_confirm` from honour-system to voiceprint binding [L, med]

**Why**. Currently the agent enforces "operator instruction in the
current turn" via AGENTS.md discipline — an honour system. A compromised
agent could skip the check.

**What**. Bind `operator_confirm` to the most recent successful
`voiceprint_verify` call. The MCP server would track:

```rust
struct OperatorSession {
    operator_id: String,
    verified_at: Instant,
    clearance_level: u8,
}
```

and reject Tier-4/5 calls where `verified_at > 5 minutes ago`. Puts
the enforcement at the boundary, not inside agent doctrine.

**Risk**. Medium. Changes tool semantics. Requires real voiceprint
data and a test operator identity. Would also need to handle sessions
across mcporter invocations — possibly a side-channel file in
`~/.avis-session.json`.

---

## Category 2 — Observability

### 2.1 Prometheus metrics on avis-gateway and avis-mcp [M, low]

**Why**. Currently the only observability is tail-the-logs. No
time-series, no dashboards, no alerts.

**What**. Expose `/metrics` on each service (`:8190/metrics` and
`:8091/metrics`). Standard metrics:

- `avis_tool_calls_total{tool,tier,status}` — counter
- `avis_tool_latency_seconds{tool,tier}` — histogram
- `avis_tier_refusals_total{tool,reason}` — counter
- `avis_edge_unreachable_total{cluster_id}` — counter
- `avis_events_drained_total{event_kind}` — counter (Stage 7 bus)

Prometheus already runs in the AnSA stack (check with
`docker ps | grep prometheus`). Add a scrape config targeting the
two endpoints.

**Risk**. Low. Metrics are read-only, independent of the tool path.

### 2.2 Grafana dashboard for NemoClaw [S after 2.1, low]

Prebuilt Grafana dashboard showing:

- Per-tier call rate over time
- Tier-4/5 refusal rate vs success rate
- Edge reachability health
- Top-N tools by latency
- SIS event drain rate

Ship as JSON in `ops/grafana/nemoclaw-dashboard.json`.

### 2.3 Structured logging with span IDs [M, low]

**Why**. Right now a single agent turn that calls 3 tools produces
3 unrelated audit log lines. Hard to correlate.

**What**. Introduce a `turn_id` header that the agent generates once
per operator turn and passes on every tool call. Audit logs record it.
Grep-able correlation across services.

```bash
grep '"turn_id":"TURN-abc123"' data/avis-*-audit.jsonl
```

**Risk**. Low. Header is optional and additive.

### 2.4 OpenTelemetry tracing [L, med]

**Why**. Turn IDs are OK for grep, but real distributed tracing
(agent → MCP → gateway → gRPC → downstream) would expose latency
bottlenecks clearly.

**What**. Add `tracing-opentelemetry` subscriber to Rust services,
`opentelemetry-sdk` to `avis-ml`. Ship to Jaeger or similar.

**Risk**. Medium. Adds dependencies and a trace collector.

---

## Category 3 — Additional integrations

### 3.1 NIMC biometric lookup [M, med]

**Why**. The agent can query MANDATE for POI context but can't verify
an identity against Nigeria's National Identity Management Commission
(NIMC). NIMC integration is on the AnSA roadmap; when it lands, the
agent should get a `avis.nimc_verify_identity` tool.

**What**. New Tier-4 tool wrapping the existing NIMC service (when
available). Shape:

```proto
rpc VerifyIdentity(NimcRequest) returns (NimcResponse);
// NimcRequest { nin: string, operator_id: string, operator_confirm: bool }
// NimcResponse { matched: bool, full_name: string, state_of_origin: string, ... }
```

**Risk**. Medium. Depends on NIMC service availability and
data-sovereignty clearance. Tier-4 because identity lookups leave a
trail and the regulator watches.

### 3.2 Multi-edge-cluster support [M, low]

**Why**. Today `config/avis-command.yaml` has one edge cluster
(`edge-1`). A full AnSA deployment has many (one per LGA / zone).

**What**. `avis.camera_status` already accepts `cluster_id`. The
config already supports multiple cluster entries. The gap is:

1. A `avis.list_clusters` Tier-1 tool that returns the known list
2. AGENTS.md guidance on picking the right cluster based on camera_id
   prefix (e.g. `LAG-*` → `edge-lagos`, `ABJ-*` → `edge-abuja`)
3. Audit log enhancement to capture which cluster served a Tier-5 call

**Risk**. Low. Additive tool, config already scales.

### 3.3 Temporal workflow introspection [M, low]

**Why**. MANDATE uses Temporal for workflow orchestration. Today the
agent sees workflow *metadata* via `mandate_list_active_workflows` but
can't inspect a specific workflow's history.

**What**. Add `avis.mandate_workflow_history` Tier-3 tool that
proxies to Temporal's query API:

- Inputs: `workflow_id`
- Outputs: step-by-step history with timestamps, activities, retries

Helpful for the agent when the operator asks "what's happening with
workflow WF-2026-0142".

**Risk**. Low. Read-only against Temporal's own history service.

### 3.4 Two-way SIS command channel [L, high]

**Why**. Currently SIS → NemoClaw is one-way (events flow up, nothing
flows down). Some operational scenarios might justify the reverse —
e.g. "ack a SIS detection so the edge stops re-reporting it".

**What**. New `avis.sis_ack_detection` Tier-4 tool. Requires a new
proto RPC on SIS's side, which means coordination with the SIS team.

**Risk**. High. Changes the SIS contract, breaks the "SIS needs zero
changes" invariant that underwrote Stage 7. Only pursue if there's a
real operator need.

---

## Category 4 — Developer experience

### 4.1 `nemoclaw status` one-liner [S, low]

**Why**. Right now checking the stack's health means running 5–6
commands. Should be one.

**What**. Shell script at `tools/nemoclaw-status.sh`:

```bash
#!/usr/bin/env bash
# Aggregated health of the NemoClaw ↔ AnSA bridge
echo "=== containers ==="
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml ps
echo "=== avis-gateway health ==="
curl -s http://localhost:8190/v1/health | jq
echo "=== sandbox reachability ==="
ssh -o ConnectTimeout=3 openshell-ansa-assistant 'mcporter call avis.health' 2>&1 || echo "sandbox unreachable"
echo "=== edge cluster ==="
curl -s http://localhost:8190/v1/decision-engine/camera/status?cluster_id=edge-1 | jq
echo "=== audit tail (last 5 Tier≥3) ==="
tail -50 data/avis-mcp-audit.jsonl | jq -c 'select(.tier >= 3)' | tail -5
```

### 4.2 Integration test suite [M, low]

**Why**. Currently verification is manual. A CI-friendly test suite
would catch regressions before re-deploy.

**What**. Pytest-based suite at `tests/integration/` that:

1. Brings up the full overlay stack
2. Hits every tool once with minimal valid inputs
3. Verifies Tier-3/4/5 refusal paths (missing `operator_confirm`)
4. Verifies Tier-1/2 always succeed
5. Verifies audit log line-count matches call-count

Runs in ~2 minutes. Skipped tests for tools that depend on unreachable
upstreams (edge cluster, MANDATE `incidents` table).

### 4.3 Stub edge cluster [M, low]

**Why**. See [upstream-issues.md §4](./07-upstream-issues.md#4-placeholder-edge-cluster-ips).
A CPU-only stub of `edge.CommandReceiverService` would unblock
positive-path Tier-5 testing without real Jetson hardware.

**What**. Rust binary at `tools/edge-stub/` implementing
`CommandReceiverService` with canned responses. Bound to
`127.0.0.1:9300`. `docker-compose.nemoclaw.yml` gets an optional
profile:

```yaml
profiles: [dev-edge-stub]
services:
  edge-stub:
    image: nemoclaw-edge-stub:latest
    network_mode: host
```

Run with `docker compose --profile dev-edge-stub up -d`.

### 4.4 MCP tool schema tests [S, low]

**Why**. `schemars::JsonSchema` generates schemas from Rust types,
but we've never tested that the generated schemas match what rmcp
advertises or what mcporter expects.

**What**. A single Rust test that:

1. Starts `avis-mcp` in-process
2. Calls `tools/list`
3. Asserts each tool has the expected input schema fields
4. Asserts numeric-typed fields are advertised as numbers (not strings)

Would catch any regression from the fixes around the mcporter
numeric-args caveat.

---

## Category 5 — Documentation & onboarding

### 5.1 Teach the agent about known edge cases [S, low]

**Why**. The agent currently relies on `AGENTS.md` doctrine to
navigate upstream issues (MANDATE incidents table, ASIAS key mismatch,
edge unreachable). Adding explicit "common failure → what to say"
patterns in AGENTS.md would reduce operator confusion.

**What**. New section in AGENTS.md:

```markdown
## Known failure modes (dev env)

If you see:
- MANDATE HTTP 500 on incidents-related tools: say
  "MANDATE is missing the incidents table in this dev environment.
   I'll use workflows and tasking data instead."
- ASIAS HTTP 401 on Tier-4 mutations: say
  "The dev API key doesn't match what ASIAS expects. This needs the
   ASIAS team to align SERVICE_API_KEY. I cannot dispatch on this env."
- edge_unreachable from Tier-3 or Tier-5: say
  "The edge cluster isn't reachable from this deployment. I can
   reason about camera state from the last known metadata, but
   I can't physically control anything."
```

### 5.2 Architecture Decision Records (ADRs) [M, low]

**Why**. `02-stages.md` captures *what* was done; `05-discoveries.md`
captures *surprises*. Neither captures *why this shape, not the other*.

**What**. `docs/adrs/` with one file per major decision:

- ADR-001: Why we chose gRPC + proto for AVIS internals
- ADR-002: Why rmcp streamable-http-server (not stdio)
- ADR-003: Why JSON passthrough envelope for MANDATE queries
- ADR-004: Why overlay pattern for isolation
- ADR-005: Why spawn ASIAS bridge from main.rs
- ADR-006: Why 5-tier authorisation scheme
- ADR-007: Why `avis.events_drain` (polling) vs streaming MCP

Format: Nygard ADR template (context, decision, consequences, status).

### 5.3 Operator playbook [M, low]

**Why**. `04-runbook.md` is for the developer running the stack. A
separate **operator playbook** in Nigerian-English register would help
actual AnSA operators understand what to ask the agent.

**What**. `docs/operator-playbook.md`:

- What the agent can see and do at each tier
- Example conversations in Nigerian register
- Emergency procedures
- Contact list for each upstream team

---

## Priority ranking (recommended order)

If you were to tackle a subset, this is the order I'd suggest:

1. **1.1 Replace devkey** — unblocks Tier-4 positive-path testing
   (depends on ASIAS team alignment).
2. **4.1 `nemoclaw status` script** — immediate dev ergonomics win.
3. **4.3 Stub edge cluster** — unblocks Tier-5 positive-path testing.
4. **2.1 Prometheus metrics** — gives you observability before you
   need it to debug.
5. **4.2 Integration test suite** — catches regressions from here on.
6. **1.2 Rate limiting** — cheap, material security win.
7. **5.1 AGENTS.md failure modes** — reduces operator confusion.
8. **3.2 Multi-edge-cluster** — once there's more than one cluster.
9. **2.3 Structured logging w/ turn IDs** — for debugging production.
10. **Everything else** as the need arises.

---

## Explicitly not on this list

- **Rewriting in another language** — Rust + Python has worked fine.
- **Replacing rmcp** — it's rough but functional; switching now would
  cost more than it saves.
- **Caching MANDATE responses in NemoClaw** — stale data in a security
  context is worse than a slow query.
- **Adding a "dry run" mode to Tier-4/5** — the right pattern is
  explicit refusal when `operator_confirm` is missing; a dry run
  would be a footgun.
- **Auto-escalating alerts based on event stream reasoning** — the
  doctrine is "never auto-act". Changing that isn't a next step, it's
  a new product.

---

## Closing thought

The current PoC is feature-complete against the 8-stage plan. Every
item on this "next steps" list is optional polish, optional scale, or
optional hardening. None of them blocks operator use of the system as
it stands today. Ship it, learn from real operators, and pick from
this list based on what actually hurts.
