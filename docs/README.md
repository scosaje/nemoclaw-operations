# NemoClaw ↔ AnSA Integration — Full Documentation

**Project**: AnSA NemoClaw PoC — integrating a NemoClaw / OpenClaw AI agent
with the live AnSA (Autonomous National Security Architecture) service
stack.
**Operator**: Inspired Technologies Limited (ITL), Abuja, Nigeria.
**Status**: All 8 stages complete and verified. Stage 9 (multi-cluster)
added 2026-04-07. Direct ASIAS/MANDATE/DE integration added 2026-04-12.
NemoClaw upgraded to **v0.0.114** on 2026-08-25 (OpenShell 0.0.106,
OpenClaw 2026.7.1) — see [11-upgrade-20260825.md](./11-upgrade-20260825.md)
for the current connection details, which supersede anything dated earlier.

This documentation set is the canonical record of what was built, why,
and how to operate it. Read the files in order on a first pass; use them
as a reference afterwards.

## Contents

| # | File | What it covers |
|---|---|---|
| 01 | [architecture.md](./01-architecture.md) | The AnSA stack, the NemoClaw bridge, the service topology, the 5-tier authorisation scheme, component inventory |
| 02 | [stages.md](./02-stages.md) | Chronological stage-by-stage record of everything built. Files changed, decisions made, verification outcomes |
| 03 | [tools-reference.md](./03-tools-reference.md) | Every MCP tool and REST endpoint with tier, inputs, outputs, examples, and what upstream RPC it wraps |
| 04 | [runbook.md](./04-runbook.md) | Operational procedures — start/stop, re-onboard, troubleshoot, inspect audit logs, ports reference |
| 05 | [discoveries.md](./05-discoveries.md) | The 12 non-obvious things we learned along the way. Each with symptom, investigation, root cause, fix, lessons |
| 06 | [isolation-model.md](./06-isolation-model.md) | How "don't affect operations when NemoClaw isn't running" was enforced through every stage |
| 07 | [upstream-issues.md](./07-upstream-issues.md) | Issues found in other teams' code, deliberately NOT fixed, with pointers for them to pick up |
| 08 | [next-steps.md](./08-next-steps.md) | What could come next: hardening, observability, additional integrations |
| 09 | [direct-integration.md](./09-direct-integration.md) | Hybrid architecture: 50 direct ASIAS/MANDATE/DE tools, security measures, code review fixes |
| 10 | [nemoclaw-upgrade.md](./10-nemoclaw-upgrade.md) | NemoClaw v0.0.12 upgrade, OpenShell 0.0.26, Gemma 4 deployment, model switching |
| 11 | [upgrade-20260825.md](./11-upgrade-20260825.md) | **Current state** — v0.0.114, OpenShell 0.0.106, gateway port 18080, Nemotron 3 Ultra 550B, restore checklist |

## At-a-glance

- **87 MCP tools** across 5 risk tiers — `mcporter call avis.<tool>`,
  `asias_*`, `mandate_*`, `de_*` from inside the NemoClaw sandbox
- **37 AVIS-routed tools** (stages 1-9) via `avis-gateway:8190`
- **50 direct tools** (2026-04-12 hybrid): 21 ASIAS, 22 MANDATE, 7 DE
- **Direct ASIAS/MANDATE paths** for T3 reads — faster, no AVIS hop
- **Direct DE gRPC** with EdgeRegistry, async background health probing
- **40+ REST endpoints** on `avis-gateway:8190` — companion HTTP surface
- **Two independent gRPC client paths** (gateway + mcp) sharing only the
  `.proto` files
- **One new gRPC server** in `avis-core` exposing the internal event bus
- **~5000 lines of net-new Rust, Python, and protobuf code** (stages 1-9)
  plus ~2000 lines for direct integration (stage "hybrid")
- **Zero edits** to `config/avis.yaml`, `config/avis-command.yaml`, or any
  AVIS production code paths reachable without the NemoClaw overlay
- **Live event stream** from ASIAS/SIS → `avis.events_drain` — agent can
  now react to events, not just respond to prompts
