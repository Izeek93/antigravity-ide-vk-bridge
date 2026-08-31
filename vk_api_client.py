import os
import sys
import json
import time
import random
import urllib.request
import urllib.parse
from pathlib import Path
from config import VK_GROUP_TOKEN, VK_API_VERSION

API_BASE = "https://api.vk.com/method/"

def call_api(method: str, params: dict = None, token: str = None) -> dict:
    if params is None:
        params = {}
    if token is None:
        token = VK_GROUP_TOKEN
    params["access_token"] = token
    if "v" not in params:
        params["v"] = VK_API_VERSION
    
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(API_BASE + method, data=data)
    with urllib.request.urlopen(req, timeout=15) as response:
        res = json.loads(response.read().decode("utf-8"))
        if "error" in res:
            raise RuntimeError(f"VK API Error ({method}): {res['error']}")
        return res.get("response", {})

def send_message(user_id: int, text: str, keyboard: dict = None, attachment: str = None) -> int:
    params = {
        "user_id": user_id,
        "random_id": random.randint(1, 2147483647),
        "message": text,
    }
    if keyboard:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
    if attachment:
        params["attachment"] = attachment
    return call_api("messages.send", params)

def set_activity(user_id: int, activity_type: str = "typing"):
    try:
        call_api("messages.setActivity", {
            "user_id": user_id,
            "type": activity_type
        })
    except Exception:
        pass

def upload_photo(user_id: int, photo_path: str) -> str:
    """Uploads a photo to VK messages server and returns attachment string 'photo{owner_id}_{id}'"""
    upload_server = call_api("photos.getMessagesUploadServer", {"peer_id": user_id})
    upload_url = upload_server["upload_url"]

    # Multipart upload
    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(photo_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{os.path.basename(photo_path)}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(upload_url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_resp = json.loads(r.read().decode("utf-8"))

    # Save messages photo
    save_resp = call_api("photos.saveMessagesPhoto", {
        "photo": upload_resp["photo"],
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
    })
    saved = save_resp[0]
    return f"photo{saved['owner_id']}_{saved['id']}"

def upload_audiomessage(user_id: int, audio_path: str) -> str:
    """Uploads voice note (audiomessage / doc) to VK messages server and returns 'doc{owner_id}_{id}'"""
    upload_server = call_api("docs.getMessagesUploadServer", {
        "peer_id": user_id,
        "type": "audio_message"
    })
    upload_url = upload_server["upload_url"]

    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(audio_path)}"\r\n'
        f"Content-Type: audio/ogg\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(upload_url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_resp = json.loads(r.read().decode("utf-8"))

    save_resp = call_api("docs.save", {
        "file": upload_resp["file"]
    })
    audio_doc = save_resp["audio_message"]
    return f"doc{audio_doc['owner_id']}_{audio_doc['id']}"
