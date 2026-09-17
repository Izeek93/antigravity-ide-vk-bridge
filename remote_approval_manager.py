# -*- coding: utf-8 -*-
"""
vk-bot/remote_approval_manager.py
=================================
Тонкий адаптер-прокси к единому масштабируемому хабу shared_ai/approval_hub.py.
Гарантирует единый источник правды (pending_approval.json) между Telegram, VK и IDE.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "shared_ai"))
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)

from approval_hub import (
    request_remote_approval as _req,
    resolve_approval as _res,
    get_pending_approval as _get,
    wait_for_approval_decision as _wait
)

def request_remote_approval(action_description: str, timeout_sec: float = 90.0) -> dict:
    return _req(action_description, timeout_sec)

def resolve_approval(decision: bool, platform: str = "vkontakte", user: str = "vk_user") -> bool:
    return _res(decision, platform=platform, user=user)

def get_pending_approval() -> dict:
    return _get()

def wait_for_approval_decision(timeout_sec: float = 90.0) -> bool:
    return _wait(timeout_sec)
