"""
vk-bot/incident_manager.py
===========================
Менеджер критических инцидентов VK моста.
Записывает инциденты напрямую в локальный файл incidents.json
для последующего подхвата приёмником bridge_receiver.py.
"""

import os
import json
import time
import traceback


def report_bridge_incident(service_name: str, error_msg: str, tb: str = None) -> bool:
    """
    Фиксирует критический инцидент моста в incidents.json.
    Приёмник bridge_receiver.py подхватит его при следующем цикле polling.
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

    # Print to console for immediate visibility
    print(f"\n🚨 [INCIDENT DETECTED in {service_name}]: {error_msg}\n{tb}\n", flush=True)

    # Write directly to local incidents.json
    incidents_file = os.path.join(os.path.dirname(__file__), "incidents.json")
    try:
        incidents = []
        if os.path.exists(incidents_file):
            with open(incidents_file, "r", encoding="utf-8") as f:
                incidents = json.load(f)
        incidents.append(incident_payload)
        with open(incidents_file, "w", encoding="utf-8") as f:
            json.dump(incidents, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        pass

    return False
