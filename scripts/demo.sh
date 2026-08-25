#!/usr/bin/env bash
# AnSA NemoClaw PoC — Demo Script
# Runs the threat detection scenario through the Supervisor Agent
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_FILE="$PROJECT_DIR/data/mock/scenarios/threat_detection.json"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║     AnSA NemoClaw PoC — Threat Detection Demo       ║"
echo "║     Autonomous National Security Architecture       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check prerequisites
echo -e "${YELLOW}[Pre-flight checks]${NC}"

if [ ! -f "$SCENARIO_FILE" ]; then
    echo -e "  ${RED}✗${NC} Scenario file not found: $SCENARIO_FILE"
    echo -e "  Run ${CYAN}bash scripts/setup.sh${NC} first."
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Scenario file found"

if [ -z "${NVIDIA_API_KEY:-}" ]; then
    echo -e "  ${RED}✗${NC} NVIDIA_API_KEY not set"
    echo -e "  Run: ${CYAN}export NVIDIA_API_KEY='your-key-here'${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} NVIDIA_API_KEY set"

if ! command -v nemoclaw &>/dev/null; then
    echo -e "  ${RED}✗${NC} NemoClaw not installed"
    echo -e "  Run ${CYAN}bash scripts/setup.sh${NC} first."
    exit 1
fi
echo -e "  ${GREEN}✓${NC} NemoClaw available"
echo ""

# Load scenario
INITIAL_PROMPT=$(python3 -c "
import json
with open('$SCENARIO_FILE') as f:
    data = json.load(f)
print(data['scenario']['initial_prompt'])
")

echo -e "${BOLD}Scenario: Airport POI Detection${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "$INITIAL_PROMPT"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}[Launching Supervisor Agent in sandbox...]${NC}"
echo -e "  Agent:    ${CYAN}ansa-assistant${NC}"
echo -e "  Model:    ${CYAN}nvidia/nemotron-3-ultra-550b-a55b${NC}"
echo -e "  Sandbox:  ${CYAN}OpenShell (landlock + seccomp + netns)${NC}"
echo -e "  Data:     ${CYAN}Simulated (mock)${NC}"
echo ""
echo -e "${GREEN}═══════════════ AGENT OUTPUT ═══════════════${NC}"
echo ""

# Run the agent with the scenario prompt
cd "$PROJECT_DIR"
nemoclaw run \
    --agent agents/supervisor/agent.yaml \
    --sandbox-config config/nemoclaw.yaml \
    --network-policy config/network-policy.yaml \
    --inference-profile config/inference-profile.yaml \
    --prompt "$INITIAL_PROMPT" \
    --verbose \
    2>&1 | while IFS= read -r line; do
        # Color-code tool calls and agent reasoning
        if [[ "$line" == *"[TOOL CALL]"* ]]; then
            echo -e "  ${CYAN}$line${NC}"
        elif [[ "$line" == *"[RESULT]"* ]]; then
            echo -e "  ${GREEN}$line${NC}"
        elif [[ "$line" == *"[ERROR]"* ]]; then
            echo -e "  ${RED}$line${NC}"
        elif [[ "$line" == *"ALERT DISPATCHED"* ]]; then
            echo -e "  ${RED}${BOLD}$line${NC}"
        else
            echo "  $line"
        fi
    done

echo ""
echo -e "${GREEN}═══════════════ END OUTPUT ═══════════════${NC}"
echo ""
echo -e "${CYAN}Demo complete. Review the agent's investigation above.${NC}"
echo -e "Expected flow: camera_feed → biometric_lookup → nimc_query → dispatch_alert"
