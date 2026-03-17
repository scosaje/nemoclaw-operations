# AnSA NemoClaw PoC

**Autonomous National Security Architecture -- Proof of Concept**
Built by [Inspired Technologies Limited (ITL)](https://inspiredtechng.com), Abuja, Nigeria | NVIDIA Technology Partner

---

## Overview

AnSA (Autonomous National Security Architecture) is an AI-powered surveillance and national security platform developed by Inspired Technologies Limited for the Nigerian government and defence sector. The full production system operates across 200+ camera feeds on a 5-node Jetson AGX Orin edge cluster, with real-time facial recognition, biometric cross-referencing, NIMC national identity verification, and voice-driven operator interaction through the AVIS Voice Intelligence System.

This **Proof of Concept** demonstrates a **Supervisor Agent** running inside NemoClaw's OpenShell sandbox environment. It uses **simulated AnSA subsystems** with fictional mock data -- no real cameras, databases, or government systems are connected. The purpose is to prove the agent architecture, tool orchestration, and security isolation model work correctly before connecting real infrastructure.

### What This PoC Demonstrates

- An autonomous AI agent (Nemotron 3 Super 120B) coordinating multi-step security investigations
- Tool-use pattern: camera query, biometric lookup, identity verification, alert dispatch
- Complete evidence chain construction from detection to actionable alert
- Sandbox isolation enforcing data sovereignty (only NVIDIA API egress permitted)
- Voice command interface with protocol-level formatting (standard, dignitary, command)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    NemoClaw OpenShell Sandbox            │
│  ┌───────────────────────────────────────────────────┐  │
│  │           AnSA Supervisor Agent                    │  │
│  │           (Nemotron 3 Super 120B)                  │  │
│  │                                                    │  │
│  │  Tools:                                            │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐          │  │
│  │  │ Camera   │ │Biometric │ │  NIMC    │          │  │
│  │  │ Feed     │ │ Lookup   │ │  Query   │          │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘          │  │
│  │  ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐          │  │
│  │  │ Alert    │ │ System   │ │  AVIS    │          │  │
│  │  │ Dispatch │ │ Status   │ │  Voice   │          │  │
│  │  └──────────┘ └──────────┘ └──────────┘          │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                               │
│  Isolation: Landlock + Seccomp + Network Namespace       │
│  Egress: NVIDIA API only (data sovereignty enforced)     │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTPS (443)
                    ┌──────┴──────┐
                    │ NVIDIA API  │
                    │ Nemotron    │
                    │ Inference   │
                    └─────────────┘
```

The agent runs entirely within an OpenShell sandbox. Landlock restricts filesystem access, Seccomp filters syscalls, and a network namespace ensures the only permitted egress is HTTPS to NVIDIA's inference API endpoints. All mock data is mounted read-only. No data leaves Nigerian-controlled infrastructure.

### Investigation Flow

```
Camera Detection ──> Biometric Match ──> NIMC Verification ──> Threat Assessment ──> Alert Dispatch
     (87%)               (92%)             (NIN verified)           (HIGH)           (NPF + DSS)
```

---

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Node.js | v22+ | NemoClaw runtime |
| Python | 3.12+ | Agent tool execution |
| Docker | Latest | Container isolation |
| Git | Latest | Version control |
| NVIDIA API Key | -- | Nemotron model inference via [build.nvidia.com](https://build.nvidia.com) |
| NemoClaw | Pre-release | OpenShell sandbox and agent orchestration |

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd nemoclaw_operations

# 2. Set your NVIDIA API key
export NVIDIA_API_KEY='nvapi-...'

# 3. Run setup (checks prerequisites, validates files, onboards sandbox)
bash scripts/setup.sh

# 4. Run the demo
bash scripts/demo.sh
```

The setup script performs six validation steps:

1. **Prerequisite check** -- verifies Node.js, Python, Docker, and Git are installed
2. **API key verification** -- confirms `NVIDIA_API_KEY` environment variable is set
3. **NemoClaw installation** -- checks for NemoClaw CLI, provides install guidance if missing
4. **OpenShell CLI check** -- verifies OpenShell is available for sandbox management
5. **Sandbox onboarding** -- runs `nemoclaw onboard` with all configuration files
6. **File validation** -- confirms all 14 required project files exist and Python tool imports succeed

---

## Project Structure

```
nemoclaw_operations/
├── README.md                                   # This file
├── package.json                                # Project metadata (ansa-nemoclaw-poc v0.1.0)
├── .gitignore                                  # Git ignore rules
│
├── agents/
│   └── supervisor/
│       ├── agent.yaml                          # Agent definition: model, system prompt, tool bindings
│       └── tools/
│           ├── camera_feed.py                  # Query simulated camera surveillance events
│           ├── biometric_lookup.py             # Match face embeddings against POI watchlist
│           ├── nimc_query.py                   # Query simulated NIMC identity database
│           ├── alert_dispatch.py               # Dispatch security alerts to command centres
│           ├── system_status.py                # Check health of all AnSA subsystems
│           └── avis_voice.py                   # AVIS voice command parsing and protocol formatting
│
├── config/
│   ├── nemoclaw.yaml                           # Sandbox isolation config (Landlock, Seccomp, Netns)
│   ├── network-policy.yaml                     # Network egress policy (NVIDIA API only)
│   └── inference-profile.yaml                  # Nemotron model parameters and reliability settings
│
├── data/
│   └── mock/
│       ├── camera_events.json                  # 10 simulated detection events across Abuja
│       ├── persons_of_interest.json            # 7 fictional POI records with threat levels
│       ├── nimc_records.json                   # 10 fictional NIMC identity records
│       └── scenarios/
│           └── threat_detection.json           # Pre-built demo scenario with expected tool sequence
│
└── scripts/
    └── setup.sh                                # One-command environment setup and validation
```

---

## Demo Walkthrough

The `threat_detection` scenario demonstrates the full investigation pipeline. The agent receives an alert about a face detection at Nnamdi Azikiwe International Airport and autonomously works through the evidence chain.

### Step 1 -- Alert Received

The agent is given an initial prompt:

> *"ALERT: Face detection system has flagged a potential match at Nnamdi Azikiwe International Airport, Terminal 1. Camera CAM-047 detected a face with 87% confidence matching a person on our watchlist at 14:23 hours today. Investigate this detection, verify the identity, and take appropriate action."*

### Step 2 -- Query Camera Feeds

The agent calls `query_camera_feeds` with location filter "Airport". It retrieves:

- **EVT-001**: CAM-047, 14:23 hours, face detected, embedding `emb_2847`, confidence **87%**. Subject at departure hall security checkpoint moving towards Gate B3.
- **EVT-008**: CAM-047, 14:31 hours, face detected, same embedding `emb_2847`, confidence **92%**. Second detection at boarding gate area with clearer angle -- subject appears to be awaiting flight departure.

The confidence escalation from 87% to 92% across two detections strengthens the evidence chain.

### Step 3 -- Biometric Lookup

The agent calls `biometric_lookup` with `face_embedding_ref: "emb_2847"`. Result:

- **Match found**: POI-2847 -- Abubakar Musa Ibrahim
- **Threat level**: HIGH
- **Profile**: Linked to financial fraud network operating across North-East region
- **NIN**: 29384710256
- **Match confidence**: 92%

### Step 4 -- NIMC Identity Verification

The agent calls `nimc_query` with `nin: "29384710256"` to cross-reference against the National Identity Management Commission database. Result:

- **Identity confirmed**: Abubakar Musa Ibrahim
- **Date of birth**: 1989-06-14
- **State of origin**: Borno, Maiduguri LGA
- **Residential address**: No. 7 Damboa Road, GRA, Maiduguri, Borno State
- **Photo reference available** for visual confirmation

### Step 5 -- Alert Dispatch

With biometric confidence >85% and identity verified via NIMC, the agent calls `dispatch_alert` with severity `HIGH`, full location details, and the complete evidence chain:

```
Evidence chain: {
  camera_event: "EVT-001 + EVT-008 (dual detection, confidence 87%->92%)",
  biometric_match: "POI-2847 (Abubakar Musa Ibrahim, threat: HIGH)",
  identity_record: "NIN 29384710256 verified via NIMC"
}
```

- **Alert dispatched** to NPF (Nigeria Police Force) and DSS (Department of State Services)
- **Estimated response time**: 15 minutes
- Evidence chain attached for operational and legal use

### Step 6 -- AVIS Voice Report

The agent reports findings through the AVIS voice interface, formatting the response according to the operator's protocol level:

| Protocol | Style | Example |
|----------|-------|---------|
| **standard** | Direct and actionable | "Target confirmed at Terminal 1. NPF and DSS alerted. Maintain visual, do not engage." |
| **dignitary** | Formal briefing | "Your Excellency, our surveillance system has identified a person of interest at the airport. Security forces have been notified and are responding." |
| **command** | Concise military-style | "POI CONFIRMED. LOC: NAIA T1. ASSETS: NPF/DSS DISPATCHED. STATUS: ACTIVE MONITORING." |

### Key Demo Talking Points

- Real-time face detection across a distributed camera network
- Automated cross-referencing against the national watchlist database
- NIMC integration for authoritative identity verification
- Sub-10-second end-to-end detection-to-alert pipeline
- Multi-camera tracking with confidence escalation (87% to 92%)
- Complete evidence chain maintained for legal and operational use

---

## Agent Tools

| Tool | Function | Description | Key Inputs | Output |
|------|----------|-------------|------------|--------|
| **Camera Feed** | `query_camera_feeds()` | Query camera surveillance network for detection events | `location` (partial match), `time_range` (HH:MM-HH:MM), `filter_type` (face_detected, vehicle_detected, anomaly_detected) | Matching events with timestamps, confidence scores, embedding refs, and frame references |
| **Biometric Lookup** | `biometric_lookup()` | Match face embeddings or person IDs against the POI watchlist | `face_embedding_ref` (e.g., emb_2847), `person_id` (e.g., POI-2847) | Match results with confidence scores, threat levels, linked NINs, and last known location |
| **NIMC Query** | `nimc_query()` | Query the NIMC national identity database by NIN or name | `nin` (11-digit NIN), `name` (partial match), `state` (state of origin filter) | Full identity records with biographical details, addresses, and photo references |
| **Alert Dispatch** | `dispatch_alert()` | Dispatch security alerts to the appropriate command centre | `severity` (LOW/MEDIUM/HIGH/CRITICAL), `description`, `location`, `evidence` (chain dict) | Alert ID, responding agencies, estimated response time, evidence summary |
| **System Status** | `system_status()` | Check health status of all AnSA subsystems | `subsystem` (cameras, biometric_db, nimc_link, avis, network, compute_cluster) -- optional | Subsystem health metrics, connectivity status, and performance data |
| **AVIS Voice** | `avis_voice_interface()` | Process natural language voice commands via AVIS | `voice_command` (natural language), `context` (operator_role, protocol_level) | Parsed intent, extracted entities, suggested tool calls, and response formatting |

### Alert Severity and Agency Routing

| Severity | Responding Agencies | Estimated Response Time |
|----------|-------------------|------------------------|
| **LOW** | NSCDC | 60 minutes |
| **MEDIUM** | NPF | 30 minutes |
| **HIGH** | NPF, DSS | 15 minutes |
| **CRITICAL** | NPF, DSS, Military Intelligence | 5 minutes |

### Monitored Subsystems

| Subsystem | Description | Key Metrics |
|-----------|-------------|-------------|
| **cameras** | Camera Surveillance Network | 217 total cameras, 209 online, 24.3 avg FPS, 67.2% storage |
| **biometric_db** | Biometric Database | 1,247,832 records, 4,721 POIs, 45ms query latency |
| **nimc_link** | NIMC Database Link | Active connection, 120ms API latency, 72.1% daily quota remaining |
| **avis** | AVIS Voice Intelligence System | 3 active sessions, 96.8% recognition accuracy, 200ms latency |
| **network** | Secure Network Infrastructure | 12 VPN tunnels, AES-256-GCM encryption, 47 intrusion attempts blocked (24h) |
| **compute_cluster** | Jetson AGX Orin Cluster | 5 nodes active, 58.3% GPU utilization, 147.2 FPS inference throughput |

---

## Configuration Files

### `config/nemoclaw.yaml` -- Sandbox Isolation

Defines the OpenShell sandbox environment for the Supervisor Agent:

- **Landlock**: Filesystem access control restricting reads to `data/mock/` and `agents/supervisor/` only
- **Seccomp**: Syscall filtering to prevent unauthorized kernel interactions
- **Network Namespace**: Full network isolation with policy-controlled egress
- **Resource Limits**: 2 GiB memory, 2 CPU cores, 256 file descriptors, 32 processes, 300-second timeout
- **Writable Paths**: `/tmp/ansa-logs` only (temporary log output)
- **Blocked Paths**: `/etc`, `/home`, `/var`, `/root`, `/proc/kcore`

### `config/network-policy.yaml` -- Data Sovereignty Enforcement

Strict network egress policy ensuring Nigerian data sovereignty:

- **Default deny** on all outbound traffic
- **Allowed egress** (two endpoints only):
  - `integrate.api.nvidia.com:443` -- Nemotron inference (rate-limited to 100 requests/min)
  - `api.nvcf.nvidia.com:443` -- NVIDIA Cloud Functions backup endpoint (rate-limited to 100 requests/min)
- **DNS restricted** to allowed hosts only
- **Ingress denied** completely -- no inbound connections permitted
- All other outbound traffic is blocked with reason: "data sovereignty enforcement"

### `config/inference-profile.yaml` -- Model Configuration

Nemotron 3 Super 120B inference parameters tuned for security operations:

- **Temperature**: 0.3 (low -- deterministic for security-critical decisions)
- **Max tokens**: 2,048 (sufficient for detailed investigation responses)
- **Top-p**: 0.9 (nucleus sampling)
- **Reliability**: 30-second timeout, 3 retries with 2x exponential backoff
- **Security**: Prompts and responses are **not logged** (contains security data); only token usage and latency are tracked

---

## Security Model

### Sandbox Isolation

The agent operates inside NemoClaw's OpenShell sandbox with three layers of kernel-level isolation:

1. **Landlock** (Linux 5.13+): Fine-grained filesystem access control. The agent can only read from `data/mock/` and `agents/supervisor/`. Write access is limited to `/tmp/ansa-logs/`. System directories (`/etc`, `/home`, `/var`, `/root`) are blocked entirely.

2. **Seccomp**: Syscall filtering prevents the agent from performing unauthorized kernel operations. Only the minimum required syscalls are permitted.

3. **Network Namespace**: The agent runs in an isolated network namespace. The only permitted egress is HTTPS (port 443) to NVIDIA's inference API endpoints (`integrate.api.nvidia.com` and `api.nvcf.nvidia.com`).

### Data Sovereignty

All surveillance data, biometric records, and identity information remain within Nigerian-controlled infrastructure. The network policy enforces this at the kernel level -- the sandbox physically cannot transmit data to any endpoint other than NVIDIA's inference API for model queries. Prompts and responses are not logged to prevent data leakage through operational logs.

### Read-Only Data Access

Mock data files are mounted read-only inside the sandbox. The agent cannot modify, delete, or exfiltrate the underlying data. In production, this same model ensures the agent can query but never alter operational databases.

### Agent-Level Safeguards

The Supervisor Agent's system prompt enforces operational discipline:

- **Verify before alerting**: Always cross-reference camera detections with biometric database AND NIMC records before dispatching high-severity alerts
- **Minimize false positives**: Only dispatch alerts when biometric confidence exceeds 85% and identity verification succeeds
- **Evidence chain required**: Every alert must include a complete evidence chain (camera event, biometric match, identity verification, threat assessment)
- **Data sovereignty awareness**: Never reference or attempt to access external databases

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Filesystem | Landlock | Read-only access to mock data, no access to system dirs |
| Syscalls | Seccomp | Filter dangerous syscalls |
| Network | Network Namespace + Policy | Block all egress except NVIDIA API |
| Data | Mock data only (PoC) | No real PII or classified data in PoC |
| Inference | NVIDIA API | Model runs on NVIDIA infrastructure, no local model weights |
| Agent | System prompt constraints | Verify before alerting, evidence chains required, 85% confidence threshold |

---

## Extending the PoC

### Swapping Mock Tools for Real Systems

Each agent tool is a standalone Python function with a well-defined interface (`def function_name(**kwargs) -> dict`). To connect real AnSA subsystems, replace the mock implementations while preserving the function signatures:

| Mock Tool | Current Behaviour | Production Replacement |
|-----------|-------------------|----------------------|
| `camera_feed.py` | Reads `camera_events.json` | Real RTSP stream ingestion via NVIDIA DeepStream SDK or camera management API |
| `biometric_lookup.py` | Reads `persons_of_interest.json` | Production facial recognition database with live embedding matching |
| `nimc_query.py` | Reads `nimc_records.json` | Authenticated NIMC NIN Verification API with proper government credentials |
| `alert_dispatch.py` | Prints to stdout, returns confirmation dict | Integration with NPF/DSS command-and-control systems and dispatch protocols |
| `system_status.py` | Returns hardcoded health data | Real health checks against Jetson cluster, network infrastructure, and camera uptime |
| `avis_voice.py` | Text-based intent parsing with regex | Full AVIS pipeline with ASR (speech recognition), NLU, and TTS (speech synthesis) |

### Integration Steps

1. Keep the same function signature as the mock tool (input parameters and return type)
2. Replace the JSON file reads with real API calls or database queries
3. Update `config/network-policy.yaml` to allow egress to the new endpoints
4. Update `config/nemoclaw.yaml` filesystem permissions if the tool needs access to new paths
5. The agent's system prompt and tool bindings in `agent.yaml` require no changes -- the interface contract is production-ready

### Adding New Tools

To add a new tool to the Supervisor Agent:

1. Create a new Python file in `agents/supervisor/tools/` with a function matching the naming convention
2. Add the tool definition to `agents/supervisor/agent.yaml` under the `tools:` section
3. Update the agent's system prompt if the tool changes the investigation workflow
4. Add mock data to `data/mock/` if the tool requires test data

---

## Production Roadmap (AnSA Full System)

The PoC validates the agent architecture for the full AnSA deployment:

- **Edge Compute**: 5-node Jetson AGX Orin cluster for real-time inference at the edge, processing camera feeds locally before transmitting results
- **Camera Network**: 200+ surveillance cameras across Nigerian federal installations, airports, and critical infrastructure with real-time face detection via NVIDIA DeepStream
- **NIMC Integration**: Live connection to the National Identity Management Commission database for authoritative NIN verification with secure, authenticated API access
- **AVIS Voice System**: Full-duplex voice interface with speech recognition supporting Hausa, Yoruba, Igbo, and English; text-to-speech for operator briefings; protocol-level formatting for field operators, dignitaries, and command staff
- **Encrypted Video Pipeline**: End-to-end encrypted video transport from cameras to edge nodes with Nigerian-sovereign key management
- **Biometric Enrollment**: Continuous enrolment and embedding updates for the persons of interest database with liveness detection to prevent spoofing
- **Multi-Agency Coordination**: Real-time alert routing to NPF, DSS, NSCDC, and Military Intelligence with acknowledgement tracking and escalation protocols
- **Hybrid Cloud**: Edge inference on Jetson cluster with sovereign data centre for long-term storage, analytics, and model retraining

---

## License

**UNLICENSED** -- Proprietary software. Copyright Inspired Technologies Limited. All rights reserved.

This software is confidential and proprietary. Unauthorised copying, distribution, or use of this software, via any medium, is strictly prohibited.

---

## Links

- **NVIDIA NemoClaw**: [NeMo Agent Toolkit Documentation](https://docs.nvidia.com/nemo/nemoclaw/)
- **NVIDIA Build**: [build.nvidia.com](https://build.nvidia.com) -- API key provisioning and model access
- **NVIDIA Jetson AGX Orin**: [developer.nvidia.com/embedded/jetson-agx-orin](https://developer.nvidia.com/embedded/jetson-agx-orin) -- Edge AI compute platform
- **Inspired Technologies Limited**: ITL, Abuja, Nigeria -- NVIDIA Technology Partner
