"""AnSA System Status Tool - Simulated subsystem health monitoring."""
import json
from datetime import datetime, timezone

# Simulated subsystem health data
SUBSYSTEMS = {
    "cameras": {
        "name": "Camera Surveillance Network",
        "status": "operational",
        "details": {
            "total_cameras": 217,
            "online": 209,
            "offline": 5,
            "maintenance": 3,
            "coverage_zones": ["FCT Abuja", "Lagos", "Kano", "Rivers", "Kaduna"],
            "fps_average": 24.3,
            "storage_used_pct": 67.2
        }
    },
    "biometric_db": {
        "name": "Biometric Database",
        "status": "operational",
        "details": {
            "total_records": 1_247_832,
            "persons_of_interest": 4_721,
            "last_sync": "2026-03-17T13:00:00Z",
            "query_latency_ms": 45,
            "storage_used_gb": 892
        }
    },
    "nimc_link": {
        "name": "NIMC Database Link",
        "status": "operational",
        "details": {
            "connection": "active",
            "api_latency_ms": 120,
            "daily_queries": 3_847,
            "quota_remaining_pct": 72.1,
            "last_heartbeat": "2026-03-17T14:20:00Z"
        }
    },
    "avis": {
        "name": "AVIS Voice Intelligence System",
        "status": "operational",
        "details": {
            "active_sessions": 3,
            "supported_protocols": ["standard", "dignitary", "command"],
            "voice_recognition_accuracy": 96.8,
            "response_latency_ms": 200,
            "languages": ["en", "ha", "yo", "ig"]
        }
    },
    "network": {
        "name": "Secure Network Infrastructure",
        "status": "operational",
        "details": {
            "vpn_tunnels_active": 12,
            "bandwidth_used_pct": 43.7,
            "encryption": "AES-256-GCM",
            "last_security_scan": "2026-03-17T06:00:00Z",
            "intrusion_attempts_blocked_24h": 47
        }
    },
    "compute_cluster": {
        "name": "Jetson AGX Orin Cluster",
        "status": "operational",
        "details": {
            "nodes": 5,
            "nodes_active": 5,
            "gpu_utilization_pct": 58.3,
            "inference_throughput_fps": 147.2,
            "temperature_avg_celsius": 62
        }
    }
}

def system_status(subsystem: str = None) -> dict:
    """Check health status of AnSA subsystems.

    Args:
        subsystem: Specific subsystem to check. Options: cameras, biometric_db,
                   nimc_link, avis, network, compute_cluster. If None, returns all.

    Returns:
        Dict with subsystem health status and details
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if subsystem:
        subsystem = subsystem.lower().replace(" ", "_").replace("-", "_")
        if subsystem not in SUBSYSTEMS:
            return {
                "status": "error",
                "message": f"Unknown subsystem '{subsystem}'. Available: {list(SUBSYSTEMS.keys())}"
            }
        info = SUBSYSTEMS[subsystem]
        return {
            "status": "success",
            "timestamp": timestamp,
            "subsystem": subsystem,
            **info
        }

    # Return all subsystems
    all_operational = all(s["status"] == "operational" for s in SUBSYSTEMS.values())
    return {
        "status": "success",
        "timestamp": timestamp,
        "overall_status": "all_operational" if all_operational else "degraded",
        "subsystem_count": len(SUBSYSTEMS),
        "subsystems": {k: {"name": v["name"], "status": v["status"]} for k, v in SUBSYSTEMS.items()},
        "details": SUBSYSTEMS
    }

if __name__ == "__main__":
    result = system_status()
    print(json.dumps(result, indent=2))
