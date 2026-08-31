import os
import sys
import json
import time
import urllib.request
import traceback

RECEIVER_URL = "http://127.0.0.1:8080/incident"

def report_bridge_incident(service_name: str, error_msg: str, tb: str = None) -> bool:
    """
    Instantly notifies Antigravity IDE agent about an unhandled bridge error
    so the AI can automatically diagnose, fix, and restart the service without user intervention.
    """
    if tb is None:
        tb = traceback.format_exc()
        
    incident_payload = {
        "type": "CRITICAL_INCIDENT",
        "service": service_name,
        "error": str(error_msg),
        "traceback": str(tb),
        "timestamp": time.time()
    }
    
    # Print clearly to console
    print(f"\n🚨 [INCIDENT DETECTED in {service_name}]: {error_msg}\n{tb}\n", flush=True)
    
    # Hit IDE receiver trigger
    try:
        data = json.dumps(incident_payload).encode("utf-8")
        req = urllib.request.Request(
            RECEIVER_URL,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return True
    except Exception:
        incidents_file = os.path.join(os.path.dirname(__file__), "incidents.json")
        try:
            incidents = []
            if os.path.exists(incidents_file):
                with open(incidents_file, "r", encoding="utf-8") as f:
                    incidents = json.load(f)
            incidents.append(incident_payload)
            with open(incidents_file, "w", encoding="utf-8") as f:
                json.dump(incidents, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
            
    return False