- **Audit log** at every tier with operator_id attribution on gated calls
- **NemoClaw v0.0.12** with Nemotron 3 Super 120B (NVIDIA) and Gemma 4
  E4B (cluster Ollama) inference options

## Quick start (next session)

```bash
# Make sure the stack is up with NemoClaw integration
cd ~/claude-projects/ansa-voice-intelligence-system
docker compose -f docker-compose.yml -f docker-compose.nemoclaw.yml up -d

# Verify from the sandbox
nemoclaw ansa-assistant exec -- bash -lc '/sandbox/.npm-global/bin/mcporter call avis.health'
# → {"healthy":true,"components":{"camera_controller":true,"gateway":true},...}

nemoclaw ansa-assistant exec -- bash -lc '/sandbox/.npm-global/bin/mcporter call avis.events_drain timeout_ms=2000'
# → live ASIAS / SIS events + internal AVIS health events

# Direct ASIAS query (hybrid, 2026-04-12)
nemoclaw ansa-assistant exec -- bash -lc '/sandbox/.npm-global/bin/mcporter call asias_graph_stats'
# → graph node/edge counts

# Direct MANDATE query (hybrid, 2026-04-12)
nemoclaw ansa-assistant exec -- bash -lc '/sandbox/.npm-global/bin/mcporter call mandate_incidents_active'
# → active MANDATE incidents
```

See [runbook.md](./04-runbook.md) for the full operational procedures.

## Repository layout (cross-repo)

This integration touches **four** git repositories. The paths are absolute
to this machine; adjust for your environment.

| Repo | Purpose | What we changed |
|---|---|---|
| `~/claude-projects/nemoclaw_operations/` | AnSA NemoClaw PoC workspace (this repo) | README, `sandbox-workspace/` (6 workspace files), `docs/` (this folder) |
| `~/claude-projects/ansa-voice-intelligence-system/` | AVIS codebase | 4 new crates/modules, 3 new proto files, 1 new compose overlay, 4 additive env-var reads in existing services |
| `~/NemoClaw/` | NemoClaw upstream fork | 2 new policy presets (`avis.yaml`, `avis-mcp.yaml`) |
| `~/claude-projects/security-intelligence-system/` | SIS (edge cluster) | Zero changes — SIS already publishes to ASIAS |
| `~/claude-projects/mandate/` | MANDATE workflow engine | Zero changes |
| `~/claude-projects/asias-codes/` | ASIAS central services | Zero changes |
| `~/claude-projects/decision-service-cpu-v1.2.0-dev/` | Decision Engine (edge) | Zero changes |

## Conventions used in this documentation

- File paths are absolute: `~/claude-projects/.../file.rs`
- Line references look like `filename.rs:42` for quick navigation
- Code blocks contain verbatim commands you can paste
- "Tier" refers to the 5-tier authorisation scheme — see
  [architecture.md](./01-architecture.md#tier-scheme)
- "Overlay" means `docker-compose.nemoclaw.yml` — the additive compose
  file that introduces NemoClaw without editing the base
- "Sandbox" means the NemoClaw/OpenShell agent sandbox, accessible via
  `nemoclaw ansa-assistant connect` (interactive) or
  `nemoclaw ansa-assistant exec -- <cmd>` (non-interactive) from this dev host

## Doctrine

Three principles sat above every design decision:

1. **Data sovereignty**: every call the agent makes passes through AVIS
   code. The agent never talks directly to MANDATE, ASIAS, or the Decision
   Engine — AVIS is the sole conduit. If AVIS is the voice system for
   AnSA, NemoClaw is an agent *using* that voice.
2. **Isolation**: nothing we built affects MANDATE, ASIAS, SIS, Decision
   Engine, or even AVIS-by-itself when NemoClaw isn't running. Reverting
   is dropping the overlay.
3. **Operator in the loop**: the agent never auto-acts on Tier-4 or
   Tier-5 operations. Every mutation and every physical-control command
   requires explicit operator instruction, confirmation headers, and a
   MEMORY.md audit entry.

Read [isolation-model.md](./06-isolation-model.md) to understand how
principles 1 and 2 were enforced through eight stages of development
without compromise.
