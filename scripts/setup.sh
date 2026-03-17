#!/usr/bin/env bash
# AnSA NemoClaw PoC — Setup Script
# One-command setup for the Supervisor Agent sandbox environment
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║     AnSA NemoClaw PoC — Environment Setup           ║"
echo "║     Autonomous National Security Architecture       ║"
echo "║     Inspired Technologies Limited                   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Track failures
ERRORS=0

check_requirement() {
    local name="$1"
    local command="$2"
    local version_flag="${3:---version}"
    local min_version="${4:-}"

    if command -v "$command" &>/dev/null; then
        local version
        version=$($command $version_flag 2>&1 | head -1)
        echo -e "  ${GREEN}✓${NC} $name: $version"
    else
        echo -e "  ${RED}✗${NC} $name: NOT FOUND"
        ERRORS=$((ERRORS + 1))
    fi
}

# Step 1: Check prerequisites
echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"
check_requirement "Node.js" "node" "--version"
check_requirement "Python" "python3" "--version"
check_requirement "Docker" "docker" "--version"
check_requirement "Git" "git" "--version"
echo ""

# Step 2: Check NVIDIA API key
echo -e "${YELLOW}[2/6] Checking NVIDIA API key...${NC}"
if [ -n "${NVIDIA_API_KEY:-}" ]; then
    echo -e "  ${GREEN}✓${NC} NVIDIA_API_KEY is set (${#NVIDIA_API_KEY} chars)"
else
    echo -e "  ${RED}✗${NC} NVIDIA_API_KEY not set"
    echo -e "  ${YELLOW}→${NC} Get your key at: https://build.nvidia.com"
    echo -e "  ${YELLOW}→${NC} Then run: export NVIDIA_API_KEY='your-key-here'"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Step 3: Install NemoClaw if not present
echo -e "${YELLOW}[3/6] Checking NemoClaw installation...${NC}"
if command -v nemoclaw &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} NemoClaw: $(nemoclaw --version 2>&1 || echo 'installed')"
else
    echo -e "  ${YELLOW}→${NC} NemoClaw not found. Installing..."
    if command -v npm &>/dev/null; then
        echo -e "  ${YELLOW}→${NC} Cloning NemoClaw repository..."
        echo -e "  ${YELLOW}NOTE:${NC} NemoClaw is pre-release. Install manually if this fails:"
        echo -e "  ${CYAN}  git clone https://github.com/nvidia/nemoclaw.git /tmp/nemoclaw${NC}"
        echo -e "  ${CYAN}  cd /tmp/nemoclaw && npm install -g .${NC}"
        echo -e "  ${RED}✗${NC} Automatic install skipped — install NemoClaw manually"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "  ${RED}✗${NC} npm not found — cannot install NemoClaw"
        ERRORS=$((ERRORS + 1))
    fi
fi
echo ""

# Step 4: Install OpenShell CLI
echo -e "${YELLOW}[4/6] Checking OpenShell CLI...${NC}"
if command -v openshell &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} OpenShell: $(openshell --version 2>&1 || echo 'installed')"
else
    echo -e "  ${YELLOW}→${NC} OpenShell CLI not found."
    echo -e "  ${YELLOW}NOTE:${NC} Install OpenShell manually:"
    echo -e "  ${CYAN}  See NemoClaw docs for OpenShell installation${NC}"
    echo -e "  ${RED}✗${NC} Automatic install skipped — install OpenShell manually"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Step 5: Onboard sandbox (if NemoClaw is available)
echo -e "${YELLOW}[5/6] Configuring sandbox environment...${NC}"
if command -v nemoclaw &>/dev/null; then
    echo -e "  ${YELLOW}→${NC} Running nemoclaw onboard..."
    cd "$PROJECT_DIR"
    nemoclaw onboard \
        --config config/nemoclaw.yaml \
        --network-policy config/network-policy.yaml \
        --inference-profile config/inference-profile.yaml \
        --agent agents/supervisor/agent.yaml \
        2>&1 | sed 's/^/  /' || {
        echo -e "  ${RED}✗${NC} Sandbox onboarding failed"
        ERRORS=$((ERRORS + 1))
    }
else
    echo -e "  ${YELLOW}⏭${NC}  Skipping sandbox setup — NemoClaw not installed"
fi
echo ""

# Step 6: Validate mock data
echo -e "${YELLOW}[6/6] Validating project files...${NC}"
REQUIRED_FILES=(
    "agents/supervisor/agent.yaml"
    "agents/supervisor/tools/camera_feed.py"
    "agents/supervisor/tools/biometric_lookup.py"
    "agents/supervisor/tools/nimc_query.py"
    "agents/supervisor/tools/alert_dispatch.py"
    "agents/supervisor/tools/system_status.py"
    "agents/supervisor/tools/avis_voice.py"
    "config/nemoclaw.yaml"
    "config/network-policy.yaml"
    "config/inference-profile.yaml"
    "data/mock/persons_of_interest.json"
    "data/mock/camera_events.json"
    "data/mock/nimc_records.json"
    "data/mock/scenarios/threat_detection.json"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$PROJECT_DIR/$file" ]; then
        echo -e "  ${GREEN}✓${NC} $file"
    else
        echo -e "  ${RED}✗${NC} $file — MISSING"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# Validate Python tools can import
echo -e "  ${YELLOW}→${NC} Testing Python tool imports..."
cd "$PROJECT_DIR"
python3 -c "
import sys
sys.path.insert(0, 'agents/supervisor/tools')
from camera_feed import query_camera_feeds
from biometric_lookup import biometric_lookup
from nimc_query import nimc_query
from alert_dispatch import dispatch_alert
from system_status import system_status
from avis_voice import avis_voice_interface
print('  All 6 tools imported successfully')
" 2>&1 || {
    echo -e "  ${RED}✗${NC} Python tool import test failed"
    ERRORS=$((ERRORS + 1))
}
echo ""

# Summary
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}✓ Setup complete! All checks passed.${NC}"
    echo ""
    echo -e "Next steps:"
    echo -e "  ${CYAN}1.${NC} Run the demo:  ${CYAN}bash scripts/demo.sh${NC}"
    echo -e "  ${CYAN}2.${NC} Or manually:   ${CYAN}nemoclaw run --agent agents/supervisor/agent.yaml${NC}"
else
    echo -e "${YELLOW}⚠ Setup completed with ${ERRORS} issue(s).${NC}"
    echo -e "Fix the issues above before running the demo."
fi
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
